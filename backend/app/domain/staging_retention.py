"""Expiry of new rejected versions' staging search documents, never source/history."""
from datetime import UTC, datetime, timedelta
import json
import re
from uuid import uuid4

from sqlalchemy import select, or_, update

from app.core.errors import AppError
from app.db.models import (ApprovalRequest, ActiveVersionManifest, Document, DocumentContentUpdate, DocumentVersion,
                           OutboxEvent, PipelineRun, Project, StagingRetentionJob)
from app.domain.system_parameter_store import read_values
from app.services.audit import add_audit

TOPIC = "staging.retention.expired"


def schedule_retention(session, version, approval_request_id, rejected_at):
    ttl = read_values(session, ("staging_index_ttl_days",))["staging_index_ttl_days"]
    job = StagingRetentionJob(id=uuid4(), project_id=version.project_id, document_id=version.document_id,
        document_version_id=version.id, approval_request_id=approval_request_id,
        rejected_at=rejected_at, ttl_days=ttl, expires_at=rejected_at + timedelta(days=ttl),
        status="scheduled", attempt=0, checkpoint={}, created_at=rejected_at, updated_at=rejected_at)
    session.add(job)
    enqueue(session, job, job.expires_at)


def enqueue(session, job, available_at):
    project = session.get(Project, job.project_id)
    session.add(OutboxEvent(id=uuid4(), topic=TOPIC, aggregate_type="staging_retention_job",
        aggregate_id=job.id, project_id=job.project_id, project_generation=project.work_generation,
        payload={"document_version_id": str(job.document_version_id)}, status="pending", attempts=0,
        available_at=available_at, created_at=datetime.now(UTC)))


def retention_state(session, version_id):
    job = session.scalar(select(StagingRetentionJob).where(StagingRetentionJob.document_version_id == version_id))
    if job is None:
        return None  # Historical rejected versions deliberately have no inferred deadline.
    return {"expires_at": job.expires_at, "ttl_days": job.ttl_days, "cleanup_status": job.status,
            "expired": datetime.now(UTC) >= job.expires_at}


def require_unexpired(session, version_id):
    state = retention_state(session, version_id)
    if state and state["expired"]:
        raise AppError("staging_retention_expired", "Staging search retention expired", status_code=409)


def cancel_project_jobs(session, project_id):
    """Caller holds the project fence; archival owns its existing cleanup policy."""
    now = datetime.now(UTC)
    result = session.execute(update(StagingRetentionJob).where(
        StagingRetentionJob.project_id == project_id,
        StagingRetentionJob.status.not_in(("completed", "cancelled")))
        .values(status="cancelled", error_code="project_archived", lease_token=None,
                lease_expires_at=None, updated_at=now))
    session.execute(update(OutboxEvent).where(OutboxEvent.project_id == project_id,
        OutboxEvent.topic == TOPIC, OutboxEvent.status.in_(("pending", "dispatching")))
        .values(status="cancelled"))
    if result.rowcount:
        add_audit(session, actor_user_id=None, action="staging.retention.cancelled", resource_type="project",
            resource_id=project_id, request_id=None, result="success",
            summary={"reason": "project_archived", "job_count": result.rowcount})


def recover_due_jobs(session, settings):
    now = datetime.now(UTC)
    jobs = list(session.scalars(select(StagingRetentionJob).join(Project, Project.id == StagingRetentionJob.project_id).where(
        Project.status == "active",
        StagingRetentionJob.expires_at <= now,
        StagingRetentionJob.status.in_(("scheduled", "queued", "running", "failed", "blocked")),
        or_(StagingRetentionJob.lease_expires_at.is_(None), StagingRetentionJob.lease_expires_at <= now))
        .order_by(StagingRetentionJob.expires_at).with_for_update(of=StagingRetentionJob, skip_locked=True).limit(settings.staging_retention_batch_size)))
    for job in jobs:
        if job.lease_expires_at and job.lease_expires_at > now:
            continue
        pending = session.scalar(select(OutboxEvent.id).where(OutboxEvent.topic == TOPIC,
            OutboxEvent.aggregate_id == job.id, OutboxEvent.status.in_(("pending", "dispatching"))).limit(1))
        if not pending:
            enqueue(session, job, now)
        job.status, job.lease_expires_at = "queued", now + timedelta(seconds=settings.staging_retention_lease_seconds)


def _protected():
    return AppError("staging_retention_protected", "Staging ownership or lifecycle is not eligible", status_code=409)


def execute_retention(session, settings, job_id):
    candidate = session.get(StagingRetentionJob, job_id)
    if candidate is None:
        return
    # Same parent -> document -> version order as staging retrieval and governance.
    project = session.scalar(select(Project).where(Project.id == candidate.project_id).with_for_update()
        .execution_options(populate_existing=True))
    session.scalar(select(Document).where(Document.id == candidate.document_id).with_for_update())
    version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == candidate.document_version_id)
                             .with_for_update().execution_options(populate_existing=True))
    job = session.scalar(select(StagingRetentionJob).where(StagingRetentionJob.id == job_id)
                         .with_for_update().execution_options(populate_existing=True))
    now = datetime.now(UTC)
    if job is None or job.status in ("completed", "cancelled"):
        return
    if project is None or project.status != "active":
        cancel_project_jobs(session, candidate.project_id)
        session.commit()
        return
    if job.expires_at > now:
        return
    if job.status == "running" and job.lease_expires_at and job.lease_expires_at > now:
        return
    token = uuid4()
    job.status, job.lease_token, job.lease_expires_at = "running", token, now + timedelta(seconds=settings.staging_retention_lease_seconds)
    job.attempt += 1
    # Durable claim before external I/O. Reacquire parent fences after commit.
    session.commit()
    try:
        project = session.scalar(select(Project).where(Project.id == project.id).with_for_update()
            .execution_options(populate_existing=True))
        session.scalar(select(Document).where(Document.id == job.document_id).with_for_update())
        version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == job.document_version_id)
            .with_for_update().execution_options(populate_existing=True))
        job = session.scalar(select(StagingRetentionJob).where(StagingRetentionJob.id == job_id)
            .with_for_update().execution_options(populate_existing=True))
        if job is None or job.lease_token != token or job.status == "cancelled":
            return
        if project is None or project.status != "active":
            cancel_project_jobs(session, job.project_id)
            session.commit()
            return
        if (not version or version.status != "review_rejected" or version.project_id != job.project_id
            or version.document_id != job.document_id
            or session.scalar(select(ActiveVersionManifest.id).where(ActiveVersionManifest.document_version_id == version.id).limit(1))
            or session.scalar(select(ApprovalRequest.id).where(ApprovalRequest.document_version_id == version.id, ApprovalRequest.published_at.is_not(None)).limit(1))
            or session.scalar(select(PipelineRun.id).where(PipelineRun.document_version_id == version.id,
                PipelineRun.status.in_(("queued", "running", "processing"))).limit(1))
            or session.scalar(select(DocumentContentUpdate.id).where(DocumentContentUpdate.document_version_id == version.id,
                DocumentContentUpdate.status.in_(("queued", "running", "cancelling"))).limit(1))):
            raise _protected()
        completed = _delete_staging_scope(session, settings, project, version)
        job.status, job.completed_at, job.error_code = "completed", datetime.now(UTC), None
        job.checkpoint = {"verified_indices": completed, "scope_count": 0}
        job.lease_expires_at = None
        add_audit(session, actor_user_id=None, action="staging.retention.completed", resource_type="document_version",
            resource_id=version.id, request_id=None, result="success", summary={"job_id": str(job.id), "index_count": len(completed)})
        session.commit()
    except Exception as exc:
        session.rollback()
        job = session.scalar(select(StagingRetentionJob).where(StagingRetentionJob.id == job_id).with_for_update())
        if job and job.lease_token == token:
            job.status = "blocked" if getattr(exc, "code", "") == "staging_retention_protected" else "failed"
            job.error_code = "staging_retention_protected" if job.status == "blocked" else "staging_retention_unconfirmed"
            job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=settings.staging_retention_retry_seconds)
            add_audit(session, actor_user_id=None, action="staging.retention.failed", resource_type="document_version",
                resource_id=job.document_version_id, request_id=None, result="failed",
                summary={"job_id": str(job.id), "error_code": job.error_code, "attempt": job.attempt})
            session.commit()
        raise


def _delete_staging_scope(session, settings, project, version):
    """Exact external deletion primitive; caller owns lifecycle/expiry fences."""
    from app.domain.extraction_pipeline import LiveOpenSearchStagingIndexAdapter, staging_index_name
    from app.domain.index_residue import known_index_names, discover_indices
    adapter = LiveOpenSearchStagingIndexAdapter(settings)
    names = known_index_names(session, version.id)
    if version.extraction_artifact_uri:
        if not version.extraction_artifact_uri.startswith("opensearch://"):
            raise _protected()
        names.add(version.extraction_artifact_uri.removeprefix("opensearch://"))
    names |= discover_indices(adapter, staging_index_name(settings.opensearch_index_prefix, project.id, version.id))
    query = {"query": {"bool": {"filter": [{"term": {"project_id": str(version.project_id)}},
        {"term": {"document_id": str(version.document_id)}}, {"term": {"document_version_id": str(version.id)}}]}}}
    options = {"context": settings.opensearch_ssl_context, "content_type": "application/json",
               "read_json": True, "allow_missing": True}
    completed = []
    for index in sorted(names):
        if not re.fullmatch(re.escape(settings.opensearch_index_prefix.lower()) + r"-staging-[a-z0-9_.-]+", index):
            raise _protected()
        url = settings.opensearch_url.rstrip("/") + "/" + index
        mapping = adapter._request("GET", url + "/_mapping", b"", **options)
        if mapping is None:
            completed.append(index)
            continue
        # Reject aliases resolving to another index, including published indices.
        if not isinstance(mapping, dict) or set(mapping) != {index}:
            raise _protected()
        result = adapter._request("POST", url + "/_delete_by_query?conflicts=abort&refresh=true&wait_for_completion=true",
                                  json.dumps(query).encode(), **options)
        if result is not None and (result.get("timed_out") is not False or result.get("failures")):
            raise AppError("staging_retention_unconfirmed", "Staging cleanup is unconfirmed", status_code=503)
        count = adapter._request("POST", url + "/_count", json.dumps(query).encode(), **options)
        if count is not None and (count.get("count") != 0 or count.get("_shards", {}).get("failed") != 0):
            raise AppError("staging_retention_unconfirmed", "Staging cleanup is unconfirmed", status_code=503)
        completed.append(index)
    return completed
