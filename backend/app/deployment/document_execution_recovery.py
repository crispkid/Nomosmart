"""Non-public REL426-022 CLI: recover one crashed document execution.

    python -m app.deployment.document_execution_recovery preview|commit

Private stdin JSON carries exactly one maintenance credential (session_cookie or
access_token) plus:
  preview: {"execution_id": "<uuid>"}
  commit:  {"scope": <scope returned by preview>,
            "confirmation": {"worker_identity": "<as shown>", "worker_stopped_confirmed": true}}

Eligible: a document execution left recovery_required by a worker that never
wrote its epilogue (heartbeat expired, no completion receipt). The worker's
claim is already fenced, so a lost worker cannot commit. The run, its in-flight
step and its version become failed; users retry through the existing retry API.
No token, receipt or document content is printed.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import sys
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import (AuditLog, DocumentVersion, FileProcessingExecution as Execution,
                           FileProcessingTask as Task, PipelineRun, PipelineRunStep)
from app.db.session import get_session_factory
from app.deployment.file_processing_recovery import Digest, digest, read_policy_snapshot, row_digest
from app.domain.document_execution import (OPERATOR_DOCUMENT_RECOVERY_SOURCE, _pool,
                                           release_operator_recovered_document)
from app.domain.document_interruption import INTERRUPTED_MESSAGE, mark_run_failed
from app.domain.file_processing_dispatch import _retry_count
from app.domain.file_processing_settings import authorize_maintenance, load_policy, policy_error
from app.security.maintenance_auth import maintenance_principal, validate_maintenance_input
from app.services.audit import add_audit

ACTION = "file_processing.document_execution.recovered"
REJECTED = "file_processing.document_execution.recovery_rejected"
ERROR_CODE = "document_execution_interrupted"


class RecoveryScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    execution_id: UUID
    generation: UUID
    deployment_id: UUID
    task_id: UUID
    run_id: UUID
    project_id: UUID
    worker_identity: str = Field(min_length=1, max_length=255)
    heartbeat_at: datetime
    step_names: tuple[str, ...]
    before_sha256: Digest
    actor_id: UUID

    @property
    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    worker_identity: str = Field(min_length=1, max_length=255)
    worker_stopped_confirmed: bool


def _rows(session, execution_id: UUID, *, lock: bool):
    def get(model, query):
        row = session.scalar((query.with_for_update() if lock else query).execution_options(populate_existing=True))
        if row is None:
            raise policy_error("document_execution_recovery_scope_missing")
        return row
    execution = get(Execution, select(Execution).where(Execution.id == execution_id))
    task = get(Task, select(Task).where(Task.execution_id == execution.id, Task.generation == execution.generation)
               .order_by(Task.created_at.desc()).limit(1))
    run = get(PipelineRun, select(PipelineRun).where(PipelineRun.id == execution.run_id))
    version = get(DocumentVersion, select(DocumentVersion).where(DocumentVersion.id == run.document_version_id))
    return execution, task, run, version


def _in_flight_steps(session, run_id: UUID) -> tuple[str, ...]:
    return tuple(session.scalars(select(PipelineRunStep.step_name).where(PipelineRunStep.run_id == run_id,
        (PipelineRunStep.status == "running") | PipelineRunStep.claim_token.is_not(None))
        .order_by(PipelineRunStep.step_name)))


def _eligible(session, execution, task, run, version, settings) -> None:
    lease = settings.ingestion_worker_lease_seconds
    if (execution.kind != "document" or execution.parent_id is not None or execution.state != "recovery_required"
            or execution.released_at is not None or execution.stop_evidence is not None
            or task.state != "recovery_required" or task.finished_at is not None or task.completion_receipt is not None
            or task.claim_token is None or not task.worker_identity
            or run.status not in {"queued", "running"} or version.id != execution.document_version_id):
        raise policy_error("document_execution_recovery_not_eligible")
    if task.heartbeat_at is None or task.heartbeat_at > datetime.now(UTC) - timedelta(seconds=lease):
        raise policy_error("document_execution_recovery_heartbeat_recent")
    if session.scalar(select(Execution.id).where(Execution.parent_id == execution.id,
                                                 Execution.released_at.is_(None)).limit(1)):
        raise policy_error("file_processing_child_still_occupied")


def preview(session, execution_id: UUID, actor: UUID, settings) -> dict:
    policy = read_policy_snapshot(session)
    execution, task, run, version = _rows(session, execution_id, lock=False)
    if execution.deployment_id != policy.deployment_id:
        raise policy_error("document_execution_recovery_scope_mismatch")
    _eligible(session, execution, task, run, version, settings)
    scope = RecoveryScope(execution_id=execution.id, generation=execution.generation, deployment_id=execution.deployment_id,
                          task_id=task.id, run_id=run.id, project_id=run.project_id, worker_identity=task.worker_identity,
                          heartbeat_at=task.heartbeat_at, step_names=_in_flight_steps(session, run.id),
                          before_sha256=row_digest(execution, task, run, version), actor_id=actor)
    return {"status": "eligible", "scope": scope.model_dump(mode="json"), "scope_sha256": scope.digest}


def _already_recovered(session, scope: RecoveryScope, execution, task) -> bool:
    proof = execution.stop_evidence or {}
    if proof.get("source") != OPERATOR_DOCUMENT_RECOVERY_SOURCE:
        return False
    audit = session.scalar(select(AuditLog).where(AuditLog.action == ACTION, AuditLog.resource_id == execution.id)
                           .order_by(AuditLog.created_at.desc()).limit(1))
    if (proof.get("scope_sha256") != scope.digest or execution.state != "failed" or execution.released_at is None
            or task.state != "finalized" or audit is None or audit.summary.get("scope_sha256") != scope.digest):
        raise policy_error("document_execution_recovery_already_changed")
    return True


def commit(session, scope: RecoveryScope, confirmation: Confirmation, actor: UUID, settings) -> dict:
    policy = load_policy(session, lock=True)  # Same lock order as every file-processing writer.
    _pool(session, "document")
    if actor != scope.actor_id or policy.deployment_id != scope.deployment_id:
        raise policy_error("document_execution_recovery_scope_mismatch")
    execution, task, run, version = _rows(session, scope.execution_id, lock=True)
    if (execution.generation != scope.generation or task.id != scope.task_id or run.id != scope.run_id
            or run.project_id != scope.project_id):
        raise policy_error("document_execution_recovery_scope_mismatch")
    if _already_recovered(session, scope, execution, task):
        return {"status": "already_recovered", "scope_sha256": scope.digest}
    if confirmation.worker_stopped_confirmed is not True:
        raise policy_error("document_execution_recovery_unconfirmed")
    if confirmation.worker_identity != task.worker_identity or scope.worker_identity != task.worker_identity:
        raise policy_error("document_execution_recovery_worker_mismatch")
    _eligible(session, execution, task, run, version, settings)
    if row_digest(execution, task, run, version) != scope.before_sha256:
        raise policy_error("document_execution_recovery_before_drift")
    now = datetime.now(UTC)
    mark_run_failed(session, run.id, message=INTERRUPTED_MESSAGE, error_code=ERROR_CODE)
    release_operator_recovered_document(session, execution_id=execution.id, generation=execution.generation, evidence={
        "source": OPERATOR_DOCUMENT_RECOVERY_SOURCE, "scope_sha256": scope.digest, "generation": str(execution.generation),
        "worker_identity": task.worker_identity, "worker_stopped_confirmed": True, "actor_id": str(actor)})
    # Same receipt shape as a claimant epilogue so the existing retry provenance
    # (prepare_dispatch: step_retry_count) authorizes the next attempt.
    task.completion_receipt = {"task_id": str(task.id), "execution_id": str(execution.id),
        "generation": str(execution.generation), "claim_token": str(task.claim_token), "disposition": "failed",
        "source": OPERATOR_DOCUMENT_RECOVERY_SOURCE, "scope_sha256": scope.digest,
        "quiesced_at": now.isoformat(), "step_retry_count": _retry_count(session, run.id)}
    task.disposition, task.state = "failed", "finalized"
    task.finished_at = task.updated_at = now
    add_audit(session, actor_user_id=actor, action=ACTION, resource_type="file_processing_execution",
              resource_id=execution.id, result="success", request_id=None,
              summary={"scope_sha256": scope.digest, "before_sha256": scope.before_sha256, "task_id": str(task.id),
                       "run_id": str(run.id), "worker_identity": task.worker_identity,
                       "step_names": list(scope.step_names)})
    session.flush()
    return {"status": "recovered_failed", "scope_sha256": scope.digest}


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("operation", choices=("preview", "commit"))
    args = cli.parse_args()
    actor = None
    factory = None
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise policy_error("file_processing_cli_input_limit", 422)
        payload = json.loads(raw)
        keys = {"execution_id"} if args.operation == "preview" else {"scope", "confirmation"}
        if type(payload) is not dict or set(payload) - {"access_token", "session_cookie"} != keys:
            raise policy_error("file_processing_cli_input_invalid", 422)
        validate_maintenance_input(payload)
        settings = get_settings()
        factory = get_session_factory()
        with factory.begin() as session:
            if args.operation == "preview":
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout='10s'"))
            session.execute(text("SET LOCAL lock_timeout='5s'"))
            principal = maintenance_principal(session, settings, payload)
            actor = authorize_maintenance(session, principal, write=True)
            if args.operation == "preview":
                result = preview(session, UUID(str(payload["execution_id"])), actor, settings)
            else:
                result = commit(session, RecoveryScope.model_validate(payload["scope"]),
                                Confirmation.model_validate(payload["confirmation"]), actor, settings)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, AppError) else (
            "file_processing_cli_input_invalid" if isinstance(exc, ValueError) else "document_execution_recovery_failed")
        if actor is not None and args.operation == "commit":
            try:
                with factory.begin() as session:
                    add_audit(session, actor_user_id=actor, action=REJECTED, resource_type="file_processing_execution",
                              resource_id=None, result="denied", request_id=None, summary={"safe_error_code": code})
            except Exception:
                code = "file_processing_rejection_audit_unavailable"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
