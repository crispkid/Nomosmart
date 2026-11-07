from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_approval_decision_routes_flush_before_idempotency_response() -> None:
    source = (ROOT / "backend" / "app" / "api" / "routes" / "approvals.py").read_text(encoding="utf-8")
    approve_block = source.split('@router.post("/approvals/{approval_task_id}/approve"', 1)[1].split('@router.post("/approvals/{approval_task_id}/reject"', 1)[0]
    reject_block = source.split('@router.post("/approvals/{approval_task_id}/reject"', 1)[1].split('@router.post("/document-versions/{version_id}/publish"', 1)[0]

    for block in (approve_block, reject_block):
        assert "session.flush()" in block
        assert "response = _approval_task_response(session, task)" in block
        assert "response.model_dump(mode=\"json\")" in block
        assert "session.refresh(task)" not in block
        assert "return response" in block


def test_completed_approval_task_repair_migration_is_conservative_and_idempotent() -> None:
    migration = (ROOT / "sql" / "migrations" / "V014__repair_completed_approval_tasks.sql").read_text(encoding="utf-8")

    assert "WHERE task.status = 'pending'" in migration
    assert "JOIN approval_requests request ON request.id = task.approval_request_id" in migration
    assert "JOIN document_versions version ON version.id = task.document_version_id" in migration
    assert "JOIN review_records record" in migration
    assert "record.review_stage = task.review_stage" in migration
    assert "task.review_stage = 'owner_review'" in migration
    assert "request.status IN ('approved', 'published')" in migration
    assert "version.status IN ('approved', 'active', 'inactive')" in migration
    assert "request.status = 'rejected'" in migration
    assert "version.status = 'review_rejected'" in migration
    assert "completed_at = COALESCE(task.completed_at, latest_review.repaired_at)" in migration
    assert "lock_version = GREATEST(task.lock_version + 1, 2)" in migration
    assert "key.scope LIKE ('approval.%:' || task.id::text || ':%')" in migration
    assert "key.response_summary->>'status' = 'pending'" in migration
