from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def test_chg291_role_validator_accepts_exactly_one_project_role() -> None:
    from app.api.routes.projects import _validate_roles

    assert _validate_roles(["owner"]) == "owner"
    assert _validate_roles(["editor"]) == "editor"
    assert _validate_roles(["viewer"]) == "viewer"


@pytest.mark.parametrize("roles", ([], ["viewer", "viewer"], ["editor", "viewer"], ["owner", "editor", "viewer"]))
def test_chg291_role_validator_rejects_non_single_cardinality(roles: list[str]) -> None:
    from app.api.routes.projects import _validate_roles
    from app.core.errors import AppError

    with pytest.raises(AppError) as rejected:
        _validate_roles(roles)
    assert rejected.value.code == "invalid_project_role_cardinality"
    assert rejected.value.status_code == 422


def test_chg291_role_validator_rejects_unknown_role() -> None:
    from app.api.routes.projects import _validate_roles
    from app.core.errors import AppError

    with pytest.raises(AppError) as rejected:
        _validate_roles(["maintainer"])
    assert rejected.value.code == "invalid_project_role"
    assert rejected.value.status_code == 422


@pytest.mark.parametrize(
    ("roles", "expected"),
    (
        ({"viewer"}, "viewer"),
        ({"viewer", "editor"}, "editor"),
        ({"viewer", "editor", "owner"}, "owner"),
        (set(), None),
    ),
)
def test_chg291_legacy_role_projection_uses_migration_precedence(roles: set[str], expected: str | None) -> None:
    from app.security.project_roles import canonical_project_role

    assert canonical_project_role(roles) == expected


def test_chg291_model_declares_one_member_row_per_project_user() -> None:
    from app.db.models import ProjectMember

    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in ProjectMember.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("project_id", "user_id") in unique_column_sets


def test_chg291_v049_normalizes_roles_and_adds_database_guard() -> None:
    migration_path = ROOT / "sql" / "migrations" / "V049__exclusive_project_member_role.sql"
    migration = migration_path.read_text(encoding="utf-8")

    assert "owner > editor > viewer" in migration
    assert "uq_project_members_project_user" in migration
    assert "UNIQUE (project_id, user_id)" in migration
    assert "project_members" in migration and "project_owners" in migration
    assert "project_without_owner" in migration
    assert "migration.chg291.exclusive_project_member_role" in migration
