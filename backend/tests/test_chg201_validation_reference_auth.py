from current_live_support import current_live  # noqa: F401
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


def test_break_glass_status_is_keycloak_backed_and_read_only(current_live) -> None:
    # Historical case identifier retained. Current emergency access belongs to
    # deployment procedures and never requires administration of the IdP.
    client = current_live.actor("system_viewer")
    response = client.get("system/break-glass/status")
    assert response.status_code == 200
    body = response.json()
    # AUTH-008 / CHG-377: disabling removes the credential. Presence of an
    # account alone cannot be presented as a configured emergency credential.
    from sqlalchemy import select
    from app.core.config import get_settings
    from app.db.models import AuthEmergencyAccess
    with current_live.database() as session:
        configured = bool(session.scalar(select(
            AuthEmergencyAccess.password_verifier.is_not(None)
            & (AuthEmergencyAccess.password_verifier != "")
        ).where(AuthEmergencyAccess.username == get_settings().auth_emergency_username)))
    assert body["configured"] is configured
    assert body["status"] == ("configured_disabled" if configured else "not_configured")
    assert body["enabled"] is False and body["local_account"] is True
    assert body["credential_source"] == "deployment_secret"
    assert body["lifecycle_control"] == "deployment_only"
    assert "password" not in body and "password_verifier" not in body
    assert client.post("system/break-glass/status", json={"enabled": True}).status_code in {404, 405}
