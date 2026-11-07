from __future__ import annotations

import hashlib
import secrets


API_KEY_PREFIX = "nms_"


def generate_api_key() -> tuple[str, str, str]:
    token = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return token, api_key_hash(token), token[:16]


def api_key_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
