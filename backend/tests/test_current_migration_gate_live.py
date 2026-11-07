"""Current integration equivalents; real Flyway and PostgreSQL only."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import MigrationProbeSettings, MigrationTargetSettings
from app.deployment.bootstrap import BootstrapFailure, DeploymentBootstrapSettings, _database_check, run_bootstrap
from app.deployment.migration_gate import (MigrationGateError, migration_connection, migration_readiness_matches,
    migration_target_detail, verify_migration_database, verify_migration_target)
from current_migration_support import load_context, settings


@pytest.fixture(scope="module", autouse=True)
def current_authority():
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_migration_support import current413_bootstrap_parameters, current413_migration_database
        assert load_context()['authority_version'] == 413
        with current413_migration_database() as engine:
            with current413_bootstrap_parameters(engine):
                yield
        return
    load_context()
    yield


def reject(config, code):
    with pytest.raises(BootstrapFailure) as failure:
        _database_check(config)
    assert failure.value.code == code and str(failure.value) == code


_current_version = int(json.loads((Path(__file__).resolve().parents[2] / 'deploy/migrations/release-contract.json').read_text())['required_version'])


@pytest.mark.parametrize("version", [f"{_current_version:03d}", str(_current_version), f"{_current_version:03d}.0", f"{_current_version}_0_0"])
def test_actual_current_target_passes_numeric_equivalence(version):
    config = settings(version=version)
    assert _database_check(config).detail == migration_target_detail(config)


@pytest.mark.parametrize("database,code", [("previous", "database_migration_target_missing"),
    ("empty", "database_migration_history_missing"), ("baseline", "database_migration_target_invalid"),
    ("failed", "database_migration_target_missing")])
def test_real_history_states_fail_closed(database, code):
    reject(settings(database), code)


def test_missing_configuration_cannot_adopt_actual_database():
    config = settings(); config.migration_required_version = ""; config.migration_required_checksum = None
    reject(config, "database_migration_contract_missing")


def test_partial_configuration_is_not_a_default():
    config = settings(); config.migration_required_checksum = None
    reject(config, "database_migration_contract_missing")


def test_different_checksum_is_rejected():
    reject(settings(checksum=load_context()["checksum"] ^ 1), "database_migration_checksum_mismatch")


def test_higher_unapproved_schema_is_rejected():
    reject(settings(version=str(int(load_context()["required_version"]) - 1)), "database_migration_version_unexpected")


def test_real_unavailable_database_is_sanitized():
    config = settings()
    config.database_url = config.database_url.__class__(make_url(config.database_url.get_secret_value()).set(port=1).render_as_string(hide_password=False))
    reject(config, "database_unavailable")


def test_readonly_history_role_succeeds_and_cannot_write():
    config = settings(reader=True)
    assert _database_check(config).detail == migration_target_detail(config)
    engine = create_engine(config.database_url.get_secret_value(), hide_parameters=True)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SHOW transaction_read_only")) == "on"
            assert tuple(connection.execute(text("SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()) == (False, False, False, False)
            verify_migration_target(connection, config.migration_required_version, config.migration_required_checksum)
            with pytest.raises(DBAPIError):
                connection.execute(text("CREATE TABLE forbidden_gate_write(id integer)"))
    finally:
        engine.dispose()


@pytest.mark.parametrize("ensure", [True, False])
def test_bootstrap_rejects_before_other_checks_or_ensure_writes(ensure):
    config = DeploymentBootstrapSettings(_env_file=None, **settings("previous").model_dump())
    config.deployment_bootstrap_release = "chg370-migration-native"
    config.opensearch_url = "http://127.0.0.1:1"; config.neo4j_uri = "bolt://127.0.0.1:1"
    with pytest.raises(BootstrapFailure) as failure:
        run_bootstrap(config, ensure=ensure)
    assert failure.value.code == "database_migration_target_missing"


def test_history_only_database_still_blocks_missing_schema():
    reject(settings("target_only"), "database_schema_incomplete")


@pytest.mark.parametrize("database,passes", [("ready", True), ("previous", False)])
def test_shared_database_probe_uses_same_target(database, passes):
    config = settings(database)
    probe = MigrationProbeSettings(_env_file=None, database_url=config.database_url,
        migration_required_version=config.migration_required_version, migration_required_checksum=config.migration_required_checksum)
    assert "app_encryption_key" not in type(probe).model_fields
    if passes: verify_migration_database(probe)
    else:
        with pytest.raises(MigrationGateError, match="database_migration_target_missing"):
            verify_migration_database(probe)


def test_shared_transaction_is_bounded_consistent_and_readonly():
    with migration_connection(settings()) as connection:
        assert connection.scalar(text("SHOW transaction_read_only")) == "on"
        assert connection.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert connection.scalar(text("SHOW statement_timeout")) == "1s"


def test_frontend_target_matches_genuine_database_check():
    config = settings()
    target = MigrationTargetSettings(migration_required_version=load_context()["required_version"] + ".0", migration_required_checksum=config.migration_required_checksum)
    assert "database_url" not in type(target).model_fields
    check = _database_check(config)
    # Native validation input from a genuine DB check; not a full HTTP-ready or
    # release receipt and never consumed by package/release qualification.
    healthy = check.detail == migration_target_detail(config)
    payload = {"status": "ready" if healthy else "not_ready",
        "dependencies": {"deployment." + check.name: {"healthy": healthy, "detail": check.detail}}}
    assert migration_readiness_matches(payload, target)
    target.migration_required_checksum ^= 1
    assert not migration_readiness_matches(payload, target)


@pytest.mark.parametrize("checksum,code", [("", "database_migration_contract_missing"),
    ("1.5", "deployment_configuration_invalid"), ("0", "database_migration_target_missing")])
def test_cli_real_predecessor_exits_nonzero_with_safe_code(checksum, code):
    config = settings("previous")
    native_subprocess = os.environ.get("COVERAGE_PROCESS_CONFIG")
    env = {key: value for key, value in os.environ.items()
        if key in {"PATH", "HOME", "PYTHONPATH", "COVERAGE_FILE", "COVERAGE_RCFILE"}
        or (not native_subprocess and key.startswith("COV_CORE_"))}
    if native_subprocess:
        env["COVERAGE_PROCESS_CONFIG"] = native_subprocess
    env.update(APP_ENV="test", PYTHONSAFEPATH="1", PYTHONDONTWRITEBYTECODE="1", APP_ENCRYPTION_KEY=os.urandom(32).hex(),
        DATABASE_URL=config.database_url.get_secret_value(), MIGRATION_REQUIRED_VERSION=config.migration_required_version,
        MIGRATION_REQUIRED_CHECKSUM=checksum, MIGRATION_CHECK_TIMEOUT_SECONDS="1", DEPLOYMENT_BOOTSTRAP_RELEASE="chg370-cli")
    result = subprocess.run([sys.executable, "-m", "app.deployment.bootstrap", "--mode", "check", "--wait-seconds", "0"],
        env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1 and json.loads(result.stderr)["code"] == code
    assert "postgresql" not in result.stderr and "Traceback" not in result.stderr


def test_real_upgrade_preserves_disabled_user_and_requires_new_sessions():
    config = settings(); engine = create_engine(config.database_url.get_secret_value(), hide_parameters=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT is_active,locally_disabled FROM users WHERE display_name LIKE 'CHG370 migration native %' ORDER BY is_active")).all()
            assert rows == [(False, True), (True, False)]
            assert connection.scalar(text("SELECT count(*) FROM auth_sessions")) == 0
            assert connection.scalar(text("SELECT count(*) FROM authentication_identities")) == 0
            assert connection.scalar(text("SELECT count(*) FROM flyway_schema_history WHERE success AND type='SQL'")) == 54
    finally:
        engine.dispose()
