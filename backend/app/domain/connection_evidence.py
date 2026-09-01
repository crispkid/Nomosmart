from __future__ import annotations

import hashlib
import json
from urllib.parse import urlparse, urlunsplit

from app.db.models import AIModel, DataConnection


def ai_model_connection_fingerprint(model: AIModel) -> str:
    config = model.config if isinstance(model.config, dict) else {}
    payload = {
        "model_type": model.model_type,
        "provider": model.provider.strip().lower(),
        "endpoint": _safe_endpoint(model.endpoint or str(config.get("base_url") or "")),
        "model_name": str(config.get("model_name") or model.name),
        "verify_tls": _bool(config.get("verify_tls", True)),
        "timeout_seconds": _int(config.get("timeout_seconds") or config.get("timeout"), 60),
        "config_version": model.config_version,
        "credential_digest": _credential_digest(model.api_key_encrypted, model.api_key_secret_ref),
    }
    return _fingerprint(payload)


def data_connection_fingerprint(connection: DataConnection) -> str:
    metadata = connection.connection_metadata if isinstance(connection.connection_metadata, dict) else {}
    identity = connection.source_identity if isinstance(connection.source_identity, dict) else {}
    payload = {
        "service_type": connection.service_type,
        "endpoint": _safe_endpoint(str(metadata.get("endpoint_url") or "")),
        "host": str(metadata.get("host") or "").strip().lower(),
        "port": metadata.get("port"),
        "region": metadata.get("region"),
        "bucket": metadata.get("bucket"),
        "verify_tls": _bool(metadata.get("verify_tls", True)),
        "verify_host_key": _bool(metadata.get("verify_host_key", True)),
        "remote_path": identity.get("remote_path"),
        "file_name": identity.get("file_name"),
        "url": _safe_endpoint(str(identity.get("url") or ""), include_path=True),
        "auth_mode": metadata.get("auth_mode"),
        "api_key_header_name": metadata.get("api_key_header_name"),
        "timeout_seconds": metadata.get("timeout_seconds"),
        "credential_digest": _credential_digest(connection.credential_encrypted, connection.credential_secret_ref),
    }
    return _fingerprint(payload)


def invalidate_model_connection_evidence(model: AIModel) -> None:
    model.last_test_status = "stale" if model.last_tested_at else None
    model.last_test_fingerprint = None
    model.last_test_latency_ms = None
    model.last_test_detail_code = "configuration_changed" if model.last_tested_at else None


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _credential_digest(encrypted: str | None, secret_ref: str | None) -> str | None:
    material = f"encrypted:{encrypted}" if encrypted else f"secret-ref:{secret_ref}" if secret_ref else ""
    return hashlib.sha256(material.encode("utf-8")).hexdigest() if material else None


def _safe_endpoint(value: str, *, include_path: bool = True) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        return value.strip()
    host = parsed.hostname.lower().rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    authority = f"{host}:{parsed.port}" if parsed.port else host
    return urlunsplit((parsed.scheme.lower(), authority, parsed.path.rstrip("/") if include_path else "", "", ""))


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _int(value: object, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
