from __future__ import annotations

from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.keycloak import KeycloakAdminClient


ROOT = BACKEND.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v043_persists_scope_phase_and_redacted_provider_evidence() -> None:
    migration = read("sql/migrations/V043__keycloak_cascaded_identity_sync.sql")
    assert all(
        value in migration
        for value in (
            "requested_scope",
            "phase",
            "identity_sync_provider_results",
            "user_sync_status",
            "group_sync_status",
            "users_added",
            "users_failed",
            "uq_identity_sync_provider_results_run_provider",
        )
    )
    for forbidden in ("bindCredential", "customUserSearchFilter", "usersDn", "connectionUrl", "access_token"):
        assert forbidden not in migration


def test_keycloak_client_uses_explicit_user_and_group_sync_contracts() -> None:
    client = read("backend/app/integrations/keycloak.py")
    assert 'params={"action": "triggerFullSync"}' in client
    assert 'params={"direction": "fedToKeycloak"}' in client
    assert "/user-storage/{safe_provider_id}/mappers/{safe_mapper_id}/sync" in client
    assert "keycloak_provider_sync_failed" in client
    assert "keycloak_group_mapper_sync_failed" in client
    assert KeycloakAdminClient._sync_counter({"added": 2}, "added") == 2
    with pytest.raises(AppError) as caught:
        KeycloakAdminClient._sync_counter({"added": "2"}, "added")
    assert caught.value.code == "keycloak_invalid_response"
    with pytest.raises(AppError) as caught:
        KeycloakAdminClient._sync_counter({"failed": -1}, "failed")
    assert caught.value.code == "keycloak_invalid_response"


def test_worker_cascades_saved_scope_before_atomic_reconciliation() -> None:
    worker = read("backend/app/worker.py")
    assert "client.list_directory_providers" in worker
    assert "client.trigger_directory_user_sync(provider.id)" in worker
    assert "client.trigger_directory_group_sync(provider.id, group_mappers[0].id)" in worker
    assert 'run.phase = "snapshot_fetch"' in worker
    assert 'run.phase = "reconciliation"' in worker
    assert "requested_scope=run.requested_scope" in worker
    assert "_IdentityRunHeartbeat" in worker
    assert "provider_result.error_code = safe_error_code" in worker
    jobs = read("backend/app/services/identity_sync_jobs.py")
    assert "def effective_identity_sync_scope" in jobs
    assert '(current.configuration or {}).get("sync_scope")' in jobs


def test_scope_aware_reconciliation_and_additive_api_contract_are_present() -> None:
    reconciliation = read("backend/app/services/identity_sync.py")
    schemas = read("backend/app/api/schemas.py")
    route = read("backend/app/api/routes/identity.py")
    assert 'apply_people = requested_scope in {"people", "people_and_groups"}' in reconciliation
    assert 'apply_groups = requested_scope in {"groups", "people_and_groups"}' in reconciliation
    assert "if apply_people:" in reconciliation
    assert "if apply_groups:" in reconciliation
    assert "class IdentitySyncProviderResultResponse" in schemas
    assert "provider_results: list[IdentitySyncProviderResultResponse]" in schemas
    assert "selectinload(IdentitySyncRun.provider_results)" in route
    assert "requested_scope=\"people\"" in read("backend/scripts/chg255_live_acceptance.py")
    assert "requested_scope=\"groups\"" in read("backend/scripts/chg255_live_acceptance.py")


def test_provider_timeout_is_typed_and_externalized() -> None:
    settings = Settings(_env_file=None)
    assert settings.identity_sync_keycloak_provider_timeout_seconds == 600
    for value in (29, 1801):
        with pytest.raises(ValueError):
            Settings(_env_file=None, identity_sync_keycloak_provider_timeout_seconds=value)
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            identity_sync_run_timeout_seconds=300,
            identity_sync_keycloak_provider_timeout_seconds=600,
        )
    assert "IDENTITY_SYNC_KEYCLOAK_PROVIDER_TIMEOUT_SECONDS" in read("docker-compose.yml")
    assert "IDENTITY_SYNC_KEYCLOAK_PROVIDER_TIMEOUT_SECONDS=600" in read("deploy/docker/nomosmart.env.example")
    assert "IDENTITY_SYNC_KEYCLOAK_PROVIDER_TIMEOUT_SECONDS" in read("deploy/helm/nomosmart/values.yaml")
