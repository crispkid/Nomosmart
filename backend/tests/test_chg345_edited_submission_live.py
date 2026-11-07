"""Read actual producer results in the approved live acceptance scope only."""
import os
from uuid import UUID

from sqlalchemy import select, text

from app.db.models import Document, DocumentVersion, PipelineRunStep, Project
from app.db.session import get_session_factory
from app.domain.content_pipeline_evidence import current_pipeline, update_submission_state
from app.domain.submission_evidence import build_submission_evidence


def test_actual_current_pipeline_and_revision_bound_submission():
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from current_content_evidence_support import current_content_evidence
        with current_content_evidence() as (session, project, document, version, pipeline):
            steps = list(session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id)))
            allowed, summary = update_submission_state(session, project, document, version, pipeline, steps)
            assert allowed and summary["step_payloads_verified"] and summary["cleanup_status"] == "completed"
            evidence = build_submission_evidence(session, project=project, document=document, version=version)
            assert evidence.next_stage_allowed is True, evidence.block_reasons
            assert evidence.manifest["pipeline"]["id"] == str(pipeline.id)
            return
    assert os.environ.get("NOMOSMART_ACCEPTANCE_CHANGE") == "CHG-345", "approved live scope required"
    version_id = UUID(os.environ["CHG345_LIVE_VERSION_ID"])
    with get_session_factory()() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        version = session.get(DocumentVersion, version_id)
        assert version is not None
        project = session.get(Project, version.project_id)
        document = session.get(Document, version.document_id)
        pipeline = current_pipeline(session, version.id, project_id=project.id, document_id=document.id)
        assert pipeline is not None
        steps = list(session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id)))
        if pipeline.run_type == "document_content_update":
            allowed, summary = update_submission_state(session, project, document, version, pipeline, steps)
            assert allowed and summary["step_payloads_verified"] and summary["cleanup_status"] == "completed"
        if version.status == "submission_ready":
            evidence = build_submission_evidence(session, project=project, document=document, version=version)
            assert evidence.next_stage_allowed is True, evidence.block_reasons
            assert evidence.manifest["pipeline"]["id"] == str(pipeline.id)
        if version.published_at is not None:
            status = {s.step_name: s.status for s in steps}
            assert all(status.get(name) == "completed" for name in ("manager_review", "owner_review", "publish", "production_index", "graph_sync"))
