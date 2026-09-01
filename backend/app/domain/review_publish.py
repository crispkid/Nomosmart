from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings, neo4j_driver_options
from app.core.errors import AppError
from app.db.models import (
    ActiveVersionManifest,
    ApprovalEvidenceManifest,
    ApprovalRequest,
    ApprovalTask,
    Chunk,
    Document,
    DocumentVersion,
    EmbeddingBuild,
    EmbeddingProfile,
    GraphSyncJob,
    PipelineRun,
    PipelineRunStep,
    Project,
    ProjectOwner,
    ReviewRecord,
    User,
)
from app.domain.embeddings import load_canonical_embeddings, resolve_index_retrieval_text
from app.domain.graph_sync_jobs import enqueue_graph_sync
from app.domain.notifications import emit_notification_event
from app.domain.search import vector_document_id
from app.services.audit import add_audit


MANAGER_REVIEW = "manager_review"
OWNER_REVIEW = "owner_review"
PUBLISH_STAGE = "publish"
GRAPH_SYNC_STAGE = "graph_sync"


@dataclass(frozen=True)
class PublishedIndexResult:
    index_name: str
    document_ids: list[str]
    checksum: str


@dataclass(frozen=True)
class GraphSyncResult:
    node_count: int
    edge_count: int


class PublishedIndexAdapter(Protocol):
    def write_published_chunks(self, *, project_id: UUID, document: Document, version: DocumentVersion, chunks: list[Chunk], vectors: list[list[float]] | None = None, profile: EmbeddingProfile | None = None) -> PublishedIndexResult:
        ...

    def delete_staging_documents(self, *, version: DocumentVersion) -> None:
        ...


class GraphSyncAdapter(Protocol):
    def sync_active_version(self, *, project_id: UUID, document: Document, version: DocumentVersion, chunks: list[Chunk]) -> GraphSyncResult:
        ...


class LiveOpenSearchPublishedAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def write_published_chunks(self, *, project_id: UUID, document: Document, version: DocumentVersion, chunks: list[Chunk], vectors: list[list[float]] | None = None, profile: EmbeddingProfile | None = None) -> PublishedIndexResult:
        if version.embedding_profile_id is None:
            raise AppError("embedding_profile_required", "Embedding profile is required before publish", status_code=409)
        if vectors is None or profile is None:
            raise AppError("embedding_vectors_required", "Published OpenSearch writes require chunk vectors", status_code=409)
        if profile.id != version.embedding_profile_id or profile.model_id != version.embedding_model_id or len(vectors) != len(chunks):
            raise AppError("embedding_profile_mismatch", "Published vectors do not match the document version profile", status_code=409)
        retrieval_texts: list[str] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            if len(vector) != profile.vector_dimension:
                raise AppError("embedding_profile_mismatch", "Chunk vector dimension does not match the published index profile", status_code=409)
            retrieval_texts.append(resolve_index_retrieval_text(chunk, profile=profile))
        index = published_index_name(self.settings.opensearch_index_prefix, version.embedding_profile_id)
        document_ids = [vector_document_id(version.embedding_profile_id, version.id, chunk.id) for chunk in chunks]
        checksum = chunk_checksum(chunks)
        base = self.settings.opensearch_url.rstrip("/")
        context = self.settings.opensearch_ssl_context
        self._ensure_index(base, index, profile, context, verify=True)
        lines: list[str] = []
        for chunk, doc_id, vector, retrieval_text in zip(chunks, document_ids, vectors, retrieval_texts, strict=True):
            lines.append(json.dumps({"index": {"_index": index, "_id": doc_id}}, ensure_ascii=False))
            lines.append(
                json.dumps(
                    {
                        "index_scope": "published",
                        "project_id": str(project_id),
                        "document_id": str(document.id),
                        "document_version_id": str(version.id),
                        "chunk_id": str(chunk.id),
                        "chunk_index": chunk.chunk_index,
                        "title": chunk.title,
                        "document_title": document.title,
                        "content": chunk.content,
                        "display_text": chunk.content,
                        "display_markdown": chunk.display_markdown,
                        "retrieval_text": retrieval_text,
                        "markdown_content": chunk.markdown_content,
                        "content_type": chunk.content_type,
                        "heading_path": chunk.heading_path or ([chunk.section_path] if chunk.section_path else []),
                        "heading_level": chunk.heading_level,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "sequence": chunk.sequence or chunk.chunk_index,
                        "stable_chunk_key": chunk.stable_chunk_key,
                        "embedding_content_hash": chunk.embedding_content_hash,
                        "parser_version": (chunk.chunk_strategy or {}).get("parser_version"),
                        "chunker_version": (chunk.chunk_strategy or {}).get("chunker_version"),
                        "normalizer_version": (chunk.chunk_strategy or {}).get("normalizer_version"),
                        "tokenizer_version": (chunk.chunk_strategy or {}).get("tokenizer_version"),
                        "embedding_vector": vector,
                        "embedding_profile_id": str(version.embedding_profile_id),
                        "embedding_model_id": str(version.embedding_model_id) if version.embedding_model_id else None,
                        "vector_dimension": profile.vector_dimension,
                        "mapping_version": profile.mapping_version,
                        "version_status": "published",
                        "published_at": datetime.now(UTC).isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
        self._request("POST", f"{base}/_bulk", ("\n".join(lines) + "\n").encode("utf-8"), context=context, content_type="application/x-ndjson")
        return PublishedIndexResult(index_name=index, document_ids=document_ids, checksum=checksum)

    def delete_staging_documents(self, *, version: DocumentVersion) -> None:
        if not version.extraction_artifact_uri or not version.extraction_artifact_uri.startswith("opensearch://"):
            return
        index = version.extraction_artifact_uri.removeprefix("opensearch://")
        base = self.settings.opensearch_url.rstrip("/")
        context = self.settings.opensearch_ssl_context
        self._request("DELETE", f"{base}/{index}", b"", context=context, content_type="application/json", allow_missing=True)

    def staging_index_exists(self, *, version: DocumentVersion) -> bool:
        if not version.extraction_artifact_uri or not version.extraction_artifact_uri.startswith("opensearch://"):
            return False
        index = version.extraction_artifact_uri.removeprefix("opensearch://")
        base = self.settings.opensearch_url.rstrip("/")
        context = self.settings.opensearch_ssl_context
        request = self._request_with_auth("HEAD", f"{base}/{index}", b"", content_type="application/json")
        try:
            with urllib.request.urlopen(request, timeout=10, context=context) as response:  # noqa: S310 - operator-configured Development endpoint
                return response.status < 400
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise AppError("opensearch_published_write_failed", "OpenSearch staging verification failed", status_code=502) from exc
        except OSError as exc:
            raise AppError("opensearch_published_unavailable", "OpenSearch published endpoint is unavailable", status_code=503) from exc

    def _request(
        self,
        method: str,
        url: str,
        body: bytes,
        *,
        context: ssl.SSLContext | None,
        content_type: str,
        allow_existing_index: bool = False,
        allow_missing: bool = False,
    ) -> None:
        request = urllib.request.Request(url, data=body, method=method, headers={"content-type": content_type})
        username = self.settings.opensearch_username.get_secret_value()
        password = self.settings.opensearch_password.get_secret_value()
        if username or password:
            token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            request.add_header("authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(request, timeout=10, context=context) as response:  # noqa: S310 - operator-configured Development endpoint
                if response.status >= 400:
                    raise AppError("opensearch_published_write_failed", "OpenSearch published operation failed", status_code=502)
        except urllib.error.HTTPError as exc:
            if allow_existing_index and exc.code == 400:
                return
            if allow_missing and exc.code == 404:
                return
            raise AppError("opensearch_published_write_failed", "OpenSearch published operation failed", status_code=502) from exc
        except OSError as exc:
            raise AppError("opensearch_published_unavailable", "OpenSearch published endpoint is unavailable", status_code=503) from exc

    def _ensure_index(self, base: str, index: str, profile: EmbeddingProfile, context: ssl.SSLContext | None, *, verify: bool = True) -> None:
        mapping = _vector_index_mapping(profile)
        try:
            self._request("PUT", f"{base}/{index}", json.dumps(mapping).encode("utf-8"), context=context, content_type="application/json", allow_existing_index=False)
        except AppError:
            self._request("PUT", f"{base}/{index}/_mapping", json.dumps(mapping["mappings"]).encode("utf-8"), context=context, content_type="application/json")
        if not verify:
            return
        request = self._request_with_auth("GET", f"{base}/{index}/_mapping", b"", content_type="application/json")
        try:
            with urllib.request.urlopen(request, timeout=10, context=context) as response:  # noqa: S310 - operator-configured Development endpoint
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AppError("vector_index_not_ready", "OpenSearch published vector mapping could not be verified", status_code=503) from exc
        properties = next(iter(payload.values()), {}).get("mappings", {}).get("properties", {})
        vector_field = properties.get("embedding_vector") if isinstance(properties, dict) else None
        if not isinstance(vector_field, dict) or vector_field.get("dimension") != profile.vector_dimension:
            raise AppError("vector_index_not_ready", "OpenSearch published vector mapping is not ready", status_code=409)

    def _request_with_auth(self, method: str, url: str, body: bytes, *, content_type: str) -> urllib.request.Request:
        request = urllib.request.Request(url, data=body, method=method, headers={"content-type": content_type})
        username = self.settings.opensearch_username.get_secret_value()
        password = self.settings.opensearch_password.get_secret_value()
        if username or password:
            token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            request.add_header("authorization", f"Basic {token}")
        return request


class LiveNeo4jGraphSyncAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def sync_active_version(self, *, project_id: UUID, document: Document, version: DocumentVersion, chunks: list[Chunk]) -> GraphSyncResult:
        return self._replace_version(project_id=project_id, document=document, version=version, chunks=chunks, status="active")

    def sync_candidate_version(self, *, project_id: UUID, document: Document, version: DocumentVersion, chunks: list[Chunk], chunk_tags: dict[UUID, list[dict[str, str]]] | None = None, version_tags: list[dict[str, str]] | None = None) -> GraphSyncResult:
        return self._replace_version(project_id=project_id, document=document, version=version, chunks=chunks, status="staging", chunk_tags=chunk_tags, version_tags=version_tags)

    def delete_version(self, *, version_id: UUID) -> None:
        driver = self._driver()
        try:
            with driver.session(database=self.settings.neo4j_database) as session:
                session.execute_write(_delete_version_graph, version_id)
                remaining = session.execute_read(_count_version_graph, version_id)
                if remaining:
                    raise AppError("project_archive_graph_delete_unverified", "Archived project graph version still exists after deletion", status_code=503)
        finally:
            driver.close()

    def _replace_version(self, *, project_id: UUID, document: Document, version: DocumentVersion, chunks: list[Chunk], status: str, chunk_tags: dict[UUID, list[dict[str, str]]] | None = None, version_tags: list[dict[str, str]] | None = None) -> GraphSyncResult:
        driver = self._driver()
        node_count = 2 + len(chunks)
        edge_count = 1 + len(chunks)
        try:
            with driver.session(database=self.settings.neo4j_database) as session:
                session.execute_write(_write_graph, project_id, document, version, chunks, status, chunk_tags or {}, version_tags or [])
        finally:
            driver.close()
        return GraphSyncResult(node_count=node_count, edge_count=edge_count)

    def _driver(self):
        try:
            from neo4j import GraphDatabase  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on optional runtime driver
            raise AppError("neo4j_driver_unavailable", "Neo4j driver is required for live graph sync", status_code=503) from exc
        return GraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_username.get_secret_value(), self.settings.neo4j_password.get_secret_value()),
            **neo4j_driver_options(self.settings),
        )


def _write_graph(tx, project_id: UUID, document: Document, version: DocumentVersion, chunks: list[Chunk], status: str = "active", chunk_tags: dict[UUID, list[dict[str, str]]] | None = None, version_tags: list[dict[str, str]] | None = None) -> None:
    _delete_version_chunks(tx, version.id)
    tx.run(
        """
        MERGE (p:Project {id: $project_id})
        MERGE (d:Document {id: $document_id})
        SET d.title = $title, d.status = 'active'
        MERGE (v:DocumentVersion {id: $version_id})
        SET v.version_label = $version_label, v.status = $status
        MERGE (p)-[:PROJECT_HAS_DOCUMENT]->(d)
        MERGE (d)-[:DOCUMENT_HAS_VERSION]->(v)
        """,
        project_id=str(project_id),
        document_id=str(document.id),
        title=document.title,
        version_id=str(version.id),
        version_label=version.version_label,
        status=status,
    )
    for chunk in chunks:
        tx.run(
            """
            MATCH (v:DocumentVersion {id: $version_id})
            MERGE (c:Chunk {id: $chunk_id})
            SET c.chunk_index = $chunk_index, c.content_type = $content_type, c.title = $title
            MERGE (v)-[:VERSION_HAS_CHUNK]->(c)
            """,
            version_id=str(version.id),
            chunk_id=str(chunk.id),
            chunk_index=chunk.chunk_index,
            content_type=chunk.content_type,
            title=chunk.title,
        )
        for tag in (chunk_tags or {}).get(chunk.id, []):
            tx.run(
                """
                MATCH (c:Chunk {id: $chunk_id})
                MERGE (t:Tag {id: $tag_id})
                SET t.name = $tag_name, t.project_id = $project_id
                MERGE (c)-[:CHUNK_HAS_TAG]->(t)
                """,
                chunk_id=str(chunk.id), tag_id=tag["id"], tag_name=tag["name"], project_id=str(project_id),
            )
    for tag in version_tags or []:
        tx.run(
            """
            MATCH (v:DocumentVersion {id: $version_id})
            MERGE (t:Tag {id: $tag_id})
            SET t.name = $tag_name, t.project_id = $project_id
            MERGE (v)-[:VERSION_HAS_TAG]->(t)
            """,
            version_id=str(version.id), tag_id=tag["id"], tag_name=tag["name"], project_id=str(project_id),
        )


def _delete_version_chunks(tx, version_id: UUID) -> None:
    tx.run(
        """
        MATCH (v:DocumentVersion {id: $version_id})-[:VERSION_HAS_CHUNK]->(c:Chunk)
        DETACH DELETE c
        """,
        version_id=str(version_id),
    )
    tx.run(
        """
        MATCH (v:DocumentVersion {id: $version_id})-[r:VERSION_HAS_TAG]->(:Tag)
        DELETE r
        """,
        version_id=str(version_id),
    )
    tx.run("MATCH (t:Tag) WHERE NOT ()-[:CHUNK_HAS_TAG|VERSION_HAS_TAG]->(t) DETACH DELETE t")


def _delete_version_graph(tx, version_id: UUID) -> None:
    _delete_version_chunks(tx, version_id)
    tx.run(
        """
        MATCH (v:DocumentVersion {id: $version_id})
        DETACH DELETE v
        """,
        version_id=str(version_id),
    )


def _count_version_graph(tx, version_id: UUID) -> int:
    record = tx.run(
        "MATCH (v:DocumentVersion {id: $version_id}) RETURN count(v) AS count",
        version_id=str(version_id),
    ).single()
    return int(record["count"]) if record is not None else 0


def submit_review(
    *,
    session: Session,
    actor_user_id: UUID,
    version: DocumentVersion,
    owner_user_id: UUID | None,
    request_id: str | None,
    evidence_revision: str,
    evidence_manifest: dict,
    evidence_generated_at: datetime,
) -> ApprovalRequest:
    if version.status != "submission_ready":
        raise AppError("version_not_submission_ready", "Document version is not ready for review", status_code=409)
    existing = session.scalar(select(ApprovalRequest).where(ApprovalRequest.document_version_id == version.id, ApprovalRequest.status.in_(("pending_manager_review", "pending_owner_review", "approved"))))
    if existing:
        raise AppError("approval_already_in_progress", "Document version already has an active approval request", status_code=409)
    submitter = session.get(User, actor_user_id)
    if submitter is None or not submitter.is_active:
        raise AppError("submitter_not_found", "Submitter is unavailable", status_code=403)
    assignee_id, delegated_from = _manager_or_delegate(submitter)
    now = datetime.now(UTC)
    manifest_hash = sha256(
        json.dumps(evidence_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    if manifest_hash != evidence_revision:
        raise AppError("submission_evidence_integrity_failed", "Submission evidence revision does not match its manifest", status_code=409)
    request = ApprovalRequest(project_id=version.project_id, document_id=version.document_id, document_version_id=version.id, submitter_id=actor_user_id, owner_user_id=owner_user_id or actor_user_id, evidence_revision=evidence_revision, status="pending_manager_review", submitted_at=now, created_at=now)
    session.add(request)
    session.flush()
    session.add(
        ApprovalEvidenceManifest(
            approval_request_id=request.id,
            project_id=version.project_id,
            document_id=version.document_id,
            document_version_id=version.id,
            evidence_revision=evidence_revision,
            manifest_hash=manifest_hash,
            manifest=evidence_manifest,
            generated_at=evidence_generated_at,
            submitted_at=now,
            created_by=actor_user_id,
        )
    )
    task = ApprovalTask(approval_request_id=request.id, project_id=version.project_id, document_id=version.document_id, document_version_id=version.id, submitter_id=actor_user_id, assignee_user_id=assignee_id, review_stage=MANAGER_REVIEW, status="pending", submitted_at=now, created_at=now)
    session.add(task)
    session.flush()
    request.current_task_id = task.id
    version.status = "pending_manager_review"
    _mark_pipeline_waiting(session, version.id, MANAGER_REVIEW, "manager")
    if assignee_id:
        _notify(session, assignee_id, version.project_id, "review.manager.pending", "待主管審核", f"文件版本 {version.version_label} 等待主管審核", {"approval_task_id": str(task.id), "document_version_id": str(version.id)})
    add_audit(session, actor_user_id=actor_user_id, action="approval.submit", resource_type="document_version", resource_id=version.id, result="success", request_id=request_id, summary={"approval_request_id": str(request.id), "manager_user_id": str(assignee_id) if assignee_id else None, "delegated_from_user_id": str(delegated_from) if delegated_from else None})
    return request


def approve_task(*, session: Session, actor_user_id: UUID, task: ApprovalTask, lock_version: int, comment: str | None, request_id: str | None) -> ApprovalTask:
    _ensure_pending_task(task, lock_version)
    request = _approval_request(session, task.approval_request_id)
    version = _version(session, task.document_version_id)
    now = datetime.now(UTC)
    task.status = "approved"
    task.completed_at = now
    task.lock_version += 1
    session.add(ReviewRecord(project_id=task.project_id, document_id=task.document_id, document_version_id=task.document_version_id, review_stage=task.review_stage, reviewer_id=actor_user_id, delegated_from_user_id=None, status="approved", comment=comment, created_at=now))
    if task.review_stage == MANAGER_REVIEW:
        _complete_pipeline_step(session, version.id, MANAGER_REVIEW, "Manager review approved")
        owner_task = ApprovalTask(approval_request_id=request.id, project_id=task.project_id, document_id=task.document_id, document_version_id=task.document_version_id, submitter_id=task.submitter_id, assignee_user_id=None, review_stage=OWNER_REVIEW, status="pending", submitted_at=now, created_at=now)
        session.add(owner_task)
        session.flush()
        request.status = "pending_owner_review"
        request.current_task_id = owner_task.id
        version.status = "pending_owner_review"
        _mark_pipeline_waiting(session, version.id, OWNER_REVIEW, "project_owner")
        for owner_id in session.scalars(select(ProjectOwner.user_id).where(ProjectOwner.project_id == task.project_id)):
            _notify(session, owner_id, task.project_id, "review.owner.pending", "待 Owner 審核", f"文件版本 {version.version_label} 等待 Project Owner 審核", {"approval_task_id": str(owner_task.id), "document_version_id": str(version.id)})
    elif task.review_stage == OWNER_REVIEW:
        request.status = "approved"
        request.current_task_id = None
        request.approved_at = now
        version.status = "approved"
        _complete_pipeline_step(session, version.id, OWNER_REVIEW, "Project Owner review approved")
        _mark_pipeline_waiting(session, version.id, PUBLISH_STAGE, "publisher")
        _notify(session, task.submitter_id, task.project_id, "review.approved", "審核已通過，等待發布", f"文件版本 {version.version_label} 已通過審核", {"document_version_id": str(version.id)})
    add_audit(session, actor_user_id=actor_user_id, action=f"approval.{task.review_stage}.approve", resource_type="approval_task", resource_id=task.id, result="success", request_id=request_id, summary={"comment": comment})
    return task


def reject_task(*, session: Session, actor_user_id: UUID, task: ApprovalTask, lock_version: int, comment: str, request_id: str | None) -> ApprovalTask:
    if not comment.strip():
        raise AppError("rejection_reason_required", "Rejection reason is required", status_code=422)
    _ensure_pending_task(task, lock_version)
    request = _approval_request(session, task.approval_request_id)
    version = _version(session, task.document_version_id)
    now = datetime.now(UTC)
    task.status = "rejected"
    task.completed_at = now
    task.lock_version += 1
    request.status = "rejected"
    request.current_task_id = None
    version.status = "review_rejected"
    version.inactive_reason = "review_rejected"
    _mark_pipeline_rejected(session, version.id, task.review_stage, "Review rejected")
    session.add(ReviewRecord(project_id=task.project_id, document_id=task.document_id, document_version_id=task.document_version_id, review_stage=task.review_stage, reviewer_id=actor_user_id, delegated_from_user_id=None, status="rejected", comment=comment, created_at=now))
    _notify(session, task.submitter_id, task.project_id, "review.rejected", "審核已退回", f"文件版本 {version.version_label} 已退回，請建立新 revision 修正後重新送審", {"document_version_id": str(version.id), "reason": comment})
    add_audit(session, actor_user_id=actor_user_id, action=f"approval.{task.review_stage}.reject", resource_type="approval_task", resource_id=task.id, result="success", request_id=request_id, summary={"comment": comment})
    return task


def publish_version(
    *,
    session: Session,
    actor_user_id: UUID,
    document: Document,
    version: DocumentVersion,
    lock_version: int,
    request_id: str | None,
    search_adapter: PublishedIndexAdapter,
    graph_adapter: GraphSyncAdapter,
) -> tuple[ActiveVersionManifest, PublishedIndexResult, GraphSyncJob]:
    project = session.scalar(select(Project).where(Project.id == version.project_id).with_for_update())
    if project is None or project.status != "active":
        raise AppError("project_archived", "Archived projects cannot publish document versions", status_code=409)
    if version.lock_version != lock_version:
        raise AppError("stale_document_version", "Document version was changed by another request", status_code=409)
    if version.status not in {"approved", "inactive", "active"}:
        raise AppError("version_not_publishable", "Only approved or previously published compatible versions can be published", status_code=409)
    if version.embedding_profile_id is None:
        raise AppError("embedding_profile_required", "Embedding profile is required before publish", status_code=409)
    chunks = list(
        session.scalars(
            select(Chunk)
            .where(Chunk.document_version_id == version.id, Chunk.status == "active")
            .order_by(Chunk.chunk_index)
        )
    )
    if not chunks:
        raise AppError("publish_chunks_required", "Published version requires chunks", status_code=409)
    project = _project(session, version.project_id)
    embedding_batch = load_canonical_embeddings(session, project=project, version=version, chunks=chunks)
    _start_pipeline_step(session, version.id, PUBLISH_STAGE, "Publishing approved version")
    _complete_pipeline_step(session, version.id, PUBLISH_STAGE, "Publish authorized")
    _start_pipeline_step(session, version.id, "production_index", "Writing published index")
    try:
        index_result = search_adapter.write_published_chunks(
            project_id=version.project_id,
            document=document,
            version=version,
            chunks=chunks,
            vectors=embedding_batch.vectors,
            profile=embedding_batch.profile,
        )
    except AppError as exc:
        _fail_pipeline_step(session, version.id, "production_index", exc.message)
        raise
    if len(index_result.document_ids) != len(chunks):
        _fail_pipeline_step(session, version.id, "production_index", "Published index chunk count does not match")
        raise AppError("published_index_verification_failed", "Published index chunk count does not match", status_code=502)
    _complete_pipeline_step(session, version.id, "production_index", "Published index written")
    now = datetime.now(UTC)
    existing_manifest = session.scalar(select(ActiveVersionManifest).where(ActiveVersionManifest.document_id == document.id).with_for_update())
    old_version_id = existing_manifest.document_version_id if existing_manifest else None
    build = _embedding_build(session, version, index_result, len(chunks))
    generation = (existing_manifest.publication_generation + 1) if existing_manifest else 1
    if existing_manifest is None:
        manifest = ActiveVersionManifest(project_id=version.project_id, document_id=document.id, document_version_id=version.id, embedding_profile_id=version.embedding_profile_id, embedding_build_id=build.id, publication_generation=generation, index_ready=True, lock_version=1)
        session.add(manifest)
        session.flush()
    else:
        manifest = existing_manifest
        manifest.document_version_id = version.id
        manifest.embedding_profile_id = version.embedding_profile_id
        manifest.embedding_build_id = build.id
        manifest.publication_generation = generation
        manifest.index_ready = True
        manifest.lock_version += 1
    if old_version_id and old_version_id != version.id:
        old_version = session.get(DocumentVersion, old_version_id)
        if old_version:
            old_version.status = "inactive"
            old_version.inactive_reason = "superseded"
    version.status = "active"
    version.published_at = now
    version.published_by = actor_user_id
    version.inactive_reason = None
    version.lock_version += 1
    document.status = "active"
    search_adapter.delete_staging_documents(version=version)
    graph_job = GraphSyncJob(project_id=version.project_id, document_id=document.id, document_version_id=version.id, trigger_type="document_published", status="running", created_at=now)
    session.add(graph_job)
    session.flush()
    _start_pipeline_step(session, version.id, GRAPH_SYNC_STAGE, "Synchronizing knowledge graph")
    try:
        graph_result = graph_adapter.sync_active_version(project_id=version.project_id, document=document, version=version, chunks=chunks)
        graph_job.status = "completed"
        graph_job.node_count = graph_result.node_count
        graph_job.edge_count = graph_result.edge_count
        graph_job.completed_at = datetime.now(UTC)
        _complete_pipeline_publication(session, version.id)
    except AppError as exc:
        graph_job.status = "failed"
        graph_job.error_message = exc.message
        _fail_pipeline_step(session, version.id, GRAPH_SYNC_STAGE, exc.message)
        add_audit(session, actor_user_id=actor_user_id, action="graph_sync.failed", resource_type="document_version", resource_id=version.id, result="failed", request_id=request_id, summary={"code": exc.code})
        raise
    request = session.scalar(select(ApprovalRequest).where(ApprovalRequest.document_version_id == version.id).order_by(desc(ApprovalRequest.created_at)).limit(1))
    if request:
        request.status = "published"
        request.published_at = now
    _notify(session, version.published_by, version.project_id, "document.published", "文件版本已發布", f"文件版本 {version.version_label} 已正式發布", {"document_version_id": str(version.id), "manifest_id": str(manifest.id)})
    add_audit(session, actor_user_id=actor_user_id, action="document_version.publish", resource_type="document_version", resource_id=version.id, result="success", request_id=request_id, summary={"manifest_id": str(manifest.id), "generation": generation, "opensearch_index": index_result.index_name, "graph_sync_job_id": str(graph_job.id)})
    return manifest, index_result, graph_job


def switch_active_version(
    *,
    session: Session,
    actor_user_id: UUID,
    document: Document,
    version: DocumentVersion,
    lock_version: int,
    impact_confirmed: bool,
    audit_reason: str,
    request_id: str | None,
) -> tuple[ActiveVersionManifest, GraphSyncJob]:
    if not impact_confirmed:
        raise AppError("impact_confirmation_required", "Active version switch requires impact confirmation", status_code=422)
    if not audit_reason.strip():
        raise AppError("switch_reason_required", "Active version switch requires an audit reason", status_code=422)
    if version.lock_version != lock_version:
        raise AppError("stale_document_version", "Document version was changed by another request", status_code=409)
    if version.status not in {"inactive", "active"} or version.published_at is None:
        raise AppError("version_not_switchable", "Only previously published versions can be switched active", status_code=409)
    if version.embedding_profile_id is None:
        raise AppError("embedding_profile_required", "Embedding profile is required before switch", status_code=409)
    existing_manifest = session.scalar(select(ActiveVersionManifest).where(ActiveVersionManifest.document_id == document.id).with_for_update())
    if existing_manifest is None or not existing_manifest.index_ready:
        raise AppError("active_manifest_required", "Current active manifest is required before switching", status_code=409)
    if existing_manifest.document_version_id == version.id:
        raise AppError("version_already_active", "Document version is already active", status_code=409)
    if existing_manifest.embedding_profile_id != version.embedding_profile_id:
        raise AppError("embedding_profile_incompatible", "Embedding profile is incompatible with the active manifest", status_code=409)
    build = session.scalar(select(EmbeddingBuild).where(EmbeddingBuild.document_version_id == version.id, EmbeddingBuild.embedding_profile_id == version.embedding_profile_id, EmbeddingBuild.status == "published").order_by(desc(EmbeddingBuild.build_revision)).limit(1))
    if build is None or not build.index_name:
        raise AppError("published_index_not_ready", "Published index data is not ready for this version", status_code=409)
    chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id).order_by(Chunk.chunk_index)))
    if not chunks:
        raise AppError("publish_chunks_required", "Switchable version requires chunks", status_code=409)

    now = datetime.now(UTC)
    old_version = session.get(DocumentVersion, existing_manifest.document_version_id)
    if old_version and old_version.id != version.id:
        old_version.status = "inactive"
        old_version.inactive_reason = "superseded"
    existing_manifest.document_version_id = version.id
    existing_manifest.embedding_build_id = build.id
    existing_manifest.publication_generation += 1
    existing_manifest.index_ready = True
    existing_manifest.lock_version += 1
    version.status = "active"
    version.inactive_reason = None
    version.lock_version += 1
    document.status = "active"

    graph_job = enqueue_graph_sync(
        session,
        project_id=version.project_id,
        document_id=document.id,
        document_version_id=version.id,
        trigger_type="active_version_switched",
        requested_by_user_id=actor_user_id,
        request_id=request_id,
    )
    _notify(session, actor_user_id, version.project_id, "document.active_switched", "生效版本已切換", f"文件版本 {version.version_label} 已切換為正式生效版本", {"document_version_id": str(version.id), "manifest_id": str(existing_manifest.id)})
    add_audit(session, actor_user_id=actor_user_id, action="document_version.switch_active", resource_type="document_version", resource_id=version.id, result="success", request_id=request_id, summary={"manifest_id": str(existing_manifest.id), "generation": existing_manifest.publication_generation, "graph_sync_job_id": str(graph_job.id), "reason": audit_reason})
    return existing_manifest, graph_job


def published_index_name(prefix: str, embedding_profile_id: UUID) -> str:
    return f"{prefix}-published-profile-{str(embedding_profile_id)[:8]}".lower()


def _project(session: Session, project_id: UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    return project


def _vector_index_mapping(profile: EmbeddingProfile) -> dict[str, object]:
    mapping_version = int(getattr(profile, "mapping_version", 1) or 1)
    source_text_mapping = (
        {"type": "text", "index": False}
        if mapping_version >= 2
        else {"type": "text"}
    )
    return {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                "index_scope": {"type": "keyword"},
                "project_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "document_version_id": {"type": "keyword"},
                "chunk_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "title": {"type": "text"},
                "document_title": {"type": "text"},
                "content": dict(source_text_mapping),
                "display_text": dict(source_text_mapping),
                # Renderer source is never a retrieval field, including while
                # reading legacy profiles.
                "display_markdown": {"type": "text", "index": False},
                "retrieval_text": {"type": "text"},
                "markdown_content": dict(source_text_mapping),
                "content_type": {"type": "keyword"},
                "heading_path": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "heading_level": {"type": "integer"},
                "page_start": {"type": "integer"},
                "page_end": {"type": "integer"},
                "sequence": {"type": "integer"},
                "stable_chunk_key": {"type": "keyword"},
                "embedding_content_hash": {"type": "keyword"},
                "parser_version": {"type": "keyword"},
                "chunker_version": {"type": "keyword"},
                "normalizer_version": {"type": "keyword"},
                "tokenizer_version": {"type": "keyword"},
                "embedding_vector": {
                    "type": "knn_vector",
                    "dimension": profile.vector_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                    },
                },
                "embedding_profile_id": {"type": "keyword"},
                "embedding_model_id": {"type": "keyword"},
                "vector_dimension": {"type": "integer"},
                "mapping_version": {"type": "integer"},
                "version_status": {"type": "keyword"},
                "published_at": {"type": "date"},
            }
        },
    }


def chunk_checksum(chunks: list[Chunk]) -> str:
    payload = [
        {
            "id": str(chunk.id),
            "stable_chunk_key": chunk.stable_chunk_key,
            "display_hash": chunk.content_hash,
            "embedding_content_hash": chunk.embedding_content_hash,
            "index": chunk.chunk_index,
            "sequence": chunk.sequence,
        }
        for chunk in chunks
    ]
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _embedding_build(session: Session, version: DocumentVersion, index_result: PublishedIndexResult, chunk_count: int) -> EmbeddingBuild:
    if version.embedding_profile_id is None:
        raise AppError("embedding_profile_required", "Embedding profile is required before publish", status_code=409)
    build = session.scalar(select(EmbeddingBuild).where(EmbeddingBuild.document_version_id == version.id, EmbeddingBuild.embedding_profile_id == version.embedding_profile_id).order_by(desc(EmbeddingBuild.build_revision)).limit(1))
    if build is None:
        build = EmbeddingBuild(project_id=version.project_id, document_id=version.document_id, document_version_id=version.id, embedding_profile_id=version.embedding_profile_id, build_revision=1, status="published", chunk_count=chunk_count, index_name=index_result.index_name, checksum=index_result.checksum)
        session.add(build)
        session.flush()
    else:
        build.status = "published"
        build.chunk_count = chunk_count
        build.index_name = index_result.index_name
        build.checksum = index_result.checksum
    return build


def _manager_or_delegate(user: User) -> tuple[UUID | None, UUID | None]:
    now = datetime.now(UTC)
    if user.manager_delegate_user_id and (user.manager_delegate_start_at is None or user.manager_delegate_start_at <= now) and (user.manager_delegate_end_at is None or user.manager_delegate_end_at >= now):
        return user.manager_delegate_user_id, user.manager_user_id
    return user.manager_user_id, None


def _ensure_pending_task(task: ApprovalTask, lock_version: int) -> None:
    if task.status != "pending":
        raise AppError("approval_task_not_pending", "Approval task is no longer pending", status_code=409)
    if task.lock_version != lock_version:
        raise AppError("stale_approval_task", "Approval task was changed by another request", status_code=409)


def _approval_request(session: Session, request_id: UUID) -> ApprovalRequest:
    request = session.get(ApprovalRequest, request_id)
    if request is None:
        raise AppError("approval_request_not_found", "Approval request was not found", status_code=404)
    return request


def _version(session: Session, version_id: UUID) -> DocumentVersion:
    version = session.get(DocumentVersion, version_id)
    if version is None:
        raise AppError("document_version_not_found", "Document version was not found", status_code=404)
    return version


def _mark_pipeline_waiting(session: Session, version_id: UUID, step_name: str, waiting_role: str) -> None:
    pipeline = _pipeline_for_version(session, version_id)
    if pipeline is None:
        return
    pipeline.status = "waiting_action"
    pipeline.current_step_name = step_name
    pipeline.current_waiting_role = waiting_role
    pipeline.current_action_url = f"/approve/{pipeline.id}" if step_name in {MANAGER_REVIEW, OWNER_REVIEW} else None
    step = _pipeline_step(session, pipeline.id, step_name)
    if step:
        step.status = "waiting_action"
        step.progress_percent = 0
        step.started_at = None
        step.completed_at = None
        step.error_message = None
        step.progress_message = f"Waiting for {waiting_role}"


def _mark_pipeline_rejected(session: Session, version_id: UUID, step_name: str, message: str) -> None:
    pipeline = _pipeline_for_version(session, version_id)
    if pipeline is None:
        return
    pipeline.status = "review_rejected"
    pipeline.current_step_name = step_name
    pipeline.current_waiting_role = "submitter"
    pipeline.current_action_url = None
    step = _pipeline_step(session, pipeline.id, step_name)
    if step:
        step.status = "review_rejected"
        step.progress_percent = 100
        step.completed_at = datetime.now(UTC)
        step.progress_message = message
        step.error_message = None


def _start_pipeline_step(session: Session, version_id: UUID, step_name: str, message: str) -> None:
    pipeline = _pipeline_for_version(session, version_id)
    if pipeline is None:
        return
    pipeline.status = "running"
    pipeline.current_step_name = step_name
    pipeline.current_waiting_role = None
    pipeline.current_action_url = None
    pipeline.completed_at = None
    step = _pipeline_step(session, pipeline.id, step_name)
    if step:
        step.status = "running"
        step.progress_percent = 10
        step.started_at = datetime.now(UTC)
        step.completed_at = None
        step.error_message = None
        step.progress_message = message


def _complete_pipeline_step(session: Session, version_id: UUID, step_name: str, message: str) -> None:
    pipeline = _pipeline_for_version(session, version_id)
    if pipeline is None:
        return
    step = _pipeline_step(session, pipeline.id, step_name)
    if step:
        step.status = "completed"
        step.progress_percent = 100
        step.completed_at = datetime.now(UTC)
        step.error_message = None
        step.progress_message = message


def _fail_pipeline_step(session: Session, version_id: UUID, step_name: str, message: str) -> None:
    pipeline = _pipeline_for_version(session, version_id)
    if pipeline is None:
        return
    pipeline.status = "failed"
    pipeline.current_step_name = step_name
    pipeline.error_message = message
    pipeline.current_waiting_role = None
    pipeline.current_action_url = None
    step = _pipeline_step(session, pipeline.id, step_name)
    if step:
        step.status = "failed"
        step.completed_at = datetime.now(UTC)
        step.error_message = message
        step.progress_message = message


def _pipeline_for_version(session: Session, version_id: UUID) -> PipelineRun | None:
    return session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version_id).order_by(desc(PipelineRun.created_at)).limit(1))


def _pipeline_step(session: Session, pipeline_id: UUID, step_name: str) -> PipelineRunStep | None:
    return session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline_id, PipelineRunStep.step_name == step_name))


def _complete_pipeline_publication(session: Session, version_id: UUID) -> None:
    pipeline = _pipeline_for_version(session, version_id)
    if not pipeline:
        return
    pipeline.status = "completed"
    pipeline.progress_percent = 100
    pipeline.current_step_name = GRAPH_SYNC_STAGE
    pipeline.current_waiting_role = None
    pipeline.current_action_url = None
    pipeline.completed_at = datetime.now(UTC)
    for name in (PUBLISH_STAGE, "production_index", GRAPH_SYNC_STAGE):
        step = _pipeline_step(session, pipeline.id, name)
        if step:
            step.status = "completed"
            step.progress_percent = 100
            step.completed_at = datetime.now(UTC)


def _notify(session: Session, recipient_user_id: UUID | None, project_id: UUID | None, notification_type: str, title: str, message: str, payload: dict[str, str]) -> None:
    if recipient_user_id is None:
        return
    target_id = payload.get("document_version_id") or payload.get("approval_task_id") or payload.get("manifest_id") or "unknown"
    business_key = f"review:{target_id}"
    terminal = notification_type in {"review.approved", "review.rejected", "document.published", "document.active_switched"}
    emit_notification_event(
        session,
        project_id=project_id,
        event_type=notification_type,
        business_key=business_key,
        recipient_user_ids=[recipient_user_id],
        severity="info",
        title=title,
        message=message,
        action_type="review",
        action_payload=payload,
        terminal=terminal,
    )
