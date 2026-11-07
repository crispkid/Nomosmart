from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_approval_workspace_response_schemas_include_display_metadata() -> None:
    schemas = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")

    for field in ("project_name", "document_title", "version_label", "submitter_name", "submitter_email"):
        assert f"{field}: str | None = None" in schemas


def test_approval_workspace_routes_enrich_pending_and_submission_rows() -> None:
    route = (ROOT / "backend" / "app" / "api" / "routes" / "approvals.py").read_text(encoding="utf-8")

    assert "return ApprovalTaskPage(items=[_approval_task_response(session, row) for row in rows]" in route
    assert "return ApprovalRequestPage(items=[_approval_request_response(session, row) for row in rows]" in route
    assert 'namespace="approval-pending"' in route
    assert 'namespace="approval-history"' in route
    assert '@router.get("/approvals/rejected", response_model=ApprovalTaskPage)' in route
    assert "project_name=project.name if project is not None else None" in route
    assert "document_title=document.title if document is not None else None" in route
    assert "version_label=version.version_label if version is not None else None" in route
    assert "submitter_name=submitter.display_name if submitter is not None else None" in route
    assert "submitter_email=submitter.email if submitter is not None else None" in route


def test_approval_workspace_routes_do_not_require_second_level_matrix_rows() -> None:
    route = (ROOT / "backend" / "app" / "api" / "routes" / "approvals.py").read_text(encoding="utf-8")

    assert "has_permission(" not in route
    assert "require_permission(" not in route
    assert "\"Review\", \"ApprovalWorkspace\"" not in route
    assert "\"Document\", \"DocumentReview\"" not in route
    assert "\"Document\", \"DocumentActivation\"" not in route
    assert "_require_submission_tracking_permission(context)" not in route


def test_pending_publish_workspace_route_requires_owner_publish_scope() -> None:
    route = (ROOT / "backend" / "app" / "api" / "routes" / "approvals.py").read_text(encoding="utf-8")
    schemas = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    block = route.split('@router.get("/approvals/pending-publish"', 1)[1].split('@router.get("/approval-requests"', 1)[0]

    assert "class ApprovalPendingPublishResponse" in schemas
    for field in ("approval_request_id", "approval_task_id", "document_version_id", "version_status", "lock_version", "approved_at"):
        assert field in schemas
    assert "require_permission(" not in block
    assert "ProjectOwner.project_id == DocumentVersion.project_id" in block
    assert "ProjectOwner.user_id == context.user_id" in block
    assert "DocumentVersion.project_id.in_(context.visible_project_ids)" in block
    assert "DocumentVersion.status == \"approved\"" in block
    assert "DocumentVersion.published_at.is_(None)" in block
    assert "ActiveVersionManifest" in block
    assert "~active_manifest_exists" in block
    assert "ApprovalRequest.current_task_id" not in block
    assert "ApprovalRequest.submitter_id == context.user_id" not in block
