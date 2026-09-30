from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from threading import Event, Thread
from uuid import UUID, uuid4

from celery import Celery
from celery.schedules import crontab
from celery.signals import heartbeat_sent, worker_ready
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import DataConnection, DataSyncRun, Document, DocumentVersion, IdentitySyncProviderResult, IdentitySyncRun, OutboxEvent, PipelineRun, Project, ValidationRun
from app.db.session import get_session_factory
from app.domain.data_sync import execute_data_source_sync, queue_due_scheduled_data_syncs
from app.domain.chunk_artifacts import RECONCILIATION_TOPIC, execute_chunk_artifact_reconciliation
from app.domain.extraction_pipeline import execute_auto_extraction
from app.domain.file_processing_dispatch import (TOPIC as DOCUMENT_TOPIC, claim_task, configured_capabilities,
    finalizable_task_ids, finalize_task, mark_stale_tasks, prepare_dispatch, quiesce_task, require_claim)
from app.domain.graph_sync_jobs import GRAPH_SYNC_TOPIC, execute_graph_sync_job
from app.domain.notifications import NOTIFICATION_TOPIC, execute_notification_event
from app.domain.project_archival import ARCHIVE_CLEANUP_TOPIC, execute_project_archive_cleanup, recover_stale_project_archive_runs
from app.domain.public_api_retention import enforce_public_api_retention
from app.domain.validation_runner import execute_validation_run
from app.integrations.keycloak import KeycloakAdminClient
from app.services.audit import add_audit
from app.services.identity_sync import reconcile_snapshot
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
celery_app.conf.timezone = settings.identity_sync_timezone
_minute, _hour, _day_of_month, _month_of_year, _day_of_week = settings.identity_sync_schedule.split()
celery_app.conf.beat_schedule = {
    "record-runtime-heartbeat": {"task": "app.worker.record_runtime_heartbeat", "schedule": float(settings.identity_sync_heartbeat_seconds)},
    "queue-daily-identity-sync": {"task": "app.worker.queue_scheduled_identity_sync", "schedule": crontab(minute=_minute, hour=_hour, day_of_month=_day_of_month, month_of_year=_month_of_year, day_of_week=_day_of_week)},
    "queue-scheduled-data-source-sync": {"task": "app.worker.queue_scheduled_data_source_sync", "schedule": 60.0},
    "dispatch-outbox": {"task": "app.worker.dispatch_outbox", "schedule": 10.0},
    "recover-stale-project-archive-runs": {"task": "app.worker.recover_stale_project_archives", "schedule": 60.0},
    "cleanup-public-api-retention": {"task": "app.worker.cleanup_public_api_retention", "schedule": 86400.0},
}


@worker_ready.connect
@heartbeat_sent.connect
def _record_worker_runtime_heartbeat(**_: object) -> None:
    try:
        record_worker_heartbeat(settings)
    except Exception:
        return


def _keycloak_client(*, timeout_seconds: float | None = None) -> KeycloakAdminClient:
    realm = settings.oidc_issuer_url.rstrip("/").rsplit("/", 1)[-1]
    return KeycloakAdminClient(
        base_url=settings.keycloak_admin_endpoint,
        realm=realm,
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
        timeout_seconds=timeout_seconds or 10.0,
    )


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


@celery_app.task(name="app.worker.run_identity_sync")
def run_identity_sync(run_id: str, lease_token: str | None = None) -> None:
    try:
        parsed_run_id = UUID(run_id)
        parsed_lease = UUID(lease_token) if lease_token else None
    except ValueError:
        return
    factory = get_session_factory()
    with factory.begin() as session:
        run = session.scalar(select(IdentitySyncRun).where(IdentitySyncRun.id == parsed_run_id).with_for_update())
        if run is None or run.status != "queued" or parsed_lease is None or run.lease_token != parsed_lease:
            return
        now = datetime.now(UTC)
        run.status = "running"
        run.phase = "provider_discovery"
        run.started_at = now
        run.heartbeat_at = now
        run.attempt += 1
    current_provider_id: str | None = None
    try:
        client = _keycloak_client(timeout_seconds=settings.identity_sync_keycloak_provider_timeout_seconds)
        with _IdentityRunHeartbeat(factory, parsed_run_id, parsed_lease, settings.identity_sync_heartbeat_seconds):
            providers = sorted(
                client.list_directory_providers(concurrency_key=settings.encryption_key_bytes),
                key=lambda provider: provider.id,
            )
            with factory.begin() as session:
                run = _active_identity_run_for_lease(session, parsed_run_id, parsed_lease)
                if run is None:
                    return
                requested_scope = run.requested_scope
                run_started_at = run.started_at or run.queued_at
                now = datetime.now(UTC)
                for provider in providers:
                    requested_people = run.requested_scope in {"people", "people_and_groups"}
                    requested_groups = run.requested_scope in {"groups", "people_and_groups"}
                    skipped = not provider.enabled
                    session.add(
                        IdentitySyncProviderResult(
                            run_id=run.id,
                            provider_id=provider.id,
                            provider_name=provider.name[:255],
                            provider_vendor=provider.vendor[:64],
                            requested_scope=run.requested_scope,
                            status="skipped" if skipped else "pending",
                            user_sync_status="skipped" if skipped and requested_people else "pending" if requested_people else "not_requested",
                            group_sync_status="skipped" if skipped and requested_groups else "pending" if requested_groups else "not_requested",
                            completed_at=now if skipped else None,
                            created_at=now,
                        )
                    )
                run.heartbeat_at = now

            for provider in providers:
                if not provider.enabled:
                    continue
                current_provider_id = provider.id
                with factory.begin() as session:
                    run = _active_identity_run_for_lease(session, parsed_run_id, parsed_lease)
                    result = _identity_provider_result(session, parsed_run_id, provider.id)
                    if run is None or result is None:
                        return
                    elapsed = (datetime.now(UTC) - run_started_at).total_seconds()
                    remaining = settings.identity_sync_run_timeout_seconds - elapsed
                    if remaining < 30:
                        raise AppError("identity_sync_run_budget_insufficient", "Identity synchronization has insufficient remaining runtime", status_code=504)
                    now = datetime.now(UTC)
                    result.status = "running"
                    result.started_at = now
                    result.heartbeat_at = now
                    run.heartbeat_at = now

                if requested_scope in {"people", "people_and_groups"}:
                    with factory.begin() as session:
                        run = _active_identity_run_for_lease(session, parsed_run_id, parsed_lease)
                        result = _identity_provider_result(session, parsed_run_id, provider.id)
                        if run is None or result is None:
                            return
                        run.phase = "provider_user_sync"
                        run.heartbeat_at = datetime.now(UTC)
                        result.user_sync_status = "running"
                        result.heartbeat_at = run.heartbeat_at
                    remaining = settings.identity_sync_run_timeout_seconds - (datetime.now(UTC) - run_started_at).total_seconds()
                    if remaining < 30:
                        raise AppError("identity_sync_run_budget_insufficient", "Identity synchronization has insufficient remaining runtime", status_code=504)
                    client.timeout_seconds = min(settings.identity_sync_keycloak_provider_timeout_seconds, remaining)
                    user_sync = client.trigger_directory_user_sync(provider.id)
                    with factory.begin() as session:
                        run = _active_identity_run_for_lease(session, parsed_run_id, parsed_lease)
                        result = _identity_provider_result(session, parsed_run_id, provider.id)
                        if run is None or result is None:
                            return
                        result.users_added = user_sync.added
                        result.users_updated = user_sync.updated
                        result.users_removed = user_sync.removed
                        result.users_failed = user_sync.failed
                        result.users_ignored = 0
                        result.user_sync_ignored = user_sync.ignored
                        result.user_sync_status = "failed" if user_sync.failed or user_sync.ignored else "succeeded"
                        result.heartbeat_at = datetime.now(UTC)
                        run.heartbeat_at = result.heartbeat_at
                    if user_sync.ignored:
                        raise AppError("keycloak_provider_sync_ignored", "Keycloak directory user synchronization was ignored", status_code=502)
                    if user_sync.failed:
                        raise AppError("keycloak_provider_sync_failed", "Keycloak directory user synchronization failed", status_code=502)

                if requested_scope in {"groups", "people_and_groups"}:
                    with factory.begin() as session:
                        run = _active_identity_run_for_lease(session, parsed_run_id, parsed_lease)
                        result = _identity_provider_result(session, parsed_run_id, provider.id)
                        if run is None or result is None:
                            return
                        run.phase = "provider_group_sync"
                        run.heartbeat_at = datetime.now(UTC)
                        result.group_sync_status = "running"
                        result.heartbeat_at = run.heartbeat_at
                    remaining = settings.identity_sync_run_timeout_seconds - (datetime.now(UTC) - run_started_at).total_seconds()
                    if remaining < 30:
                        raise AppError("identity_sync_run_budget_insufficient", "Identity synchronization has insufficient remaining runtime", status_code=504)
                    client.timeout_seconds = min(settings.identity_sync_keycloak_provider_timeout_seconds, remaining)
                    group_mappers = client.list_directory_group_mappers(provider.id)
                    if not group_mappers:
                        raise AppError("keycloak_group_mapper_missing", "Keycloak LDAP group mapper was not found", status_code=422)
                    if len(group_mappers) > 1:
                        raise AppError("keycloak_group_mapper_ambiguous", "Multiple Keycloak LDAP group mappers were found", status_code=422)
                    expected_group_path = settings.keycloak_ldap_group_path.rstrip("/") or "/"
                    if group_mappers[0].groups_path != expected_group_path:
                        raise AppError("keycloak_ldap_group_path_mismatch", "Keycloak LDAP group mapper path does not match deployment configuration", status_code=422)
                    remaining = settings.identity_sync_run_timeout_seconds - (datetime.now(UTC) - run_started_at).total_seconds()
                    if remaining < 30:
                        raise AppError("identity_sync_run_budget_insufficient", "Identity synchronization has insufficient remaining runtime", status_code=504)
                    client.timeout_seconds = min(settings.identity_sync_keycloak_provider_timeout_seconds, remaining)
                    client.trigger_directory_group_sync(provider.id, group_mappers[0].id)
                    with factory.begin() as session:
                        run = _active_identity_run_for_lease(session, parsed_run_id, parsed_lease)
                        result = _identity_provider_result(session, parsed_run_id, provider.id)
                        if run is None or result is None:
                            return
                        result.group_sync_status = "succeeded"
                        result.heartbeat_at = datetime.now(UTC)
                        run.heartbeat_at = result.heartbeat_at

                with factory.begin() as session:
                    run = _active_identity_run_for_lease(session, parsed_run_id, parsed_lease)
                    result = _identity_provider_result(session, parsed_run_id, provider.id)
                    if run is None or result is None:
                        return
                    now = datetime.now(UTC)
                    result.status = "succeeded"
                    result.completed_at = now
                    result.heartbeat_at = now
                    run.heartbeat_at = now
                    add_audit(
                        session,
                        actor_user_id=None,
                        action="identity_sync.provider.completed",
                        resource_type="identity_sync_provider_result",
                        resource_id=result.id,
                        result="success",
                        request_id=None,
                        summary={
                            "run_id": str(run.id),
                            "provider_id": provider.id,
                            "provider_name": provider.name[:255],
                            "provider_vendor": provider.vendor[:64],
                            "requested_scope": run.requested_scope,
                            "users_added": result.users_added,
                            "users_updated": result.users_updated,
                            "users_removed": result.users_removed,
                            "users_failed": result.users_failed,
                            "users_ignored": result.users_ignored,
                            "user_sync_ignored": result.user_sync_ignored,
                        },
                    )
                current_provider_id = None

            with factory.begin() as session:
                run = _active_identity_run_for_lease(session, parsed_run_id, parsed_lease)
                if run is None:
                    return
                run.phase = "snapshot_fetch"
                run.heartbeat_at = datetime.now(UTC)
            remaining = settings.identity_sync_run_timeout_seconds - (datetime.now(UTC) - run_started_at).total_seconds()
            if remaining < 30:
                raise AppError("identity_sync_run_budget_insufficient", "Identity synchronization has insufficient remaining runtime", status_code=504)
            client.timeout_seconds = min(settings.identity_sync_keycloak_provider_timeout_seconds, remaining)
            snapshot = client.snapshot()
            with factory.begin() as session:
                run = _active_identity_run_for_lease(session, parsed_run_id, parsed_lease)
                if run is None:
                    return
                run.phase = "reconciliation"
                run.heartbeat_at = datetime.now(UTC)
                reconcile_snapshot(
                    session,
                    run,
                    snapshot,
                    ldap_group_path=settings.keycloak_ldap_group_path,
                    break_glass_username=settings.break_glass_username,
                    requested_scope=run.requested_scope,
                )
                add_audit(
                    session,
                    actor_user_id=None,
                    action="worker.identity_sync.completed",
                    resource_type="identity_sync_run",
                    resource_id=run.id,
                    result="success",
                    request_id=None,
                    summary={
                        "requested_scope": run.requested_scope,
                        "provider_count": len(providers),
                        "users_created": run.users_created,
                        "users_updated": run.users_updated,
                        "users_disabled": run.users_disabled,
                        "groups_created": run.groups_created,
                        "groups_updated": run.groups_updated,
                        "role_memberships_updated": run.role_memberships_updated,
                        "attempt": run.attempt,
                    },
                )
    except Exception as exc:
        with factory.begin() as session:
            run = session.scalar(select(IdentitySyncRun).where(IdentitySyncRun.id == parsed_run_id).with_for_update())
            if run is not None and run.status in {"queued", "running"} and run.lease_token == parsed_lease:
                candidate_error_code = getattr(exc, "code", "identity_sync_failed")
                safe_error_code = candidate_error_code if isinstance(candidate_error_code, str) and 0 < len(candidate_error_code) <= 100 else "identity_sync_failed"
                run.status = "failed"
                run.phase = "failed"
                run.completed_at = datetime.now(UTC)
                run.error_code = safe_error_code
                run.error_message = "Identity synchronization failed"
                if current_provider_id:
                    provider_result = _identity_provider_result(session, parsed_run_id, current_provider_id)
                    if provider_result is not None:
                        provider_result.status = "failed"
                        provider_result.completed_at = run.completed_at
                        provider_result.heartbeat_at = run.completed_at
                        provider_result.error_code = safe_error_code
                        if provider_result.user_sync_status in {"pending", "running"}:
                            provider_result.user_sync_status = "failed"
                        if provider_result.group_sync_status in {"pending", "running"}:
                            provider_result.group_sync_status = "failed"
                add_audit(session, actor_user_id=None, action="worker.identity_sync.failed", resource_type="identity_sync_run", resource_id=run.id, result="failed", request_id=None, summary={"error_code": run.error_code, "attempt": run.attempt})


@celery_app.task(name="app.worker.queue_scheduled_identity_sync")
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
            OutboxEvent.topic.in_(("identity.sync.requested", "validation.run.requested", "data_source.sync.requested", GRAPH_SYNC_TOPIC, NOTIFICATION_TOPIC, RECONCILIATION_TOPIC, ARCHIVE_CLEANUP_TOPIC)),
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
                if event.topic == "identity.sync.requested":
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
        "identity.sync.requested": run_identity_sync,
        "validation.run.requested": run_project_chat_validation,
        "data_source.sync.requested": run_data_source_sync,
        GRAPH_SYNC_TOPIC: run_graph_sync,
        NOTIFICATION_TOPIC: run_notification_event,
        RECONCILIATION_TOPIC: run_chunk_artifact_reconciliation,
        ARCHIVE_CLEANUP_TOPIC: run_project_archive_cleanup,
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


@celery_app.task(name="app.worker.run_chunk_artifact_reconciliation", autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=3)
def run_chunk_artifact_reconciliation(version_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        execute_chunk_artifact_reconciliation(session, UUID(version_id), settings)


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
