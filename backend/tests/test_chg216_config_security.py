from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

import pytest
import yaml
from pydantic import ValidationError

from app.core.config import Settings, neo4j_driver_options
from app.security.auth_configuration import OidcConfiguration, ProtocolConfiguration


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "cors_allowed_origins": "https://nomosmart.example.test",
        "frontend_app_origin": "https://nomosmart.example.test",
        "database_url": "postgresql+psycopg2://nomosmart:strong-password@db.example.test:5432/nomosmart",
        "s3_endpoint_url": "https://s3.example.test",
        "s3_access_key_id": "production-access-key",
        "s3_secret_access_key": "production-secret-key",
        "s3_use_ssl": True,
        "s3_verify_tls": True,
        "opensearch_url": "https://search.example.test:9200",
        # The configured live test service can use a different account. This
        # validation case provides its own input; defaults are tested separately
        # in the clean subprocess below, without changing any service setting.
        "opensearch_username": "nomosmart",
        "opensearch_password": "production-search-password",
        "opensearch_verify_tls": True,
        "opensearch_staging_live_write": True,
        "neo4j_password": "production-neo4j-password",
        "oidc_issuer_url": "https://identity.example.test/realms/nomosmart",
        "oidc_client_secret": "production-oidc-secret",
        "app_encryption_key": "a" * 64,
        "deployment_bootstrap_release": "production-2026.07.14",
        "break_glass_runbook_uri": "https://runbooks.example.test/nomosmart/break-glass",
        "break_glass_alerting_evidence": "production-alert-route",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_production_configuration_is_accepted() -> None:
    settings = production_settings()
    assert settings.app_env == "production"
    assert settings.opensearch_username.get_secret_value() == "nomosmart"
    assert "keycloak_admin_internal_url" not in Settings.model_fields


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"app_encryption_key": "0" * 64}, "all-zero"),
        ({"oidc_issuer_url": "http://127.0.0.1:8080/realms/nomosmart"}, "OIDC_ISSUER_URL"),
        ({"cors_allowed_origins": "https://nomosmart.example.test,http://localhost:3000"}, "CORS_ALLOWED_ORIGINS"),
        ({"frontend_app_origin": "http://localhost:3000"}, "FRONTEND_APP_ORIGIN"),
        ({"s3_use_ssl": False}, "S3_USE_SSL"),
        ({"s3_verify_tls": False}, "S3_VERIFY_TLS"),
        ({"opensearch_verify_tls": False}, "OPENSEARCH_VERIFY_TLS"),
        ({"opensearch_staging_live_write": False}, "OPENSEARCH_STAGING_LIVE_WRITE"),
        ({"oidc_client_secret": "CHANGE_ME_OIDC_SECRET"}, "OIDC_CLIENT_SECRET"),
        ({"database_url": "postgresql+psycopg2://postgres:postgres@db.example.test:5432/nomosmart"}, "DATABASE_URL"),
        ({"deployment_bootstrap_release": ""}, "DEPLOYMENT_BOOTSTRAP_RELEASE"),
    ],
)
def test_unsafe_production_configuration_is_rejected(overrides: dict[str, object], expected: str) -> None:
    if "oidc_issuer_url" in overrides:
        # Active OIDC settings live in the typed protocol configuration.
        with pytest.raises(ValidationError, match="HTTPS issuer"):
            OidcConfiguration(issuer=overrides["oidc_issuer_url"], client_id="owned-test-client")
    elif "oidc_client_secret" in overrides:
        # Plaintext credentials cannot be embedded in active configuration.
        root = Path(__file__).resolve().parents[2]
        candidate = __import__("json").loads((root / "deploy/docker/auth-bootstrap.oidc.example.json").read_text())["configuration"]
        with pytest.raises(ValidationError) as rejected:
            ProtocolConfiguration.model_validate({**candidate, **overrides})
        assert any(row['loc']==('oidc_client_secret',) and row['type']=='extra_forbidden'
                   for row in rejected.value.errors())
    else:
        with pytest.raises(ValidationError, match=expected):
            production_settings(**overrides)


def test_development_configuration_keeps_local_service_defaults() -> None:
    # _env_file=None does not disable environment variables. Test actual defaults
    # in a clean process without overwriting this suite's strict-TLS endpoints.
    backend = Path(__file__).resolve().parents[1]
    env = {key: os.environ[key] for key in ("PATH", "HOME", "SYSTEMROOT") if key in os.environ}
    env["PYTHONPATH"] = str(backend)
    subprocess.run([sys.executable, "-c", "from app.core.config import Settings; "
        "s=Settings(_env_file=None, app_env='development'); "
        "assert s.oidc_issuer_url.startswith('http://127.0.0.1'); "
        "assert s.opensearch_username.get_secret_value() == 'nomosmart'"],
        env=env, cwd=backend.parent, check=True, capture_output=True, text=True)


def test_production_neo4j_tls_accepts_system_or_custom_ca(tmp_path: Path) -> None:
    ca = tmp_path / "neo4j-ca.crt"
    ca.write_text("placeholder certificate", encoding="utf-8")
    settings = production_settings(
        neo4j_uri="neo4j+s://neo4j.example.test:7687",
        neo4j_ca_cert_path=str(ca),
    )
    assert type(neo4j_driver_options(settings)["trusted_certificates"]).__name__ == "TrustCustomCAs"

    system = production_settings(neo4j_uri="neo4j+s://neo4j.example.test:7687", neo4j_ca_cert_path="")
    assert neo4j_driver_options(system) == {"encrypted": True}
    with pytest.raises(ValidationError, match="NEO4J_CA_CERT_PATH"):
        production_settings(neo4j_uri="bolt://neo4j.example.test:7687", neo4j_ca_cert_path=str(ca))
    assert not any(name.startswith("pandoc_") for name in production_settings(pandoc_command="", pandoc_timeout_seconds="retired").model_fields)


def test_helm_production_overlay_replaces_unsafe_development_defaults() -> None:
    chart = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "nomosmart"
    base = yaml.safe_load((chart / "values.yaml").read_text(encoding="utf-8"))
    production = yaml.safe_load((chart / "values-prod.yaml").read_text(encoding="utf-8"))
    backend = {**base["backend"]["env"], **production["backend"]["env"]}
    frontend = {**base["frontend"]["env"], **production["frontend"]["env"]}

    assert base["backend"]["env"]["APP_ENV"] == "development"
    assert backend["APP_ENV"] == "production"
    assert "MALWARE_SCANNER_MODE" not in backend
    assert backend["OPENSEARCH_STAGING_LIVE_WRITE"] == "true"
    assert backend["S3_USE_SSL"] == backend["S3_VERIFY_TLS"] == "true"
    assert "S3_QUARANTINE_BUCKET" not in backend
    assert not any(name.startswith("PANDOC_") for name in backend)
    assert backend["OPENSEARCH_VERIFY_TLS"] == "true"
    assert production["global"]["publicOrigin"].startswith("https://")
    assert backend["CORS_ALLOWED_ORIGINS"].startswith("https://")
    assert backend["FRONTEND_APP_ORIGIN"].startswith("https://")
    assert frontend["NEXT_PUBLIC_APP_ORIGIN"].startswith("https://")
    assert not any(name.startswith(("NEXT_PUBLIC_OIDC_", "FRONTEND_OIDC_")) for name in frontend)
    # No environment is silently given an authentication mode or directory.
    # Operators provide the typed configuration through the deployment input.
    assert base["authentication"]["bootstrapConfiguration"] == {}
    example = __import__("json").loads((chart.parents[1] / "docker/auth-bootstrap.oidc.example.json").read_text())
    assert ProtocolConfiguration.model_validate(example["configuration"]).auth_mode == "oidc"
    assert production["ingress"]["enabled"] is True
    assert production["ingress"]["tls"]
    assert (chart / "values.schema.json").is_file()
