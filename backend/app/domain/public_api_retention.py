from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatFeedbackEvent, PublicApiRequestLog


def enforce_public_api_retention(session: Session, *, now: datetime | None = None, batch_size: int = 500) -> dict[str, int]:
    effective_now = now or datetime.now(UTC)
    redacted = 0
    tombstoned = 0
    rows = list(
        session.scalars(
            select(PublicApiRequestLog)
            .where(
                PublicApiRequestLog.legal_hold.is_(False),
                PublicApiRequestLog.deleted_at.is_(None),
                PublicApiRequestLog.content_expires_at <= effective_now,
            )
            .order_by(PublicApiRequestLog.content_expires_at)
            .with_for_update(skip_locked=True)
            .limit(batch_size)
        )
    )
    for row in rows:
        row.question = None
        row.answer = None
        row.citations = []
        row.question_encrypted = None
        row.answer_encrypted = None
        row.citations_encrypted = None
        row.end_user_metadata_encrypted = None
        row.redacted_at = row.redacted_at or effective_now
        redacted += 1
        if row.retention_expires_at is not None and row.retention_expires_at <= effective_now:
            row.end_user_employee_id = ""
            row.end_user_employee_name = None
            row.end_user_department = None
            row.end_user_identity_hash = None
            row.request_hash = None
            row.idempotency_key_hash = None
            row.error_message = None
            row.metadata_ = {"retention_tombstone": True}
            row.deleted_at = effective_now
            feedback = list(session.scalars(select(ChatFeedbackEvent).where(ChatFeedbackEvent.public_response_id == row.id)))
            for event in feedback:
                event.comment = None
                event.end_user_employee_id = None
                event.end_user_employee_name = None
                event.end_user_department = None
                event.end_user_identity_hash = None
                event.end_user_metadata_encrypted = None
                event.idempotency_key_hash = None
            tombstoned += 1
    session.commit()
    return {"redacted": redacted, "tombstoned": tombstoned}
