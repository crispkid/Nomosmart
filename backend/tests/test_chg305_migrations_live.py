"""P22 R01 real PostgreSQL/Flyway acceptance SOURCE; NOT_RUN under A.

Requires externally provisioned, one-use databases. Never import main/create_all,
insert Flyway history, delete evidence, or substitute success for a real service.
"""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.db.models import (AuditLog, FileProcessingExecution as Execution, FileProcessingPolicyRevision,
                           FileProcessingTask as Task, SystemParameter)
from app.deployment.migration_gate import MigrationGateError, verify_migration_target
from app.domain.file_processing_dispatch import prepare_dispatch
from app.domain.file_processing_settings import UNITS, load_policy
from chg305_support import CAPS, initialize, runs
from chg305_v051_flyway import BoundedFlyway
from chg305_v051_scope import ScopeError, digest
from chg305_v051_support import consume_case, isolated_case, live_db_v051, snapshot


NEW_TABLES = {"file_processing_policies", "file_processing_policy_revisions",
              "file_processing_pools", "file_processing_executions", "file_processing_tasks"}


def history(connection):
    if connection.scalar(text("SELECT to_regclass('public.flyway_schema_history')")) is None:
        return []
    return [tuple(row) for row in connection.execute(text(
        "SELECT installed_rank, version, type, script, checksum, success "
        "FROM public.flyway_schema_history ORDER BY installed_rank"))]


@pytest.mark.parametrize("scenario", ["fresh", "upgrade_049", "upgrade_050"])
def test_flyway_upgrade_preserves_data_and_is_idempotent(isolated_case, scenario):
    db = isolated_case
    assert db["case"]["scenario"] == scenario
    before = db["before"]
    if scenario != "fresh":
        # Empty upgrades do not prove preservation of real synthetic business rows.
        for name in ("users", "projects", "documents", "document_versions", "pipeline_runs", "system_parameters"):
            assert before[name]["count"] > 0
    if scenario == "upgrade_050":
        for name in NEW_TABLES - {"file_processing_tasks"}:
            assert before[name]["count"] > 0
    with db["engine"].connect() as connection:
        original_history = history(connection)
    runner = BoundedFlyway(db)
    runner.run("migrate")
    with db["engine"].connect().execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True) as connection:
        verify_migration_target(connection, "051", db["case"]["checksums"]["051"])
        after = snapshot(connection)
        current_history = history(connection)
        assert current_history[:len(original_history)] == original_history
        assert all(after[name] == value for name, value in before.items())
        if scenario != "fresh":
            assert set(after) - set(before) == (NEW_TABLES if scenario == "upgrade_049" else {"file_processing_tasks"})
        for name in NEW_TABLES - {"file_processing_pools"}:
            assert after[name]["count"] == before.get(name, {"count": 0})["count"]
        assert connection.execute(text("SELECT kind FROM public.file_processing_pools ORDER BY kind")).scalars().all() == ["document", "parser"]
        if scenario == "fresh":
            keys = connection.execute(text("SELECT key FROM public.system_parameters")).scalars().all()
            assert not set(keys).intersection(UNITS)  # DDL does not silently initialize policy.
        constraints = set(connection.execute(text(
            "SELECT conname FROM pg_constraint WHERE conrelid IN "
            "('public.file_processing_tasks'::regclass, 'public.file_processing_executions'::regclass)"
        )).scalars())
        assert {"ck_file_task_claim", "ck_file_task_final", "ck_file_task_completion",
                "uq_file_execution_attempt", "ck_file_execution_parent", "ck_file_execution_release"} <= constraints
        references = connection.execute(text(
            "SELECT confrelid::regclass::text, confdeltype FROM pg_constraint "
            "WHERE conrelid='public.file_processing_tasks'::regclass AND contype='f'"
        )).all()
        assert len(references) == 2 and all(row[0] == "file_processing_executions" and row[1] == "a" for row in references)
        indexes = set(connection.execute(text(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND "
            "tablename IN ('file_processing_tasks','file_processing_executions')"
        )).scalars())
        assert {"uq_file_task_active", "ix_file_task_state", "uq_file_execution_active", "ix_file_execution_occupancy"} <= indexes
        for version, checksum, expected_code in (
            ("049", db["case"]["checksums"]["049"], "database_migration_version_unexpected"),
            ("050", db["case"]["checksums"]["050"], "database_migration_version_unexpected"),
            ("051", db["case"]["checksums"]["051"] ^ 1, "database_migration_checksum_mismatch"),
        ):
            with pytest.raises(MigrationGateError) as error:
                verify_migration_target(connection, version, checksum)
            assert error.value.code == expected_code
        assert history(connection) == current_history
    runner.run("validate")
    runner.run("migrate")
    with db["engine"].connect() as connection:
        assert snapshot(connection) == after
        assert history(connection) == current_history
    if scenario == "fresh":
        runner.run("validate", changed_checksum=True)
        with db["engine"].connect() as connection:
            assert snapshot(connection) == after and history(connection) == current_history


@pytest.mark.parametrize("preserve", [False, True], ids=["empty", "existing"])
def test_v051_initializer_preserves_values_provenance_and_audit(live_db_v051, preserve):
    db = live_db_v051
    with db["factory"].begin() as session:
        with pytest.raises(AppError) as error:
            load_policy(session)
        assert error.value.code == "file_processing_policy_missing"
        if preserve:
            session.add(SystemParameter(key="pdf_parser_max_pages", value=333, default_value=222,
                value_type="integer", unit="pages", description="Reviewed synthetic legacy parameter"))
        session.add(SystemParameter(key="chg305_test_unrelated", value="retain", default_value="retain",
            value_type="string", description="Synthetic unrelated parameter"))
    with db["engine"].connect() as connection:
        baseline = snapshot(connection)
    original_principal = db["principal"]
    db["principal"] = replace(original_principal, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    try:
        with pytest.raises(AppError) as error:
            initialize(db)
        assert error.value.code == "token_expired"
    finally:
        db["principal"] = original_principal
    with db["engine"].connect() as connection:
        assert snapshot(connection) == baseline
    first = initialize(db, timeout=180, pages=500, upload=20)
    assert first.revision == 1 and first.settings.pdf_parser_max_pages == (333 if preserve else 500)
    assert first.settings.pdf_parser_timeout_seconds == 180 and first.settings.pdf_parser_max_output_mib == 80
    with db["factory"]() as session:
        keys = session.scalars(select(SystemParameter.key).where(SystemParameter.key.in_(UNITS))).all()
        assert len(keys) == 13 and set(keys) == set(UNITS)
        revision = session.get(FileProcessingPolicyRevision, 1)
        assert revision.provenance["preserved_keys"] == (["pdf_parser_max_pages"] if preserve else [])
        assert revision.provenance["legacy_timeout_seconds"] == 180
        assert revision.provenance["legacy_max_pages"] == 500 and revision.provenance["legacy_upload_mib"] == 20
        assert revision.snapshot == first.settings.model_dump(mode="json")
        assert revision.content_hash == first.settings.content_hash
        preserved = session.scalar(select(SystemParameter).where(SystemParameter.key == "pdf_parser_max_pages"))
        assert (preserved.default_value, preserved.value) == ((222, 333) if preserve else (500, 500))
        assert session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.actor_user_id == db["actor"], AuditLog.action == "file_processing.policy.updated")) == 1
        assert load_policy(session) == first
    with db["engine"].connect() as connection:
        initialized = snapshot(connection)
    assert initialize(db, timeout=120, pages=200, upload=100) == first
    with db["engine"].connect() as connection:
        assert snapshot(connection) == initialized  # Includes unchanged audit/history/unrelated rows.


def test_retained_task_fk_and_one_use_case_guard(live_db_v051):
    db = live_db_v051
    initialize(db)
    run_id = runs(db, 1)[0]
    with db["factory"].begin() as session:
        prepared = prepare_dispatch(session, run_id=run_id, capabilities=CAPS)
    with db["engine"].connect() as connection:
        retained = snapshot(connection)
    with db["factory"].begin() as session:
        with pytest.raises(IntegrityError) as error:
            with session.begin_nested():
                # Real failed SQL in a savepoint, not fixture cleanup or a fake FK.
                session.execute(delete(Execution).where(Execution.id == prepared.execution_id))
        assert error.value.orig.pgcode == "23503"
        assert session.get(Task, prepared.task_id) is not None
        assert session.get(Execution, prepared.execution_id).released_at is None
    with db["engine"].begin() as connection:
        with pytest.raises(ScopeError, match="^case_already_consumed$"):
            consume_case(connection, db["scope"], db["case"], db["node_id"])
    with db["engine"].connect() as connection:
        assert digest(snapshot(connection)) == digest(retained)
