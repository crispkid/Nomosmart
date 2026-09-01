from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_chg233_migration_enforces_origin_sources_and_independent_mapping_uniqueness() -> None:
    migration = read("sql/migrations/V027__local_roles_ldap_group_mapping.sql")

    assert "identity_origin IN ('ldap', 'ad', 'keycloak_local')" in migration
    assert "source IN ('manual', 'external_sync', 'break_glass')" in migration
    assert "UNIQUE (external_group_id)" in migration
    assert "UNIQUE (role_id)" in migration
    assert "external_group.identity_origin = 'ldap'" in migration
    assert "name IN ('project-owner', 'knowledge-editor', 'reviewer')" in migration
    assert "CHG-233 cannot choose among ambiguous external group role mappings" in migration


def test_chg233_keycloak_mapper_lookup_is_scoped_to_the_unique_ldap_provider() -> None:
    integration = read("backend/app/integrations/keycloak.py")
    bootstrap = read("backend/app/deployment/bootstrap.py")

    for source in (integration, bootstrap):
        assert "org.keycloak.storage.UserStorageProvider" in source
        assert 'providerId") == "ldap"' in source
        assert '"parent"' in source or "parent={provider_id}" in source
        assert "group-ldap-mapper" in source
        assert "Exactly one LDAP" in source or "keycloak_ldap_provider_invalid" in source


@pytest.mark.parametrize(
    "relative_path",
    (
        "backend/.env.example",
        "deploy/docker/nomosmart.env.example",
        "docker-compose.yml",
        "deploy/helm/nomosmart/values.yaml",
        "deploy/helm/nomosmart/values.schema.json",
    ),
)
def test_chg233_deployment_contract_exposes_ldap_path_and_break_glass_username(relative_path: str) -> None:
    source = read(relative_path)
    assert "KEYCLOAK_LDAP_GROUP_PATH" in source
    assert "BREAK_GLASS_USERNAME" in source


def test_chg233_api_uses_role_scoped_mapping_and_retires_bulk_write() -> None:
    roles = read("backend/app/api/routes/roles.py")
    identity = read("backend/app/api/routes/identity.py")
    compatibility = read("API_COMPATIBILITY.md")

    assert '@router.put("/{role_id}/external-group-mapping"' in roles
    assert "acquire_identity_membership_lock(session)" in roles
    assert "reconcile_external_role_memberships(session, role_ids=(role.id,))" in roles
    assert '@router.put("/external-group-role-mappings"' not in identity
    assert "PUT /api/v1/roles/{role_id}/external-group-mapping" in compatibility


def test_chg233_break_glass_reconciliation_requires_local_protected_group_membership() -> None:
    source = read("backend/app/services/identity_sync.py")

    assert 'item.auth_source == "keycloak"' in source
    assert '== "/system-admin"' in source
    assert "is_protected_group_member" in source
    assert "break_glass_membership_unavailable" in source
