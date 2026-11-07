"""Production helper/native-time tests, not a simulated Provider or database.

No fixtures/mocks/clock replacement. ORM instances are policy input values only;
they are not claimed as database persistence evidence. Real HTTP test uses an OS
port reserved without a listener, so refusal is real and no Provider is called.
"""
from __future__ import annotations
import asyncio
import copy
import json
import logging
import socket
import ssl
import threading
import time
from uuid import uuid4

import httpx
import pytest

from app.core.errors import AppError
from app.core.config import Settings
from app.db.session import get_session_factory
from owned_service_scope import verify_owned_services
from app.db.models import AIModel, DocumentVersion
from app.api.routes.models import _normalized_config
from app.domain.document_imports import ocr_execution_snapshot
from app.domain.extraction_pipeline import _ocr_snapshot
from app.domain.ocr_timeout_policy import PAGE_KEY, DOCUMENT_KEY, POLICY_KEY, SPLIT_POLICY, OCRRequestWindow, normalize_timeout_config, snapshot_timeout_policy, diagnostic_error, error_metadata, safe_diagnostics, safe_provider_error
from app.integrations.ocr_transport import (classify_transport_error, decode_ocr_response, post_ocr_json,
    _PrivateTransportLogFilter, _private_request)


def test_defaults_do_not_mutate_config():
    from app.domain.ocr_timeout_policy import split_snapshot  # Historical, unqualified retired contract.
    config = {"timeout_seconds": 2, "model_name": "test-policy-input"}
    before = copy.deepcopy(config)
    assert normalize_timeout_config(config) == {PAGE_KEY: 30, DOCUMENT_KEY: 600}
    assert split_snapshot(config) == {POLICY_KEY: SPLIT_POLICY, PAGE_KEY: 30, DOCUMENT_KEY: 600}
    assert config == before


@pytest.mark.parametrize("page,document", [(1, 1), (1, 600), (30, 600), (600, 600)])
def test_valid_config_boundaries(page, document):
    assert normalize_timeout_config({PAGE_KEY: page, DOCUMENT_KEY: document}) == {PAGE_KEY: page, DOCUMENT_KEY: document}


@pytest.mark.parametrize("key", [PAGE_KEY, DOCUMENT_KEY])
@pytest.mark.parametrize("value", [None, True, False, "30", 30.0, 0, -1, 601, float("nan"), {}, []])
def test_invalid_values_fail_closed(key, value):
    with pytest.raises(AppError) as error:
        normalize_timeout_config({key: value})
    assert error.value.code == "ocr_timeout_config_invalid"
    assert error.value.status_code == 422
    assert error.value.details == {}


def test_page_cannot_exceed_document():
    with pytest.raises(AppError):
        normalize_timeout_config({PAGE_KEY: 31, DOCUMENT_KEY: 30})
    with pytest.raises(AppError) as error:
        normalize_timeout_config([1])
    assert error.value.code == "ocr_timeout_config_invalid"


def test_legacy_is_marker_absence_not_live_config():
    from app.domain.ocr_timeout_policy import PDFOCRDeadline  # Historical, unqualified retired contract.
    assert snapshot_timeout_policy({"timeout_seconds": 30, PAGE_KEY: 3}) == {}
    with pytest.raises(AppError):
        PDFOCRDeadline.start({"timeout_seconds": 30})


@pytest.mark.parametrize("snapshot", [
    {POLICY_KEY: None}, {POLICY_KEY: ""}, {POLICY_KEY: "split-v2"}, {POLICY_KEY: []},
    {POLICY_KEY: SPLIT_POLICY}, {POLICY_KEY: SPLIT_POLICY, PAGE_KEY: 30},
    {POLICY_KEY: SPLIT_POLICY, PAGE_KEY: 30, DOCUMENT_KEY: None},
])
def test_invalid_versioned_snapshots_are_not_repaired_from_defaults(snapshot):
    with pytest.raises(AppError):
        snapshot_timeout_policy(snapshot)


@pytest.fixture
def ocr_settings_session():
    verify_owned_services(Settings(_env_file=None))
    with get_session_factory()() as session:
        try:yield session
        finally:session.rollback()


@pytest.mark.parametrize("provider,extension,expected", [
    ("OpenAI", ".pdf", True), (" openai ", ".PDF", True),
    ("OpenAI", ".docx", False), ("OpenAI", ".png", False), ("OpenAI", None, False),
    ("Tesseract", ".pdf", False), ("generic_http", ".pdf", False),
])
def test_only_new_openai_pdf_gets_split_snapshot(provider, extension, expected, ocr_settings_session):
    model = AIModel(id=uuid4(), name="policy-input", model_type="OCR", provider=provider,
                    config_version=4, config={"timeout_seconds": 9})
    before = copy.deepcopy(model.config)
    snapshot = ocr_execution_snapshot(model, force_ocr=False, canonical_extension=extension, session=ocr_settings_session)
    assert (POLICY_KEY in snapshot) == expected
    assert snapshot["timeout_seconds"] == 9
    assert snapshot["config_version"] == 4 and model.config == before
    if expected:
        assert snapshot[PAGE_KEY] == 30 and snapshot[DOCUMENT_KEY] == 600
        assert snapshot['ocr_page_max_output_tokens']==10000
        assert snapshot['ocr_document_max_tokens']==1000000
        assert snapshot['ocr_token_budget_basis']=='output'


def test_execution_uses_frozen_new_snapshot_and_legacy_remains_legacy():
    from app.domain.ocr_timeout_policy import split_snapshot  # Historical, unqualified retired contract.
    model = AIModel(id=uuid4(), name="policy-input", model_type="OCR", provider="OpenAI", config_version=9,
                    config={PAGE_KEY: 100, DOCUMENT_KEY: 200})
    saved = {**split_snapshot({PAGE_KEY: 5, DOCUMENT_KEY: 60}), "timeout_seconds": 30, "config_version": 4}
    version = DocumentVersion(id=uuid4(), canonical_extension=".pdf", ocr_config_version=4,
                              ocr_model_id=model.id, chunk_strategy={"ocr_snapshot": saved})
    resolved = _ocr_snapshot(model, version, False)
    assert resolved[PAGE_KEY] == 5 and resolved[DOCUMENT_KEY] == 60
    assert resolved["config_version"] == 4 and version.chunk_strategy["ocr_snapshot"] == saved
    version.chunk_strategy = {"ocr_snapshot": {"timeout_seconds": 30, "config_version": 4}}
    assert POLICY_KEY not in _ocr_snapshot(model, version, False)
    version.chunk_strategy = {"ocr_snapshot": {POLICY_KEY: SPLIT_POLICY}}
    with pytest.raises(AppError):
        _ocr_snapshot(model, version, False)


def test_model_config_normalization_is_provider_and_type_scoped():
    base = {"model_name": "policy-input", "timeout_seconds": 120}
    result = _normalized_config(provider="OpenAI", model_type="OCR", endpoint=None,
                                config=base, has_credential=True)
    assert result[PAGE_KEY] == 30 and result[DOCUMENT_KEY] == 600 and result["timeout_seconds"] == 120
    assert PAGE_KEY not in base
    for provider, model_type in [("OpenAI", "Chat"), ("Ollama", "OCR")]:
        config = _normalized_config(provider=provider, model_type=model_type, endpoint="http://127.0.0.1",
                                     config=base, has_credential=True)
        assert PAGE_KEY not in config
    with pytest.raises(AppError):
        _normalized_config(provider="OpenAI", model_type="OCR", endpoint=None,
                           config={**base, PAGE_KEY: False}, has_credential=True)


def test_native_fractional_window_and_expiry_no_rounding_or_reset():
    from app.domain.ocr_timeout_policy import PDFOCRDeadline  # Historical, unqualified retired contract.
    from app.domain.ocr_timeout_policy import split_snapshot  # Historical, unqualified retired contract.
    budget = PDFOCRDeadline.start(split_snapshot({PAGE_KEY: 1, DOCUMENT_KEY: 1}))
    original = budget.deadline
    time.sleep(0.05)
    window = budget.request_window()
    assert 0 < window.remaining() < 1
    assert window.deadline == original and window.timeout_kind == "document_timeout"
    time.sleep(window.remaining() + 0.02)
    for attempted in [False, True]:
        with pytest.raises(AppError) as error:
            window.check(attempted=attempted)
        assert error.value.ocr_diagnostics["attempted"] is attempted
        assert error.value.ocr_diagnostics["error_kind"] == "document_timeout"
        assert not error.value.details
    with pytest.raises(AppError):
        budget.request_window()
    assert budget.deadline == original


def test_default_document_can_cross_thirty_real_seconds():
    from app.domain.ocr_timeout_policy import PDFOCRDeadline  # Historical, unqualified retired contract.
    from app.domain.ocr_timeout_policy import split_snapshot  # Historical, unqualified retired contract.
    budget = PDFOCRDeadline.start(split_snapshot({}))
    original = budget.deadline
    first = budget.request_window()
    assert first.timeout_kind == "page_timeout"
    time.sleep(30.05)
    with pytest.raises(AppError):
        first.check(attempted=True)
    following = budget.request_window()
    assert budget.deadline == original
    assert 29 < following.remaining() <= 30
    assert following.timeout_kind == "page_timeout"
    metadata = budget.diagnostics(page=10, config_version=4, window=following)
    assert metadata["document_elapsed_ms"] >= 30000
    assert metadata["remaining_document_ms"] < 570000
    assert metadata["page_timeout_seconds"] == 30 and metadata["document_timeout_seconds"] == 600


@pytest.mark.parametrize("error,kind,phase", [
    (httpx.ConnectTimeout("private"), "page_timeout", "connect"),
    (httpx.ReadTimeout("private"), "page_timeout", "read"),
    (httpx.WriteTimeout("private"), "page_timeout", "write"),
    (httpx.PoolTimeout("private"), "page_timeout", "pool"),
    (TimeoutError("private"), "page_timeout", "unknown"),
    (ssl.SSLError("private"), "tls_error", "unknown"),
    (ConnectionRefusedError("private"), "connection_error", "unknown"),
    (json.JSONDecodeError("private", "private", 0), "invalid_response", "response"),
    (httpx.DecodingError("private"), "invalid_response", "response"),
    (RuntimeError("private"), "unknown", "unknown"),
])
def test_error_classification_is_typed_not_message_guessing(error, kind, phase):
    window = OCRRequestWindow(time.monotonic(), time.monotonic()+30, "page_timeout")
    assert classify_transport_error(error, window) == (kind, phase)


def test_nested_tls_and_document_timeout_classification():
    window = OCRRequestWindow(time.monotonic(), time.monotonic()+1, "document_timeout")
    error = httpx.ConnectError("private")
    error.__cause__ = ssl.SSLCertVerificationError("private")
    assert classify_transport_error(error, window) == ("tls_error", "unknown")
    assert classify_transport_error(httpx.ReadTimeout("private"), window) == ("document_timeout", "read")


@pytest.mark.parametrize("raw,code", [(b"not json", "ocr_adapter_unavailable"),
    (b"\xff", "ocr_adapter_unavailable"), (b"[]", "ocr_adapter_response_invalid"),
    (b"null", "ocr_adapter_response_invalid")])
def test_decode_failure_contains_no_raw_document(raw, code):
    with pytest.raises(AppError) as error:
        decode_ocr_response(raw)
    assert error.value.code == code and error.value.details == {}
    assert error.value.ocr_diagnostics == {"error_kind": "invalid_response", "phase": "response", "attempted": True}


def test_json_decoder_preserves_object_but_does_not_certify_provider_success():
    # Pure decoder input, not a fabricated HTTP response or OCR result.
    assert decode_ocr_response(b'{"unrelated_key": 1}') == {"unrelated_key": 1}


def test_safe_metadata_drops_unapproved_and_sensitive_values():
    details = {"status_code": 429, "type": "rate_limit_error", "code": "quota_exceeded", "param": "input[0]",
               "message": "private document", "api_key": "private key", "url": "https://private.test"}
    assert safe_provider_error(details) == {k: details[k] for k in ("status_code", "type", "code", "param")}
    for value in ["sk-private", "Bearer-private", "eyJ-private", "https://private", "private text", "bad\nvalue", "x"*161, 123, [], None]:
        assert safe_provider_error({"code": value, "status_code": True}) == {}
    data = {"physical_page": 10, "config_version": 4, "attempted": True, "phase": "read",
            "error_kind": "page_timeout", "policy": SPLIT_POLICY, "page_elapsed_ms": 123,
            "document_elapsed_ms": -1, "remaining_document_ms": True, "body": "private"}
    safe = safe_diagnostics(data)
    assert "body" not in safe and "remaining_document_ms" not in safe and "document_elapsed_ms" not in safe
    assert safe["physical_page"] == 10
    assert safe_diagnostics({"error_kind": [], "phase": {}, "policy": []}) == {}


def test_page_usage_metadata_keeps_safe_diagnostics_without_raw_values():
    from app.domain.extraction_pipeline import _ocr_page_usage_metadata
    error = diagnostic_error("ocr_adapter_unavailable", "safe", kind="document_timeout", attempted=True)
    error.details = {"status_code": 503, "message": "private"}
    error.ocr_diagnostics.update(physical_page=10, page_elapsed_ms=1000, request="private")
    attempt = {"physical_page": 10, **error_metadata(error), "body": "private"}
    result = _ocr_page_usage_metadata(attempt)
    assert result["ocr_diagnostics"]["error_kind"] == "document_timeout"
    assert result["provider_error"] == {"status_code": 503}
    assert "private" not in json.dumps(result)
    assert "ocr_diagnostics" not in error.details
    assert _ocr_page_usage_metadata({"physical_page": 1, "ocr_diagnostics": None}) == {"physical_page": 1}


def test_predispatch_errors_never_imply_a_paid_attempt():
    from app.domain.extraction_pipeline import _pdf_error_diagnostics
    for code in ("ocr_adapter_not_configured", "ocr_adapter_credential_required", "ocr_adapter_secret_ref_unresolved"):
        assert _pdf_error_diagnostics(AppError(code, "safe"))["attempted"] is False
    assert _pdf_error_diagnostics(diagnostic_error("ocr_pdf_budget_exhausted", "safe",
        kind="document_timeout", attempted=False))["attempted"] is False


def test_missing_real_model_credential_fails_before_http_dispatch():
    from app.domain.ocr_timeout_policy import PDFOCRDeadline  # Historical, unqualified retired contract.
    from app.domain.ocr_timeout_policy import split_snapshot  # Historical, unqualified retired contract.
    from app.domain.extraction_pipeline import _post_openai_ocr
    model = AIModel(id=uuid4(), name="policy-input", model_type="OCR", provider="OpenAI", config={})
    window = PDFOCRDeadline.start(split_snapshot({})).request_window()
    with pytest.raises(AppError) as error:
        _post_openai_ocr(model, Settings(_env_file=None), {}, timeout_seconds=30, request_window=window)
    assert error.value.code == "ocr_adapter_credential_required"
    assert error.value.ocr_diagnostics["attempted"] is False


def test_context_local_library_log_privacy_does_not_suppress_other_threads():
    log_filter = _PrivateTransportLogFilter()
    record = logging.LogRecord("httpx", logging.INFO, "", 1, "private endpoint", (), None)
    assert log_filter.filter(record)
    token = _private_request.set(True)
    try:
        assert not log_filter.filter(record)
        other = []
        thread = threading.Thread(target=lambda: other.append(log_filter.filter(record)))
        thread.start()
        thread.join(2)
        assert other == [True] and not thread.is_alive()
    finally:
        _private_request.reset(token)
    assert log_filter.filter(record)


def test_expired_transport_window_does_not_open_network():
    window = OCRRequestWindow(time.monotonic()-2, time.monotonic()-1, "document_timeout")
    with pytest.raises(AppError) as error:
        post_ocr_json(url="http://127.0.0.1", headers={}, body={}, verify=True, window=window)
    assert error.value.ocr_diagnostics["attempted"] is False
    assert error.value.ocr_diagnostics["error_kind"] == "document_timeout"


def test_nested_event_loop_is_rejected_without_thread_or_provider():
    from app.domain.ocr_timeout_policy import PDFOCRDeadline  # Historical, unqualified retired contract.
    from app.domain.ocr_timeout_policy import split_snapshot  # Historical, unqualified retired contract.
    async def check():
        window = PDFOCRDeadline.start(split_snapshot({})).request_window()
        with pytest.raises(AppError) as error:
            post_ocr_json(url="http://127.0.0.1", headers={}, body={}, verify=True, window=window)
        assert error.value.ocr_diagnostics["attempted"] is False
    with asyncio.Runner() as runner:
        loop = runner.get_loop()
        runner.run(check())
    assert loop.is_closed()


def test_real_os_connection_refusal_and_runner_cleanup():
    from app.domain.ocr_timeout_policy import PDFOCRDeadline  # Historical, unqualified retired contract.
    from app.domain.ocr_timeout_policy import split_snapshot  # Historical, unqualified retired contract.
    before = {t.ident for t in threading.enumerate()}
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))  # Not listening; real OS refusal, no HTTP server/fixture.
        port = reserved.getsockname()[1]
        # Use the approved production default, including cold library/TLS setup.
        # A 2s total budget can expire under coverage before OS refusal arrives;
        # short-window expiry is verified separately above, not accepted as refusal.
        window = PDFOCRDeadline.start(split_snapshot({})).request_window()
        with pytest.raises(AppError) as error:
            post_ocr_json(url=f"http://127.0.0.1:{port}", headers={}, body={}, verify=True, window=window)
        assert error.value.code == "ocr_adapter_unavailable"
        assert error.value.ocr_diagnostics == {"error_kind": "connection_error", "phase": "unknown", "attempted": True}
        assert error.value.details == {} and "127.0.0.1" not in str(error.value)
    assert {t.ident for t in threading.enumerate()} == before
    assert _private_request.get() is False
