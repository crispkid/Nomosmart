from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentReference, DocumentReferenceEvent, ProjectMember, ProjectOwner, User
from app.domain.notifications import emit_notification_event


def create_source_reference_events(
    session: Session,
    *,
    source_document: Document,
    event_type: str,
    old_source_version_id: UUID | None = None,
    new_source_version_id: UUID | None = None,
    message: str | None = None,
) -> list[DocumentReferenceEvent]:
    references = list(
        session.scalars(
            select(DocumentReference).where(
                DocumentReference.source_document_id == source_document.id,
                DocumentReference.status == "active",
                DocumentReference.reference_mode == "linked",
            )
        )
    )
    now = datetime.now(UTC)
    events: list[DocumentReferenceEvent] = []
    for reference in references:
        event = DocumentReferenceEvent(
            id=uuid4(),
            reference_id=reference.id,
            event_type=event_type,
            source_project_id=reference.source_project_id,
            source_document_id=reference.source_document_id,
            old_source_version_id=old_source_version_id,
            new_source_version_id=new_source_version_id,
            message=message or _event_message(event_type, source_document.title),
            is_read=False,
            created_at=now,
        )
        session.add(event)
        _create_reference_event_notifications(session, reference=reference, event=event, source_document=source_document)
        events.append(event)
    return events


def _event_message(event_type: str, title: str) -> str:
    if event_type == "source_updated":
        return f"Source document '{title}' has a newer version available."
    if event_type == "source_deactivated":
        return f"Source document '{title}' was deactivated."
    if event_type == "source_activated":
        return f"Source document '{title}' was activated."
    if event_type == "source_deleted":
        return f"Source document '{title}' was deleted."
    return f"Source document '{title}' changed."


def _create_reference_event_notifications(session: Session, *, reference: DocumentReference, event: DocumentReferenceEvent, source_document: Document) -> None:
    recipient_ids = _target_reference_recipient_ids(session, reference)
    if not recipient_ids:
        return
    title, message = _notification_copy(reference=reference, event=event, source_document=source_document)
    emit_notification_event(
        session,
        project_id=reference.target_project_id,
        event_type="reference_source_event",
        business_key=f"document-reference:{reference.id}",
        recipient_user_ids=recipient_ids,
        severity=_notification_severity(event.event_type),
        title=title,
        message=message,
        action_type="sync" if event.event_type in {"source_updated", "source_activated"} else "view",
        action_payload={
            "event_id": str(event.id),
            "reference_id": str(reference.id),
            "target_project_id": str(reference.target_project_id),
            "target_document_id": str(reference.target_document_id),
            "event_type": event.event_type,
        },
    )


def _target_reference_recipient_ids(session: Session, reference: DocumentReference) -> list[UUID]:
    target_document = session.get(Document, reference.target_document_id)
    raw_ids = {
        *session.scalars(select(ProjectOwner.user_id).where(ProjectOwner.project_id == reference.target_project_id)).all(),
        *session.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == reference.target_project_id, ProjectMember.project_role.in_(("owner", "editor")))).all(),
    }
    if target_document and target_document.created_by:
        raw_ids.add(target_document.created_by)
    if not raw_ids:
        return []
    return list(session.scalars(select(User.id).where(User.id.in_(raw_ids), User.is_active.is_(True)).order_by(User.display_name)))


def _notification_copy(*, reference: DocumentReference, event: DocumentReferenceEvent, source_document: Document) -> tuple[str, str]:
    source_project = reference.source_project_name_snapshot or "Source project"
    source_title = reference.source_document_name_snapshot or source_document.title
    if event.event_type == "source_updated":
        return (
            "Referenced source document updated",
            f"{source_project} / {source_title} has a newer source version. The target project was not updated automatically.",
        )
    if event.event_type == "source_deactivated":
        return (
            "Referenced source document deactivated",
            f"{source_project} / {source_title} was deactivated. Review the referenced document before using or updating it.",
        )
    if event.event_type == "source_activated":
        return (
            "Referenced source document reactivated",
            f"{source_project} / {source_title} was reactivated. You can review whether to update the referenced document.",
        )
    if event.event_type == "source_deleted":
        return (
            "Referenced source document deleted",
            f"{source_project} / {source_title} was deleted. Existing target-project extraction remains unchanged.",
        )
    return (
        "Referenced source document changed",
        f"{source_project} / {source_title} changed. Review the referenced document before taking action.",
    )


def _notification_severity(event_type: str) -> str:
    if event_type in {"source_deleted", "source_deactivated"}:
        return "critical"
    if event_type in {"source_updated", "source_activated"}:
        return "warning"
    return "info"
