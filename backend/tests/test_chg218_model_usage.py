from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.api.routes.reports import _model_usage_rows
from app.core.errors import AppError
from app.db.models import AIModel, AIModelUsageEvent
from app.db.session import get_session_factory
from app.domain.model_usage import normalize_usage, record_model_usage, validate_pricing_config


def test_pricing_accepts_zero_and_requires_currency() -> None:
    config = validate_pricing_config({"input_cost_per_million_tokens": 0, "cost_currency": "twd"})
    assert config["input_cost_per_million_tokens"] == "0"
    assert config["cost_currency"] == "TWD"

    with pytest.raises(AppError) as missing_currency:
        validate_pricing_config({"input_cost_per_million_tokens": 0})
    assert missing_currency.value.code == "model_cost_currency_required"

    with pytest.raises(AppError) as negative:
        validate_pricing_config({"input_cost_per_million_tokens": -0.01, "cost_currency": "USD"})
    assert negative.value.code == "model_price_negative"


def test_provider_usage_normalization_is_safe() -> None:
    openai = normalize_usage({"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25, "api_key": "must-not-persist", "response": "must-not-persist"})
    assert (openai.input_tokens, openai.output_tokens, openai.total_tokens) == (20, 5, 25)
    assert "api_key" not in (openai.raw_usage or {})
    assert "response" not in (openai.raw_usage or {})

    gemini = normalize_usage({"promptTokenCount": 11, "candidatesTokenCount": 4, "totalTokenCount": 15})
    assert (gemini.input_tokens, gemini.output_tokens, gemini.total_tokens) == (11, 4, 15)

    ollama = normalize_usage({"prompt_eval_count": 9, "eval_count": 3})
    assert (ollama.input_tokens, ollama.output_tokens, ollama.total_tokens) == (9, 3, 12)


def test_live_usage_ledger_keeps_zero_cost_and_currencies_separate() -> None:
    session_factory = get_session_factory()
    model_id = uuid4()
    with session_factory() as session:
        model = AIModel(
            id=model_id,
            name=f"chg218-{model_id.hex[:12]}",
            model_type="Chat",
            provider="Custom",
            endpoint="https://example.invalid/v1",
            is_active=True,
            is_default=False,
            config={
                "model_name": "chg218-live-ledger",
                "input_cost_per_million_tokens": "0",
                "output_cost_per_million_tokens": "0",
                "cost_currency": "TWD",
            },
            config_version=1,
        )
        session.add(model)
        session.flush()
        estimated = record_model_usage(
            session,
            model=model,
            usage_purpose="chat_test",
            source_channel="chat_test",
            status="success",
            token_usage={"input_tokens": 100, "output_tokens": 50},
        )
        official = record_model_usage(
            session,
            model=model,
            usage_purpose="chat_test",
            source_channel="chat_test",
            status="success",
            token_usage={"input_tokens": 10, "output_tokens": 2, "total_cost": "0", "currency": "USD"},
        )
        session.commit()

        assert estimated.cost_source == "estimated"
        assert estimated.cost_currency == "TWD"
        assert estimated.estimated_cost is not None and float(estimated.estimated_cost) == 0
        assert official.cost_source == "provider_reported"
        assert official.cost_currency == "USD"
        assert official.provider_reported_cost is not None and float(official.provider_reported_cost) == 0

        rows = [row for row in _model_usage_rows(session, None, None, None, 100) if row["model_name"] == "chg218-live-ledger"]
        assert {row["currency"] for row in rows} == {"TWD", "USD"}
        assert len(rows) == 2

        session.execute(delete(AIModelUsageEvent).where(AIModelUsageEvent.model_id == model_id))
        session.execute(delete(AIModel).where(AIModel.id == model_id))
        session.commit()
