"""Current pipeline identity and revision-bound evidence, without provider calls."""
from __future__ import annotations

import hashlib

from sqlalchemy import select

from app.db.models import DocumentContentState, DocumentContentUpdate, PipelineRun, PipelineRunStep

UPDATE_STEPS = ("generate_markdown", "parse_structure", "auto_tag", "embedding", "staging_index", "build_graph_preview", "cleanup_superseded")
DERIVED_BODY_STEPS = ("auto_tag", "build_graph_preview")
BODY_KEYS = frozenset(("nodes", "edges", "document_tags", "chunk_tags", "tagged_chunks"))


def current_pipeline(session, version_id, *, project_id=None, document_id=None):
    query = select(PipelineRun).where(PipelineRun.document_version_id == version_id,
        ~((PipelineRun.run_type == "document_content_update") & (PipelineRun.status == "cancelled")))
    if project_id is not None:
        query = query.where(PipelineRun.project_id == project_id)
    if document_id is not None:
        query = query.where(PipelineRun.document_id == document_id)
    return session.scalar(query.order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc()).limit(1))


def has_derived_body(payload):
    return isinstance(payload, dict) and bool(BODY_KEYS.intersection(payload))


def obsolete_step_bodies(session, project, document, version, current_run_id):
    return any(has_derived_body(payload) for payload in session.scalars(
        select(PipelineRunStep.artifact_payload).join(PipelineRun, PipelineRun.id == PipelineRunStep.run_id)
        .where(PipelineRun.project_id == project.id, PipelineRun.document_id == document.id,
            PipelineRun.document_version_id == version.id, PipelineRun.id != current_run_id,
            PipelineRunStep.step_name.in_(DERIVED_BODY_STEPS))))


def update_submission_state(session, project, document, version, pipeline, steps):
    """A terminal word alone cannot certify a content update or its cleanup."""
    job = session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.pipeline_run_id == pipeline.id)
        .order_by(DocumentContentUpdate.created_at.desc(), DocumentContentUpdate.id.desc()).limit(1))
    state = session.get(DocumentContentState, version.id)
    checkpoint = job.checkpoint if job and isinstance(job.checkpoint, dict) else {}
    cleanup = checkpoint.get("cleanup")
    cleanup = cleanup if isinstance(cleanup, dict) else {}
    payloads = cleanup.get("step_payloads")
    payloads = payloads if isinstance(payloads, dict) else {}
    statuses = {step.step_name: step.status for step in steps}
    ready = bool(job and state and job.project_id == state.project_id == project.id
        and job.document_id == state.document_id == document.id and job.document_version_id == version.id
        and job.project_generation == project.work_generation and job.status == "ready"
        and job.claim_token is None and job.lease_expires_at is None and job.pending_markdown is None
        and not checkpoint.get("provider_inflight") and checkpoint.get("promoted") is True
        and job.target_revision == state.content_revision and job.target_sha256 == state.current_sha256
        and hashlib.sha256(state.current_markdown.encode()).hexdigest() == state.current_sha256
        and cleanup.get("status") == "completed" and payloads.get("verified") is True
        and payloads.get("revision") == state.content_revision and payloads.get("canonical_sha256") == state.current_sha256
        and all(statuses.get(name) == "completed" for name in UPDATE_STEPS))
    if ready:
        ready = not obsolete_step_bodies(session, project, document, version, pipeline.id)
    summary = {"id": str(job.id), "revision": job.target_revision, "canonical_sha256": job.target_sha256,
        "status": job.status, "promoted": bool(checkpoint.get("promoted")),
        "cleanup_status": cleanup.get("status"), "step_payloads_verified": payloads.get("verified") is True,
        "retired_step_payload_count": payloads.get("retired_count", 0)} if job else None
    return ready, summary
