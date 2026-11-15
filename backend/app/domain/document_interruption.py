"""CHG-426 REL426-022/023: record an interrupted document run as a retryable failure."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import DocumentVersion, PipelineRun, PipelineRunStep
from app.domain.extraction_pipeline import _fail_step

INTERRUPTED_MESSAGE = "Document processing was interrupted; retry is required"
UNEXPECTED_MESSAGE = "Document processing stopped unexpectedly; retry is required"


def mark_run_failed(session: Session, run_id: UUID, *, message: str, error_code: str) -> PipelineRun:
    """Fail the in-flight step(s), the run and its version. The caller holds the execution lock."""
    run = session.get(PipelineRun, run_id, populate_existing=True)
    steps = list(session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == run_id,
        or_(PipelineRunStep.status == "running", PipelineRunStep.claim_token.is_not(None)))
        .with_for_update().execution_options(populate_existing=True)))
    for step in steps:
        _fail_step(step, message)
        step.artifact_payload = {**(step.artifact_payload or {}), "error_code": error_code}
    run.status, run.error_message = "failed", message
    if steps:
        run.current_step_name = steps[0].step_name
    version = session.get(DocumentVersion, run.document_version_id, populate_existing=True)
    version.status, version.updated_at = "failed", datetime.now(UTC)
    session.flush()
    return run
