from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from app.api.routes import models as model_routes
from app.api.schemas import AIModelUpdate
from app.core.errors import AppError
from app.db.models import AIModel, DocumentVersion
from app.domain import ai_provider, extraction_pipeline
from app.domain.document_imports import _require_ocr_model_credential


def _ocr_model(config: dict[str, object] | None = None) -> AIModel:
    return AIModel(
        id=uuid4(),
        name="nomosmart-ocr",
        model_type="OCR",
        provider="OpenAI",
        endpoint="https://api.openai.com/v1",
        api_key_encrypted="ciphertext-not-a-secret",
        config={"model_name": "gpt-5.6-luna", **(config or {})},
    )


def test_ocr_responses_payload_omits_implicit_temperature_but_preserves_explicit_value() -> None:
    version = DocumentVersion(original_file_name="policy.pdf", canonical_extension=".pdf")
    payload = extraction_pipeline._openai_ocr_payload(
        _ocr_model(),
        version,
        [("policy.pdf", "application/pdf", b"%PDF-contract")],
        "",
    )
    assert payload["model"] == "gpt-5.6-luna"
    assert payload["max_output_tokens"] == 4096
    assert "temperature" not in payload
    assert payload["input"][1]["content"][1]["type"] == "input_file"

    explicit = extraction_pipeline._openai_ocr_payload(
        _ocr_model({"temperature": 0.25, "max_output_tokens": 2048}),
        version,
        [("page.png", "image/png", b"image")],
        "",
    )
    assert explicit["temperature"] == 0.25
    assert explicit["max_output_tokens"] == 2048
    assert explicit["input"][1]["content"][1]["type"] == "input_image"


def test_provider_error_diagnostics_are_strictly_allowlisted() -> None:
    provider_body = b'{"error":{"message":"sensitive echoed document text","type":"invalid_request_error","code":"unsupported_parameter","param":"temperature","authorization":"Bearer secret"}}'
    error = HTTPError("https://api.openai.com/v1/responses", 400, "bad request", {}, BytesIO(provider_body))
    details = extraction_pipeline._safe_provider_error_details(error)
    assert details == {
        "status_code": 400,
        "type": "invalid_request_error",
        "code": "unsupported_parameter",
        "param": "temperature",
    }
    metadata = extraction_pipeline._safe_usage_error_metadata(
        AppError("ocr_adapter_provider_rejected", "rejected", details=details)
    )
    assert metadata == {"provider_error": details}
    assert "message" not in str(metadata).lower()
    assert "authorization" not in str(metadata).lower()


def test_openai_chat_and_judge_api_mode_is_explicit_and_validated() -> None:
    absent = model_routes._normalized_config(
        provider="OpenAI",
        model_type="Chat",
        endpoint="https://api.openai.com/v1",
        config={"model_name": "gpt-5.6-luna"},
        has_credential=True,
    )
    assert "api_mode" not in absent
    assert ai_provider._uses_openai_responses_api(AIModel(provider="OpenAI", endpoint="https://api.openai.com/v1", config=absent)) is False

    responses = model_routes._normalized_config(
        provider="OpenAI",
        model_type="Judge",
        endpoint="https://api.openai.com/v1",
        config={"model_name": "gpt-5.6-luna", "api_mode": "RESPONSES"},
        has_credential=True,
    )
    assert responses["api_mode"] == "responses"
    assert ai_provider._uses_openai_responses_api(AIModel(provider="OpenAI", endpoint="https://api.openai.com/v1", config=responses)) is True

    with pytest.raises(AppError) as invalid:
        model_routes._normalized_config(
            provider="OpenAI",
            model_type="Chat",
            endpoint="https://api.openai.com/v1",
            config={"model_name": "gpt-5.6-luna", "api_mode": "auto"},
            has_credential=True,
        )
    assert invalid.value.code == "invalid_openai_api_mode"


def test_credential_fields_are_tristate_and_inactive_models_may_be_explicitly_cleared() -> None:
    omitted = AIModelUpdate(name="renamed")
    assert omitted.model_dump(exclude_unset=True) == {"name": "renamed"}
    blank = AIModelUpdate(api_key=None, api_key_secret_ref="")
    assert blank.model_fields_set == {"api_key", "api_key_secret_ref"}
    clear = AIModelUpdate(clear_credential=True, credential_clear_confirmation="nomosmart-ocr", is_active=False, is_default=False)
    assert clear.clear_credential is True
    assert clear.credential_clear_confirmation == "nomosmart-ocr"
    normalized = model_routes._normalized_config(
        provider="OpenAI",
        model_type="OCR",
        endpoint="https://api.openai.com/v1",
        config={"model_name": "gpt-5.6-luna"},
        has_credential=False,
        require_credential=False,
    )
    assert normalized["model_name"] == "gpt-5.6-luna"


def test_remote_ocr_credential_gate_fails_before_work_creation() -> None:
    remote = _ocr_model()
    remote.api_key_encrypted = None
    with pytest.raises(AppError) as missing:
        _require_ocr_model_credential(remote)
    assert missing.value.code == "ocr_model_credential_required"
    assert missing.value.status_code == 409

    local = AIModel(id=uuid4(), name="tesseract", model_type="OCR", provider="Tesseract", config={})
    assert _require_ocr_model_credential(local) is local
