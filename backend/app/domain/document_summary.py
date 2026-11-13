"""Batch, authorized document/version presentation metadata (no writes)."""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, DocumentVersion, User


def document_summary_metadata(session: Session, project_id: UUID, document_ids: list[UUID]) -> dict:
    if not document_ids:
        return {"versions": {}, "creators": {}}
    versions = list(session.scalars(select(DocumentVersion).where(
        DocumentVersion.project_id == project_id, DocumentVersion.document_id.in_(document_ids))))
    ids = [version.id for version in versions]
    counts = dict(session.execute(select(Chunk.document_version_id, func.count(Chunk.id)).where(
        Chunk.project_id == project_id, Chunk.document_version_id.in_(ids), Chunk.status == "active"
    ).group_by(Chunk.document_version_id)).all()) if ids else {}
    documents = list(session.scalars(select(Document).where(Document.project_id == project_id, Document.id.in_(document_ids))))
    by_document = {item.id: item for item in documents}
    creators = {}
    for version in versions:
        actor = (version.chunk_strategy or {}).get("version_created_by")
        try:
            creators[version.id] = UUID(actor) if isinstance(actor, str) else None
        except ValueError:
            creators[version.id] = None
        document = by_document.get(version.document_id)
        if not creators[version.id] and document and version.version_major == 1 and version.extraction_revision == 0 and version.created_at == document.created_at:
            creators[version.id] = document.created_by
    # OPT424-016 / D424-11: creators are recorded on the version (backfilled by V060);
    # audit_logs are no longer read here. Versions without a record stay unknown.
    user_ids = {item.created_by for item in documents} | set(creators.values())
    user_ids.discard(None)
    # Only names of authors of the already-scoped documents; never enumerate users.
    names = dict(session.execute(select(User.id, User.display_name).where(User.id.in_(user_ids))).all()) if user_ids else {}
    return {
        "versions": {v.id: {"active_chunk_count": counts.get(v.id, 0),
                            "created_by": creators.get(v.id), "created_by_name": names.get(creators.get(v.id))}
                     for v in versions},
        "creators": {d.id: names.get(d.created_by) for d in documents},
    }
