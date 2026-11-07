from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_reference_sources_use_project_scope_not_global_document_reference_rbac() -> None:
    source = (ROOT / "backend" / "app" / "api" / "routes" / "references.py").read_text(encoding="utf-8")
    list_block = source.split('@router.get("/projects/{project_id}/reference-sources"', 1)[1].split('@router.post("/projects/{project_id}/document-references"', 1)[0]

    assert "require_permission" not in list_block
    assert "visible_project_ids = set(context.visible_project_ids)" in list_block
    assert "Project.id.in_(visible_project_ids)" in list_block
    assert "Project.id != target_project.id" in list_block


def test_reference_write_operations_require_target_project_owner_or_editor() -> None:
    source = (ROOT / "backend" / "app" / "api" / "routes" / "references.py").read_text(encoding="utf-8")

    assert 'REFERENCE_TARGET_WRITE_ROLES = frozenset({"owner", "editor"})' in source
    assert "def _require_target_reference_write" in source
    assert "select(ProjectMember.project_role)" in source
    assert "session.get(ProjectOwner, (target_project_id, context.user_id))" in source
    assert "project_reference_role_required" in source
    for route_marker in [
        '@router.post("/projects/{project_id}/document-references"',
        '@router.post("/projects/{project_id}/document-references/import"',
        '@router.post("/document-references/{reference_id}/detach"',
        '@router.post("/document-references/{reference_id}/sync"',
        '@router.post("/document-references/{reference_id}/update"',
        '@router.post("/document-reference-events/{event_id}/resolve"',
    ]:
        block = source.split(route_marker, 1)[1].split("@router.", 1)[0]
        assert "_require_target_reference_write" in block
