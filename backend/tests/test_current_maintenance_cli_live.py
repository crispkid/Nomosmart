"""Current cookie-authenticated CLI against real owned API/SQL services.

These are maintenance contracts, not IdP-token or elapsed-time acceptance.
No original deployment, fake identity, replacement service or clock is used.
"""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from app.db.auth_models import AuthSession
from app.db.models import (
    AuditLog, FileProcessingExecution, FileProcessingPolicy,
    FileProcessingPolicyRevision, SystemParameter, User,
)
from app.domain.file_processing_settings import UNITS
from app.security.session_auth import SESSION_COOKIE, digest
from chg305_support import CAPS
from current_live_support import current_live


def _snapshot(live):
    with live.database() as db:
        return {
            "policy": [(row.deployment_id, row.revision, row.content_hash, row.updated_at)
                       for row in db.scalars(select(FileProcessingPolicy))],
            "history": [(row.revision, deepcopy(row.snapshot), row.content_hash)
                        for row in db.scalars(select(FileProcessingPolicyRevision).order_by(
                            FileProcessingPolicyRevision.revision))],
            "parameters": {row.key: deepcopy(row.value) for row in db.scalars(
                select(SystemParameter).where(SystemParameter.key.in_(UNITS)))},
        }


def _cookie(live, actor):
    client = live.actor(actor)
    value = client.cookies.get(SESSION_COOKIE)
    assert value, "A genuinely issued application session is required"
    return value


def _cli(case, operation, *, actor="owner", changes=None, revision=None,
         cookie=None, payload=None, raw_input=None, deployment=True):
    credential = cookie if cookie is not None else _cookie(case["live"], actor)
    if payload is None:
        payload = {"session_cookie": credential}
        if changes is not None:
            payload["changes"] = changes
    raw = bytearray(json.dumps(payload).encode() if raw_input is None else raw_input)
    command = [sys.executable, "-B", "-m", "coverage", "run", "--parallel-mode",
               "--rcfile=" + str(case["backend"] / "pyproject.toml"),
               "-m", "app.deployment.file_processing_policy", operation,
               "--capabilities-file", str(case["capabilities"])]
    if revision is not None:
        command += ["--expected-revision", str(revision)]
    if operation == "initialize" and deployment:
        command += ["--deployment-id", str(case["deployment"])]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("COV_CORE") and key != "COVERAGE_PROCESS_START"}
    environment["COVERAGE_FILE"] = str(case["coverage"] / ".coverage.cli")
    try:
        result = subprocess.run(command, input=bytes(raw), cwd=case["backend"],
                                env=environment, capture_output=True, timeout=30)
    finally:
        raw[:] = b"\0" * len(raw)
    assert result.returncode in (0, 1), "CLI process failed outside its contract"
    output = result.stdout + result.stderr
    assert len(output) <= 65536, "CLI output exceeded the bounded contract"
    if credential.encode() in output:
        raise AssertionError("CLI output contained a private credential")
    selected = result.stdout if result.returncode == 0 else result.stderr
    assert not (result.stderr if result.returncode == 0 else result.stdout)
    rows = selected.decode().splitlines()
    assert len(rows) == 1, "CLI must return one safe JSON object"
    value = json.loads(rows[0])
    if result.returncode:
        assert set(value) == {"error"} and isinstance(value["error"], str)
    return result.returncode, value


@pytest.fixture(scope="module")
def maintenance(current_live, tmp_path_factory):
    # This suite cannot reset a shared policy DB or another deployment's row.
    live = current_live
    root = tmp_path_factory.mktemp("current-maintenance")
    root.chmod(0o700)
    capabilities = root / "capabilities.json"
    capabilities.write_text(json.dumps(CAPS.maxima))
    capabilities.chmod(0o600)
    coverage = root / "coverage"
    coverage.mkdir(mode=0o700)
    case = {"live": live, "deployment": uuid4(), "capabilities": capabilities,
            "coverage": coverage, "backend": Path(__file__).resolve().parents[1]}
    with live.database() as db:
        assert db.get(FileProcessingPolicy, 1) is None, "Existing policy must be preserved"
        assert db.scalar(select(FileProcessingPolicyRevision.revision).limit(1)) is None
        assert db.scalar(select(FileProcessingExecution.id).limit(1)) is None
        original = [{column.key: deepcopy(getattr(row, column.key))
                     for column in SystemParameter.__table__.columns}
                    for row in db.scalars(select(SystemParameter).where(
                        SystemParameter.key.in_(UNITS)))]
    try:
        code, initial = _cli(case, "initialize", revision=0)
        assert code == 0 and initial["revision"] == 1
        case["initial"] = initial
        yield case
    finally:
        with live.database() as db:
            row = db.get(FileProcessingPolicy, 1)
            if row is not None:
                assert row.deployment_id == case["deployment"], "Unknown policy owner"
                assert db.scalar(select(FileProcessingExecution.id).limit(1)) is None
                db.delete(row)
                db.execute(delete(FileProcessingPolicyRevision))
                db.execute(delete(SystemParameter).where(SystemParameter.key.in_(UNITS)))
                db.flush()
                db.add_all(SystemParameter(**values) for values in original)
                db.commit()


def test_real_cookie_cli_initialize_read_cas_idempotence_and_audit(maintenance):
    case = maintenance
    assert _cli(case, "read", actor="system_viewer") == (0, case["initial"])
    assert _cli(case, "initialize", revision=0) == (0, case["initial"])
    changes = {"document_processing_max_concurrent": 1, "pdf_parser_max_concurrent": 1}
    code, updated = _cli(case, "update", actor="system_editor", revision=1, changes=changes)
    assert code == 0 and updated["revision"] == 2
    assert updated["content_hash"] != case["initial"]["content_hash"]
    assert _cli(case, "update", actor="system_editor", revision=2, changes=changes) == (0, updated)
    assert _cli(case, "read") == (0, updated)
    with case["live"].database() as db:
        actor = UUID(case["live"].context["actors"]["system_editor"]["user_id"])
        assert any(row.summary.get("revision") == 2 for row in db.scalars(
            select(AuditLog).where(AuditLog.actor_user_id == actor,
                                  AuditLog.action == "file_processing.policy.updated")))


@pytest.mark.parametrize("actor,operation", [
    ("system_viewer", "update"), ("system_edit_only", "read"),
    ("system_creator", "read"),
])
def test_real_cookie_cli_requires_view_and_edit_independently(maintenance, actor, operation):
    before = _snapshot(maintenance["live"])
    assert _cli(maintenance, operation, actor=actor, revision=2,
                changes={"pdf_parser_max_concurrent": 2} if operation == "update" else None
                ) == (1, {"error": "permission_denied"})
    assert _snapshot(maintenance["live"]) == before


def test_real_cookie_cli_rejects_locally_disabled_user(maintenance):
    live = maintenance["live"]
    cookie = _cookie(live, "system_viewer")
    user_id = UUID(live.context["actors"]["system_viewer"]["user_id"])
    with live.database() as db:
        user = db.get(User, user_id)
        original = user.locally_disabled
        user.locally_disabled = True
        db.commit()
    before = _snapshot(live)
    try:
        assert _cli(maintenance, "read", cookie=cookie) == (1, {"error": "user_disabled"})
        assert _snapshot(live) == before
    finally:
        with live.database() as db:
            db.get(User, user_id).locally_disabled = original
            db.commit()


def test_real_logout_and_stored_expiration_reject_prior_cookie(maintenance):
    live = maintenance["live"]
    client = live.actor("system_viewer")
    cookie = _cookie(live, "system_viewer")
    assert client.post("auth/logout").status_code == 204
    before = _snapshot(live)
    assert _cli(maintenance, "read", cookie=cookie) == (1, {"error": "session_expired"})
    cookie = _cookie(live, "system_viewer")
    # Native stored expired-state input; the actual clock is never replaced.
    with live.database() as db:
        row = db.scalar(select(AuthSession).where(AuthSession.secret_digest == digest(cookie)))
        assert row is not None and row.revoked_at is None
        original = row.last_activity_at
        row.last_activity_at = datetime.now(UTC) - timedelta(minutes=31)
        db.commit()
    try:
        assert _cli(maintenance, "read", cookie=cookie) == (1, {"error": "session_expired"})
        assert _snapshot(live) == before
    finally:
        with live.database() as db:
            row = db.scalar(select(AuthSession).where(AuthSession.secret_digest == digest(cookie)))
            row.last_activity_at = original
            db.commit()


@pytest.mark.parametrize("operation,revision,changes,error", [
    ("update", 0, {"pdf_parser_max_concurrent": 1}, "file_processing_policy_conflict"),
    ("update", 2, {"unknown": 1}, "file_processing_update_invalid"),
    ("read", None, {"pdf_parser_max_concurrent": 1}, "file_processing_cli_input_invalid"),
])
def test_cli_rejects_invalid_update_without_policy_changes(maintenance, operation, revision, changes, error):
    before = _snapshot(maintenance["live"])
    assert _cli(maintenance, operation, revision=revision, changes=changes) == (1, {"error": error})
    assert _snapshot(maintenance["live"]) == before


@pytest.mark.parametrize("payload,error", [
    ({}, "file_processing_cli_input_invalid"),
    ({"session_cookie": "untrusted-input", "access_token": "untrusted-input"},
     "file_processing_cli_input_invalid"),
    ({"session_cookie": None}, "authentication_required"),
    ({"access_token": "untrusted-external-input"}, "authentication_required"),
    ({"session_cookie": "untrusted-input", "unknown": True}, "file_processing_cli_input_invalid"),
])
def test_private_cli_refuses_ambiguous_external_or_invalid_credentials(maintenance, payload, error):
    before = _snapshot(maintenance["live"])
    assert _cli(maintenance, "read", payload=payload) == (1, {"error": error})
    assert _snapshot(maintenance["live"]) == before


def test_real_no_role_session_cannot_read_maintenance_policy(current_live, tmp_path):
    import httpx

    live = current_live
    actor = live.context["actors"]["denial"]
    tmp_path.chmod(0o700)
    capabilities = tmp_path / "capabilities.json"
    capabilities.write_text(json.dumps(CAPS.maxima))
    capabilities.chmod(0o600)
    coverage = tmp_path / "coverage"
    coverage.mkdir(mode=0o700)
    case = {"live": live, "backend": Path(__file__).resolve().parents[1],
            "capabilities": capabilities, "coverage": coverage}
    before = _snapshot(live)
    with httpx.Client(base_url=live.context["backend_url"].rstrip("/") +
                      live.context.get("api_prefix", "/api/v1") + "/",
                      verify=live.context["ca_file"], trust_env=False,
                      follow_redirects=False, timeout=15,
                      headers={"Origin": live.context["origin"]}) as client:
        result = client.post("auth/login", json={"username": actor["username"],
                                                  "password": actor["password"]})
        assert result.status_code == 200, "A real directory-issued session is required"
        try:
            cookie = client.cookies.get(SESSION_COOKIE)
            assert cookie and client.get("auth/me").status_code == 403
            assert _cli(case, "read", cookie=cookie) == (1, {"error": "permission_denied"})
            assert _snapshot(live) == before
        finally:
            state = client.get("auth/session")
            assert state.status_code == 200
            client.headers["X-CSRF-Token"] = state.json()["csrf_token"]
            assert client.post("auth/logout").status_code == 204


def test_current_cli_sql_snapshot_revision_and_audit_parity(maintenance):
    case = maintenance
    before = _snapshot(case["live"])
    previous_revision = before["policy"][0][1]
    changes = {key: 2 if before["parameters"][key] == 1 else 1
               for key in ("document_processing_max_concurrent", "pdf_parser_max_concurrent")}
    code, updated = _cli(case, "update", actor="system_editor",
                         revision=previous_revision, changes=changes)
    assert code == 0 and updated["revision"] == previous_revision + 1
    assert _cli(case, "initialize", revision=0) == (0, updated)
    assert _cli(case, "read", actor="system_viewer") == (0, updated)
    with case["live"].database() as db:
        revisions = db.scalars(select(FileProcessingPolicyRevision).order_by(
            FileProcessingPolicyRevision.revision)).all()
        assert [row.revision for row in revisions] == list(range(1, updated["revision"] + 1))
        assert revisions[-1].content_hash == updated["content_hash"]
        parameters = {row.key: deepcopy(row.value) for row in db.scalars(
            select(SystemParameter).where(SystemParameter.key.in_(UNITS)))}
        assert parameters == updated["values"] == revisions[-1].snapshot
        actor = UUID(case["live"].context["actors"]["system_editor"]["user_id"])
        audits = db.scalars(select(AuditLog).where(
            AuditLog.actor_user_id == actor,
            AuditLog.action == "file_processing.policy.updated")).all()
        assert any(row.summary.get("revision") == updated["revision"]
                   and row.summary.get("current") == updated["values"] for row in audits)


def test_current_cli_raw_capability_and_rejection_audit_parity(maintenance, tmp_path):
    case = maintenance
    live = case["live"]
    before = _snapshot(live)
    revision = before["policy"][0][1]
    maximum = before["parameters"]["pdf_parser_max_pages"]
    assert 1 <= maximum < 2000
    caps = dict(CAPS.maxima, pdf_parser_max_pages=maximum)
    capability_file = tmp_path / "bounded-capabilities.json"
    capability_file.write_text(json.dumps(caps))
    capability_file.chmod(0o600)
    bounded = dict(case, capabilities=capability_file)
    actor = UUID(live.context["actors"]["system_editor"]["user_id"])

    def rejections():
        with live.database() as db:
            return db.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.actor_user_id == actor,
                AuditLog.action == "file_processing.policy.rejected"))

    audit_before = rejections()
    cases = [
        (case, "update", {"revision": 0, "changes": {"pdf_parser_max_concurrent": 1}},
         "file_processing_policy_conflict"),
        (case, "update", {"revision": revision, "changes": {"unknown": 1}},
         "file_processing_update_invalid"),
        (case, "update", {"revision": revision, "changes": {"pdf_parser_max_concurrent": True}},
         "file_processing_policy_invalid"),
        (bounded, "update", {"revision": revision, "changes": {"pdf_parser_max_pages": maximum + 1}},
         "file_processing_capability_exceeded"),
        (case, "read", {"changes": {"pdf_parser_max_concurrent": 1}},
         "file_processing_cli_input_invalid"),
        (case, "initialize", {"revision": 1}, "file_processing_initialization_contract_invalid"),
        (case, "initialize", {"revision": 0, "deployment": False},
         "file_processing_initialization_contract_invalid"),
    ]
    for selected, operation, kwargs, error in cases:
        assert _cli(selected, operation, actor="system_editor", **kwargs) == (1, {"error": error})
        assert _snapshot(live) == before
    assert rejections() - audit_before == 7
    raw_cases = [
        (b"{}", "file_processing_cli_input_invalid"),
        (b"[]", "file_processing_cli_input_invalid"),
        (b'{"unexpected":true}', "file_processing_cli_input_invalid"),
        (b"x" * 65537, "file_processing_cli_input_limit"),
        (b"{", "file_processing_maintenance_failed"),
    ]
    for raw, error in raw_cases:
        assert _cli(case, "read", actor="system_editor", raw_input=raw) == (1, {"error": error})
        assert _snapshot(live) == before
    assert rejections() - audit_before == 7


def test_current_cli_inactive_user_is_refused_without_policy_mutation(maintenance):
    live = maintenance["live"]
    cookie = _cookie(live, "system_viewer")
    user_id = UUID(live.context["actors"]["system_viewer"]["user_id"])
    before = _snapshot(live)
    with live.database() as db:
        user = db.get(User, user_id)
        original = user.is_active
        assert original is True
        user.is_active = False
        db.commit()
    try:
        assert _cli(maintenance, "read", cookie=cookie) == (1, {"error": "user_disabled"})
        assert _snapshot(live) == before
    finally:
        with live.database() as db:
            db.get(User, user_id).is_active = original
            db.commit()
