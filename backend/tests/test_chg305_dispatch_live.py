"""Real isolated PostgreSQL domain regression; NOT Worker/parser/Provider proof.

Run only in the next explicitly approved environment with V051 already applied.
No mocked broker/runtime/stop evidence and no manually successful pipeline.
"""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import FileProcessingTask, OutboxEvent
from app.domain.file_processing_dispatch import claim_task, finalize_task, prepare_dispatch, quiesce_task, require_claim
from chg305_support import CAPS, initialize, runs
from chg305_v051_support import isolated_case, live_db_v051


def test_real_db_single_claim_fencing_yield_and_finalization(live_db_v051):
    db = live_db_v051
    initialize(db)
    run = runs(db, 1)[0]
    with db["factory"].begin() as session:
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        session.add(OutboxEvent(id=uuid4(), topic="document.extraction.requested", aggregate_type="pipeline_run",
            aggregate_id=run, payload={}, status="pending", available_at=now, created_at=now, attempts=0))
        prepared = prepare_dispatch(session, run_id=run, capabilities=CAPS)
    with db["factory"].begin() as session:
        assert prepare_dispatch(session, run_id=run, capabilities=CAPS) == prepared
        assert not finalize_task(session, prepared.task_id)

    def contender(_):
        with db["factory"].begin() as session:
            return claim_task(session, task_id=prepared.task_id, generation=prepared.generation,
                broker_task_id=prepared.broker_task_id, worker_identity="isolated-domain-test:no-work-launched")

    with ThreadPoolExecutor(max_workers=5) as pool:
        claims = [claim for claim in pool.map(contender, range(5)) if claim]
    assert len(claims) == 1
    claim = claims[0]
    with db["factory"].begin() as session:
        require_claim(session, claim)
        # No business work started. Yield, not a fabricated successful pipeline.
        quiesce_task(session, claim, disposition="yield")
    with db["factory"].begin() as session:
        with pytest.raises(AppError, match="File-processing"):
            require_claim(session, claim)
    with db["factory"].begin() as session:
        assert finalize_task(session, prepared.task_id)
        assert not finalize_task(session, prepared.task_id)
    with db["factory"].begin() as session:
        next_dispatch = prepare_dispatch(session, run_id=run, capabilities=CAPS)
        assert next_dispatch.task_id != prepared.task_id
        assert next_dispatch.execution_id == prepared.execution_id
        assert next_dispatch.generation == prepared.generation
        assert session.scalar(select(FileProcessingTask.state).where(FileProcessingTask.id == prepared.task_id)) == "finalized"
    # Keep both task records; this database is never reused by another test case.
