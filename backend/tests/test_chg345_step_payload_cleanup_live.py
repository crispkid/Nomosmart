"""Actual database payload bodies and their audit-only retirement receipts."""
import hashlib
import json
import os
from uuid import UUID

from sqlalchemy import select, text

from app.db.models import Document, DocumentVersion, PipelineRun, PipelineRunStep, Project
from app.db.session import get_session_factory
from app.domain.content_pipeline_evidence import current_pipeline, obsolete_step_bodies, DERIVED_BODY_STEPS


def test_actual_unprotected_step_outputs_are_retired_without_hiding_bodies():
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from current_content_evidence_support import current_content_evidence
        with current_content_evidence() as (session, project, document, version, pipeline):
            assert not obsolete_step_bodies(session, project, document, version, pipeline.id)
            steps = list(session.scalars(select(PipelineRunStep).join(PipelineRun).where(
                PipelineRun.document_version_id == version.id, PipelineRun.id != pipeline.id,
                PipelineRun.run_type == "document_content_update",
                PipelineRunStep.step_name.in_(DERIVED_BODY_STEPS))))
            # A first edit has no old same-version producer; that is not a
            # passing retirement test. Require actual earlier body receipts.
            retired = [step for step in steps if step.artifact_payload]
            assert retired, "BLOCKED: a genuine superseded same-version producer is required"
            for step in retired:
                payload = step.artifact_payload
                assert payload.get("payload_retired") is True
                assert payload["document_version_id"] == str(version.id)
                assert len(payload["original_payload_sha256"]) == 64
                assert hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == step.artifact_fingerprint
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
        assert not obsolete_step_bodies(session, project, document, version, pipeline.id)
        steps = list(session.scalars(select(PipelineRunStep).join(PipelineRun).where(
            PipelineRun.document_version_id == version.id, PipelineRun.id != pipeline.id,
            PipelineRunStep.step_name.in_(DERIVED_BODY_STEPS))))
        if steps:
            for step in steps:
                payload = step.artifact_payload or {}
                if payload:
                    assert payload.get("payload_retired") is True
                    assert payload["document_version_id"] == str(version.id)
                    assert len(payload["original_payload_sha256"]) == 64
                    assert hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == step.artifact_fingerprint
