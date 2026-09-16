from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
from collections import deque
from datetime import UTC, datetime
from base64 import b64encode
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domain.project_access import get_scoped_project as _get_scoped_project
from app.domain.chat_conversations import conversation_identities, lock_conversation, require_conversation_identity, validate_visible_identity
from app.api.schemas import (
    NotificationCountResponse,
    NotificationPage,
    NotificationResponse,
    ProjectChatConversationDeleteResponse,
    ProjectChatConversationPage,
    ProjectChatCitation,
    ProjectChatConversationResponse,
    ProjectChatFeedbackPayload,
    ProjectChatQueryPayload,
    ProjectChatQueryResponse,
    ProjectChatRecordResponse,
    ProjectGraphEdge,
    ProjectGraphNode,
    ProjectGraphResponse,
    ProjectServingDocumentStatus,
    ProjectServingStatusResponse,
    ValidationRunCreatePayload,
    ValidationCancellationResponse,
    ValidationRunItemResponse,
    ValidationRunItemPage,
    ValidationRunPage,
    ValidationRunResponse,
)
from app.core.cursor import cursor_filter_hash, decode_cursor, encode_cursor
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import AIModel, ActiveVersionManifest, ChatFeedbackEvent, ChatRecord, Chunk, Document, DocumentVersion, EmbeddingBuild, EmbeddingProfile, GraphSyncJob, Notification, OutboxEvent, Project, ProjectOwner, ValidationRun, ValidationRunItem
from app.db.session import get_db
from app.domain.ai_provider import generate_rag_answer
from app.domain.chat_citations import chunk_display_markdown, citation_persistence_payload, compact_citation_view, hydrate_citation_groups, validate_citation_markers
from app.domain.chat_retrieval import fuse_ranked_hits, is_markdown_heading_only, is_structural_only
from app.domain.embeddings import embed_chunks, embed_query
from app.domain.model_usage import record_model_usage
from app.domain.chunk_artifacts import chunk_artifact_state, require_ready_chunk_artifacts
from app.domain.extraction_pipeline import LiveOpenSearchStagingIndexAdapter, staging_index_name
from app.domain.review_publish import published_index_name
from app.domain.system_prompts import resolve_system_prompt
from app.security.context import IdentityContext, get_identity_context
from app.services.audit import add_audit
from app.db.models import User


router = APIRouter(tags=["serving"])


@router.get("/projects/{project_id}/graph", response_model=ProjectGraphResponse)
def get_project_graph(project_id: UUID, node_limit: int = Query(default=120, ge=10, le=500), context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ProjectGraphResponse:
    project = _get_scoped_project(session, project_id, context)
    active_ids = _active_version_ids(session, project.id)
    if not active_ids:
        return ProjectGraphResponse(project_id=project.id, nodes=[], edges=[], node_limit=node_limit)

    graph = _project_graph_without_chunk_content(session, project, active_ids, node_limit)
    return _hydrate_graph_chunk_content(session, graph, project.id, active_ids)


@router.get("/projects/{project_id}/graph/neighbors", response_model=ProjectGraphResponse)
def get_project_graph_neighbors(project_id: UUID, node_id: str, node_limit: int = Query(default=80, ge=10, le=200), context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ProjectGraphResponse:
    project = _get_scoped_project(session, project_id, context)
    active_ids = _active_version_ids(session, project.id)
    if not active_ids:
        return ProjectGraphResponse(project_id=project.id, nodes=[], edges=[], node_limit=node_limit)
    graph = _project_graph_without_chunk_content(session, project, active_ids, min(500, max(node_limit * 4, node_limit)))
    neighbor_graph = _neighbor_graph(graph, node_id, node_limit)
    return _hydrate_graph_chunk_content(session, neighbor_graph, project.id, active_ids)


@router.get("/projects/{project_id}/graph/paths", response_model=ProjectGraphResponse)
def get_project_graph_paths(project_id: UUID, source_id: str, target_id: str, max_depth: int = Query(default=4, ge=1, le=8), node_limit: int = Query(default=120, ge=10, le=500), context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ProjectGraphResponse:
    project = _get_scoped_project(session, project_id, context)
    active_ids = _active_version_ids(session, project.id)
    if not active_ids:
        return ProjectGraphResponse(project_id=project.id, nodes=[], edges=[], node_limit=node_limit)
    graph = _project_graph_without_chunk_content(session, project, active_ids, node_limit)
    node_ids = {node.id for node in graph.nodes}
    if source_id not in node_ids or target_id not in node_ids:
        raise AppError("graph_node_not_found", "Graph node was not found in the authorized Project scope", status_code=404)
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.source, []).append((edge.target, edge.id))
        adjacency.setdefault(edge.target, []).append((edge.source, edge.id))
    queue = deque([(source_id, [source_id], [])])
    visited = {source_id}
    found_nodes: list[str] | None = None
    found_edges: list[str] | None = None
    while queue:
        current, path_nodes, path_edges = queue.popleft()
        if current == target_id:
            found_nodes, found_edges = path_nodes, path_edges
            break
        if len(path_edges) >= max_depth:
            continue
        for neighbor, edge_id in adjacency.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((neighbor, [*path_nodes, neighbor], [*path_edges, edge_id]))
    if found_nodes is None or found_edges is None:
        return ProjectGraphResponse(project_id=project_id, nodes=[], edges=[], truncated=graph.truncated, node_limit=node_limit)
    node_set, edge_set = set(found_nodes), set(found_edges)
    path_graph = ProjectGraphResponse(
        project_id=project_id,
        truncated=graph.truncated,
        nodes=[node for node in graph.nodes if node.id in node_set],
        edges=[edge for edge in graph.edges if edge.id in edge_set],
        node_limit=node_limit,
    )
    return _hydrate_graph_chunk_content(session, path_graph, project.id, active_ids)


@router.get(
    "/projects/{project_id}/documents/{document_id}/versions/{version_id}/graph",
    response_model=ProjectGraphResponse,
)
def get_document_version_graph(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    node_limit: int = Query(default=120, ge=10, le=500),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ProjectGraphResponse:
    project = _get_scoped_project(session, project_id, context)
    document = session.get(Document, document_id)
    version = session.get(DocumentVersion, version_id)
    if (
        document is None
        or document.project_id != project.id
        or document.is_deleted
        or version is None
        or version.project_id != project.id
        or version.document_id != document.id
    ):
        raise AppError("document_version_not_found", "Document version was not found in the authorized scope", status_code=404)
    version_ids = {version.id}
    graph = _project_graph_without_chunk_content(session, project, version_ids, node_limit, allow_preview=True)
    return _hydrate_graph_chunk_content(session, graph, project.id, version_ids)


@router.get("/projects/{project_id}/serving-status", response_model=ProjectServingStatusResponse)
def get_project_serving_status(project_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ProjectServingStatusResponse:
    project = _get_scoped_project(session, project_id, context)
    manifests = list(session.scalars(_active_retrieval_manifest_query(project.id).order_by(ActiveVersionManifest.created_at.desc())))
    documents: list[ProjectServingDocumentStatus] = []
    for manifest in manifests:
        document = session.get(Document, manifest.document_id)
        version = session.get(DocumentVersion, manifest.document_version_id)
        if document is None or version is None or document.project_id != project.id or version.project_id != project.id:
            continue
        graph_job = session.scalar(
            select(GraphSyncJob)
            .where(GraphSyncJob.project_id == project.id, GraphSyncJob.document_version_id == manifest.document_version_id)
            .order_by(GraphSyncJob.created_at.desc())
            .limit(1)
        )
        chunk_count = _serving_manifest_chunk_count(session, manifest)
        # A completed historical job is not proof that the current graph still
        # matches the canonical source. Verify without mutating or querying LLMs.
        from app.domain.graph_projection import build_graph_projection
        from app.domain.graph_reconciliation import Neo4jProjectionStore
        actual = None
        try:
            projection = build_graph_projection(session, project, document, version)
            actual = Neo4jProjectionStore(get_settings()).read(projection)
            graph_verified = actual.matches(projection)
        except AppError:
            graph_verified = False
        documents.append(
            ProjectServingDocumentStatus(
                document_id=document.id,
                document_title=document.title,
                document_version_id=version.id,
                version_label=version.version_label,
                publication_generation=manifest.publication_generation,
                chunk_count=chunk_count,
                index_ready=manifest.index_ready,
                graph_sync_status="completed" if graph_verified else (graph_job.status if graph_job and graph_job.status in {"queued", "running", "failed", "cancelled"} else "failed"),
                graph_node_count=len(actual.graph["nodes"]) if actual else None,
                graph_edge_count=len(actual.graph["edges"]) if actual else None,
            )
        )
    ready_index_count = sum(1 for item in documents if item.index_ready)
    graph_ready_count = sum(1 for item in documents if item.graph_sync_status == "completed")
    readiness = "empty" if not documents else "ready" if ready_index_count == len(documents) and graph_ready_count == len(documents) else "partial"
    return ProjectServingStatusResponse(project_id=project.id, readiness=readiness, active_document_count=len(documents), ready_index_count=ready_index_count, graph_ready_count=graph_ready_count, documents=documents)


def _serving_manifest_chunk_count(session: Session, manifest: ActiveVersionManifest) -> int:
    build = session.get(EmbeddingBuild, manifest.embedding_build_id)
    if build is not None and build.document_version_id == manifest.document_version_id:
        return int(build.chunk_count or 0)
    return int(
        session.scalar(
            select(func.count(Chunk.id)).where(
                Chunk.project_id == manifest.project_id,
                Chunk.document_id == manifest.document_id,
                Chunk.document_version_id == manifest.document_version_id,
                Chunk.status == "active",
            )
        )
        or 0
    )


@router.post("/projects/{project_id}/chat/query", response_model=ProjectChatQueryResponse)
def query_project_chat(project_id: UUID, payload: ProjectChatQueryPayload, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ProjectChatQueryResponse:
    project = _get_scoped_project(session, project_id, context)
    conversation_id = payload.conversation_id or uuid4()
    if payload.scope_mode == "document_staging" and len(set(payload.document_version_ids or [])) != 1:
        raise AppError("document_version_scope_required", "Document chat requires exactly one document version", status_code=422)
    # Identity denial precedes even retrieval readiness resolution. An unavailable
    # index must not disguise a foreign conversation ID as a new conversation.
    require_conversation_identity(session, project_id=project.id, conversation_id=conversation_id,
        user_id=context.user_id, scope_mode=payload.scope_mode,
        requested_ids=set(payload.document_version_ids) if payload.document_version_ids else None)
    if payload.scope_mode == "document_staging":
        manifest_ids: set[UUID] = set()
        requested_ids = _resolve_document_staging_scope(session, project.id, payload.document_version_ids)
    else:
        _manifests, manifest_ids, requested_ids = _resolve_retrieval_scope(session, project.id, payload.document_version_ids)
    _ensure_conversation_can_continue(session, project.id, conversation_id, requested_ids, context.user_id, payload.scope_mode)
    started = perf_counter()
    asked_at = datetime.now(UTC)
    citations = (
        _search_document_staging_chunks(session, project.id, requested_ids, payload.question, payload.top_k, source_channel="chat_test", actor_user_id=context.user_id)
        if payload.scope_mode == "document_staging"
        else _search_published_chunks(session, project.id, requested_ids, payload.question, payload.top_k, source_channel="chat_test", actor_user_id=context.user_id)
    )
    status = "answered" if citations else "no_answer"
    chat_model = _select_chat_model(session, project) if citations else None
    provider_started = perf_counter()
    provider_result = None
    try:
        provider_result = _generate_citation_bound_answer(session, payload.question, citations, chat_model)
        validate_citation_markers(provider_result.answer, len(citations))
    except AppError as exc:
        if chat_model is not None:
            record_model_usage(
                session,
                model=chat_model,
                usage_purpose="chat_test",
                source_channel="chat_test",
                status="failed",
                token_usage=provider_result.token_usage if provider_result is not None else None,
                error_code=exc.code,
                latency_ms=max(0, int((perf_counter() - provider_started) * 1000)),
                project_id=project.id,
                document_version_id=next(iter(requested_ids)) if len(requested_ids) == 1 else None,
                actor_user_id=context.user_id,
                metadata={"scope_mode": payload.scope_mode},
            )
            session.commit()
        raise
    answer, prompt_version, token_usage = provider_result.answer, provider_result.prompt_version, provider_result.token_usage
    answered_at = datetime.now(UTC)
    latency_ms = max(0, int((perf_counter() - started) * 1000))
    title = payload.conversation_title or _conversation_title(payload.question)
    record = ChatRecord(
        id=uuid4(),
        project_id=project.id,
        document_version_id=next(iter(requested_ids)) if len(requested_ids) == 1 else None,
        scope_mode=payload.scope_mode,
        conversation_id=conversation_id,
        conversation_title=title,
        selected_document_version_ids=[str(item) for item in sorted(requested_ids, key=str)],
        question=payload.question,
        answer=answer,
        reference_docs=[citation_persistence_payload(citation) for citation in citations],
        evaluation="not_evaluated",
        llm_model_id=chat_model.id if chat_model else None,
        embedding_model_id=None,
        prompt_version=prompt_version,
        system_prompt_source=provider_result.system_prompt_source,
        system_prompt_version_id=provider_result.system_prompt_version_id,
        system_prompt_content_hash=provider_result.system_prompt_content_hash,
        system_prompt_layers=provider_result.system_prompt_layers,
        token_usage=token_usage,
        latency_ms=latency_ms,
        created_by=context.user_id,
        asked_at=asked_at,
        answered_at=answered_at,
        created_at=asked_at,
    )
    session.add(record)
    session.flush([record])
    if chat_model is not None:
        record_model_usage(
            session,
            model=chat_model,
            usage_purpose="chat_test",
            source_channel="chat_test",
            status="success",
            token_usage=token_usage,
            latency_ms=max(0, int((perf_counter() - provider_started) * 1000)),
            project_id=project.id,
            document_version_id=record.document_version_id,
            chat_record_id=record.id,
            actor_user_id=context.user_id,
            metadata={"scope_mode": payload.scope_mode},
        )
    session.commit()
    session.refresh(record)
    compact = compact_citation_view(answer, citations)
    return ProjectChatQueryResponse(chat_record_id=record.id, conversation_id=conversation_id, conversation_title=title, answer=compact.answer or "", citations=compact.citations, manifest_version_ids=sorted(manifest_ids, key=str), selected_version_ids=sorted(requested_ids, key=str), status=status, retrieval_strategy="hybrid", prompt_version=prompt_version, system_prompt_source=provider_result.system_prompt_source, system_prompt_version_id=provider_result.system_prompt_version_id, system_prompt_content_hash=provider_result.system_prompt_content_hash, system_prompt_layers=provider_result.system_prompt_layers, llm_model_id=chat_model.id if chat_model else None, token_usage=token_usage, latency_ms=latency_ms)


@router.get("/projects/{project_id}/chat/conversations", response_model=ProjectChatConversationPage)
def list_project_chat_conversations(
    project_id: UUID,
    request: Request,
    scope_mode: Literal["published", "document_staging"] = Query(...),
    document_version_id: UUID | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ProjectChatConversationPage:
    project = _get_scoped_project(session, project_id, context)
    if scope_mode == "document_staging":
        if document_version_id is None:
            raise AppError("document_version_scope_required", "Document chat history requires a document version id", status_code=422)
        _authorize_document_staging_identity(session, project.id, document_version_id)
    elif document_version_id is not None:
        raise AppError("conversation_scope_invalid", "Published conversation history does not accept a document staging version", status_code=422)
    filters = [
        ChatRecord.project_id == project.id,
        ChatRecord.scope_mode == scope_mode,
        ChatRecord.deleted_at.is_(None),
    ]
    if scope_mode == "document_staging":
        filters.append(ChatRecord.document_version_id == document_version_id)
    filter_hash = cursor_filter_hash(
        {
            "project_id": project.id,
            "user_id": context.user_id,
            "scope_mode": scope_mode,
            "document_version_id": document_version_id,
        }
    )
    latest = (
        select(
            ChatRecord.conversation_id.label("conversation_id"),
            func.max(ChatRecord.created_at).label("updated_at"),
        )
        .where(*filters)
        .group_by(ChatRecord.conversation_id)
        .subquery()
    )
    page_query = select(latest.c.conversation_id, latest.c.updated_at)
    if cursor:
        cursor_payload = decode_cursor(request.app.state.settings, namespace="chat-conversations", value=cursor)
        if cursor_payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current conversation scope", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(cursor_payload["updated_at"]))
            cursor_id = UUID(str(cursor_payload["conversation_id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        page_query = page_query.where(
            or_(
                latest.c.updated_at < cursor_time,
                (latest.c.updated_at == cursor_time) & (latest.c.conversation_id < cursor_id),
            )
        )
    identities = list(
        session.execute(
            page_query.order_by(latest.c.updated_at.desc(), latest.c.conversation_id.desc()).limit(limit + 1)
        )
    )
    has_more = len(identities) > limit
    identities = identities[:limit]
    conversation_ids = [row.conversation_id for row in identities]
    records = (
        list(
            session.scalars(
                select(ChatRecord)
                .where(*filters, ChatRecord.conversation_id.in_(conversation_ids))
                .order_by(ChatRecord.asked_at, ChatRecord.id)
            )
        )
        if conversation_ids
        else []
    )
    summaries = {item.id: item for item in _conversation_summaries(session, project.id, records, user_id=context.user_id, include_records=True)}
    items = [summaries[conversation_id] for conversation_id in conversation_ids if conversation_id in summaries]
    next_cursor = None
    if has_more and identities:
        last = identities[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="chat-conversations",
            payload={
                "filter": filter_hash,
                "updated_at": last.updated_at.isoformat(),
                "conversation_id": str(last.conversation_id),
            },
        )
    return ProjectChatConversationPage(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get("/projects/{project_id}/chat/conversations/{conversation_id}", response_model=ProjectChatConversationResponse)
def get_project_chat_conversation(
    project_id: UUID,
    conversation_id: UUID,
    scope_mode: Literal["published", "document_staging"] = Query(...),
    document_version_id: UUID | None = Query(default=None),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ProjectChatConversationResponse:
    project = _get_scoped_project(session, project_id, context)
    records = _authorized_conversation_records(
        session,
        project_id=project.id,
        conversation_id=conversation_id,
        user_id=context.user_id,
        scope_mode=scope_mode,
        document_version_id=document_version_id,
        shared_read=True,
    )
    if not records:
        raise AppError("conversation_not_found", "Conversation was not found", status_code=404)
    summaries = _conversation_summaries(session, project.id, records, user_id=context.user_id, include_records=True)
    if not summaries:
        # A concurrent delete/identity conflict may invalidate the earlier read.
        raise AppError("conversation_not_found", "Conversation was not found", status_code=404)
    return summaries[0]


@router.get("/projects/{project_id}/chat/conversations/{conversation_id}/export.csv", response_model=None)
def export_project_chat_conversation(
    project_id: UUID,
    conversation_id: UUID,
    scope_mode: Literal["published", "document_staging"] = Query(...),
    document_version_id: UUID | None = Query(default=None),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    project = _get_scoped_project(session, project_id, context)
    records = _authorized_conversation_records(
        session,
        project_id=project.id,
        conversation_id=conversation_id,
        user_id=context.user_id,
        scope_mode=scope_mode,
        document_version_id=document_version_id,
    )
    if not records:
        raise AppError("conversation_not_found", "Conversation was not found", status_code=404)
    columns = [
        "conversation_id",
        "conversation_title",
        "scope_mode",
        "project_id",
        "document_version_id",
        "selected_document_version_ids",
        "record_id",
        "question",
        "answer",
        "asked_at",
        "answered_at",
        "citations",
        "evaluation",
        "revision_suggestion",
    ]
    hydrated_groups = hydrate_citation_groups(
        session,
        [row.reference_docs for row in records],
        project_id=project.id,
        allowed_version_ids=_record_version_ids(records),
    )
    compact_by_record_id = {
        row.id: compact_citation_view(row.answer, citations)
        for row, citations in zip(records, hydrated_groups, strict=True)
    }

    def stream_rows():
        yield "\ufeff" + _csv_row(columns)
        for row in records:
            compact = compact_by_record_id[row.id]
            yield _csv_row(
                [
                    row.conversation_id,
                    row.conversation_title,
                    row.scope_mode,
                    row.project_id,
                    row.document_version_id,
                    json.dumps(row.selected_document_version_ids or [], ensure_ascii=False),
                    row.id,
                    row.question,
                    compact.answer,
                    row.asked_at.isoformat(),
                    row.answered_at.isoformat() if row.answered_at else None,
                    json.dumps(compact.citations, ensure_ascii=False),
                    row.evaluation,
                    row.revision_suggestion,
                ]
            )

    return StreamingResponse(
        stream_rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="nomosmart-conversation-{conversation_id}.csv"'},
    )


@router.delete("/projects/{project_id}/chat/conversations/{conversation_id}", response_model=ProjectChatConversationDeleteResponse)
def delete_project_chat_conversation(
    project_id: UUID,
    conversation_id: UUID,
    request: Request,
    scope_mode: Literal["published", "document_staging"] = Query(...),
    document_version_id: UUID | None = Query(default=None),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ProjectChatConversationDeleteResponse:
    project = _get_scoped_project(session, project_id, context)
    records = _authorized_conversation_records(
        session,
        project_id=project.id,
        conversation_id=conversation_id,
        user_id=context.user_id,
        scope_mode=scope_mode,
        document_version_id=document_version_id,
    )
    if not records:
        raise AppError("conversation_not_found", "Conversation was not found", status_code=404)
    deleted_at = datetime.now(UTC)
    for record in records:
        record.deleted_at = deleted_at
        record.deleted_by = context.user_id
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="project_chat.conversation.delete",
        resource_type="project_chat_conversation",
        resource_id=conversation_id,
        result="success",
        request_id=request.state.request_id,
        summary={
            "project_id": str(project.id),
            "scope_mode": scope_mode,
            "document_version_id": str(document_version_id) if document_version_id else None,
            "deleted_count": len(records),
        },
    )
    session.commit()
    return ProjectChatConversationDeleteResponse(conversation_id=conversation_id, deleted_count=len(records), deleted_at=deleted_at)


@router.post("/projects/{project_id}/chat/records/{record_id}/feedback", response_model=ProjectChatRecordResponse)
def update_project_chat_feedback(project_id: UUID, record_id: UUID, payload: ProjectChatFeedbackPayload, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ProjectChatRecordResponse:
    project = _get_scoped_project(session, project_id, context)
    record = session.get(ChatRecord, record_id)
    if record is None or record.project_id != project.id or record.created_by != context.user_id:
        raise AppError("chat_record_not_found", "Chat record was not found", status_code=404)
    if record.deleted_at is not None:
        raise AppError("chat_record_not_found", "Chat record was not found", status_code=404)
    _authorized_conversation_records(session, project_id=project.id, conversation_id=record.conversation_id,
        user_id=context.user_id, scope_mode=record.scope_mode,
        document_version_id=record.document_version_id if record.scope_mode == "document_staging" else None)
    if payload.evaluation == "needs_revision" and not (payload.revision_suggestion or "").strip():
        raise AppError("revision_suggestion_required", "Revision suggestion is required", status_code=422)
    record.evaluation = payload.evaluation
    record.revision_suggestion = payload.revision_suggestion.strip() if payload.revision_suggestion else None
    session.add(
        ChatFeedbackEvent(
            id=uuid4(),
            project_id=project.id,
            chat_record_id=record.id,
            source="ui",
            feedback_value=payload.evaluation,
            comment=record.revision_suggestion,
            actor_user_id=context.user_id,
            created_at=datetime.now(UTC),
        )
    )
    session.commit()
    session.refresh(record)
    allowed_version_ids = _record_version_ids([record])
    hydrated = hydrate_citation_groups(
        session,
        [record.reference_docs],
        project_id=project.id,
        allowed_version_ids=allowed_version_ids,
    )[0]
    return _chat_record_response(record, citations=hydrated)


@router.post("/projects/{project_id}/chat/validation-runs", response_model=ValidationRunResponse, status_code=201)
def create_project_chat_validation_run(project_id: UUID, payload: ValidationRunCreatePayload, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ValidationRunResponse:
    project = _get_scoped_project(session, project_id, context)
    if payload.scope_mode == "document_staging":
        selected_ids = _resolve_document_staging_scope(session, project.id, payload.selected_document_version_ids)
        if len(selected_ids) != 1:
            raise AppError(
                "document_version_scope_required",
                "Document validation requires exactly one document version",
                status_code=422,
            )
    else:
        _manifests, _manifest_ids, selected_ids = _resolve_retrieval_scope(session, project.id, payload.selected_document_version_ids)
    now = datetime.now(UTC)
    run_scope = "document_staging" if payload.scope_mode == "document_staging" else "project_chat"
    input_item_ids = [item.input_item_id or uuid4() for item in payload.questions]
    if len(set(input_item_ids)) != len(input_item_ids):
        raise AppError(
            "validation_input_item_duplicate",
            "Validation input_item_id values must be unique within a run",
            status_code=422,
        )
    max_attempts = get_settings().validation_max_attempts
    execution_manifest = _validation_execution_manifest(
        session,
        project=project,
        scope_mode=payload.scope_mode,
        selected_ids=selected_ids,
        max_attempts=max_attempts,
    )
    execution_manifest_hash = _canonical_json_hash(execution_manifest)
    run = ValidationRun(
        id=uuid4(),
        project_id=project.id,
        project_generation=project.work_generation,
        uploaded_file_name=payload.uploaded_file_name,
        status="queued",
        run_scope=run_scope,
        document_version_id=next(iter(selected_ids))
        if payload.scope_mode == "document_staging" and len(selected_ids) == 1
        else None,
        selected_document_ids=[str(item) for item in sorted(selected_ids, key=str)],
        execution_manifest=execution_manifest,
        execution_manifest_hash=execution_manifest_hash,
        max_attempts=max_attempts,
        total_count=len(payload.questions),
        completed_count=0,
        failed_count=0,
        created_by=context.user_id,
        created_at=now,
    )
    session.add(run)
    session.flush()
    for ordinal, (item, input_item_id) in enumerate(
        zip(payload.questions, input_item_ids, strict=True),
        start=1,
    ):
        row_scope = set(item.selected_document_ids or selected_ids)
        if not row_scope.issubset(selected_ids):
            raise AppError("validation_scope_denied", "CSV row selected documents must be within the fixed conversation scope", status_code=403)
        input_payload = {
            "question": item.question,
            "expected_answer": item.expected_answer,
            "expected_keywords": item.expected_keywords,
            "selected_document_ids": [
                str(value) for value in sorted(row_scope, key=str)
            ],
            "category": item.category,
            "priority": item.priority,
        }
        session.add(
            ValidationRunItem(
                id=uuid4(),
                run_id=run.id,
                input_item_id=input_item_id,
                input_ordinal=ordinal,
                input_content_hash=_canonical_json_hash(input_payload),
                question=item.question,
                expected_answer=item.expected_answer,
                expected_keywords=item.expected_keywords,
                selected_document_ids=input_payload["selected_document_ids"],
                category=item.category,
                priority=item.priority,
                status="pending",
                created_at=now,
            )
        )
    session.add(
        OutboxEvent(
            topic="validation.run.requested",
            aggregate_type="validation_run",
            aggregate_id=run.id,
            project_id=project.id,
            project_generation=project.work_generation,
            payload={
                "run_id": str(run.id),
                "project_id": str(project.id),
                "project_generation": project.work_generation,
                "execution_manifest_hash": execution_manifest_hash,
            },
            status="pending",
            attempts=0,
            available_at=now,
            created_at=now,
        )
    )
    session.commit()
    session.refresh(run)
    return _validation_run_response(session, run)


@router.get("/projects/{project_id}/chat/validation-runs", response_model=ValidationRunPage)
def list_project_chat_validation_runs(
    project_id: UUID,
    request: Request,
    scope_mode: Literal["published", "document_staging"] = Query(...),
    document_version_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None, max_length=32),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ValidationRunPage:
    project = _get_scoped_project(session, project_id, context)
    run_scope = "document_staging" if scope_mode == "document_staging" else "project_chat"
    if scope_mode == "document_staging":
        if document_version_id is None:
            raise AppError("document_version_scope_required", "Document validation history requires a document version id", status_code=422)
        _authorize_document_staging_identity(session, project.id, document_version_id)
    elif document_version_id is not None:
        raise AppError("validation_scope_invalid", "Published validation history does not accept a document staging version", status_code=422)
    filters = [
        ValidationRun.project_id == project.id,
        ValidationRun.created_by == context.user_id,
        ValidationRun.run_scope == run_scope,
    ]
    if document_version_id is not None:
        filters.append(ValidationRun.document_version_id == document_version_id)
    if status:
        filters.append(ValidationRun.status == status)
    filter_hash = cursor_filter_hash(
        {
            "project_id": project.id,
            "user_id": context.user_id,
            "run_scope": run_scope,
            "document_version_id": document_version_id,
            "status": status,
        }
    )
    statement = select(ValidationRun).where(*filters)
    if cursor:
        cursor_payload = decode_cursor(request.app.state.settings, namespace="validation-runs", value=cursor)
        if cursor_payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current validation scope", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(cursor_payload["created_at"]))
            cursor_id = UUID(str(cursor_payload["run_id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                ValidationRun.created_at < cursor_time,
                (ValidationRun.created_at == cursor_time) & (ValidationRun.id < cursor_id),
            )
        )
    runs = list(session.scalars(statement.order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc()).limit(limit + 1)))
    has_more = len(runs) > limit
    runs = runs[:limit]
    next_cursor = None
    if has_more and runs:
        last = runs[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="validation-runs",
            payload={"filter": filter_hash, "created_at": last.created_at.isoformat(), "run_id": str(last.id)},
        )
    return ValidationRunPage(items=[_validation_run_response(session, run) for run in runs], next_cursor=next_cursor, has_more=has_more)


@router.get("/projects/{project_id}/chat/validation-runs/{run_id}", response_model=ValidationRunResponse)
def get_project_chat_validation_run(project_id: UUID, run_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ValidationRunResponse:
    project = _get_scoped_project(session, project_id, context)
    run = session.get(ValidationRun, run_id)
    if run is None or run.project_id != project.id:
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    if run.created_by != context.user_id and session.get(ProjectOwner, (project.id, context.user_id)) is None:
        raise AppError("validation_run_forbidden", "Validation run belongs to another user", status_code=403)
    return _validation_run_response(session, run)


@router.get("/projects/{project_id}/chat/validation-runs/{run_id}/export.csv", response_model=None)
def export_project_chat_validation_run(
    project_id: UUID,
    run_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    project = _get_scoped_project(session, project_id, context)
    run = session.get(ValidationRun, run_id)
    if run is None or run.project_id != project.id:
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    if run.created_by != context.user_id and session.get(ProjectOwner, (project.id, context.user_id)) is None:
        raise AppError("validation_run_forbidden", "Validation run belongs to another user", status_code=403)
    items = list(
        session.scalars(
            select(ValidationRunItem)
            .where(ValidationRunItem.run_id == run.id)
            .order_by(
                ValidationRunItem.input_ordinal,
                ValidationRunItem.attempt,
                ValidationRunItem.id,
            )
        )
    )
    columns = [
        "run_id",
        "run_scope",
        "document_version_id",
        "run_status",
        "execution_manifest_hash",
        "item_id",
        "parent_item_id",
        "attempt",
        "is_current",
        "input_item_id",
        "input_ordinal",
        "input_content_hash",
        "question",
        "expected_answer",
        "expected_keywords",
        "selected_document_ids",
        "category",
        "priority",
        "answer",
        "citations",
        "chat_record_id",
        "item_status",
        "score",
        "evaluation_reason",
        "error_message",
        "error_code",
        "latency_ms",
        "token_usage",
    ]
    allowed_version_ids = _citation_version_ids([item.reference_docs for item in items])
    if run.document_version_id is not None:
        allowed_version_ids.add(run.document_version_id)
    hydrated_groups = hydrate_citation_groups(
        session,
        [item.reference_docs for item in items],
        project_id=run.project_id,
        allowed_version_ids=allowed_version_ids,
    )
    compact_by_item_id = {
        item.id: compact_citation_view(item.answer, citations)
        for item, citations in zip(items, hydrated_groups, strict=True)
    }

    def stream_rows():
        yield "\ufeff" + _csv_row(columns)
        for item in items:
            compact = compact_by_item_id[item.id]
            yield _csv_row(
                [
                    run.id,
                    run.run_scope,
                    run.document_version_id,
                    run.status,
                    run.execution_manifest_hash,
                    item.id,
                    item.parent_item_id,
                    item.attempt,
                    item.is_current,
                    item.input_item_id,
                    item.input_ordinal,
                    item.input_content_hash,
                    item.question,
                    item.expected_answer,
                    json.dumps(item.expected_keywords or [], ensure_ascii=False),
                    json.dumps(item.selected_document_ids or [], ensure_ascii=False),
                    item.category,
                    item.priority,
                    compact.answer,
                    json.dumps(compact.citations, ensure_ascii=False),
                    item.chat_record_id,
                    item.status,
                    item.score,
                    item.evaluation_reason,
                    item.error_message,
                    item.error_code,
                    item.latency_ms,
                    json.dumps(item.token_usage or {}, ensure_ascii=False),
                ]
            )

    return StreamingResponse(
        stream_rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="nomosmart-validation-{run.id}.csv"'},
    )


@router.post("/projects/{project_id}/chat/validation-runs/{run_id}/cancel", response_model=ValidationCancellationResponse)
def cancel_project_chat_validation_run(
    project_id: UUID,
    run_id: UUID,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ValidationCancellationResponse:
    project = _get_scoped_project(session, project_id, context)
    run = session.scalar(select(ValidationRun).where(ValidationRun.id == run_id).with_for_update())
    if run is None or run.project_id != project.id:
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    is_owner = session.get(ProjectOwner, (project.id, context.user_id)) is not None
    if run.created_by != context.user_id and not is_owner:
        raise AppError("validation_cancel_forbidden", "Only the creator or Project Owner may cancel this run", status_code=403)
    if run.status not in {"queued", "running"}:
        raise AppError("validation_run_not_cancellable", "Validation run is no longer cancellable", status_code=409)
    now = datetime.now(UTC)
    items = list(
        session.scalars(
            select(ValidationRunItem)
            .where(ValidationRunItem.run_id == run.id, ValidationRunItem.status.in_(("pending", "running")))
            .with_for_update()
        )
    )
    for item in items:
        item.status = "cancelled"
        item.error_message = None
    run.status = "cancelled"
    run.completed_at = now
    for event in session.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.aggregate_type == "validation_run",
            OutboxEvent.aggregate_id == run.id,
            OutboxEvent.status.in_(("pending", "dispatching")),
        )
        .with_for_update()
    ):
        event.status = "cancelled"
        event.processed_at = now
        event.claim_token = None
        event.claimed_at = None
        event.lease_expires_at = None
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="validation_run.cancel",
        resource_type="validation_run",
        resource_id=run.id,
        result="success",
        request_id=request.state.request_id,
        summary={"cancelled_item_count": len(items)},
    )
    session.commit()
    return ValidationCancellationResponse(
        validation_run_id=run.id,
        status=run.status,
        cancelled_item_count=len(items),
        completed_at=now,
    )


@router.post("/projects/{project_id}/chat/validation-runs/{run_id}/retry-failed", response_model=ValidationRunResponse)
def retry_failed_project_chat_validation_items(project_id: UUID, run_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ValidationRunResponse:
    project = _get_scoped_project(session, project_id, context)
    run = session.get(ValidationRun, run_id)
    if run is None or run.project_id != project.id:
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    if run.created_by != context.user_id:
        raise AppError("validation_run_forbidden", "Validation run belongs to another user", status_code=403)
    failed_items = list(session.scalars(select(ValidationRunItem).where(ValidationRunItem.run_id == run.id, ValidationRunItem.is_current.is_(True), ValidationRunItem.status.in_(("failed", "error"))).order_by(ValidationRunItem.input_ordinal, ValidationRunItem.id)))
    if not failed_items:
        raise AppError("validation_retry_not_available", "Validation run has no failed items to retry", status_code=409)
    retryable_items = [item for item in failed_items if item.attempt < run.max_attempts]
    if not retryable_items:
        raise AppError(
            "validation_retry_limit_reached",
            "Validation run items have reached the configured maximum attempts",
            status_code=409,
        )
    now = datetime.now(UTC)
    for item in retryable_items:
        item.is_current = False
        session.add(
            ValidationRunItem(
                id=uuid4(),
                run_id=run.id,
                parent_item_id=item.parent_item_id or item.id,
                attempt=item.attempt + 1,
                is_current=True,
                input_item_id=item.input_item_id,
                input_ordinal=item.input_ordinal,
                input_content_hash=item.input_content_hash,
                question=item.question,
                expected_answer=item.expected_answer,
                expected_keywords=item.expected_keywords,
                selected_document_ids=item.selected_document_ids,
                category=item.category,
                priority=item.priority,
                reference_docs=[],
                status="pending",
                created_at=now,
            )
        )
    completed_count = session.scalar(select(func.count()).select_from(ValidationRunItem).where(ValidationRunItem.run_id == run.id, ValidationRunItem.is_current.is_(True), ValidationRunItem.status.in_(("passed", "needs_review", "completed", "skipped")))) or 0
    run.status = "queued"
    run.completed_count = int(completed_count)
    run.failed_count = len(failed_items) - len(retryable_items)
    run.completed_at = None
    session.add(OutboxEvent(topic="validation.run.requested", aggregate_type="validation_run", aggregate_id=run.id, project_id=project.id, project_generation=project.work_generation, payload={"run_id": str(run.id), "project_id": str(project.id), "project_generation": project.work_generation, "retry": "failed", "execution_manifest_hash": run.execution_manifest_hash}, status="pending", attempts=0, available_at=now, created_at=now))
    session.commit()
    session.refresh(run)
    return _validation_run_response(session, run)


@router.get("/validation-runs", response_model=ValidationRunPage)
def list_validation_runs(
    request: Request,
    project_id: UUID | None = None,
    scope_mode: Literal["published", "document_staging"] | None = None,
    document_version_id: UUID | None = None,
    status: str | None = Query(default=None, max_length=32),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ValidationRunPage:
    owner_project_ids = select(ProjectOwner.project_id).where(ProjectOwner.user_id == context.user_id)
    filters = [
        ValidationRun.project_id.in_(context.visible_project_ids),
        or_(ValidationRun.created_by == context.user_id, ValidationRun.project_id.in_(owner_project_ids)),
    ]
    if project_id is not None:
        if project_id not in context.visible_project_ids:
            raise AppError("project_scope_denied", "Project is outside the authorized scope", status_code=403)
        filters.append(ValidationRun.project_id == project_id)
    if scope_mode:
        filters.append(ValidationRun.run_scope == ("document_staging" if scope_mode == "document_staging" else "project_chat"))
    if document_version_id:
        filters.append(ValidationRun.document_version_id == document_version_id)
    if status:
        filters.append(ValidationRun.status == status)
    filter_hash = cursor_filter_hash(
        {
            "actor": context.user_id,
            "project_id": project_id,
            "scope_mode": scope_mode,
            "document_version_id": document_version_id,
            "status": status,
        }
    )
    statement = select(ValidationRun).where(*filters)
    if cursor:
        payload = decode_cursor(request.app.state.settings, namespace="validation-run-inventory", value=cursor)
        if payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current validation filters", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(payload["created_at"]))
            cursor_id = UUID(str(payload["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                ValidationRun.created_at < cursor_time,
                (ValidationRun.created_at == cursor_time) & (ValidationRun.id < cursor_id),
            )
        )
    rows = list(session.scalars(statement.order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="validation-run-inventory",
            payload={"filter": filter_hash, "created_at": last.created_at.isoformat(), "id": str(last.id)},
        )
    return ValidationRunPage(items=[_validation_run_metadata(run) for run in rows], next_cursor=next_cursor, has_more=has_more)


@router.get("/validation-runs/{run_id}/items", response_model=ValidationRunItemPage)
def list_validation_run_items(
    run_id: UUID,
    request: Request,
    status: str | None = Query(default=None, max_length=32),
    category: str | None = Query(default=None, max_length=100),
    priority: str | None = Query(default=None, max_length=32),
    current_only: bool = Query(default=False),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ValidationRunItemPage:
    run = _authorized_validation_run(session, run_id, context)
    filters = [ValidationRunItem.run_id == run.id]
    if status:
        filters.append(ValidationRunItem.status == status)
    if category:
        filters.append(ValidationRunItem.category == category)
    if priority:
        filters.append(ValidationRunItem.priority == priority)
    if current_only:
        filters.append(ValidationRunItem.is_current.is_(True))
    filter_hash = cursor_filter_hash(
        {
            "actor": context.user_id,
            "run_id": run.id,
            "status": status,
            "category": category,
            "priority": priority,
            "current_only": current_only,
        }
    )
    statement = select(ValidationRunItem).where(*filters)
    if cursor:
        payload = decode_cursor(request.app.state.settings, namespace="validation-run-items", value=cursor)
        if payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current validation item filters", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(payload["created_at"]))
            cursor_id = UUID(str(payload["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                ValidationRunItem.created_at > cursor_time,
                (ValidationRunItem.created_at == cursor_time) & (ValidationRunItem.id > cursor_id),
            )
        )
    rows = list(session.scalars(statement.order_by(ValidationRunItem.created_at, ValidationRunItem.id).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="validation-run-items",
            payload={"filter": filter_hash, "created_at": last.created_at.isoformat(), "id": str(last.id)},
        )
    allowed_version_ids = _citation_version_ids([item.reference_docs for item in rows])
    if run.document_version_id is not None:
        allowed_version_ids.add(run.document_version_id)
    hydrated_groups = hydrate_citation_groups(
        session,
        [item.reference_docs for item in rows],
        project_id=run.project_id,
        allowed_version_ids=allowed_version_ids,
    )
    return ValidationRunItemPage(
        items=[
            _validation_item_response(item, citations=citations)
            for item, citations in zip(rows, hydrated_groups, strict=True)
        ],
        next_cursor=next_cursor, has_more=has_more,
    )


@router.get("/validation-runs/{run_id}", response_model=ValidationRunResponse)
def get_validation_run(
    run_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ValidationRunResponse:
    return _validation_run_metadata(_authorized_validation_run(session, run_id, context))


@router.get("/validation-runs/{run_id}/export.csv", response_model=None)
def export_validation_run(
    run_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    run = _authorized_validation_run(session, run_id, context)
    return export_project_chat_validation_run(
        project_id=run.project_id,
        run_id=run.id,
        context=context,
        session=session,
    )


@router.post("/validation-runs/{run_id}/retry-failed", response_model=ValidationRunResponse)
def retry_failed_validation_items(
    run_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ValidationRunResponse:
    run = _authorized_validation_run(session, run_id, context)
    if run.created_by != context.user_id:
        raise AppError("validation_retry_forbidden", "Only the run creator may retry failed items", status_code=403)
    return retry_failed_project_chat_validation_items(
        project_id=run.project_id,
        run_id=run.id,
        context=context,
        session=session,
    )


@router.get("/notifications", response_model=NotificationPage)
def list_notifications(
    request: Request,
    notification_type: str | None = Query(default=None, max_length=100),
    severity: str | None = Query(default=None, max_length=32),
    is_read: bool | None = Query(default=None),
    resolved: bool | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> NotificationPage:
    filter_hash = cursor_filter_hash(
        {
            "actor": context.user_id,
            "notification_type": notification_type,
            "severity": severity,
            "is_read": is_read,
            "resolved": resolved,
        }
    )
    statement = _notification_scope_query(context)
    if notification_type:
        statement = statement.where(Notification.notification_type == notification_type)
    if severity:
        statement = statement.where(Notification.severity == severity)
    if is_read is not None:
        statement = statement.where(Notification.is_read.is_(is_read))
    if resolved is not None:
        statement = statement.where(Notification.resolved_at.is_not(None) if resolved else Notification.resolved_at.is_(None))
    if cursor:
        payload = decode_cursor(request.app.state.settings, namespace="notifications", value=cursor)
        if payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current notification filters", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(payload["created_at"]))
            cursor_id = UUID(str(payload["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                Notification.created_at < cursor_time,
                (Notification.created_at == cursor_time) & (Notification.id < cursor_id),
            )
        )
    rows = list(session.scalars(statement.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="notifications",
            payload={"filter": filter_hash, "created_at": last.created_at.isoformat(), "id": str(last.id)},
        )
    return NotificationPage(items=rows, next_cursor=next_cursor, has_more=has_more)


@router.get("/notifications/unread-count", response_model=NotificationCountResponse)
def notification_unread_count(context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> NotificationCountResponse:
    unread_count = session.scalar(select(func.count()).select_from(_notification_scope_query(context).where(Notification.is_read.is_(False)).subquery())) or 0
    return NotificationCountResponse(unread_count=int(unread_count))


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(notification_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> Notification:
    notification = _scoped_notification(session, notification_id, context)
    notification.is_read = True
    session.commit()
    session.refresh(notification)
    return notification


@router.post("/notifications/read-all", response_model=NotificationCountResponse)
def mark_all_notifications_read(context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> NotificationCountResponse:
    notifications = list(session.scalars(_notification_scope_query(context).where(Notification.is_read.is_(False))))
    for notification in notifications:
        notification.is_read = True
    session.commit()
    return NotificationCountResponse(unread_count=0)


@router.post("/notifications/{notification_id}/resolve", response_model=NotificationResponse)
def resolve_notification(notification_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> Notification:
    notification = _scoped_notification(session, notification_id, context)
    notification.is_read = True
    notification.resolved_at = datetime.now(UTC)
    session.commit()
    session.refresh(notification)
    return notification


def _notification_scope_query(context: IdentityContext):
    project_filters = [Notification.project_id.is_(None)]
    if context.visible_project_ids:
        project_filters.append(Notification.project_id.in_(context.visible_project_ids))
    return select(Notification).where(Notification.recipient_user_id == context.user_id, or_(*project_filters))


def _scoped_notification(session: Session, notification_id: UUID, context: IdentityContext) -> Notification:
    notification = session.get(Notification, notification_id)
    if (
        notification is None
        or notification.recipient_user_id != context.user_id
        or (notification.project_id is not None and notification.project_id not in context.visible_project_ids)
    ):
        raise AppError("notification_not_found", "Notification was not found", status_code=404)
    return notification


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
        require_ready_chunk_artifacts(session, version)
    return requested_ids


def _authorize_document_staging_identity(
    session: Session,
    project_id: UUID,
    document_version_id: UUID,
) -> DocumentVersion:
    version = session.get(DocumentVersion, document_version_id)
    if version is None or version.project_id != project_id:
        raise AppError(
            "retrieval_scope_denied",
            "Document version is not in the authorized project",
            status_code=403,
        )
    document = session.get(Document, version.document_id)
    if document is None or document.project_id != project_id or document.is_deleted:
        raise AppError(
            "retrieval_scope_denied",
            "Document version is not attached to a non-deleted document in the authorized project",
            status_code=403,
        )
    return version


def _ensure_conversation_can_continue(session: Session, project_id: UUID, conversation_id: UUID, requested_ids: set[UUID], user_id: UUID, scope_mode: str) -> None:
    identity = require_conversation_identity(session, project_id=project_id, conversation_id=conversation_id,
        user_id=user_id, scope_mode=scope_mode, requested_ids=requested_ids)
    if identity is not None:
        eligible = (_staging_continuable_version_ids(session, project_id, requested_ids)
                    if scope_mode == "document_staging" else _active_version_ids(session, project_id))
        if not requested_ids or not requested_ids.issubset(eligible):
            raise AppError("conversation_read_only", "Conversation retrieval scope is no longer available", status_code=403)


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


def _conversation_title(question: str) -> str:
    normalized = " ".join(question.split())
    return normalized[:80] or "新對話"


def _uuid_set(values: list | None) -> set[UUID]:
    result: set[UUID] = set()
    for value in values or []:
        try:
            result.add(value if isinstance(value, UUID) else UUID(str(value)))
        except ValueError:
            continue
    return result


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _authorized_conversation_records(
    session: Session,
    *,
    project_id: UUID,
    conversation_id: UUID,
    user_id: UUID,
    scope_mode: str,
    document_version_id: UUID | None,
    shared_read: bool = False,
) -> list[ChatRecord]:
    filters = [
        ChatRecord.project_id == project_id,
        ChatRecord.conversation_id == conversation_id,
        ChatRecord.scope_mode == scope_mode,
        ChatRecord.deleted_at.is_(None),
    ]
    if scope_mode == "document_staging":
        if document_version_id is None:
            raise AppError("document_version_scope_required", "Document conversation requires a document version id", status_code=422)
        _authorize_document_staging_identity(session, project_id, document_version_id)
        filters.append(ChatRecord.document_version_id == document_version_id)
    elif document_version_id is not None:
        raise AppError("conversation_scope_invalid", "Published conversation does not accept a document staging version", status_code=422)
    if not shared_read:
        lock_conversation(session, conversation_id)
    identity = conversation_identities(session, [conversation_id]).get(conversation_id)
    if identity is None:
        raise AppError("conversation_not_found", "Conversation was not found", status_code=404)
    validate_visible_identity(identity, project_id=project_id, scope_mode=scope_mode, document_version_id=document_version_id)
    if not shared_read and identity.creator_id != user_id:
        raise AppError("conversation_read_only", "Only the conversation creator may change it", status_code=403)
    return list(
        session.scalars(
            select(ChatRecord)
            .where(*filters)
            .order_by(ChatRecord.asked_at, ChatRecord.id)
            .execution_options(populate_existing=True)
        )
    )


def _csv_row(values: list | tuple) -> str:
    output = io.StringIO()
    csv.writer(output, lineterminator="\r\n").writerow(
        ["" if value is None else str(value) for value in values]
    )
    return output.getvalue()


def _conversation_summaries(session: Session, project_id: UUID, records: list[ChatRecord], *, user_id: UUID | None = None, include_records: bool = False) -> list[ProjectChatConversationResponse]:
    identities = conversation_identities(session, list({record.conversation_id for record in records}))
    # Never partially expose mixed-author/scope history selected by a narrower query.
    records = [record for record in records if identities[record.conversation_id].valid
               and identities[record.conversation_id].project_ids == {project_id}]
    names = dict(session.execute(select(User.id, User.display_name).where(
        User.id.in_({record.created_by for record in records}))).all()) if records else {}
    active_ids = _active_version_ids(session, project_id)
    hydrated_by_record_id: dict[UUID, list] = {}
    if include_records and records:
        hydrated_groups = hydrate_citation_groups(
            session,
            [record.reference_docs for record in records],
            project_id=project_id,
            allowed_version_ids=_record_version_ids(records),
        )
        hydrated_by_record_id = {
            record.id: citations
            for record, citations in zip(records, hydrated_groups, strict=True)
        }
    grouped: dict[UUID, list[ChatRecord]] = {}
    for record in records:
        grouped.setdefault(record.conversation_id, []).append(record)
    responses: list[ProjectChatConversationResponse] = []
    for conversation_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: row.asked_at)
        latest = max(ordered, key=lambda row: row.created_at)
        creator_id = identities[conversation_id].creator_id
        is_mine = creator_id is not None and creator_id == user_id
        selected_ids = sorted(_uuid_set(latest.selected_document_version_ids), key=str)
        continuable_ids = (
            _staging_continuable_version_ids(session, project_id, set(selected_ids))
            if latest.scope_mode == "document_staging"
            else active_ids
        )
        responses.append(
            ProjectChatConversationResponse(
                id=conversation_id,
                title=latest.conversation_title or _conversation_title(ordered[0].question),
                scope_mode=latest.scope_mode,
                selected_document_version_ids=selected_ids,
                message_count=len(ordered),
                updated_at=latest.created_at,
                can_continue=is_mine and bool(selected_ids) and set(selected_ids).issubset(continuable_ids),
                created_by_user_id=creator_id,
                created_by_display_name=names.get(creator_id),
                is_mine=is_mine,
                can_delete=is_mine,
                can_evaluate=is_mine,
                can_export=is_mine,
                read_only_reason=("not_conversation_creator" if not is_mine else
                                  "retrieval_scope_unavailable" if not selected_ids or not set(selected_ids).issubset(continuable_ids) else None),
                records=[_chat_record_response(row, citations=hydrated_by_record_id.get(row.id)) for row in ordered] if include_records else [],
            )
        )
    return sorted(responses, key=lambda item: item.updated_at, reverse=True)


def _staging_continuable_version_ids(
    session: Session,
    project_id: UUID,
    selected_ids: set[UUID],
) -> set[UUID]:
    if not selected_ids:
        return set()
    versions = list(
        session.scalars(
            select(DocumentVersion)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                Document.project_id == project_id,
                Document.is_deleted.is_(False),
                DocumentVersion.id.in_(selected_ids),
                DocumentVersion.status.in_(("submission_ready", "pending_review")),
            )
        )
    )
    continuable: set[UUID] = set()
    for version in versions:
        chunk_count = int(
            session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.document_version_id == version.id, Chunk.status == "active")
            )
            or 0
        )
        _status, ready, _details = chunk_artifact_state(version, chunk_count)
        if ready:
            continuable.add(version.id)
    return continuable


def _record_version_ids(records: list[ChatRecord]) -> set[UUID]:
    version_ids: set[UUID] = set()
    for record in records:
        version_ids.update(_uuid_set(record.selected_document_version_ids))
        if record.document_version_id is not None:
            version_ids.add(record.document_version_id)
    return version_ids


def _citation_version_ids(citation_groups: list[list | None]) -> set[UUID]:
    version_ids: set[UUID] = set()
    for citations in citation_groups:
        for citation in citations or []:
            raw_version_id = (
                citation.get("document_version_id")
                if isinstance(citation, dict)
                else getattr(citation, "document_version_id", None)
            )
            version_id = _uuid_or_none(raw_version_id)
            if version_id is not None:
                version_ids.add(version_id)
    return version_ids


def _chat_record_response(record: ChatRecord, *, citations: list | None = None) -> ProjectChatRecordResponse:
    compact = compact_citation_view(
        record.answer,
        record.reference_docs if citations is None else citations,
    )
    return ProjectChatRecordResponse(
        id=record.id,
        conversation_id=record.conversation_id,
        conversation_title=record.conversation_title,
        scope_mode=record.scope_mode,
        selected_document_version_ids=sorted(_uuid_set(record.selected_document_version_ids), key=str),
        question=record.question,
        answer=compact.answer,
        citations=[ProjectChatCitation(**citation) if isinstance(citation, dict) else citation for citation in compact.citations],
        evaluation=record.evaluation,
        revision_suggestion=record.revision_suggestion,
        llm_model_id=record.llm_model_id,
        prompt_version=record.prompt_version,
        system_prompt_source=record.system_prompt_source,
        system_prompt_version_id=record.system_prompt_version_id,
        system_prompt_content_hash=record.system_prompt_content_hash,
        system_prompt_layers=record.system_prompt_layers,
        token_usage=record.token_usage,
        latency_ms=record.latency_ms,
        asked_at=record.asked_at,
        answered_at=record.answered_at,
    )


def _canonical_json_hash(value: dict | list) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prompt_manifest(prompt) -> dict:
    return {
        "content": prompt.content,
        "source": prompt.source,
        "version_id": str(prompt.version_id) if prompt.version_id else None,
        "content_hash": prompt.content_hash,
        "layers": prompt.metadata(),
    }


def _validation_execution_manifest(
    session: Session,
    *,
    project: Project,
    scope_mode: str,
    selected_ids: set[UUID],
    max_attempts: int,
) -> dict:
    chat_model = _select_chat_model(session, project)
    embedding_model = (
        session.get(AIModel, project.embedding_model_id)
        if project.embedding_model_id
        else None
    )
    if (
        embedding_model is None
        or embedding_model.deleted_at is not None
        or not embedding_model.is_active
    ):
        raise AppError(
            "model_configuration_required",
            "An active Embedding Model is required to create a validation run",
            status_code=409,
        )
    judge_model = session.scalar(
        select(AIModel).where(
            AIModel.model_type == "Judge",
            AIModel.is_active.is_(True),
            AIModel.is_default.is_(True),
            AIModel.deleted_at.is_(None),
        )
    )
    if judge_model is None:
        judge_model = session.scalar(
            select(AIModel).where(
                AIModel.model_type == "Judge",
                AIModel.is_active.is_(True),
                AIModel.deleted_at.is_(None),
            )
        )
    chat_prompt = resolve_system_prompt(
        session,
        model=chat_model,
        model_type="Chat",
    )
    judge_prompt = (
        resolve_system_prompt(session, model=judge_model, model_type="Judge")
        if judge_model is not None
        else None
    )
    return {
        "manifest_version": "validation-v1",
        "state": "available",
        "project_id": str(project.id),
        "project_generation": project.work_generation,
        "scope_mode": scope_mode,
        "selected_document_version_ids": [
            str(item) for item in sorted(selected_ids, key=str)
        ],
        "chat_model_id": str(chat_model.id),
        "embedding_model_id": str(embedding_model.id),
        "judge_model_id": str(judge_model.id) if judge_model else None,
        "chat_prompt": _prompt_manifest(chat_prompt),
        "judge_prompt": _prompt_manifest(judge_prompt) if judge_prompt else None,
        "retrieval_strategy": "hybrid",
        "retrieval_top_k": 5,
        "max_attempts": max_attempts,
    }


def _public_validation_manifest(manifest: dict | None) -> dict:
    public_manifest = json.loads(json.dumps(manifest or {}))
    for key in ("chat_prompt", "judge_prompt"):
        prompt = public_manifest.get(key)
        if isinstance(prompt, dict):
            prompt.pop("content", None)
    return public_manifest


def _validation_run_response(session: Session, run: ValidationRun) -> ValidationRunResponse:
    items = list(session.scalars(select(ValidationRunItem).where(ValidationRunItem.run_id == run.id, ValidationRunItem.is_current.is_(True)).order_by(ValidationRunItem.input_ordinal, ValidationRunItem.id)))
    allowed_version_ids = _citation_version_ids([item.reference_docs for item in items])
    if run.document_version_id is not None:
        allowed_version_ids.add(run.document_version_id)
    hydrated_groups = hydrate_citation_groups(
        session,
        [item.reference_docs for item in items],
        project_id=run.project_id,
        allowed_version_ids=allowed_version_ids,
    )
    hydrated_by_item_id = {
        item.id: citations
        for item, citations in zip(items, hydrated_groups, strict=True)
    }
    return ValidationRunResponse(
        id=run.id,
        project_id=run.project_id,
        uploaded_file_name=run.uploaded_file_name,
        status=run.status,
        run_scope=run.run_scope,
        selected_document_ids=sorted(_uuid_set(run.selected_document_ids), key=str),
        execution_manifest=_public_validation_manifest(run.execution_manifest),
        execution_manifest_hash=run.execution_manifest_hash,
        max_attempts=run.max_attempts,
        total_count=run.total_count,
        completed_count=run.completed_count,
        failed_count=run.failed_count,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        items=[
            _validation_item_response(
                item,
                citations=hydrated_by_item_id.get(item.id, []),
            )
            for item in items
        ],
    )


def _validation_run_metadata(run: ValidationRun) -> ValidationRunResponse:
    return ValidationRunResponse(
        id=run.id,
        project_id=run.project_id,
        uploaded_file_name=run.uploaded_file_name,
        status=run.status,
        run_scope=run.run_scope,
        selected_document_ids=sorted(_uuid_set(run.selected_document_ids), key=str),
        execution_manifest=_public_validation_manifest(run.execution_manifest),
        execution_manifest_hash=run.execution_manifest_hash,
        max_attempts=run.max_attempts,
        total_count=run.total_count,
        completed_count=run.completed_count,
        failed_count=run.failed_count,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        items=[],
    )


def _validation_item_response(item: ValidationRunItem, *, citations: list | None = None) -> ValidationRunItemResponse:
    compact = compact_citation_view(
        item.answer,
        item.reference_docs if citations is None else citations,
    )
    return ValidationRunItemResponse(
        id=item.id,
        parent_item_id=item.parent_item_id,
        attempt=item.attempt,
        is_current=item.is_current,
        input_item_id=item.input_item_id,
        input_ordinal=item.input_ordinal,
        input_content_hash=item.input_content_hash,
        question=item.question,
        expected_answer=item.expected_answer,
        expected_keywords=item.expected_keywords,
        selected_document_ids=sorted(_uuid_set(item.selected_document_ids), key=str),
        category=item.category,
        priority=item.priority,
        answer=compact.answer,
        citations=[ProjectChatCitation(**citation) if isinstance(citation, dict) else citation for citation in compact.citations],
        chat_record_id=item.chat_record_id,
        status=item.status,
        score=float(item.score) if item.score is not None else None,
        evaluation_reason=item.evaluation_reason,
        error_message=item.error_message,
        error_code=item.error_code,
        latency_ms=item.latency_ms,
        token_usage=item.token_usage,
        system_prompt_source=item.system_prompt_source,
        system_prompt_version_id=item.system_prompt_version_id,
        system_prompt_content_hash=item.system_prompt_content_hash,
        system_prompt_layers=item.system_prompt_layers,
    )


def _authorized_validation_run(session: Session, run_id: UUID, context: IdentityContext) -> ValidationRun:
    run = session.get(ValidationRun, run_id)
    if run is None or run.project_id not in context.visible_project_ids:
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    project = session.get(Project, run.project_id)
    if project is None or project.status != "active":
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    if run.created_by != context.user_id and session.get(ProjectOwner, (run.project_id, context.user_id)) is None:
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    if run.run_scope == "document_staging":
        if run.document_version_id is None:
            raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
        try:
            _authorize_document_staging_identity(session, run.project_id, run.document_version_id)
        except AppError as exc:
            raise AppError("validation_run_not_found", "Validation run was not found", status_code=404) from exc
    elif run.run_scope != "project_chat":
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    return run


def _active_version_ids(session: Session, project_id: UUID) -> set[UUID]:
    return {manifest.document_version_id for manifest in session.scalars(_active_retrieval_manifest_query(project_id).where(ActiveVersionManifest.index_ready.is_(True)))}


def _filter_graph_edges(edges: list[ProjectGraphEdge], nodes: dict[str, ProjectGraphNode]) -> list[ProjectGraphEdge]:
    return [edge for edge in edges if edge.source in nodes and edge.target in nodes]


def _project_graph_without_chunk_content(
    session: Session,
    project: Project,
    version_ids: set[UUID],
    node_limit: int,
    *,
    allow_preview: bool = False,
) -> ProjectGraphResponse:
    return _read_neo4j_project_graph(project, version_ids, node_limit, session=session, allow_preview=allow_preview)


def _hydrate_graph_chunk_content(
    session: Session,
    graph: ProjectGraphResponse,
    project_id: UUID,
    version_ids: set[UUID],
) -> ProjectGraphResponse:
    eligible_ids: set[UUID] = set()
    expected_versions: dict[UUID, UUID] = {}
    for node in graph.nodes:
        if node.type != "Chunk":
            continue
        chunk_id = _uuid_or_none(node.id)
        raw_version_id = node.metadata.get("document_version_id")
        version_id = _uuid_or_none(str(raw_version_id)) if raw_version_id is not None else None
        if chunk_id is None or version_id not in version_ids:
            continue
        eligible_ids.add(chunk_id)
        expected_versions[chunk_id] = version_id

    hydrated: dict[UUID, tuple[UUID, int, str, str | None, str]] = {}
    if eligible_ids and version_ids:
        rows = session.execute(
            select(
                Chunk.id,
                Chunk.document_version_id,
                Chunk.chunk_index,
                Chunk.content,
                Chunk.markdown_content,
                Chunk.display_markdown,
            ).where(
                Chunk.id.in_(eligible_ids),
                Chunk.project_id == project_id,
                Chunk.document_version_id.in_(version_ids),
                Chunk.status == "active",
            )
        )
        for chunk_id, version_id, chunk_index, content, markdown_content, display_markdown in rows:
            if expected_versions.get(chunk_id) != version_id:
                continue
            authorized_display = next(
                (
                    value
                    for value in (display_markdown, markdown_content, content)
                    if isinstance(value, str) and value.strip()
                ),
                "",
            )
            hydrated[chunk_id] = (version_id, int(chunk_index), content, markdown_content, authorized_display)

    nodes: list[ProjectGraphNode] = []
    for node in graph.nodes:
        if node.type != "Chunk":
            nodes.append(node)
            continue
        metadata = {
            key: value
            for key, value in node.metadata.items()
            if key not in {"chunk_index", "content", "markdown_content", "display_markdown", "retrieval_text"}
        }
        chunk_id = _uuid_or_none(node.id)
        row = hydrated.get(chunk_id) if chunk_id is not None else None
        if row is not None:
            version_id, chunk_index, content, markdown_content, display_markdown = row
            metadata.update(
                {
                    "document_version_id": str(version_id),
                    "chunk_index": chunk_index,
                    "content": content,
                    "markdown_content": markdown_content,
                    "display_markdown": display_markdown,
                }
            )
        nodes.append(ProjectGraphNode(id=node.id, type=node.type, label=node.label, metadata=metadata))
    graph.nodes = nodes
    return graph





def _neighbor_graph(graph: ProjectGraphResponse, node_id: str, node_limit: int) -> ProjectGraphResponse:
    node_by_id = {node.id: node for node in graph.nodes}
    selected_node = node_by_id.get(node_id)
    if selected_node is None:
        return ProjectGraphResponse(project_id=graph.project_id, nodes=[], edges=[], truncated=graph.truncated, node_limit=node_limit)

    neighbor_ids = {node_id}
    selected_edges: list[ProjectGraphEdge] = []
    for edge in graph.edges:
        if edge.source == node_id or edge.target == node_id:
            neighbor_ids.add(edge.source)
            neighbor_ids.add(edge.target)
            selected_edges.append(edge)

    ordered_nodes = [selected_node] + [node for node in graph.nodes if node.id in neighbor_ids and node.id != node_id]
    truncated = graph.truncated or len(ordered_nodes) > node_limit
    limited_nodes = ordered_nodes[:node_limit]
    limited_node_map = {node.id: node for node in limited_nodes}
    return ProjectGraphResponse(
        project_id=graph.project_id,
        nodes=limited_nodes,
        edges=_filter_graph_edges(selected_edges, limited_node_map),
        truncated=truncated,
        node_limit=node_limit,
    )


def _read_neo4j_project_graph(project: Project, active_version_ids: set[UUID], node_limit: int = 120,
                              *, session: Session, allow_preview: bool = False) -> ProjectGraphResponse:
    from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired
    from app.core.config import get_settings
    from app.domain.graph_projection import build_graph_projection
    from app.domain.graph_reconciliation import Neo4jProjectionStore

    nodes: dict[str, ProjectGraphNode] = {}
    edges: dict[str, ProjectGraphEdge] = {}
    store = Neo4jProjectionStore(get_settings())
    for version_id in sorted(active_version_ids, key=str):
        version = session.get(DocumentVersion, version_id)
        document = session.get(Document, version.document_id) if version else None
        if version is None or document is None or version.project_id != project.id or document.project_id != project.id or document.is_deleted:
            raise AppError("document_version_not_found", "Document version was not found in the authorized scope", status_code=404)
        projection = build_graph_projection(session, project, document, version)
        if allow_preview and version.published_at is None:
            graph = projection.graph
        else:
            try:
                actual = store.read(projection)
            except (Neo4jError, ServiceUnavailable, SessionExpired, OSError) as exc:
                raise AppError("graph_projection_not_ready", "Graph projection is not ready", status_code=503) from exc
            if version.published_at is None or not actual.matches(projection):
                raise AppError("graph_projection_not_ready", "Graph projection is not ready", status_code=503)
            graph = actual.graph
        ids = {node["id"]: f'tag:{node["id"]}' if node["type"] == "Tag" else node["id"] for node in graph["nodes"]}
        for node in graph["nodes"]:
            props = node["properties"]
            key = ids[node["id"]]
            metadata = {**props, "technical_id": node["id"]}
            if node["type"] == "Project":
                metadata["status"] = project.status
            elif node["type"] == "DocumentVersion":
                metadata["status"] = version.status
            elif node["type"] == "Document":
                previous_ids = nodes[key].metadata.get("document_version_ids", []) if key in nodes else []
                metadata.update(version_label=version.version_label, version_status=version.status,
                    document_version_ids=[*previous_ids, str(version.id)])
            nodes[key] = ProjectGraphNode(id=key, type=node["type"],
                label=props.get("name") or props.get("title") or props.get("version_label") or node["type"],
                metadata=metadata)
        for edge in graph["edges"]:
            source, target = ids[edge["source"]], ids[edge["target"]]
            key = f'{source}:{target}:{edge["type"]}'
            edges[key] = ProjectGraphEdge(id=key, source=source, target=target, type=edge["type"], metadata=edge["properties"])
    priority = {"Project": 0, "Document": 1, "DocumentVersion": 2, "Chunk": 3, "Tag": 4}
    ordered = sorted(nodes.values(), key=lambda n: (priority[n.type], n.metadata.get("chunk_index", 0), n.id))
    visible = {n.id: n for n in ordered[:node_limit]}
    return ProjectGraphResponse(project_id=project.id, nodes=list(visible.values()),
        edges=_filter_graph_edges(list(edges.values()), visible), truncated=len(nodes) > node_limit, node_limit=node_limit)


def _search_document_staging_chunks(session: Session, project_id: UUID, version_ids: set[UUID], question: str, top_k: int, *, source_channel: str = "chat_test", actor_user_id: UUID | None = None) -> list[ProjectChatCitation]:
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
        _model, query_vector = embed_query(session, profile=profile, question=question, settings=settings, project_id=project_id, actor_user_id=actor_user_id, source_channel=source_channel)
        for index_name, scoped_version_ids in _hybrid_index_scopes(settings.opensearch_index_prefix, project_id, scoped_versions, scope):
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
    """Build missing document-scoped staging indices without falling back to PostgreSQL retrieval.

    Document Chat Test is allowed to query the current working version in the
    staging scope. Older development records may already have PostgreSQL chunks
    and an embedding profile but predate live OpenSearch staging writes. In that
    case, rebuild the missing staging index first and still execute the answer
    path through OpenSearch hybrid retrieval.
    """

    project = session.get(Project, project_id)
    if project is None:
        raise AppError("project_not_found", "Project not found", status_code=404)
    adapter = LiveOpenSearchStagingIndexAdapter(settings)
    for version in versions:
        index_name = staging_index_name(settings.opensearch_index_prefix, project.id, version.id)
        if version.embedding_profile_id and _opensearch_index_exists(index_name):
            continue
        document = session.get(Document, version.document_id)
        if document is None or document.project_id != project.id:
            raise AppError("retrieval_scope_inconsistent", "Retrieval document is inconsistent with project scope", status_code=409)
        chunks = [chunk for chunk in chunks_by_id.values() if chunk.document_version_id == version.id]
        if not chunks:
            continue
        batch = embed_chunks(session, project=project, version=version, chunks=sorted(chunks, key=lambda item: item.chunk_index), settings=settings)
        result = adapter.write_chunks(project=project, document=document, version=version, chunks=sorted(chunks, key=lambda item: item.chunk_index), vectors=batch.vectors, profile=batch.profile)
        version.extraction_artifact_uri = f"opensearch://{result.index_name}"
        session.flush()


def _hybrid_index_scopes(prefix: str, project_id: UUID, versions: list[DocumentVersion], scope: str) -> list[tuple[str, set[UUID]]]:
    if scope == "published":
        grouped: dict[str, set[UUID]] = {}
        for version in versions:
            if version.embedding_profile_id is None:
                raise AppError("embedding_profile_required", "Embedding Profile is required before hybrid retrieval", status_code=409)
            grouped.setdefault(published_index_name(prefix, version.embedding_profile_id), set()).add(version.id)
        return list(grouped.items())
    if scope == "staging":
        return [(staging_index_name(prefix, project_id, version.id), {version.id}) for version in versions]
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


def _opensearch_index_exists(index_name: str) -> bool:  # pragma: no cover - covered by live acceptance
    from app.core.config import get_settings

    settings = get_settings()
    context = settings.opensearch_ssl_context
    request = urllib.request.Request(f"{settings.opensearch_url.rstrip('/')}/{index_name}", method="HEAD")
    username = settings.opensearch_username.get_secret_value()
    password = settings.opensearch_password.get_secret_value()
    if username or password:
        token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=5, context=context):  # noqa: S310
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise AppError("hybrid_retrieval_failed", "OpenSearch hybrid retrieval endpoint is unavailable", status_code=503) from exc
    except OSError as exc:
        raise AppError("hybrid_retrieval_failed", "OpenSearch hybrid retrieval endpoint is unavailable", status_code=503) from exc


def _legacy_keyword_opensearch_search(index_name: str, project_id: UUID, question: str, version_ids: list[str], top_k: int) -> dict:  # pragma: no cover - retained only for migration reference
    data = _opensearch_search(
        index_name,
        _keyword_query_body(
            project_id,
            question,
            version_ids,
            top_k,
            "published",
            mapping_version=1,
        ),
    )
    return data


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
