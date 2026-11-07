"""P23 real Redis + production solo Worker, guarded before all Provider work.

NOT_RUN in A. Requires CHG305_V051 and CHG305_WORKER scopes; no fake adapter,
clock manipulation, task epilogue injection or success-state setup.
"""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import os
import time

import pytest
from sqlalchemy import func, select, text

from app.db.models import FileProcessingExecution as Execution, FileProcessingTask as Task, PipelineRun, Project
from app.domain.file_processing_dispatch import finalize_task, mark_stale_tasks, prepare_dispatch
from chg305_support import CAPS, initialize, runs
from chg305_v051_scope import ScopeError, require
from chg305_v051_support import isolated_case, live_db_v051
from chg305_worker_fault_support import WorkerHarness


BUSINESS_TABLES = ("ai_models", "ai_model_usage_events", "pipeline_run_steps", "chunks", "embedding_builds", "embedding_build_vectors")


def no_business_work(db):
    with db["engine"].connect() as connection:
        for name in BUSINESS_TABLES:  # Fixed local identifiers, never scope/input SQL.
            require(connection.scalar(text(f"SELECT count(*) FROM public.{name}")) == 0, "unexpected_business_work")
        require(connection.scalar(text("SELECT count(*) FROM file_processing_executions WHERE kind='parser'")) == 0,
                "unexpected_parser_work")


@contextmanager
def real_worker_case(db):
    __tracebackhide__ = True
    try:
        no_business_work(db)
        initialize(db)
        run_id = runs(db, 1)[0]
        with db["factory"].begin() as session:
            dispatch = prepare_dispatch(session, run_id=run_id, capabilities=CAPS)
            require(dispatch is not None, "worker_dispatch_missing")
        with db["factory"].begin() as session:
            run = session.get(PipelineRun, run_id)
            session.get(Project, run.project_id).work_generation += 1
        # Claim may run; scope check must reject before extraction on ALL paths.
        harness = WorkerHarness
        if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
            from current_worker_fault_support import CurrentOwnedWorkerHarness
            harness = CurrentOwnedWorkerHarness
        with harness(db) as worker:
            yield worker, dispatch
            no_business_work(db)
    except Exception as error:
        code = str(error) if isinstance(error, ScopeError) else "worker_case_failed"
        pytest.fail("P23 incomplete: " + code, pytrace=False)


def task_observation(db, dispatch):
    with db["factory"]() as session:
        assert session.scalar(select(func.count()).select_from(Task)) == 1
        assert session.scalar(select(func.count()).select_from(Execution)) == 1
        task = session.get(Task, dispatch.task_id)
        parent = session.get(Execution, dispatch.execution_id)
        return {"state": task.state, "claim_token": task.claim_token, "worker": task.worker_identity,
                "receipt": task.completion_receipt, "heartbeat": task.heartbeat_at,
                "execution_state": parent.state, "released_at": parent.released_at,
                "run_status": session.get(PipelineRun, dispatch.run_id).status}


def test_real_worker_duplicate_delivery_has_one_cancellation_epilogue(live_db_v051):
    db = live_db_v051
    with real_worker_case(db) as (worker, dispatch):
        process, host = worker.start()
        worker.publish(dispatch)
        worker.wait_for(lambda: len(worker.deliveries(dispatch)) == 1)
        first = task_observation(db, dispatch)
        assert first["state"] == "quiescent" and first["claim_token"] is not None
        assert first["worker"] == f"{host}:{process.pid}"
        assert first["receipt"]["source"] == "claimant_epilogue_v1"
        assert first["receipt"]["disposition"] == "cancelled"
        assert first["receipt"]["claim_token"] == str(first["claim_token"])
        assert first["released_at"] is None and first["run_status"] == "failed"
        worker.publish(dispatch)
        worker.wait_for(lambda: len(worker.deliveries(dispatch)) == 2)
        assert len(worker.deliveries(dispatch, "task-received")) == 2
        assert not worker.deliveries(dispatch, "task-failed")
        assert task_observation(db, dispatch) == first
        with db["factory"].begin() as session:
            assert finalize_task(session, dispatch.task_id)
        with db["factory"].begin() as session:
            assert not finalize_task(session, dispatch.task_id)
        after = task_observation(db, dispatch)
        assert after["state"] == "finalized" and after["execution_state"] == "cancelled"
        assert after["released_at"] is not None and after["receipt"] == first["receipt"]


def worker_connections(db, worker, *, blocker=None):
    with db["engine"].connect() as connection:
        sql = "SELECT count(*) FROM pg_stat_activity WHERE application_name=:name AND usename=current_user"
        values = {"name": worker.application_name}
        if blocker is not None:
            sql += " AND wait_event_type='Lock' AND :blocker=ANY(pg_blocking_pids(pid))"
            values["blocker"] = blocker
        return connection.scalar(text(sql), values)


def test_real_worker_crash_expiry_restart_replay_keeps_slot(live_db_v051):
    db = live_db_v051
    with real_worker_case(db) as (worker, dispatch):
        diagnostic_count = 0

        def observe_connections(phase):
            nonlocal diagnostic_count
            diagnostic_count += 1
            require(diagnostic_count <= 8, 'worker_diagnostic_budget')
            try:
                with db['engine'].begin() as connection:
                    connection.execute(text("SET LOCAL statement_timeout='2000'"))
                    connection.execute(text("SET LOCAL lock_timeout='1000'"))
                    check_interval = connection.scalar(text('SHOW client_connection_check_interval'))
                    rows = connection.execute(text("""SELECT pid, backend_start, state, wait_event_type,
                        wait_event, pg_blocking_pids(pid) AS blockers FROM pg_stat_activity
                        WHERE datname=current_database() AND usename=current_user AND application_name=:name
                        ORDER BY pid LIMIT 33"""), {'name': worker.application_name}).mappings().all()
                    require(len(rows) <= 32, 'worker_diagnostic_row_budget')
                    metadata = [dict(row, backend_start=row['backend_start'].isoformat()) for row in rows]
                worker.record('worker_pg_observation', phase=phase, monotonic_ns=time.monotonic_ns(),
                    rows=metadata, observer_client_connection_check_interval=check_interval)
            except Exception as error:
                # Record only a safe type; never mask a primary case failure with diagnostic failure.
                worker.record('worker_pg_observation_failed', phase=phase, monotonic_ns=time.monotonic_ns(),
                    error_type=type(error).__name__)
                return False
            return True

        process, first_host = worker.start()
        with db["engine"].connect() as holder:
            transaction = holder.begin()
            try:
                holder.execute(text("SET LOCAL idle_in_transaction_session_timeout='20000'"))
                holder.execute(text("SELECT id FROM pipeline_runs WHERE id=:run FOR UPDATE"), {"run": dispatch.run_id}).one()
                blocker = holder.scalar(text("SELECT pg_backend_pid()"))
                worker.publish(dispatch)
                worker.wait_for(lambda: task_observation(db, dispatch)["state"] == "claimed"
                    and worker_connections(db, worker, blocker=blocker) == 1, seconds=8)
                before = task_observation(db, dispatch)
                assert before["worker"] == f"{first_host}:{process.pid}" and before["receipt"] is None
                assert before["run_status"] == "queued"
                worker.record("claim_and_lock_observed", task_id=str(dispatch.task_id), blocker_pid=blocker)
                before_observed = observe_connections('claimed_before_kill')
                worker.crash(process)
                killed_observed = observe_connections('killed_controller_lock_held')
            finally:
                transaction.rollback()  # Release only our test lock; no pipeline update or synthetic clock.
                worker.record('controller_lock_released', monotonic_ns=time.monotonic_ns())
            unlocked_observed = observe_connections('controller_lock_released')
            try:
                worker.wait_for(lambda: worker_connections(db, worker) == 0, seconds=5)
            except Exception:
                observe_connections('connection_wait_failed')
                raise
            disconnected_observed = observe_connections('worker_connections_zero')
            assert before_observed and killed_observed and unlocked_observed and disconnected_observed
        after_crash = task_observation(db, dispatch)
        assert {k: v for k, v in after_crash.items() if k != "heartbeat"} == {
            k: v for k, v in before.items() if k != "heartbeat"}
        assert after_crash["heartbeat"] >= before["heartbeat"]

        def expired():
            with db["factory"]() as session:
                return session.scalar(select(Task.id).where(Task.id == dispatch.task_id,
                    Task.heartbeat_at < func.clock_timestamp() - text("interval '31 seconds'"),
                    Task.heartbeat_at < datetime.now(UTC) - timedelta(seconds=31))) is not None

        worker.wait_for(expired, seconds=45)
        with db["factory"].begin() as session:
            assert mark_stale_tasks(session, stale_seconds=30) == 1
        held = task_observation(db, dispatch)
        assert held["state"] == held["execution_state"] == "recovery_required"
        assert held["receipt"] is None and held["released_at"] is None
        with db["factory"].begin() as session:
            assert not finalize_task(session, dispatch.task_id)
        # An unrelated valid project is still blocked by the uncertain global slot.
        waiting = runs(db, 1)[0]
        with db["factory"].begin() as session:
            assert prepare_dispatch(session, run_id=waiting, capabilities=CAPS) is None
        _, second_host = worker.start()
        worker.publish(dispatch)  # Explicit real replay, NOT visibility-timeout recovery.
        worker.wait_for(lambda: len(worker.deliveries(dispatch, host=second_host)) == 1)
        assert len(worker.deliveries(dispatch, "task-received", host=second_host)) == 1
        assert not worker.deliveries(dispatch, "task-failed")
        assert task_observation(db, dispatch) == held
        # Unknown completion remains occupied. No repair, cleanup or third send.
