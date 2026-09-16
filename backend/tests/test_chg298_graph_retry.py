"""Real graph failure/retry execution; no Provider or publish-success claim."""
import os
from uuid import UUID

import pytest
from sqlalchemy import select

if os.environ.get("CHG298_ISOLATED") != "1":
    raise RuntimeError("BLOCKED: fresh CHG-298 isolated services required")

from test_live_backend_api_behavior import live_client, _seed_live_document_workspace, _synchronize_stored_graph_input
from app.core.config import get_settings
from app.db.models import AuditLog, Document, DocumentVersion, GraphSyncJob, OutboxEvent, Project
from app.db.session import get_session_factory
from app.domain.graph_sync_jobs import enqueue_graph_sync, execute_graph_sync_job
from app.domain.graph_projection import build_graph_projection
from app.domain.graph_reconciliation import Neo4jProjectionStore


def test_real_failed_graph_job_retries_once_with_key_and_worker(live_client):
    client, headers, actor, _ = live_client
    factory = get_session_factory()
    data = _seed_live_document_workspace(factory, actor)
    _synchronize_stored_graph_input(data)
    pid, did, vid = (UUID(data[key]) for key in ("project_id", "document_id", "version_id"))
    settings = get_settings()
    assert "127.0.0.1" in settings.neo4j_uri
    with factory() as session:
        job = enqueue_graph_sync(session, project_id=pid, document_id=did, document_version_id=vid,
            trigger_type="manual_retry", requested_by_user_id=UUID(actor), request_id="chg298-connection-refusal")
        jid = job.id; session.commit()
        # A real refused TCP connection, not a fake store or a hand-filled failed
        # job. Only this worker invocation gets the isolated unavailable address.
        refused = settings.model_copy(update={"neo4j_uri":"bolt://127.0.0.1:65535"})
        execute_graph_sync_job(session, settings=refused, job_id=jid)
        session.expire_all(); failed=session.get(GraphSyncJob,jid)
        assert failed.status == "failed" and failed.error_code == "graph_projection_not_ready"
        assert failed.attempt == 1 and failed.claim_token is None
    response=client.post(f"/api/v1/graph-sync-jobs/{jid}/retry",headers=headers)
    assert response.status_code==422 and response.json()["code"]=="idempotency_key_required"
    with factory() as session:
        assert not list(session.scalars(select(GraphSyncJob).where(GraphSyncJob.parent_job_id==jid)))
    keyed={**headers,"Idempotency-Key":f"chg298-graph-{jid}"}
    response=client.post(f"/api/v1/graph-sync-jobs/{jid}/retry",headers=keyed)
    assert response.status_code==202,response.text
    queued=response.json(); child_id=UUID(queued["id"])
    assert queued["status"]=="queued"
    # Parent identity is stored internally; it is not a declared public DTO
    # field. The exact parent/child/outbox relationship is checked below in SQL.
    replay=client.post(f"/api/v1/graph-sync-jobs/{jid}/retry",headers=keyed)
    assert replay.status_code==202 and replay.json()==queued
    with factory() as session:
        assert list(session.scalars(select(GraphSyncJob.id).where(GraphSyncJob.parent_job_id==jid)))==[child_id]
        assert len(list(session.scalars(select(OutboxEvent.id).where(OutboxEvent.aggregate_id==child_id))))==1
        assert session.get(GraphSyncJob,child_id).attempt==0  # no inline worker
        execute_graph_sync_job(session,settings=settings,job_id=child_id)
        session.expire_all(); child=session.get(GraphSyncJob,child_id)
        assert child.status=="completed" and child.attempt==1 and child.error_code is None
        project=session.get(Project,pid);document=session.get(Document,did);version=session.get(DocumentVersion,vid)
        projection=build_graph_projection(session,project,document,version)
        assert Neo4jProjectionStore(settings).read(projection).matches(projection)
        terminal=list(session.scalars(select(AuditLog.id).where(AuditLog.resource_id==child_id,AuditLog.action=="worker.graph_sync.completed")))
        assert len(terminal)==1
        session.commit()
        execute_graph_sync_job(session,settings=settings,job_id=child_id)
        session.expire_all()
        assert session.get(GraphSyncJob,child_id).attempt==1
        assert list(session.scalars(select(AuditLog.id).where(AuditLog.resource_id==child_id,AuditLog.action=="worker.graph_sync.completed")))==terminal
    completed=client.post(f"/api/v1/graph-sync-jobs/{child_id}/retry",headers=keyed)
    assert completed.status_code==409 and completed.json()["code"]=="graph_sync_retry_not_available"
