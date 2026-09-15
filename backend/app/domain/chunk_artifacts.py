from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Chunk, Document, DocumentVersion, EmbeddingBuild, OutboxEvent, Project
from app.domain.embeddings import embed_chunks
from app.domain.extraction_pipeline import LiveOpenSearchStagingIndexAdapter, _graph_preview_artifact
from app.domain.graph_reconciliation import clear_zero_candidate_chunks


ARTIFACT_METADATA_KEY = "chunk_artifacts"
RECONCILIATION_TOPIC = "chunk.artifacts.reconcile"


def lock_chunk_write_scope(session: Session, version: DocumentVersion) -> tuple[Project | None, Document | None, DocumentVersion | None]:
    """Enter before changing rows: governance parents precede the version fence.

    Do not autoflush a pending Version update ahead of its Project lock. Callers
    invoke this at entry, not after preparing mutations; refreshed rows are the
    authoritative scope after a wait. Authorization remains with the caller.
    """
    project_id, document_id, version_id = version.project_id, version.document_id, version.id
    with session.no_autoflush:
        project = session.scalar(select(Project).where(Project.id == project_id)
            .with_for_update().execution_options(populate_existing=True))
        document = session.scalar(select(Document).where(Document.id == document_id, Document.project_id == project_id)
            .with_for_update().execution_options(populate_existing=True))
        current = session.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id,
            DocumentVersion.project_id == project_id, DocumentVersion.document_id == document_id)
            .with_for_update().execution_options(populate_existing=True))
    return project, document, current


def chunk_artifact_state(version: DocumentVersion, active_chunk_count: int) -> tuple[str, bool, str | None]:
    if active_chunk_count == 0:
        return "chunks_required", False, "chunks_required"
    status = str(_metadata(version).get("status") or "")
    if status in {"queued", "running", "failed", "ready"}:
        return status, status == "ready", None if status == "ready" else "chunk_artifacts_not_ready"
    if version.status == "submission_ready":
        return "ready", True, None
    return "failed", False, "chunk_artifacts_not_ready"


def require_ready_chunk_artifacts(session: Session, version: DocumentVersion) -> None:
    count = len(_active_chunks(session, version.id))
    status, allowed, _reason = chunk_artifact_state(version, count)
    if count == 0:
        raise AppError("chunks_required", "At least one active chunk is required", status_code=409)
    if not allowed:
        raise AppError("chunk_artifacts_not_ready", "Chunk artifacts are not ready", status_code=409, details={"status": status})


def queue_chunk_artifact_reconciliation(session: Session, version: DocumentVersion, *, actor_user_id: UUID | None) -> OutboxEvent:
    chunks = _active_chunks(session, version.id)
    revision = version.lock_version
    current = _metadata(version)
    if int(current.get("revision") or -1) == revision and current.get("status") in {"queued", "running"}:
        existing_id = _uuid(current.get("outbox_event_id"))
        existing = session.get(OutboxEvent, existing_id) if existing_id else None
        if existing is not None:
            return existing
    now = datetime.now(UTC)
    project = session.scalar(select(Project).where(Project.id == version.project_id).with_for_update())
    if project is None or project.status != "active":
        raise AppError("project_archived", "Archived projects cannot reconcile chunk artifacts", status_code=409)
    event = OutboxEvent(
        id=uuid4(), topic=RECONCILIATION_TOPIC, aggregate_type="document_version", aggregate_id=version.id,
        project_id=version.project_id, project_generation=project.work_generation,
        payload={"document_version_id": str(version.id), "revision": revision, "project_id": str(version.project_id), "project_generation": project.work_generation}, status="pending", attempts=0,
        available_at=now, created_at=now,
    )
    session.add(event)
    version.chunk_strategy = {
        **(version.chunk_strategy or {}),
        ARTIFACT_METADATA_KEY: {
            "revision": revision,
            "status": "queued" if chunks else "chunks_required",
            "outbox_event_id": str(event.id),
            "requested_by": str(actor_user_id) if actor_user_id else None,
            "requested_at": now.isoformat(),
            "project_generation": project.work_generation,
            "error_code": None,
        },
    }
    for build in session.scalars(select(EmbeddingBuild).where(
        EmbeddingBuild.document_version_id == version.id,
        EmbeddingBuild.status.in_(("completed", "staged")),
    )):
        build.status = "invalidated"
    return event


def execute_chunk_artifact_reconciliation(session: Session, version_id: UUID, settings: Settings) -> None:
    version = session.get(DocumentVersion, version_id)
    if version is None:
        return
    project, document, version = lock_chunk_write_scope(session, version)
    if version is None:
        return
    initial_metadata = _metadata(version)
    revision = int(initial_metadata.get("revision") or version.lock_version)
    if revision != version.lock_version:
        return
    if initial_metadata.get("status") == "ready" or (initial_metadata.get("status") == "chunks_required" and initial_metadata.get("reconciled_at")):
        return
    if project is None or document is None or document.is_deleted or document.status == "deleted":
        _mark_failed(session, version, revision, "chunk_artifact_scope_missing")
        session.commit()
        return
    expected_generation = int(initial_metadata.get("project_generation") or 0)
    if project.status != "active" or project.work_generation != expected_generation:
        _mark_failed(session, version, revision, "project_archived")
        session.commit()
        return
    chunks = _active_chunks(session, version.id)
    expected_chunk_ids = [chunk.id for chunk in chunks]
    _set_status(version, revision, "running" if chunks else "chunks_required")
    session.flush()
    staging = LiveOpenSearchStagingIndexAdapter(settings)
    try:
        session.refresh(project)
        if project.status != "active" or project.work_generation != expected_generation:
            raise AppError("project_archived", "Archived projects cannot write chunk artifacts", status_code=409)
        if not chunks:
            clear_zero_candidate_chunks(session, settings, version)
            staging.delete_version(project_id=project.id, version_id=version.id)
            result = None
        else:
            batch = embed_chunks(session, project=project, version=version, chunks=chunks, settings=settings)
            result = staging.write_chunks(project=project, document=document, version=version, chunks=chunks, vectors=batch.vectors, profile=batch.profile)
            batch.build.status = "staged"
            batch.build.index_name = result.index_name
    except Exception as exc:  # noqa: BLE001 - store only a safe failure code
        session.rollback()
        # Reacquire the fence after rollback: a newer edit may have committed
        # while an external write failed. Never stamp its revision as failed.
        current = session.get(DocumentVersion, version_id)
        if current is not None:
            _project, _document, current = lock_chunk_write_scope(session, current)
        if current is not None and current.lock_version == revision:
            _mark_failed(session, current, revision, getattr(exc, "code", "chunk_artifact_reconciliation_failed"))
            session.commit()
        raise
    session.flush()
    session.expire(version)
    current = session.get(DocumentVersion, version_id)
    current_chunks = _active_chunks(session, version_id)
    session.refresh(project)
    if current is None or current.lock_version != revision or project.status != "active" or project.work_generation != expected_generation or [chunk.id for chunk in current_chunks] != expected_chunk_ids:
        session.rollback()
        return
    if current_chunks:
        current.extraction_artifact_uri = f"opensearch://{result.index_name}" if result is not None else None
        current.chunk_strategy = {**(current.chunk_strategy or {}), "graph_preview": _graph_preview_artifact(session, project, document, current, current_chunks)}
        _set_status(current, revision, "ready")
    else:
        current.extraction_artifact_uri = None
        current.embedding_model_id = None
        current.embedding_profile_id = None
        current.chunk_strategy = {**(current.chunk_strategy or {}), "graph_preview": _graph_preview_artifact(session, project, document, current, [])}
        _set_status(current, revision, "chunks_required")
    completed_metadata = _metadata(current)
    current.chunk_strategy = {**(current.chunk_strategy or {}), ARTIFACT_METADATA_KEY: {
        **completed_metadata, "reconciled_at": datetime.now(UTC).isoformat(),
    }}
    session.commit()


def _active_chunks(session: Session, version_id: UUID) -> list[Chunk]:
    return list(session.scalars(select(Chunk).where(
        Chunk.document_version_id == version_id, Chunk.status == "active",
    ).order_by(Chunk.chunk_index, Chunk.created_at)))


def _metadata(version: DocumentVersion) -> dict[str, Any]:
    value = (version.chunk_strategy or {}).get(ARTIFACT_METADATA_KEY)
    return dict(value) if isinstance(value, dict) else {}


def _set_status(version: DocumentVersion, revision: int, status: str) -> None:
    metadata = _metadata(version)
    if int(metadata.get("revision") or revision) != revision:
        return
    version.chunk_strategy = {**(version.chunk_strategy or {}), ARTIFACT_METADATA_KEY: {
        **metadata, "revision": revision, "status": status, "error_code": None,
        "updated_at": datetime.now(UTC).isoformat(),
    }}


def _mark_failed(session: Session, version: DocumentVersion, revision: int, error_code: str) -> None:
    metadata = _metadata(version)
    if int(metadata.get("revision") or revision) != revision:
        return
    version.chunk_strategy = {**(version.chunk_strategy or {}), ARTIFACT_METADATA_KEY: {
        **metadata, "revision": revision, "status": "failed", "error_code": error_code,
        "updated_at": datetime.now(UTC).isoformat(),
    }}
    session.flush()


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None
