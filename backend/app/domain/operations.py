from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.schemas import OperationComponentStatus, OperationRecentError, OperationsStatusResponse
from app.core.config import Settings
from app.db.models import AIModel, ActiveVersionManifest, AuditLog, OutboxEvent, ValidationRun
from app.integrations.health import DependencyStatus, check_dependencies
from app.services.identity_sync_jobs import identity_runtime_status


DEGRADED_STATUSES = {"degraded", "unavailable"}
EXTERNAL_CREDENTIAL_PROVIDERS = {"openai", "gemini", "claude", "anthropic"}


def _now() -> datetime:
    return datetime.now(UTC)


def _overall(components: list[OperationComponentStatus]) -> str:
    if any(component.status == "unavailable" for component in components):
        return "unavailable"
    if any(component.status == "degraded" for component in components):
        return "degraded"
    return "healthy"


def dependency_component(status: DependencyStatus, checked_at: datetime | None = None) -> OperationComponentStatus:
    return OperationComponentStatus(
        name=status.name,
        status=status.status,
        detail_code=status.detail,
        checked_at=checked_at or _now(),
        metrics={},
    )


def _provider_components(session: Session, checked_at: datetime) -> list[OperationComponentStatus]:
    models = list(session.scalars(select(AIModel).where(AIModel.is_active.is_(True), AIModel.deleted_at.is_(None)).order_by(AIModel.model_type, AIModel.name)))
    components: list[OperationComponentStatus] = []
    for model_type in ("Chat", "Embedding", "Judge", "OCR"):
        candidates = [model for model in models if model.model_type.lower() == model_type.lower()]
        default = next((model for model in candidates if model.is_default), None)
        selected = default or (candidates[0] if candidates else None)
        if selected is None:
            components.append(OperationComponentStatus(name=f"provider.{model_type.lower()}", status="degraded", detail_code="config_missing", checked_at=checked_at, metrics={"active_models": 0}))
            continue
        provider_key = selected.provider.lower()
        credential_required = provider_key in EXTERNAL_CREDENTIAL_PROVIDERS
        credential_missing = credential_required and not selected.api_key_configured
        status = "degraded" if credential_missing or default is None else "healthy"
        detail = "credential_missing" if credential_missing else ("default_missing" if default is None else "configured")
        components.append(
            OperationComponentStatus(
                name=f"provider.{model_type.lower()}",
                status=status,
                detail_code=detail,
                checked_at=checked_at,
                metrics={"active_models": len(candidates), "default_configured": bool(default), "credential_configured": bool(selected.api_key_configured)},
            )
        )
    return components


def _queue_component(session: Session, checked_at: datetime) -> OperationComponentStatus:
    pending = int(session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "pending")) or 0)
    failed = int(session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "failed")) or 0)
    processed_at = session.scalar(select(func.max(OutboxEvent.processed_at)))
    status = "healthy"
    detail = "empty" if pending == 0 else "pending"
    if failed:
        status, detail = "degraded", "failed_events_present"
    elif pending > 100:
        status, detail = "degraded", "queue_depth_high"
    return OperationComponentStatus(
        name="queue.outbox",
        status=status,
        detail_code=detail,
        checked_at=checked_at,
        metrics={"pending": pending, "failed": failed, "last_processed_at": processed_at.isoformat() if processed_at else None},
    )


def _worker_component(session: Session, queue: OperationComponentStatus, checked_at: datetime, settings: Settings) -> OperationComponentStatus:
    running_validations = int(session.scalar(select(func.count()).select_from(ValidationRun).where(ValidationRun.status.in_(("queued", "running")))) or 0)
    failed_validations = int(session.scalar(select(func.count()).select_from(ValidationRun).where(ValidationRun.status.in_(("failed", "final_failed")))) or 0)
    runtime = identity_runtime_status(settings)
    if not runtime["worker_available"]:
        status, detail = "unavailable", "worker_heartbeat_missing"
    elif not runtime["beat_available"]:
        status, detail = "degraded", "beat_heartbeat_missing"
    elif queue.status in DEGRADED_STATUSES:
        status, detail = "degraded", "queue_degraded"
    elif failed_validations:
        status, detail = "degraded", "validation_failures_present"
    else:
        status, detail = "healthy", "runtime_heartbeat_current"
    return OperationComponentStatus(
        name="worker.celery",
        status=status,
        detail_code=detail,
        checked_at=checked_at,
        metrics={
            "running_validations": running_validations,
            "failed_validations": failed_validations,
            "pending_outbox": queue.metrics.get("pending", 0),
            **runtime,
        },
    )


def _retrieval_component(session: Session, checked_at: datetime) -> OperationComponentStatus:
    total = int(session.scalar(select(func.count()).select_from(ActiveVersionManifest)) or 0)
    ready = int(session.scalar(select(func.count()).select_from(ActiveVersionManifest).where(ActiveVersionManifest.index_ready.is_(True))) or 0)
    if total == 0:
        status, detail = "degraded", "active_manifest_missing"
    elif ready < total:
        status, detail = "degraded", "index_not_ready"
    else:
        status, detail = "healthy", "index_ready"
    return OperationComponentStatus(name="retrieval.index", status=status, detail_code=detail, checked_at=checked_at, metrics={"active_manifests": total, "index_ready": ready})


def _recent_errors(session: Session) -> list[OperationRecentError]:
    rows = list(session.scalars(select(AuditLog).where(AuditLog.result != "success").order_by(desc(AuditLog.created_at)).limit(10)))
    errors: list[OperationRecentError] = []
    for row in rows:
        summary: dict[str, Any] = row.summary or {}
        detail_code = str(summary.get("error_code") or summary.get("code") or row.result)
        errors.append(OperationRecentError(source=row.resource_type, action=row.action, result=row.result, detail_code=detail_code, created_at=row.created_at))
    return errors


def build_operations_status(session: Session, settings: Settings) -> OperationsStatusResponse:
    checked_at = _now()
    dependencies = [dependency_component(status, checked_at) for status in check_dependencies(settings)]
    providers = _provider_components(session, checked_at)
    queue = _queue_component(session, checked_at)
    worker = _worker_component(session, queue, checked_at, settings)
    retrieval = _retrieval_component(session, checked_at)
    components = [*dependencies, *providers, queue, worker, retrieval]
    return OperationsStatusResponse(
        status=_overall(components),
        generated_at=checked_at,
        dependencies=dependencies,
        providers=providers,
        worker=worker,
        queue=queue,
        retrieval=retrieval,
        recent_errors=_recent_errors(session),
    )
