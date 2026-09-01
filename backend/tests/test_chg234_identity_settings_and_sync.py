from __future__ import annotations

from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.errors import AppError
from app.domain.directory_filters import validate_directory_filter


ROOT = BACKEND.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_directory_filter_uses_structured_rfc4515_parser() -> None:
    assert validate_directory_filter("(&(objectClass=person)(mail=*))") == "(&(objectClass=person)(mail=*))"
    assert validate_directory_filter("") == ""
    for value in ("(uid=test)(mail=*)", "(&(uid=test)", "(uid=bad\\zz)", "(uid=test)\x00"):
        with pytest.raises(AppError) as caught:
            validate_directory_filter(value)
        assert caught.value.code in {"directory_filter_invalid", "directory_filter_too_long"}
    with pytest.raises(AppError) as too_long:
        validate_directory_filter(f"(cn={'a' * 2050})")
    assert too_long.value.code == "directory_filter_too_long"


def test_identity_provider_api_is_allowlisted_and_audited_without_filter_plaintext() -> None:
    route = read("backend/app/api/routes/identity_settings.py")
    client = read("backend/app/integrations/keycloak.py")
    assert "DirectoryProviderResponse" in route
    assert "customUserSearchFilter" in client
    assert 'config["customUserSearchFilter"]' in client
    for forbidden in ("connectionUrl", "usersDn", "bindDn", "bindCredential"):
        assert forbidden not in route
    assert '"old_filter_hash"' in route
    assert '"new_filter_hash"' in route
    assert '"custom_user_search_filter": validated_filter' not in route


def test_sync_recovery_contract_has_durable_lease_and_runtime_health() -> None:
    migration = read("sql/migrations/V028__identity_settings_truth_and_sync_recovery.sql")
    jobs = read("backend/app/services/identity_sync_jobs.py")
    worker = read("backend/app/worker.py")
    compose = read("docker-compose.yml")
    assert all(column in migration for column in ("queued_at", "heartbeat_at", "lease_token"))
    assert "uq_identity_sync_runs_single_active" in migration
    assert "identity_sync_worker_unavailable" in read("backend/app/api/routes/identity.py")
    assert "recover_stale_identity_runs" in jobs
    assert "run.lease_token != parsed_lease" in worker
    assert "record-runtime-heartbeat" in worker
    assert "celery-worker" in compose and "healthcheck" in compose


def test_keycloak_bootstrap_reconciles_exact_reauth_callback() -> None:
    bootstrap = read("backend/app/deployment/bootstrap.py")
    keycloak = read("backend/app/integrations/keycloak.py")
    callback = "/api/backend/system/identity-settings/reauth/callback"
    assert callback in bootstrap
    assert callback in keycloak
    assert "actual | required" in bootstrap
    assert '"manage-realm"' in bootstrap
