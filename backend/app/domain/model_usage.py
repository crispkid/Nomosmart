from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AIModel, AIModelUsageEvent


PRICING_KEYS = (
    "input_cost_per_million_tokens",
    "output_cost_per_million_tokens",
    "embedding_cost_per_million_tokens",
    "ocr_cost_per_page",
    "ocr_cost_per_image",
)
_SAFE_RAW_USAGE_KEYS = {
    "input_tokens", "output_tokens", "total_tokens", "prompt_tokens",
    "completion_tokens", "promptTokenCount", "candidatesTokenCount",
    "totalTokenCount", "prompt_eval_count", "eval_count", "embedding_tokens",
    "ocr_pages", "ocr_images", "pages", "images", "vector_count",
    "chunk_count", "cost", "total_cost", "cost_currency", "currency",
}


@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    embedding_tokens: int | None = None
    ocr_pages: int | None = None
    ocr_images: int | None = None
    vector_count: int | None = None
    chunk_count: int | None = None
    raw_usage: dict[str, Any] | None = None


def validate_pricing_config(config: dict[str, object]) -> dict[str, object]:
    normalized = dict(config)
    configured = False
    for key in PRICING_KEYS:
        value = normalized.get(key)
        if value in (None, ""):
            normalized.pop(key, None)
            continue
        amount = _decimal(value, field=key)
        if amount < 0:
            raise AppError("model_price_negative", "Model pricing cannot be negative", status_code=422, details={"field": key})
        normalized[key] = str(amount)
        configured = True
    currency_value = normalized.get("cost_currency")
    currency = str(currency_value or "").strip().upper()
    if configured and not _valid_currency(currency):
        raise AppError("model_cost_currency_required", "A valid ISO 4217 currency is required when pricing is configured", status_code=422)
    if currency:
        if not _valid_currency(currency):
            raise AppError("model_cost_currency_invalid", "Model cost currency must be a three-letter ISO 4217 code", status_code=422)
        normalized["cost_currency"] = currency
    else:
        normalized.pop("cost_currency", None)
    return normalized


def normalize_usage(raw: dict[str, Any] | None, *, model_type: str | None = None, vector_count: int | None = None, chunk_count: int | None = None) -> NormalizedUsage:
    usage = raw if isinstance(raw, dict) else {}
    input_tokens = _first_int(usage, "input_tokens", "prompt_tokens", "promptTokenCount", "prompt_eval_count")
    output_tokens = _first_int(usage, "output_tokens", "completion_tokens", "candidatesTokenCount", "eval_count")
    total_tokens = _first_int(usage, "total_tokens", "totalTokenCount")
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    embedding_tokens = _first_int(usage, "embedding_tokens")
    if embedding_tokens is None and (model_type or "").lower() == "embedding":
        embedding_tokens = total_tokens or input_tokens
    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        embedding_tokens=embedding_tokens,
        ocr_pages=_first_int(usage, "ocr_pages", "pages"),
        ocr_images=_first_int(usage, "ocr_images", "images"),
        vector_count=vector_count if vector_count is not None else _first_int(usage, "vector_count"),
        chunk_count=chunk_count if chunk_count is not None else _first_int(usage, "chunk_count"),
        raw_usage={key: value for key, value in usage.items() if key in _SAFE_RAW_USAGE_KEYS and isinstance(value, (str, int, float, bool))},
    )


def record_model_usage(
    session: Session,
    *,
    model: AIModel,
    usage_purpose: str,
    source_channel: str,
    status: str,
    token_usage: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    error_code: str | None = None,
    attempted: bool = True,
    attempt_number: int = 1,
    correlation_id: str | None = None,
    project_id: UUID | None = None,
    document_id: UUID | None = None,
    document_version_id: UUID | None = None,
    pipeline_run_id: UUID | None = None,
    pipeline_step_id: UUID | None = None,
    chat_record_id: UUID | None = None,
    validation_run_id: UUID | None = None,
    validation_run_item_id: UUID | None = None,
    public_api_request_log_id: UUID | None = None,
    integration_client_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    vector_count: int | None = None,
    chunk_count: int | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> AIModelUsageEvent:
    normalized = normalize_usage(token_usage, model_type=model.model_type, vector_count=vector_count, chunk_count=chunk_count)
    provider_cost, estimated_cost, currency, cost_source, cost_metadata = _resolve_cost(model, token_usage, normalized)
    event = AIModelUsageEvent(
        id=uuid4(),
        model_id=model.id,
        model_type=model.model_type,
        provider=model.provider,
        project_id=project_id,
        document_id=document_id,
        document_version_id=document_version_id,
        pipeline_run_id=pipeline_run_id,
        pipeline_step_id=pipeline_step_id,
        chat_record_id=chat_record_id,
        validation_run_id=validation_run_id,
        validation_run_item_id=validation_run_item_id,
        public_api_request_log_id=public_api_request_log_id,
        integration_client_id=integration_client_id,
        actor_user_id=actor_user_id,
        source_channel=source_channel,
        usage_purpose=usage_purpose,
        status=status,
        error_code=error_code,
        attempted=attempted,
        attempt_number=max(1, attempt_number),
        correlation_id=correlation_id,
        input_tokens=normalized.input_tokens,
        output_tokens=normalized.output_tokens,
        total_tokens=normalized.total_tokens,
        embedding_tokens=normalized.embedding_tokens,
        ocr_pages=normalized.ocr_pages,
        ocr_images=normalized.ocr_images,
        vector_count=normalized.vector_count,
        chunk_count=normalized.chunk_count,
        raw_usage=normalized.raw_usage or {},
        provider_reported_cost=provider_cost,
        estimated_cost=estimated_cost,
        cost_currency=currency,
        cost_source=cost_source,
        cost_metadata=cost_metadata,
        latency_ms=max(0, latency_ms) if latency_ms is not None else None,
        metadata_=metadata or {},
        created_at=created_at or datetime.now(UTC),
    )
    session.add(event)
    session.flush()
    return event


def _resolve_cost(model: AIModel, raw: dict[str, Any] | None, usage: NormalizedUsage) -> tuple[Decimal | None, Decimal | None, str | None, str, dict[str, Any]]:
    raw_usage = raw if isinstance(raw, dict) else {}
    provider_amount = _optional_decimal(raw_usage.get("total_cost", raw_usage.get("cost")))
    provider_currency = str(raw_usage.get("cost_currency") or raw_usage.get("currency") or "").strip().upper()
    if provider_amount is not None and provider_amount >= 0 and _valid_currency(provider_currency):
        return _money(provider_amount), None, provider_currency, "provider_reported", {"method": "provider_reported"}

    config = model.config if isinstance(model.config, dict) else {}
    currency = str(config.get("cost_currency") or "").strip().upper()
    if not _valid_currency(currency):
        return None, None, None, "unavailable", {"reason": "pricing_or_currency_missing"}

    model_type = (model.model_type or "").strip().lower()
    provider = (model.provider or "").strip().lower()
    basis = "token"
    if model_type == "embedding":
        component_specs = (
            ("embedding", usage.embedding_tokens, config.get("embedding_cost_per_million_tokens"), True),
        )
        basis = "embedding"
    elif (
        model_type == "ocr"
        and provider != "openai"
        and _has_positive_ocr_unit(usage)
        and _has_configured_ocr_unit_price(config)
    ):
        component_specs = (
            ("ocr_page", usage.ocr_pages, config.get("ocr_cost_per_page"), False),
            ("ocr_image", usage.ocr_images, config.get("ocr_cost_per_image"), False),
        )
        basis = "ocr_unit"
    else:
        component_specs = (
            ("input", usage.input_tokens, config.get("input_cost_per_million_tokens"), True),
            ("output", usage.output_tokens, config.get("output_cost_per_million_tokens"), True),
        )
    components = _complete_positive_components(component_specs)
    if components is None:
        return None, None, None, "unavailable", {"reason": "usage_or_matching_price_missing"}
    return None, _money(sum((value for _, value in components), Decimal("0"))), currency, "estimated", {
        "method": "configured_pricing",
        "basis": basis,
        "components": [name for name, _ in components],
    }


def _has_positive_ocr_unit(usage: NormalizedUsage) -> bool:
    return (usage.ocr_pages or 0) > 0 or (usage.ocr_images or 0) > 0


def _has_configured_ocr_unit_price(config: dict[str, object]) -> bool:
    return any(
        _optional_decimal(config.get(key)) is not None
        for key in ("ocr_cost_per_page", "ocr_cost_per_image")
    )


def _complete_positive_components(
    specs: tuple[tuple[str, int | None, object, bool], ...],
) -> list[tuple[str, Decimal]] | None:
    positive_specs = [spec for spec in specs if (spec[1] or 0) > 0]
    if not positive_specs:
        return None
    components: list[tuple[str, Decimal]] = []
    for name, count, raw_price, per_million in positive_specs:
        amount = _optional_decimal(raw_price)
        if amount is None or amount < 0 or count is None:
            return None
        value = Decimal(count) * amount
        if per_million:
            value /= Decimal("1000000")
        components.append((name, value))
    return components


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AppError("model_price_invalid", "Model pricing must be numeric", status_code=422, details={"field": field}) from exc


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _valid_currency(value: str) -> bool:
    return len(value) == 3 and value.isascii() and value.isalpha() and value.isupper()


def _first_int(values: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return None
