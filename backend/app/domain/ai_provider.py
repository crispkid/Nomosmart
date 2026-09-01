from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.api.schemas import ProjectChatCitation
from app.core.config import Settings, get_settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.security.secrets import resolve_runtime_secret
from app.db.models import AIModel
from app.domain.system_prompts import SystemPromptResolution, backend_default_prompt


PROMPT_VERSION = "rag-provider-v1"


@dataclass(frozen=True)
class AIProviderResult:
    answer: str
    prompt_version: str
    token_usage: dict[str, Any] | None = None
    system_prompt_source: str | None = None
    system_prompt_version_id: UUID | None = None
    system_prompt_content_hash: str | None = None
    system_prompt_layers: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class AIProviderStreamChunk:
    text: str = ""
    token_usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class AIProviderStream:
    chunks: AsyncIterator[AIProviderStreamChunk]
    prompt_version: str
    system_prompt_source: str | None = None
    system_prompt_version_id: UUID | None = None
    system_prompt_content_hash: str | None = None
    system_prompt_layers: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class AIJudgeResult:
    score: float | None
    reason: str
    token_usage: dict[str, Any] | None = None
    system_prompt_source: str | None = None
    system_prompt_version_id: UUID | None = None
    system_prompt_content_hash: str | None = None
    system_prompt_layers: list[dict[str, Any]] | None = None


def generate_rag_answer(
    *,
    question: str,
    citations: list[ProjectChatCitation],
    model: AIModel | None,
    settings: Settings | None = None,
    system_prompt: SystemPromptResolution | None = None,
) -> AIProviderResult:
    resolved_prompt = system_prompt or backend_default_prompt("Chat")
    if not citations:
        return _provider_result(answer="無法確認，找不到足夠依據。", token_usage=None, system_prompt=resolved_prompt)
    if model is None:
        raise AppError("model_configuration_required", "An active Chat Model is required to generate an answer", status_code=409)
    prompt = _build_citation_bound_prompt(question, citations, resolved_prompt.content)
    provider = model.provider.strip().lower()
    effective_settings = settings or get_settings()
    if provider == "openai" and _uses_openai_responses_api(model):
        payload = _invoke_openai_responses(model, prompt, effective_settings)
        return _provider_result(answer=_openai_responses_answer(payload), token_usage=payload.get("usage"), system_prompt=resolved_prompt)
    if provider in {"openai", "vllm", "custom"}:
        payload = _invoke_openai_compatible(model, prompt, effective_settings)
        return _provider_result(answer=_openai_answer(payload), token_usage=payload.get("usage"), system_prompt=resolved_prompt)
    if provider == "ollama":
        payload = _invoke_ollama(model, prompt, effective_settings)
        return _provider_result(answer=_ollama_answer(payload), token_usage=_ollama_usage(payload), system_prompt=resolved_prompt)
    if provider == "gemini":
        payload = _invoke_gemini(model, prompt, effective_settings)
        return _provider_result(answer=_gemini_answer(payload), token_usage=_gemini_usage(payload), system_prompt=resolved_prompt)
    if provider in {"claude", "anthropic"}:
        payload = _invoke_claude(model, prompt, effective_settings)
        return _provider_result(answer=_claude_answer(payload), token_usage=_claude_usage(payload), system_prompt=resolved_prompt)
    raise AppError("model_provider_unsupported", "Chat Model provider is not supported for RAG generation", status_code=422, details={"provider": model.provider})


def stream_rag_answer(
    *,
    question: str,
    citations: list[ProjectChatCitation],
    model: AIModel | None,
    settings: Settings | None = None,
    system_prompt: SystemPromptResolution | None = None,
) -> AIProviderStream:
    resolved_prompt = system_prompt or backend_default_prompt("Chat")
    if not citations:
        async def no_answer() -> AsyncIterator[AIProviderStreamChunk]:
            yield AIProviderStreamChunk(text="無法確認，找不到足夠依據。")

        chunks = no_answer()
    else:
        if model is None:
            raise AppError("model_configuration_required", "An active Chat Model is required to generate an answer", status_code=409)
        messages = _build_citation_bound_prompt(question, citations, resolved_prompt.content)
        chunks = _stream_provider(model, messages, settings or get_settings())
    return AIProviderStream(
        chunks=chunks,
        prompt_version=PROMPT_VERSION,
        system_prompt_source=resolved_prompt.source,
        system_prompt_version_id=resolved_prompt.version_id,
        system_prompt_content_hash=resolved_prompt.content_hash,
        system_prompt_layers=resolved_prompt.metadata(),
    )


async def _stream_provider(model: AIModel, messages: list[dict[str, str]], settings: Settings) -> AsyncIterator[AIProviderStreamChunk]:
    provider = model.provider.strip().lower()
    config = model.config or {}
    headers = _auth_headers(model, settings)
    if provider == "openai" and _uses_openai_responses_api(model):
        body: dict[str, Any] = {
            "model": _model_name(model),
            "instructions": messages[0]["content"],
            "input": messages[1]["content"],
            "max_output_tokens": _int(config.get("max_output_tokens") or config.get("max_tokens"), default=1024),
            "stream": True,
        }
        async for chunk in _stream_sse_json(_openai_responses_url(config.get("base_url") or model.endpoint), body, headers, model, "responses"):
            yield chunk
        return
    if provider in {"openai", "vllm", "custom"}:
        default_url = "https://api.openai.com/v1" if provider == "openai" else ""
        base_url = _string(config.get("base_url") or model.endpoint or default_url).rstrip("/")
        if not base_url:
            raise AppError("model_endpoint_required", "Chat Model endpoint is required", status_code=422)
        body = {
            "model": _model_name(model),
            "messages": messages,
            "temperature": _float(config.get("temperature"), default=0.1),
            "max_tokens": _int(config.get("max_tokens"), default=1024),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        async for chunk in _stream_sse_json(f"{base_url}/chat/completions", body, headers, model, "openai-chat"):
            yield chunk
        return
    if provider == "ollama":
        base_url = _string(config.get("base_url") or model.endpoint).rstrip("/")
        if not base_url:
            raise AppError("model_endpoint_required", "Ollama Chat Model endpoint is required", status_code=422)
        body = {"model": _model_name(model), "messages": messages, "stream": True}
        options = {key: config[key] for key in ("temperature", "top_p", "num_predict") if key in config}
        if options:
            body["options"] = options
        async for chunk in _stream_ndjson(f"{base_url}/api/chat", body, {}, model):
            yield chunk
        return
    if provider == "gemini":
        base_url = _string(config.get("base_url") or model.endpoint or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        api_key = _resolve_api_key(model, settings)
        if api_key:
            headers["x-goog-api-key"] = api_key
        body = {
            "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
            "contents": [{"role": "user", "parts": [{"text": messages[1]["content"]}]}],
            "generationConfig": {"temperature": _float(config.get("temperature"), default=0.1), "maxOutputTokens": _int(config.get("max_tokens"), default=1024)},
        }
        url = f"{base_url}/models/{urllib.parse.quote(_model_name(model), safe='')}:streamGenerateContent?alt=sse"
        async for chunk in _stream_sse_json(url, body, headers, model, "gemini"):
            yield chunk
        return
    if provider in {"claude", "anthropic"}:
        base_url = _string(config.get("base_url") or model.endpoint or "https://api.anthropic.com/v1").rstrip("/")
        headers["anthropic-version"] = _string(config.get("anthropic_version") or "2023-06-01")
        body = {
            "model": _model_name(model),
            "system": messages[0]["content"],
            "messages": [{"role": "user", "content": messages[1]["content"]}],
            "temperature": _float(config.get("temperature"), default=0.1),
            "max_tokens": _int(config.get("max_tokens"), default=1024),
            "stream": True,
        }
        async for chunk in _stream_sse_json(f"{base_url}/messages", body, headers, model, "anthropic"):
            yield chunk
        return
    raise AppError("model_provider_unsupported", "Chat Model provider is not supported for RAG generation", status_code=422, details={"provider": model.provider})


async def _stream_sse_json(url: str, body: dict[str, Any], headers: dict[str, str], model: AIModel, protocol: str) -> AsyncIterator[AIProviderStreamChunk]:
    config = model.config or {}
    try:
        async with httpx.AsyncClient(verify=_verify_tls(config), timeout=_timeout(config), trust_env=False, follow_redirects=False) as client:
            async with client.stream("POST", url, json=body, headers=headers) as response:
                if response.status_code >= 400:
                    raise AppError("model_invocation_failed", "Chat Model provider rejected the request", status_code=502, details={"status_code": response.status_code})
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise AppError("model_stream_invalid", "Chat Model stream returned invalid JSON", status_code=502) from exc
                    text, usage = _stream_payload(protocol, payload)
                    if text or usage:
                        yield AIProviderStreamChunk(text=text, token_usage=usage)
    except AppError:
        raise
    except (httpx.HTTPError, TimeoutError) as exc:
        raise AppError("model_provider_unavailable", "Chat Model provider is unavailable", status_code=503) from exc


async def _stream_ndjson(url: str, body: dict[str, Any], headers: dict[str, str], model: AIModel) -> AsyncIterator[AIProviderStreamChunk]:
    config = model.config or {}
    try:
        async with httpx.AsyncClient(verify=_verify_tls(config), timeout=_timeout(config), trust_env=False, follow_redirects=False) as client:
            async with client.stream("POST", url, json=body, headers=headers) as response:
                if response.status_code >= 400:
                    raise AppError("model_invocation_failed", "Chat Model provider rejected the request", status_code=502, details={"status_code": response.status_code})
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise AppError("model_stream_invalid", "Chat Model stream returned invalid JSON", status_code=502) from exc
                    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
                    usage = _ollama_usage(payload) if payload.get("done") else None
                    text = str(message.get("content") or "")
                    if text or usage:
                        yield AIProviderStreamChunk(text=text, token_usage=usage)
    except AppError:
        raise
    except (httpx.HTTPError, TimeoutError) as exc:
        raise AppError("model_provider_unavailable", "Chat Model provider is unavailable", status_code=503) from exc


def _stream_payload(protocol: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    if protocol == "openai-chat":
        choices = payload.get("choices") or []
        delta = choices[0].get("delta", {}) if choices and isinstance(choices[0], dict) else {}
        return str(delta.get("content") or ""), payload.get("usage")
    if protocol == "responses":
        event_type = str(payload.get("type") or "")
        if event_type == "response.output_text.delta":
            return str(payload.get("delta") or ""), None
        response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
        return "", response.get("usage") if event_type == "response.completed" else None
    if protocol == "gemini":
        candidates = payload.get("candidates") or []
        content = candidates[0].get("content", {}) if candidates and isinstance(candidates[0], dict) else {}
        parts = content.get("parts") or []
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
        return text, payload.get("usageMetadata")
    if protocol == "anthropic":
        delta = payload.get("delta") if isinstance(payload.get("delta"), dict) else {}
        return str(delta.get("text") or ""), delta.get("usage") or payload.get("usage")
    return "", None


def evaluate_rag_answer(
    *,
    question: str,
    answer: str | None,
    expected_answer: str | None,
    expected_keywords: list | None,
    citations: list[ProjectChatCitation],
    model: AIModel,
    settings: Settings | None = None,
    system_prompt: SystemPromptResolution | None = None,
) -> AIJudgeResult:
    resolved_prompt = system_prompt or backend_default_prompt("Judge")
    prompt = _build_judge_prompt(question=question, answer=answer, expected_answer=expected_answer, expected_keywords=expected_keywords, citations=citations, system_prompt=resolved_prompt.content)
    provider = model.provider.strip().lower()
    effective_settings = settings or get_settings()
    if provider == "openai" and _uses_openai_responses_api(model):
        payload = _invoke_openai_responses(model, prompt, effective_settings)
        return _judge_result(_openai_responses_answer(payload), payload.get("usage"), resolved_prompt)
    if provider in {"openai", "vllm", "custom"}:
        payload = _invoke_openai_compatible(model, prompt, effective_settings)
        content = _openai_answer(payload)
        return _judge_result(content, payload.get("usage"), resolved_prompt)
    if provider == "ollama":
        payload = _invoke_ollama(model, prompt, effective_settings)
        return _judge_result(_ollama_answer(payload), _ollama_usage(payload), resolved_prompt)
    if provider == "gemini":
        payload = _invoke_gemini(model, prompt, effective_settings)
        return _judge_result(_gemini_answer(payload), _gemini_usage(payload), resolved_prompt)
    if provider in {"claude", "anthropic"}:
        payload = _invoke_claude(model, prompt, effective_settings)
        return _judge_result(_claude_answer(payload), _claude_usage(payload), resolved_prompt)
    raise AppError("model_provider_unsupported", "Judge Model provider is not supported", status_code=422, details={"provider": model.provider})


def generate_knowledge_tags(
    *,
    text: str,
    model: AIModel,
    max_tags: int = 5,
    settings: Settings | None = None,
    system_prompt: SystemPromptResolution | None = None,
    allow_empty: bool = False,
) -> AIProviderResult:
    resolved_prompt = system_prompt or backend_default_prompt("Chat")
    trimmed = text.strip()
    if not trimmed:
        raise AppError("tagging_text_required", "Text is required for auto tagging", status_code=422)
    prompt = _build_tagging_prompt(trimmed, max_tags, resolved_prompt.content, allow_empty=allow_empty)
    provider = model.provider.strip().lower()
    effective_settings = settings or get_settings()
    if provider == "openai" and _uses_openai_responses_api(model):
        payload = _invoke_openai_responses(model, prompt, effective_settings)
        content = _openai_responses_answer(payload)
        return _provider_result(answer=json.dumps(_parse_tag_result(content, allow_empty=allow_empty), ensure_ascii=False), token_usage=payload.get("usage"), system_prompt=resolved_prompt)
    if provider in {"openai", "vllm", "custom"}:
        payload = _invoke_openai_compatible(model, prompt, effective_settings)
        content = _openai_answer(payload)
        return _provider_result(answer=json.dumps(_parse_tag_result(content, allow_empty=allow_empty), ensure_ascii=False), token_usage=payload.get("usage"), system_prompt=resolved_prompt)
    if provider == "ollama":
        payload = _invoke_ollama(model, prompt, effective_settings)
        content = _ollama_answer(payload)
        return _provider_result(answer=json.dumps(_parse_tag_result(content, allow_empty=allow_empty), ensure_ascii=False), token_usage=_ollama_usage(payload), system_prompt=resolved_prompt)
    if provider == "gemini":
        payload = _invoke_gemini(model, prompt, effective_settings)
        content = _gemini_answer(payload)
        return _provider_result(answer=json.dumps(_parse_tag_result(content, allow_empty=allow_empty), ensure_ascii=False), token_usage=_gemini_usage(payload), system_prompt=resolved_prompt)
    if provider in {"claude", "anthropic"}:
        payload = _invoke_claude(model, prompt, effective_settings)
        content = _claude_answer(payload)
        return _provider_result(answer=json.dumps(_parse_tag_result(content, allow_empty=allow_empty), ensure_ascii=False), token_usage=_claude_usage(payload), system_prompt=resolved_prompt)
    raise AppError("model_provider_unsupported", "Chat Model provider is not supported for auto tagging", status_code=422, details={"provider": model.provider})


def _provider_result(*, answer: str, token_usage: dict[str, Any] | None, system_prompt: SystemPromptResolution) -> AIProviderResult:
    return AIProviderResult(
        answer=answer,
        prompt_version=PROMPT_VERSION,
        token_usage=token_usage,
        system_prompt_source=system_prompt.source,
        system_prompt_version_id=system_prompt.version_id,
        system_prompt_content_hash=system_prompt.content_hash,
        system_prompt_layers=system_prompt.metadata(),
    )


def _build_tagging_prompt(text: str, max_tags: int, system: str, *, allow_empty: bool = False) -> list[dict[str, str]]:
    empty_rule = "；若內容沒有明確重點，請輸出空 JSON 陣列 []" if allow_empty else ""
    user = (
        f"請為以下知識內容產生最多 {max_tags} 個精簡標籤。\n"
        f"規則：只輸出 JSON 陣列；每個元素是 2 到 24 字的標籤文字；不要輸出說明{empty_rule}。\n\n"
        f"內容：\n{text[:12000]}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_tag_result(content: str, *, allow_empty: bool = False) -> list[str]:
    raw = content.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", raw)
        if not match:
            raise AppError("tagging_response_invalid", "Tagging response did not contain a JSON array", status_code=502)
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise AppError("tagging_response_invalid", "Tagging response JSON is invalid", status_code=502) from exc
    if not isinstance(parsed, list):
        raise AppError("tagging_response_invalid", "Tagging response must be a JSON array", status_code=502)
    tags: list[str] = []
    for item in parsed:
        text = str(item).strip()
        if text and text not in tags:
            tags.append(text[:80])
    if not tags and not allow_empty:
        raise AppError("tagging_response_empty", "Tagging response did not contain tags", status_code=502)
    return tags


def _build_citation_bound_prompt(question: str, citations: list[ProjectChatCitation], system: str) -> list[dict[str, str]]:
    sources = []
    for index, citation in enumerate(citations, start=1):
        context = (citation.generation_text or citation.excerpt or "").strip()
        if not context:
            continue
        title = citation.title or f"Document {citation.document_id}"
        heading = " > ".join(citation.heading_path)
        heading_line = f"\nsection={heading}" if heading else ""
        sources.append(f"[{index}] {title}\nversion={citation.document_version_id}\nchunk={citation.chunk_id}{heading_line}\ncontent={context}")
    if not sources:
        raise AppError("retrieval_excerpt_required", "Retrieved citations do not contain answerable excerpts", status_code=409)
    user = "Question:\n" + question.strip() + "\n\nPublished sources:\n" + "\n\n".join(sources)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _build_judge_prompt(*, question: str, answer: str | None, expected_answer: str | None, expected_keywords: list | None, citations: list[ProjectChatCitation], system_prompt: str) -> list[dict[str, str]]:
    citation_text = "\n".join(f"- {citation.title or citation.chunk_id}: {(citation.excerpt or '').strip()}" for citation in citations if citation.excerpt)
    keywords = ", ".join(str(item) for item in expected_keywords or [])
    user = (
        f"Question: {question}\n"
        f"Answer: {answer or ''}\n"
        f"Expected answer: {expected_answer or ''}\n"
        f"Expected keywords: {keywords}\n"
        f"Citations:\n{citation_text}\n"
        "Evaluate whether the answer is grounded in citations and satisfies the expectation."
    )
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user}]


def _invoke_openai_compatible(model: AIModel, messages: list[dict[str, str]], settings: Settings) -> dict[str, Any]:
    config = model.config or {}
    provider = model.provider.strip().lower()
    if provider == "openai":
        base_url = _string(config.get("base_url") or model.endpoint or "https://api.openai.com/v1").rstrip("/")
    else:
        base_url = _string(config.get("base_url") or model.endpoint).rstrip("/")
    if not base_url:
        raise AppError("model_endpoint_required", "Chat Model endpoint is required", status_code=422)
    body = {
        "model": _model_name(model),
        "messages": messages,
        "temperature": _float(config.get("temperature"), default=0.1),
        "max_tokens": _int(config.get("max_tokens"), default=1024),
    }
    return _post_json(
        f"{base_url}/chat/completions",
        body,
        headers=_auth_headers(model, settings),
        timeout_seconds=_timeout(config),
        verify_tls=_verify_tls(config),
    )


def _uses_openai_responses_api(model: AIModel) -> bool:
    config = model.config or {}
    mode = _string(config.get("api_mode") or config.get("api_type") or config.get("endpoint_type")).lower()
    if mode in {"responses", "response"}:
        return True
    configured = _string(config.get("base_url") or model.endpoint).rstrip("/").lower()
    return configured.endswith("/responses")


def _invoke_openai_responses(model: AIModel, messages: list[dict[str, str]], settings: Settings) -> dict[str, Any]:
    config = model.config or {}
    url = _openai_responses_url(config.get("base_url") or model.endpoint)
    body: dict[str, Any] = {
        "model": _model_name(model),
        "instructions": messages[0]["content"],
        "input": messages[1]["content"],
        "max_output_tokens": _int(config.get("max_output_tokens") or config.get("max_tokens"), default=1024),
    }
    temperature = config.get("temperature")
    if temperature is not None:
        body["temperature"] = _float(temperature, default=0.1)
    return _post_json(
        url,
        body,
        headers=_auth_headers(model, settings),
        timeout_seconds=_timeout(config),
        verify_tls=_verify_tls(config),
    )


def _openai_responses_url(value: object) -> str:
    base_url = _string(value).rstrip("/") or "https://api.openai.com/v1"
    return base_url if base_url.lower().endswith("/responses") else f"{base_url}/responses"


def _invoke_ollama(model: AIModel, messages: list[dict[str, str]], _settings: Settings) -> dict[str, Any]:
    config = model.config or {}
    base_url = _string(config.get("base_url") or model.endpoint).rstrip("/")
    if not base_url:
        raise AppError("model_endpoint_required", "Ollama Chat Model endpoint is required", status_code=422)
    body = {"model": _model_name(model), "messages": messages, "stream": False}
    options = {key: config[key] for key in ("temperature", "top_p", "num_predict") if key in config}
    if options:
        body["options"] = options
    return _post_json(f"{base_url}/api/chat", body, timeout_seconds=_timeout(config), verify_tls=_verify_tls(config))


def _invoke_gemini(model: AIModel, messages: list[dict[str, str]], settings: Settings) -> dict[str, Any]:
    config = model.config or {}
    model_name = _model_name(model)
    base_url = _string(config.get("base_url") or model.endpoint or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    api_key = _resolve_api_key(model, settings)
    url = f"{base_url}/models/{urllib.parse.quote(model_name, safe='')}:generateContent"
    headers = {"x-goog-api-key": api_key} if api_key else {}
    body = {
        "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
        "contents": [{"role": "user", "parts": [{"text": messages[1]["content"]}]}],
        "generationConfig": {"temperature": _float(config.get("temperature"), default=0.1), "maxOutputTokens": _int(config.get("max_tokens"), default=1024)},
    }
    return _post_json(url, body, headers=headers, timeout_seconds=_timeout(config), verify_tls=_verify_tls(config))


def _invoke_claude(model: AIModel, messages: list[dict[str, str]], settings: Settings) -> dict[str, Any]:
    config = model.config or {}
    base_url = _string(config.get("base_url") or model.endpoint or "https://api.anthropic.com/v1").rstrip("/")
    headers = _auth_headers(model, settings)
    headers["anthropic-version"] = _string(config.get("anthropic_version") or "2023-06-01")
    body = {
        "model": _model_name(model),
        "system": messages[0]["content"],
        "messages": [{"role": "user", "content": messages[1]["content"]}],
        "temperature": _float(config.get("temperature"), default=0.1),
        "max_tokens": _int(config.get("max_tokens"), default=1024),
    }
    return _post_json(f"{base_url}/messages", body, headers=headers, timeout_seconds=_timeout(config), verify_tls=_verify_tls(config))


def _post_json(
    url: str,
    body: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: int,
    verify_tls: bool,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    context = _ssl_context(verify_tls)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AppError("model_invocation_failed", "Chat Model provider rejected the request", status_code=502, details={"status_code": exc.code}) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AppError("model_provider_unavailable", "Chat Model provider is unavailable", status_code=503) from exc


def _ssl_context(verify_tls: bool) -> ssl.SSLContext | None:
    if not verify_tls:
        return ssl._create_unverified_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        return None


def _auth_headers(model: AIModel, settings: Settings) -> dict[str, str]:
    provider = model.provider.strip().lower()
    api_key = _resolve_api_key(model, settings)
    if not api_key:
        return {}
    if provider in {"claude", "anthropic"}:
        return {"x-api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _resolve_api_key(model: AIModel, settings: Settings) -> str | None:
    if model.api_key_secret_ref:
        return resolve_runtime_secret(settings, model.api_key_secret_ref)
    if model.api_key_encrypted:
        if settings.app_env == "production":
            raise AppError("legacy_model_credential_forbidden", "Legacy model credentials are not permitted in production", status_code=503)
        cipher = EnvelopeCipher(settings.encryption_key_bytes)
        contexts = [f"ai-model:{model.id}", f"ai-model:{model.name}"]
        last_error: AppError | None = None
        for context in contexts:
            try:
                return cipher.decrypt(model.api_key_encrypted, context=context)
            except AppError as exc:
                last_error = exc
        if last_error:
            raise last_error
    return None


def _model_name(model: AIModel) -> str:
    value = _string((model.config or {}).get("model_name") or model.name)
    if not value:
        raise AppError("model_name_required", "Chat Model model_name is required", status_code=422)
    return value


def _openai_answer(payload: dict[str, Any]) -> str:
    try:
        return str(payload["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise AppError("model_response_invalid", "Chat Model response did not contain an answer", status_code=502) from exc


def _openai_responses_answer(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    text_parts: list[str] = []
    for output in payload.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                text_parts.append(content["text"].strip())
    answer = "\n".join(part for part in text_parts if part).strip()
    if answer:
        return answer
    raise AppError("model_response_invalid", "OpenAI Responses API response did not contain an answer", status_code=502)


def _ollama_answer(payload: dict[str, Any]) -> str:
    try:
        return str(payload["message"]["content"]).strip()
    except (KeyError, TypeError) as exc:
        raise AppError("model_response_invalid", "Ollama response did not contain an answer", status_code=502) from exc


def _gemini_answer(payload: dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
        return "\n".join(str(part.get("text", "")).strip() for part in parts if part.get("text")).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise AppError("model_response_invalid", "Gemini response did not contain an answer", status_code=502) from exc


def _claude_answer(payload: dict[str, Any]) -> str:
    try:
        return "\n".join(str(item.get("text", "")).strip() for item in payload["content"] if item.get("type") == "text").strip()
    except (KeyError, TypeError) as exc:
        raise AppError("model_response_invalid", "Claude response did not contain an answer", status_code=502) from exc


def _judge_result(content: str, token_usage: dict[str, Any] | None, system_prompt: SystemPromptResolution) -> AIJudgeResult:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AppError("judge_response_invalid", "Judge Model response did not contain valid JSON", status_code=502) from exc
    try:
        score = max(0.0, min(float(parsed.get("score")), 1.0))
    except (TypeError, ValueError) as exc:
        raise AppError("judge_response_invalid", "Judge Model response did not contain a valid score", status_code=502) from exc
    reason = str(parsed.get("reason") or "Judge Model did not provide a reason").strip()
    return AIJudgeResult(
        score=score,
        reason=reason,
        token_usage=token_usage,
        system_prompt_source=system_prompt.source,
        system_prompt_version_id=system_prompt.version_id,
        system_prompt_content_hash=system_prompt.content_hash,
        system_prompt_layers=system_prompt.metadata(),
    )


def _ollama_usage(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in ("prompt_eval_count", "eval_count", "total_duration") if key in payload}


def _gemini_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
    usage = payload.get("usageMetadata")
    return usage if isinstance(usage, dict) else None


def _claude_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
    usage = payload.get("usage")
    return usage if isinstance(usage, dict) else None


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _timeout(config: dict[str, Any]) -> int:
    return max(1, min(_int(config.get("timeout_seconds") or config.get("timeout"), default=60), 300))


def _verify_tls(config: dict[str, Any]) -> bool:
    raw = config.get("verify_tls")
    return bool(raw) if raw is not None else True
