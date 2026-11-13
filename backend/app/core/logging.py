from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

from app.core.readiness_diagnostics import safe_readiness_checks


SENSITIVE_LOG_KEYS = ("password", "secret", "token", "api_key", "credential", "authorization", "prompt", "document_content", "citation")
SAFE_EXTRA_KEYS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "latency_ms",
    "error_code",
    "result",
    "project_id",
    "conversation_id",
    "validation_run_id",
    "model_id",
    "provider",
    "worker_id",
    "worker_task",
    "readiness_checks",
)


def redact_log_value(key: str, value: Any) -> Any:
    normalized = key.lower()
    if any(sensitive in normalized for sensitive in SENSITIVE_LOG_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(child_key): redact_log_value(str(child_key), child_value) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [redact_log_value(key, child) for child in value[:20]]
    if isinstance(value, str) and len(value) > 500:
        return f"{value[:120]}…"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in SAFE_EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = safe_readiness_checks(value) if key == "readiness_checks" else redact_log_value(key, value)
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
            payload["stack"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class ApprovalAccessLogPrivacy(logging.Filter):
    """Preserve Uvicorn access facts while excluding approval filter values."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5 and isinstance(record.args[2], str):
            target = record.args[2]
            path = target.split("?", 1)[0]
            decoded = unquote(path)
            if "/approvals/" in decoded or decoded.endswith("/approvals") or "/auth/" in decoded:
                record.args = (*record.args[:2], path, *record.args[3:])
        return True


def configure_logging(level: str = "INFO", output_format: str = "json") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if output_format == "json" else logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, ApprovalAccessLogPrivacy) for item in access.filters):
        access.addFilter(ApprovalAccessLogPrivacy())
