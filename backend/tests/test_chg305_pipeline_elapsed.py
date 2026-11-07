"""PIPE-ELAPSED-001: real model/projection/serialization, not HTTP/DB evidence."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.api.routes.documents import _pipeline_detail, _pipeline_summary
from app.api.schemas import PipelineRunDetail, PipelineSummary
from app.db.models import PipelineRun


@pytest.mark.parametrize("offset", [0, 8, -5])
def test_summary_and_detail_preserve_existing_times(offset):
    start = datetime(2026, 9, 29, 12, 0, tzinfo=timezone(timedelta(hours=offset)))
    end = start + timedelta(hours=25, seconds=32)
    run = PipelineRun(id=uuid4(), project_id=uuid4(), document_id=uuid4(),
                      document_version_id=uuid4(), run_type="document_import",
                      status="submission_ready", progress_percent=100,
                      started_at=start, completed_at=end)
    summary, detail = _pipeline_summary(run), _pipeline_detail(run)
    assert summary.started_at == detail.started_at == run.started_at == start
    assert summary.completed_at == detail.completed_at == run.completed_at == end
    assert summary.model_dump(mode="json") == {
        key: detail.model_dump(mode="json")[key] for key in PipelineSummary.model_fields
    }
    assert PipelineSummary.model_validate_json(summary.model_dump_json()) == summary
    assert PipelineRunDetail.model_validate_json(detail.model_dump_json()) == detail
    assert summary.progress_percent == 100
    assert summary.execution is None  # Unattached model: no invented execution or DB.


def test_queued_and_legacy_payloads_are_nullable_without_synthesizing_start():
    run = PipelineRun(id=uuid4(), project_id=uuid4(), status="queued", progress_percent=0)
    summary = _pipeline_summary(run)
    assert summary.started_at is None
    assert summary.completed_at is None
    assert PipelineSummary(status="queued", progress_percent=0).started_at is None
    assert '"started_at":null' in summary.model_dump_json()
    assert run.started_at is None


def test_failed_run_missing_end_is_not_repaired_by_projection():
    start = datetime(2026, 9, 29, tzinfo=timezone.utc)
    run = PipelineRun(id=uuid4(), project_id=uuid4(), status="failed", progress_percent=52,
                      started_at=start, error_message="timeout")
    summary = _pipeline_summary(run)
    assert summary.started_at == start
    assert summary.completed_at is None
    assert summary.progress_percent == 52
    assert summary.error_message == "timeout"
