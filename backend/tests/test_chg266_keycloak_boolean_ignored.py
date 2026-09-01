from __future__ import annotations

from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.errors import AppError
from app.integrations.keycloak import KeycloakAdminClient


ROOT = BACKEND.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_boolean_false_is_separate_from_integer_counters() -> None:
    result = KeycloakAdminClient._directory_user_sync_result(
        {"added": 5, "updated": 2, "removed": 0, "failed": 0, "ignored": False}
    )
    assert (result.added, result.updated, result.removed, result.failed) == (5, 2, 0, 0)
    assert result.ignored is False


def test_boolean_true_is_preserved_as_explicit_ignored_result() -> None:
    result = KeycloakAdminClient._directory_user_sync_result(
        {"added": 0, "updated": 0, "removed": 0, "failed": 0, "ignored": True}
    )
    assert result.ignored is True
    assert type(result.ignored) is bool


@pytest.mark.parametrize("ignored", [None, 0, 1, "false", [], {}])
def test_non_boolean_ignored_is_rejected(ignored: object) -> None:
    with pytest.raises(AppError) as caught:
        KeycloakAdminClient._directory_user_sync_result(
            {"added": 0, "updated": 0, "removed": 0, "failed": 0, "ignored": ignored}
        )
    assert caught.value.code == "keycloak_invalid_response"


def test_missing_ignored_is_rejected() -> None:
    with pytest.raises(AppError) as caught:
        KeycloakAdminClient._directory_user_sync_result(
            {"added": 0, "updated": 0, "removed": 0, "failed": 0}
        )
    assert caught.value.code == "keycloak_invalid_response"


@pytest.mark.parametrize("counter", [True, False, -1, 1.5, "1", None, [], {}])
def test_non_integer_or_negative_counter_is_rejected(counter: object) -> None:
    with pytest.raises(AppError) as caught:
        KeycloakAdminClient._directory_user_sync_result(
            {"added": counter, "updated": 0, "removed": 0, "failed": 0, "ignored": False}
        )
    assert caught.value.code == "keycloak_invalid_response"


def test_non_object_sync_payload_is_rejected() -> None:
    with pytest.raises(AppError) as caught:
        KeycloakAdminClient._directory_user_sync_result("not-an-object")
    assert caught.value.code == "keycloak_invalid_response"


def test_http_json_decode_error_is_mapped_to_invalid_response_in_client_path() -> None:
    client = read("backend/app/integrations/keycloak.py")
    decode = client.index("payload = response.json()", client.index("def trigger_directory_user_sync"))
    invalid = client.index('raise AppError("keycloak_invalid_response"', decode)
    unavailable = client.index('raise AppError("keycloak_unavailable"', invalid)
    assert decode < invalid < unavailable


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


def test_worker_records_boolean_and_stops_ignored_before_group_phase() -> None:
    worker = read("backend/app/worker.py")
    store = worker.index("result.user_sync_ignored = user_sync.ignored")
    ignored_guard = worker.index("if user_sync.ignored:", store)
    ignored_error = worker.index('"keycloak_provider_sync_ignored"', ignored_guard)
    group_phase = worker.index('run.phase = "provider_group_sync"', ignored_error)
    assert store < ignored_guard < ignored_error < group_phase
    assert "result.users_ignored = 0" in worker
    assert '"user_sync_ignored": result.user_sync_ignored' in worker
