from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_first_level_menu_permission_migration_defines_only_menu_rows() -> None:
    migration = ROOT / "sql" / "migrations" / "V017__first_level_menu_permissions.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "'Menu', 'KnowledgeProjects'" in sql
    assert "'Menu', 'Reports'" in sql
    assert "'Menu', 'SystemManagement'" in sql
    assert "WHERE module_name = 'Project' AND function_name = 'ProjectList'" in sql
    assert "WHERE module_name = 'System'" in sql
    assert "('Menu', 'KnowledgeProjects', true, true, false, false)" in sql
    assert "('Menu', 'Reports', true, false, false, false)" in sql
    assert "('Menu', 'SystemManagement', true, true, true, true)" in sql


def test_managed_permission_replace_preserves_unrelated_legacy_rows() -> None:
    route = ROOT / "backend" / "app" / "api" / "routes" / "roles.py"
    source = route.read_text(encoding="utf-8")

    assert "Permission matrix contains an unsupported row" in source
    assert "Permission row contains an unsupported action" in source
    assert "delete(RolePermission).where(RolePermission.role_id == role_id, _managed_permission_filter())" in source
    assert "delete(RolePermission).where(RolePermission.role_id == role_id)" not in source


def test_owner_and_editor_role_templates_can_submit_document_review() -> None:
    migration = ROOT / "sql" / "migrations" / "V012__owner_editor_submit_review_permission.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "project-owner" in sql
    assert "knowledge-editor" in sql
    assert "'Document', 'DocumentReview', true, true, true, false" in sql
    assert "can_create = true" in sql
    assert "can_delete = false" in sql


def test_applied_initial_seed_keeps_original_review_permissions() -> None:
    migration = ROOT / "sql" / "migrations" / "V003__seed_role_permissions.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "('Document', 'DocumentReview', true, false, true, false)" in sql
    assert "('Project', 'ProjectList'), ('Document', 'DocumentImport'), ('Document', 'DocumentVersion')," in sql
    assert "('Project', 'ProjectList'), ('Document', 'DocumentImport'), ('Document', 'DocumentVersion'), ('Document', 'DocumentReview')" not in sql
