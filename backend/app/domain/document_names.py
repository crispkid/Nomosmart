"""CHG-442 REN442-001/004: document names are edited per document and unique site-wide.

Names are compared by `title_key` (NFKC, trimmed, lower-case, no extension). Live documents
(`is_deleted = false`) count, inactive ones included; project references share their
source's name and are exempt. V064 backs this with a partial unique index; the advisory
lock below serialises concurrent checks so a race gets the same friendly error.
"""
from __future__ import annotations

import unicodedata
from uuid import UUID

from sqlalchemy import select, text

from app.core.errors import AppError
from app.db.models import Document, Project, ProjectOwner, User

MAX_DOCUMENT_TITLE_LENGTH = 200
REFERENCE_SOURCE_TYPE = "project_reference"


def title_key(title: str) -> str:
    return unicodedata.normalize("NFKC", title).strip().lower()


def validate_title(raw: str) -> str:
    """Return the cleaned name or raise `document_title_invalid` (REN442-001)."""
    title = unicodedata.normalize("NFC", raw or "").strip()
    if (not title or len(title) > MAX_DOCUMENT_TITLE_LENGTH or any(ch in title for ch in "/\\")
            or any(not ch.isprintable() for ch in title) or not title.strip(" .")):
        raise AppError("document_title_invalid", "Document name is invalid", status_code=422,
                       details={"max_length": MAX_DOCUMENT_TITLE_LENGTH})
    return title


def _lock(session, key: str) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 442))"), {"k": key})


def _duplicate_error(session, existing: Document, visible_project_ids: set[UUID] | None) -> AppError:
    project = session.get(Project, existing.project_id)
    owners = session.scalars(select(User.display_name).join(ProjectOwner, ProjectOwner.user_id == User.id)
                             .where(ProjectOwner.project_id == existing.project_id).order_by(User.display_name)).all()
    visible = visible_project_ids is not None and existing.project_id in visible_project_ids
    details = {"project_name": project.name if project else None, "project_owners": list(owners),
               "can_reference": visible}
    if visible:
        details.update(project_id=str(existing.project_id), document_id=str(existing.id))
    return AppError("document_title_duplicate", "A document with this name already exists", status_code=409, details=details)


def ensure_title_available(session, title: str, *, visible_project_ids: set[UUID] | None,
                           exclude_document_id: UUID | None = None, source_type: str | None = None) -> str:
    """Lock and check the name; return its key. References never conflict (G2-A)."""
    key = title_key(title)
    if source_type == REFERENCE_SOURCE_TYPE:
        return key
    _lock(session, key)
    query = select(Document).where(Document.title_key == key, Document.is_deleted.is_(False),
                                   Document.source_type != REFERENCE_SOURCE_TYPE)
    if exclude_document_id is not None:
        query = query.where(Document.id != exclude_document_id)
    existing = session.scalar(query.order_by(Document.created_at).limit(1))
    if existing is not None:
        raise _duplicate_error(session, existing, visible_project_ids)
    return key

