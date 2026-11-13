"""Knowledge tag details for chunks and document versions, shared by document and approval routes (OPT424-021)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import KnowledgeTagResponse
from app.db.models import ChunkTag, DocumentVersionTag, Tag


def tag_details_query(session: Session, source_model, link_filter) -> list[KnowledgeTagResponse]:
    rows = session.execute(select(source_model, Tag).join(Tag, source_model.tag_id == Tag.id).where(link_filter, source_model.source != "rule").order_by(Tag.name)).all()
    return [
        KnowledgeTagResponse(
            tag_id=tag.id,
            tag_text=tag.name,
            source=link.source,
            confidence_score=float(link.confidence_score) if link.confidence_score is not None else None,
            metadata=link.metadata_ or {},
            created_by=link.created_by,
            created_at=link.created_at,
        )
        for link, tag in rows
    ]


def chunk_tag_details(session: Session, chunk_id: UUID) -> list[KnowledgeTagResponse]:
    return tag_details_query(session, ChunkTag, ChunkTag.chunk_id == chunk_id)


def document_tag_details(session: Session, version_id: UUID) -> list[KnowledgeTagResponse]:
    return tag_details_query(session, DocumentVersionTag, DocumentVersionTag.document_version_id == version_id)
