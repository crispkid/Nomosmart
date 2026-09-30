"""Non-public FILEPROC-042 CLI. Only private stdin carries the OIDC token.

    python -m app.deployment.file_processing_recovery preview|commit

The trusted operator command observes the real platform; this module verifies
identity, bounded evidence and exact DB scope. It cannot itself observe a node.
No token, claim receipt or document content is returned.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import sys
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, select, text

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import (AuditLog, Document, DocumentVersion, FileProcessingExecution as Execution,
                           FileProcessingTask as Task, FileProcessingPolicy, FileProcessingPolicyRevision,
                           IdentitySetting, PipelineRun, Project)
from app.db.session import get_session_factory
from app.domain.document_execution import _pool, release_operator_failed_parser
from app.domain.file_processing_dispatch import _retry_count, _valid_epilogue_time, finalize_task
from app.domain.file_processing_settings import (PolicySnapshot, _parameter_rows, _row_values, _validated,
                                                  authorize_maintenance, load_policy, policy_error)
from app.security.auth import build_identity_jwt_validator, is_token_revoked
from app.services.audit import add_audit

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Positive = Annotated[int, Field(strict=True, ge=1)]
ACTION = "file_processing.failed_worker.recovered"


class RecoveryScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_sha256: Digest
    before_sha256: Digest
    deployment_id: UUID
    policy_revision: Positive
    policy_sha256: Digest
    project_id: UUID
    project_generation: Positive
    run_id: UUID
    document_execution_id: UUID
    document_generation: UUID
    parser_execution_id: UUID
    parser_generation: UUID
    task_id: UUID
    broker_task_id: UUID
    launch_uid: UUID
    worker_uid: UUID
    worker_pid: Positive
    node_uid: UUID
    node_container_id: Digest
    container_id: Digest
    scratch_before_sha256: Digest
    actor_id: UUID

    @property
    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))


def digest(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def row_digest(*rows) -> str:
    # Includes the receipt for drift detection; only its one-way digest leaves DB.
    return digest([{c.key: getattr(row, c.key) for c in inspect(row).mapper.column_attrs} for row in rows])


def read_policy_snapshot(session):
    """Preview only: MVCC snapshot, not FOR SHARE (forbidden in READ ONLY).

    Verify the same catalog/history invariant as load_policy. The caller must
    use a repeatable-read, read-only transaction; commit still calls load_policy
    with its original exclusive lock. No existing policy writer is relaxed.
    """
    if (session.scalar(text("SHOW transaction_read_only")) != "on"
            or session.scalar(text("SHOW transaction_isolation")) != "repeatable read"):
        raise policy_error("file_processing_preview_transaction_invalid")
    row = session.get(FileProcessingPolicy, 1, populate_existing=True)
    if row is None:
        raise policy_error("file_processing_policy_missing", 503)
    values = _validated(_row_values(_parameter_rows(session)))
    history = session.get(FileProcessingPolicyRevision, row.revision, populate_existing=True)
    if (history is None or values.content_hash != row.content_hash or history.content_hash != row.content_hash
            or history.snapshot != values.model_dump(mode="json")):
        raise policy_error("file_processing_policy_revision_mismatch", 503)
    return PolicySnapshot(row.deployment_id, row.revision, values)


def check_scope(session, scope: RecoveryScope, actor: UUID, *, lock: bool):
    policy = load_policy(session, lock=True) if lock else read_policy_snapshot(session)
    if (actor != scope.actor_id or policy.deployment_id != scope.deployment_id
            or policy.revision != scope.policy_revision or policy.settings.content_hash != scope.policy_sha256):
        raise policy_error("file_processing_recovery_scope_stale")
    if lock:
        # All file-processing writers first serialize on the singleton policy.
        _pool(session, "document")
        _pool(session, "parser")

    def get(model, identity):
        query = select(model).where(model.id == identity).execution_options(populate_existing=True)
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise policy_error("file_processing_recovery_scope_missing")
        return row

    parent = get(Execution, scope.document_execution_id)
    parser = get(Execution, scope.parser_execution_id)
    task = get(Task, scope.task_id)
    run = get(PipelineRun, scope.run_id)
    project = get(Project, scope.project_id)
    document = get(Document, run.document_id)
    version = get(DocumentVersion, run.document_version_id)
    if (run.project_id != project.id or project.status != "active" or document.is_deleted
            or document.project_id != project.id or version.document_id != document.id
            or project.work_generation != scope.project_generation or run.project_generation != scope.project_generation
            or run.status != "failed" or parser.parent_id != parent.id or parser.kind != "parser" or parent.kind != "document"
            or parent.parent_id is not None or parent.generation != scope.document_generation
            or parser.generation != scope.parser_generation or task.execution_id != parent.id
            or task.generation != parent.generation or task.broker_task_id != scope.broker_task_id
            or task.disposition != "failed" or task.claim_token is None
            or parser.workload_uid != str(scope.launch_uid)
            or parser.workload_id != f"{scope.worker_uid}/{scope.worker_pid}/{scope.launch_uid}"
            or task.worker_identity != f"{scope.worker_uid}:{scope.worker_pid}"
            or parser.profile != "worker-local-v1" or parser.image_digest is not None):
        raise policy_error("file_processing_recovery_scope_mismatch")
    for row in (parent, parser):
        if (row.run_id != run.id or row.document_version_id != version.id or row.input_hash != version.content_sha256
                or row.deployment_id != scope.deployment_id or row.project_generation != scope.project_generation
                or row.policy_revision != scope.policy_revision or row.policy_hash != scope.policy_sha256):
            raise policy_error("file_processing_recovery_scope_mismatch")
    receipt = task.completion_receipt
    expected = {"source": "claimant_epilogue_v1", "task_id": str(task.id), "execution_id": str(parent.id),
                "generation": str(parent.generation), "claim_token": str(task.claim_token), "disposition": "failed"}
    if (type(receipt) is not dict or any(receipt.get(k) != v for k, v in expected.items())
            or not _valid_epilogue_time(receipt.get("body_quiesced_at"), task)
            or type(receipt.get("step_retry_count")) is not int
            or receipt["step_retry_count"] != _retry_count(session, run.id)):
        raise policy_error("file_processing_completion_receipt_invalid")
    audit = session.scalar(select(AuditLog).where(AuditLog.action == ACTION, AuditLog.resource_id == parser.id)
                           .order_by(AuditLog.created_at.desc()).limit(1))
    finalized = (parser.state == parent.state == "failed" and parser.released_at is not None
                 and parent.released_at is not None and task.state == "finalized" and task.finished_at is not None)
    if finalized:
        proof = parser.stop_evidence or {}
        if (proof.get("source") != "operator_runtime_terminal_v1" or proof.get("scope_sha256") != scope.digest
                or audit is None or audit.actor_user_id != actor or audit.summary.get("scope_sha256") != scope.digest
                or not _valid_epilogue_time(receipt.get("quiesced_at"), task)):
            raise policy_error("file_processing_recovery_already_changed")
        return parent, parser, task, run, True
    if (audit is not None or parser.state != "recovery_required" or parent.state != "recovery_required"
            or task.state != "recovery_required" or parser.released_at is not None or parent.released_at is not None
            or task.finished_at is not None or parser.stop_evidence is not None or parser.output_evidence is not None
            or parent.stop_evidence is not None or "quiesced_at" in receipt
            or row_digest(parent, parser, task, run) != scope.before_sha256):
        raise policy_error("file_processing_recovery_before_drift")
    if (set(session.scalars(select(Execution.id).where(Execution.released_at.is_(None)))) != {parent.id, parser.id}
            or set(session.scalars(select(Task.id).where(Task.finished_at.is_(None)))) != {task.id}):
        raise policy_error("file_processing_recovery_unknown_work")
    return parent, parser, task, run, False


def recover(session, scope: RecoveryScope, actor: UUID, evidence: dict):
    parent, parser, task, run, finalized = check_scope(session, scope, actor, lock=True)
    binding = {"scope_sha256": scope.digest, "generation": str(scope.parser_generation),
               "workload_uid": str(scope.launch_uid), "worker_uid": str(scope.worker_uid),
               "node_uid": str(scope.node_uid), "node_container_id": scope.node_container_id,
               "container_id": scope.container_id, "scratch_before_sha256": scope.scratch_before_sha256,
               "actor_id": str(actor)}
    if type(evidence) is not dict or any(evidence.get(k) != v for k, v in binding.items()):
        raise policy_error("file_processing_operator_runtime_mismatch")
    if finalized:
        # A repeat may refresh the observation time, but cannot change the proof.
        if {k:v for k,v in evidence.items() if k != "observed_at"} != {
                k:v for k,v in parser.stop_evidence.items() if k != "observed_at"}:
            raise policy_error("file_processing_recovery_evidence_changed")
        return {"status": "already_finalized", "scope_sha256": scope.digest}
    pipeline_digest = row_digest(run)
    release_operator_failed_parser(session, execution_id=parser.id, generation=parser.generation,
                                   evidence=evidence, actor_id=actor, scope_sha256=scope.digest)
    if not finalize_task(session, task.id):
        raise policy_error("file_processing_recovery_finalize_failed")
    session.flush()
    session.refresh(run)
    if row_digest(run) != pipeline_digest or parent.state != "failed" or task.state != "finalized":
        raise policy_error("file_processing_recovery_integrity_failed")
    add_audit(session, actor_user_id=actor, action=ACTION, resource_type="file_processing_execution",
              resource_id=parser.id, result="success", request_id=None,
              summary={"scope_sha256": scope.digest, "plan_sha256": scope.plan_sha256,
                       "before_sha256": scope.before_sha256, "source": evidence["source"],
                       "document_execution_id": str(parent.id), "task_id": str(task.id)})
    session.flush()
    return {"status": "finalized_failed", "scope_sha256": scope.digest}


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("operation", choices=("preview", "commit"))
    args = cli.parse_args()
    actor = None
    factory = None
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise policy_error("file_processing_cli_input_limit", 422)
        payload = json.loads(raw)
        keys = {"access_token", "scope"} | ({"evidence"} if args.operation == "commit" else set())
        if type(payload) is not dict or set(payload) != keys:
            raise policy_error("file_processing_cli_input_invalid", 422)
        token = payload["access_token"]
        if not isinstance(token, str) or not 1 <= len(token) <= 32768:
            raise policy_error("authentication_required", 401)
        scope = RecoveryScope.model_validate(payload["scope"])
        factory = get_session_factory()
        with factory.begin() as session:
            if args.operation == "preview":
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout='10s'"))
            session.execute(text("SET LOCAL lock_timeout='5s'"))
            identity = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
            principal = build_identity_jwt_validator(get_settings(), identity.configuration if identity else {}).validate(token)
            if is_token_revoked(session, principal, token):
                raise policy_error("token_revoked", 401)
            actor = authorize_maintenance(session, principal, write=True)
            if args.operation == "preview":
                *_, finalized = check_scope(session, scope, actor, lock=False)
                result = {"status": "already_finalized" if finalized else "eligible_failed_only",
                          "scope_sha256": scope.digest, "platform_proof": "not_checked_by_preview"}
            else:
                result = recover(session, scope, actor, payload["evidence"])
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, AppError) else "file_processing_recovery_failed"
        # Preview is strictly read-only, including rejected requests.
        if actor is not None and args.operation == "commit":
            try:
                with factory.begin() as session:
                    add_audit(session, actor_user_id=actor, action="file_processing.failed_worker.rejected",
                              resource_type="file_processing_execution", resource_id=None, result="denied",
                              request_id=None, summary={"safe_error_code": code})
            except Exception:
                code = "file_processing_rejection_audit_unavailable"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
