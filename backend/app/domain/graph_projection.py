"""Canonical, content-free graph evidence shared by previews and publication."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Chunk, ChunkTag, Document, DocumentVersion, DocumentVersionTag, Project, Tag

PROJECTION_VERSION = "tag-graph-v1"
TAG_RELATIONS = frozenset({"CHUNK_HAS_TAG", "VERSION_HAS_TAG"})
RELATIONS = TAG_RELATIONS | {"PROJECT_HAS_DOCUMENT", "DOCUMENT_HAS_VERSION", "VERSION_HAS_CHUNK"}
LABELS = frozenset({"Project", "Document", "DocumentVersion", "Chunk", "Tag"})


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def edge_key(edge: dict) -> tuple[str, str, str]:
    return edge["source"], edge["type"], edge["target"]


def canonical_graph(nodes: list[dict], edges: list[dict]) -> dict:
    return {"nodes": sorted(nodes, key=lambda n: (n["type"], n["id"])), "edges": sorted(edges, key=edge_key)}


@dataclass(frozen=True)
class GraphProjection:
    project_id: UUID
    document_id: UUID
    version_id: UUID
    revision: int
    project_generation: int
    graph: dict
    tag_revision: int = 0

    @property
    def source_digest(self) -> str:
        return digest({"projection_version": PROJECTION_VERSION, "project_id": str(self.project_id),
                       "document_id": str(self.document_id), "version_id": str(self.version_id),
                       "revision": self.revision, "tag_revision": self.tag_revision, "generation": self.project_generation, "graph": self.graph})

    def binding(self) -> dict:
        return {"project_id": str(self.project_id), "document_id": str(self.document_id),
                "version_id": str(self.version_id), "revision": self.revision,
                "project_generation": self.project_generation, "tag_revision": self.tag_revision, "source_digest": self.source_digest}


def assignment_properties(link: ChunkTag | DocumentVersionTag) -> dict:
    """Never copy arbitrary Provider/prompt/user metadata into the graph."""
    props: dict[str, Any] = {"source": link.source, "created_at": link.created_at.isoformat()}
    if link.confidence_score is not None:
        props["confidence_score"] = float(link.confidence_score)
    for key in ("model_id", "llm_model_id", "prompt_version", "system_prompt_version_id", "system_prompt_content_hash"):
        value = (link.metadata_ or {}).get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            props[key] = str(value)[:255]
    return props


def build_graph_projection(session: Session, project: Project, document: Document, version: DocumentVersion,
                           chunks: list[Chunk] | None = None) -> GraphProjection:
    session.flush()
    if document.project_id != project.id or version.project_id != project.id or version.document_id != document.id:
        raise AppError("graph_scope_mismatch", "Graph source scope does not match", status_code=409)
    if chunks is None:
        chunks = list(session.scalars(select(Chunk).where(Chunk.project_id == project.id,
            Chunk.document_id == document.id, Chunk.document_version_id == version.id,
            Chunk.status == "active").order_by(Chunk.chunk_index, Chunk.id).execution_options(populate_existing=True)))
    if any(c.project_id != project.id or c.document_version_id != version.id or c.document_id != document.id or c.status != "active" for c in chunks):
        raise AppError("graph_scope_mismatch", "Graph chunk scope does not match", status_code=409)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(kind: str, identity: UUID, **properties: Any) -> None:
        key = str(identity)
        if key in nodes:
            if nodes[key]["type"] != kind:
                raise AppError("graph_identity_conflict", "Graph identities conflict", status_code=409)
            return
        nodes[key] = {"id": key, "type": kind, "properties": properties}

    def edge(source: UUID, relation: str, target: UUID, properties: dict | None = None) -> None:
        edges.append({"source": str(source), "type": relation, "target": str(target), "properties": properties or {}})

    node("Project", project.id, name=project.name)
    node("Document", document.id, title=document.title, project_id=str(project.id), source_type=document.source_type)
    node("DocumentVersion", version.id, version_label=version.version_label, project_id=str(project.id), document_id=str(document.id))
    edge(project.id, "PROJECT_HAS_DOCUMENT", document.id)
    edge(document.id, "DOCUMENT_HAS_VERSION", version.id)
    for chunk in chunks:
        node("Chunk", chunk.id, title=chunk.title, chunk_index=chunk.chunk_index, content_type=chunk.content_type,
             project_id=str(project.id), document_version_id=str(version.id))
        edge(version.id, "VERSION_HAS_CHUNK", chunk.id)
    chunk_ids = [chunk.id for chunk in chunks]
    assignments = list(session.execute(select(DocumentVersionTag, Tag).join(Tag, Tag.id == DocumentVersionTag.tag_id)
        .where(DocumentVersionTag.document_version_id == version.id).execution_options(populate_existing=True)))
    if chunk_ids:
        assignments.extend(session.execute(select(ChunkTag, Tag).join(Tag, Tag.id == ChunkTag.tag_id)
            .where(ChunkTag.chunk_id.in_(chunk_ids)).execution_options(populate_existing=True)))
    for link, tag in assignments:
        if tag.project_id != project.id:
            raise AppError("graph_scope_mismatch", "Graph tag scope does not match", status_code=409)
        node("Tag", tag.id, name=tag.name, project_id=str(project.id))
        is_chunk = isinstance(link, ChunkTag)
        edge(link.chunk_id if is_chunk else version.id, "CHUNK_HAS_TAG" if is_chunk else "VERSION_HAS_TAG",
             tag.id, assignment_properties(link))
    return GraphProjection(project.id, document.id, version.id, version.lock_version, project.work_generation,
                           canonical_graph(list(nodes.values()), edges), int((version.chunk_strategy or {}).get("graph_tag_revision") or 0))


def preview_artifact(projection: GraphProjection) -> dict:
    kinds = {"Project": "project", "Document": "document", "DocumentVersion": "version", "Chunk": "chunk", "Tag": "tag"}
    ids = {n["id"]: (f"tag:{n['id']}" if n["type"] == "Tag" else n["id"]) for n in projection.graph["nodes"]}
    nodes = [{"id": ids[n["id"]], "type": kinds[n["type"]], "technical_id": n["id"],
              "label": n["properties"].get("name") or n["properties"].get("title") or n["properties"].get("version_label") or n["type"],
              **n["properties"]} for n in projection.graph["nodes"]]
    edges = [{"source": ids[e["source"]], "target": ids[e["target"]], "type": e["type"],
              "metadata": e["properties"]} for e in projection.graph["edges"]]
    return {"status": "available", "source": "postgresql_staging_preview", "source_digest": projection.source_digest,
            "revision": projection.revision, "tag_revision": projection.tag_revision, "node_count": len(nodes), "edge_count": len(edges),
            "chunk_count": sum(n["type"] == "chunk" for n in nodes), "nodes": nodes, "edges": edges}


def graph_difference(expected: dict, actual: dict) -> dict:
    def difference(left: list[dict], right: list[dict], key) -> dict:
        a, b = {key(x): x for x in left}, {key(x): x for x in right}
        return {"missing": sorted(a.keys() - b.keys()), "extra": sorted(b.keys() - a.keys()),
                "changed": sorted(k for k in a.keys() & b.keys() if a[k] != b[k])}
    return {"nodes": difference(expected["nodes"], actual["nodes"], lambda n: n["id"]),
            "edges": difference(expected["edges"], actual["edges"], edge_key)}
