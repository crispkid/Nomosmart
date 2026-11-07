"""Explicit operator-owned capabilities for native PDF Responses requests."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.core.errors import AppError


PROFILE_KEY = "native_pdf"
INTEGER_KEYS = ("max_input_bytes", "max_request_bytes", "max_response_bytes", "context_window", "max_output_tokens", "min_output_tokens")


def normalize_native_capabilities(config: dict[str, object]) -> dict[str, object]:
    profile = config.get(PROFILE_KEY) if isinstance(config, dict) else None
    if not isinstance(profile, dict):
        raise AppError("ocr_native_capability_required", "Native PDF capabilities must be configured explicitly", status_code=422)
    if (profile.get("protocol") != "openai_responses" or profile.get("supports_pdf") is not True
            or profile.get("count_input_tokens") is not True):
        raise AppError("ocr_native_capability_invalid", "Native PDF requires Responses, PDF input and input-token counting", status_code=422)
    mimes = profile.get("mime_types")
    if not isinstance(mimes, list) or not mimes or any(not isinstance(mime, str) for mime in mimes) or "application/pdf" not in mimes:
        raise AppError("ocr_native_capability_invalid", "Native PDF MIME capability is missing", status_code=422)
    result = {"protocol": "openai_responses", "supports_pdf": True,
              "count_input_tokens": True, "mime_types": sorted(set(mimes))}
    for key in INTEGER_KEYS:
        value = profile.get(key)
        if type(value) is not int or not 1 <= value <= 2**63 - 1:
            raise AppError("ocr_native_capability_invalid", "Native PDF capability limits must be positive integers", status_code=422, details={"field": key})
        result[key] = value
    if result["min_output_tokens"] > result["max_output_tokens"] or result["max_output_tokens"] >= result["context_window"]:
        raise AppError("ocr_native_capability_invalid", "Native PDF token capabilities are inconsistent", status_code=422)
    if "supports_temperature" in profile and type(profile["supports_temperature"]) is not bool:
        raise AppError("ocr_native_capability_invalid", "Temperature capability must be a boolean", status_code=422)
    result["supports_temperature"] = profile.get("supports_temperature", False)
    return {**profile, **result}


@dataclass(frozen=True)
class NativePDFCapabilities:
    profile: dict[str, object]
    responses_url: str
    model_name: str

    @property
    def count_url(self) -> str:
        return self.responses_url + "/input_tokens"

    def limit(self, key: str) -> int:
        return self.profile[key]


def require_native_capabilities(model) -> NativePDFCapabilities:
    if (model is None or model.model_type != "OCR" or str(model.provider).strip().lower() != "openai"
            or not model.is_active or model.deleted_at is not None):
        raise AppError("ocr_native_model_required", "An active OpenAI native PDF OCR model is required", status_code=409)
    config = model.config if isinstance(model.config, dict) else {}
    profile = normalize_native_capabilities(config)
    model_name = config.get("model_name")
    if not isinstance(model_name, str) or not model_name.strip():
        raise AppError("ocr_model_name_required", "Native PDF model_name is required", status_code=422)
    base = config.get("base_url") or model.endpoint
    if not isinstance(base, str) or not base.strip():
        raise AppError("ocr_adapter_not_configured", "Native PDF endpoint is required", status_code=422)
    parsed = urlsplit(base.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AppError("ocr_native_endpoint_invalid", "Native PDF endpoint must be an HTTP origin and path without credentials or query", status_code=422)
    # API routes additionally apply the existing operator endpoint/SSRF policy.
    try:
        parsed.port
    except ValueError:
        raise AppError("ocr_native_endpoint_invalid", "Native PDF endpoint port is invalid", status_code=422) from None
    path = parsed.path.rstrip("/")
    if not path.endswith("/responses"):
        path += "/responses"
    url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    return NativePDFCapabilities(profile, url, model_name.strip())
