"""Run only inside the guarded CHG-300 real PostgreSQL/Flyway lab container."""
from __future__ import annotations

import os
from pathlib import Path
import app
import json
import hashlib
import subprocess
import sys

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from app.core.config import MigrationProbeSettings, MigrationTargetSettings, Settings
from app.deployment.bootstrap import BootstrapFailure, DeploymentBootstrapSettings, _database_check, run_bootstrap
from app.deployment.migration_gate import MigrationGateError, migration_connection, migration_readiness_matches, migration_target_detail, required_contract, verify_migration_database, verify_migration_target, version_key


@pytest.fixture(scope="module", autouse=True)
def guarded_lab():
    assert os.environ.get("M300_ISOLATED") == "1", "Use chg300_migration_checks.py"
    if os.environ.get("M300_EXECUTION_MODE") == "image":
        assert Path(app.__file__).resolve().is_relative_to("/app/app"), "Image-internal source not loaded"
        manifest = json.loads(Path("/verify/image-manifest.json").read_text())
        for name, expected in manifest["files"].items():
            if name.startswith("backend/app/"):
                actual = Path("/app") / name.removeprefix("backend/")
                assert hashlib.sha256(actual.read_bytes()).hexdigest() == expected, name
    else:
        assert Path(app.__file__).resolve().is_relative_to("/current/app"), "Current source not loaded"
    assert os.environ["M300_URL"].split("@")[1].startswith("pg:5432/v49_m300_")
    engine = create_engine(os.environ["M300_URL"])
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_database()")) == "v49_m300_ready"
        # Genuine migration state, required checksum supplied by the host runner.
        assert connection.scalar(text("SELECT count(*) FROM public.flyway_schema_history WHERE success")) == 49
    engine.dispose()


def settings(*, database="ready", version="049", checksum=None, **extra):
    return Settings(_env_file=None, app_env="test", database_url=os.environ["M300_URL"].replace(
        "v49_m300_ready", "v49_m300_" + database), migration_required_version=version,
        migration_required_checksum=int(os.environ["M300_CHECKSUM"]) if checksum is None else checksum,
        migration_check_timeout_seconds=1, **extra)


def reject(config, code):
    with pytest.raises(BootstrapFailure) as failure:
        _database_check(config)
    assert failure.value.code == code
    assert str(failure.value) == code


@pytest.mark.parametrize("version", ["049", "49", "049.0", "49_0_0"])
def test_actual_v049_passes_same_numeric_version(version):
    config = settings(version=version)
    assert _database_check(config).detail == migration_target_detail(config)


@pytest.mark.parametrize("database,code", [
    ("v048", "database_migration_target_missing"),
    ("empty", "database_migration_history_missing"),
    ("baseline", "database_migration_target_invalid"),
    ("failed", "database_migration_target_missing"),
])
def test_real_history_states_fail_closed(database, code):
    reject(settings(database=database), code)


def test_missing_configuration_cannot_adopt_actual_db():
    config = settings()
    config.migration_required_version = ""
    config.migration_required_checksum = None
    reject(config, "database_migration_contract_missing")


def test_partial_configuration_is_not_a_default():
    config = settings()
    config.migration_required_checksum = None
    reject(config, "database_migration_contract_missing")


def test_different_checksum_rejected():
    reject(settings(checksum=int(os.environ["M300_CHECKSUM"]) ^ 1), "database_migration_checksum_mismatch")


def test_higher_unapproved_schema_rejected():
    reject(settings(version="048"), "database_migration_version_unexpected")


def test_real_unavailable_db_is_sanitized():
    config = settings()
    config.database_url = config.database_url.__class__(
        os.environ["M300_URL"].replace("@pg:5432/", "@pg:1/"))
    reject(config, "database_unavailable")


def test_read_only_history_role_succeeds_and_cannot_write():
    config = settings()
    config.database_url = config.database_url.__class__(os.environ["M300_READONLY_URL"])
    assert _database_check(config).detail == migration_target_detail(config)
    engine = create_engine(os.environ["M300_READONLY_URL"])
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SHOW transaction_read_only")) == "on"
            verify_migration_target(connection, "049", int(os.environ["M300_CHECKSUM"]))
            from sqlalchemy.exc import DBAPIError
            with pytest.raises(DBAPIError):
                connection.execute(text("CREATE TABLE forbidden_gate_write(id integer)"))
    finally:
        engine.dispose()


@pytest.mark.parametrize("ensure", [True, False])
def test_bootstrap_rejects_before_other_checks_or_ensure_writes(ensure):
    config = DeploymentBootstrapSettings(_env_file=None, **settings(database="v048").model_dump(),
        deployment_keycloak_mode="verify")
    config.deployment_bootstrap_release = "chg300-isolated"
    # Actual unavailable endpoints. Wrong order would fail on a network check,
    # not the expected migration error. No mocks or synthetic service responses.
    config.opensearch_url = "http://127.0.0.1:1"
    config.neo4j_uri = "bolt://127.0.0.1:1"
    with pytest.raises(BootstrapFailure) as failure:
        run_bootstrap(config, ensure=ensure)
    assert failure.value.code == "database_migration_target_missing"


@pytest.mark.parametrize("value", [True, 1.5, "1.5", "--1", "2147483648", "-2147483649", "١٢"])
def test_typed_checksum_rejects_invalid_values(value):
    with pytest.raises(ValidationError):
        settings(checksum=value)


@pytest.mark.parametrize("value", [-2147483648, 2147483647, 0, "-2147483648", "0"])
def test_signed_checksum_range(value):
    assert settings(checksum=value).migration_required_checksum == int(value)


@pytest.mark.parametrize("version", ["x49", "49;SELECT 1", "-49", "49..0", "1" * 81])
def test_version_format_rejected(version):
    with pytest.raises(ValidationError):
        settings(version=version)
    with pytest.raises(MigrationGateError):
        version_key(version)


@pytest.mark.parametrize("version,checksum", [("0", 1), ("49", True), ("49", 2147483648)])
def test_direct_contract_cannot_bypass_typed_settings(version, checksum):
    with pytest.raises(MigrationGateError) as failure:
        required_contract(version, checksum)
    assert failure.value.code == "database_migration_contract_invalid"


def test_blank_checksum_is_missing_not_zero():
    assert settings(checksum="").migration_required_checksum is None


def test_missing_remaining_schema_still_blocks_after_target_success():
    reject(settings(database="target_only"), "database_schema_incomplete")


@pytest.mark.parametrize("database,passes", [("ready", True), ("v048", False)])
def test_shared_database_probe_uses_same_target(database, passes):
    config = settings(database=database)
    probe = MigrationProbeSettings(_env_file=None, database_url=config.database_url,
        migration_required_version=config.migration_required_version,
        migration_required_checksum=config.migration_required_checksum)
    assert "app_encryption_key" not in type(probe).model_fields
    if passes:
        verify_migration_database(probe)
    else:
        with pytest.raises(MigrationGateError, match="database_migration_target_missing"):
            verify_migration_database(probe)


def test_shared_transaction_is_bounded_consistent_and_readonly():
    with migration_connection(settings()) as connection:
        assert connection.scalar(text("SHOW transaction_read_only")) == "on"
        assert connection.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert connection.scalar(text("SHOW statement_timeout")) == "1s"


def test_frontend_target_has_no_db_credential_and_matches_genuine_database_check():
    config = settings()
    target = MigrationTargetSettings(migration_required_version="49.0", migration_required_checksum=config.migration_required_checksum)
    assert "database_url" not in type(target).model_fields
    check = _database_check(config)  # Real verified PostgreSQL, never fabricated success.
    payload = {"status": "ready", "dependencies": {"deployment.database": {"healthy": True, "detail": check.detail}}}
    assert migration_readiness_matches(payload, target)
    target.migration_required_checksum ^= 1
    assert not migration_readiness_matches(payload, target)


@pytest.mark.parametrize("payload", [None, [], {}, {"status": "not_ready"}, {"status": "ready"},
    {"status": "ready", "dependencies": {"deployment.database": {"healthy": True, "detail": "ready"}}},
    {"status": "ready", "dependencies": {"deployment.database": {"healthy": False, "detail": "database_unavailable"}}},
    {"status": "ready", "dependencies": {"deployment.database": []}}])
def test_frontend_does_not_accept_legacy_or_malformed_readiness(payload):
    assert not migration_readiness_matches(payload, settings())


@pytest.mark.parametrize("checksum,code", [("", "database_migration_contract_missing"),
    ("1.5", "deployment_configuration_invalid"), ("0", "database_migration_target_missing")])
def test_cli_real_v048_exits_nonzero_with_safe_code(checksum, code):
    env = {key: os.environ[key] for key in ("PATH", "HOME", "PYTHONPATH", "APP_ENCRYPTION_KEY") if key in os.environ}
    env.update(APP_ENV="test", PYTHONSAFEPATH="1", PYTHONDONTWRITEBYTECODE="1",
        DATABASE_URL=settings(database="v048").database_url.get_secret_value(),
        MIGRATION_REQUIRED_VERSION="049", MIGRATION_REQUIRED_CHECKSUM=checksum,
        MIGRATION_CHECK_TIMEOUT_SECONDS="1", DEPLOYMENT_BOOTSTRAP_RELEASE="chg300-cli")
    result = subprocess.run([sys.executable, "-m", "app.deployment.bootstrap", "--mode", "check", "--wait-seconds", "0"],
        env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert json.loads(result.stderr)["code"] == code
    assert "postgresql" not in result.stderr and "Traceback" not in result.stderr
