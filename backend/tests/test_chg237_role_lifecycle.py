from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_chg237_migration_adds_tombstones_partial_uniqueness_and_state_constraint() -> None:
    migration = read("sql/migrations/V030__local_role_lifecycle.sql")

    assert "ADD COLUMN deleted_at timestamptz" in migration
    assert "ADD COLUMN deleted_by uuid REFERENCES users(id)" in migration
    assert "DROP CONSTRAINT roles_name_key" in migration
    assert "CHECK (deleted_at IS NULL OR is_active = false)" in migration
    assert "CREATE UNIQUE INDEX uq_roles_undeleted_name" in migration
    assert "WHERE deleted_at IS NULL" in migration
    assert "migration.chg237.local_role_lifecycle" in migration


def test_chg237_role_routes_distinguish_disable_enable_and_delete() -> None:
    routes = read("backend/app/api/routes/roles.py")

    assert ".where(Role.deleted_at.is_(None))" in routes
    assert 'requested_fields != {"is_active"}' in routes
    assert '"inactive_role_read_only"' in routes
    assert 'action = "role.enable" if next_active else "role.disable"' in routes
    assert "confirmation_name: str = Query" in routes
    assert "confirmation_name != role.name" in routes
    assert 'action="role.delete"' in routes
    assert "role.deleted_at = datetime.now(UTC)" in routes
    assert "session.delete(mapping)" in routes
    assert 'action="role.deactivate"' not in routes


def test_chg237_permission_and_membership_queries_exclude_tombstoned_roles() -> None:
    context = read("backend/app/security/context.py")
    memberships = read("backend/app/services/role_memberships.py")
    models = read("backend/app/db/models.py")

    assert "Role.deleted_at.is_(None)" in context
    assert "Role.deleted_at.is_(None)" in memberships
    assert '"uq_roles_undeleted_name"' in models
    assert 'CheckConstraint("deleted_at IS NULL OR is_active = false"' in models


def test_chg237_release_docs_prohibit_unsafe_code_only_rollback() -> None:
    deploy_readme = read("deploy/README.md")
    release_readiness = read("deploy/RELEASE_READINESS.md")

    assert "CHG-237 V030 restriction" in deploy_readme
    assert "code-only rollback is prohibited" in release_readiness
    assert "complete pre-deployment PostgreSQL backup" in deploy_readme
