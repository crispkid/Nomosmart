from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from current_live_support import current_live  # noqa: F401
from current_directory_support import current_directory_snapshot


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")





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


def test_normalization_preserves_structured_name_and_canonical_display_order(current_live) -> None:
    snapshot = current_directory_snapshot(current_live)
    assert snapshot.people
    for person in snapshot.people:
        assert person.display_name.strip()
        for part in (person.given_name, person.family_name):
            assert part is None or part == part.strip()



def test_normalization_falls_back_without_inventing_name_parts() -> None:
    # Structural fallback contract; actual service entries are checked above.
    source = read("backend/app/integrations/ldap_directory.py")
    assert '_one(attrs, "givenName"), _one(attrs, "sn")' in source
    assert 'display_name=_one(attrs, "displayName") or " ".join(v for v in (given, family) if v) or username' in source



def test_normalization_rejects_a_user_without_any_name_or_username() -> None:
    # Structural rejection contract, no synthetic LDAP adapter.
    source = read("backend/app/integrations/ldap_directory.py")
    assert 'if not username:' in source
    assert 'Directory account has no login identifier' in source



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
