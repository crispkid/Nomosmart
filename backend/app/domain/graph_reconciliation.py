"""Bounded Neo4j reconciliation. No embedding, indexing or publication actions."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, create_neo4j_driver
from app.core.errors import AppError
from app.db.models import ActiveVersionManifest, ApprovalRequest, Chunk, Document, DocumentVersion, Project
from app.domain.graph_projection import (GraphProjection, LABELS, PROJECTION_VERSION, RELATIONS, TAG_RELATIONS,
    build_graph_projection, canonical_graph, digest, edge_key, graph_difference)

NODE_PROPERTIES = {
    "Project": ("name",), "Document": ("title", "project_id", "source_type"),
    "DocumentVersion": ("version_label", "project_id", "document_id"),
    "Chunk": ("title", "chunk_index", "content_type", "project_id", "document_version_id"),
    "Tag": ("name", "project_id"),
}
EDGE_PROPERTIES = ("source", "created_at", "confidence_score", "model_id", "llm_model_id", "prompt_version",
                   "system_prompt_version_id", "system_prompt_content_hash")


@dataclass(frozen=True)
class GraphComparison:
    graph: dict
    receipt: str | None
    source_digest: str

    @property
    def target_digest(self) -> str:
        return digest({"graph": self.graph, "receipt": self.receipt})

    def matches(self, projection: GraphProjection) -> bool:
        return self.graph == projection.graph and self.receipt == projection.source_digest

    def report(self, projection: GraphProjection) -> dict:
        return {**projection.binding(), "target_digest": self.target_digest,
                "ready": self.matches(projection), "differences": graph_difference(projection.graph, self.graph),
                "node_count": len(self.graph["nodes"]), "edge_count": len(self.graph["edges"])}


def conflict() -> AppError:
    return AppError("graph_identity_conflict", "Graph identity or relationship ownership is inconsistent", status_code=409)


class Neo4jProjectionStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    @contextmanager
    def connection(self) -> Iterator:
        driver = create_neo4j_driver(self.settings)
        try:
            with driver.session(database=self.settings.neo4j_database) as session:
                yield session
        except (Neo4jError, ServiceUnavailable, SessionExpired, OSError) as exc:
            raise AppError("graph_projection_not_ready", "Graph projection is not ready", status_code=503) from exc
        finally:
            driver.close()

    def read(self, projection: GraphProjection) -> GraphComparison:
        with self.connection() as session:
            return session.execute_read(self._read, projection)

    @staticmethod
    def _read(tx, projection: GraphProjection) -> GraphComparison:
        vid, did = str(projection.version_id), str(projection.document_id)
        rows = list(tx.run("""
            MATCH (s)-[r:PROJECT_HAS_DOCUMENT|DOCUMENT_HAS_VERSION|VERSION_HAS_CHUNK|VERSION_HAS_TAG|CHUNK_HAS_TAG]->(t)
            WHERE (type(r) = 'PROJECT_HAS_DOCUMENT' AND t.id = $did)
               OR (type(r) = 'DOCUMENT_HAS_VERSION' AND t.id = $vid)
               OR (type(r) IN ['VERSION_HAS_CHUNK', 'VERSION_HAS_TAG'] AND s.id = $vid)
               OR (type(r) = 'CHUNK_HAS_TAG' AND EXISTS {
                   MATCH (:DocumentVersion {id: $vid})-[:VERSION_HAS_CHUNK]->(s) })
            RETURN s.id AS source, t.id AS target, type(r) AS kind, properties(r) AS props
            """, vid=vid, did=did))
        edges: list[dict] = []
        seen_edges = set()
        for row in rows:
            props = dict(row["props"])
            if props.get("projection_owner") not in (None, PROJECTION_VERSION):
                raise conflict()
            key = (row["source"], row["kind"], row["target"])
            if None in key or key in seen_edges:
                raise conflict()
            seen_edges.add(key)
            edges.append({"source": key[0], "type": key[1], "target": key[2],
                          "properties": {k: props[k] for k in EDGE_PROPERTIES if k in props} if key[1] in TAG_RELATIONS else {}})
        identities = sorted({n["id"] for n in projection.graph["nodes"]} |
                            {e[k] for e in edges for k in ("source", "target")})
        nodes: list[dict] = []
        seen = set()
        receipt = None
        expected = {n["id"]: n for n in projection.graph["nodes"]}
        for row in tx.run("MATCH (n) WHERE n.id IN $ids RETURN labels(n) AS labels, properties(n) AS props", ids=identities):
            props, labels = dict(row["props"]), set(row["labels"])
            key = props.get("id")
            kinds = labels & LABELS
            if key in seen or len(kinds) != 1:
                raise conflict()
            seen.add(key)
            kind = next(iter(kinds))
            if key in expected and expected[key]["type"] != kind:
                raise conflict()
            if kind == "Project" and key != str(projection.project_id):
                raise conflict()
            if props.get("project_id") not in (None, str(projection.project_id)):
                raise conflict()
            if kind == "Chunk" and props.get("document_version_id") not in (None, vid):
                raise conflict()
            if kind == "DocumentVersion" and (key != vid or props.get("document_id") not in (None, did)):
                raise conflict()
            if kind == "Document" and key != did:
                raise conflict()
            if kind == "Tag" and key not in expected and props.get("project_id") != str(projection.project_id):
                raise conflict()  # An obsolete tag needs explicit ownership evidence.
            nodes.append({"id": key, "type": kind, "properties": {k: props.get(k) for k in NODE_PROPERTIES[kind]}})
            if key == vid:
                receipt = props.get("graph_source_digest")
        # Legacy nodes may lack scope properties. Their existing structural
        # parent must still agree; never adopt a node owned by another version.
        for row in tx.run("""
            MATCH (v)-[:VERSION_HAS_CHUNK]->(c)
            WHERE c.id IN $ids AND (v.id IS NULL OR v.id <> $vid)
            RETURN c.id LIMIT 1
            """, ids=[n["id"] for n in nodes if n["type"] == "Chunk"], vid=vid):
            raise conflict()
        # Expected tags may already exist through another version. They are
        # included in the comparison but their assignments remain version-scoped.
        return GraphComparison(canonical_graph(nodes, edges), receipt, projection.source_digest)

    def reconcile(self, projection: GraphProjection, *, target_digest: str | None = None,
                  tags_only: bool = False) -> GraphComparison:
        with self.connection() as session:
            return session.execute_write(self._reconcile, projection, target_digest, tags_only)

    @classmethod
    def _reconcile(cls, tx, projection: GraphProjection, target_digest: str | None, tags_only: bool) -> GraphComparison:
        before = cls._read(tx, projection)
        if target_digest is not None and before.target_digest != target_digest:
            raise AppError("graph_target_changed", "Graph changed since comparison", status_code=409)
        if before.matches(projection):
            return before
        expected_nodes = {n["id"]: n for n in projection.graph["nodes"]}
        expected_edges = {edge_key(e): e for e in projection.graph["edges"]}
        # Never delete structural/unknown edges or obsolete Chunk nodes as a
        # side effect of repairing tags. Require a separate reviewed repair.
        if any(n["id"] not in expected_nodes and n["type"] != "Tag" for n in before.graph["nodes"]):
            raise conflict()
        if any(edge_key(e) not in expected_edges and e["type"] not in TAG_RELATIONS for e in before.graph["edges"]):
            raise conflict()
        if tags_only:
            expected_structure = {edge_key(e) for e in projection.graph["edges"] if e["type"] not in TAG_RELATIONS}
            actual_structure = {edge_key(e) for e in before.graph["edges"] if e["type"] not in TAG_RELATIONS}
            actual_ids = {n["id"] for n in before.graph["nodes"]}
            if expected_structure != actual_structure or any(n["id"] not in actual_ids for n in projection.graph["nodes"] if n["type"] != "Tag"):
                raise AppError("graph_structure_repair_required", "Graph-only tag repair requires existing version structure", status_code=409)
        for node in projection.graph["nodes"]:
            label = node["type"]
            if label not in LABELS:
                raise conflict()
            # Properties are allowed canonical metadata, never raw content.
            tx.run(f"MERGE (n:{label} {{id: $id}}) SET n += $props", id=node["id"], props=node["properties"]).consume()
        for edge in before.graph["edges"]:
            if edge_key(edge) not in expected_edges:
                relation = edge["type"]
                if relation not in TAG_RELATIONS:
                    raise conflict()
                tx.run(f"MATCH (s {{id: $source}})-[r:{relation}]->(t {{id: $target}}) DELETE r",
                       source=edge["source"], target=edge["target"]).consume()
        for edge in projection.graph["edges"]:
            relation = edge["type"]
            if relation not in RELATIONS:
                raise conflict()
            if tags_only and relation not in TAG_RELATIONS:
                continue
            props = {"projection_owner": PROJECTION_VERSION, **edge["properties"]}
            tx.run(f"MATCH (s {{id: $source}}), (t {{id: $target}}) MERGE (s)-[r:{relation}]->(t) "
                   "SET r += $props", source=edge["source"], target=edge["target"], props=props).consume()
            # Remove only stale managed provenance, preserving unknown properties.
            if relation in TAG_RELATIONS:
                obsolete = [k for k in EDGE_PROPERTIES if k not in props]
                for key in obsolete:
                    tx.run(f"MATCH (s {{id: $source}})-[r:{relation}]->(t {{id: $target}}) REMOVE r.{key}",
                           source=edge["source"], target=edge["target"]).consume()
        tx.run("MATCH (v:DocumentVersion {id: $id}) SET v.graph_source_digest=$digest, v.graph_projection_version=$format",
               id=str(projection.version_id), digest=projection.source_digest, format=PROJECTION_VERSION).consume()
        after = cls._read(tx, projection)
        # Nodes of obsolete tags are deliberately retained, but no longer part
        # of this version's projection after their last edge is removed.
        if not after.matches(projection):
            raise AppError("graph_projection_mismatch", "Graph read-back did not match the canonical snapshot", status_code=503)
        return after


def locked_projection(session: Session, project_id, document_id, version_id, *, expected_binding: dict | None = None) -> GraphProjection:
    # Autoflush the caller's pending publication, then refresh identity-map
    # instances after waiting for locks. A stale cached ORM object is not a fence.
    session.flush()  # Application sessions deliberately disable autoflush.
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update().execution_options(populate_existing=True))
    document = session.scalar(select(Document).where(Document.id == document_id).with_for_update().execution_options(populate_existing=True))
    version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update().execution_options(populate_existing=True))
    if project is None or document is None or version is None or project.status != "active" or document.is_deleted or document.status != "active":
        raise AppError("graph_scope_inactive", "Graph synchronization scope is not active", status_code=409)
    if version.published_at is None or version.status not in {"active", "inactive"}:
        raise AppError("graph_version_not_published", "Only published version evidence can be synchronized", status_code=409)
    projection = build_graph_projection(session, project, document, version)
    if expected_binding is not None and projection.binding() != expected_binding:
        raise AppError("graph_source_changed", "Graph source changed since the work was requested", status_code=409)
    return projection


def synchronize_graph(session: Session, settings: Settings, project_id, document_id, version_id,
                      *, expected_binding: dict | None = None, target_digest: str | None = None,
                      tags_only: bool = False) -> GraphComparison:
    projection = locked_projection(session, project_id, document_id, version_id, expected_binding=expected_binding)
    result = Neo4jProjectionStore(settings).reconcile(projection, target_digest=target_digest, tags_only=tags_only)
    # Locks are held through the caller's receipt/audit transaction. No external
    # graph operation commits the PostgreSQL transaction or modifies a manifest.
    current = locked_projection(session, project_id, document_id, version_id)
    if current.binding() != projection.binding():
        raise AppError("graph_source_changed", "Graph source changed during synchronization", status_code=409)
    return result


def clear_zero_candidate_chunks(session: Session, settings: Settings, version: DocumentVersion) -> None:
    """Separate from published tag repair; caller holds the version write lock.

    Keep shared nodes and version/tag relationships. Only demonstrably owned
    stale Chunk nodes/edges may be removed. Unknown edges fail before any write;
    ordinary DELETE (never DETACH) also rejects a late unexpected relationship.
    """
    if (version.published_at is not None or version.status != "submission_ready"
        or session.scalar(select(Chunk.id).where(Chunk.document_version_id == version.id, Chunk.status == "active").limit(1))
        or session.scalar(select(ActiveVersionManifest.id).where(ActiveVersionManifest.document_version_id == version.id).limit(1))
        or session.scalar(select(ApprovalRequest.id).where(ApprovalRequest.document_version_id == version.id).limit(1))):
        raise conflict()
    with Neo4jProjectionStore(settings).connection() as graph:
        graph.execute_write(_clear_zero_candidate_chunks, str(version.project_id), str(version.document_id), str(version.id))


def _clear_zero_candidate_chunks(tx, project_id: str, document_id: str, version_id: str) -> None:
    versions = list(tx.run("MATCH (v {id:$vid}) RETURN labels(v) AS labels, properties(v) AS props", vid=version_id))
    if len(versions) > 1 or any(set(row["labels"]) != {"DocumentVersion"}
        or row["props"].get("project_id") not in (None, project_id)
        or row["props"].get("document_id") not in (None, document_id) for row in versions):
        raise conflict()
    if tx.run("MATCH (d)-[:DOCUMENT_HAS_VERSION]->(v {id:$vid}) "
              "WHERE d.id IS NULL OR d.id <> $did RETURN d LIMIT 1", vid=version_id, did=document_id).single():
        raise conflict()
    rows = list(tx.run("""
        MATCH (c) WHERE c.document_version_id=$vid OR EXISTS {
            MATCH (:DocumentVersion {id:$vid})-[:VERSION_HAS_CHUNK]->(c) }
        RETURN elementId(c) AS key, labels(c) AS labels, properties(c) AS props
        """, vid=version_id))
    if not rows:
        return
    ids = [row["props"].get("id") for row in rows]
    if None in ids or len(set(ids)) != len(ids) or any(set(row["labels"]) != {"Chunk"}
        or row["props"].get("project_id") not in (None, project_id)
        or row["props"].get("document_version_id") not in (None, version_id) for row in rows):
        raise conflict()
    keys = [row["key"] for row in rows]
    edges = list(tx.run("""
        MATCH (s)-[r]->(t) WHERE elementId(s) IN $keys OR elementId(t) IN $keys
        RETURN elementId(r) AS key, type(r) AS kind, properties(r) AS props,
               s.id AS source, t.id AS target, labels(t) AS target_labels,
               t.project_id AS target_project
        """, keys=keys))
    parents = set()
    for edge in edges:
        structural = edge["kind"] == "VERSION_HAS_CHUNK" and edge["source"] == version_id and edge["target"] in ids
        tag = (edge["kind"] == "CHUNK_HAS_TAG" and edge["source"] in ids
               and set(edge["target_labels"]) == {"Tag"} and edge["target_project"] == project_id)
        if not (structural or tag) or edge["props"].get("projection_owner") not in (None, PROJECTION_VERSION):
            raise conflict()
        if structural:
            parents.add(edge["target"])
    if any(row["props"]["id"] not in parents and (
        row["props"].get("project_id") != project_id or row["props"].get("document_version_id") != version_id) for row in rows):
        raise conflict()
    tx.run("MATCH ()-[r]->() WHERE elementId(r) IN $keys DELETE r", keys=[edge["key"] for edge in edges]).consume()
    tx.run("MATCH (c) WHERE elementId(c) IN $keys DELETE c", keys=keys).consume()
    tx.run("MATCH (v:DocumentVersion {id:$vid}) REMOVE v.graph_source_digest", vid=version_id).consume()
