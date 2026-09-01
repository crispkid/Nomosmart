from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse, urlunsplit

import httpx

from app.api.schemas import DataSourceConnectionPayload
from app.core.config import Settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import AIModel, DataConnection
from app.domain.connection_evidence import ai_model_connection_fingerprint, data_connection_fingerprint
from app.integrations.remote_sources import FTPRemoteSourceClient, FTPSRemoteSourceClient, HTTPRemoteSourceClient, SFTPRemoteSourceClient
from app.integrations.s3_storage import S3ClientConfig, S3ObjectStorage
from app.security.secrets import resolve_runtime_secret


@dataclass(frozen=True)
class ConnectionProbeResult:
    fingerprint: str
    latency_ms: int
    detail_code: str


def probe_ai_model(settings: Settings, model: AIModel) -> ConnectionProbeResult:
    started = time.monotonic()
    provider = model.provider.strip().lower()
    if provider == "tesseract":
        _probe_local_command(["tesseract", "--version"], timeout_seconds=10)
        detail = "local_provider_ready"
    else:
        api_key = _resolve_model_credential(settings, model)
        _probe_http_model(model, api_key)
        detail = "provider_model_ready"
    return ConnectionProbeResult(ai_model_connection_fingerprint(model), _latency_ms(started), detail)


def probe_data_source_candidate(settings: Settings, payload: DataSourceConnectionPayload) -> ConnectionProbeResult:
    started = time.monotonic()
    credential = _resolve_candidate_credential(settings, payload.credential, payload.credential_secret_ref)
    _probe_data_source_values(settings, payload, credential)
    fingerprint = _candidate_fingerprint(payload, credential_configured=bool(credential))
    return ConnectionProbeResult(fingerprint, _latency_ms(started), "remote_object_ready")


def probe_stored_data_connection(settings: Settings, connection: DataConnection) -> ConnectionProbeResult:
    from app.domain.data_sync import _decrypted_credential, _http_headers, _s3_connection_storage

    started = time.monotonic()
    metadata = connection.connection_metadata or {}
    identity = connection.source_identity or {}
    file_name = str(identity.get("file_name") or connection.name)
    remote_path = str(identity.get("remote_path") or "")
    timeout = int(metadata.get("timeout_seconds") or 30)
    if connection.service_type == "S3":
        storage = _s3_connection_storage(settings, connection)
        storage.object_status(bucket=str(metadata.get("bucket") or ""), key=_object_key(remote_path, file_name))
    elif connection.service_type == "HTTP_API":
        HTTPRemoteSourceClient().probe(url=str(identity.get("url") or ""), headers=_http_headers(settings, connection), timeout_seconds=timeout, verify_tls=bool(metadata.get("verify_tls", True)), allowed_hosts=settings.http_source_allowed_hostnames, allowed_networks=settings.http_source_allowed_networks)
    else:
        credential = _decrypted_credential(settings, connection)
        _probe_file_protocol(connection.service_type, str(metadata.get("host") or ""), int(metadata.get("port") or 0), str(metadata.get("username") or ""), credential, remote_path, file_name, timeout, settings.sftp_known_hosts_path)
    return ConnectionProbeResult(data_connection_fingerprint(connection), _latency_ms(started), "remote_object_ready")


def _probe_data_source_values(settings: Settings, payload: DataSourceConnectionPayload, credential: str | None) -> None:
    if payload.service_type == "HTTP_API":
        headers = {key: value for key, value in payload.headers.items() if key.lower() not in {"authorization", "cookie", "set-cookie"}}
        if payload.auth_mode == "bearer":
            headers["authorization"] = f"Bearer {credential or ''}"
        elif payload.auth_mode == "api_key_header" and payload.api_key_header_name:
            headers[payload.api_key_header_name] = credential or ""
        HTTPRemoteSourceClient().probe(url=payload.url or "", headers=headers, timeout_seconds=payload.timeout_seconds, verify_tls=payload.verify_tls, allowed_hosts=settings.http_source_allowed_hostnames, allowed_networks=settings.http_source_allowed_networks)
        return
    if not credential:
        raise AppError("data_source_credential_required", "Data source credential is required for live testing", status_code=422)
    if payload.service_type == "S3":
        config = _candidate_s3_config(payload, credential)
        S3ObjectStorage(config).object_status(bucket=payload.bucket or "", key=_object_key(payload.remote_path, payload.file_name))
        return
    _probe_file_protocol(payload.service_type, payload.host, payload.port, payload.username, credential, payload.remote_path, payload.file_name, payload.timeout_seconds, settings.sftp_known_hosts_path)


def _probe_file_protocol(service_type: str, host: str, port: int, username: str, credential: str, remote_path: str, file_name: str, timeout: int, known_hosts_path: str) -> None:
    arguments = {"host": host, "port": port, "username": username, "credential": credential, "remote_path": remote_path, "file_name": file_name, "timeout_seconds": timeout}
    if service_type == "FTP":
        FTPRemoteSourceClient().probe(**arguments)
    elif service_type == "FTPS":
        FTPSRemoteSourceClient().probe(**arguments)
    elif service_type == "SFTP":
        SFTPRemoteSourceClient().probe(**arguments, known_hosts_path=known_hosts_path)
    else:
        raise AppError("unsupported_protocol", "Data source protocol is not supported", status_code=422)


def _probe_http_model(model: AIModel, api_key: str | None) -> None:
    config = model.config or {}
    provider = model.provider.strip().lower()
    model_name = str(config.get("model_name") or model.name).strip()
    timeout = max(1, min(int(config.get("timeout_seconds") or config.get("timeout") or 30), 120))
    verify_tls = bool(config.get("verify_tls", True))
    if provider == "gemini":
        if not api_key:
            raise AppError("model_credential_required", "Model provider credential is required", status_code=422)
        base = _model_base_url(str(config.get("base_url") or model.endpoint or "https://generativelanguage.googleapis.com"))
        url = f"{base}/v1beta/models/{quote(model_name, safe='')}"
        headers = {"x-goog-api-key": api_key}
    elif provider == "claude":
        if not api_key:
            raise AppError("model_credential_required", "Model provider credential is required", status_code=422)
        base = _model_base_url(str(config.get("base_url") or model.endpoint or "https://api.anthropic.com"))
        url = f"{base}/v1/models/{quote(model_name, safe='')}"
        headers = {"x-api-key": api_key, "anthropic-version": str(config.get("anthropic_version") or "2023-06-01")}
    elif provider == "ollama":
        base = _model_base_url(str(config.get("base_url") or model.endpoint or ""))
        if not base:
            raise AppError("model_endpoint_required", "Model provider endpoint is required", status_code=422)
        url = f"{base}/api/tags"
        headers = {}
    else:
        base = _model_base_url(str(config.get("base_url") or model.endpoint or ""))
        if not base:
            raise AppError("model_endpoint_required", "Model provider endpoint is required", status_code=422)
        if not api_key and provider in {"openai", "vllm", "custom"}:
            raise AppError("model_credential_required", "Model provider credential is required", status_code=422)
        url = f"{base}/models" if not base.endswith("/models") else base
        headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with httpx.Client(timeout=timeout, verify=verify_tls, follow_redirects=False, trust_env=False) as client:
            response = client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise AppError("model_connection_timeout", "Model provider connection timed out", status_code=503) from exc
    except httpx.HTTPError as exc:
        raise AppError("model_connection_failed", "Model provider connection failed", status_code=503) from exc
    if 300 <= response.status_code < 400:
        raise AppError("model_redirect_not_allowed", "Model provider redirect is not allowed", status_code=422)
    if response.status_code in {401, 403}:
        raise AppError("model_authentication_failed", "Model provider authentication failed", status_code=503)
    if response.status_code >= 400:
        raise AppError("model_connection_failed", "Model provider rejected the readiness request", status_code=503, details={"status_code": response.status_code})
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppError("model_response_invalid", "Model provider returned invalid JSON", status_code=503) from exc
    if not _model_exists(payload, model_name, provider):
        raise AppError("model_not_available", "Configured model was not found at the provider", status_code=503)


def _model_exists(payload: object, model_name: str, provider: str) -> bool:
    if not isinstance(payload, dict):
        return False
    if provider in {"gemini", "claude"}:
        value = str(payload.get("name") or payload.get("id") or "")
        return value == model_name or value.endswith(f"/{model_name}")
    rows = payload.get("models") if provider == "ollama" else payload.get("data")
    if not isinstance(rows, list):
        return False
    names = {str(row.get("name") or row.get("model") or row.get("id") or "") for row in rows if isinstance(row, dict)}
    return model_name in names


def _model_base_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AppError("model_endpoint_invalid", "Model provider endpoint must be an HTTP(S) URL without credentials or query parameters", status_code=422)
    path = parsed.path.rstrip("/")
    for suffix in ("/chat/completions", "/embeddings", "/responses", "/models"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _resolve_model_credential(settings: Settings, model: AIModel) -> str | None:
    if model.api_key_secret_ref:
        return resolve_runtime_secret(settings, model.api_key_secret_ref)
    if model.api_key_encrypted:
        if settings.app_env == "production":
            raise AppError("legacy_model_credential_forbidden", "Legacy model credentials are not permitted in production", status_code=503)
        cipher = EnvelopeCipher(settings.encryption_key_bytes)
        for context in (f"ai-model:{model.id}", f"ai-model:{model.name}"):
            try:
                return cipher.decrypt(model.api_key_encrypted, context=context)
            except AppError:
                continue
        raise AppError("model_credential_invalid", "Model provider credential could not be decrypted", status_code=503)
    return None


def _resolve_candidate_credential(settings: Settings, credential: str | None, secret_ref: str | None) -> str | None:
    if secret_ref:
        return resolve_runtime_secret(settings, secret_ref)
    if credential and settings.app_env == "production":
        raise AppError("plaintext_runtime_credential_forbidden", "Plaintext runtime credentials are not permitted in production", status_code=422)
    return credential


def _candidate_s3_config(payload: DataSourceConnectionPayload, credential: str) -> S3ClientConfig:
    stripped = credential.strip()
    try:
        values = json.loads(stripped) if stripped.startswith("{") else {"access_key": payload.username, "secret_key": credential}
    except json.JSONDecodeError as exc:
        raise AppError("s3_connection_credential_invalid", "S3 credential JSON is invalid", status_code=422) from exc
    if not isinstance(values, dict) or not values.get("access_key") or not values.get("secret_key"):
        raise AppError("s3_connection_credential_invalid", "S3 credential is incomplete", status_code=422)
    return S3ClientConfig(endpoint_url=payload.host, region=payload.region or "", access_key=str(values["access_key"]), secret_key=str(values["secret_key"]), verify_tls=payload.verify_tls, session_token=str(values.get("session_token") or "") or None)


def _candidate_fingerprint(payload: DataSourceConnectionPayload, *, credential_configured: bool) -> str:
    import hashlib

    values = payload.model_dump(exclude={"credential"}, mode="json")
    values["credential_configured"] = credential_configured
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _object_key(remote_path: str, file_name: str) -> str:
    return str(PurePosixPath(remote_path.strip("/") or ".") / file_name).removeprefix("./")


def _probe_local_command(command: list[str], *, timeout_seconds: int) -> None:
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout_seconds, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise AppError("local_model_provider_unavailable", "Local model provider is unavailable", status_code=503) from exc
    if result.returncode != 0:
        raise AppError("local_model_provider_unavailable", "Local model provider readiness check failed", status_code=503)


def _latency_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))
