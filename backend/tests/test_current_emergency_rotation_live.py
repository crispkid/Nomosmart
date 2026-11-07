"""Real current-run emergency generation rotation and session retirement."""
from pathlib import Path
import json
import os
import stat
import subprocess
import sys

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AuthEmergencyAccess, AuthSession, IdentitySetting
from app.db.session import get_session_factory
from current_live_support import load_current_context


def test_emergency_rotation_retires_password_and_sessions_then_returns_disabled(tmp_path):
    context = load_current_context()
    assert context["auth_mode"] == "ldap"
    tmp_path.chmod(0o700)
    factory = get_session_factory()
    with factory() as session:
        rows = list(session.scalars(select(AuthEmergencyAccess)))
        assert len(rows) <= 1 and all(row.active_until is None and row.password_verifier is None for row in rows)
        before = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current))
        revision = before.revision
        username = get_settings().auth_emergency_username
    paths = [tmp_path / "generation-one", tmp_path / "generation-two"]
    attempts = []

    def cli(action, filename=None):
        args = [sys.executable, "-m", "app.deployment.protocol_bootstrap", action]
        if filename is not None:
            args += ["--password-file", str(filename)]
        attempts.append({"action": action, "state": "INTENT"})
        (tmp_path / "operations.json").write_text(json.dumps(attempts))
        result = subprocess.run(args, cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, timeout=30)
        attempts[-1].update(raw_exit=result.returncode, stdout=result.stdout.decode(), stderr_bytes=len(result.stderr))
        (tmp_path / "operations.json").write_text(json.dumps(attempts))
        assert result.returncode == 0
        return result

    def client():
        return httpx.Client(base_url=context["backend_direct_url"].rstrip("/") + "/api/v1/",
                            verify=context["ca_file"], trust_env=False, timeout=15,
                            headers={"Origin": context["origin"]})

    enabled = False
    secrets = []
    try:
        enabled = True  # Any unknown enable outcome is followed only by safe disable.
        first = cli("emergency-enable", paths[0])
        assert stat.S_IMODE(paths[0].stat().st_mode) == 0o600
        one = paths[0].read_text().strip()
        secrets.append(one)
        assert one and one.encode() not in first.stdout + first.stderr
        with client() as old, client() as new:
            response = old.post("auth/emergency/login", json={"username": username, "password": one})
            assert response.status_code == 200
            response = old.get("auth/me")
            assert response.status_code == 200 and response.json()["mode"] == "emergency"
            emergency_user_id = response.json()["user_id"]
            second = cli("emergency-enable", paths[1])
            assert stat.S_IMODE(paths[1].stat().st_mode) == 0o600
            two = paths[1].read_text().strip()
            secrets.append(two)
            assert two and two != one and two.encode() not in second.stdout + second.stderr
            assert old.get("auth/me").status_code == 401
            assert new.post("auth/emergency/login", json={"username": username, "password": one}).status_code == 401
            assert new.post("auth/emergency/login", json={"username": username, "password": two}).status_code == 200
            response = new.get("auth/me")
            assert response.status_code == 200 and response.json()["user_id"] == emergency_user_id
            cli("emergency-disable")
            enabled = False
            assert new.get("auth/me").status_code == 401
            assert new.post("auth/emergency/login", json={"username": username, "password": two}).status_code == 401
        with factory() as session:
            row = session.scalar(select(AuthEmergencyAccess))
            assert row.active_until is None and row.password_verifier is None
            assert not list(session.scalars(select(AuthSession.id).where(
                AuthSession.user_id == row.user_id, AuthSession.revoked_at.is_(None))))
            assert session.scalar(select(IdentitySetting.revision).where(IdentitySetting.is_current)) == revision
        with client() as normal:
            actor = context["actors"]["owner"]
            assert normal.post("auth/login", json={"username": actor["username"], "password": actor["password"]}).status_code == 200
            response = normal.get("auth/me")
            assert response.status_code == 200 and response.json()["user_id"] == actor["user_id"] and response.json()["mode"] == "ldap"
            assert normal.post("auth/logout", headers={"X-CSRF-Token": response.json()["csrf_token"]}).status_code == 204
        raw = (tmp_path / "operations.json").read_text()
        assert all(secret not in raw for secret in secrets)
    finally:
        try:
            if enabled:
                cli("emergency-disable")
        finally:
            for path in paths:
                path.unlink(missing_ok=True)
