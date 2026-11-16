"""CHG-434 ORESP434-002: internal Open Responses entry for the web chat test.

`POST /api/v1/responses` accepts only the browser session (the public entry
`/api/public/v1/responses` accepts only API keys). Both share the request/response
contract in `domain/responses_service.py` and the retrieval/answer path in
`domain/project_retrieval.py`; chat-test answers stay in `chat_records`.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.routes.serving import (
    _conversation_title,
    _ensure_conversation_can_continue,
    run_chat_test_query,
)
from app.api.schemas import ProjectChatCitation, ProjectChatQueryPayload
from app.core.errors import AppError
from app.db.models import AIModel, ChatRecord
from app.db.session import get_db, get_session_factory
from app.domain.ai_provider import stream_rag_answer
from app.domain.chat_citations import CitationStreamCompactor, citation_persistence_payload, compact_citation_view, validate_citation_markers
from app.domain.chat_conversations import require_conversation_identity
from app.domain.conversation_history import ConversationContext, chat_test_context, chat_test_mode
from app.domain.model_usage import record_model_usage
from app.domain.project_access import get_scoped_project
from app.domain.project_retrieval import (
    _resolve_document_staging_scope,
    _resolve_retrieval_scope,
    _search_document_staging_chunks,
    _search_published_chunks,
    _select_chat_model,
)
from app.domain.responses_service import (
    CreateRequest,
    ResponseEventStream,
    answer_extensions,
    build_response,
    citation_annotations,
    log_stream_finished,
    parse_create_request,
)
from app.domain.system_prompts import resolve_system_prompt
from app.security.context import IdentityContext, get_identity_context

router = APIRouter(tags=["responses"])


@router.post("/responses")
def create_internal_response(
    request: Request,
    body: Any = Body(default=None),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
):
    parsed = parse_create_request(body, channel="internal")
    payload = _chat_payload(parsed)
    if not parsed.stream:
        created_at = datetime.now(UTC)
        result = run_chat_test_query(parsed.project_id, payload, context, session)
        return JSONResponse(_resource_from_result(request, parsed, result, created_at))
    return _stream_chat_test(request, parsed, payload, context, session)


def _chat_payload(parsed: CreateRequest) -> ProjectChatQueryPayload:
    return ProjectChatQueryPayload(
        question=parsed.question,
        document_version_ids=parsed.document_version_ids,
        scope_mode=parsed.scope_mode,
        top_k=parsed.top_k,
        conversation_id=parsed.conversation_id,
        conversation_title=parsed.conversation_title,
        previous_id=parsed.previous_id,
        conversation_mode=parsed.conversation_mode,
        truncation=parsed.truncation,
    )


def _resource_from_result(request: Request, parsed: CreateRequest, result, created_at: datetime) -> dict:
    settings = request.app.state.settings
    response_uuid = result.chat_record_id
    return build_response(
        response_uuid=response_uuid,
        request=parsed,
        created_at=created_at,
        completed_at=datetime.now(UTC),
        status="completed",
        answer=result.answer,
        annotations=citation_annotations(result.answer, result.citations, project_id=parsed.project_id, frontend_origin=settings.frontend_app_origin, channel="internal"),
        token_usage=result.token_usage,
        extensions=answer_extensions(
            request_id=getattr(request.state, "request_id", None),
            answer_status=result.status,
            selected_document_version_ids=result.selected_version_ids,
            system_prompt_source=result.system_prompt_source,
            system_prompt_version_id=result.system_prompt_version_id,
            system_prompt_content_hash=result.system_prompt_content_hash,
            llm_model_id=result.llm_model_id,
            latency_ms=result.latency_ms,
            extra=_internal_extra(result.conversation_id, result.conversation_title, result.manifest_version_ids, result.prompt_version,
                                  result.conversation_mode, result.context),
        ),
    )


def _internal_extra(conversation_id: UUID, title: str, manifest_ids, prompt_version: str | None, mode: str, turn_context: dict) -> dict:
    return {
        "nomosmart:conversation": {"id": str(conversation_id), "title": title, "mode": mode},
        "nomosmart:context": turn_context,
        "nomosmart:manifest_version_ids": [str(item) for item in sorted(manifest_ids, key=str)],
        "nomosmart:retrieval_strategy": "hybrid",
        "nomosmart:prompt_version": prompt_version,
    }


def _stream_chat_test(request: Request, parsed: CreateRequest, payload: ProjectChatQueryPayload, context: IdentityContext, session: Session) -> StreamingResponse:
    """Same checks as `run_chat_test_query`, answering with the streaming provider path."""

    settings = request.app.state.settings
    project = get_scoped_project(session, parsed.project_id, context)
    conversation_id = payload.conversation_id or uuid4()
    if payload.scope_mode == "document_staging" and len(set(payload.document_version_ids or [])) != 1:
        raise AppError("document_version_scope_required", "Document chat requires exactly one document version", status_code=422)
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
    conversation_mode, turn = chat_test_context(session, settings, project, payload, user_id=context.user_id, conversation_id=conversation_id)
    citations = (
        _search_document_staging_chunks(session, project.id, requested_ids, turn.search_question, payload.top_k, source_channel="chat_test", actor_user_id=context.user_id)
        if payload.scope_mode == "document_staging"
        else _search_published_chunks(session, project.id, requested_ids, turn.search_question, payload.top_k, source_channel="chat_test", actor_user_id=context.user_id)
    )
    answer_status = "answered" if citations else "no_answer"
    chat_model = _select_chat_model(session, project) if citations else None
    system_prompt = resolve_system_prompt(session, model=chat_model, model_type="Chat") if chat_model is not None else None
    provider_stream = stream_rag_answer(question=payload.question, citations=citations, model=chat_model, settings=settings, system_prompt=system_prompt, history=turn.history)
    title = payload.conversation_title or _conversation_title(payload.question)
    record_id = uuid4()
    project_id = project.id
    user_id = context.user_id
    chat_model_id = chat_model.id if chat_model else None
    request_id = getattr(request.state, "request_id", None)
    session.commit()

    def extensions(latency_ms: int | None) -> dict:
        return answer_extensions(
            request_id=request_id,
            answer_status=answer_status,
            selected_document_version_ids=requested_ids,
            system_prompt_source=provider_stream.system_prompt_source,
            system_prompt_version_id=provider_stream.system_prompt_version_id,
            system_prompt_content_hash=provider_stream.system_prompt_content_hash,
            llm_model_id=chat_model_id,
            latency_ms=latency_ms,
            extra=_internal_extra(conversation_id, title, manifest_ids, provider_stream.prompt_version, conversation_mode, turn.extension()),
        )

    async def events():
        answer_parts: list[str] = []
        display_parts: list[str] = []
        compactor = CitationStreamCompactor(len(citations))
        token_usage: dict | None = None
        provider_started = perf_counter()
        events_out = ResponseEventStream(record_id)
        for event in events_out.start(build_response(response_uuid=record_id, request=parsed, created_at=asked_at, status="in_progress", answer=None, annotations=None, token_usage=None, extensions=extensions(None))):
            yield event
        try:
            async for chunk in provider_stream.chunks:
                if await request.is_disconnected():
                    _record_stream_usage(chat_model_id, project_id, user_id, payload, requested_ids, token_usage, provider_started, "partial" if answer_parts else "cancelled", "chat_test_stream_cancelled")
                    log_stream_finished(request, project_id=project_id, result="cancelled", error_code="chat_test_stream_cancelled", started=started)
                    return
                if chunk.text:
                    answer_parts.append(chunk.text)
                    display_text = compactor.feed(chunk.text)
                    if display_text:
                        display_parts.append(display_text)
                        yield events_out.delta(display_text)
                if chunk.token_usage:
                    token_usage = chunk.token_usage
            trailing = compactor.finish()
            if trailing:
                display_parts.append(trailing)
                yield events_out.delta(trailing)
            raw_answer = "".join(answer_parts)
            validate_citation_markers(raw_answer, len(citations))
            compact = compact_citation_view(raw_answer, citations)
            if compact.answer != "".join(display_parts):
                raise AppError("provider_response_contract_invalid", "Streamed Chat Model response does not match the final citation view", status_code=502)
            latency_ms = max(0, int((perf_counter() - started) * 1000))
            _persist_chat_record(
                record_id=record_id, project_id=project_id, user_id=user_id, payload=payload, conversation_id=conversation_id,
                title=title, requested_ids=requested_ids, citations=citations, answer=raw_answer, chat_model_id=chat_model_id,
                provider_stream=provider_stream, token_usage=token_usage, latency_ms=latency_ms, asked_at=asked_at,
                provider_latency_ms=max(0, int((perf_counter() - provider_started) * 1000)),
                conversation_mode=conversation_mode, turn=turn,
            )
            resource = build_response(
                response_uuid=record_id,
                request=parsed,
                created_at=asked_at,
                completed_at=datetime.now(UTC),
                status="completed",
                answer=compact.answer or "",
                annotations=citation_annotations(compact.answer or "", compact.citations, project_id=project_id, frontend_origin=settings.frontend_app_origin, channel="internal"),
                token_usage=token_usage,
                extensions=extensions(latency_ms),
            )
            for event in events_out.finish(resource):
                yield event
            log_stream_finished(request, project_id=project_id, result="completed", started=started)
        except asyncio.CancelledError:
            _record_stream_usage(chat_model_id, project_id, user_id, payload, requested_ids, token_usage, provider_started, "partial" if answer_parts else "cancelled", "chat_test_stream_cancelled")
            log_stream_finished(request, project_id=project_id, result="cancelled", error_code="chat_test_stream_cancelled", started=started)
            raise
        except AppError as exc:
            _record_stream_usage(chat_model_id, project_id, user_id, payload, requested_ids, token_usage, provider_started, "failed", exc.code)
            log_stream_finished(request, project_id=project_id, result="failed", error_code=exc.code, started=started)
            failed = build_response(response_uuid=record_id, request=parsed, created_at=asked_at, completed_at=datetime.now(UTC), status="failed", answer=None, annotations=None, token_usage=token_usage, extensions=extensions(None), error=exc)
            for event in events_out.fail(failed, exc, request_id):
                yield event

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _persist_chat_record(
    *,
    record_id: UUID,
    project_id: UUID,
    user_id: UUID,
    payload: ProjectChatQueryPayload,
    conversation_id: UUID,
    title: str,
    requested_ids: set[UUID],
    citations: list[ProjectChatCitation],
    answer: str,
    chat_model_id: UUID | None,
    provider_stream,
    token_usage: dict | None,
    latency_ms: int,
    asked_at: datetime,
    provider_latency_ms: int,
    conversation_mode: str,
    turn: ConversationContext,
) -> None:
    """Write the chat record after the stream, re-checking the conversation under its lock."""

    with get_session_factory()() as session:
        require_conversation_identity(session, project_id=project_id, conversation_id=conversation_id,
            user_id=user_id, scope_mode=payload.scope_mode, requested_ids=requested_ids)
        _ensure_conversation_can_continue(session, project_id, conversation_id, requested_ids, user_id, payload.scope_mode)
        # The conversation may have moved on while this answer streamed; re-apply the mode rule under the lock.
        chat_test_mode(session, conversation_id, payload.conversation_mode, payload.previous_id)
        answered_at = datetime.now(UTC)
        record = ChatRecord(
            id=record_id,
            project_id=project_id,
            document_version_id=next(iter(requested_ids)) if len(requested_ids) == 1 else None,
            scope_mode=payload.scope_mode,
            conversation_id=conversation_id,
            conversation_title=title,
            selected_document_version_ids=[str(item) for item in sorted(requested_ids, key=str)],
            question=payload.question,
            answer=answer,
            reference_docs=[citation_persistence_payload(citation) for citation in citations],
            evaluation="not_evaluated",
            llm_model_id=chat_model_id,
            embedding_model_id=None,
            prompt_version=provider_stream.prompt_version,
            system_prompt_source=provider_stream.system_prompt_source,
            system_prompt_version_id=provider_stream.system_prompt_version_id,
            system_prompt_content_hash=provider_stream.system_prompt_content_hash,
            system_prompt_layers=provider_stream.system_prompt_layers,
            token_usage=token_usage,
            latency_ms=latency_ms,
            created_by=user_id,
            asked_at=asked_at,
            answered_at=answered_at,
            created_at=asked_at,
            previous_response_id=turn.previous_id,
            conversation_mode=conversation_mode,
            history_turns=turn.turns_used,
            history_truncated=turn.truncated,
            rewritten_query=turn.rewritten_query,
            rewrite_status=turn.rewrite_status,
        )
        session.add(record)
        session.flush([record])
        model = session.get(AIModel, chat_model_id) if chat_model_id else None
        if model is not None:
            record_model_usage(
                session,
                model=model,
                usage_purpose="chat_test",
                source_channel="chat_test",
                status="success",
                token_usage=token_usage,
                latency_ms=provider_latency_ms,
                project_id=project_id,
                document_version_id=record.document_version_id,
                chat_record_id=record.id,
                actor_user_id=user_id,
                metadata={"scope_mode": payload.scope_mode},
            )
        session.commit()


def _record_stream_usage(chat_model_id, project_id, user_id, payload, requested_ids, token_usage, provider_started, status: str, error_code: str) -> None:
    if chat_model_id is None:
        return
    with get_session_factory()() as session:
        model = session.get(AIModel, chat_model_id)
        if model is None:
            return
        record_model_usage(
            session,
            model=model,
            usage_purpose="chat_test",
            source_channel="chat_test",
            status=status,
            token_usage=token_usage,
            error_code=error_code,
            latency_ms=max(0, int((perf_counter() - provider_started) * 1000)),
            project_id=project_id,
            document_version_id=next(iter(requested_ids)) if len(requested_ids) == 1 else None,
            actor_user_id=user_id,
            metadata={"scope_mode": payload.scope_mode},
        )
        session.commit()
