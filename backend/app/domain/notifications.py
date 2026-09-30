from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Notification, NotificationEvent, OutboxEvent, Project, User
from app.services.audit import add_audit


NOTIFICATION_TOPIC = "notification.event.requested"


def emit_notification_event(
    session: Session,
    *,
    project_id: UUID | None,
    event_type: str,
    business_key: str,
    recipient_user_ids: list[UUID],
    severity: str,
    title: str,
    message: str,
    action_type: str | None,
    action_payload: dict,
    terminal: bool = False,
) -> NotificationEvent | None:
    recipients = sorted({str(item) for item in recipient_user_ids})
    if not recipients:
        return None
    payload = {
        "severity": severity,
        "title": title,
        "message": message,
        "action_type": action_type,
        "action_payload": action_payload,
    }
    identity = json.dumps(
        {
            "project_id": str(project_id) if project_id else None,
            "event_type": event_type,
            "business_key": business_key,
            "recipients": recipients,
            "payload": payload,
            "terminal": terminal,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    dedupe_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    existing = session.scalar(select(NotificationEvent).where(NotificationEvent.dedupe_key == dedupe_key))
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    event = NotificationEvent(
        id=uuid4(),
        project_id=project_id,
        event_type=event_type,
        business_key=business_key,
        dedupe_key=dedupe_key,
        recipient_user_ids=recipients,
        payload=payload,
        terminal=terminal,
        status="queued",
        attempts=0,
        created_at=now,
    )
    session.add(event)
    session.flush()
    project_generation = session.get(Project, project_id).work_generation if project_id is not None and session.get(Project, project_id) is not None else None
    session.add(
        OutboxEvent(
            id=uuid4(),
            topic=NOTIFICATION_TOPIC,
            aggregate_type="notification_event",
            aggregate_id=event.id,
            project_id=project_id,
            project_generation=project_generation,
            payload={"notification_event_id": str(event.id)},
            status="pending",
            attempts=0,
            available_at=now,
            created_at=now,
        )
    )
    return event


def execute_notification_event(session: Session, event_id: UUID) -> None:
    event = session.scalar(select(NotificationEvent).where(NotificationEvent.id == event_id).with_for_update())
    if event is None or event.status == "completed":
        return
    if event.status not in {"queued", "failed"}:
        return
    now = datetime.now(UTC)
    event.status = "running"
    event.attempts += 1
    payload = event.payload or {}
    recipient_ids = []
    for raw_id in event.recipient_user_ids or []:
        try:
            recipient_ids.append(UUID(str(raw_id)))
        except ValueError:
            continue
    active_ids = set(session.scalars(select(User.id).where(User.id.in_(recipient_ids), User.is_active.is_(True)))) if recipient_ids else set()
    if event.terminal and active_ids:
        for notification in session.scalars(
            select(Notification).where(
                Notification.business_key == event.business_key,
                Notification.recipient_user_id.in_(active_ids),
                Notification.resolved_at.is_(None),
            )
        ):
            notification.resolved_at = now
            notification.resolved_reason = f"terminal:{event.event_type}"
    for recipient_id in active_ids:
        existing = session.scalar(
            select(Notification.id).where(
                Notification.source_event_id == event.id,
                Notification.recipient_user_id == recipient_id,
            )
        )
        if existing is not None:
            continue
        session.add(
            Notification(
                source_event_id=event.id,
                recipient_user_id=recipient_id,
                project_id=event.project_id,
                notification_type=event.event_type,
                severity=str(payload.get("severity") or "info"),
                title=str(payload.get("title") or ""),
                message=str(payload.get("message") or ""),
                action_type=payload.get("action_type"),
                action_payload=payload.get("action_payload") if isinstance(payload.get("action_payload"), dict) else {},
                business_key=event.business_key,
                is_read=False,
                created_at=event.created_at,
            )
        )
    event.status = "completed"
    event.completed_at = now
    event.error_code = None
    add_audit(
        session,
        actor_user_id=None,
        action="notification.event.completed",
        resource_type="notification_event",
        resource_id=event.id,
        result="success",
        request_id=None,
        summary={"event_type": event.event_type, "recipient_count": len(active_ids), "terminal": event.terminal},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = session.get(NotificationEvent, event_id)
        if replay is not None:
            replay.status = "completed"
            replay.completed_at = now
            session.commit()


def resolve_business_notifications(session: Session, *, business_key: str, reason: str) -> int:
    now = datetime.now(UTC)
    rows = list(
        session.scalars(
            select(Notification).where(
                Notification.business_key == business_key,
                Notification.resolved_at.is_(None),
            )
        )
    )
    for row in rows:
        row.resolved_at = now
        row.resolved_reason = reason
    return len(rows)
