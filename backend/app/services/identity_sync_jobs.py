from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import IdentitySetting, IdentitySyncProviderResult, IdentitySyncRun, OutboxEvent
from app.integrations.redis_ha import redis_client
from app.services.audit import add_audit


WORKER_HEARTBEAT_KEY = "nomosmart:runtime:celery-worker"
BEAT_HEARTBEAT_KEY = "nomosmart:runtime:celery-beat"


def _redis(settings: Settings) -> Redis:
    return redis_client(
        settings,
        url=settings.celery_broker_url.get_secret_value(),
    )


def record_worker_heartbeat(settings: Settings) -> None:
    ttl = max(60, settings.identity_sync_heartbeat_seconds * 3)
    client = _redis(settings)
    try:
        client.set(WORKER_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=ttl)
    finally:
        client.close()


def record_beat_heartbeat(settings: Settings) -> None:
    ttl = max(60, settings.identity_sync_heartbeat_seconds * 3)
    client = _redis(settings)
    try:
        client.set(BEAT_HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=ttl)
    finally:
        client.close()


def identity_runtime_status(settings: Settings) -> dict[str, bool]:
    client = _redis(settings)
    try:
        values = client.mget(WORKER_HEARTBEAT_KEY, BEAT_HEARTBEAT_KEY)
        return {"worker_available": values[0] is not None, "beat_available": values[1] is not None}
    except RedisError:
        return {"worker_available": False, "beat_available": False}
    finally:
        client.close()


def recover_stale_identity_runs(
    session: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
    request_id: str | None = None,
) -> list[UUID]:
    current = now or datetime.now(UTC)
    rows = list(
        session.scalars(
            select(IdentitySyncRun)
            .where(IdentitySyncRun.status.in_(("queued", "running")))
            .with_for_update()
        )
    )
    recovered: list[UUID] = []
    for run in rows:
        if run.status == "queued":
            stale = run.queued_at <= current - timedelta(seconds=settings.identity_sync_queue_timeout_seconds)
            error_code = "identity_sync_queue_timeout"
        else:
            evidence = run.heartbeat_at or run.started_at or run.queued_at
            stale = evidence <= current - timedelta(seconds=settings.identity_sync_run_timeout_seconds)
            error_code = "identity_sync_heartbeat_timeout"
        if not stale:
            continue
        run.status = "failed"
        run.phase = "failed"
        run.completed_at = current
        run.error_code = error_code
        run.error_message = "Identity synchronization timed out"
        provider_results = list(
            session.scalars(
                select(IdentitySyncProviderResult)
                .where(
                    IdentitySyncProviderResult.run_id == run.id,
                    IdentitySyncProviderResult.status.in_(("pending", "running")),
                )
                .with_for_update()
            )
        )
        for provider_result in provider_results:
            provider_result.status = "failed"
            provider_result.completed_at = current
            provider_result.heartbeat_at = current
            provider_result.error_code = error_code
            if provider_result.user_sync_status in {"pending", "running"}:
                provider_result.user_sync_status = "failed"
            if provider_result.group_sync_status in {"pending", "running"}:
                provider_result.group_sync_status = "failed"
        recovered.append(run.id)
        add_audit(
            session,
            actor_user_id=None,
            action="identity_sync.recover_stale",
            resource_type="identity_sync_run",
            resource_id=run.id,
            result="failed",
            request_id=request_id,
            summary={"error_code": error_code, "attempt": run.attempt},
        )
    return recovered


def active_identity_run(session: Session, *, lock: bool = False) -> IdentitySyncRun | None:
    statement = select(IdentitySyncRun).where(IdentitySyncRun.status.in_(("queued", "running")))
    if lock:
        statement = statement.with_for_update()
    return session.scalar(statement)


def effective_identity_sync_scope(session: Session, settings: Settings) -> str:
    current = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
    configured = (current.configuration or {}).get("sync_scope") if current is not None else None
    if configured in {"people", "groups", "people_and_groups"}:
        return str(configured)
    return settings.identity_sync_scope


def create_identity_sync_run(
    session: Session,
    *,
    trigger_type: str,
    actor_user_id: UUID | None,
    request_id: str | None,
    requested_scope: str,
    now: datetime | None = None,
) -> IdentitySyncRun:
    current = now or datetime.now(UTC)
    existing = active_identity_run(session, lock=True)
    if existing is not None:
        raise AppError(
            "identity_sync_already_running",
            "Identity synchronization is already queued or running",
            status_code=409,
            details={"run_id": str(existing.id), "status": existing.status},
        )
    lease_token = uuid4()
    run = IdentitySyncRun(
        source="keycloak",
        trigger_type=trigger_type,
        status="queued",
        requested_scope=requested_scope,
        phase="queued",
        queued_at=current,
        heartbeat_at=None,
        lease_token=lease_token,
        users_created=0,
        users_updated=0,
        users_disabled=0,
        groups_created=0,
        groups_updated=0,
        role_memberships_updated=0,
        attempt=0,
    )
    session.add(run)
    session.flush()
    session.add(
        OutboxEvent(
            topic="identity.sync.requested",
            aggregate_type="identity_sync_run",
            aggregate_id=run.id,
            payload={"run_id": str(run.id), "lease_token": str(lease_token)},
            status="pending",
            attempts=0,
            available_at=current,
            created_at=current,
        )
    )
    add_audit(
        session,
        actor_user_id=actor_user_id,
        action="identity_sync.queue",
        resource_type="identity_sync_run",
        resource_id=run.id,
        result="success",
        request_id=request_id,
        summary={"trigger_type": trigger_type, "requested_scope": requested_scope},
    )
    return run
