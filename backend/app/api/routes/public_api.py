from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import UUID, uuid4

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.serving import (
    _active_retrieval_manifest_query,
    _generate_citation_bound_answer,
    _search_published_chunks,
    _select_chat_model,
)
from app.domain.retrieval_tuning import resolve_retrieval_tuning
from app.api.schemas import (
    ProjectChatCitation,
    PublicApiChatPayload,
    PublicApiChatScope,
    PublicApiFeedbackPayload,
    PublicApiFeedbackResponse,
)
from app.core.errors import AppError
from app.db.models import (
    ActiveVersionManifest,
    AIModel,
    ChatFeedbackEvent,
    IdempotencyKey,
    IntegrationClient,
    IntegrationClientProjectScope,
    Project,
    PublicApiRequestLog,
)
from app.db.session import get_db, get_session_factory
from app.domain.ai_provider import stream_rag_answer
from app.domain.chat_citations import CitationStreamCompactor, citation_persistence_payload, compact_citation_view, validate_citation_markers
from app.domain.integration_api_keys import api_key_hash
from app.domain.model_usage import record_model_usage
from app.domain.conversation_history import ConversationContext, bound_history, public_turns, rewrite_question
from app.domain.responses_service import (
    CreateRequest,
    ResponseEventStream,
    answer_extensions,
    log_stream_finished,
    build_response,
    citation_annotations,
    format_response_id,
    parse_create_request,
    parse_response_id,
)
from app.domain.public_api_controls import IdempotencyReplay, begin_idempotent_operation, complete_idempotent_operation, encrypt_payload, end_user_identity_hash, enforce_rate_limit, fail_idempotent_operation, keyed_fingerprint, release_idempotent_operation
from app.domain.system_prompts import resolve_system_prompt


router = APIRouter(prefix="/api/public/v1", tags=["public-api"])


def get_public_integration_client(request: Request, session: Session = Depends(get_db)) -> IntegrationClient:
    settings = request.app.state.settings
    try:
        token = _extract_api_key(request)
    except AppError:
        enforce_rate_limit(
            settings,
            dimension=f"invalid:missing:{_source_address(request)}",
            limit=settings.public_api_invalid_auth_requests_per_minute,
        )
        raise
    token_hash = api_key_hash(token)
    client = session.scalar(select(IntegrationClient).where(IntegrationClient.api_key_hash == token_hash))
    if client is None:
        enforce_rate_limit(
            settings,
            dimension=f"invalid:{keyed_fingerprint(settings, 'unknown-api-key', token)}:{_source_address(request)}",
            limit=settings.public_api_invalid_auth_requests_per_minute,
        )
        raise AppError("invalid_api_key", "API key is invalid", status_code=401)
    now = datetime.now(UTC)
    if client.status == "revoked" or client.revoked_at is not None:
        _record_invalid_auth_rate(request, token)
        _record_auth_failure(session, client)
        raise AppError("api_key_revoked", "API key is revoked", status_code=401)
    if client.status != "active":
        _record_invalid_auth_rate(request, token)
        _record_auth_failure(session, client)
        raise AppError("api_key_inactive", "API key is inactive", status_code=401)
    if client.valid_from is not None and client.valid_from > now:
        _record_invalid_auth_rate(request, token)
        _record_auth_failure(session, client)
        raise AppError("api_key_not_yet_valid", "API key is not yet valid", status_code=401)
    if client.expires_at is not None and client.expires_at <= now:
        _record_invalid_auth_rate(request, token)
        _record_auth_failure(session, client)
        raise AppError("api_key_expired", "API key is expired", status_code=401)
    return client


@router.post("/responses")
def create_public_response(
    request: Request,
    body: Any = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    client: IntegrationClient = Depends(get_public_integration_client),
    session: Session = Depends(get_db),
):
    """CHG-434 ORESP434-002..006: Open Responses create, JSON or SSE (`stream: true`)."""
    settings = request.app.state.settings
    parsed = parse_create_request(body, channel="public")
    payload = PublicApiChatPayload(
        question=parsed.question,
        end_user=parsed.end_user,
        scope=PublicApiChatScope(document_ids=parsed.document_ids) if parsed.document_ids is not None else None,
        top_k=parsed.top_k,
        top_p=parsed.top_p,
    )
    response_mode = "sse" if parsed.stream else "json"
    replay, operation = begin_idempotent_operation(
        session,
        settings,
        scope=f"public-responses:{client.id}:{parsed.project_id}:{response_mode}",
        raw_key=_idempotency_key_or_single_use(idempotency_key),
        request_payload=body,
    )
    _set_idempotency_state(request, idempotency_key, replayed=replay is not None)
    if replay is not None:
        if replay.status_code >= 400:
            _raise_replay_error(replay)
        resource = dict(replay.body)
        if not parsed.stream:
            return JSONResponse(resource)
        return _event_stream_response(_replay_events(request, resource, parsed.project_id))
    session.commit()
    request.state.public_model_called = False
    if not parsed.stream:
        try:
            return JSONResponse(_run_public_chat(session, request, client, parsed, payload, operation))
        except AppError as exc:
            _settle_failed_operation(session, request, idempotency_key, operation.id, exc)
            _record_public_error(session, request, client, parsed.project_id, payload, exc, response_mode="json")
            raise

    project_id = parsed.project_id
    try:
        prepared = _prepare_public_chat(session, request, client, project_id, payload, response_mode="sse", parsed=parsed)
        turn: ConversationContext = request.state.public_turn
        system_prompt = resolve_system_prompt(session, model=prepared[4], model_type="Chat") if prepared[4] is not None else None
        provider_stream = stream_rag_answer(question=payload.question, citations=prepared[3], model=prepared[4], settings=settings, system_prompt=system_prompt, history=turn.history)
        log = _create_public_log(
            session,
            request,
            client,
            project_id,
            payload,
            response_mode="sse",
            lifecycle_status="streaming",
            operation=operation,
            manifests=prepared[0],
            selected_version_ids=prepared[2],
            citations=prepared[3],
            chat_model=prepared[4],
            turn=turn,
        )
        log.prompt_version = provider_stream.prompt_version
        log.system_prompt_source = provider_stream.system_prompt_source
        log.system_prompt_version_id = provider_stream.system_prompt_version_id
        log.system_prompt_content_hash = provider_stream.system_prompt_content_hash
        log.system_prompt_layers = provider_stream.system_prompt_layers
        session.commit()
    except AppError as exc:
        _settle_failed_operation(session, request, idempotency_key, operation.id, exc)
        _record_public_error(session, request, client, project_id, payload, exc, response_mode="sse")
        session.commit()
        raise

    selected_docs = sorted({manifest.document_id for manifest in prepared[0] if manifest.document_version_id in prepared[2]}, key=str)
    answer_status = "answered" if prepared[3] else "no_answer"
    created_at = log.started_at
    request_id = log.request_id
    started = perf_counter()

    def extensions(token_latency: int | None) -> dict:
        return answer_extensions(
            request_id=request_id,
            answer_status=answer_status,
            selected_document_version_ids=prepared[2],
            system_prompt_source=provider_stream.system_prompt_source,
            system_prompt_version_id=provider_stream.system_prompt_version_id,
            system_prompt_content_hash=provider_stream.system_prompt_content_hash,
            llm_model_id=prepared[4].id if prepared[4] else None,
            latency_ms=token_latency,
            extra={"nomosmart:selected_document_ids": [str(item) for item in selected_docs], "nomosmart:context": turn.extension()},
        )

    async def events():
        answer_parts: list[str] = []
        display_parts: list[str] = []
        stream_compactor = CitationStreamCompactor(len(prepared[3]))
        token_usage: dict | None = None
        events_out = ResponseEventStream(log.id)
        try:
            # The opening events are inside the try: a client can leave while they are sent (CHG-476).
            for event in events_out.start(build_response(response_uuid=log.id, request=parsed, created_at=created_at, status="in_progress", answer=None, annotations=None, token_usage=None, extensions=extensions(None))):
                yield event
            async for chunk in provider_stream.chunks:
                if await request.is_disconnected():
                    await _persist_stream_terminal(log.id, operation.id, client.id, settings, answer_parts, prepared[3], token_usage, "cancelled", started)
                    log_stream_finished(request, project_id=project_id, result="cancelled", error_code="public_stream_cancelled", started=started)
                    return
                if chunk.text:
                    answer_parts.append(chunk.text)
                    display_text = stream_compactor.feed(chunk.text)
                    if display_text:
                        display_parts.append(display_text)
                        yield events_out.delta(display_text)
                if chunk.token_usage:
                    token_usage = chunk.token_usage
            trailing_text = stream_compactor.finish()
            if trailing_text:
                display_parts.append(trailing_text)
                yield events_out.delta(trailing_text)
            raw_answer = "".join(answer_parts)
            validate_citation_markers(raw_answer, len(prepared[3]))
            compact = compact_citation_view(raw_answer, prepared[3])
            if compact.answer != "".join(display_parts):
                raise AppError(
                    "provider_response_contract_invalid",
                    "Streamed Chat Model response does not match the final citation view",
                    status_code=502,
                )
            latency_ms = max(0, int((perf_counter() - started) * 1000))
            completed_at = datetime.now(UTC)
            resource = build_response(
                response_uuid=log.id,
                request=parsed,
                created_at=created_at,
                completed_at=completed_at,
                status="completed",
                answer=compact.answer or "",
                annotations=citation_annotations(compact.answer or "", compact.citations, project_id=project_id, frontend_origin=settings.frontend_app_origin, channel="public"),
                token_usage=token_usage,
                extensions=extensions(latency_ms),
            )
            await _persist_stream_success(log.id, operation.id, client.id, settings, resource, answer_status=answer_status, token_usage=token_usage, latency_ms=latency_ms, raw_answer=raw_answer)
            for event in events_out.finish(resource):
                yield event
            log_stream_finished(request, project_id=project_id, result="completed", started=started)
        except (asyncio.CancelledError, GeneratorExit):
            # GeneratorExit: the client left while the stream waited to send an event; the generator is then closed
            # at its `yield` instead of being cancelled. Either way the request is recorded as cancelled (CHG-476).
            await _persist_stream_terminal(log.id, operation.id, client.id, settings, answer_parts, prepared[3], token_usage, "cancelled", started)
            log_stream_finished(request, project_id=project_id, result="cancelled", error_code="public_stream_cancelled", started=started)
            raise
        except AppError as exc:
            await _persist_stream_terminal(log.id, operation.id, client.id, settings, answer_parts, prepared[3], token_usage, "failed", started, exc)
            log_stream_finished(request, project_id=project_id, result="failed", error_code=exc.code, started=started)
            failed = build_response(response_uuid=log.id, request=parsed, created_at=created_at, completed_at=datetime.now(UTC), status="failed", answer=None, annotations=None, token_usage=token_usage, extensions=extensions(None), error=exc)
            for event in events_out.fail(failed, exc, request_id):
                yield event

    return _event_stream_response(events())


@router.post("/responses/{response_id}/feedback", response_model=PublicApiFeedbackResponse)
def create_public_feedback(
    response_id: str,
    payload: PublicApiFeedbackPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    client: IntegrationClient = Depends(get_public_integration_client),
    session: Session = Depends(get_db),
) -> PublicApiFeedbackResponse:
    settings = request.app.state.settings
    response_uuid = parse_response_id(response_id)
    if response_uuid is None:
        raise AppError("public_response_not_found", "Public API response was not found", status_code=404)
    replay, operation = begin_idempotent_operation(
        session,
        settings,
        scope=f"public-feedback:{client.id}:{response_uuid}",
        raw_key=_idempotency_key_or_single_use(idempotency_key),
        request_payload=payload.model_dump(mode="json"),
    )
    _set_idempotency_state(request, idempotency_key, replayed=replay is not None)
    if replay is not None:
        if replay.status_code >= 400:
            _raise_replay_error(replay)
        return PublicApiFeedbackResponse.model_validate(replay.body)
    log = session.get(PublicApiRequestLog, response_uuid)
    identity_hash = end_user_identity_hash(settings, payload.end_user.employee_id)
    if (
        log is None
        or log.integration_client_id != client.id
        or log.deleted_at is not None
        or log.end_user_identity_hash != identity_hash
    ):
        exc = AppError("public_response_not_found", "Public API response was not found", status_code=404)
        fail_idempotent_operation(operation, exc)
        session.commit()
        raise exc
    # The event is durable; a replay-cache operation can be removed after TTL.
    # Bind the encrypted caller metadata to the event, not the temporary row.
    event_id = uuid4()
    event = ChatFeedbackEvent(
        id=event_id,
        project_id=log.project_id,
        public_response_id=log.id,
        source="api",
        feedback_value=payload.feedback,
        comment=_clean_optional(payload.comment),
        integration_client_id=client.id,
        end_user_employee_id=None,
        end_user_employee_name=None,
        end_user_department=None,
        end_user_identity_hash=identity_hash,
        end_user_metadata_encrypted=encrypt_payload(settings, log.id, f"feedback:{event_id}:end-user", payload.end_user.model_dump(mode="json")),
        idempotency_key_hash=operation.key,
        request_id=getattr(request.state, "request_id", None),
        created_at=datetime.now(UTC),
    )
    session.add(event)
    session.flush()
    result = PublicApiFeedbackResponse(feedback_event_id=event.id, response_id=format_response_id(log.id), latest_feedback=payload.feedback, comment=event.comment, created_at=event.created_at)
    complete_idempotent_operation(operation, result.model_dump(mode="json"), status_code=200)
    session.commit()
    return result


def _run_public_chat(
    session: Session,
    request: Request,
    client: IntegrationClient,
    parsed: CreateRequest,
    payload: PublicApiChatPayload,
    operation: IdempotencyKey,
) -> dict:
    project_id = parsed.project_id
    manifests, _manifest_ids, selected_version_ids, citations, chat_model = _prepare_public_chat(session, request, client, project_id, payload, response_mode="json", parsed=parsed)
    turn: ConversationContext = request.state.public_turn
    started = perf_counter()
    provider_result = None
    if citations:
        request.state.public_model_called = True  # PUBIDEM440-001: answer generation calls the model
    try:
        provider_result = _generate_citation_bound_answer(session, payload.question, citations, chat_model, turn.history)
        validate_citation_markers(provider_result.answer, len(citations))
    except AppError as exc:
        if chat_model is not None:
            record_model_usage(
                session,
                model=chat_model,
                usage_purpose="public_api_chat",
                source_channel="public_api",
                status="failed",
                token_usage=provider_result.token_usage if provider_result is not None else None,
                error_code=exc.code,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                project_id=project_id,
                integration_client_id=client.id,
                correlation_id=getattr(request.state, "request_id", None),
            )
        raise
    latency_ms = max(0, int((perf_counter() - started) * 1000))
    selected_docs = sorted({manifest.document_id for manifest in manifests if manifest.document_version_id in selected_version_ids}, key=str)
    answer_status = "answered" if citations else "no_answer"
    log = _create_public_log(
        session,
        request,
        client,
        project_id,
        payload,
        response_mode="json",
        lifecycle_status=answer_status,
        operation=operation,
        manifests=manifests,
        selected_version_ids=selected_version_ids,
        citations=citations,
        chat_model=chat_model,
        turn=turn,
    )
    settings = request.app.state.settings
    log.answer_encrypted = encrypt_payload(settings, log.id, "answer", provider_result.answer)
    log.prompt_version = provider_result.prompt_version
    log.system_prompt_source = provider_result.system_prompt_source
    log.system_prompt_version_id = provider_result.system_prompt_version_id
    log.system_prompt_content_hash = provider_result.system_prompt_content_hash
    log.system_prompt_layers = provider_result.system_prompt_layers
    log.token_usage = provider_result.token_usage
    log.latency_ms = latency_ms
    log.result = "success"
    log.completed_at = datetime.now(UTC)
    client.success_count += 1
    client.last_used_at = log.completed_at
    client.last_used_project_id = project_id
    if chat_model is not None:
        record_model_usage(
            session,
            model=chat_model,
            usage_purpose="public_api_chat",
            source_channel="public_api",
            status="success",
            token_usage=provider_result.token_usage,
            latency_ms=latency_ms,
            project_id=project_id,
            public_api_request_log_id=log.id,
            integration_client_id=client.id,
            correlation_id=log.request_id,
        )
    compact = compact_citation_view(provider_result.answer, citations)
    resource = build_response(
        response_uuid=log.id,
        request=parsed,
        created_at=log.started_at,
        completed_at=log.completed_at,
        status="completed",
        answer=compact.answer or "",
        annotations=citation_annotations(compact.answer or "", compact.citations, project_id=project_id, frontend_origin=settings.frontend_app_origin, channel="public"),
        token_usage=provider_result.token_usage,
        extensions=answer_extensions(
            request_id=log.request_id,
            answer_status=answer_status,
            selected_document_version_ids=selected_version_ids,
            system_prompt_source=provider_result.system_prompt_source,
            system_prompt_version_id=provider_result.system_prompt_version_id,
            system_prompt_content_hash=provider_result.system_prompt_content_hash,
            llm_model_id=chat_model.id if chat_model else None,
            latency_ms=latency_ms,
            extra={"nomosmart:selected_document_ids": [str(item) for item in selected_docs], "nomosmart:context": turn.extension()},
        ),
    )
    resource = json.loads(json.dumps(resource, default=str))
    complete_idempotent_operation(operation, resource, status_code=200)
    session.commit()
    return resource


def _idempotency_key_or_single_use(raw_key: str | None) -> str:
    """CHG-434 D434-03 (Peter 2026-11-16 "C"): Idempotency-Key is optional on the public entry.

    A caller key keeps replay protection. Without one, a server-generated single-use key still
    records the operation (audit and failure state) but can never match a retry, so each call
    is a new answer, as with other Open Responses servers.
    """
    if raw_key is not None and raw_key.strip():
        return raw_key
    return f"single-use-{uuid4()}"


def _set_idempotency_state(request: Request, raw_key: str | None, *, replayed: bool) -> None:
    """PUBIDEM440-007: how this request used the Idempotency-Key, for the request log."""
    caller_key = raw_key is not None and bool(raw_key.strip())
    request.state.idempotency = "replayed" if replayed else ("new" if caller_key else "none")


def _settle_failed_operation(session: Session, request: Request, raw_key: str | None, operation_id: UUID, exc: AppError) -> None:
    """PUBIDEM440-001/002: keep a failure for replay only once the model was called; otherwise release the key.

    Committed by the caller together with the failure request log (PUBIDEM440-003).
    """
    operation = session.get(IdempotencyKey, operation_id)
    if operation is None:
        return
    if getattr(request.state, "public_model_called", False):
        fail_idempotent_operation(operation, exc)
        return
    release_idempotent_operation(session, operation)
    if raw_key is not None and raw_key.strip():
        request.state.idempotency = "released"


def _event_stream_response(events) -> StreamingResponse:
    return StreamingResponse(events, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _replay_events(request: Request, resource: dict, project_id: UUID):
    """A replayed idempotent stream re-emits the stored final response as standard events."""
    started = perf_counter()
    response_uuid = parse_response_id(str(resource.get("id", ""))) or uuid4()
    events_out = ResponseEventStream(response_uuid)
    started = {**resource, "status": "in_progress", "output": [], "usage": None, "completed_at": None}
    for event in events_out.start(started):
        yield event
    text = resource["output"][0]["content"][0]["text"] if resource.get("output") else ""
    if text:
        yield events_out.delta(text)
    for event in events_out.finish(resource):
        yield event
    log_stream_finished(request, project_id=project_id, result="completed", started=started)


def _prepare_public_chat(session: Session, request: Request, client: IntegrationClient, project_id: UUID, payload: PublicApiChatPayload, *, response_mode: str,
                         parsed: CreateRequest | None = None):
    settings = request.app.state.settings
    limit = int((client.rate_limit_config or {}).get("requests_per_minute") or 60)
    enforce_rate_limit(settings, dimension=f"client:{client.id}", limit=limit)
    enforce_rate_limit(settings, dimension=f"client-project:{client.id}:{project_id}", limit=limit)
    _ensure_project_scope(session, client.id, project_id)
    project = session.get(Project, project_id)
    if project is None or project.status != "active":
        raise AppError("project_not_found", "Project was not found", status_code=404)
    selected_document_ids = payload.scope.document_ids if payload.scope else None
    # MTURN435-003: who may continue is decided before scope readiness, so an unusable id is always 404.
    turn, turns = _public_history(session, request, client, project, payload, parsed)
    manifests, manifest_ids, selected_version_ids = _resolve_public_scope(session, project.id, selected_document_ids)
    _public_rewrite(session, request, client, project, payload, parsed, turn, turns)
    tuning = resolve_retrieval_tuning(session, project.id, top_k=payload.top_k, top_p=payload.top_p)  # CHG-486 TOPKP486-003
    citations = _search_published_chunks(session, project.id, selected_version_ids, turn.search_question, tuning, source_channel="public_api")
    chat_model = _select_chat_model(session, project) if citations else None
    request.state.public_turn = turn
    return manifests, manifest_ids, selected_version_ids, citations, chat_model


def _public_history(session: Session, request: Request, client: IntegrationClient, project: Project, payload: PublicApiChatPayload,
                    parsed: CreateRequest | None) -> tuple[ConversationContext, list[tuple[str, str]]]:
    """CHG-435 MTURN435-002/003: earlier turns from this API key, employee and project only."""
    settings = request.app.state.settings
    previous_id = parsed.previous_id if parsed else None
    turn = ConversationContext(previous_id=previous_id, search_question=payload.question)
    if previous_id is None:
        return turn, []
    turns = public_turns(session, settings, previous_id, client_id=client.id,
                         identity_hash=end_user_identity_hash(settings, payload.end_user.employee_id), project_id=project.id)
    return turn, turns


def _public_rewrite(session: Session, request: Request, client: IntegrationClient, project: Project, payload: PublicApiChatPayload,
                    parsed: CreateRequest | None, turn: ConversationContext, turns: list[tuple[str, str]]) -> None:
    """MTURN435-004/005: bound the history, then rewrite the follow-up before retrieval."""
    if not turns:
        return
    settings = request.app.state.settings
    turn.history, turn.truncated = bound_history(turns, settings, parsed.truncation if parsed else None)
    try:
        model = _select_chat_model(session, project)
    except AppError:
        model = None
    if turn.history and model is not None:
        request.state.public_model_called = True  # PUBIDEM440-001: the follow-up rewrite calls the model
    rewrite_question(session, settings, turn, payload.question, model, source_channel="public_api", project_id=project.id,
                     integration_client_id=client.id, correlation_id=getattr(request.state, "request_id", None))


def _create_public_log(
    session: Session,
    request: Request,
    client: IntegrationClient,
    project_id: UUID,
    payload: PublicApiChatPayload,
    *,
    response_mode: str,
    lifecycle_status: str,
    operation: IdempotencyKey,
    manifests: list[ActiveVersionManifest],
    selected_version_ids: set[UUID],
    citations: list[ProjectChatCitation],
    chat_model,
    turn: ConversationContext | None = None,
) -> PublicApiRequestLog:
    settings = request.app.state.settings
    now = datetime.now(UTC)
    response_id = uuid4()
    selected_docs = sorted({manifest.document_id for manifest in manifests if manifest.document_version_id in selected_version_ids}, key=str)
    log = PublicApiRequestLog(
        id=response_id,
        integration_client_id=client.id,
        project_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        endpoint="/api/public/v1/responses",
        response_mode=response_mode,
        result="processing",
        http_status=200,
        lifecycle_status=lifecycle_status,
        request_hash=operation.request_hash,
        idempotency_key_hash=operation.key,
        end_user_employee_id="",
        end_user_employee_name=None,
        end_user_department=None,
        end_user_identity_hash=end_user_identity_hash(settings, payload.end_user.employee_id),
        end_user_metadata_encrypted=encrypt_payload(settings, response_id, "end-user", payload.end_user.model_dump(mode="json")),
        question=None,
        question_encrypted=encrypt_payload(settings, response_id, "question", payload.question),
        answer=None,
        citations=[],
        citations_encrypted=encrypt_payload(settings, response_id, "citations", [citation_persistence_payload(citation) for citation in citations]),
        selected_document_ids=[str(item) for item in selected_docs],
        selected_document_version_ids=[str(item) for item in sorted(selected_version_ids, key=str)],
        retrieval_strategy="hybrid",
        retrieval_status="answered" if citations else "no_answer",
        llm_model_id=chat_model.id if chat_model else None,
        started_at=now,
        content_expires_at=now + timedelta(days=settings.public_api_content_retention_days),
        retention_expires_at=now + timedelta(days=settings.public_api_record_retention_days),
        metadata_={"encrypted_content": True},
        created_at=now,
    )
    if turn is not None:
        log.previous_response_id = turn.previous_id
        log.history_turns = turn.turns_used
        log.history_truncated = turn.truncated
        log.rewrite_status = turn.rewrite_status
        log.rewritten_query_encrypted = encrypt_payload(settings, response_id, "rewritten-query", turn.rewritten_query) if turn.rewritten_query else None
    session.add(log)
    session.flush()
    return log


async def _persist_stream_success(
    log_id: UUID,
    operation_id: UUID,
    client_id: UUID,
    settings,
    resource: dict,
    *,
    answer_status: str,
    token_usage: dict | None,
    latency_ms: int,
    raw_answer: str,
) -> None:
    with get_session_factory()() as session:
        log = session.get(PublicApiRequestLog, log_id)
        operation = session.get(IdempotencyKey, operation_id)
        client = session.get(IntegrationClient, client_id)
        if log is None or operation is None or client is None:
            return
        log.answer_encrypted = encrypt_payload(settings, log.id, "answer", raw_answer)
        log.lifecycle_status = answer_status
        log.result = "success"
        log.retrieval_status = answer_status
        log.token_usage = token_usage
        log.latency_ms = latency_ms
        log.completed_at = datetime.now(UTC)
        client.success_count += 1
        client.last_used_at = log.completed_at
        client.last_used_project_id = log.project_id
        model = session.get(AIModel, log.llm_model_id) if log.llm_model_id is not None else None
        if model is not None:
            record_model_usage(
                session,
                model=model,
                usage_purpose="public_api_chat",
                source_channel="public_api",
                status="success",
                token_usage=token_usage,
                latency_ms=latency_ms,
                project_id=log.project_id,
                public_api_request_log_id=log.id,
                integration_client_id=client.id,
                correlation_id=log.request_id,
            )
        complete_idempotent_operation(operation, json.loads(json.dumps(resource, default=str)), status_code=200)
        session.commit()


async def _persist_stream_terminal(
    log_id: UUID,
    operation_id: UUID,
    client_id: UUID,
    settings,
    answer_parts: list[str],
    citations: list[ProjectChatCitation],
    token_usage: dict | None,
    terminal: str,
    started: float,
    error: AppError | None = None,
) -> None:
    with get_session_factory()() as session:
        log = session.get(PublicApiRequestLog, log_id)
        operation = session.get(IdempotencyKey, operation_id)
        client = session.get(IntegrationClient, client_id)
        if log is None or operation is None or client is None:
            return
        answer = "".join(answer_parts)
        log.answer_encrypted = encrypt_payload(settings, log.id, "answer", answer) if answer else None
        log.lifecycle_status = "partial" if answer else terminal
        log.result = terminal
        log.http_status = 499 if terminal == "cancelled" else (error.status_code if error else 500)
        log.token_usage = token_usage
        log.latency_ms = max(0, int((perf_counter() - started) * 1000))
        log.completed_at = datetime.now(UTC)
        log.cancelled_at = log.completed_at if terminal == "cancelled" else None
        if error:
            log.error_code = error.code
            log.error_message = error.message
            fail_idempotent_operation(operation, error)
        else:
            cancelled = AppError("public_stream_cancelled", "Public API stream was cancelled", status_code=409)
            fail_idempotent_operation(operation, cancelled)
        client.failure_count += 1
        client.last_used_at = log.completed_at
        model = session.get(AIModel, log.llm_model_id) if log.llm_model_id is not None else None
        if model is not None:
            record_model_usage(
                session,
                model=model,
                usage_purpose="public_api_chat",
                source_channel="public_api",
                status="partial" if answer else terminal,
                token_usage=token_usage,
                latency_ms=log.latency_ms,
                error_code=error.code if error else "public_stream_cancelled",
                project_id=log.project_id,
                public_api_request_log_id=log.id,
                integration_client_id=client.id,
                correlation_id=log.request_id,
            )
        session.commit()


def _resolve_public_scope(session: Session, project_id: UUID, document_ids: list[UUID] | None) -> tuple[list[ActiveVersionManifest], set[UUID], set[UUID]]:
    statement = _active_retrieval_manifest_query(project_id).where(ActiveVersionManifest.index_ready.is_(True))
    if document_ids:
        statement = statement.where(ActiveVersionManifest.document_id.in_(set(document_ids)))
    manifests = list(session.scalars(statement))
    if not manifests:
        raise AppError("active_manifest_required", "Project has no ready active manifest for retrieval", status_code=409)
    if document_ids and {manifest.document_id for manifest in manifests} != set(document_ids):
        raise AppError("retrieval_scope_denied", "Retrieval scope must be active published documents in this project", status_code=403)
    manifest_ids = {manifest.document_version_id for manifest in manifests}
    return manifests, manifest_ids, manifest_ids


def _ensure_project_scope(session: Session, client_id: UUID, project_id: UUID) -> None:
    allowed = session.scalar(select(IntegrationClientProjectScope).where(IntegrationClientProjectScope.client_id == client_id, IntegrationClientProjectScope.project_id == project_id))
    if allowed is None:
        raise AppError("integration_project_scope_denied", "API key cannot access this project", status_code=403)


def _record_public_error(session: Session, request: Request, client: IntegrationClient, project_id: UUID, payload: PublicApiChatPayload, exc: AppError, *, response_mode: str) -> None:
    now = datetime.now(UTC)
    client.failure_count += 1
    client.last_used_at = now
    if session.get(Project, project_id) is not None:
        settings = request.app.state.settings
        response_id = uuid4()
        session.add(
            PublicApiRequestLog(
                id=response_id,
                integration_client_id=client.id,
                project_id=project_id,
                request_id=getattr(request.state, "request_id", None),
                endpoint="/api/public/v1/responses",
                response_mode=response_mode,
                result="failure",
                http_status=exc.status_code,
                lifecycle_status="failed",
                end_user_employee_id="",
                end_user_identity_hash=end_user_identity_hash(settings, payload.end_user.employee_id),
                end_user_metadata_encrypted=encrypt_payload(settings, response_id, "end-user", payload.end_user.model_dump(mode="json")),
                question_encrypted=encrypt_payload(settings, response_id, "question", payload.question),
                selected_document_ids=[str(item) for item in (payload.scope.document_ids if payload.scope and payload.scope.document_ids else [])],
                selected_document_version_ids=[],
                retrieval_strategy="hybrid",
                retrieval_status="error",
                error_code=exc.code,
                error_message=exc.message,
                started_at=now,
                completed_at=now,
                content_expires_at=now + timedelta(days=settings.public_api_content_retention_days),
                retention_expires_at=now + timedelta(days=settings.public_api_record_retention_days),
                metadata_={"encrypted_content": True},
                created_at=now,
            )
        )
    session.commit()


def _record_auth_failure(session: Session, client: IntegrationClient) -> None:
    client.failure_count += 1
    client.last_used_at = datetime.now(UTC)
    session.commit()


def _record_invalid_auth_rate(request: Request, token: str) -> None:
    settings = request.app.state.settings
    enforce_rate_limit(
        settings,
        dimension=f"invalid:{keyed_fingerprint(settings, 'inactive-api-key', token)}:{_source_address(request)}",
        limit=settings.public_api_invalid_auth_requests_per_minute,
    )


def _raise_replay_error(replay: IdempotencyReplay) -> None:
    error = replay.body.get("error") if isinstance(replay.body, dict) else None
    raise AppError(
        str(error.get("code") if isinstance(error, dict) else "idempotent_operation_failed"),
        str(error.get("message") if isinstance(error, dict) else "Previous idempotent operation failed"),
        status_code=replay.status_code,
    )


def _extract_api_key(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    header_key = request.headers.get("x-nomosmart-api-key", "").strip()
    if header_key:
        return header_key
    raise AppError("api_key_required", "API key is required", status_code=401)


def _source_address(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
