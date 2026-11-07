from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import ip_network
from pathlib import Path
from uuid import uuid4

import pytest

from app.api.routes.data_sources import _validate_data_source_payload
from app.api.schemas import DataSourceConnectionPayload
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AIModel, DataConnection
from app.domain.connection_evidence import ai_model_connection_fingerprint, data_connection_fingerprint, invalidate_model_connection_evidence
from app.domain.connection_probes import probe_ai_model
from app.integrations.remote_sources import _pinned_http_target


def test_http_source_blocks_private_and_metadata_addresses_by_default() -> None:
    for url in ("http://127.0.0.1/private", "http://10.20.30.40/internal", "http://169.254.169.254/latest/meta-data"):
        with pytest.raises(AppError) as blocked:
            _pinned_http_target(url)
        assert blocked.value.code == "http_source_ssrf_blocked"


def test_http_source_requires_explicit_allowlist_and_pins_destination() -> None:
    pinned, host, sni = _pinned_http_target("https://10.20.30.40:8443/path?q=1", allowed_networks=(ip_network("10.20.30.0/24"),))
    assert pinned == "https://10.20.30.40:8443/path?q=1"
    assert host == "10.20.30.40:8443"
    assert sni == "10.20.30.40"
    public, public_host, _ = _pinned_http_target("https://8.8.8.8/resource")
    assert public == "https://8.8.8.8/resource"
    assert public_host == "8.8.8.8"


def test_connection_fingerprints_change_without_containing_plaintext_secret() -> None:
    model = AIModel(id=uuid4(), name="embedding-live", model_type="Embedding", provider="OpenAI", endpoint="https://models.example.test/v1", api_key_encrypted="ciphertext-secret", config={"model_name": "embed-1", "verify_tls": True}, config_version=1, is_active=True, is_default=False)
    first = ai_model_connection_fingerprint(model)
    assert "ciphertext-secret" not in first
    model.endpoint = "https://models-2.example.test/v1"
    assert ai_model_connection_fingerprint(model) != first

    connection = DataConnection(id=uuid4(), project_id=uuid4(), service_type="S3", name="source", connection_metadata={"endpoint_url": "https://s3.example.test", "region": "us-east-1", "bucket": "source", "verify_tls": True}, credential_encrypted="encrypted-s3-secret", source_identity={"remote_path": "docs", "file_name": "a.pdf"}, schedule_mode="once", timezone="Asia/Taipei", enabled=True, lock_version=1)
    source_first = data_connection_fingerprint(connection)
    connection.connection_metadata = {**connection.connection_metadata, "bucket": "source-2"}
    assert data_connection_fingerprint(connection) != source_first
    assert "encrypted-s3-secret" not in source_first


def test_model_evidence_becomes_stale_after_configuration_change() -> None:
    model = AIModel(id=uuid4(), name="chat", model_type="Chat", provider="OpenAI", endpoint="https://models.example.test/v1", config={"model_name": "chat-1"}, config_version=1, is_active=True, is_default=False, last_test_status="success", last_tested_at=datetime.now(UTC), last_test_fingerprint="a" * 64, last_test_latency_ms=10, last_test_detail_code="provider_model_ready")
    invalidate_model_connection_evidence(model)
    assert model.last_test_status == "stale"
    assert model.last_test_fingerprint is None
    assert model.last_test_detail_code == "configuration_changed"


def test_missing_model_endpoint_or_credential_never_reports_ready() -> None:
    model = AIModel(id=uuid4(), name="missing", model_type="Embedding", provider="Custom", endpoint=None, config={"model_name": "missing"}, config_version=1, is_active=True, is_default=False)
    with pytest.raises(AppError) as missing:
        probe_ai_model(Settings(_env_file=None, app_encryption_key="a" * 64), model)
    assert missing.value.code == "model_endpoint_required"


def test_sftp_requires_host_key_verification_and_s3_requires_endpoint_region() -> None:
    settings = Settings(_env_file=None, app_encryption_key="a" * 64)
    common = {"name": "source", "host": "internal.example.test", "port": 22, "username": "user", "credential": "secret", "remote_path": "docs", "file_name": "a.pdf"}
    with pytest.raises(AppError) as host_key:
        _validate_data_source_payload(DataSourceConnectionPayload(service_type="SFTP", verify_host_key=False, **common), settings=settings)
    assert host_key.value.code == "sftp_host_key_verification_required"
    with pytest.raises(AppError) as region:
        _validate_data_source_payload(DataSourceConnectionPayload(service_type="S3", bucket="source", region=None, **common), settings=settings)
    assert region.value.code == "s3_connection_config_required"


def test_v022_and_routes_remove_configuration_only_success() -> None:
    root = Path(__file__).parents[2]
    migration = (root / "sql/migrations/V022__connection_test_evidence.sql").read_text(encoding="utf-8")
    models_route = (root / "backend/app/api/routes/models.py").read_text(encoding="utf-8")
    data_route = (root / "backend/app/api/routes/data_sources.py").read_text(encoding="utf-8")
    provider = (root / "backend/app/domain/ai_provider.py").read_text(encoding="utf-8")
    assert "last_test_fingerprint" in migration and "last_test_actor_id" in migration
    assert "adapter_ready" not in models_route
    assert "configuration_validated" not in data_route
    assert "probe_ai_model" in models_route
    assert "probe_data_source_candidate" in data_route
    gemini = provider.split("def _invoke_gemini", 1)[1].split("def _invoke_claude", 1)[0]
    assert '"x-goog-api-key"' in gemini
    assert "urlencode" not in gemini
