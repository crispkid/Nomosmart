from __future__ import annotations

import hashlib
import json

from app.core.errors import AppError


def storage_scope(scope: str) -> str:
    """Fit the existing VARCHAR(100) without changing valid historical scopes.

    The reserved prefix is internal: callers construct identity scopes on the
    server. Hash the complete operation/actor/target, never a truncated prefix.
    """
    if len(scope) <= 100:
        return scope
    return "scope:v1:sha256:" + hashlib.sha256(scope.encode("utf-8")).hexdigest()


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
