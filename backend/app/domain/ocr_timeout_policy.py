"""Versioned PDF OCR budgets and content-free diagnostic metadata."""
from __future__ import annotations

from dataclasses import dataclass
import re
from time import monotonic

from app.core.errors import AppError


POLICY_KEY = "pdf_ocr_timeout_policy"
SPLIT_POLICY = "split-v1"
PAGE_KEY = "ocr_page_timeout_seconds"
DOCUMENT_KEY = "ocr_document_timeout_seconds"
ERROR_KINDS = frozenset({"page_timeout", "document_timeout", "token_budget_exhausted",
    "connection_error", "tls_error", "provider_rejected", "invalid_response", "unknown"})
PHASES = frozenset({"connect", "read", "write", "pool", "response", "unknown"})
_NUMERIC_FIELDS = frozenset({"physical_page", "config_version", "page_timeout_seconds",
    "document_timeout_seconds", "effective_request_timeout_ms", "page_elapsed_ms",
    "document_elapsed_ms", "remaining_document_ms"})


def normalize_timeout_config(config: dict[str, object], *, required: bool = False) -> dict[str, int]:
    if not isinstance(config, dict):
        raise AppError("ocr_timeout_config_invalid", "OCR timeout configuration must be an object", status_code=422)
    result: dict[str, int] = {}
    for key, default in ((PAGE_KEY, 30), (DOCUMENT_KEY, 600)):
        value = config.get(key) if required else config.get(key, default)
        if type(value) is not int or not 1 <= value <= 600:
            raise AppError("ocr_timeout_config_invalid", "OCR timeouts must be integers from 1 to 600 seconds", status_code=422)
        result[key] = value
    if result[PAGE_KEY] > result[DOCUMENT_KEY]:
        raise AppError("ocr_timeout_config_invalid", "OCR document timeout must not be shorter than the page timeout", status_code=422)
    return result


def split_snapshot(config: dict[str, object]) -> dict[str, object]:
    return {POLICY_KEY: SPLIT_POLICY, **normalize_timeout_config(config)}


def snapshot_timeout_policy(snapshot: dict[str, object]) -> dict[str, object]:
    # Absence, not null/unknown, means a pre-policy snapshot. Never read live config here.
    if POLICY_KEY not in snapshot:
        return {}
    if snapshot[POLICY_KEY] != SPLIT_POLICY:
        raise AppError("ocr_timeout_config_invalid", "PDF OCR timeout policy is unsupported", status_code=422)
    return {POLICY_KEY: SPLIT_POLICY, **normalize_timeout_config(snapshot, required=True)}


def safe_provider_error(details: object) -> dict[str, object]:
    if not isinstance(details, dict):
        return {}
    result: dict[str, object] = {}
    status = details.get("status_code")
    if type(status) is int and 100 <= status <= 599:
        result["status_code"] = status
    for key in ("type", "code", "param"):
        value = details.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:\[\]-]{1,160}", value):
            if not value.lower().startswith(("sk-", "bearer", "eyj")):
                result[key] = value
    return result


def safe_diagnostics(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, object] = {}
    for key in _NUMERIC_FIELDS:
        number = value.get(key)
        if type(number) is int and 0 <= number <= 2**63 - 1:
            result[key] = number
    if value.get("policy") in (SPLIT_POLICY, "legacy"):
        result["policy"] = value["policy"]
    if isinstance(value.get("error_kind"), str) and value["error_kind"] in ERROR_KINDS:
        result["error_kind"] = value["error_kind"]
    if isinstance(value.get("phase"), str) and value["phase"] in PHASES:
        result["phase"] = value["phase"]
    if type(value.get("attempted")) is bool:
        result["attempted"] = value["attempted"]
    return result


def error_metadata(error: AppError) -> dict[str, object]:
    result: dict[str, object] = {}
    provider = safe_provider_error(error.details)
    diagnostics = safe_diagnostics(getattr(error, "ocr_diagnostics", None))
    if provider:
        result["provider_error"] = provider
    if diagnostics:
        result["ocr_diagnostics"] = diagnostics
    return result


def diagnostic_error(code: str, message: str, *, kind: str, phase: str = "unknown",
                     attempted: bool = False, status_code: int = 503) -> AppError:
    error = AppError(code, message, status_code=status_code)
    error.ocr_diagnostics = safe_diagnostics({"error_kind": kind, "phase": phase, "attempted": attempted})
    return error


@dataclass(frozen=True)
class OCRRequestWindow:
    started: float
    deadline: float
    timeout_kind: str

    def remaining(self) -> float:
        return max(0.0, self.deadline - monotonic())

    def check(self, *, attempted: bool) -> None:
        if self.remaining() <= 0:
            raise diagnostic_error("ocr_adapter_unavailable" if attempted else "ocr_pdf_budget_exhausted",
                "PDF OCR request deadline expired", kind=self.timeout_kind, attempted=attempted,
                status_code=503 if attempted else 422)


@dataclass(frozen=True)
class PDFOCRDeadline:
    page_seconds: int
    document_seconds: int
    started: float

    @classmethod
    def start(cls, snapshot: dict[str, object]) -> PDFOCRDeadline:
        policy = snapshot_timeout_policy(snapshot)
        if not policy:
            raise AppError("ocr_timeout_config_invalid", "Split PDF OCR requires a versioned snapshot", status_code=422)
        return cls(policy[PAGE_KEY], policy[DOCUMENT_KEY], monotonic())

    @property
    def deadline(self) -> float:
        return self.started + self.document_seconds

    def request_window(self) -> OCRRequestWindow:
        now = monotonic()
        document_limited = self.deadline <= now + self.page_seconds
        window = OCRRequestWindow(now, min(now + self.page_seconds, self.deadline),
                                  "document_timeout" if document_limited else "page_timeout")
        window.check(attempted=False)
        return window

    def diagnostics(self, *, page: int, config_version: object, window: OCRRequestWindow | None = None) -> dict[str, object]:
        now = monotonic()
        return safe_diagnostics({"policy": SPLIT_POLICY, "physical_page": page, "config_version": config_version,
            "page_timeout_seconds": self.page_seconds, "document_timeout_seconds": self.document_seconds,
            "effective_request_timeout_ms": max(0, int((window.deadline-window.started)*1000)) if window else 0,
            "page_elapsed_ms": max(0, int((now-window.started)*1000)) if window else 0,
            "document_elapsed_ms": max(0, int((now-self.started)*1000)),
            "remaining_document_ms": max(0, int((self.deadline-now)*1000))})
