from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.api.routes.reports import _model_usage_rows
from app.db.models import AIModel, IntegrationClient
from app.db.session import get_session_factory
from app.domain.model_usage import _resolve_cost, normalize_usage, record_model_usage


def _model(*, model_type: str = "OCR", provider: str = "OpenAI", config: dict | None = None) -> AIModel:
    identity = uuid4()
    return AIModel(
        id=identity,
        name=f"chg278-local-{identity.hex[:10]}",
        model_type=model_type,
        provider=provider,
        endpoint="https://example.invalid/v1",
        is_active=True,
        is_default=False,
        config={"model_name": "chg278-provider-model", **(config or {})},
        config_version=1,
    )


def test_ocr_cost_uses_one_complete_matching_basis() -> None:
    openai = _model(
        config={
            "input_cost_per_million_tokens": "0.2",
            "output_cost_per_million_tokens": "1.2",
            "ocr_cost_per_page": "9",
            "cost_currency": "USD",
        }
    )
    usage = normalize_usage(
        {"input_tokens": 1_000_000, "output_tokens": 500_000, "ocr_pages": 3},
        model_type="OCR",
    )
    official, estimated, currency, source, metadata = _resolve_cost(openai, usage.raw_usage, usage)
    assert official is None
    assert estimated == Decimal("0.80000000")
    assert currency == "USD"
    assert source == "estimated"
    assert metadata == {"method": "configured_pricing", "basis": "token", "components": ["input", "output"]}

    missing_output = _model(
        config={
            "input_cost_per_million_tokens": "0.2",
            "ocr_cost_per_page": "9",
            "cost_currency": "USD",
        }
    )
    assert _resolve_cost(missing_output, usage.raw_usage, usage)[3:] == (
        "unavailable",
        {"reason": "usage_or_matching_price_missing"},
    )

    page_billed = _model(
        provider="Generic HTTP",
        config={"ocr_cost_per_page": "0.2", "cost_currency": "USD"},
    )
    page_usage = normalize_usage({"ocr_pages": 3}, model_type="OCR")
    page_result = _resolve_cost(page_billed, page_usage.raw_usage, page_usage)
    assert page_result[1] == Decimal("0.60000000")
    assert page_result[4] == {"method": "configured_pricing", "basis": "ocr_unit", "components": ["ocr_page"]}

    zero_page_usage = normalize_usage({"input_tokens": 10, "output_tokens": 2, "ocr_pages": 0}, model_type="OCR")
    zero_page_result = _resolve_cost(page_billed, zero_page_usage.raw_usage, zero_page_usage)
    assert zero_page_result[0:4] == (None, None, None, "unavailable")


def test_model_usage_aggregates_clients_and_uses_local_model_name() -> None:
    session_factory = get_session_factory()
    model = _model(
        model_type="Chat",
        config={"input_cost_per_million_tokens": "0", "output_cost_per_million_tokens": "0", "cost_currency": "USD"},
    )
    client_one = IntegrationClient(
        id=uuid4(),
        name=f"chg278-client-one-{uuid4().hex[:8]}",
        status="active",
        api_key_hash=uuid4().hex + uuid4().hex,
        api_key_prefix="nms_test_one",
        api_key_version=1,
        rate_limit_config={},
        lock_version=1,
    )
    client_two = IntegrationClient(
        id=uuid4(),
        name=f"chg278-client-two-{uuid4().hex[:8]}",
        status="active",
        api_key_hash=uuid4().hex + uuid4().hex,
        api_key_prefix="nms_test_two",
        api_key_version=1,
        rate_limit_config={},
        lock_version=1,
    )
    with session_factory() as session:
        session.add_all([model, client_one, client_two])
        session.flush()
        cases = [
            ("success", True, client_one.id),
            ("failed", True, client_two.id),
            ("timeout", True, client_one.id),
            ("failed", False, client_one.id),
            ("partial", False, client_two.id),
        ]
        for status, attempted, client_id in cases:
            record_model_usage(
                session,
                model=model,
                usage_purpose="chat_test",
                source_channel="chat_test",
                status=status,
                attempted=attempted,
                integration_client_id=client_id,
                token_usage={"input_tokens": 10, "output_tokens": 2},
            )
        rows = [row for row in _model_usage_rows(session, None, None, None, 100) if row["ai_model_name"] == model.name]
        assert len(rows) == 1
        row = rows[0]
        assert row["model_name"] == "chg278-provider-model"
        assert row["call_count"] == 3
        assert row["success_count"] == 1
        assert row["failure_count"] == 2
        assert row["error_rate"] == 0.66667
        assert "integration_client_id" not in row
        assert "api_key_prefix" not in row
        session.rollback()
