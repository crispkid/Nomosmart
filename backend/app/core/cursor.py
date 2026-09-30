from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError


def encode_cursor(settings: Settings, *, namespace: str, payload: dict[str, Any]) -> str:
    body = json.dumps({"v": 1, **payload}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(settings.encryption_key_bytes, f"{namespace}:".encode("utf-8") + body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + signature).decode("ascii").rstrip("=")


def decode_cursor(settings: Settings, *, namespace: str, value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(decoded) <= 32:
            raise ValueError
        body, provided = decoded[:-32], decoded[-32:]
        expected = hmac.new(settings.encryption_key_bytes, f"{namespace}:".encode("utf-8") + body, hashlib.sha256).digest()
        if not hmac.compare_digest(provided, expected):
            raise ValueError
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError
        return payload
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc


def cursor_filter_hash(payload: object) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
