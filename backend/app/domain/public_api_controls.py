from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.core.idempotency import canonical_request_hash, storage_scope, validate_replay
from app.db.models import IdempotencyKey
from app.integrations.redis_ha import redis_client


_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


@dataclass(frozen=True)
class IdempotencyReplay:
    status_code: int
    body: dict[str, Any]


def keyed_fingerprint(settings: Settings, namespace: str, value: str) -> str:
    return hmac.new(settings.encryption_key_bytes, f"{namespace}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def end_user_identity_hash(settings: Settings, employee_id: str) -> str:
    return keyed_fingerprint(settings, "public-end-user", employee_id.strip())


def require_idempotency_key(value: str | None) -> str:
    key = (value or "").strip()
    if len(key) < 8 or len(key) > 255 or any(ord(character) < 33 or ord(character) > 126 for character in key):
        raise AppError("idempotency_key_required", "A valid Idempotency-Key header is required", status_code=422)
    return key


def begin_idempotent_operation(
    session: Session,
    settings: Settings,
    *,
    scope: str,
    raw_key: str | None,
    request_payload: object,
) -> tuple[IdempotencyReplay | None, IdempotencyKey]:
    key = require_idempotency_key(raw_key)
    scope = storage_scope(scope)
    key_hash = keyed_fingerprint(settings, "public-idempotency", key)
    request_hash = canonical_request_hash(request_payload)
    now = datetime.now(UTC)
    existing = session.scalar(select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key_hash))
    if existing is not None and existing.expires_at <= now:
        session.delete(existing)
        session.flush()
        existing = None
    if existing is not None:
        return _existing_idempotency(existing, request_hash, now, settings), existing
    record = IdempotencyKey(
        scope=scope,
        key=key_hash,
        request_hash=request_hash,
        status="in_progress",
        expires_at=now + timedelta(hours=settings.public_api_idempotency_ttl_hours),
        created_at=now,
    )
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError:
        existing = session.scalar(select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key_hash))
        if existing is None:
            raise
        return _existing_idempotency(existing, request_hash, now, settings), existing
    return None, record


def _existing_idempotency(record: IdempotencyKey, request_hash: str, now: datetime, settings: Settings) -> IdempotencyReplay | None:
    validate_replay(record.request_hash, request_hash)
    if record.status in {"completed", "failed"} and record.response_summary is not None:
        return IdempotencyReplay(status_code=record.response_status or 200, body=record.response_summary)
    lease_deadline = record.created_at + timedelta(seconds=settings.public_api_idempotency_lease_seconds)
    if lease_deadline <= now:
        record.status = "expired"
        record.expires_at = now
        raise AppError("idempotency_key_expired", "The previous idempotent operation lease expired; use a new key", status_code=409)
    raise AppError("idempotency_key_in_progress", "Idempotency key is already processing", status_code=409)


def complete_idempotent_operation(record: IdempotencyKey, body: dict[str, Any], *, status_code: int = 200) -> None:
    record.status = "completed"
    record.response_status = status_code
    record.response_summary = body
    record.completed_at = datetime.now(UTC)


def fail_idempotent_operation(record: IdempotencyKey, error: AppError) -> None:
    record.status = "failed"
    record.response_status = error.status_code
    record.response_summary = {"error": {"code": error.code, "message": error.message}}
    record.completed_at = datetime.now(UTC)


def enforce_rate_limit(settings: Settings, *, dimension: str, limit: int) -> None:
    key = f"nomosmart:public-api:rate:{keyed_fingerprint(settings, 'rate', dimension)}"
    try:
        client = redis_client(
            settings,
            decode_responses=True,
        )
        try:
            count = int(client.eval(_RATE_LIMIT_SCRIPT, 1, key, settings.public_api_rate_limit_window_seconds))
        finally:
            client.close()
    except redis.RedisError as exc:
        raise AppError("public_api_rate_limit_unavailable", "Public API rate limiting is unavailable", status_code=503) from exc
    if count > limit:
        raise AppError("public_api_rate_limited", "API rate limit exceeded", status_code=429)


def encrypt_payload(settings: Settings, response_id: object, field: str, value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return EnvelopeCipher(settings.encryption_key_bytes).encrypt(serialized, context=f"public-response:{response_id}:{field}")


def decrypt_payload(settings: Settings, response_id: object, field: str, value: str) -> Any:
    plaintext = EnvelopeCipher(settings.encryption_key_bytes).decrypt(value, context=f"public-response:{response_id}:{field}")
    return json.loads(plaintext)
