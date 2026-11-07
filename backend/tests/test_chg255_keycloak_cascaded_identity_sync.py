from __future__ import annotations
from current_live_support import current_live  # noqa: F401

from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import Settings
from app.core.errors import AppError


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


def test_keycloak_client_uses_explicit_user_and_group_sync_contracts():
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: upstream user-storage and mapper cascade removed; current acceptance: test_worker_cascades_saved_scope_before_atomic_reconciliation')


def test_worker_cascades_saved_scope_before_atomic_reconciliation(current_live) -> None:
    # Retain the historical case ID, checking the current direct-directory worker.
    client = current_live.actor("system_viewer")
    settings = client.get("system/identity-settings")
    assert settings.status_code == 200
    configuration = settings.json()
    run = current_live.sync_receipt()
    assert run["requested_scope"] == configuration["configuration"]["sync_scope"]
    assert run["source"] in {"ldap", "ad"}
    from uuid import UUID
    from app.db.models import IdentitySyncRun
    with current_live.database() as session:
        saved_run = session.get(IdentitySyncRun, UUID(run["id"]))
        assert saved_run is not None and saved_run.configuration_revision == configuration["revision"]
    assert run["phase"] == "completed" and run["error_code"] is None


def test_scope_aware_reconciliation_and_additive_api_contract_are_present() -> None:
    reconciliation = read("backend/app/services/directory_sync.py")
    schemas = read("backend/app/api/schemas.py")
    route = read("backend/app/api/routes/identity.py")
    assert 'people_selected = run.requested_scope in {"people", "people_and_groups"}' in reconciliation
    assert 'groups_selected = run.requested_scope in {"groups", "people_and_groups"}' in reconciliation
    assert "if people_selected:" in reconciliation
    assert "if groups_selected:" in reconciliation
    assert "class IdentitySyncProviderResultResponse" in schemas
    assert "provider_results: list[IdentitySyncProviderResultResponse]" in schemas
    assert "selectinload(IdentitySyncRun.provider_results)" in route


def test_provider_timeout_is_typed_and_externalized() -> None:
    # Current network deadline replaces the retired per-provider Admin API budget.
    settings = Settings(_env_file=None)
    assert 0 < settings.auth_network_timeout_seconds <= 60
    assert "identity_sync_keycloak_provider_timeout_seconds" not in Settings.model_fields
    for value in (0, 61):
        with pytest.raises(ValueError):
            Settings(_env_file=None, auth_network_timeout_seconds=value)
    assert "IDENTITY_SYNC_RUN_TIMEOUT_SECONDS" in read("docker-compose.yml")
    assert "IDENTITY_SYNC_RUN_TIMEOUT_SECONDS" in read("deploy/helm/nomosmart/values.yaml")
