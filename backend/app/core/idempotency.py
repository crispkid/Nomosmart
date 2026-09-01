from __future__ import annotations

import hashlib
import json

from app.core.errors import AppError


def canonical_request_hash(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def validate_replay(stored_request_hash: str, request_hash: str) -> None:
    if stored_request_hash != request_hash:
        raise AppError(
            "idempotency_key_conflict",
            "Idempotency key was already used with a different request",
            status_code=409,
        )

