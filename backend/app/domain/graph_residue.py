"""Full-scope graph inventory and PostgreSQL protection for physical residues."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import Text, cast, select

from app.core.errors import AppError
from app.db.models import ApprovalEvidenceManifest, ChatRecord, Chunk, ChunkTag, DocumentVersionTag, Tag
from app.domain.graph_projection import PROJECTION_VERSION

BATCH_SIZE = 200


def _conflict():
    return AppError("graph_identity_conflict", "Graph residue ownership is inconsistent", status_code=409)


def protection_reason(session, kind: str, identity: str, project_id: str, version_id: str | None = None) -> str | None:
    """An existing Chunk identity protects vectors, lineage and historical FKs too."""
    if not isinstance(identity, str):
        raise _conflict()
    try:
        key = UUID(identity)
    except (TypeError, ValueError) as exc:
        raise _conflict() from exc
    if str(key) != identity:
        raise _conflict()
    if kind == "Chunk":
        chunk = session.get(Chunk, key)
        if chunk is not None:
            if (str(chunk.project_id) != project_id
                or (version_id is not None and str(chunk.document_version_id) != version_id)):
                raise _conflict()
            return "postgres_chunk_identity"
    if kind == "Tag":
        tag = session.get(Tag, key)
        if tag is not None and str(tag.project_id) != project_id:
            raise _conflict()
        if (session.scalar(select(ChunkTag.chunk_id).where(ChunkTag.tag_id == key).limit(1))
            or session.scalar(select(DocumentVersionTag.document_version_id).where(DocumentVersionTag.tag_id == key).limit(1))):
            return "postgres_tag_assignment"
    # Immutable manifests and retained citations can outlive a physical source
    # row. A literal UUID occurrence is deliberately a conservative protection.
    for model, column in ((ApprovalEvidenceManifest, ApprovalEvidenceManifest.manifest),
                          (ChatRecord, ChatRecord.reference_docs)):
        if session.scalar(select(model.id).where(cast(column, Text).contains(identity)).limit(1)):
            return "retained_evidence_reference"
    return None


def inventory(tx, projection, session) -> tuple[dict, ...]:
    """Read every scoped orphan in pages; nothing is truncated into a clean result."""
    expected = [n["id"] for n in projection.graph["nodes"]]
    cursor = ""
    result = []
    while True:
        rows = list(tx.run("""
            MATCH (n)
            WHERE ((n.document_version_id=$vid OR EXISTS {
                MATCH (:DocumentVersion {id:$vid})-[:VERSION_HAS_CHUNK]->(n) })
                OR (n:Tag AND n.project_id=$pid AND NOT (n)--()))
              AND (n.id IS NULL OR NOT n.id IN $expected) AND elementId(n)>$cursor
            RETURN elementId(n) AS key, labels(n) AS labels, properties(n) AS props
            ORDER BY key LIMIT $batch
            """, vid=str(projection.version_id), pid=str(projection.project_id),
            expected=expected, cursor=cursor, batch=BATCH_SIZE))
        if not rows:
            break
        for row in rows:
            props = dict(row["props"])
            labels = set(row["labels"])
            kind = "Chunk" if labels == {"Chunk"} else "Tag" if labels == {"Tag"} else None
            if (kind is None or props.get("project_id") != str(projection.project_id)
                or (kind == "Chunk" and props.get("document_version_id") != str(projection.version_id))
                or props.get("projection_owner") not in (None, PROJECTION_VERSION)):
                raise _conflict()
            reason = protection_reason(session, kind, props.get("id"), str(projection.project_id), str(projection.version_id))
            result.append({"key": row["key"], "id": props["id"], "type": kind,
                           "properties": props, "protected_reason": reason})
        cursor = rows[-1]["key"]
    # Scope-property queries must also detect duplicate IDs with a foreign node.
    for offset in range(0, len(result), BATCH_SIZE):
        ids = [row["id"] for row in result[offset:offset+BATCH_SIZE]]
        duplicates = tx.run("MATCH(n) WHERE n.id IN $ids WITH n.id AS id,count(n) AS c WHERE c<>1 RETURN id LIMIT 1", ids=ids).single()
        if len(ids) != len(set(ids)) or duplicates:
            raise _conflict()
    return tuple(result)


def prune(tx, projection, session, residues, *, tags_only=False) -> dict:
    """Recheck scope, PG references and all external edges before ordinary DELETE."""
    removable = [r for r in residues if not r["protected_reason"]]
    if tags_only and any(r["type"] == "Chunk" for r in removable):
        raise AppError("graph_structure_repair_required", "Tag repair cannot remove graph structure", status_code=409)
    plans = []
    for residue in removable:
        rows = list(tx.run("MATCH(n) WHERE elementId(n)=$key RETURN labels(n) AS labels,properties(n) AS props",
                           key=residue["key"]))
        if len(rows) != 1 or set(rows[0]["labels"]) != {residue["type"]} or dict(rows[0]["props"]) != residue["properties"]:
            raise _conflict()
        if protection_reason(session, residue["type"], residue["id"], str(projection.project_id), str(projection.version_id)):
            raise AppError("graph_target_changed", "Graph residue acquired a protected reference", status_code=409)
        edges = list(tx.run("""
            MATCH(s)-[r]->(t) WHERE elementId(s)=$key OR elementId(t)=$key
            RETURN elementId(r) AS key,type(r) AS kind,properties(r) AS props,
                   s.id AS source,t.id AS target,labels(t) AS labels,t.project_id AS project
            """, key=residue["key"]))
        for edge in edges:
            structural = (residue["type"] == "Chunk" and edge["kind"] == "VERSION_HAS_CHUNK"
                          and edge["source"] == str(projection.version_id) and edge["target"] == residue["id"])
            tag = (residue["type"] == "Chunk" and edge["kind"] == "CHUNK_HAS_TAG"
                   and edge["source"] == residue["id"] and set(edge["labels"]) == {"Tag"}
                   and edge["project"] == str(projection.project_id))
            if not (structural or tag) or edge["props"].get("projection_owner") not in (None, PROJECTION_VERSION):
                raise _conflict()
        plans.append((residue["key"], [e["key"] for e in edges], residue["type"]))
    # Validate the entire plan before any deletion; a late unknown relationship
    # causes ordinary DELETE to fail and the Neo4j transaction to roll back.
    for key, edges, _kind in plans:
        tx.run("MATCH()-[r]->() WHERE elementId(r) IN $keys DELETE r", keys=edges).consume()
        tx.run("MATCH(n) WHERE elementId(n)=$key DELETE n", key=key).consume()
    return {"removed_nodes": len(plans), "protected_nodes": len(residues)-len(plans)}
