from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.errors import AppError
from app.integrations.keycloak import KeycloakSnapshot
from app.services.identity_sync import normalize_snapshot


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def snapshot(user: dict[str, object]) -> KeycloakSnapshot:
    return KeycloakSnapshot(users=(user,), groups=(), user_group_ids={str(user["id"]): frozenset()})


def load_reconciler():
    path = ROOT / "deploy/docker/ldap-test/reconcile_keycloak.py"
    spec = importlib.util.spec_from_file_location("chg267_reconcile_keycloak", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mapper(component_id: str, model_attribute: str, ldap_attribute: str) -> dict[str, object]:
    return {
        "id": component_id,
        "name": model_attribute,
        "providerId": "user-attribute-ldap-mapper",
        "providerType": "org.keycloak.storage.ldap.mappers.LDAPStorageMapper",
        "parentId": "provider-id",
        "config": {
            "user.model.attribute": [model_attribute],
            "ldap.attribute": [ldap_attribute],
        },
    }


def test_normalization_preserves_structured_name_and_canonical_display_order() -> None:
    users, _ = normalize_snapshot(snapshot({
        "id": "user05-id",
        "username": "user05",
        "firstName": " Jam ",
        "lastName": " Liu ",
        "displayName": "Jam Liu Liu",
        "enabled": True,
        "federationLink": "provider-id",
        "attributes": {},
    }))
    assert users[0].given_name == "Jam"
    assert users[0].family_name == "Liu"
    assert users[0].display_name == "Jam Liu"


def test_normalization_falls_back_without_inventing_name_parts() -> None:
    users, _ = normalize_snapshot(snapshot({
        "id": "legacy-id",
        "username": "legacy",
        "displayName": "Legacy Display",
        "enabled": True,
        "attributes": {},
    }))
    assert users[0].given_name is None
    assert users[0].family_name is None
    assert users[0].display_name == "Legacy Display"


def test_normalization_rejects_a_user_without_any_name_or_username() -> None:
    with pytest.raises(AppError) as caught:
        normalize_snapshot(snapshot({"id": "invalid-id", "enabled": True, "attributes": {}}))
    assert caught.value.code == "identity_snapshot_invalid"


def test_mapper_plan_targets_only_first_name_cn_and_preserves_last_name_sn() -> None:
    reconciler = load_reconciler()
    plan = reconciler.person_name_mapper_plan([
        mapper("first-id", "firstName", "cn"),
        mapper("last-id", "lastName", "sn"),
    ])
    assert plan["first_mapper_id"] == "first-id"
    assert plan["first_ldap_attribute"] == "cn"
    assert plan["last_mapper_id"] == "last-id"
    assert plan["last_ldap_attribute"] == "sn"
    assert plan["requires_change"] is True

    already_correct = reconciler.person_name_mapper_plan([
        mapper("first-id", "firstName", "givenName"),
        mapper("last-id", "lastName", "sn"),
    ])
    assert already_correct["first_mapper_id"] == "first-id"
    assert already_correct["requires_change"] is False


@pytest.mark.parametrize(
    "rows",
    [
        [mapper("first-id", "firstName", "mail"), mapper("last-id", "lastName", "sn")],
        [mapper("first-id", "firstName", "cn"), mapper("last-id", "lastName", "surname")],
        [mapper("first-a", "firstName", "cn"), mapper("first-b", "firstName", "cn"), mapper("last-id", "lastName", "sn")],
    ],
)
def test_mapper_plan_fails_closed_on_unexpected_or_ambiguous_state(rows: list[dict[str, object]]) -> None:
    with pytest.raises(RuntimeError):
        load_reconciler().person_name_mapper_plan(rows)


def test_v045_and_api_contracts_are_additive() -> None:
    migration = read("sql/migrations/V045__structured_person_names.sql")
    model = read("backend/app/db/models.py")
    schemas = read("backend/app/api/schemas.py")
    frontend_api = read("frontend/src/lib/api.ts")
    assert "ADD COLUMN given_name varchar(255)" in migration
    assert "ADD COLUMN family_name varchar(255)" in migration
    assert "DROP COLUMN" not in migration.upper()
    assert "given_name: Mapped[str | None]" in model
    assert "family_name: Mapped[str | None]" in model
    assert "submitter_given_name" in schemas
    assert "submitter_family_name" in schemas
    assert "given_name: string | null" in frontend_api
    assert "family_name: string | null" in frontend_api


def test_all_current_person_name_surfaces_use_shared_formatter() -> None:
    expected_surfaces = (
        "frontend/src/components/AuthProvider.tsx",
        "frontend/src/components/SystemManagementWorkspace.tsx",
        "frontend/src/app/project/[id]/import/page.tsx",
        "frontend/src/app/approve/page.tsx",
        "frontend/src/app/approve/[approvalTaskId]/page.tsx",
    )
    for path in expected_surfaces:
        assert "formatPersonName" in read(path), path
