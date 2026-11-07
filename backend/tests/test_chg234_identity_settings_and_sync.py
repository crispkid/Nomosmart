from __future__ import annotations
from current_live_support import current_live  # noqa: F401

from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.errors import AppError
from app.domain.directory_filters import validate_directory_filter


ROOT = BACKEND.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_directory_filter_uses_structured_rfc4515_parser() -> None:
    assert validate_directory_filter("(&(objectClass=person)(mail=*))") == "(&(objectClass=person)(mail=*))"
    assert validate_directory_filter("") == ""
    for value in ("(uid=test)(mail=*)", "(&(uid=test)", "(uid=bad\\zz)", "(uid=test)\x00"):
        with pytest.raises(AppError) as caught:
            validate_directory_filter(value)
        assert caught.value.code in {"directory_filter_invalid", "directory_filter_too_long"}
    with pytest.raises(AppError) as too_long:
        validate_directory_filter(f"(cn={'a' * 2050})")
    assert too_long.value.code == "directory_filter_too_long"


def test_identity_provider_api_is_allowlisted_and_audited_without_filter_plaintext() -> None:
    # Current validation route owns direct directory candidates, not upstream Providers.
    route = read("backend/app/api/routes/protocol_identity.py")
    assert "CandidateRequest" in route and "expected_revision" in route
    assert "stage_configuration" in route and "add_audit" in route
    assert not (ROOT / "backend/app/api/routes/identity_settings.py").exists()
    assert "customUserSearchFilter" not in route


def test_sync_recovery_contract_has_durable_lease_and_runtime_health(current_live) -> None:
    from sqlalchemy import text
    from app.db.session import get_session_factory
    run = current_live.sync_receipt()
    assert run["queued_at"] and run["started_at"] and run["completed_at"]
    assert run["error_code"] is None
    with get_session_factory()() as session:
        columns = set(session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='identity_sync_runs'")).scalars())
        assert {"queued_at", "heartbeat_at", "lease_token", "configuration_revision"} <= columns


def test_keycloak_bootstrap_reconciles_exact_reauth_callback():
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: application no longer manages IdP clients/callback registration; current acceptance: PROTAUTH-002 backend-owned callback and trusted discovery')
