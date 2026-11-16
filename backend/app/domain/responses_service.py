"""CHG-434 ORESP434-001..006: one Open Responses contract for every question-answering entry.

The public entry (`/api/public/v1/responses`, API key) and the internal entry
(`/api/v1/responses`, browser session) parse the same request body, answer through the
same retrieval/model/System Prompt path (`project_retrieval`), and return the same
`ResponseResource` and SSE event sequence. Only authentication, the extension fields a
caller may send, and the record table differ (Peter 2026-11-16, D434-01).

Specification: Open Responses 2026-04-24 (https://www.openresponses.org/specification).
CHG-435 adds multi-turn context through `previous_response_id` (MTURN435-001..009).
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from app.api.schemas import PublicApiEndUser
from app.core.errors import AppError
from app.domain.model_usage import normalize_usage

Channel = Literal["public", "internal"]
StreamResult = Literal["completed", "failed", "cancelled"]

stream_logger = logging.getLogger("nomosmart.responses")

PROJECT_MODEL_PREFIX = "nomosmart:project/"
RESPONSE_ID_PREFIX = "resp_"
QUESTION_MAX_LENGTH = 4000
NO_ANSWER_STATUS = "no_answer"

_CITATION_MARKER = re.compile(r"\[(\d+)\]")

# Standard fields NomoSmart accepts when they carry no behavior it would have to honor.
_NEUTRAL_FIELDS: dict[str, Any] = {
    "tools": lambda value: value in (None, []),
    "tool_choice": lambda value: value in (None, "auto", "none"),
    "parallel_tool_calls": lambda value: value is None or isinstance(value, bool),
    "truncation": lambda value: value in (None, "auto", "disabled"),
    "include": lambda value: value in (None, []),
    "stream_options": lambda value: value is None or isinstance(value, dict),
    "service_tier": lambda value: value in (None, "auto", "default"),
    "background": lambda value: value in (None, False),
    "safety_identifier": lambda value: value is None or (isinstance(value, str) and len(value) <= 64),
    "prompt_cache_key": lambda value: value is None or (isinstance(value, str) and len(value) <= 64),
}
# Standard fields that would change model behavior; the project configuration decides them.
_BEHAVIOR_FIELDS = (
    "temperature", "top_p", "presence_penalty", "frequency_penalty", "top_logprobs",
    "max_output_tokens", "max_tool_calls", "reasoning", "text",
)
_COMMON_FIELDS = {"model", "input", "stream", "metadata", "store", "instructions", "previous_response_id", "nomosmart:scope", "nomosmart:top_k"}
_CHANNEL_FIELDS = {"public": {"nomosmart:end_user"}, "internal": {"nomosmart:conversation"}}


@dataclass(frozen=True)
class CreateRequest:
    """A validated Open Responses create request mapped to NomoSmart terms."""

    channel: Channel
    model: str
    project_id: UUID
    question: str
    stream: bool
    top_k: int
    metadata: dict[str, str] = field(default_factory=dict)
    end_user: PublicApiEndUser | None = None
    document_ids: list[UUID] | None = None
    scope_mode: Literal["published", "document_staging"] = "published"
    document_version_ids: list[UUID] | None = None
    conversation_id: UUID | None = None
    conversation_title: str | None = None
    conversation_mode: Literal["single", "multi"] | None = None
    previous_response_id: str | None = None
    previous_id: UUID | None = None
    truncation: str | None = None


def invalid(code: str, message: str, param: str | None = None, *, status_code: int = 400) -> AppError:
    return AppError(code, message, status_code=status_code, details={"param": param} if param else {})


def parse_create_request(body: Any, *, channel: Channel) -> CreateRequest:
    if not isinstance(body, dict):
        raise invalid("invalid_request_body", "Request body must be a JSON object")
    allowed = _COMMON_FIELDS | _CHANNEL_FIELDS[channel] | set(_NEUTRAL_FIELDS) | set(_BEHAVIOR_FIELDS)
    for name in body:
        if name not in allowed:
            raise invalid("unsupported_parameter", f"Parameter '{name}' is not supported", name)
    for name, accepts in _NEUTRAL_FIELDS.items():
        if name in body and not accepts(body[name]):
            raise invalid("unsupported_parameter", f"Parameter '{name}' value is not supported", name)
    for name in _BEHAVIOR_FIELDS:
        if body.get(name) is not None:
            raise invalid("unsupported_parameter", f"Parameter '{name}' is decided by the project configuration", name)
    if body.get("instructions") is not None:
        raise invalid("instructions_not_supported", "Callers cannot set or override the System Prompt", "instructions")
    previous_response_id = body.get("previous_response_id")
    previous_id = None
    if previous_response_id is not None:
        # CHG-435 MTURN435-003: an unknown or malformed id is reported like any id the caller cannot use.
        previous_id = parse_response_id(previous_response_id) if isinstance(previous_response_id, str) else None
        if previous_id is None:
            raise AppError("previous_response_not_found", "The previous response was not found", status_code=404,
                           details={"param": "previous_response_id"})
    store = body.get("store")
    if store is not None and store is not True:
        raise invalid("store_false_not_supported", "Every answer is stored as an audit record; store must be true or omitted", "store")
    stream = body.get("stream")
    if stream is not None and not isinstance(stream, bool):
        raise invalid("invalid_type", "stream must be a boolean", "stream")

    model = body.get("model")
    project_id = parse_project_model(model)
    question = _parse_input(body.get("input"))
    metadata = _parse_metadata(body.get("metadata"))
    top_k = _parse_top_k(body.get("nomosmart:top_k"))
    request = dict(channel=channel, model=model, project_id=project_id, question=question, stream=bool(stream), top_k=top_k, metadata=metadata,
                   previous_response_id=previous_response_id if previous_id else None, previous_id=previous_id, truncation=body.get("truncation"))
    scope = body.get("nomosmart:scope")
    if scope is not None and not isinstance(scope, dict):
        raise invalid("invalid_type", "nomosmart:scope must be an object", "nomosmart:scope")

    if channel == "public":
        if body.get("nomosmart:end_user") is None:
            raise invalid("missing_required_parameter", "nomosmart:end_user is required", "nomosmart:end_user")
        try:
            end_user = PublicApiEndUser.model_validate(body["nomosmart:end_user"])
        except ValidationError as exc:
            raise invalid("invalid_end_user", "nomosmart:end_user is invalid", _validation_param("nomosmart:end_user", exc)) from exc
        document_ids = None
        if scope is not None:
            for key in scope:
                if key != "document_ids":
                    raise invalid("unsupported_parameter", f"Scope field '{key}' is not supported", f"nomosmart:scope.{key}")
            document_ids = _uuid_list(scope.get("document_ids"), "nomosmart:scope.document_ids")
        return CreateRequest(**request, end_user=end_user, document_ids=document_ids)

    scope = scope or {}
    for key in scope:
        if key not in {"mode", "document_version_ids"}:
            raise invalid("unsupported_parameter", f"Scope field '{key}' is not supported", f"nomosmart:scope.{key}")
    mode = scope.get("mode", "published")
    if mode not in {"published", "document_staging"}:
        raise invalid("invalid_scope_mode", "Scope mode must be published or document_staging", "nomosmart:scope.mode")
    conversation = body.get("nomosmart:conversation") or {}
    if not isinstance(conversation, dict) or set(conversation) - {"id", "title", "mode"}:
        raise invalid("unsupported_parameter", "nomosmart:conversation accepts only id, title and mode", "nomosmart:conversation")
    conversation_mode = conversation.get("mode")
    if conversation_mode is not None and conversation_mode not in {"single", "multi"}:
        raise invalid("invalid_conversation_mode", "Conversation mode must be single or multi", "nomosmart:conversation.mode")
    conversation_id = _uuid_or_error(conversation["id"], "nomosmart:conversation.id") if conversation.get("id") is not None else None
    title = conversation.get("title")
    if title is not None and (not isinstance(title, str) or len(title) > 500):
        raise invalid("invalid_type", "Conversation title must be text of at most 500 characters", "nomosmart:conversation.title")
    return CreateRequest(
        **request,
        scope_mode=mode,
        document_version_ids=_uuid_list(scope.get("document_version_ids"), "nomosmart:scope.document_version_ids"),
        conversation_id=conversation_id,
        conversation_title=title,
        conversation_mode=conversation_mode,
    )


def parse_project_model(model: Any) -> UUID:
    if not isinstance(model, str) or not model.startswith(PROJECT_MODEL_PREFIX):
        raise invalid("invalid_model", f"model must be '{PROJECT_MODEL_PREFIX}<project id>'", "model")
    return _uuid_or_error(model[len(PROJECT_MODEL_PREFIX):], "model", code="invalid_model")


def format_response_id(value: UUID) -> str:
    return f"{RESPONSE_ID_PREFIX}{value}"


def parse_response_id(value: str) -> UUID | None:
    if not value.startswith(RESPONSE_ID_PREFIX):
        return None
    try:
        return UUID(value[len(RESPONSE_ID_PREFIX):])
    except ValueError:
        return None


def usage_payload(token_usage: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_usage(token_usage)
    raw = token_usage if isinstance(token_usage, dict) else {}
    input_details = raw.get("input_tokens_details") if isinstance(raw.get("input_tokens_details"), dict) else {}
    output_details = raw.get("output_tokens_details") if isinstance(raw.get("output_tokens_details"), dict) else {}
    return {
        "input_tokens": normalized.input_tokens or 0,
        "output_tokens": normalized.output_tokens or 0,
        "total_tokens": normalized.total_tokens or 0,
        "input_tokens_details": {"cached_tokens": int(input_details.get("cached_tokens") or 0)},
        "output_tokens_details": {"reasoning_tokens": int(output_details.get("reasoning_tokens") or 0)},
    }


def citation_payload(citation: Any, *, channel: Channel) -> dict[str, Any]:
    """Citation detail returned as `nomosmart:citation`; the public copy stays the stable public shape."""

    data = citation.model_dump(mode="json") if hasattr(citation, "model_dump") else dict(citation)
    if channel == "public":
        # Same public shape as before CHG-434; internal canonical indexes (chunk_index) stay private (CHG-275).
        keys = ("document_id", "document_version_id", "chunk_id", "title", "score", "excerpt", "content_type", "page", "source_mapping", "index_name")
        return {key: data.get(key) for key in keys}
    return {key: value for key, value in data.items() if key not in {"generation_text", "raw_markdown"}}


def citation_annotations(answer: str, citations: list[Any], *, project_id: UUID, frontend_origin: str, channel: Channel) -> list[dict[str, Any]]:
    """One `url_citation` per marker `[n]` in the compact answer, pointing at citation n."""

    annotations: list[dict[str, Any]] = []
    for match in _CITATION_MARKER.finditer(answer or ""):
        ordinal = int(match.group(1))
        if ordinal < 1 or ordinal > len(citations):
            continue
        detail = citation_payload(citations[ordinal - 1], channel=channel)
        annotations.append({
            "type": "url_citation",
            "url": f"{frontend_origin.rstrip('/')}/project/{project_id}/knowledge/{detail['document_id']}",
            "start_index": match.start(),
            "end_index": match.end(),
            "title": detail.get("title") or "",
            "nomosmart:citation": detail,
        })
    return annotations


def build_response(
    *,
    response_uuid: UUID,
    request: CreateRequest,
    created_at: datetime,
    status: Literal["in_progress", "completed", "failed", "incomplete"],
    answer: str | None,
    annotations: list[dict[str, Any]] | None,
    token_usage: dict[str, Any] | None,
    extensions: dict[str, Any] | None = None,
    error: AppError | None = None,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    if answer is not None:
        output.append(_message_item(response_uuid, answer, annotations or [], "completed" if status == "completed" else "incomplete"))
    return {
        "id": format_response_id(response_uuid),
        "object": "response",
        "created_at": int(created_at.timestamp()),
        "completed_at": int(completed_at.timestamp()) if completed_at else None,
        "status": status,
        "incomplete_details": {"reason": "interrupted"} if status == "incomplete" else None,
        "model": request.model,
        "previous_response_id": request.previous_response_id,
        "instructions": None,
        "output": output,
        "error": {"code": error.code, "message": error.message} if error else None,
        "tools": [],
        "tool_choice": "auto",
        "truncation": request.truncation or "auto",
        "parallel_tool_calls": False,
        "text": {"format": {"type": "text"}},
        "top_p": None,
        "presence_penalty": None,
        "frequency_penalty": None,
        "top_logprobs": None,
        "temperature": None,
        "reasoning": None,
        "usage": usage_payload(token_usage) if status != "in_progress" else None,
        "max_output_tokens": None,
        "max_tool_calls": None,
        "store": True,
        "background": False,
        "service_tier": "default",
        "metadata": request.metadata,
        "safety_identifier": None,
        "prompt_cache_key": None,
        **(extensions or {}),
    }


def answer_extensions(
    *,
    request_id: str | None,
    answer_status: str,
    selected_document_version_ids: list[UUID] | set[UUID],
    system_prompt_source: str | None,
    system_prompt_version_id: UUID | None,
    system_prompt_content_hash: str | None,
    llm_model_id: UUID | None,
    latency_ms: int | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "nomosmart:request_id": request_id,
        "nomosmart:answer_status": answer_status,
        "nomosmart:selected_document_version_ids": [str(item) for item in sorted(selected_document_version_ids, key=str)],
        "nomosmart:system_prompt": {
            "source": system_prompt_source,
            "version_id": str(system_prompt_version_id) if system_prompt_version_id else None,
            "content_hash": system_prompt_content_hash,
        },
        "nomosmart:llm_model_id": str(llm_model_id) if llm_model_id else None,
        "nomosmart:latency_ms": latency_ms,
        **(extra or {}),
    }


def error_type(status_code: int) -> str:
    return {
        400: "invalid_request", 401: "authentication_error", 403: "permission_error", 404: "not_found",
        409: "conflict", 422: "invalid_request", 429: "too_many_requests", 502: "model_error", 503: "service_unavailable",
    }.get(status_code, "server_error" if status_code >= 500 else "invalid_request")


def error_payload(exc: AppError, request_id: str | None) -> dict[str, Any]:
    param = exc.details.get("param") if isinstance(exc.details, dict) else None
    return {
        "error": {"type": error_type(exc.status_code), "code": exc.code, "message": exc.message, "param": param},
        "nomosmart:request_id": request_id,
    }


def log_stream_finished(request: Any, *, project_id: UUID | None, result: StreamResult, started: float, error_code: str | None = None) -> None:
    """CHG-440 PUBIDEM440-006: one safe log line when a response stream ends.

    The HTTP status of a stream is already 200 when the request log is written, so the real outcome
    is recorded here. Only identifiers, the outcome and the error code are logged, never content.
    """
    stream_logger.log(
        logging.INFO if result == "completed" else logging.WARNING,
        "response_stream_finished",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "path": request.url.path,
            "project_id": str(project_id) if project_id else None,
            "result": result,
            "error_code": error_code,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
        },
    )


def is_open_responses_path(path: str) -> bool:
    return path in {"/api/public/v1/responses", "/api/v1/responses"} or path.startswith("/api/public/v1/responses/")


class ResponseEventStream:
    """Open Responses SSE events for one assistant message (ORESP434-005)."""

    def __init__(self, response_uuid: UUID) -> None:
        self.response_uuid = response_uuid
        self.item_id = f"msg_{response_uuid.hex}"
        self._sequence = 0

    def _event(self, event_type: str, payload: dict[str, Any]) -> str:
        self._sequence += 1
        data = {"type": event_type, "sequence_number": self._sequence, **payload}
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    def start(self, response: dict[str, Any]) -> Iterator[str]:
        yield self._event("response.created", {"response": response})
        yield self._event("response.in_progress", {"response": response})
        yield self._event("response.output_item.added", {"output_index": 0, "item": _message_item(self.response_uuid, "", [], "in_progress", content=False)})
        yield self._event("response.content_part.added", {"item_id": self.item_id, "output_index": 0, "content_index": 0, "part": _text_part("", [])})

    def delta(self, text: str) -> str:
        return self._event("response.output_text.delta", {"item_id": self.item_id, "output_index": 0, "content_index": 0, "delta": text, "logprobs": []})

    def finish(self, response: dict[str, Any]) -> Iterator[str]:
        message = response["output"][0]
        part = message["content"][0]
        for index, annotation in enumerate(part["annotations"]):
            yield self._event("response.output_text.annotation.added", {"item_id": self.item_id, "output_index": 0, "content_index": 0, "annotation_index": index, "annotation": annotation})
        yield self._event("response.output_text.done", {"item_id": self.item_id, "output_index": 0, "content_index": 0, "text": part["text"], "logprobs": []})
        yield self._event("response.content_part.done", {"item_id": self.item_id, "output_index": 0, "content_index": 0, "part": part})
        yield self._event("response.output_item.done", {"output_index": 0, "item": message})
        yield self._event("response.completed", {"response": response})

    def fail(self, response: dict[str, Any], exc: AppError, request_id: str | None) -> Iterator[str]:
        body = error_payload(exc, request_id)
        yield self._event("error", {"error": body["error"], "nomosmart:request_id": request_id})
        yield self._event("response.failed", {"response": response})


def _message_item(response_uuid: UUID, answer: str, annotations: list[dict[str, Any]], status: str, *, content: bool = True) -> dict[str, Any]:
    return {
        "type": "message",
        "id": f"msg_{response_uuid.hex}",
        "role": "assistant",
        "status": status,
        "phase": "final_answer",
        "content": [_text_part(answer, annotations)] if content else [],
    }


def _text_part(text: str, annotations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "output_text", "text": text, "annotations": annotations, "logprobs": []}


def _parse_input(value: Any) -> str:
    if isinstance(value, str):
        question = value
    elif isinstance(value, list):
        if len(value) != 1 or not isinstance(value[0], dict):
            raise invalid("unsupported_input_item", "input must be text or exactly one user message", "input")
        item = value[0]
        if item.get("type", "message") != "message" or item.get("role") != "user":
            raise invalid("unsupported_input_item", "Only a single user message is supported", "input")
        content = item.get("content")
        if isinstance(content, str):
            question = content
        elif isinstance(content, list) and content and all(isinstance(part, dict) and part.get("type") == "input_text" and isinstance(part.get("text"), str) for part in content):
            question = "\n".join(part["text"] for part in content)
        else:
            raise invalid("unsupported_input_item", "Message content must be text (input_text)", "input")
    else:
        raise invalid("missing_required_parameter", "input is required", "input")
    if not question.strip():
        raise invalid("invalid_input", "input must not be empty", "input")
    if len(question) > QUESTION_MAX_LENGTH:
        raise invalid("input_too_long", f"input is limited to {QUESTION_MAX_LENGTH} characters", "input")
    return question


def _parse_metadata(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 16 or not all(
        isinstance(key, str) and len(key) <= 64 and isinstance(item, str) and len(item) <= 512 for key, item in value.items()
    ):
        raise invalid("invalid_metadata", "metadata allows at most 16 text pairs (key 64, value 512 characters)", "metadata")
    return dict(value)


def _parse_top_k(value: Any) -> int:
    if value is None:
        return 5
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 20:
        raise invalid("invalid_top_k", "nomosmart:top_k must be an integer from 1 to 20", "nomosmart:top_k")
    return value


def _uuid_list(value: Any, param: str) -> list[UUID] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise invalid("invalid_type", f"{param} must be a list of ids", param)
    return [_uuid_or_error(item, param) for item in value]


def _uuid_or_error(value: Any, param: str, *, code: str = "invalid_id") -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise invalid(code, f"{param} must be a valid id", param) from exc


def _validation_param(prefix: str, exc: ValidationError) -> str:
    errors = exc.errors()
    location = ".".join(str(part) for part in errors[0]["loc"]) if errors else ""
    return f"{prefix}.{location}" if location else prefix
