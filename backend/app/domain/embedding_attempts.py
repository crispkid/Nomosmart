"""Durable dispatch fence for manual chunk reconciliation only."""
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.config import get_settings
from app.db.models import AIModel, DocumentVersion, Project

UNKNOWN_CODE = "embedding_build_provider_result_unknown"
STOP_PHASES = frozenset({"prepared", "dispatched", "unknown", "usage_unconfirmed"})


def artifact_metadata(version: DocumentVersion) -> dict:
    value = (version.chunk_strategy or {}).get("chunk_artifacts")
    return dict(value) if isinstance(value, dict) else {}


def attempt_metadata(version: DocumentVersion) -> dict:
    value = artifact_metadata(version).get("embedding_attempt")
    return dict(value) if isinstance(value, dict) else {}


def attempt_stop_code(version: DocumentVersion) -> str | None:
    attempt = attempt_metadata(version)
    if attempt.get("phase") in STOP_PHASES:
        return "model_usage_persistence_unconfirmed" if attempt["phase"] == "usage_unconfirmed" else UNKNOWN_CODE
    return None


def attempt_block_reason(version: DocumentVersion) -> str | None:
    attempt = attempt_metadata(version)
    if attempt.get("phase") in {"prepared", "dispatched"}:
        try:
            if datetime.now(UTC) < datetime.fromisoformat(attempt["deadline_at"]):
                return "embedding_build_in_progress"
        except (KeyError, TypeError, ValueError):
            pass
    return attempt_stop_code(version)


def require_no_pending_embedding_attempt(version: DocumentVersion) -> None:
    code = attempt_block_reason(version)
    if code:
        raise AppError(code, "The previous embedding attempt must be reconciled before editing", status_code=409,
                       details={"automatic_retry_allowed": False})


def begin_embedding_attempt(session: Session, project: Project, version: DocumentVersion,
                            model: AIModel, fingerprint: str) -> dict:
    """Caller holds governance locks; commit the intent before any dispatch."""
    metadata = artifact_metadata(version)
    prior = attempt_metadata(version)
    if prior:
        # A redelivery without a completed matching build never starts again.
        raise AppError(attempt_stop_code(version) or metadata.get("error_code") or UNKNOWN_CODE,
                       "Embedding attempt cannot be automatically replayed", status_code=409,
                       details={"automatic_retry_allowed": False})
    from app.domain.embeddings import _timeout
    deadline = datetime.now(UTC) + timedelta(seconds=_timeout(model.config or {}, default=60) + 2 * get_settings().model_usage_write_timeout_seconds)
    attempt = {"attempt_id": str(uuid4()), "revision": version.lock_version,
               "project_generation": project.work_generation, "embedding_model_id": str(model.id),
               "model_config_version": model.config_version, "input_fingerprint": fingerprint,
               "phase": "prepared", "started_at": datetime.now(UTC).isoformat(), "deadline_at": deadline.isoformat()}
    version.chunk_strategy = {**(version.chunk_strategy or {}), "chunk_artifacts": {
        **metadata, "embedding_attempt": attempt}}
    # This commit releases governance row locks so the independent usage writer
    # can take FK key-share locks without waiting on this transaction.
    session.commit()
    return attempt


def mark_embedding_dispatched(session: Session, version: DocumentVersion, model: AIModel,
                               attempt: dict, chunk_ids: list[UUID]) -> None:
    from app.domain.chunk_artifacts import lock_chunk_write_scope, _active_chunks
    project, document, current = lock_chunk_write_scope(session, version, allow_pending_attempt=True)
    session.refresh(model)
    if (current is None or project is None or document is None or project.status != "active"
        or document.is_deleted or document.status == "deleted" or current.lock_version != attempt["revision"]
        or project.work_generation != attempt["project_generation"]
        or not model.is_active or model.deleted_at is not None or model.config_version != attempt["model_config_version"]
        or attempt_metadata(current).get("attempt_id") != attempt["attempt_id"]
        or attempt_metadata(current).get("phase") != "prepared"
        or [chunk.id for chunk in _active_chunks(session, current.id)] != chunk_ids):
        session.rollback()
        raise AppError("embedding_dispatch_scope_changed", "Embedding dispatch scope changed", status_code=409)
    metadata = artifact_metadata(current)
    current.chunk_strategy = {**(current.chunk_strategy or {}), "chunk_artifacts": {
        **metadata, "embedding_attempt": {**attempt, "phase": "dispatched"}}}
    session.commit()


def finish_embedding_attempt(session: Session, version_id: UUID, attempt: dict, phase: str,
                             *, error_code: str | None = None, build_id: UUID | None = None) -> bool:
    from app.domain.chunk_artifacts import lock_chunk_write_scope
    version = session.get(DocumentVersion, version_id)
    if version is None:
        return False
    _project, _document, current = lock_chunk_write_scope(session, version, allow_pending_attempt=True)
    if current is None:
        return False
    metadata = artifact_metadata(current)
    recorded = attempt_metadata(current)
    if recorded.get("attempt_id") != attempt["attempt_id"] or current.lock_version != attempt["revision"]:
        return False
    finished = {**recorded, "phase": phase, "finished_at": datetime.now(UTC).isoformat()}
    if build_id:
        finished["embedding_build_id"] = str(build_id)
    current.chunk_strategy = {**(current.chunk_strategy or {}), "chunk_artifacts": {
        **metadata, "embedding_attempt": finished, "error_code": error_code,
        "status": "running" if phase == "completed" else "failed"}}
    return True
