from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.serving import (
    _active_retrieval_manifest_query,
    _generate_citation_bound_answer,
    _search_published_chunks,
    _select_chat_model,
)
from app.api.schemas import (
    ProjectChatCitation,
    PublicApiChatPayload,
    PublicApiChatResponse,
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
from app.domain.public_api_controls import (
    IdempotencyReplay,
    begin_idempotent_operation,
    complete_idempotent_operation,
    decrypt_payload,
    encrypt_payload,
    end_user_identity_hash,
    enforce_rate_limit,
    fail_idempotent_operation,
    keyed_fingerprint,
)
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


@router.post("/projects/{project_id}/chat", response_model=PublicApiChatResponse)
def public_project_chat(
    project_id: UUID,
    payload: PublicApiChatPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    client: IntegrationClient = Depends(get_public_integration_client),
    session: Session = Depends(get_db),
) -> PublicApiChatResponse:
    settings = request.app.state.settings
    replay, operation = begin_idempotent_operation(
        session,
        settings,
        scope=f"public-chat:{client.id}:{project_id}:json",
        raw_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
    )
    if replay is not None:
        return _chat_replay(replay)
    session.commit()
    try:
        return _run_public_chat(session, request, client, project_id, payload, operation)
    except AppError as exc:
        _record_public_error(session, request, client, project_id, payload, exc, response_mode="json")
        operation = session.get(IdempotencyKey, operation.id)
        if operation is not None:
            fail_idempotent_operation(operation, exc)
            session.commit()
        raise


@router.post("/projects/{project_id}/chat/stream")
def public_project_chat_stream(
    project_id: UUID,
    payload: PublicApiChatPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    client: IntegrationClient = Depends(get_public_integration_client),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    settings = request.app.state.settings
    replay, operation = begin_idempotent_operation(
        session,
        settings,
        scope=f"public-chat:{client.id}:{project_id}:sse",
        raw_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
    )
    if replay is not None:
        result = _chat_replay(replay)

        async def replay_events():
            yield _sse_event("metadata", {"response_id": str(result.response_id), "status": result.status, "request_id": result.request_id, "replay": True})
            if result.answer:
                yield _sse_event("delta", {"text": result.answer})
            yield _sse_event("citations", {"citations": [citation.model_dump(mode="json") for citation in result.citations]})
            if result.token_usage:
                yield _sse_event("usage", result.token_usage)
            yield _sse_event("done", result.model_dump(mode="json"))

        return StreamingResponse(replay_events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    session.commit()
    try:
        prepared = _prepare_public_chat(session, request, client, project_id, payload, response_mode="sse")
        system_prompt = resolve_system_prompt(session, model=prepared[4], model_type="Chat") if prepared[4] is not None else None
        provider_stream = stream_rag_answer(question=payload.question, citations=prepared[3], model=prepared[4], settings=settings, system_prompt=system_prompt)
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
        )
        log.prompt_version = provider_stream.prompt_version
        log.system_prompt_source = provider_stream.system_prompt_source
        log.system_prompt_version_id = provider_stream.system_prompt_version_id
        log.system_prompt_content_hash = provider_stream.system_prompt_content_hash
        log.system_prompt_layers = provider_stream.system_prompt_layers
        session.commit()
    except AppError as exc:
        operation = session.get(IdempotencyKey, operation.id)
        if operation is not None:
            fail_idempotent_operation(operation, exc)
        _record_public_error(session, request, client, project_id, payload, exc, response_mode="sse")
        session.commit()
        raise

    selected_docs = sorted({manifest.document_id for manifest in prepared[0] if manifest.document_version_id in prepared[2]}, key=str)
    status = "answered" if prepared[3] else "no_answer"
    started = perf_counter()

    async def events():
        answer_parts: list[str] = []
        display_parts: list[str] = []
        stream_compactor = CitationStreamCompactor(len(prepared[3]))
        token_usage: dict | None = None
        yield _sse_event("metadata", {"response_id": str(log.id), "status": status, "request_id": log.request_id})
        try:
            async for chunk in provider_stream.chunks:
                if await request.is_disconnected():
                    await _persist_stream_terminal(log.id, operation.id, client.id, settings, answer_parts, prepared[3], token_usage, "cancelled", started)
                    return
                if chunk.text:
                    answer_parts.append(chunk.text)
                    display_text = stream_compactor.feed(chunk.text)
                    if display_text:
                        display_parts.append(display_text)
                        yield _sse_event("delta", {"text": display_text})
                if chunk.token_usage:
                    token_usage = chunk.token_usage
            trailing_text = stream_compactor.finish()
            if trailing_text:
                display_parts.append(trailing_text)
                yield _sse_event("delta", {"text": trailing_text})
            raw_answer = "".join(answer_parts)
            validate_citation_markers(raw_answer, len(prepared[3]))
            compact = compact_citation_view(raw_answer, prepared[3])
            if compact.answer != "".join(display_parts):
                raise AppError(
                    "provider_response_contract_invalid",
                    "Streamed Chat Model response does not match the final citation view",
                    status_code=502,
                )
            result = PublicApiChatResponse(
                response_id=log.id,
                answer=compact.answer or "",
                citations=compact.citations,
                status=status,
                retrieval_strategy="hybrid",
                selected_document_ids=selected_docs,
                selected_document_version_ids=sorted(prepared[2], key=str),
                prompt_version=provider_stream.prompt_version,
                system_prompt_source=provider_stream.system_prompt_source,
                system_prompt_version_id=provider_stream.system_prompt_version_id,
                system_prompt_content_hash=provider_stream.system_prompt_content_hash,
                system_prompt_layers=provider_stream.system_prompt_layers,
                llm_model_id=prepared[4].id if prepared[4] else None,
                token_usage=token_usage,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                request_id=log.request_id,
            )
            await _persist_stream_success(log.id, operation.id, client.id, settings, result, raw_answer=raw_answer)
            yield _sse_event("citations", {"citations": [citation.model_dump(mode="json") for citation in result.citations]})
            if token_usage:
                yield _sse_event("usage", token_usage)
            yield _sse_event("done", result.model_dump(mode="json"))
        except asyncio.CancelledError:
            await _persist_stream_terminal(log.id, operation.id, client.id, settings, answer_parts, prepared[3], token_usage, "cancelled", started)
            raise
        except AppError as exc:
            await _persist_stream_terminal(log.id, operation.id, client.id, settings, answer_parts, prepared[3], token_usage, "failed", started, exc)
            yield _sse_event("error", {"code": exc.code, "message": exc.message, "response_id": str(log.id)})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/chat/responses/{response_id}/feedback", response_model=PublicApiFeedbackResponse)
def create_public_feedback(
    response_id: UUID,
    payload: PublicApiFeedbackPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    client: IntegrationClient = Depends(get_public_integration_client),
    session: Session = Depends(get_db),
) -> PublicApiFeedbackResponse:
    settings = request.app.state.settings
    replay, operation = begin_idempotent_operation(
        session,
        settings,
        scope=f"public-feedback:{client.id}:{response_id}",
        raw_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
    )
    if replay is not None:
        if replay.status_code >= 400:
            _raise_replay_error(replay)
        return PublicApiFeedbackResponse.model_validate(replay.body)
    log = session.get(PublicApiRequestLog, response_id)
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
    event = ChatFeedbackEvent(
        id=uuid4(),
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
        end_user_metadata_encrypted=encrypt_payload(settings, log.id, f"feedback:{operation.id}:end-user", payload.end_user.model_dump(mode="json")),
        idempotency_key_hash=operation.key,
        request_id=getattr(request.state, "request_id", None),
        created_at=datetime.now(UTC),
    )
    session.add(event)
    session.flush()
    result = PublicApiFeedbackResponse(feedback_event_id=event.id, response_id=log.id, latest_feedback=payload.feedback, comment=event.comment, created_at=event.created_at)
    complete_idempotent_operation(operation, result.model_dump(mode="json"), status_code=200)
    session.commit()
    return result


def _run_public_chat(
    session: Session,
    request: Request,
    client: IntegrationClient,
    project_id: UUID,
    payload: PublicApiChatPayload,
    operation: IdempotencyKey,
) -> PublicApiChatResponse:
    manifests, _manifest_ids, selected_version_ids, citations, chat_model = _prepare_public_chat(session, request, client, project_id, payload, response_mode="json")
    started = perf_counter()
    provider_result = None
    try:
        provider_result = _generate_citation_bound_answer(session, payload.question, citations, chat_model)
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
    log = _create_public_log(
        session,
        request,
        client,
        project_id,
        payload,
        response_mode="json",
        lifecycle_status="answered" if citations else "no_answer",
        operation=operation,
        manifests=manifests,
        selected_version_ids=selected_version_ids,
        citations=citations,
        chat_model=chat_model,
    )
    log.answer_encrypted = encrypt_payload(request.app.state.settings, log.id, "answer", provider_result.answer)
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
    result = PublicApiChatResponse(
        response_id=log.id,
        answer=compact.answer or "",
        citations=compact.citations,
        status="answered" if citations else "no_answer",
        retrieval_strategy="hybrid",
        selected_document_ids=selected_docs,
        selected_document_version_ids=sorted(selected_version_ids, key=str),
        prompt_version=provider_result.prompt_version,
        system_prompt_source=provider_result.system_prompt_source,
        system_prompt_version_id=provider_result.system_prompt_version_id,
        system_prompt_content_hash=provider_result.system_prompt_content_hash,
        system_prompt_layers=provider_result.system_prompt_layers,
        llm_model_id=chat_model.id if chat_model else None,
        token_usage=provider_result.token_usage,
        latency_ms=latency_ms,
        request_id=log.request_id,
    )
    complete_idempotent_operation(operation, result.model_dump(mode="json"), status_code=200)
    session.commit()
    return result


def _prepare_public_chat(session: Session, request: Request, client: IntegrationClient, project_id: UUID, payload: PublicApiChatPayload, *, response_mode: str):
    settings = request.app.state.settings
    limit = int((client.rate_limit_config or {}).get("requests_per_minute") or 60)
    enforce_rate_limit(settings, dimension=f"client:{client.id}", limit=limit)
    enforce_rate_limit(settings, dimension=f"client-project:{client.id}:{project_id}", limit=limit)
    _ensure_project_scope(session, client.id, project_id)
    project = session.get(Project, project_id)
    if project is None or project.status != "active":
        raise AppError("project_not_found", "Project was not found", status_code=404)
    selected_document_ids = payload.scope.document_ids if payload.scope else None
    manifests, manifest_ids, selected_version_ids = _resolve_public_scope(session, project.id, selected_document_ids)
    citations = _search_published_chunks(session, project.id, selected_version_ids, payload.question, payload.top_k, source_channel="public_api")
    chat_model = _select_chat_model(session, project) if citations else None
    return manifests, manifest_ids, selected_version_ids, citations, chat_model


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
        endpoint=f"/api/public/v1/projects/{project_id}/chat" + ("/stream" if response_mode == "sse" else ""),
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
    session.add(log)
    session.flush()
    return log


async def _persist_stream_success(log_id: UUID, operation_id: UUID, client_id: UUID, settings, result: PublicApiChatResponse, *, raw_answer: str) -> None:
    with get_session_factory()() as session:
        log = session.get(PublicApiRequestLog, log_id)
        operation = session.get(IdempotencyKey, operation_id)
        client = session.get(IntegrationClient, client_id)
        if log is None or operation is None or client is None:
            return
        log.answer_encrypted = encrypt_payload(settings, log.id, "answer", raw_answer)
        log.lifecycle_status = result.status
        log.result = "success"
        log.retrieval_status = result.status
        log.token_usage = result.token_usage
        log.latency_ms = result.latency_ms
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
                token_usage=result.token_usage,
                latency_ms=result.latency_ms,
                project_id=log.project_id,
                public_api_request_log_id=log.id,
                integration_client_id=client.id,
                correlation_id=log.request_id,
            )
        complete_idempotent_operation(operation, result.model_dump(mode="json"), status_code=200)
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
                endpoint=f"/api/public/v1/projects/{project_id}/chat" + ("/stream" if response_mode == "sse" else ""),
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


def _chat_replay(replay: IdempotencyReplay) -> PublicApiChatResponse:
    if replay.status_code >= 400:
        _raise_replay_error(replay)
    return PublicApiChatResponse.model_validate(replay.body)


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


def _sse_event(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
