"""CHG-442 REF442-001..005: textual references from chunks to other documents of the same project.

Rules only (DD442-01, no Chat LLM): titles in 《…》 and regulation names after 依／依據／依照／
參照／參考／詳見／請見／比照／準用. A reference resolves when its normalized name equals the
normalized name of exactly one other live document of the project; failing that, when exactly
one such document name contains it or is contained in it (at least 4 characters). Several
candidates keep it unresolved (DD442-08). These rows are unrelated to `DocumentReference`
(cross-project linked documents).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.db.models import Chunk, ChunkReference, Document, DocumentVersion

DOC_KINDS = "辦法|規定|規則|準則|手冊|要點|細則|制度|政策|章程|條例|守則|須知|規範|程序書|作業說明|程序"
_NAME = rf"[《「〈]?([^，。；、：\s《》「」〈〉()（）]{{2,30}}?(?:{DOC_KINDS}))[》」〉]?"
PATTERNS = (
    re.compile(r"《([^》\n]{2,60})》"),
    re.compile(rf"依(?:據|照)?\s*{_NAME}"),
    re.compile(rf"(?:參照|參考|詳見|請見|比照|準用)\s*{_NAME}"),
)
_EXTENSION = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|txt|md|markdown|html?|csv)$", re.I)
MIN_CONTAINMENT_LENGTH = 4
MAX_RAW_LENGTH = 500


@dataclass(frozen=True)
class FoundReference:
    raw_text: str
    start: int
    end: int
    key: str


def reference_key(name: str) -> str:
    value = unicodedata.normalize("NFKC", name or "").strip()
    value = _EXTENSION.sub("", value).strip("《》「」〈〉 ")
    return re.sub(r"\s+", "", value).lower()


def find_references(text: str) -> list[FoundReference]:
    """Each text span yields at most one reference; 依《員工手冊》 counts once."""
    found: list[FoundReference] = []
    taken: list[tuple[int, int]] = []
    for pattern in PATTERNS:
        for match in pattern.finditer(text or ""):
            start, end = match.span(1)
            if any(start < t_end and t_start < end for t_start, t_end in taken):
                continue
            key = reference_key(match.group(1))
            if len(key) < 2:
                continue
            taken.append((start, end))
            found.append(FoundReference(match.group(1)[:MAX_RAW_LENGTH], start, end, key[:MAX_RAW_LENGTH]))
    return sorted(found, key=lambda item: item.start)


def project_name_index(session, project_id: UUID) -> dict[str, list[UUID]]:
    index: dict[str, list[UUID]] = {}
    for doc_id, title in session.execute(select(Document.id, Document.title).where(
            Document.project_id == project_id, Document.is_deleted.is_(False))):
        index.setdefault(reference_key(title), []).append(doc_id)
    return index


def resolve_key(index: dict[str, list[UUID]], key: str, source_document_id: UUID) -> UUID | None:
    exact = [doc for doc in index.get(key, []) if doc != source_document_id]
    if exact:
        return exact[0] if len(exact) == 1 else None
    if len(key) < MIN_CONTAINMENT_LENGTH:
        return None
    partial = {doc for name, docs in index.items() if len(name) >= MIN_CONTAINMENT_LENGTH and (key in name or name in key)
               for doc in docs if doc != source_document_id}
    return next(iter(partial)) if len(partial) == 1 else None


def _add_rule_references(session, version: DocumentVersion, chunk: Chunk, index: dict[str, list[UUID]],
                         actor_user_id: UUID | None, now: datetime) -> tuple[int, int]:
    added = resolved = 0
    for item in find_references(chunk.content):
        target = resolve_key(index, item.key, version.document_id)
        session.add(ChunkReference(
            id=uuid4(), project_id=version.project_id, document_id=version.document_id, document_version_id=version.id,
            chunk_id=chunk.id, raw_text=item.raw_text, start_offset=item.start, end_offset=item.end,
            normalized_name=item.key, status="resolved" if target else "unresolved", target_document_id=target,
            source="rule", is_deleted=False, created_by=actor_user_id, updated_by=actor_user_id, lock_version=1,
            created_at=now, updated_at=now))
        added += 1
        resolved += target is not None
    return added, resolved


def extract_version_references(session, version: DocumentVersion, *, actor_user_id: UUID | None = None) -> dict[str, int]:
    """Extraction step: add rule references for active chunks that have none yet. Existing rows (manual
    or removed ones included) are left untouched so human corrections survive re-runs."""
    chunks = session.scalars(select(Chunk).where(Chunk.document_version_id == version.id, Chunk.status == "active")).all()
    handled = set(session.scalars(select(ChunkReference.chunk_id).where(ChunkReference.document_version_id == version.id)).all())
    index = project_name_index(session, version.project_id)
    now = datetime.now(UTC)
    added = resolved = 0
    for chunk in chunks:
        if chunk.id not in handled:
            counts = _add_rule_references(session, version, chunk, index, actor_user_id, now)
            added, resolved = added + counts[0], resolved + counts[1]
    session.flush()
    return {"chunks": len(chunks), "added": added, "resolved": resolved}


def carry_chunk_references(session, version: DocumentVersion, chunk: Chunk, original: Chunk | None) -> None:
    """Content update: a chunk whose text is unchanged keeps its references, manual and removed ones
    included; a changed chunk is read again by the rules."""
    if session.scalar(select(ChunkReference.id).where(ChunkReference.chunk_id == chunk.id).limit(1)) is not None:
        return
    now = datetime.now(UTC)
    if original is not None and original.content == chunk.content:
        for row in session.scalars(select(ChunkReference).where(ChunkReference.chunk_id == original.id)).all():
            session.add(ChunkReference(
                id=uuid4(), project_id=version.project_id, document_id=version.document_id, document_version_id=version.id,
                chunk_id=chunk.id, raw_text=row.raw_text, start_offset=row.start_offset, end_offset=row.end_offset,
                normalized_name=row.normalized_name, status=row.status, target_document_id=row.target_document_id,
                source=row.source, is_deleted=row.is_deleted, created_by=row.created_by, updated_by=row.updated_by,
                lock_version=1, created_at=row.created_at, updated_at=now))
        return
    _add_rule_references(session, version, chunk, project_name_index(session, version.project_id), None, now)


def resolve_pending_references(session, project_id: UUID) -> int:
    """REF442-005 / REN442-003: retry unresolved references of a project after a publish or rename."""
    rows = session.scalars(select(ChunkReference).where(
        ChunkReference.project_id == project_id, ChunkReference.status == "unresolved",
        ChunkReference.is_deleted.is_(False)).with_for_update()).all()
    if not rows:
        return 0
    session.flush()  # a pending rename or publish must be visible to the name index
    index = project_name_index(session, project_id)
    now = datetime.now(UTC)
    count = 0
    for row in rows:
        target = resolve_key(index, row.normalized_name, row.document_id)
        if target is not None:
            row.status, row.target_document_id, row.updated_at = "resolved", target, now
            row.lock_version += 1
            count += 1
    session.flush()
    return count


def version_reference_rows(session, version_id: UUID, *, include_removed: bool = False) -> list[tuple[ChunkReference, int, str | None]]:
    """References on active chunks, ordered by chunk and position, with the target document's name."""
    query = (select(ChunkReference, Chunk.chunk_index, Document.title)
             .join(Chunk, Chunk.id == ChunkReference.chunk_id)
             .outerjoin(Document, Document.id == ChunkReference.target_document_id)
             .where(ChunkReference.document_version_id == version_id, Chunk.status == "active"))
    if not include_removed:
        query = query.where(ChunkReference.is_deleted.is_(False))
    return list(session.execute(query.order_by(Chunk.chunk_index, ChunkReference.start_offset, ChunkReference.created_at)).all())


def reference_summary(session, version_id: UUID) -> dict[str, int]:
    counts = {"total": 0, "resolved": 0, "unresolved": 0, "external": 0}
    for row, _index, _title in version_reference_rows(session, version_id):
        counts["total"] += 1
        counts[row.status] += 1
    return counts


def require_target_document(session, project_id: UUID, source_document_id: UUID, target_id: UUID) -> Document:
    from app.core.errors import AppError
    target = session.get(Document, target_id)
    if target is None or target.project_id != project_id or target.is_deleted:
        raise AppError("chunk_reference_target_not_found", "Referenced document was not found in this project", status_code=404)
    if target.id == source_document_id:
        raise AppError("chunk_reference_self", "A document cannot reference itself", status_code=422)
    return target
