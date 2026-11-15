"""CHG-426 REL426-021: concurrency-safe project tag lookup/creation."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Tag


def get_or_create_project_tag(session: Session, project_id: UUID, name: str) -> Tag:
    """Return the project's tag with this exact (already normalized) name, creating it if absent.

    Concurrent extractions that create the same new tag must share one row instead of
    aborting on tags_project_id_name_key, so the insert is an upsert followed by a read.
    """
    tag = session.scalar(select(Tag).where(Tag.project_id == project_id, Tag.name == name))
    if tag is not None:
        return tag
    session.execute(insert(Tag).values(id=uuid4(), project_id=project_id, name=name, created_at=datetime.now(UTC))
                    .on_conflict_do_nothing(index_elements=[Tag.project_id, Tag.name]))
    return session.scalar(select(Tag).where(Tag.project_id == project_id, Tag.name == name)
                          .execution_options(populate_existing=True))
