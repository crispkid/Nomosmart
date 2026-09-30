"""Durable two-pool admission and fenced progress. Never infer stop from a lease.

This module does not start a runtime or call a provider. Callers commit the intent
before creating a workload, and pass verified lifecycle evidence on completion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentVersion, FileProcessingExecution as Execution, FileProcessingPool, PipelineRun, Project
from app.domain.file_processing_settings import FileProcessingSettings, PlatformCapabilities, load_policy, policy_error


ACTIVE_STATES = frozenset({"reserved", "starting", "running", "stopping", "recovery_required"})
TRANSITIONS = {
    "reserved": {"starting", "running", "stopping", "recovery_required"},
    "starting": {"running", "stopping", "recovery_required"},
    "running": {"stopping", "recovery_required"},
    "stopping": {"recovery_required"},
    "recovery_required": {"stopping"},
}
PHASES = frozenset({"queued", "starting_parser", "parsing", "waiting_worker", "processing", "stopping", "recovery_required"})


@dataclass(frozen=True)
class Admission:
    execution_id: UUID
    generation: UUID
    created: bool


def _pool(session: Session, kind: str) -> None:
    if kind not in {"document", "parser"}:
        raise policy_error("file_processing_pool_invalid")
    if session.scalar(select(FileProcessingPool).where(FileProcessingPool.kind == kind).with_for_update()) is None:
        raise policy_error("file_processing_pool_missing", 503)


def _active(session: Session, run_id: UUID, kind: str) -> Execution | None:
    return session.scalar(select(Execution).where(Execution.run_id == run_id, Execution.kind == kind,
        Execution.released_at.is_(None)).execution_options(populate_existing=True).with_for_update())


def claim_execution(
    session: Session, *, run_id: UUID, kind: str, capabilities: PlatformCapabilities,
    parent_generation: UUID | None = None, retry_authorized: bool = False,
) -> Admission | None:
    policy = load_policy(session, lock=True)
    capabilities.validate(policy.settings)
    _pool(session, kind)
    current = _active(session, run_id, kind)
    if current:
        return Admission(current.id, current.generation, False)  # Not authority to run it again.
    recovery = session.scalar(select(Execution.id).where(Execution.kind == kind, Execution.released_at.is_(None),
        Execution.state == "recovery_required").limit(1))
    if recovery:
        return None
    occupied = session.scalar(select(func.count()).select_from(Execution).where(
        Execution.kind == kind, Execution.released_at.is_(None)))
    maximum = (policy.settings.document_processing_max_concurrent if kind == "document"
               else policy.settings.pdf_parser_max_concurrent)
    if occupied >= maximum:
        return None
    pipeline = session.get(PipelineRun, run_id)
    if pipeline is None or pipeline.document_version_id is None or pipeline.status not in {"queued", "running"}:
        raise policy_error("file_processing_run_not_admissible")
    version = session.get(DocumentVersion, pipeline.document_version_id)
    project = session.get(Project, pipeline.project_id)
    document = session.get(Document, pipeline.document_id) if pipeline.document_id else None
    if (version is None or project is None or project.status != "active" or document is None or document.is_deleted
            or version.document_id != document.id or document.project_id != project.id
            or pipeline.project_generation != project.work_generation):
        raise policy_error("file_processing_scope_stale")
    if not isinstance(version.content_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", version.content_sha256):
        raise policy_error("file_processing_input_identity_missing")
    parent = None
    if kind == "parser":
        parent = _active(session, run_id, "document")
        if parent is None or parent.generation != parent_generation or parent.state != "running":
            raise policy_error("file_processing_parent_stale")
        if parent.input_hash != version.content_sha256:
            raise policy_error("file_processing_input_changed")
    previous = session.scalar(select(Execution).where(Execution.run_id == run_id, Execution.kind == kind)
                              .order_by(Execution.attempt.desc()).limit(1))
    first_child_of_authorized_attempt = parent is not None and previous is not None and previous.parent_id != parent.id
    if previous is not None and not retry_authorized and not first_child_of_authorized_attempt:
        raise policy_error("file_processing_retry_requires_authorization")
    # Parser resource policy inherits the document attempt, not a mid-flight update.
    values = FileProcessingSettings.model_validate(parent.policy_snapshot) if parent else policy.settings
    capabilities.validate(values)
    now = datetime.now(UTC)
    row = Execution(
        id=uuid4(), run_id=run_id, document_version_id=version.id, kind=kind,
        parent_id=parent.id if parent else None, attempt=1 if previous is None else previous.attempt + 1,
        generation=uuid4(), deployment_id=policy.deployment_id, project_generation=project.work_generation,
        state="reserved", policy_revision=parent.policy_revision if parent else policy.revision,
        policy_snapshot=values.model_dump(mode="json"), policy_hash=values.content_hash,
        input_hash=version.content_sha256, phase="starting_parser" if kind == "parser" else "waiting_worker",
        progress_revision=0, completed_units=0, created_at=now, updated_at=now,
    )
    session.add(row)
    session.flush()
    return Admission(row.id, row.generation, True)


def _locked(session: Session, execution_id: UUID, generation: UUID) -> Execution:
    # Lock order matches settings updates, claims and releases.
    policy = load_policy(session, lock=True)
    row = session.get(Execution, execution_id)
    if row is None:
        raise policy_error("file_processing_execution_missing")
    _pool(session, row.kind)
    row = session.scalar(select(Execution).where(Execution.id == execution_id)
        .execution_options(populate_existing=True).with_for_update())
    if row.generation != generation or row.deployment_id != policy.deployment_id or row.released_at is not None:
        raise policy_error("file_processing_generation_stale")
    return row


def begin_execution(session: Session, *, execution_id: UUID, generation: UUID) -> bool:
    row = _locked(session, execution_id, generation)
    if row.state != "reserved":
        return False  # At-most-one worker may cross this durable start fence.
    now = datetime.now(UTC)
    row.state = "starting" if row.kind == "parser" else "running"
    row.phase = "starting_parser" if row.kind == "parser" else "processing"
    row.updated_at = row.heartbeat_at = now
    if row.kind == "parser":
        row.deadline_at = now + timedelta(seconds=row.policy_snapshot["pdf_parser_timeout_seconds"])
    return True


def bind_workload(session: Session, *, execution_id: UUID, generation: UUID,
                  workload_id: str, workload_uid: str, image_digest: str, profile: str) -> None:
    row = _locked(session, execution_id, generation)
    if row.kind != "parser" or row.state not in {"starting", "recovery_required"}:
        raise policy_error("file_processing_workload_state_invalid")
    if not all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.:/@-]{1,255}", v)
               for v in (workload_id, workload_uid, image_digest)) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", profile):
        raise policy_error("file_processing_workload_identity_invalid")
    if not re.search(r"sha256:[a-f0-9]{64}$", image_digest):
        raise policy_error("file_processing_image_unpinned")
    identity = (workload_id, workload_uid, image_digest, profile)
    existing = (row.workload_id, row.workload_uid, row.image_digest, row.profile)
    if row.workload_uid is not None and existing != identity:
        raise policy_error("file_processing_workload_identity_changed")
    row.workload_id, row.workload_uid, row.image_digest, row.profile = identity
    if row.state == "starting":
        row.state, row.phase = "running", "parsing"
    row.updated_at = datetime.now(UTC)


def bind_local_workload(session: Session, *, execution_id: UUID, generation: UUID,
                        worker_identity: str, worker_pid: int, launch_uid: str) -> None:
    row = _locked(session, execution_id, generation)
    if (row.kind != "parser" or row.state != "starting" or row.workload_uid is not None
            or not isinstance(worker_identity, str) or not re.fullmatch(r"[A-Za-z0-9_.:/@-]{1,160}", worker_identity)
            or type(worker_pid) is not int or worker_pid <= 0):
        raise policy_error("file_processing_workload_identity_invalid")
    try:
        if str(UUID(launch_uid)) != launch_uid:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise policy_error("file_processing_workload_identity_invalid") from None
    row.workload_id = f"{worker_identity}/{worker_pid}/{launch_uid}"
    row.workload_uid, row.profile, row.image_digest = launch_uid, "worker-local-v1", None
    row.state, row.phase, row.updated_at = "running", "parsing", datetime.now(UTC)
    session.flush()


def transition_execution(session: Session, *, execution_id: UUID, generation: UUID, state: str, error_code: str | None = None) -> None:
    row = _locked(session, execution_id, generation)
    if state not in TRANSITIONS[row.state]:
        raise policy_error("file_processing_transition_invalid")
    if error_code is not None and (not isinstance(error_code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", error_code)):
        raise policy_error("file_processing_error_code_invalid")
    row.state, row.updated_at = state, datetime.now(UTC)
    row.safe_error_code = error_code
    if state in {"stopping", "recovery_required"}:
        row.phase = state


def record_progress(session: Session, *, execution_id: UUID, generation: UUID, sequence: int,
                    phase: str, completed: int, total: int | None, unit: str | None) -> bool:
    row = _locked(session, execution_id, generation)
    if (type(sequence) is not int or sequence < 1 or phase not in PHASES or type(completed) is not int
            or completed < 0 or (total is not None and (type(total) is not int or total < completed))
            or unit not in {None, "pages", "steps"} or (unit is None and (completed != 0 or total is not None))):
        raise policy_error("file_processing_progress_invalid", 422)
    if sequence <= row.progress_revision:
        return False
    if row.state != "running" or phase != ("parsing" if row.kind == "parser" else "processing"):
        raise policy_error("file_processing_progress_state_invalid")
    if row.progress_revision and row.unit != unit:
        raise policy_error("file_processing_progress_unit_changed", 422)
    if row.unit == unit and (completed < row.completed_units or (row.total_units is not None and total != row.total_units)):
        raise policy_error("file_processing_progress_regression", 422)
    now = datetime.now(UTC)
    row.heartbeat_at = now
    interval = row.policy_snapshot["file_processing_progress_interval_seconds"]
    if row.progress_revision and (now - row.updated_at).total_seconds() < interval and completed != total:
        return False
    row.progress_revision, row.phase = sequence, phase
    row.completed_units, row.total_units, row.unit = completed, total, unit
    row.updated_at = now
    return True


def release_execution(session: Session, *, execution_id: UUID, generation: UUID, terminal: str,
                      stop_evidence: dict, output_evidence: dict | None = None) -> None:
    row = _locked(session, execution_id, generation)
    if terminal not in {"completed", "failed", "cancelled"} or row.state not in {"stopping", "recovery_required"}:
        raise policy_error("file_processing_release_state_invalid")
    # Evidence originates in the trusted lifecycle adapter, never a public API payload.
    if (type(stop_evidence) is not dict or stop_evidence.get("generation") != str(generation)
            or stop_evidence.get("stopped") is not True or stop_evidence.get("cleanup_confirmed") is not True):
        raise policy_error("file_processing_stop_not_confirmed")
    local = row.kind == "parser" and row.profile == "worker-local-v1"
    expected = "local_process" if local else "runtime" if row.kind == "parser" else "worker"
    if stop_evidence.get("source") != expected:
        raise policy_error("file_processing_stop_source_invalid")
    if row.kind == "parser":
        # A create attempt with lost response must be reconciled before absence is proven.
        if row.workload_uid is None or stop_evidence.get("workload_uid") != row.workload_uid:
            raise policy_error("file_processing_workload_stop_unproven")
        if local and (row.image_digest is not None or stop_evidence.get("all_children_reaped") is not True
                or type(stop_evidence.get("child_count")) is not int or not 0 <= stop_evidence["child_count"] <= 20000
                or type(stop_evidence.get("all_exits_zero")) is not bool
                or not re.fullmatch(r"[a-f0-9]{64}", str(stop_evidence.get("exit_codes_sha256", "")))
                or (terminal == "completed" and (not stop_evidence["all_exits_zero"] or stop_evidence["child_count"] < 1))):
            raise policy_error("file_processing_local_stop_unproven")
        if terminal == "completed" and (type(output_evidence) is not dict
                or output_evidence.get("input_hash") != row.input_hash
                or output_evidence.get("generation") != str(generation)
                or output_evidence.get("complete") is not True
                or not re.fullmatch(r"[a-f0-9]{64}", str(output_evidence.get("output_hash", "")))):
            raise policy_error("file_processing_output_unaccepted")
    elif session.scalar(select(Execution.id).where(Execution.parent_id == row.id, Execution.released_at.is_(None)).limit(1)):
        raise policy_error("file_processing_child_still_occupied")
    if row.kind == "document" and terminal == "completed":
        pipeline = session.get(PipelineRun, row.run_id, populate_existing=True)
        if pipeline.status != "submission_ready":
            raise policy_error("file_processing_document_not_complete")
    # Store a bounded allowlist, not arbitrary supplied logs/content.
    row.stop_evidence = {key: stop_evidence[key] for key in ("generation", "source", "stopped", "cleanup_confirmed")}
    if row.kind == "parser":
        row.stop_evidence = row.stop_evidence | {"workload_uid": row.workload_uid}
        if local:
            row.stop_evidence |= {key: stop_evidence[key] for key in
                ("child_count", "all_children_reaped", "exit_codes_sha256", "all_exits_zero")}
    if row.kind == "parser" and terminal == "completed":
        row.output_evidence = {key: output_evidence[key] for key in ("input_hash", "generation", "complete", "output_hash")}
    row.state = row.phase = terminal
    row.released_at = row.updated_at = datetime.now(UTC)
    session.flush()


def execution_projection(session: Session, run_id: UUID) -> dict | None:
    """Call only after the existing route's project/version authorization succeeds."""
    row = session.scalar(select(Execution).where(Execution.run_id == run_id)
        .order_by(Execution.created_at.desc(), Execution.id.desc()).limit(1))
    if row is None:
        return None
    document = session.get(Execution, row.parent_id) if row.parent_id else row
    if row.released_at is not None and document.released_at is None:
        row = document  # Parser completion is not document completion.
    return {"phase": row.phase, "attempt": row.attempt, "progress_revision": row.progress_revision,
            "updated_at": row.updated_at, "heartbeat_at": row.heartbeat_at,
            "completed_units": row.completed_units, "total_units": row.total_units, "unit": row.unit,
            "safe_error_code": row.safe_error_code,
            "poll_interval_seconds": row.policy_snapshot["file_processing_progress_interval_seconds"],
            "background_poll_interval_seconds": row.policy_snapshot["file_processing_background_poll_interval_seconds"]}


def release_operator_failed_parser(session: Session, *, execution_id: UUID, generation: UUID,
                                   evidence: dict, actor_id: UUID, scope_sha256: str) -> None:
    """FILEPROC-042: separate maintenance path, never synthetic local child evidence.

    The authenticated maintenance caller owns platform observation, exact-scope
    validation and the atomic parent finalization/audit transaction. No API uses
    this function. Ordinary release_execution deliberately keeps its old checks.
    """
    row = _locked(session, execution_id, generation)
    required = {"source", "scope_sha256", "generation", "workload_uid", "worker_uid",
                "node_uid", "node_container_id", "container_id", "started_at", "finished_at",
                "observed_at", "exit_code", "scratch_before_sha256", "scratch_absent",
                "runtime_stopped", "maintenance_sha256", "actor_id"}
    if (type(evidence) is not dict or set(evidence) != required
            or evidence["source"] != "operator_runtime_terminal_v1"
            or evidence["scope_sha256"] != scope_sha256 or evidence["actor_id"] != str(actor_id)
            or evidence["generation"] != str(generation) or evidence["workload_uid"] != row.workload_uid
            or row.kind != "parser" or row.profile != "worker-local-v1" or row.image_digest is not None
            or row.state != "recovery_required" or row.stop_evidence is not None or row.output_evidence is not None
            or evidence["runtime_stopped"] is not True or evidence["scratch_absent"] is not True
            or type(evidence["exit_code"]) is not int or evidence["exit_code"] != 0):
        raise policy_error("file_processing_operator_evidence_invalid")
    for key in ("worker_uid", "node_uid", "workload_uid", "actor_id", "generation"):
        try:
            if str(UUID(evidence[key])) != evidence[key]:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise policy_error("file_processing_operator_evidence_invalid") from None
    for key in ("scope_sha256", "container_id", "node_container_id", "scratch_before_sha256", "maintenance_sha256"):
        if not isinstance(evidence[key], str) or not re.fullmatch(r"[a-f0-9]{64}", evidence[key]):
            raise policy_error("file_processing_operator_evidence_invalid")
    try:
        started, finished, observed = (datetime.fromisoformat(evidence[k]) for k in
                                       ("started_at", "finished_at", "observed_at"))
        now = datetime.now(UTC)
        valid_time = (all(t.tzinfo is not None for t in (started, finished, observed))
                      and started <= row.created_at <= finished <= observed <= now
                      and (now - observed).total_seconds() <= 120)
    except (ValueError, TypeError):
        valid_time = False
    if (not valid_time or not row.workload_id
            or row.workload_id.split("/")[0] != evidence["worker_uid"]):
        raise policy_error("file_processing_operator_runtime_mismatch")
    row.stop_evidence = dict(evidence)
    row.state = row.phase = "failed"
    row.released_at = row.updated_at = datetime.now(UTC)
    session.flush()
