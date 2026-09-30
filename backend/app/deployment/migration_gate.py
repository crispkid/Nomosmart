"""Read-only verification of an operator-bound Flyway target, never migration."""
from __future__ import annotations

import re
from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import MigrationProbeSettings, MigrationTargetSettings


class MigrationGateError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def version_key(value: str) -> tuple[int, ...]:
    """Flyway numeric version semantics (leading/trailing zeros, dot/underscore)."""
    if not isinstance(value, str) or len(value) > 80 or not re.fullmatch(r"[0-9]+(?:[._][0-9]+)*", value):
        raise MigrationGateError("database_migration_version_invalid")
    parts = [int(part) for part in re.split(r"[._]", value)]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def required_contract(
    version: str, checksum: int | None, baseline_checksum: int | None = None,
) -> tuple[tuple[int, ...], int]:
    if not version or checksum is None:
        raise MigrationGateError("database_migration_contract_missing")
    target = version_key(version)
    if target == (0,) or type(checksum) is not int or not -(2**31) <= checksum < 2**31:
        raise MigrationGateError("database_migration_contract_invalid")
    if baseline_checksum is not None and (
        type(baseline_checksum) is not int or not -(2**31) <= baseline_checksum < 2**31
    ):
        raise MigrationGateError("database_migration_contract_invalid")
    return target, checksum


def verify_migration_target(
    connection: Connection, version: str, checksum: int | None,
    baseline_checksum: int | None = None,
) -> None:
    target, expected = required_contract(version, checksum, baseline_checksum)
    trusted_checksums = {"SQL": expected}
    if baseline_checksum is not None:
        trusted_checksums["SQL_BASELINE"] = baseline_checksum
    if not connection.scalar(text("SELECT to_regclass('public.flyway_schema_history')")):
        raise MigrationGateError("database_migration_history_missing")
    # Schema-qualified: a search_path override must not substitute another history.
    rows = connection.execute(text(
        "SELECT version, type, checksum, success FROM public.flyway_schema_history "
        "ORDER BY installed_rank"
    )).mappings().all()
    if any(not row["success"] for row in rows):
        raise MigrationGateError("database_migration_failed")
    targets = []
    for row in rows:
        if row["version"] is None:  # Successful repeatables are not the version target.
            continue
        actual = version_key(row["version"])
        if actual > target:
            raise MigrationGateError("database_migration_version_unexpected")
        if actual == target:
            targets.append(row)
    if not targets:
        raise MigrationGateError("database_migration_target_missing")
    if len(targets) != 1 or targets[0]["type"] not in trusted_checksums:
        raise MigrationGateError("database_migration_target_invalid")
    if targets[0]["checksum"] != trusted_checksums[targets[0]["type"]]:
        raise MigrationGateError("database_migration_checksum_mismatch")


@contextmanager
def migration_connection(settings: MigrationProbeSettings) -> Iterator[Connection]:
    """Shared bounded, consistent and read-only transaction for all init paths."""
    required_contract(settings.migration_required_version, settings.migration_required_checksum,
                      settings.migration_baseline_checksum)
    engine = None
    try:
        engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True,
                               connect_args={"connect_timeout": settings.migration_check_timeout_seconds})
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True,
        ) as connection:
            connection.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                               {"timeout": str(settings.migration_check_timeout_seconds * 1000)})
            verify_migration_target(connection, settings.migration_required_version,
                                    settings.migration_required_checksum, settings.migration_baseline_checksum)
            yield connection
    except SQLAlchemyError as exc:
        raise MigrationGateError("database_unavailable") from exc
    finally:
        if engine is not None:
            engine.dispose()


def verify_migration_database(settings: MigrationProbeSettings) -> None:
    with migration_connection(settings):
        pass


def migration_target_detail(settings: MigrationTargetSettings) -> str:
    target, checksum = required_contract(settings.migration_required_version, settings.migration_required_checksum,
                                        settings.migration_baseline_checksum)
    detail = "migrated:" + ".".join(map(str, target)) + ":" + str(checksum)
    if settings.migration_baseline_checksum is not None:
        detail += ":SQL_BASELINE:" + str(settings.migration_baseline_checksum)
    return detail


def migration_readiness_matches(payload: object, settings: MigrationTargetSettings) -> bool:
    """Match successful Backend verification, not a legacy HTTP-200 response."""
    expected = migration_target_detail(settings)
    if not isinstance(payload, dict) or payload.get("status") != "ready":
        return False
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, dict):
        return False
    database = dependencies.get("deployment.database")
    return (isinstance(database, dict) and database.get("healthy") is True
            and database.get("detail") == expected)
