from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.core.config import Settings, neo4j_driver_options


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
        "opensearch_password": "production-search-password",
        "opensearch_verify_tls": True,
        "opensearch_staging_live_write": True,
        "neo4j_password": "production-neo4j-password",
        "oidc_issuer_url": "https://identity.example.test/realms/nomosmart",
        "oidc_client_secret": "production-oidc-secret",
        "keycloak_admin_api_url": "https://identity.example.test",
        "keycloak_admin_internal_url": "http://keycloak:8080/identity",
        "keycloak_sync_client_secret": "production-sync-secret",
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
    assert settings.keycloak_admin_endpoint == "http://keycloak:8080/identity"


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
        ({"pandoc_sandbox_command": ""}, "PANDOC_SANDBOX_COMMAND"),
        ({"deployment_bootstrap_release": ""}, "DEPLOYMENT_BOOTSTRAP_RELEASE"),
    ],
)
def test_unsafe_production_configuration_is_rejected(overrides: dict[str, object], expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        production_settings(**overrides)


def test_development_configuration_keeps_local_service_defaults() -> None:
    settings = Settings(_env_file=None, app_env="development")
    assert settings.oidc_issuer_url.startswith("http://127.0.0.1")
    assert settings.opensearch_username.get_secret_value() == "nomosmart"


def test_production_neo4j_tls_requires_and_loads_operator_ca(tmp_path: Path) -> None:
    ca = tmp_path / "neo4j-ca.crt"
    ca.write_text("placeholder certificate", encoding="utf-8")
    settings = production_settings(
        neo4j_uri="neo4j+s://neo4j.example.test:7687",
        neo4j_ca_cert_path=str(ca),
    )
    assert type(neo4j_driver_options(settings)["trusted_certificates"]).__name__ == "TrustCustomCAs"

    with pytest.raises(ValidationError, match="NEO4J_CA_CERT_PATH"):
        production_settings(neo4j_uri="neo4j+s://neo4j.example.test:7687")


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
    assert backend["PANDOC_SANDBOX_COMMAND"] == "bwrap"
    assert backend["OPENSEARCH_VERIFY_TLS"] == "true"
    assert production["global"]["publicOrigin"].startswith("https://")
    assert backend["CORS_ALLOWED_ORIGINS"].startswith("https://")
    assert backend["FRONTEND_APP_ORIGIN"].startswith("https://")
    assert frontend["NEXT_PUBLIC_APP_ORIGIN"].startswith("https://")
    assert frontend["NEXT_PUBLIC_OIDC_ISSUER_URL"].startswith("https://")
    assert production["ingress"]["enabled"] is True
    assert production["ingress"]["tls"]
    assert (chart / "values.schema.json").is_file()
