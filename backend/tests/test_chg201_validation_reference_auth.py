from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_validation_runs_persist_csv_metadata_and_status_semantics() -> None:
    serving = read("backend/app/api/routes/serving.py")
    runner = read("backend/app/domain/validation_runner.py")
    schemas = read("backend/app/api/schemas.py")
    migration = read("sql/migrations/V018__validation_run_item_metadata.sql")

    assert "ADD COLUMN IF NOT EXISTS category" in migration
    assert "ADD COLUMN IF NOT EXISTS priority" in migration
    assert "category=item.category" in serving
    assert "priority=item.priority" in serving
    assert "status.in_((\"failed\", \"error\"))" in serving
    assert "VALIDATION_PASS_THRESHOLD = 0.7" in runner
    assert "return \"needs_review\"" in runner
    assert "return \"passed\"" in runner
    assert 'else "failed"' in runner
    assert 'item.status = "error"' in runner
    assert 'Literal["pending", "running", "passed", "failed", "needs_review", "error", "completed", "skipped", "cancelled"]' in schemas


def test_reference_events_create_target_safe_notifications() -> None:
    source = read("backend/app/domain/reference_events.py")

    assert "def _create_reference_event_notifications" in source
    assert 'event_type="reference_source_event"' in source
    assert "DocumentReferenceEvent(" in source
    assert "source_project_name_snapshot" in source
    assert "source_document_name_snapshot" in source
    assert '"target_project_id"' in source
    assert '"target_document_id"' in source
    assert '"source_project_id"' not in source
    assert '"source_document_id"' not in source
    assert "ProjectOwner" in source
    assert "ProjectMember.project_role.in_((\"owner\", \"editor\"))" in source
    assert "User.is_active.is_(True)" in source


def test_break_glass_status_is_keycloak_backed_and_read_only() -> None:
    keycloak = read("backend/app/integrations/keycloak.py")
    system = read("backend/app/api/routes/system.py")
    schemas = read("backend/app/api/schemas.py")
    config = read("backend/app/core/config.py")

    assert "class KeycloakBreakGlassStatus" in keycloak
    assert "def break_glass_status" in keycloak
    assert "def ensure_break_glass_user" in keycloak
    assert "enabled: bool = False" in keycloak
    assert '"enabled": enabled' in keycloak
    assert '"UPDATE_PASSWORD"' in keycloak
    assert 'required_actions = ["UPDATE_PASSWORD"]' in keycloak
    assert '"temporary": True' in keycloak
    assert 'str(action) != "CONFIGURE_TOTP"' in keycloak
    assert "credential_update_required" in keycloak
    assert "def get_break_glass_status" in system
    assert '@router.get("/break-glass/status"' in system
    assert "require_menu_permission" in system
    assert "PermissionAction.VIEW" in system
    assert "keycloak_sync_client_secret" in system
    assert "break_glass_runbook_uri" in config
    assert "break_glass_alerting_evidence" in config
    assert "_break_glass_deployment_evidence" in system
    assert "deployment_evidence_missing" in system
    assert "add_audit(session" in system
    assert "class BreakGlassStatusResponse" in schemas
    assert "credential_source: str" in schemas
    assert "credential_update_required: bool | None" in schemas
    assert "runbook_evidence: str" in schemas
    assert "alerting_evidence: str" in schemas
    assert "lifecycle_control: str" in schemas
    route_block = system.split('def get_break_glass_status', 1)[1].split('@router.put("/parameters"', 1)[0]
    assert "initial_password" not in route_block
    assert "password" not in route_block.lower()
