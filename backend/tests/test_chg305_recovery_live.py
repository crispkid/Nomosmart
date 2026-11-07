"""Real isolated PostgreSQL recovery-domain sources; NOT_RUN in R12 A.

No runtime or business work is launched here. A reserved, unreleased parser is
deliberately UNKNOWN, not fake stop evidence. Runtime/fault/OIDC proof is separate.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.db.models import FileProcessingExecution as Execution, FileProcessingTask as Task, PipelineRun, Project
from app.domain.document_execution import claim_execution
from app.domain.file_processing_dispatch import (
    claim_task, finalizable_task_ids, finalize_task, mark_stale_tasks,
    prepare_dispatch, quiesce_task, require_claim,
)
from chg305_support import CAPS, initialize, runs
from chg305_v051_support import isolated_case, live_db_v051


@pytest.fixture
def recovery_db(request):
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_recovery_domain_support import current_recovery_domain_db
        with current_recovery_domain_db(request.node.nodeid) as db:
            yield db
        return
    yield request.getfixturevalue('live_db_v051')


@contextmanager
def claimed(db, *, child=False):
    initialize(db)
    run_id = runs(db, 1)[0]
    with db["factory"].begin() as session:
        dispatch = prepare_dispatch(session, run_id=run_id, capabilities=CAPS)
    with db["factory"].begin() as session:
        claim = claim_task(session, task_id=dispatch.task_id, generation=dispatch.generation,
            broker_task_id=dispatch.broker_task_id, worker_identity="isolated-recovery-domain:no-work-launched")
    parser = None
    if child:
        with db["factory"].begin() as session:
            parser = claim_execution(session, run_id=run_id, kind="parser", capabilities=CAPS,
                parent_generation=claim.generation)
    yield claim, parser
    # Retain task + UNKNOWN child evidence, also when an assertion fails.


def change_project_generation(db, claim):
    with db["factory"].begin() as session:
        run = session.get(PipelineRun, claim.run_id)
        project = session.get(Project, run.project_id)
        project.work_generation += 1  # Real isolated domain mutation, not a successful pipeline.


def test_cooperative_cancel_without_child_finalizes_once(recovery_db):
    db = recovery_db
    with claimed(db) as (claim, _):
        change_project_generation(db, claim)
        with db["factory"].begin() as session:
            quiesce_task(session, claim, disposition="cancelled")
        with db["factory"].begin() as session:
            assert claim.task_id in finalizable_task_ids(session)

        def finisher(_):
            with db["factory"].begin() as session:
                return finalize_task(session, claim.task_id)

        with ThreadPoolExecutor(max_workers=5) as pool:
            assert list(pool.map(finisher, range(5))).count(True) == 1
        with db["factory"].begin() as session:
            assert not finalize_task(session, claim.task_id)
        with db["factory"]() as session:
            task = session.get(Task, claim.task_id)
            parent = session.get(Execution, claim.execution_id)
            assert task.state == "finalized" and parent.state == "cancelled"
            assert parent.released_at is not None
            assert task.completion_receipt["body_quiesced_at"] == task.completion_receipt["quiesced_at"]


def test_body_receipt_with_unknown_child_keeps_both_slots(recovery_db):
    db = recovery_db
    with claimed(db, child=True) as (claim, parser):
        change_project_generation(db, claim)
        with db["factory"].begin() as session:
            quiesce_task(session, claim, disposition="cancelled")
        with db["factory"].begin() as session:
            task = session.get(Task, claim.task_id)
            assert task.state == "recovery_required"
            assert task.completion_receipt["source"] == "claimant_epilogue_v1"
            assert task.completion_receipt["body_quiesced_at"]
            assert "quiesced_at" not in task.completion_receipt
            assert not finalize_task(session, task.id)
            assert task.id not in finalizable_task_ids(session)
            for key in (claim.execution_id, parser.execution_id):
                row = session.get(Execution, key)
                assert row.released_at is None and row.stop_evidence is None
        with db["factory"].begin() as session:
            with pytest.raises(AppError) as error:
                require_claim(session, claim, check_scope=False)
            assert error.value.code == "file_processing_task_fenced"


def test_expired_heartbeat_without_epilogue_does_not_release(recovery_db):
    db = recovery_db
    with claimed(db) as (claim, _):
        with db["factory"].begin() as session:
            session.get(Task, claim.task_id).heartbeat_at = datetime.now(UTC) - timedelta(seconds=61)
        with db["factory"].begin() as session:
            assert mark_stale_tasks(session, stale_seconds=30) == 1
        with db["factory"].begin() as session:
            task = session.get(Task, claim.task_id)
            assert task.state == "recovery_required" and task.completion_receipt is None
            assert not finalize_task(session, task.id)
            assert task.id not in finalizable_task_ids(session)
            assert session.get(Execution, claim.execution_id).released_at is None


def test_wrong_claim_in_real_db_receipt_is_rejected(recovery_db):
    db = recovery_db
    with claimed(db) as (claim, _):
        change_project_generation(db, claim)
        with db["factory"].begin() as session:
            quiesce_task(session, claim, disposition="cancelled")
        with db["factory"].begin() as session:
            task = session.get(Task, claim.task_id)
            task.completion_receipt = {**task.completion_receipt, "claim_token": str(uuid4())}
        with db["factory"].begin() as session:
            with pytest.raises(AppError) as error:
                finalize_task(session, claim.task_id)
            assert error.value.code == "file_processing_completion_receipt_invalid"
            assert session.get(Execution, claim.execution_id).released_at is None
