"""CHG-442 REF442-005: `(:Document)-[:REFERENCES]->(:Document)` edges in the formal graph.

PostgreSQL is the source of truth: resolved, not removed references on active chunks of published (active)
versions, pointing at documents that also have a published version. The edges of one project are recomputed
as a whole and read back. They are owned by `chunk-references-v1`; the version projection read-back
(`graph_reconciliation._read`) only matches its own relation types, so these edges never disturb it.
"""
from __future__ import annotations

from collections import Counter
from uuid import UUID

from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Chunk, ChunkReference, Document, DocumentVersion

OWNER = "chunk-references-v1"


def published_reference_edges(session, project_id: UUID) -> dict[tuple[str, str], dict]:
    """(source document, target document) -> {count, source_version_id} for published documents only."""
    live = {doc_id: version_id for doc_id, version_id in session.execute(
        select(Document.id, DocumentVersion.id).join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(Document.project_id == project_id, Document.is_deleted.is_(False), Document.status == "active",
               DocumentVersion.status == "active", DocumentVersion.published_at.is_not(None)))}
    if not live:
        return {}
    counts: Counter[tuple[UUID, UUID]] = Counter(session.execute(
        select(ChunkReference.document_id, ChunkReference.target_document_id)
        .join(Chunk, Chunk.id == ChunkReference.chunk_id)
        .where(ChunkReference.project_id == project_id, ChunkReference.status == "resolved", ChunkReference.is_deleted.is_(False),
               Chunk.status == "active", ChunkReference.document_version_id.in_(list(live.values())))).all())
    return {(str(source), str(target)): {"count": count, "source_version_id": str(live[source])}
            for (source, target), count in counts.items() if target in live and source != target}


def _replace(tx, project_id: str, edges: list[dict]) -> list[tuple]:
    tx.run("MATCH (d:Document {project_id: $pid})-[r:REFERENCES]->(:Document) DELETE r", pid=project_id).consume()
    if edges:
        tx.run("""
            UNWIND $edges AS e
            MATCH (s:Document {id: e.source}), (t:Document {id: e.target})
            MERGE (s)-[r:REFERENCES]->(t)
            SET r.count = e.count, r.source_version_id = e.source_version_id, r.projection_owner = $owner
            """, edges=edges, owner=OWNER).consume()
    rows = tx.run("""
        MATCH (s:Document {project_id: $pid})-[r:REFERENCES]->(t:Document)
        RETURN s.id AS source, t.id AS target, r.count AS count, r.projection_owner AS owner
        """, pid=project_id)
    return sorted((row["source"], row["target"], row["count"], row["owner"]) for row in rows)


def sync_reference_edges(session, settings: Settings, project_id: UUID) -> int:
    """Recompute and verify the project's REFERENCES edges; returns the edge count."""
    from app.domain.graph_reconciliation import Neo4jProjectionStore
    desired = published_reference_edges(session, project_id)
    edges = [{"source": s, "target": t, **value} for (s, t), value in sorted(desired.items())]
    with Neo4jProjectionStore(settings).connection() as graph:
        written = graph.execute_write(_replace, str(project_id), edges)
    # Targets without a graph node (not yet synchronized) cannot hold an edge; everything else must match.
    expected = sorted((e["source"], e["target"], e["count"], OWNER) for e in edges)
    if any(row not in expected for row in written) or len(written) > len(expected):
        raise AppError("graph_reference_mismatch", "Reference edges did not match after synchronization", status_code=503)
    return len(written)


def preview_reference_lines(session, version_ids: list[UUID]) -> list[tuple[str, str, str]]:
    """REF442-007: (chunk id, target document id, target title) of resolved references on active chunks, for
    graph previews of versions that are not published yet."""
    if not version_ids:
        return []
    rows = session.execute(
        select(ChunkReference.chunk_id, ChunkReference.target_document_id, Document.title)
        .join(Chunk, Chunk.id == ChunkReference.chunk_id)
        .join(Document, Document.id == ChunkReference.target_document_id)
        .where(ChunkReference.document_version_id.in_(version_ids), ChunkReference.status == "resolved",
               ChunkReference.is_deleted.is_(False), Chunk.status == "active", Document.is_deleted.is_(False))).all()
    return [(str(chunk_id), str(target_id), title) for chunk_id, target_id, title in rows]
