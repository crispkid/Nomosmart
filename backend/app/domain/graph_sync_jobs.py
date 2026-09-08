from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Chunk, Document, DocumentVersion, GraphSyncJob, OutboxEvent, Project, ProjectOwner
from app.domain.notifications import emit_notification_event, resolve_business_notifications
from app.services.audit import add_audit
from app.domain.graph_reconciliation import locked_projection, synchronize_graph


GRAPH_SYNC_TOPIC = "graph_sync.requested"
_SAFE_FAILURE_MESSAGE = "Graph synchronization failed"


def enqueue_graph_sync(
    session: Session,
    *,
    project_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    trigger_type: str,
    requested_by_user_id: UUID | None,
    request_id: str | None,
    parent_job_id: UUID | None = None,
) -> GraphSyncJob:
    now = datetime.now(UTC)
    projection = locked_projection(session, project_id, document_id, document_version_id)
    project = session.get(Project, project_id)
    project_generation = project.work_generation if project is not None else 0
    job = GraphSyncJob(
        project_id=project_id,
        document_id=document_id,
        document_version_id=document_version_id,
        project_generation=project_generation,
        parent_job_id=parent_job_id,
        requested_by_user_id=requested_by_user_id,
        request_id=request_id,
        trigger_type=trigger_type,
        status="queued",
        attempt=0,
        created_at=now,
    )
    session.add(job)
    session.flush()
    session.add(
        OutboxEvent(
            topic=GRAPH_SYNC_TOPIC,
            aggregate_type="graph_sync_job",
            aggregate_id=job.id,
            project_id=project_id,
            project_generation=project_generation,
            payload={"job_id": str(job.id), "parent_job_id": str(parent_job_id) if parent_job_id else None, "project_generation": project_generation, "graph_binding": projection.binding()},
            status="pending",
            attempts=0,
            available_at=now,
            created_at=now,
        )
    )
    return job


def execute_graph_sync_job(session: Session, *, settings: Settings, job_id: UUID) -> None:
    now = datetime.now(UTC)
    job = session.get(GraphSyncJob, job_id)
    if job is None:
        return
    project_id = job.project_id
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update().execution_options(populate_existing=True))
    job = session.scalar(select(GraphSyncJob).where(GraphSyncJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    if job is None or job.status == "completed":
        return
    if job.status == "running" and job.lease_expires_at is not None and job.lease_expires_at > now:
        return
    if job.status not in {"queued", "running"}:
        return
    if project is None or project.status != "active" or project.work_generation != job.project_generation:
        job.status = "cancelled"
        job.error_code = "project_work_generation_stale"
        job.error_message = "Graph synchronization was cancelled because the project state changed"
        job.completed_at = now
        session.commit()
        return

    claim_token = uuid4()
    job.status = "running"
    job.attempt += 1
    job.claim_token = claim_token
    job.claimed_at = now
    job.lease_expires_at = now + timedelta(seconds=settings.ingestion_worker_lease_seconds)
    job.error_code = None
    job.error_message = None
    session.commit()

    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update().execution_options(populate_existing=True))
    job = session.scalar(select(GraphSyncJob).where(GraphSyncJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    if job is None or job.claim_token != claim_token:
        session.rollback()
        return
    if project is None or project.status != "active" or project.work_generation != job.project_generation:
        cancelled = session.get(GraphSyncJob, job_id)
        if cancelled is not None and cancelled.claim_token == claim_token:
            cancelled.status = "cancelled"
            cancelled.error_code = "project_work_generation_stale"
            cancelled.error_message = "Graph synchronization was cancelled because the project state changed"
            cancelled.completed_at = datetime.now(UTC)
            cancelled.claim_token = None
            cancelled.claimed_at = None
            cancelled.lease_expires_at = None
            session.commit()
        return
    document = session.get(Document, job.document_id)
    version = session.get(DocumentVersion, job.document_version_id)
    chunks = (
        list(
            session.scalars(
                select(Chunk)
                .where(Chunk.document_version_id == job.document_version_id, Chunk.status == "active")
                .order_by(Chunk.chunk_index)
            )
        )
        if document is not None and version is not None
        else []
    )
    try:
        if document is None or version is None or not chunks:
            raise AppError("graph_sync_resource_not_ready", _SAFE_FAILURE_MESSAGE, status_code=409)
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.topic == GRAPH_SYNC_TOPIC,
            OutboxEvent.aggregate_id == job.id).order_by(OutboxEvent.created_at.desc()))
        binding = (event.payload or {}).get("graph_binding") if event is not None else None
        if not binding:
            raise AppError("graph_work_binding_required", _SAFE_FAILURE_MESSAGE, status_code=409)
        result = synchronize_graph(session, settings, job.project_id, document.id, version.id, expected_binding=binding)
    except Exception as exc:
        # Preserve the committed claim but discard any aborted source/read
        # transaction before recording durable failure evidence.
        session.rollback()
        session.scalar(select(Project).where(Project.id == project_id).with_for_update())
        failed = session.scalar(select(GraphSyncJob).where(GraphSyncJob.id == job_id).with_for_update())
        if failed is None or failed.claim_token != claim_token:
            session.rollback()
            return
        failed.status = "failed"
        failed.error_code = getattr(exc, "code", "graph_sync_failed")
        failed.error_message = _SAFE_FAILURE_MESSAGE
        failed.completed_at = datetime.now(UTC)
        failed.claim_token = None
        failed.claimed_at = None
        failed.lease_expires_at = None
        add_audit(
            session,
            actor_user_id=failed.requested_by_user_id,
            action="worker.graph_sync.failed",
            resource_type="graph_sync_job",
            resource_id=failed.id,
            result="failed",
            request_id=failed.request_id,
            summary={"error_code": failed.error_code, "attempt": failed.attempt},
        )
        notify_graph_failure(session, failed)
        session.commit()
        return

    completed = session.scalar(select(GraphSyncJob).where(GraphSyncJob.id == job_id).with_for_update())
    if completed is None or completed.claim_token != claim_token:
        session.rollback()
        return
    completed.status = "completed"
    completed.node_count = len(result.graph["nodes"])
    completed.edge_count = len(result.graph["edges"])
    completed.error_code = None
    completed.error_message = None
    completed.completed_at = datetime.now(UTC)
    completed.claim_token = None
    completed.claimed_at = None
    completed.lease_expires_at = None
    resolve_business_notifications(session, business_key=f"graph:{completed.document_version_id}", reason="graph_verified")
    add_audit(
        session,
        actor_user_id=completed.requested_by_user_id,
        action="worker.graph_sync.completed",
        resource_type="graph_sync_job",
        resource_id=completed.id,
        result="success",
        request_id=completed.request_id,
        summary={"node_count": completed.node_count, "edge_count": completed.edge_count, "attempt": completed.attempt},
    )
    session.commit()


def notify_graph_failure(session: Session, job: GraphSyncJob) -> None:
    recipients = list(session.scalars(select(ProjectOwner.user_id).where(ProjectOwner.project_id == job.project_id)))
    if job.requested_by_user_id is not None:
        recipients.append(job.requested_by_user_id)
    emit_notification_event(session, project_id=job.project_id, event_type="graph_sync.failed",
        business_key=f"graph:{job.document_version_id}", recipient_user_ids=recipients, severity="error",
        title="知識圖譜同步失敗", message="圖譜尚未通過一致性驗證，請檢查同步工作。",
        action_type="graph_sync", action_payload={"job_id": str(job.id), "document_version_id": str(job.document_version_id), "error_code": job.error_code})
