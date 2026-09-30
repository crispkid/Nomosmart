"""Durable admission, unique Celery task claims and cooperative finalization.

No broker or runtime operations occur under these transactions. Crash recovery
never treats an expired lease as task completion. Callers commit before dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import re
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentVersion, FileProcessingExecution as Execution, FileProcessingTask as Task, OutboxEvent, PipelineRun, PipelineRunStep, Project
from app.domain.document_execution import _locked, begin_execution, claim_execution, release_execution, transition_execution
from app.domain.file_processing_settings import PlatformCapabilities, load_policy, policy_error

TOPIC = "document.extraction.requested"


def configured_capabilities(settings) -> PlatformCapabilities:
    try:
        maxima = json.loads(settings.file_processing_capabilities_json)
    except (ValueError, TypeError) as exc:
        raise policy_error("file_processing_capability_invalid", 503) from exc
    if not isinstance(maxima, dict):
        raise policy_error("file_processing_capability_invalid", 503)
    return PlatformCapabilities(maxima)


@dataclass(frozen=True)
class Dispatch:
    task_id: UUID
    broker_task_id: UUID
    execution_id: UUID
    generation: UUID
    run_id: UUID


@dataclass(frozen=True)
class Claim:
    task_id: UUID
    claim_token: UUID
    execution_id: UUID
    generation: UUID
    run_id: UUID


def _current_scope(session: Session, execution: Execution) -> bool:
    # Read fresh scalar columns without refreshing/discarding pending business
    # changes on the ORM objects used by the extraction step in this session.
    return session.scalar(select(PipelineRun.id)
        .join(DocumentVersion, PipelineRun.document_version_id == DocumentVersion.id)
        .join(Document, PipelineRun.document_id == Document.id)
        .join(Project, PipelineRun.project_id == Project.id)
        .where(PipelineRun.id == execution.run_id,
            DocumentVersion.id == execution.document_version_id,
            DocumentVersion.document_id == Document.id, Document.project_id == Project.id,
            Project.status == "active", Document.is_deleted.is_(False),
            Project.work_generation == execution.project_generation,
            PipelineRun.project_generation == execution.project_generation,
            DocumentVersion.content_sha256 == execution.input_hash)) is not None


def prepare_dispatch(session: Session, *, run_id: UUID, capabilities: PlatformCapabilities) -> Dispatch | None:
    # The existing authorized retry endpoint increments step retry counts. It is
    # the provenance for a new document attempt, never a boolean from a message.
    previous = session.scalar(select(Execution).where(Execution.run_id == run_id, Execution.kind == "document")
                              .order_by(Execution.attempt.desc()).limit(1))
    run = session.get(PipelineRun, run_id)
    retry_authorized = False
    if previous is not None and previous.released_at is not None:
        last = session.scalar(select(Task).where(Task.execution_id == previous.id, Task.state == "finalized")
                              .order_by(Task.finished_at.desc()).limit(1))
        old_count = (last.completion_receipt or {}).get("step_retry_count") if last else None
        retry_authorized = bool(previous.state == "failed" and run and run.status == "queued"
            and type(old_count) is int and _retry_count(session, run_id) > old_count)
    admission = claim_execution(session, run_id=run_id, kind="document", capabilities=capabilities,
                                retry_authorized=retry_authorized)
    if admission is None:
        return None
    execution = _locked(session, admission.execution_id, admission.generation)
    if execution.state not in {"reserved", "running"} or not _current_scope(session, execution):
        return None
    task = session.scalar(select(Task).where(Task.execution_id == execution.id, Task.finished_at.is_(None))
                          .with_for_update().execution_options(populate_existing=True))
    if task is None:
        now = datetime.now(UTC)
        task = Task(id=uuid4(), execution_id=execution.id, generation=execution.generation,
                    broker_task_id=uuid4(), state="prepared", created_at=now, updated_at=now)
        session.add(task)
        session.flush()
    if task.state != "prepared":
        return None
    return Dispatch(task.id, task.broker_task_id, execution.id, execution.generation, execution.run_id)


def _retry_count(session: Session, run_id: UUID) -> int:
    return sum(session.scalars(select(PipelineRunStep.retry_count).where(PipelineRunStep.run_id == run_id)))


def claim_task(session: Session, *, task_id: UUID, generation: UUID, broker_task_id: UUID, worker_identity: str) -> Claim | None:
    candidate = session.get(Task, task_id)
    if candidate is None or candidate.generation != generation or candidate.broker_task_id != broker_task_id:
        return None
    execution = _locked(session, candidate.execution_id, generation)
    task = session.scalar(select(Task).where(Task.id == task_id).with_for_update().execution_options(populate_existing=True))
    if task.state != "prepared" or execution.state not in {"reserved", "running"}:
        return None
    if not isinstance(worker_identity, str) or not re.fullmatch(r"[A-Za-z0-9_.:@/-]{1,255}", worker_identity):
        raise policy_error("file_processing_worker_identity_invalid")
    # Claim before checking scope: even a stale dispatched task needs a known owner
    # to record quiescence without launching any business work.
    if execution.state == "reserved" and not begin_execution(session, execution_id=execution.id, generation=generation):
        return None
    now = datetime.now(UTC)
    task.state, task.claim_token = "claimed", uuid4()
    task.worker_identity = worker_identity
    task.updated_at = task.heartbeat_at = now
    return Claim(task.id, task.claim_token, execution.id, generation, execution.run_id)


def require_claim(session: Session, claim: Claim, *, check_scope: bool = True) -> Execution:
    execution = _locked(session, claim.execution_id, claim.generation)
    task = session.scalar(select(Task).where(Task.id == claim.task_id).with_for_update().execution_options(populate_existing=True))
    if (task is None or task.execution_id != execution.id or task.generation != execution.generation
            or task.state != "claimed" or task.claim_token != claim.claim_token
            or task.finished_at is not None or execution.state != "running"):
        raise policy_error("file_processing_task_fenced")
    if check_scope and not _current_scope(session, execution):
        raise policy_error("file_processing_scope_stale")
    task.heartbeat_at = execution.heartbeat_at = datetime.now(UTC)
    return execution


def quiesce_task(session: Session, claim: Claim, *, disposition: str) -> None:
    """Trusted task epilogue only, after closing all work. Revokes its capability."""
    execution = require_claim(session, claim, check_scope=False)
    task = session.get(Task, claim.task_id)
    if disposition not in {"completed", "failed", "cancelled", "yield"}:
        raise policy_error("file_processing_disposition_invalid")
    run = session.get(PipelineRun, execution.run_id, populate_existing=True)
    if disposition == "completed" and run.status != "submission_ready":
        raise policy_error("file_processing_document_not_complete")
    if disposition == "failed" and run.status != "failed":
        raise policy_error("file_processing_document_not_failed")
    if disposition == "yield" and run.status not in {"running", "queued"}:
        raise policy_error("file_processing_yield_not_allowed")
    if disposition == "cancelled" and _current_scope(session, execution) and run.status != "cancelled":
        raise policy_error("file_processing_cancel_not_confirmed")
    now = datetime.now(UTC)
    task.completion_receipt = {"task_id": str(task.id), "execution_id": str(execution.id),
        "generation": str(execution.generation), "claim_token": str(task.claim_token),
        "disposition": disposition, "source": "claimant_epilogue_v1", "body_quiesced_at": now.isoformat(),
        "step_retry_count": _retry_count(session, execution.run_id)}
    task.disposition, task.updated_at = disposition, now
    if _occupied_child(session, execution.id):
        # The caller has closed its own business calls/heartbeat, not proved that
        # the independent parser stopped. Persist only the former observation.
        task.state = "recovery_required"
        transition_execution(session, execution_id=execution.id, generation=execution.generation,
                             state="recovery_required", error_code="parser_stop_unconfirmed")
        return
    task.completion_receipt = {**task.completion_receipt, "quiesced_at": now.isoformat()}
    task.state, task.disposition, task.updated_at = "quiescent", disposition, now
    execution.phase = "waiting_worker" if disposition == "yield" else "stopping"
    execution.updated_at = now


def _occupied_child(session: Session, execution_id: UUID) -> bool:
    return session.scalar(select(Execution.id).where(
        Execution.parent_id == execution_id, Execution.released_at.is_(None)).limit(1)) is not None


def finalizable_task_ids(session: Session) -> list[UUID]:
    """Scheduling hint only; finalization rechecks identity and children locked."""
    children = select(Execution.id).where(Execution.parent_id == Task.execution_id,
        Execution.released_at.is_(None)).exists()
    recovery = and_(Task.state == "recovery_required",
        Task.disposition.in_(("completed", "failed", "cancelled")),
        Task.completion_receipt["source"].astext == "claimant_epilogue_v1",
        Task.completion_receipt["body_quiesced_at"].astext.is_not(None))
    return list(session.scalars(select(Task.id).where(
        or_(Task.state == "quiescent", recovery), ~children, Task.finished_at.is_(None))
        .order_by(Task.updated_at, Task.id).limit(20)))


def _valid_epilogue_time(value, task: Task) -> bool:
    try:
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else None
        return (stamp is not None and stamp.tzinfo is not None
                and task.created_at <= stamp <= datetime.now(UTC))
    except (ValueError, TypeError):
        return False


def finalize_task(session: Session, task_id: UUID) -> bool:
    candidate = session.get(Task, task_id)
    if candidate is None or candidate.state not in {"quiescent", "recovery_required"}:
        return False
    # Two dispatchers may select the same hint. Serialize first and refresh it
    # before _locked rejects an execution already released by the other finisher.
    load_policy(session, lock=True)
    candidate = session.get(Task, task_id, populate_existing=True)
    if candidate is None or candidate.state not in {"quiescent", "recovery_required"}:
        return False
    execution = _locked(session, candidate.execution_id, candidate.generation)
    task = session.scalar(select(Task).where(Task.id == task_id).with_for_update().execution_options(populate_existing=True))
    if task.state not in {"quiescent", "recovery_required"} or task.finished_at is not None:
        return False
    receipt = task.completion_receipt or {}
    recovery = task.state == "recovery_required"
    if recovery and (task.disposition == "yield" or not receipt):
        return False  # An unknown crash or suspended task is not an epilogue.
    expected = {"task_id": str(task.id), "execution_id": str(execution.id), "generation": str(execution.generation),
                "claim_token": str(task.claim_token), "disposition": task.disposition}
    if (type(receipt) is not dict or task.claim_token is None
            or task.disposition not in {"completed", "failed", "cancelled", "yield"}
            or any(receipt.get(key) != value for key, value in expected.items())
            or type(receipt.get("step_retry_count")) is not int or receipt["step_retry_count"] < 0):
        raise policy_error("file_processing_completion_receipt_invalid")
    if recovery:
        if (execution.state != "recovery_required" or receipt.get("source") != "claimant_epilogue_v1"
                or not _valid_epilogue_time(receipt.get("body_quiesced_at"), task)
                or "quiesced_at" in receipt):
            raise policy_error("file_processing_completion_receipt_invalid")
    elif not _valid_epilogue_time(receipt.get("quiesced_at"), task):
        raise policy_error("file_processing_completion_receipt_invalid")
    if _occupied_child(session, execution.id):
        if recovery:
            return False
        raise policy_error("file_processing_child_still_occupied")
    run_status = session.scalar(select(PipelineRun.status).where(PipelineRun.id == execution.run_id))
    old_retry_count = receipt.get("step_retry_count")
    authorized_pending_retry = (run_status == "queued" and type(old_retry_count) is int
        and _retry_count(session, execution.run_id) > old_retry_count)
    if task.disposition == "failed" and run_status != "failed" and not authorized_pending_retry:
        raise policy_error("file_processing_document_not_failed")
    if task.disposition == "cancelled" and _current_scope(session, execution) and run_status != "cancelled":
        raise policy_error("file_processing_cancel_not_confirmed")
    if recovery:
        task.completion_receipt = {**receipt, "quiesced_at": datetime.now(UTC).isoformat()}
    if task.disposition == "yield":
        if run_status not in {"queued", "running"}:
            raise policy_error("file_processing_yield_not_allowed")
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.topic == TOPIC,
            OutboxEvent.aggregate_id == execution.run_id).with_for_update())
        if event is None:
            raise policy_error("file_processing_outbox_missing")
        event.status, event.available_at, event.processed_at = "pending", (
            datetime.now(UTC) + timedelta(seconds=execution.policy_snapshot["pdf_parser_retry_delay_seconds"])), None
        event.task_id = None
        event.claim_token = event.claimed_at = event.lease_expires_at = None
        event.last_error = None
    else:
        if execution.state != "stopping":
            transition_execution(session, execution_id=execution.id, generation=execution.generation, state="stopping")
            # Sessions disable autoflush. release_execution refreshes the locked
            # row, so persist this transition before it validates the new state.
            session.flush()
        release_execution(session, execution_id=execution.id, generation=execution.generation,
            terminal=task.disposition, stop_evidence={"source": "worker", "generation": str(execution.generation),
                "stopped": True, "cleanup_confirmed": True})
    task.state = "finalized"
    task.finished_at = task.updated_at = datetime.now(UTC)
    return True


def mark_stale_tasks(session: Session, *, stale_seconds: int) -> int:
    """Fence further commits on uncertainty, but never release/retry unknown work."""
    if type(stale_seconds) is not int or stale_seconds < 30:
        raise policy_error("file_processing_heartbeat_policy_invalid")
    threshold = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    candidates = list(session.scalars(select(Task.id).where(Task.state == "claimed",
        Task.heartbeat_at < threshold).order_by(Task.heartbeat_at).limit(20)))
    count = 0
    for task_id in candidates:
        candidate = session.get(Task, task_id)
        execution = _locked(session, candidate.execution_id, candidate.generation)
        task = session.scalar(select(Task).where(Task.id == task_id).with_for_update().execution_options(populate_existing=True))
        if task.state != "claimed" or task.heartbeat_at is None or task.heartbeat_at >= threshold:
            continue
        task.state, task.updated_at = "recovery_required", datetime.now(UTC)
        if execution.state != "recovery_required":
            transition_execution(session, execution_id=execution.id, generation=execution.generation,
                state="recovery_required", error_code="worker_heartbeat_expired")
        count += 1
    return count
