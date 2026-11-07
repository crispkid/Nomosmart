"""Real owned SQL/API/CLI checks; no original secrets or fake auth results."""
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import AIModel, AuditLog, AuthEmergencyAccess, AuthSession, User
from app.deployment.application_key_rotation import _schema, preview, rotate
from app.deployment.application_key_rotation import ACTION
from app.security.auth_configuration import keyring
from app.security.session_auth import SESSION_COOKIE, digest
from current_live_support import current_live


def _maintenance_snapshot(live):
    with live.database() as db:
        return {
            "models": [(str(row.id), hashlib.sha256((row.api_key_encrypted or "").encode()).hexdigest())
                       for row in db.scalars(select(AIModel).order_by(AIModel.id))],
            "rotation_audits": [str(value) for value in db.scalars(select(AuditLog.id).where(
                AuditLog.action == ACTION).order_by(AuditLog.id))],
        }


def _rotation_arguments(live):
    settings = get_settings()
    with live.database() as db:
        database = db.bind.url.database
    return dict(current=settings.encryption_key_bytes, candidate=secrets.token_bytes(32),
                before="closure-before", after="closure-after", expected_database=database,
                auth_keys=keyring(settings), max_records=5000)


def _emergency_rows(live):
    with live.database() as db:
        return [(str(row.user_id), row.username, bool(row.password_verifier), row.active_until,
                 db.get(User, row.user_id).is_active)
                for row in db.scalars(select(AuthEmergencyAccess))]


def _deployment_cli(action, root, password_file=None):
    backend = Path(__file__).resolve().parents[1]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("COV_CORE") and key != "COVERAGE_PROCESS_START"}
    environment["COVERAGE_FILE"] = str(root / ".coverage.emergency")
    command = [sys.executable, "-B", "-m", "coverage", "run", "--parallel-mode",
               "--rcfile=" + str(backend / "pyproject.toml"),
               "-m", "app.deployment.protocol_bootstrap", action]
    if password_file:
        command += ["--password-file", str(password_file)]
    result = subprocess.run(command, cwd=backend, env=environment,
                            capture_output=True, timeout=30)
    assert result.returncode == 0, "Owned deployment CLI failed; retain private diagnostics"
    assert not result.stderr and len(result.stdout) < 4096
    return json.loads(result.stdout)


def test_emergency_status_tracks_real_cli_credential_and_read_only_get(current_live, tmp_path):
    live = current_live
    assert _emergency_rows(live) == [], "Existing emergency identities must be preserved"
    client = live.actor("owner")
    before = client.get("system/break-glass/status")
    assert before.status_code == 200
    assert before.json()["configured"] is False
    assert before.json()["status"] == "not_configured"
    assert before.json()["enabled"] is False and _emergency_rows(live) == []
    tmp_path.chmod(0o700)
    password_file = tmp_path / "emergency-password.txt"
    try:
        assert _deployment_cli("emergency-enable", tmp_path, password_file)["state"] == "enabled"
        assert password_file.stat().st_mode & 0o077 == 0
        rows = _emergency_rows(live)
        assert len(rows) == 1 and rows[0][2] and rows[0][3] > datetime.now(UTC)
        active = client.get("system/break-glass/status")
        assert active.status_code == 200
        value = active.json()
        assert value["configured"] and value["enabled"] and value["system_admin_mapped"]
        assert value["status"] == "attention_required"
        assert _emergency_rows(live) == rows, "GET must not change credentials or activation window"
    finally:
        _deployment_cli("emergency-disable", tmp_path)
        password_file.unlink(missing_ok=True)
    disabled = client.get("system/break-glass/status")
    assert disabled.status_code == 200
    assert not disabled.json()["configured"] and not disabled.json()["enabled"]
    assert disabled.json()["status"] == "not_configured"
    assert disabled.json()["system_admin_mapped"] is True  # Historical grant remains.
    rows = _emergency_rows(live)
    assert len(rows) == 1 and rows[0][2:] == (False, None, False)


def test_empty_reserved_auth_ciphertext_allows_read_only_preview(current_live):
    live = current_live
    before = _maintenance_snapshot(live)
    arguments = _rotation_arguments(live)
    with live.database() as db:
        assert db.scalar(text("SELECT count(*) FROM auth_sessions WHERE upstream_ciphertext IS NOT NULL")) == 0
        result = preview(db.bind, **arguments)
    assert result["status"] == "PREVIEW_ONLY"
    assert _maintenance_snapshot(live) == before
    assert arguments["current"].hex() not in json.dumps(result)


@pytest.mark.parametrize("storage_input", ["encrypted", "empty"])
def test_reserved_auth_ciphertext_blocks_preview_and_rotation_without_writes(current_live, storage_input):
    live = current_live
    client = live.actor("system_viewer")
    cookie = client.cookies.get(SESSION_COOKIE)
    assert cookie and client.post("auth/logout").status_code == 204
    arguments = _rotation_arguments(live)
    with live.database() as db:
        row = db.scalar(select(AuthSession).where(AuthSession.secret_digest == digest(cookie)))
        assert row and row.revoked_at and row.upstream_ciphertext is None
        session_id = row.id
        # Native negative storage input in an actual revoked session. This is
        # not a Provider token or a claim of supported upstream-token storage.
        row.upstream_ciphertext = (EnvelopeCipher(get_settings().auth_encryption_key_bytes).encrypt(
            "reserved storage input", context=f"unsupported-upstream:{session_id}")
            if storage_input == "encrypted" else "")
        db.commit()
    before = _maintenance_snapshot(live)
    try:
        with live.database() as db:
            for operation in ("preview", "rotate"):
                with pytest.raises(AppError) as caught:
                    if operation == "preview":
                        preview(db.bind, **arguments)
                    else:
                        rotate(db.bind, **arguments, expected_digest="0" * 64,
                               operation_id=uuid4(), writers_quiesced=True)
                assert caught.value.code == "app_key_unhandled_auth_ciphertext"
        assert _maintenance_snapshot(live) == before
    finally:
        with live.database() as db:
            row = db.get(AuthSession, session_id)
            assert row and row.revoked_at
            row.upstream_ciphertext = None
            db.commit()


def test_unknown_ciphertext_schema_is_refused_and_ddl_rolls_back(current_live):
    live = current_live
    with live.database() as db:
        assert db.scalar(text("SELECT to_regclass('public.chg377_cipher_catalog_guard')")) is None
        db.execute(text("CREATE TABLE chg377_cipher_catalog_guard (id integer, unknown_ciphertext text)"))
        try:
            with pytest.raises(AppError) as caught:
                _schema(db)
            assert caught.value.code == "app_key_unknown_encrypted_field"
        finally:
            db.rollback()
        assert db.scalar(text("SELECT to_regclass('public.chg377_cipher_catalog_guard')")) is None
