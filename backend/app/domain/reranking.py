"""Rerank model calls (CHG-486 RERANK486-001).

A rerank model scores each (question, chunk text) pair. Two common `/rerank` wire formats are supported:

- `cohere` (default; vLLM, Cohere, Jina and other compatible servers):
  `{"model", "query", "documents", "top_n"}` -> `{"results": [{"index", "relevance_score"}]}`
- `tei` (Hugging Face Text Embeddings Inference): `{"query", "texts"}` -> `[{"index", "score"}]`

The model's `config.rerank_protocol` picks the request shape; either response shape is accepted.
Scores outside 0..1 (raw logits) are mapped with a sigmoid so every score is a 0..1 relevance.
"""
from __future__ import annotations

import math
from typing import Any

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import AIModel
from app.domain.model_credentials import resolve_model_credential
from app.integrations.provider_http import ProviderRejectedError, ProviderUnavailableError, post_provider_json

RERANK_PROTOCOLS = ("cohere", "tei")
RERANK_PROVIDERS = ("vllm", "custom")
MAX_RERANK_TEXT_CHARS = 4000


def rerank_url(endpoint: str | None) -> str:
    base = (endpoint or "").strip().rstrip("/")
    if not base:
        raise AppError("model_endpoint_required", "Rerank model endpoint is required", status_code=422)
    return base if base.endswith("/rerank") else f"{base}/rerank"


def model_endpoint(model: AIModel) -> str | None:
    config = model.config or {}
    return model.endpoint or config.get("base_url") or config.get("endpoint")


def rerank_scores(model: AIModel, query: str, texts: list[str], settings: Settings | None = None) -> list[float]:
    """Return one 0..1 score per text, in input order. Raises AppError when the provider fails."""
    if not texts:
        return []
    settings = settings or get_settings()
    config = model.config or {}
    protocol = str(config.get("rerank_protocol") or "cohere").strip().lower()
    if protocol not in RERANK_PROTOCOLS:
        raise AppError("rerank_protocol_invalid", "Rerank protocol is invalid", status_code=422)
    bounded = [text[:MAX_RERANK_TEXT_CHARS] for text in texts]
    if protocol == "tei":
        body: dict[str, Any] = {"query": query, "texts": bounded, "raw_scores": False, "truncate": True}
    else:
        body = {"model": str(config.get("model_name") or model.name), "query": query, "documents": bounded, "top_n": len(bounded)}
    headers = {}
    api_key = resolve_model_credential(settings, model)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    timeout = max(1, min(int(config.get("timeout_seconds") or 30), 300))
    verify_tls = bool(config["verify_tls"]) if config.get("verify_tls") is not None else True
    try:
        payload = post_provider_json(rerank_url(model_endpoint(model)), body, headers=headers, timeout_seconds=timeout, verify_tls=verify_tls)
    except ProviderRejectedError as exc:
        raise AppError("rerank_failed", "Rerank model provider rejected the request", status_code=502, details={"status_code": exc.status_code}) from exc
    except ProviderUnavailableError as exc:
        raise AppError("rerank_failed", "Rerank model provider is unavailable", status_code=503) from exc
    return normalize_scores(parse_rerank_response(payload, len(bounded)))


def parse_rerank_response(payload: Any, count: int) -> list[float]:
    items = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise AppError("rerank_failed", "Rerank model response is invalid", status_code=502)
    scores: list[float | None] = [None] * count
    for item in items:
        if not isinstance(item, dict):
            raise AppError("rerank_failed", "Rerank model response is invalid", status_code=502)
        index = item.get("index")
        score = item.get("relevance_score", item.get("score"))
        if type(index) is not int or not 0 <= index < count or type(score) not in (int, float) or not math.isfinite(score):
            raise AppError("rerank_failed", "Rerank model response is invalid", status_code=502)
        scores[index] = float(score)
    if any(score is None for score in scores):
        raise AppError("rerank_failed", "Rerank model response is incomplete", status_code=502)
    return [float(score) for score in scores]  # type: ignore[arg-type]


def normalize_scores(scores: list[float]) -> list[float]:
    """RERANK486-001: scores already in 0..1 are kept; otherwise every score is mapped with a sigmoid."""
    if all(0.0 <= score <= 1.0 for score in scores):
        return scores
    return [1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, score)))) for score in scores]
