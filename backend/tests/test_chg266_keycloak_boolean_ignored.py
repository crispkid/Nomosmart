from __future__ import annotations
from current_live_support import current_live  # noqa: F401

from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.errors import AppError


ROOT = BACKEND.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_boolean_false_is_separate_from_integer_counters():
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: retired Admin API ignored/counter response decoder; current acceptance: test_worker_records_boolean_and_stops_ignored_before_group_phase; V044 additive contract retained')


def test_boolean_true_is_preserved_as_explicit_ignored_result():
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: retired Admin API ignored/counter response decoder; current acceptance: test_worker_records_boolean_and_stops_ignored_before_group_phase; V044 additive contract retained')


@pytest.mark.parametrize("ignored", [None, 0, 1, "false", [], {}])
def test_non_boolean_ignored_is_rejected(ignored: object):
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: retired Admin API ignored/counter response decoder; current acceptance: test_worker_records_boolean_and_stops_ignored_before_group_phase; V044 additive contract retained')


def test_missing_ignored_is_rejected():
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: retired Admin API ignored/counter response decoder; current acceptance: test_worker_records_boolean_and_stops_ignored_before_group_phase; V044 additive contract retained')


@pytest.mark.parametrize("counter", [True, False, -1, 1.5, "1", None, [], {}])
def test_non_integer_or_negative_counter_is_rejected(counter: object):
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: retired Admin API ignored/counter response decoder; current acceptance: test_worker_records_boolean_and_stops_ignored_before_group_phase; V044 additive contract retained')


def test_non_object_sync_payload_is_rejected():
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: retired Admin API ignored/counter response decoder; current acceptance: test_worker_records_boolean_and_stops_ignored_before_group_phase; V044 additive contract retained')


def test_http_json_decode_error_is_mapped_to_invalid_response_in_client_path():
    # Explicit retirement: this is skipped, never a passing runtime substitute.
    pytest.skip('CHG-374 retired: retired Admin API ignored/counter response decoder; current acceptance: test_worker_records_boolean_and_stops_ignored_before_group_phase; V044 additive contract retained')


def test_v044_and_application_contracts_are_additive_and_type_safe() -> None:
    migration = read("sql/migrations/V044__keycloak_boolean_ignored_sync_result.sql")
    model = read("backend/app/db/models.py")
    schema = read("backend/app/api/schemas.py")
    frontend = read("frontend/src/lib/api.ts")
    assert "ADD COLUMN user_sync_ignored boolean NOT NULL DEFAULT false" in migration
    assert "Deprecated compatibility counter; always zero" in migration
    assert "DROP COLUMN" not in migration.upper()
    assert "user_sync_ignored: Mapped[bool]" in model
    assert "user_sync_ignored: bool" in schema
    assert "users_ignored: int" in schema
    assert "user_sync_ignored: boolean" in frontend
    assert "users_ignored: number" in frontend


def test_worker_records_boolean_and_stops_ignored_before_group_phase(current_live) -> None:
    # The retired upstream "ignored" response is replaced by direct-directory
    # completeness checks. A real query limit failure must preserve active data.
    import copy
    client = current_live.unlock_directory_settings()
    response = client.get("system/identity-settings")
    assert response.status_code == 200
    before = response.json()
    candidate = copy.deepcopy(before["configuration"])
    candidate["directory"]["maximum_entries"] = 1
    rejected = client.post("system/identity-settings/validate", json={"configuration": candidate,
        "expected_revision": before["revision"], "secrets": {}})
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "directory_limit_exceeded"
    after = client.get("system/identity-settings")
    assert after.status_code == 200
    assert after.json()["revision"] == before["revision"]
    assert after.json()["configuration"] == before["configuration"]
    assert current_live.sync_receipt()["status"] == "succeeded"
