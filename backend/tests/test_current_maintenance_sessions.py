"""PP370-T09: real LDAP sessions and private-schema maintenance, no fake auth."""
from datetime import UTC, datetime
import json
import os
import subprocess
import sys
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.models import AuditLog, AuthSession, FileProcessingPolicy, FileProcessingPolicyRevision, SystemParameter, User
from app.security.session_auth import SESSION_COOKIE, digest, session_expiration
from current_live_support import current_live  # noqa: F401
from owned_service_scope import verify_owned_services


@pytest.fixture
def maintenance_schema(current_live):
    settings = get_settings()
    verify_owned_services(settings)
    schema = "pp370_maintenance_" + uuid4().hex
    url = make_url(current_live.context["database_url"])
    control = create_engine(url, hide_parameters=True)
    with control.begin() as connection:
        connection.execute(text('CREATE SCHEMA "' + schema + '"'))
    scoped = url.update_query_dict({"options": "-csearch_path=" + schema + ",public"})
    engine = create_engine(scoped, hide_parameters=True)
    try:
        # Only the three policy tables are fresh; genuine auth/role tables are
        # resolved in public. No application policy or business data is replaced.
        with engine.begin() as connection:
            SystemParameter.__table__.create(connection, checkfirst=False)
            FileProcessingPolicy.__table__.create(connection, checkfirst=False)
            FileProcessingPolicyRevision.__table__.create(connection, checkfirst=False)
        yield scoped.render_as_string(hide_password=False)
    finally:
        engine.dispose()
        with control.begin() as connection:
            connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
        control.dispose()


def issued(current_live, actor):
    client = current_live.actor(actor)
    return client.cookies.get(SESSION_COOKIE)


def cli(database_url, operation, credential, *options):
    env = dict(os.environ, DATABASE_URL=database_url)
    result = subprocess.run([sys.executable, "-m", "coverage", "run", "--parallel-mode",
        "-m", "app.deployment.file_processing_policy", operation, *options],
        input=json.dumps(credential), env=env, capture_output=True, text=True, timeout=20)
    # The CLI returns safe metadata only. Credentials never appear in argv.
    value = json.loads(result.stdout if result.returncode == 0 else result.stderr)
    assert all(secret not in result.stdout + result.stderr for key, secret in credential.items()
               if key in {"session_cookie", "access_token"} and isinstance(secret, str) and secret)
    return result.returncode, value


def test_real_session_initializes_reads_and_preserves_view_edit_boundary(current_live, maintenance_schema):
    owner = {"session_cookie": issued(current_live, "owner")}
    code, initialized = cli(maintenance_schema, "initialize", owner,
        "--deployment-id", str(uuid4()), "--expected-revision", "0")
    assert code == 0
    assert initialized["revision"] == 1
    code, _ = cli(maintenance_schema, "read", {"session_cookie": issued(current_live, "system_viewer")})
    assert code == 0
    code, denied = cli(maintenance_schema, "update", {"session_cookie": issued(current_live, "system_viewer"),
        "changes": {"document_processing_max_concurrent": 1}}, "--expected-revision", "1")
    assert code != 0 and denied["error"] == "permission_denied"
    code, _ = cli(maintenance_schema, "read", owner)
    assert code == 0


def test_revoked_real_session_is_rejected(current_live, maintenance_schema):
    client = current_live.actor("system_viewer")
    raw = client.cookies.get(SESSION_COOKIE)
    assert client.post("auth/logout").status_code == 204
    code, result = cli(maintenance_schema, "read", {"session_cookie": raw})
    assert code != 0 and result["error"] == "session_expired"


def test_disabled_real_user_is_rejected(current_live, maintenance_schema):
    raw = issued(current_live, "system_viewer")
    editor = current_live.actor("system_editor")
    user_id = current_live.context["actors"]["system_viewer"]["user_id"]
    assert editor.patch("users/" + user_id + "/status", json={"is_active": False}).status_code == 200
    try:
        with current_live.database() as session:
            row = session.scalar(select(AuthSession).where(AuthSession.secret_digest == digest(raw)))
            assert row.revoked_at is not None
            assert session.get(User, row.user_id).is_active is False
        code, result = cli(maintenance_schema, "read", {"session_cookie": raw})
        # The real status API revokes sessions immediately; revocation is
        # checked before the additional disabled-user defense.
        assert code != 0 and result["error"] == "session_expired"
    finally:
        assert editor.patch("users/" + user_id + "/status", json={"is_active": True}).status_code == 200


def test_external_token_and_ambiguous_input_are_rejected(current_live, maintenance_schema):
    code, result = cli(maintenance_schema, "read", {"access_token": "retired-external-credential"})
    assert code != 0 and result["error"] == "authentication_required"
    code, result = cli(maintenance_schema, "read", {"access_token": "retired-external-credential",
        "session_cookie": issued(current_live, "owner")})
    assert code != 0 and result["error"] == "file_processing_cli_input_invalid"


def test_actual_login_without_menu_permission_cannot_read_policy(current_live, maintenance_schema):
    cfg = current_live.context
    actor = cfg["actors"]["denial"]
    with httpx.Client(base_url=cfg["backend_url"] + cfg["api_prefix"] + "/", verify=cfg["ca_file"],
            trust_env=False, headers={"Origin": cfg["origin"]}, timeout=15) as client:
        assert client.post("auth/login", json={"username": actor["username"], "password": actor["password"]}).status_code == 200
        assert client.get("auth/me").status_code == 403
        code, result = cli(maintenance_schema, "read", {"session_cookie": client.cookies.get(SESSION_COOKIE)})
        assert code != 0 and result["error"] == "permission_denied"


def test_naturally_expired_issued_session_is_rejected(current_live, maintenance_schema):
    raw = current_live.context.get("naturally_expired_session_cookie")
    assert raw, "BLOCKED: retain an actually issued session until its natural idle expiry"
    with current_live.database() as session:
        row = session.scalar(select(AuthSession).where(AuthSession.secret_digest == digest(raw)))
        assert row and row.revoked_at is None
        assert datetime.now(UTC) >= session_expiration(row, get_settings().auth_session_idle_seconds)
    code, result = cli(maintenance_schema, "read", {"session_cookie": raw})
    assert code != 0 and result["error"] == "session_expired"


def test_recovery_preview_uses_real_session_and_keeps_rejection_read_only(current_live, maintenance_schema):
    from app.deployment.file_processing_recovery import RecoveryScope
    from sqlalchemy import func
    from uuid import UUID
    raw = issued(current_live, "owner")
    deployment_id = str(uuid4())
    code, policy = cli(maintenance_schema, "initialize", {"session_cookie": raw},
        "--deployment-id", deployment_id, "--expected-revision", "0")
    assert code == 0
    fields = {}
    for name in RecoveryScope.model_fields:
        fields[name] = ("a" * 64 if name.endswith("sha256") or name.endswith("container_id")
            else 1 if name in {"policy_revision", "project_generation", "worker_pid"}
            else str(uuid4()))
    fields["actor_id"] = current_live.context["actors"]["owner"]["user_id"]
    fields.update(deployment_id=deployment_id, policy_revision=policy["revision"], policy_sha256=policy["content_hash"])
    # These nonexistent IDs are deliberately invalid scope inputs; no stopped
    # worker, successful recovery or historical evidence is manufactured.
    scope = RecoveryScope.model_validate(fields).model_dump(mode="json")
    actor = UUID(fields["actor_id"])
    def audits():
        with current_live.database() as session:
            return session.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.actor_user_id == actor, AuditLog.action.like("file_processing.failed_worker.%")))
    before = audits()
    env = dict(os.environ, DATABASE_URL=maintenance_schema)
    command = [sys.executable, "-m", "coverage", "run", "--parallel-mode",
        "-m", "app.deployment.file_processing_recovery", "preview"]
    result = subprocess.run(command, input=json.dumps({"session_cookie": raw, "scope": scope}),
        env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1 and json.loads(result.stderr)["error"] == "file_processing_recovery_scope_missing"
    assert raw not in result.stdout + result.stderr
    assert audits() == before
