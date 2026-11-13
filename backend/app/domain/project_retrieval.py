"""Project retrieval and answer generation shared by Chat and validation runs (OPT424-021).

Moved unchanged from app.api.routes.serving so domain code and workers never import route modules:
retrieval scope resolution, staging/published hybrid search, prompt chunk selection and the
citation-bound answer call.
"""
from __future__ import annotations

import json
import re
import urllib.request

from app.api.schemas import ProjectChatCitation
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import AIModel, ActiveVersionManifest, Chunk, Document, DocumentVersion, EmbeddingProfile, Project
from app.domain.ai_provider import generate_rag_answer
from app.domain.chat_citations import chunk_display_markdown
from app.domain.chat_retrieval import fuse_ranked_hits, is_markdown_heading_only, is_structural_only
from app.domain.chunk_artifacts import require_ready_chunk_artifacts
from app.domain.embeddings import embed_query
from app.domain.extraction_pipeline import staging_index_name
from app.domain.review_publish import published_index_name
from app.domain.staging_retention import require_unexpired
from app.domain.system_prompts import resolve_system_prompt
from base64 import b64encode
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID


def _resolve_retrieval_scope(session: Session, project_id: UUID, document_version_ids: list[UUID] | None) -> tuple[list[ActiveVersionManifest], set[UUID], set[UUID]]:
    manifests = list(session.scalars(_active_retrieval_manifest_query(project_id).where(ActiveVersionManifest.index_ready.is_(True))))
    if not manifests:
        raise AppError("active_manifest_required", "Project has no ready active manifest for retrieval", status_code=409)
    manifest_ids = {manifest.document_version_id for manifest in manifests}
    requested_ids = set(document_version_ids or manifest_ids)
    if not requested_ids or not requested_ids.issubset(manifest_ids):
        raise AppError("retrieval_scope_denied", "Retrieval scope must be active published document versions in this project", status_code=403)
    return manifests, manifest_ids, requested_ids


def _active_retrieval_manifest_query(project_id: UUID):
    return (
        select(ActiveVersionManifest)
        .join(Document, ActiveVersionManifest.document_id == Document.id)
        .join(DocumentVersion, ActiveVersionManifest.document_version_id == DocumentVersion.id)
        .where(
            ActiveVersionManifest.project_id == project_id,
            Document.project_id == project_id,
            DocumentVersion.project_id == project_id,
            DocumentVersion.document_id == Document.id,
            Document.is_deleted.is_(False),
            Document.status == "active",
            DocumentVersion.status == "active",
        )
    )


def _resolve_document_staging_scope(session: Session, project_id: UUID, document_version_ids: list[UUID] | None) -> set[UUID]:
    requested_ids = set(document_version_ids or [])
    if not requested_ids:
        raise AppError("retrieval_scope_required", "Document staging retrieval requires an explicit document version scope", status_code=422)
    # Parent locks must precede the shared Version fence. Otherwise evidence's
    # parent FKs can wait on a writer that is itself waiting for this Version.
    # KEY SHARE parents allow concurrent readers; Version SHARE protects JSON
    # citations through evidence commit. Lock multi-document scopes in ID order.
    project = session.scalar(select(Project).where(Project.id == project_id)
        .with_for_update(read=True, key_share=True).execution_options(populate_existing=True))
    if project is None or project.status != "active":
        raise AppError("project_archived", "Archived projects cannot serve staging retrieval", status_code=409)
    scope = list(session.execute(select(DocumentVersion.id, DocumentVersion.document_id, DocumentVersion.project_id)
        .where(DocumentVersion.id.in_(requested_ids))))
    if {row.id for row in scope} != requested_ids or any(row.project_id != project_id for row in scope):
        raise AppError("retrieval_scope_denied", "Retrieval scope must be document versions in this project", status_code=403)
    document_ids = {row.document_id for row in scope}
    documents = list(session.scalars(select(Document).where(Document.id.in_(document_ids))
        .order_by(Document.id).with_for_update(read=True, key_share=True).execution_options(populate_existing=True)))
    versions = list(session.scalars(select(DocumentVersion).where(DocumentVersion.id.in_(requested_ids))
        .order_by(DocumentVersion.id).with_for_update(read=True).execution_options(populate_existing=True)))
    if {version.id for version in versions} != requested_ids or any(version.project_id != project_id for version in versions):
        raise AppError("retrieval_scope_denied", "Retrieval scope must be document versions in this project", status_code=403)
    if {document.id for document in documents} != {version.document_id for version in versions} or any(document.project_id != project_id or document.is_deleted or document.status == "deleted" for document in documents):
        raise AppError("retrieval_scope_denied", "Retrieval scope must be non-deleted documents in this project", status_code=403)
    for version in versions:
        require_unexpired(session, version.id)
        require_ready_chunk_artifacts(session, version)
    return requested_ids


def _select_chat_model(session: Session, project: Project) -> AIModel:
    model = session.get(AIModel, project.llm_model_id) if project.llm_model_id else None
    if model is None or model.deleted_at is not None:
        model = session.scalar(select(AIModel).where(AIModel.model_type == "Chat", AIModel.is_active.is_(True), AIModel.is_default.is_(True), AIModel.deleted_at.is_(None)))
    if model is None or not model.is_active or model.deleted_at is not None:
        raise AppError("model_configuration_required", "An active Chat Model is required to generate an answer", status_code=409)
    if model.provider.lower() not in {"ollama", "vllm"} and not model.api_key_configured:
        raise AppError("model_configuration_required", "Chat Model credential is required to generate an answer", status_code=409)
    return model


def _generate_citation_bound_answer(session: Session, question: str, citations: list[ProjectChatCitation], model: AIModel | None):
    system_prompt = resolve_system_prompt(session, model=model, model_type="Chat") if model is not None else None
    return generate_rag_answer(question=question, citations=citations, model=model, system_prompt=system_prompt)


def _search_document_staging_chunks(session: Session, project_id: UUID, version_ids: set[UUID], question: str, top_k: int, *, source_channel: str = "chat_test", actor_user_id: UUID | None = None) -> list[ProjectChatCitation]:
    for version_id in version_ids:
        require_unexpired(session, version_id)
    return _search_hybrid_chunks(session, project_id, version_ids, question, top_k, scope="staging", source_channel=source_channel, actor_user_id=actor_user_id)


def _query_terms(question: str) -> list[str]:
    normalized = question.lower()
    latin_terms = re.findall(r"[a-z0-9][a-z0-9._-]*", normalized)
    cjk_terms = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
    seen: set[str] = set()
    terms: list[str] = []
    for term in latin_terms + cjk_terms:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


def _search_published_chunks(session: Session, project_id: UUID, version_ids: set[UUID], question: str, top_k: int, *, source_channel: str = "chat_test", actor_user_id: UUID | None = None) -> list[ProjectChatCitation]:
    return _search_hybrid_chunks(session, project_id, version_ids, question, top_k, scope="published", source_channel=source_channel, actor_user_id=actor_user_id)


def _search_hybrid_chunks(session: Session, project_id: UUID, version_ids: set[UUID], question: str, top_k: int, *, scope: str, source_channel: str, actor_user_id: UUID | None) -> list[ProjectChatCitation]:
    from app.core.config import get_settings

    versions = list(session.scalars(select(DocumentVersion).where(DocumentVersion.id.in_(version_ids))))
    if {version.id for version in versions} != version_ids or any(version.project_id != project_id for version in versions):
        raise AppError("retrieval_scope_inconsistent", "Retrieval versions are inconsistent with project scope", status_code=409)
    chunks_by_id = {chunk.id: chunk for chunk in session.scalars(select(Chunk).where(Chunk.project_id == project_id, Chunk.document_version_id.in_(version_ids), Chunk.status == "active"))}
    if not chunks_by_id:
        return []
    chunks_by_position = {
        (chunk.document_id, chunk.document_version_id, chunk.chunk_index): chunk
        for chunk in chunks_by_id.values()
    }
    settings = get_settings()
    if scope == "staging":
        _ensure_document_staging_indices(session, project_id, versions, chunks_by_id, settings)
    profile_versions: dict[UUID, list[DocumentVersion]] = {}
    for version in versions:
        if not version.embedding_profile_id:
            raise AppError("embedding_profile_required", "Embedding Profile is required before hybrid retrieval", status_code=409)
        profile_versions.setdefault(version.embedding_profile_id, []).append(version)
    citations: list[ProjectChatCitation] = []
    for profile_id, scoped_versions in profile_versions.items():
        profile = session.get(EmbeddingProfile, profile_id)
        if profile is None:
            raise AppError("embedding_profile_required", "Embedding Profile is required before hybrid retrieval", status_code=409)
        index_scopes = _hybrid_index_scopes(settings.opensearch_index_prefix, project_id, scoped_versions, scope)
        _model, query_vector = embed_query(session, profile=profile, question=question, settings=settings, project_id=project_id, actor_user_id=actor_user_id, source_channel=source_channel)
        for index_name, scoped_version_ids in index_scopes:
            hits = _opensearch_hybrid_search(
                index_name,
                project_id,
                question,
                query_vector,
                [str(item) for item in scoped_version_ids],
                top_k,
                scope=scope,
                mapping_version=profile.mapping_version,
            )
            remaining = top_k - len(citations)
            selected_hits = _select_prompt_chunks(
                hits,
                chunks_by_id=chunks_by_id,
                chunks_by_position=chunks_by_position,
                project_id=project_id,
                scoped_version_ids=scoped_version_ids,
                limit=remaining,
            )
            for hit, chunk in selected_hits:
                citations.append(
                    ProjectChatCitation(
                        document_id=chunk.document_id,
                        document_version_id=chunk.document_version_id,
                        chunk_id=chunk.id,
                        chunk_index=chunk.chunk_index,
                        title=chunk.title,
                        score=hit.get("_score"),
                        excerpt=_safe_excerpt(chunk.content),
                        content_type=chunk.content_type,
                        heading_path=list(chunk.heading_path or []),
                        page=chunk.page_start or _first_source_page(chunk.source_mapping),
                        source_mapping=chunk.source_mapping,
                        index_name=index_name,
                        display_markdown=chunk_display_markdown(chunk),
                        generation_text=chunk.content,
                        raw_markdown=chunk.markdown_content if (chunk.chunk_strategy or {}).get("source") == "structure_aware" else None,
                    )
                )
                if len(citations) >= top_k:
                    return citations
    return citations


def _ensure_document_staging_indices(session: Session, project_id: UUID, versions: list[DocumentVersion], chunks_by_id: dict[UUID, Chunk], settings) -> None:
    """A query never repairs an index or embeds document content as a side effect."""
    for version in versions:
        if version.project_id != project_id:
            raise AppError("retrieval_scope_denied", "Staging version scope is invalid", status_code=403)
        require_ready_chunk_artifacts(session, version)


def _hybrid_index_scopes(prefix: str, project_id: UUID, versions: list[DocumentVersion], scope: str) -> list[tuple[str, set[UUID]]]:
    if scope == "published":
        grouped: dict[str, set[UUID]] = {}
        for version in versions:
            if version.embedding_profile_id is None:
                raise AppError("embedding_profile_required", "Embedding Profile is required before hybrid retrieval", status_code=409)
            grouped.setdefault(published_index_name(prefix, version.embedding_profile_id), set()).add(version.id)
        return list(grouped.items())
    if scope == "staging":
        bound_scopes: list[tuple[str, set[UUID]]] = []
        for version in versions:
            if version.project_id != project_id:
                raise AppError("retrieval_scope_denied", "Staging version scope is invalid", status_code=403)
            uri = version.extraction_artifact_uri or ""
            base_name = staging_index_name(prefix, project_id, version.id)
            index_name = uri.removeprefix("opensearch://")
            if not uri.startswith("opensearch://") or not re.fullmatch(re.escape(base_name) + r"(?:-edit-[0-9a-f]{32})?", index_name):
                raise AppError("opensearch_index_not_ready", "OpenSearch retrieval index is not ready", status_code=409)
            bound_scopes.append((index_name, {version.id}))
        return bound_scopes
    raise AppError("retrieval_scope_invalid", "Retrieval scope is invalid", status_code=422)


def _opensearch_hybrid_search(
    index_name: str,
    project_id: UUID,
    question: str,
    query_vector: list[float],
    version_ids: list[str],
    top_k: int,
    *,
    scope: str,
    mapping_version: int = 1,
) -> list[dict]:  # pragma: no cover - covered by live acceptance
    candidate_limit = max(top_k * 2, 10)
    vector_data = _opensearch_search(index_name, _vector_query_body(project_id, query_vector, version_ids, candidate_limit, scope))
    keyword_data = _opensearch_search(
        index_name,
        _keyword_query_body(
            project_id,
            question,
            version_ids,
            candidate_limit,
            scope,
            mapping_version=mapping_version,
        ),
    )
    vector_hits = vector_data.get("hits", {}).get("hits", [])
    keyword_hits = keyword_data.get("hits", {}).get("hits", [])
    if not isinstance(vector_hits, list) or not isinstance(keyword_hits, list):
        raise AppError("hybrid_retrieval_failed", "OpenSearch hybrid retrieval returned invalid hits", status_code=502)
    return fuse_ranked_hits(vector_hits, keyword_hits)[:candidate_limit]


def _select_prompt_chunks(
    hits: list[dict],
    *,
    chunks_by_id: dict[UUID, Chunk],
    chunks_by_position: dict[tuple[UUID, UUID, int], Chunk],
    project_id: UUID,
    scoped_version_ids: set[UUID],
    limit: int,
) -> list[tuple[dict, Chunk]]:
    if limit <= 0:
        return []
    selected: list[tuple[dict, Chunk]] = []
    selected_ids: set[UUID] = set()
    for hit in hits:
        chunk = _authorized_hit_chunk(
            hit,
            chunks_by_id=chunks_by_id,
            project_id=project_id,
            scoped_version_ids=scoped_version_ids,
        )
        if chunk is None:
            continue
        promoted = (
            _content_bearing_successor(chunk, chunks_by_position)
            if is_structural_only(chunk.content)
            else None
        )
        prompt_chunk = promoted or chunk
        if prompt_chunk.id in selected_ids:
            continue
        selected.append((hit, prompt_chunk))
        selected_ids.add(prompt_chunk.id)
        if len(selected) >= limit:
            break
    return selected


def _authorized_hit_chunk(
    hit: dict,
    *,
    chunks_by_id: dict[UUID, Chunk],
    project_id: UUID,
    scoped_version_ids: set[UUID],
) -> Chunk | None:
    source = hit.get("_source", {})
    try:
        chunk_id = UUID(source["chunk_id"])
        version_id = UUID(source["document_version_id"])
        document_id = UUID(source["document_id"])
    except (KeyError, TypeError, ValueError):
        return None
    chunk = chunks_by_id.get(chunk_id)
    if (
        version_id not in scoped_version_ids
        or chunk is None
        or chunk.project_id != project_id
        or chunk.document_id != document_id
        or chunk.document_version_id != version_id
    ):
        return None
    return chunk


def _content_bearing_successor(
    chunk: Chunk,
    chunks_by_position: dict[tuple[UUID, UUID, int], Chunk],
) -> Chunk | None:
    for offset in (1, 2):
        successor = chunks_by_position.get(
            (chunk.document_id, chunk.document_version_id, chunk.chunk_index + offset)
        )
        if successor is None:
            return None
        if not _same_section_ancestry(chunk.section_path, successor.section_path):
            return None
        if is_markdown_heading_only(successor.content):
            return None
        if is_structural_only(successor.content):
            continue
        return successor
    return None


def _same_section_ancestry(left: str | list | tuple | None, right: str | list | tuple | None) -> bool:
    if not left or not right:
        return True
    left_path = (left.strip(),) if isinstance(left, str) else tuple(str(item) for item in left)
    right_path = (right.strip(),) if isinstance(right, str) else tuple(str(item) for item in right)
    common = min(len(left_path), len(right_path))
    return left_path[:common] == right_path[:common]


def _hit_id(hit: dict) -> str | None:
    value = hit.get("_id")
    return str(value) if value is not None else None


def _scope_filters(project_id: UUID, version_ids: list[str], scope: str) -> list[dict]:
    return [
        {"term": {"project_id": str(project_id)}},
        {"term": {"index_scope": scope}},
        {"terms": {"document_version_id": version_ids}},
    ]


def _keyword_query_body(
    project_id: UUID,
    question: str,
    version_ids: list[str],
    top_k: int,
    scope: str,
    *,
    mapping_version: int = 1,
) -> dict:
    # Mapping v2 stores the complete document/heading context in the normalized
    # retrieval representation. BM25 and vector search must therefore evaluate
    # the same body. Older active v1 indices remain readable through this
    # deliberately named, read-only compatibility field list.
    fields = ["retrieval_text"] if mapping_version >= 2 else _legacy_keyword_fields()
    return {
        "size": top_k,
        "query": {
            "bool": {
                "must": [{"multi_match": {"query": question, "fields": fields}}],
                "filter": _scope_filters(project_id, version_ids, scope),
            }
        },
    }


def _legacy_keyword_fields() -> list[str]:
    """Fields used only to read pre-v2 active indices during migration."""

    return [
        "retrieval_text^3",
        "document_title^2",
        "heading_path^2",
        "display_text",
        "title",
        "content",
        "markdown_content^0.25",
    ]


def _vector_query_body(project_id: UUID, query_vector: list[float], version_ids: list[str], top_k: int, scope: str) -> dict:
    return {
        "size": top_k,
        "query": {
            "bool": {
                "must": [{"knn": {"embedding_vector": {"vector": query_vector, "k": top_k}}}],
                "filter": _scope_filters(project_id, version_ids, scope),
            }
        },
    }


def _opensearch_search(index_name: str, body: dict) -> dict:  # pragma: no cover - covered by live acceptance
    from app.core.config import get_settings

    settings = get_settings()
    context = settings.opensearch_ssl_context
    request = urllib.request.Request(f"{settings.opensearch_url.rstrip('/')}/{index_name}/_search", data=json.dumps(body).encode("utf-8"), method="POST", headers={"content-type": "application/json"})
    username = settings.opensearch_username.get_secret_value()
    password = settings.opensearch_password.get_secret_value()
    if username or password:
        token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AppError("opensearch_index_not_ready", "OpenSearch retrieval index is not ready", status_code=409) from exc
        raise AppError("hybrid_retrieval_failed", "OpenSearch hybrid retrieval endpoint is unavailable", status_code=503) from exc
    except OSError as exc:
        raise AppError("hybrid_retrieval_failed", "OpenSearch hybrid retrieval endpoint is unavailable", status_code=503) from exc


def _safe_excerpt(content: str | None, *, limit: int = 280) -> str | None:
    if not content:
        return None
    normalized = " ".join(content.split())
    return normalized if len(normalized) <= limit else f"{normalized[:limit].rstrip()}…"


def _first_source_page(source_mapping: list | None) -> int | None:
    if not source_mapping:
        return None
    for item in source_mapping:
        if not isinstance(item, dict):
            continue
        raw_page = item.get("page") or item.get("page_no") or item.get("source_page")
        try:
            return int(raw_page)
        except (TypeError, ValueError):
            continue
    return None
