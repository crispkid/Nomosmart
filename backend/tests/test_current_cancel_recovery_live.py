"""CHG-383: real retained work, real cancellation API, no producer replay."""
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.db.models import (ApprovalRequest, ApprovalTask, AuditLog, Document,
    DocumentVersion, EmbeddingBuild, PipelineRun, PipelineRunStep, Project,
    ProjectMember, ReviewRecord, User)
from app.db.session import get_session_factory
from app.domain.content_pipeline_evidence import current_pipeline, update_submission_state
from app.domain.extraction_pipeline import AUTO_EXTRACTION_STEPS, REVIEW_AND_PUBLICATION_STEPS
from app.domain.markdown_artifacts import resolve_markdown_artifact
from app.domain.review_publish import restore_cancelled_review_pipeline
from current_live_support import current_live, load_current_context
from scripts.current_e2e_governance_fixture import read_private


@pytest.fixture(scope="module")
def retained_work():
    context = load_current_context()
    source = Path(__file__).resolve().parents[2]
    approval = json.loads((source / "docs/CHG-383-APPROVAL.json").read_text())
    assert approval["approved_by"] == "Peter" and approval["gate_4"] == "APPROVED"
    assert sha256((source / approval["plan"]).read_bytes()).hexdigest() == approval["plan_sha256"]
    assert approval["original_run_uuid"] == context["run_id"]
    root = Path(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"]).parent.parent
    proof = read_private(root / "integration-switch-real-manifest/shared-draft-real-result.json")
    assert proof["run_uuid"] == context["run_id"] and proof["SQL_success_terminal_rows"] == 0
    old = json.loads((source / "docs/CHG-382-EVIDENCE/cancel-state-root-cause.json").read_text())
    assert old["run_uuid"] == context["run_id"]
    assert old["version_id"] == proof["candidate"]["version_id"]
    return context, dict(proof["candidate"]), old


@contextmanager
def governance(context, data, actor_name, manager_name):
    """Owned SQL manager/member inputs only; restore the exact original values."""
    factory = get_session_factory()
    actor_id = UUID(context["actors"][actor_name]["user_id"])
    manager_id = UUID(context["actors"][manager_name]["user_id"])
    project_id = UUID(data["project_id"])
    assert actor_id != manager_id
    added = None
    with factory.begin() as session:
        user, manager = session.get(User, actor_id), session.get(User, manager_id)
        assert all(u and u.is_active and u.directory_enabled and u.directory_object_id for u in (user, manager))
        before = user.manager_user_id, user.updated_at
        user.manager_user_id = manager_id
        existing = session.scalar(select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == manager_id))
        if existing is None:
            added = ProjectMember(project_id=project_id, user_id=manager_id, project_role="viewer",
                created_at=datetime.now(UTC))
            session.add(added)
            session.flush()
            added = (project_id, manager_id, "viewer")
    try:
        yield actor_id, manager_id
    finally:
        with factory.begin() as session:
            user = session.get(User, actor_id)
            assert user.manager_user_id == manager_id
            user.manager_user_id, user.updated_at = before
            if added is not None:
                member = session.get(ProjectMember, added)
                assert member and member.user_id == manager_id and member.project_role == "viewer"
                session.delete(member)
        with factory() as session:
            user = session.get(User, actor_id)
            assert (user.manager_user_id, user.updated_at) == before


def base(data):
    return f"projects/{data['project_id']}/documents/{data['document_id']}/versions/{data['version_id']}"


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def submit(client, data, actor_id):
    evidence = ok(client.get(base(data) + "/submission-evidence"))
    assert evidence["next_stage_allowed"], evidence["block_reasons"]
    return ok(client.post(base(data) + "/submit-review", headers={"Idempotency-Key": "chg383-" + uuid4().hex},
        json={"owner_user_id": str(actor_id), "evidence_revision": evidence["evidence_revision"],
            "lock_version": evidence["lock_version"]}), 201)


def cancel(client, request_id):
    result = ok(client.post(f"approval-requests/{request_id}/cancel"))
    assert result["status"] == "cancelled"
    return result


def artifact_snapshot(version_id):
    """Hash real stored artifacts, automatic steps and ALL owned usage rows."""
    factory = get_session_factory()
    with factory() as session:
        version = session.get(DocumentVersion, UUID(version_id))
        assert version and version.published_at is None
        markdown = resolve_markdown_artifact(session, version, require_fingerprint=True)
        assert markdown.status == "available" and markdown.text
        pipeline = current_pipeline(session, version.id)
        steps = list(session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id)))
        automatic = [{column.name: getattr(step, column.name) for column in PipelineRunStep.__table__.columns}
            for step in steps if step.step_name not in REVIEW_AND_PUBLICATION_STEPS]
        stable_version = {key: getattr(version, key) for key in ("content_sha256", "storage_key",
            "original_snapshot_uri", "markdown_artifact_uri", "extraction_artifact_uri", "embedding_profile_id")}
        tables = {
            "chunks": "r.document_version_id=:version",
            "embedding_builds": "r.document_version_id=:version",
            "embedding_build_vectors": "r.embedding_build_id IN (SELECT id FROM embedding_builds WHERE document_version_id=:version)",
            "document_content_states": "r.document_version_id=:version",
            "document_content_update_jobs": "r.document_version_id=:version",
            "ai_model_usage_events": "true",
        }
        stored = {}
        for table, predicate in tables.items():
            # All identifiers are fixed above; values remain bound parameters.
            stored[table] = list(session.scalars(text(
                f"SELECT to_jsonb(r) FROM {table} r WHERE {predicate} ORDER BY to_jsonb(r)::text"),
                {"version": version.id}))
        payload = {"version": stable_version, "markdown": markdown.text,
            "automatic": sorted(automatic, key=lambda r: r["step_name"]), "stored": stored,
            "pipeline_completed_at": pipeline.completed_at}
        return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def assert_ready(client, data, expected_status):
    value = ok(client.get(base(data) + "/submission-evidence"))
    assert value["next_stage_allowed"], value["block_reasons"]
    editor = ok(client.get(base(data) + "/content-editor"))
    assert editor["edit_mode"] != "readonly" and editor["reason_code"] is None
    with get_session_factory()() as session:
        version = session.get(DocumentVersion, UUID(data["version_id"]))
        pipeline = current_pipeline(session, version.id)
        assert version.status == "submission_ready" and version.published_at is None
        assert pipeline.status == expected_status and pipeline.progress_percent == 100
        assert pipeline.current_waiting_role is None and pipeline.current_action_url is None
        manual = list(session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id,
            PipelineRunStep.step_name.in_(REVIEW_AND_PUBLICATION_STEPS))))
        assert manual and all(s.status == "pending" and s.progress_percent == 0 for s in manual)


def test_cancelled_extraction_restores_editing_and_resubmission_without_replaying_models(current_live, retained_work):
    context, data, old = retained_work
    factory = get_session_factory()
    with governance(context, data, "project_owner", "owner") as (actor_id, _):
        client = current_live.actor("project_owner")
        before = artifact_snapshot(data["version_id"])
        with factory() as session:
            original = session.get(ApprovalRequest, UUID(old["approval_request_id"]))
            assert original.status == "cancelled" and original.cancelled_at
            original_cancelled_at = original.cancelled_at
            assert current_pipeline(session, original.document_version_id).status == "waiting_action"
        first = cancel(client, old["approval_request_id"])
        assert_ready(client, data, "submission_ready")
        assert first == cancel(client, old["approval_request_id"])
        with factory() as session:
            repairs = list(session.scalars(select(AuditLog).where(AuditLog.resource_id == UUID(old["approval_request_id"]),
                AuditLog.action == "approval_request.cancel_repair")))
            assert len(repairs) == 1
            assert session.get(ApprovalRequest, UUID(old["approval_request_id"])).cancelled_at == original_cancelled_at
        new = submit(client, data, actor_id)
        try:
            assert new["status"] == "pending_manager_review"
            cancel(client, old["approval_request_id"])
            with factory() as session:
                request = session.get(ApprovalRequest, UUID(new["id"]))
                assert request.status == "pending_manager_review" and request.current_task_id
                assert current_pipeline(session, request.document_version_id).status == "waiting_action"
        finally:
            cancel(client, new["id"])
        assert_ready(client, data, "submission_ready")
        assert artifact_snapshot(data["version_id"]) == before


def test_owner_stage_cancellation_preserves_real_manager_review_and_completed_artifacts(current_live, retained_work):
    context, data, _ = retained_work
    factory = get_session_factory()
    with governance(context, data, "project_owner", "owner") as (actor_id, manager_id):
        client = current_live.actor("project_owner")
        before = artifact_snapshot(data["version_id"])
        new = submit(client, data, actor_id)
        try:
            with factory() as session:
                request = session.get(ApprovalRequest, UUID(new["id"]))
                task = session.get(ApprovalTask, request.current_task_id)
                assert task.assignee_user_id == manager_id and task.submitter_id != manager_id
                task_id, lock = task.id, task.lock_version
            result = ok(current_live.actor("owner").post(f"approvals/{task_id}/approve",
                headers={"Idempotency-Key": "chg383-manager-" + uuid4().hex},
                json={"lock_version": lock, "comment": "CHG-383 real manager stage"}))
            assert result["status"] == "approved"
            with factory() as session:
                request = session.get(ApprovalRequest, UUID(new["id"]))
                assert request.status == "pending_owner_review"
                owner_task = session.get(ApprovalTask, request.current_task_id)
                assert owner_task.review_stage == "owner_review" and owner_task.status == "pending"
                records = {r.id for r in session.scalars(select(ReviewRecord).where(
                    ReviewRecord.document_version_id == UUID(data["version_id"])))}
                assert session.scalar(select(ReviewRecord.id).where(ReviewRecord.document_version_id == UUID(data["version_id"]),
                    ReviewRecord.reviewer_id == manager_id, ReviewRecord.review_stage == "manager_review",
                    ReviewRecord.status == "approved"))
        finally:
            cancel(client, new["id"])
        with factory() as session:
            assert {r.id for r in session.scalars(select(ReviewRecord).where(
                ReviewRecord.document_version_id == UUID(data["version_id"])))} == records
            assert session.get(ApprovalTask, task_id).status == "approved"
            assert session.get(ApprovalTask, owner_task.id).status == "cancelled"
        assert_ready(client, data, "submission_ready")
        assert artifact_snapshot(data["version_id"]) == before


def test_cancelled_real_content_update_retains_completed_revision_cleanup_and_artifacts(current_live, retained_work):
    context, _, _ = retained_work
    data = context["staging"]
    factory = get_session_factory()
    with governance(context, data, "owner", "project_owner") as (actor_id, _):
        client = current_live.actor("owner")
        before = artifact_snapshot(data["version_id"])
        with factory() as session:
            version = session.get(DocumentVersion, UUID(data["version_id"]))
            pipeline = current_pipeline(session, version.id)
            assert pipeline.run_type == "document_content_update" and pipeline.status == "completed"
            steps = list(session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id)))
            ready, summary = update_submission_state(session, session.get(Project, version.project_id),
                session.get(Document, version.document_id), version, pipeline, steps)
            assert ready and summary["cleanup_status"] == "completed" and summary["step_payloads_verified"]
        new = submit(client, data, actor_id)
        cancel(client, new["id"])
        assert_ready(client, data, "completed")
        assert artifact_snapshot(data["version_id"]) == before


def test_incomplete_real_work_is_not_certified_by_cancellation_and_tentative_changes_rollback(retained_work):
    _, data, _ = retained_work
    factory = get_session_factory()
    before = artifact_snapshot(data["version_id"])
    for missing in ("automatic_step", "embedding_artifact"):
        with factory() as session:
            version = session.get(DocumentVersion, UUID(data["version_id"]))
            approval = session.scalar(select(ApprovalRequest).where(ApprovalRequest.document_version_id == version.id)
                .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc()).limit(1))
            assert approval.status == "cancelled" and version.status == "submission_ready"
            pipeline = current_pipeline(session, version.id)
            assert pipeline.status == "submission_ready"
            # Deliberately invalid native inputs, never committed or successful
            # producer rows. The actual retained work remains unchanged.
            pipeline.status, pipeline.current_step_name = "waiting_action", "manager_review"
            if missing == "automatic_step":
                step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id,
                    PipelineRunStep.step_name == AUTO_EXTRACTION_STEPS[0]))
                step.status = "failed"
            else:
                builds = list(session.scalars(select(EmbeddingBuild).where(EmbeddingBuild.document_version_id == version.id)))
                assert builds
                for build in builds:
                    build.status = "failed"
            session.flush()
            preview = json.dumps(version.chunk_strategy, sort_keys=True)
            assert restore_cancelled_review_pipeline(session, approval, version) is False
            assert pipeline.status == "waiting_action" and pipeline.current_step_name == "manager_review"
            assert json.dumps(version.chunk_strategy, sort_keys=True) == preview
            session.rollback()
    assert artifact_snapshot(data["version_id"]) == before
