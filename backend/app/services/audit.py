from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import AuditLog


SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "private_key", "credential"}


def sanitize_summary(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS) else sanitize_summary(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_summary(item) for item in value]
    return value


def add_audit(
    session: Session,
    *,
    actor_user_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    result: str,
    request_id: str | None,
    summary: dict[str, object] | None = None,
) -> AuditLog:
    row = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        request_id=request_id,
        summary=sanitize_summary(summary or {}),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    return row

