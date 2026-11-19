"""CHG-442 STAGE442-009/010: when a station is done again, keep the work of unchanged chunks.

Re-chunking (station 2 after a station 1 edit, or a new revision after rejection) compares the new chunks with a
reuse pool: the version's previous active chunks, or the rejected source version's active chunks. A new chunk with
the same Markdown text and heading path as a pool chunk takes over its chunk tags (manual ones included), its
references and, later, its vector. Manual chunks of the pool are kept when their exact text is still found once in
the new content. Station 3 then calls the tagging model only for chunks without a matching tag receipt, and station
4 calls the embedding model only for vectors it cannot reuse.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import desc, select

from app.db.models import Chunk, ChunkReference, ChunkTag, DocumentVersion, EmbeddingBuild, EmbeddingBuildVector

REUSED_FROM = "station_reused_from"
POOL_KEY = "station_reuse_pool"


def _key(chunk: Chunk) -> tuple[str, tuple[str, ...]]:
    return (chunk.markdown_content or chunk.content or "", tuple(chunk.heading_path or ()))


def is_manual(chunk: Chunk) -> bool:
    return (chunk.chunk_strategy or {}).get("source") == "manual"


def active_chunks(session, version_id: UUID) -> list[Chunk]:
    return list(session.scalars(select(Chunk).where(Chunk.document_version_id == version_id, Chunk.status == "active")
                                .order_by(Chunk.chunk_index)))


def take_reuse_pool(session, version: DocumentVersion) -> list[Chunk]:
    """Before re-chunking: the version's active chunks become the pool (status superseded, kept as history). A new
    revision made after rejection has no chunks yet; its pool is the source version's active chunks."""
    own = active_chunks(session, version.id)
    if own:
        now = datetime.now(UTC)
        for chunk in own:
            chunk.status, chunk.superseded_at = "superseded", now
        session.flush()
        return own
    source_id = (version.chunk_strategy or {}).get("station_revision_of")
    if source_id:
        source = session.get(DocumentVersion, UUID(str(source_id)))
        if source is not None and source.document_id == version.document_id:
            return active_chunks(session, source.id)
    return []


def _copy_tags(session, source: Chunk, target: Chunk) -> int:
    count = 0
    for link in session.scalars(select(ChunkTag).where(ChunkTag.chunk_id == source.id)).all():
        if link.source == "rule":
            continue
        session.add(ChunkTag(chunk_id=target.id, tag_id=link.tag_id, source=link.source, confidence_score=link.confidence_score,
                             metadata_=dict(link.metadata_ or {}), created_by=link.created_by, created_at=link.created_at))
        count += 1
    return count


def _copy_references(session, version: DocumentVersion, source: Chunk, target: Chunk) -> None:
    now = datetime.now(UTC)
    for row in session.scalars(select(ChunkReference).where(ChunkReference.chunk_id == source.id)).all():
        session.add(ChunkReference(
            id=uuid4(), project_id=version.project_id, document_id=version.document_id, document_version_id=version.id,
            chunk_id=target.id, raw_text=row.raw_text, start_offset=row.start_offset, end_offset=row.end_offset,
            normalized_name=row.normalized_name, status=row.status, target_document_id=row.target_document_id,
            source=row.source, relation_type=row.relation_type, is_deleted=row.is_deleted, created_by=row.created_by, updated_by=row.updated_by,
            lock_version=1, created_at=row.created_at, updated_at=now))


def _take_over(session, version: DocumentVersion, source: Chunk, target: Chunk) -> None:
    receipt = (source.chunk_strategy or {}).get("tag_receipt")
    target.chunk_strategy = {**(target.chunk_strategy or {}), REUSED_FROM: str(source.id),
                             **({"tag_receipt": receipt} if receipt else {})}
    _copy_tags(session, source, target)
    _copy_references(session, version, source, target)


def _copy_manual(session, version: DocumentVersion, source: Chunk, start: int, end: int, temporary_index: int) -> Chunk:
    values = {column.key: getattr(source, column.key) for column in Chunk.__table__.columns}
    now = datetime.now(UTC)
    shift = start - (source.start_offset or 0)
    mappings = []
    for mapping in source.source_mapping or []:
        item = dict(mapping)
        for name in ("markdown_start_offset", "markdown_end_offset", "start_offset", "end_offset"):
            if type(item.get(name)) is int:
                item[name] += shift
        mappings.append(item)
    values.update(id=uuid4(), document_version_id=version.id, start_offset=start, end_offset=end, status="active",
                  source_mapping=mappings, superseded_at=None, superseded_by_id=None, embedding_vector_ref=None,
                  created_at=now, updated_at=now, chunk_index=temporary_index)
    chunk = Chunk(**{key: value for key, value in values.items() if hasattr(Chunk, key)})
    session.add(chunk)
    return chunk


def carry_from_pool(session, version: DocumentVersion, new_chunks: list[Chunk], pool: list[Chunk], markdown: str) -> dict[str, int]:
    """Give unchanged new chunks the work of their pool twin and keep manual chunks whose text is still present."""
    automatic = {}
    for chunk in pool:
        if not is_manual(chunk):
            automatic.setdefault(_key(chunk), chunk)
    reused = 0
    for chunk in new_chunks:
        twin = automatic.pop(_key(chunk), None)
        if twin is not None:
            _take_over(session, version, twin, chunk)
            reused += 1
    kept, dropped = 0, 0
    taken = {(c.start_offset, c.end_offset) for c in new_chunks}
    for source in (c for c in pool if is_manual(c)):
        text = source.markdown_content or ""
        start = source.start_offset if type(source.start_offset) is int and markdown[source.start_offset:source.end_offset] == text else None
        if start is None and text and markdown.count(text) == 1:
            start = markdown.index(text)
        if start is None or not text or (start, start + len(text)) in taken:
            dropped += 1
            continue
        copy = _copy_manual(session, version, source, start, start + len(text), -1 - kept)
        session.flush()
        _take_over(session, version, source, copy)
        taken.add((start, start + len(text)))
        kept += 1
    session.flush()
    reindex(session, version.id)
    return {"reused_chunks": reused, "new_chunks": len(new_chunks) - reused, "manual_kept": kept, "manual_dropped": dropped}


def reindex(session, version_id: UUID) -> None:
    """Order by source position; at the same start a manual chunk comes after the automatic one (CHUNK442-002)."""
    chunks = active_chunks(session, version_id)
    for offset, chunk in enumerate(chunks, start=1):
        chunk.chunk_index = -10_000 - offset
    session.flush()
    ordered = sorted(chunks, key=lambda c: (c.start_offset if c.start_offset is not None else 10**12, 1 if is_manual(c) else 0,
                                            c.end_offset or 0, c.created_at))
    for index, chunk in enumerate(ordered, start=1):
        chunk.chunk_index = index
        if hasattr(chunk, "sequence"):
            chunk.sequence = index
    session.flush()


def tag_input_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def tag_receipt_matches(chunk: Chunk, *, model, prompt, text: str) -> bool:
    receipt = (chunk.chunk_strategy or {}).get("tag_receipt") or {}
    return (receipt.get("model_id") == str(model.id) and receipt.get("config_version") == model.config_version
            and receipt.get("prompt_sha256") == prompt.content_hash and receipt.get("input_sha256") == tag_input_digest(text))


def reusable_vectors(session, *, model, profile, chunks: list[Chunk]) -> dict[str, list[float]]:
    """Vectors already built for the same embedding input: the chunk itself or the pool chunk it was taken from."""
    from app.domain.embeddings import embedding_reuse_key, resolve_embedding_retrieval_text
    reuse: dict[str, list[float]] = {}
    for chunk in chunks:
        source_id = (chunk.chunk_strategy or {}).get(REUSED_FROM) or str(chunk.id)
        for candidate_id in dict.fromkeys((str(chunk.id), source_id)):
            source = session.get(Chunk, UUID(candidate_id))
            if source is None:
                continue
            row = session.scalar(select(EmbeddingBuildVector).join(EmbeddingBuild, EmbeddingBuild.id == EmbeddingBuildVector.embedding_build_id)
                                 .where(EmbeddingBuildVector.chunk_id == source.id, EmbeddingBuild.model_id == model.id,
                                        EmbeddingBuild.embedding_profile_id == (profile.id if profile else None),
                                        EmbeddingBuild.status.in_(("completed", "staged", "published")))
                                 .order_by(desc(EmbeddingBuild.created_at)).limit(1))
            if row is None or not isinstance(row.vector, list):
                continue
            key = embedding_reuse_key(model, source, resolve_embedding_retrieval_text(source, model=model, profile=profile), profile)
            reuse.setdefault(key, [float(value) for value in row.vector])
    return reuse
