from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from threading import Event, Thread
from uuid import UUID, uuid4

from kombu import Queue
from celery import Celery
from app.services.directory_schedule import DirectoryDailySchedule
from celery.signals import heartbeat_sent, worker_ready
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import DataConnection, DataSyncRun, Document, DocumentVersion, IdentitySyncProviderResult, IdentitySyncRun, OutboxEvent, PipelineRun, Project, ValidationRun
from app.db.session import get_session_factory
from app.domain.data_sync import execute_data_source_sync, queue_due_scheduled_data_syncs
from app.domain.chunk_artifacts import RECONCILIATION_TOPIC, execute_chunk_artifact_reconciliation
from app.domain.document_content_updates import CONTENT_UPDATE_TOPIC, execute_content_update
from app.domain.extraction_pipeline import execute_auto_extraction
from app.domain.file_processing_dispatch import (TOPIC as DOCUMENT_TOPIC, claim_task, configured_capabilities,
    finalizable_task_ids, finalize_task, mark_stale_tasks, prepare_dispatch, quiesce_task, require_claim)
from app.domain.graph_sync_jobs import GRAPH_SYNC_TOPIC, execute_graph_sync_job
from app.domain.notifications import NOTIFICATION_TOPIC, execute_notification_event
from app.domain.project_archival import ARCHIVE_CLEANUP_TOPIC, execute_project_archive_cleanup, recover_stale_project_archive_runs
from app.domain.public_api_retention import enforce_public_api_retention
from app.domain.staging_retention import TOPIC as STAGING_RETENTION_TOPIC, execute_retention, recover_due_jobs
from app.domain.validation_runner import execute_validation_run
from app.services.audit import add_audit
from app.services.identity_sync_jobs import (
    create_identity_sync_run,
    effective_identity_sync_scope,
    record_beat_heartbeat,
    record_worker_heartbeat,
    recover_stale_identity_runs,
)


settings = get_settings()
celery_app = Celery("nomosmart", broker=settings.celery_broker_url.get_secret_value(), backend=settings.celery_result_backend.get_secret_value())
if settings.redis_ha_mode == "sentinel":
    redis_ssl = {
        "ssl_cert_reqs": "required",
        "ssl_ca_certs": settings.redis_tls_ca_cert_path,
    }
    sentinel_kwargs = {
        "username": settings.redis_sentinel_username,
        "password": settings.redis_sentinel_password.get_secret_value(),
        "ssl": True,
        "ssl_ca_certs": settings.redis_tls_ca_cert_path,
        "ssl_cert_reqs": "required",
        "ssl_check_hostname": True,
    }
    celery_app.conf.broker_transport_options = {
        "master_name": settings.redis_sentinel_master_name,
        "sentinel_kwargs": sentinel_kwargs,
        "visibility_timeout": 3600,
    }
    celery_app.conf.result_backend_transport_options = {
        "master_name": settings.redis_sentinel_master_name,
        "sentinel_kwargs": sentinel_kwargs,
        "retry_policy": {"timeout": 5.0},
    }
    celery_app.conf.broker_use_ssl = redis_ssl
    celery_app.conf.redis_backend_use_ssl = redis_ssl
if settings.celery_global_keyprefix:
    celery_app.conf.broker_transport_options = {**celery_app.conf.broker_transport_options,
        "global_keyprefix": settings.celery_global_keyprefix}
    celery_app.conf.result_backend_transport_options = {**celery_app.conf.result_backend_transport_options,
        "global_keyprefix": settings.celery_global_keyprefix}
celery_app.conf.task_queues = (Queue("celery"), Queue("nomosmart-auth-v2"))
celery_app.conf.task_routes = {
    "app.worker.run_directory_sync_v2": {"queue": "nomosmart-auth-v2"},
    "app.worker.queue_scheduled_directory_sync_v2": {"queue": "nomosmart-auth-v2"},
    "app.worker.record_runtime_heartbeat": {"queue": "nomosmart-auth-v2"},
}
celery_app.conf.beat_scheduler = "app.services.directory_schedule:DirectoryBeatScheduler"
celery_app.conf.beat_max_loop_interval = 60
celery_app.conf.timezone = settings.identity_sync_timezone
_minute, _hour, _day_of_month, _month_of_year, _day_of_week = settings.identity_sync_schedule.split()
celery_app.conf.beat_schedule = {
    "record-runtime-heartbeat": {"task": "app.worker.record_runtime_heartbeat", "schedule": float(settings.identity_sync_heartbeat_seconds)},
    "queue-daily-identity-sync": {"task": "app.worker.queue_scheduled_directory_sync_v2", "schedule": DirectoryDailySchedule(run_every=60, app=celery_app)},
    "queue-scheduled-data-source-sync": {"task": "app.worker.queue_scheduled_data_source_sync", "schedule": 60.0},
    "dispatch-outbox": {"task": "app.worker.dispatch_outbox", "schedule": 10.0},
    "recover-stale-project-archive-runs": {"task": "app.worker.recover_stale_project_archives", "schedule": 60.0},
    "cleanup-authentication-retention": {"task": "app.worker.cleanup_authentication_retention", "schedule": 86400.0},
    "recover-staging-retention": {"task": "app.worker.recover_staging_retention", "schedule": float(settings.staging_retention_recovery_seconds)},
    "cleanup-public-api-retention": {"task": "app.worker.cleanup_public_api_retention", "schedule": 86400.0},
}


@worker_ready.connect
@heartbeat_sent.connect
def _record_worker_runtime_heartbeat(**_: object) -> None:
    try:
        record_worker_heartbeat(settings)
    except Exception:
        return




class _IdentityRunHeartbeat:
    def __init__(self, factory, run_id: UUID, lease_token: UUID, interval_seconds: int) -> None:
        self.factory = factory
        self.run_id = run_id
        self.lease_token = lease_token
        self.interval_seconds = interval_seconds
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name=f"identity-sync-heartbeat-{run_id}", daemon=True)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                with self.factory.begin() as session:
                    run = session.scalar(
                        select(IdentitySyncRun).where(
                            IdentitySyncRun.id == self.run_id,
                            IdentitySyncRun.status == "running",
                            IdentitySyncRun.lease_token == self.lease_token,
                        )
                    )
                    if run is None:
                        return
                    run.heartbeat_at = datetime.now(UTC)
            except Exception:
                continue

    def __enter__(self) -> "_IdentityRunHeartbeat":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2.0)


def _active_identity_run_for_lease(session, run_id: UUID, lease_token: UUID) -> IdentitySyncRun | None:
    return session.scalar(
        select(IdentitySyncRun)
        .where(
            IdentitySyncRun.id == run_id,
            IdentitySyncRun.status == "running",
            IdentitySyncRun.lease_token == lease_token,
        )
        .with_for_update()
    )


def _identity_provider_result(session, run_id: UUID, provider_id: str) -> IdentitySyncProviderResult | None:
    return session.scalar(
        select(IdentitySyncProviderResult)
        .where(
            IdentitySyncProviderResult.run_id == run_id,
            IdentitySyncProviderResult.provider_id == provider_id,
        )
        .with_for_update()
    )


@celery_app.task(name="app.worker.record_runtime_heartbeat")
def record_runtime_heartbeat() -> None:
    record_worker_heartbeat(settings)
    record_beat_heartbeat(settings)


@celery_app.task(name="app.worker.run_directory_sync_v2")
def run_identity_sync(run_id: str, lease_token: str | None = None) -> None:
    from app.services.directory_sync_worker import execute_directory_sync
    try:
        parsed_id = UUID(run_id)
        parsed_lease = UUID(lease_token) if lease_token else None
    except ValueError:
        return
    if parsed_lease is None:
        return
    factory = get_session_factory()
    with _IdentityRunHeartbeat(factory, parsed_id, parsed_lease, settings.identity_sync_heartbeat_seconds):
        execute_directory_sync(settings, factory, parsed_id, parsed_lease)



@celery_app.task(name="app.worker.queue_scheduled_directory_sync_v2")
def queue_scheduled_identity_sync() -> None:
    factory = get_session_factory()
    with factory.begin() as session:
        recover_stale_identity_runs(session, settings)
        try:
            create_identity_sync_run(
                session,
                trigger_type="scheduled",
                actor_user_id=None,
                request_id=None,
                requested_scope=effective_identity_sync_scope(session, settings),
            )
        except Exception as exc:
            if getattr(exc, "code", None) == "identity_sync_already_running":
                return
            raise


@celery_app.task(name="app.worker.queue_scheduled_data_source_sync")
def queue_scheduled_data_source_sync() -> None:
    factory = get_session_factory()
    with factory.begin() as session:
        queue_due_scheduled_data_syncs(session)


@celery_app.task(name="app.worker.recover_stale_project_archives")
def recover_stale_project_archives() -> None:
    factory = get_session_factory()
    with factory.begin() as session:
        recover_stale_project_archive_runs(session)


@celery_app.task(name="app.worker.dispatch_outbox")
def dispatch_outbox() -> None:
    factory = get_session_factory()
    with factory.begin() as session:
        now = datetime.now(UTC)
        events = list(session.scalars(select(OutboxEvent).where(
            OutboxEvent.topic.in_(("identity.directory-sync.v2.requested", "validation.run.requested", "data_source.sync.requested", GRAPH_SYNC_TOPIC, NOTIFICATION_TOPIC, RECONCILIATION_TOPIC, CONTENT_UPDATE_TOPIC, ARCHIVE_CLEANUP_TOPIC, STAGING_RETENTION_TOPIC)),
            OutboxEvent.available_at <= now,
            or_(OutboxEvent.status == "pending", (OutboxEvent.status == "dispatching") & (OutboxEvent.lease_expires_at < now)),
        ).with_for_update(skip_locked=True).limit(20)))
        for event in events:
            if not _outbox_generation_current(session, event):
                event.status = "cancelled"
                event.processed_at = now
                event.last_error = "project_generation_stale"
                event.claim_token = None
                event.claimed_at = None
                event.lease_expires_at = None
                continue
            claim = uuid4()
            task_id = str(uuid4())
            event.status = "dispatching"
            event.claim_token = claim
            event.claimed_at = now
            event.lease_expires_at = now + timedelta(seconds=settings.ingestion_worker_lease_seconds)
            event.task_id = task_id
            event.attempts += 1
            try:
                task = _outbox_task(event.topic)
                args = [str(event.aggregate_id)]
                if event.topic == "identity.directory-sync.v2.requested":
                    args.append(str((event.payload or {}).get("lease_token") or ""))
                task.apply_async(args=args, task_id=task_id)
            except Exception as exc:
                event.status = "pending"
                event.available_at = now + timedelta(seconds=min(300, 2 ** min(event.attempts, 8)))
                event.last_error = type(exc).__name__
                event.claim_token = None
                event.claimed_at = None
                event.lease_expires_at = None
                continue
            event.status = "dispatched"
            event.processed_at = datetime.now(UTC)
            event.last_error = None
            event.claim_token = None
            event.claimed_at = None
            event.lease_expires_at = None


    # Document intent is committed BEFORE broker I/O. Other topics retain their
    # existing behavior and are not held up by unavailable document capacity.
    dispatch_document_outbox(factory)


def dispatch_document_outbox(factory) -> None:
    with factory.begin() as session:
        mark_stale_tasks(session, stale_seconds=settings.ingestion_worker_lease_seconds)
    with factory() as session:
        completed = finalizable_task_ids(session)
    for task_id in completed:
        with factory.begin() as session:
            finalize_task(session, task_id)
    with factory() as session:
        now = datetime.now(UTC)
        candidates = list(session.scalars(select(OutboxEvent.id).where(OutboxEvent.topic == DOCUMENT_TOPIC,
            OutboxEvent.available_at <= now, or_(OutboxEvent.status == "pending",
                (OutboxEvent.status == "dispatching") & (OutboxEvent.lease_expires_at < now)))
            .order_by(OutboxEvent.created_at, OutboxEvent.id).limit(20)))
    if not candidates:
        return
    capabilities = configured_capabilities(settings)
    for event_id in candidates:
        with factory.begin() as session:
            candidate = session.get(OutboxEvent, event_id)
            if candidate is None:
                continue
            run = session.get(PipelineRun, candidate.aggregate_id)
            if not _outbox_generation_current(session, candidate) or run is None or run.status not in {"queued", "running"}:
                # Remove stale metadata from the dispatch queue, not application
                # content or occupancy. No policy/task lock is acquired here.
                event = session.get(OutboxEvent, event_id, with_for_update=True, populate_existing=True)
                # A user may have authorized a retry between the initial read
                # and this lock. Re-read scope/status before cancelling metadata.
                run_status = session.scalar(select(PipelineRun.status).where(PipelineRun.id == event.aggregate_id))
                if event.project_id:
                    session.get(Project, event.project_id, populate_existing=True)
                if (event.status in {"pending", "dispatching"}
                        and (not _outbox_generation_current(session, event)
                             or run_status not in {"queued", "running"})):
                    event.status, event.processed_at = "cancelled", datetime.now(UTC)
                    event.last_error = "file_processing_run_not_dispatchable"
                    event.claim_token = event.claimed_at = event.lease_expires_at = None
                continue
            now = datetime.now(UTC)
            if candidate.status not in {"pending", "dispatching"} or candidate.available_at > now:
                continue
            if candidate.status == "dispatching" and candidate.lease_expires_at and candidate.lease_expires_at > now:
                continue
            dispatch = prepare_dispatch(session, run_id=candidate.aggregate_id, capabilities=capabilities)
            if dispatch is None:
                continue
            event = session.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id)
                .with_for_update().execution_options(populate_existing=True))
            now = datetime.now(UTC)
            if event.status not in {"pending", "dispatching"} or event.available_at > now:
                session.rollback()  # Do not commit an intent for an ineligible event.
                continue
            if event.status == "dispatching" and event.lease_expires_at and event.lease_expires_at > now:
                session.rollback()
                continue
            event.status, event.task_id = "dispatching", str(dispatch.broker_task_id)
            event.lease_expires_at = now + timedelta(seconds=settings.ingestion_worker_lease_seconds)
            event.attempts += 1
        try:
            run_document_extraction.apply_async(args=[str(dispatch.run_id), str(dispatch.task_id),
                str(dispatch.generation)], task_id=str(dispatch.broker_task_id))
        except Exception:  # Ambiguous broker response: retain same durable task, never re-claim it.
            with factory.begin() as session:
                event = session.get(OutboxEvent, event_id, with_for_update=True)
                if event and event.task_id == str(dispatch.broker_task_id):
                    event.last_error = "file_processing_broker_unconfirmed"
            continue
        with factory.begin() as session:
            event = session.get(OutboxEvent, event_id, with_for_update=True)
            if event and event.status == "dispatching" and event.task_id == str(dispatch.broker_task_id):
                event.status, event.processed_at, event.last_error = "dispatched", datetime.now(UTC), None
                event.lease_expires_at = None


def _outbox_task(topic: str):
    tasks = {
        "identity.directory-sync.v2.requested": run_identity_sync,
        "validation.run.requested": run_project_chat_validation,
        "data_source.sync.requested": run_data_source_sync,
        GRAPH_SYNC_TOPIC: run_graph_sync,
        NOTIFICATION_TOPIC: run_notification_event,
        RECONCILIATION_TOPIC: run_chunk_artifact_reconciliation,
        CONTENT_UPDATE_TOPIC: run_document_content_update,
        ARCHIVE_CLEANUP_TOPIC: run_project_archive_cleanup,
        STAGING_RETENTION_TOPIC: run_staging_retention,
    }
    return tasks[topic]


def _outbox_generation_current(session, event: OutboxEvent) -> bool:
    project_id = event.project_id
    if project_id is None:
        raw_project_id = (event.payload or {}).get("project_id")
        try:
            project_id = UUID(str(raw_project_id)) if raw_project_id else None
        except ValueError:
            return False
    if project_id is None:
        return True
    project = session.get(Project, project_id)
    if project is None:
        return False
    expected = event.project_generation
    if expected is None:
        raw_generation = (event.payload or {}).get("project_generation")
        try:
            expected = int(raw_generation) if raw_generation is not None else None
        except (TypeError, ValueError):
            return False
    if event.topic == ARCHIVE_CLEANUP_TOPIC:
        return project.status == "archived" and expected == project.work_generation
    return project.status == "active" and expected == project.work_generation


@celery_app.task(name="app.worker.run_graph_sync", acks_late=True, reject_on_worker_lost=True)
def run_graph_sync(job_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        execute_graph_sync_job(session, settings=settings, job_id=UUID(job_id))


@celery_app.task(name="app.worker.run_notification_event", acks_late=True, reject_on_worker_lost=True)
def run_notification_event(event_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        execute_notification_event(session, UUID(event_id))


@celery_app.task(name="app.worker.run_project_archive_cleanup", autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5, acks_late=True, reject_on_worker_lost=True)
def run_project_archive_cleanup(run_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        execute_project_archive_cleanup(session, settings=settings, run_id=UUID(run_id))


@celery_app.task(name="app.worker.run_chunk_artifact_reconciliation", acks_late=True, reject_on_worker_lost=True)
def run_chunk_artifact_reconciliation(version_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        execute_chunk_artifact_reconciliation(session, UUID(version_id), settings)


@celery_app.task(name="app.worker.run_document_content_update",acks_late=True,reject_on_worker_lost=True)
def run_document_content_update(update_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        execute_content_update(session,UUID(update_id),settings)


@celery_app.task(name="app.worker.run_project_chat_validation", autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=3)
def run_project_chat_validation(run_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        run = session.get(ValidationRun, UUID(run_id))
        project = session.get(Project, run.project_id) if run is not None else None
        if run is None or project is None:
            return
        if project.status != "active" or run.project_generation != project.work_generation:
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            session.commit()
            return
        try:
            execute_validation_run(session, UUID(run_id))
        except Exception as exc:
            add_audit(session, actor_user_id=None, action="worker.validation_run.failed", resource_type="validation_run", resource_id=UUID(run_id), result="failed", request_id=None, summary={"error_code": getattr(exc, "code", "validation_run_failed")})
            session.commit()
            raise


@celery_app.task(name="app.worker.run_data_source_sync", autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=3)
def run_data_source_sync(run_id: str) -> None:
    factory = get_session_factory()
    with factory.begin() as session:
        run = session.get(DataSyncRun, UUID(run_id))
        connection = session.get(DataConnection, run.data_connection_id) if run is not None else None
        project = session.get(Project, connection.project_id) if connection is not None else None
        if run is None or project is None:
            return
        if project.status != "active" or run.project_generation != project.work_generation:
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            run.error_code = "project_work_generation_stale"
            run.error_summary = "Synchronization was cancelled because the project state changed"
            return
        execute_data_source_sync(session=session, settings=settings, run_id=UUID(run_id))


@celery_app.task(name="app.worker.cleanup_public_api_retention")
def cleanup_public_api_retention() -> None:
    factory = get_session_factory()
    with factory() as session:
        enforce_public_api_retention(session)


@celery_app.task(bind=True, name="app.worker.run_document_extraction", acks_late=True, reject_on_worker_lost=True)
def run_document_extraction(self, pipeline_run_id: str, task_id: str | None = None, generation: str | None = None) -> None:
    # Legacy unfenced messages are not a bypass. Rollout requires draining them.
    if task_id is None or generation is None:
        return
    if not settings.file_processing_worker_runtime_id:
        raise AppError("file_processing_worker_identity_missing", "File-processing runtime identity is not configured", status_code=503)
    factory = get_session_factory()
    with factory.begin() as session:
        claim = claim_task(session, task_id=UUID(task_id), generation=UUID(generation),
            broker_task_id=UUID(self.request.id),
            worker_identity=f"{settings.file_processing_worker_runtime_id}:{os.getpid()}")
        if claim is None:
            return
        if claim.run_id != UUID(pipeline_run_id):
            raise ValueError("file_processing_task_run_mismatch")
    disposition = "yield"
    with _DocumentTaskHeartbeat(factory, claim), factory() as session:
        try:
            require_claim(session, claim)
            session.commit()
            pipeline = session.get(PipelineRun, claim.run_id)
            project = session.get(Project, pipeline.project_id)
            document = session.get(Document, pipeline.document_id)
            version = session.get(DocumentVersion, pipeline.document_version_id)
            pipeline.status = "running"
            pipeline.started_at = pipeline.started_at or datetime.now(UTC)
            version.status = "processing"
            session.commit()
            execute_auto_extraction(session=session, settings=settings, project=project, document=document,
                version=version, pipeline=pipeline, durable=True, execution_claim=claim)
            disposition = "completed" if pipeline.status == "submission_ready" else "failed" if pipeline.status == "failed" else "yield"
        except Exception as exc:
            session.rollback()
            if isinstance(exc, AppError) and exc.code == "file_processing_scope_stale":
                disposition = "cancelled"
                pipeline = session.get(PipelineRun, claim.run_id)
                if pipeline is not None:
                    pipeline.status = "failed"
                    pipeline.error_message = "Project state changed before extraction completed"
                    pipeline.completed_at = datetime.now(UTC)
                    session.commit()
            else:
                # No fabricated completion on an unclassified interruption.
                raise
    # All business calls are now closed; this is the last operation by this task.
    # A separate dispatcher finalizer verifies this receipt and releases the slot.
    with factory.begin() as session:
        quiesce_task(session, claim, disposition=disposition)


class _DocumentTaskHeartbeat:
    """A live heartbeat does not certify completion; no task body on this thread."""
    def __init__(self, factory, claim):
        self.factory, self.claim = factory, claim
        self.stop = Event()
        self.thread = Thread(target=self._loop, name="document-heartbeat", daemon=True)

    def _loop(self):
        while not self.stop.wait(max(1, settings.ingestion_worker_lease_seconds // 3)):
            try:
                with self.factory.begin() as session:
                    require_claim(session, self.claim, check_scope=False)
            except Exception:
                return  # Missing DB proof is handled fail-closed by the reconciler.

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise AppError("file_processing_heartbeat_stop_unconfirmed", "Task finalization requires confirmed shutdown", status_code=503)


@celery_app.task(name="app.worker.cleanup_authentication_retention")
def cleanup_authentication_retention() -> None:
    from app.services.auth_retention import cleanup_authentication
    with get_session_factory().begin() as session:
        cleanup_authentication(session)


@celery_app.task(name="app.worker.run_staging_retention", acks_late=True, reject_on_worker_lost=True)
def run_staging_retention(job_id: str) -> None:
    with get_session_factory()() as session:
        execute_retention(session, settings, UUID(job_id))


@celery_app.task(name="app.worker.recover_staging_retention")
def recover_staging_retention() -> None:
    with get_session_factory().begin() as session:
        recover_due_jobs(session, settings)
