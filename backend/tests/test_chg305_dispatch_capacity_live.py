"""P23 real PostgreSQL domain cases; NOT running-Worker/container evidence."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import FileProcessingExecution as Execution, OutboxEvent, PipelineRun
from app.domain.document_execution import claim_execution
from app.domain.file_processing_dispatch import (
    claim_task, finalize_task, prepare_dispatch, quiesce_task, require_claim,
)
from app.domain.file_processing_settings import update_policy
from chg305_support import CAPS, initialize, runs
from chg305_v051_support import isolated_case, live_db_v051


def prepare(db, run):
    with db["factory"].begin() as session:
        now = datetime.now(UTC)
        session.add(OutboxEvent(id=uuid4(), topic="document.extraction.requested",
            aggregate_type="pipeline_run", aggregate_id=run, payload={}, status="pending",
            available_at=now, created_at=now, attempts=0))
        session.flush()
        return prepare_dispatch(session, run_id=run, capabilities=CAPS)


def claim(db, dispatch):
    with db["factory"].begin() as session:
        result = claim_task(session, task_id=dispatch.task_id, generation=dispatch.generation,
            broker_task_id=dispatch.broker_task_id, worker_identity="p23:domain-no-business-work")
        assert result is not None
        return result


def test_capacity_downscale_drain_then_upscale_preserves_snapshots(live_db_v051):
    db = live_db_v051
    initial = initialize(db)
    ids = runs(db, 13)
    dispatched = [prepare(db, run) for run in ids[:8]]
    claims = [claim(db, item) for item in dispatched]
    with db["factory"].begin() as session:
        update_policy(session, principal=db["principal"], expected_revision=1,
            changes={"document_processing_max_concurrent": 5, "pdf_parser_max_pages": 500},
            capabilities=CAPS)
    assert prepare(db, ids[8]) is None
    with db["factory"].begin() as session:
        rows = session.scalars(select(Execution)).all()
        assert len(rows) == 8 and all(row.state == "running" and row.released_at is None for row in rows)
        assert all(row.policy_hash == initial.settings.content_hash for row in rows)
    for held in claims[:4]:
        with db["factory"].begin() as session:
            # Synthetic cancellation of work never launched. Not UI/permission proof.
            session.get(PipelineRun, held.run_id).status = "cancelled"
            session.flush()
            quiesce_task(session, held, disposition="cancelled")
        with db["factory"].begin() as session:
            assert finalize_task(session, held.task_id)
    with db["factory"].begin() as session:
        fifth = prepare_dispatch(session, run_id=ids[8], capabilities=CAPS)
        assert fifth is not None
    claim(db, fifth)
    assert prepare(db, ids[9]) is None
    with db["factory"].begin() as session:
        update_policy(session, principal=db["principal"], expected_revision=2,
            changes={"document_processing_max_concurrent": 8}, capabilities=CAPS)
        resumed = prepare_dispatch(session, run_id=ids[9], capabilities=CAPS)
    claim(db, resumed)
    for run in ids[10:12]:
        claim(db, prepare(db, run))
    assert prepare(db, ids[12]) is None
    with db["factory"].begin() as session:
        rows = session.scalars(select(Execution)).all()
        occupied = [row for row in rows if row.released_at is None]
        assert len(rows) == 12 and len(occupied) == 8
        old = {item.execution_id for item in dispatched}
        assert all(row.policy_snapshot["pdf_parser_max_pages"] == (200 if row.id in old else 500)
                   for row in rows)
        assert all(row.state == "cancelled" for row in rows if row.released_at is not None)


def test_parser_current_cap_parent_snapshot_and_yield_fence(live_db_v051):
    db = live_db_v051
    initialize(db)
    with db["factory"].begin() as session:
        update_policy(session, principal=db["principal"], expected_revision=1,
            changes={"document_processing_max_concurrent": 2, "pdf_parser_max_concurrent": 1}, capabilities=CAPS)
    ids = runs(db, 3)
    first, second = (prepare(db, run) for run in ids[:2])
    claim(db, first)
    old_claim = claim(db, second)
    assert prepare(db, ids[2]) is None
    with db["factory"].begin() as session:
        parser = claim_execution(session, run_id=ids[0], kind="parser", capabilities=CAPS,
                                 parent_generation=first.generation)
        assert parser is not None
    with db["factory"].begin() as session:
        assert claim_execution(session, run_id=ids[1], kind="parser", capabilities=CAPS,
                               parent_generation=second.generation) is None
        quiesce_task(session, old_claim, disposition="yield")
    with db["factory"].begin() as session:
        assert finalize_task(session, second.task_id)
    with db["factory"].begin() as session:
        replacement = prepare_dispatch(session, run_id=ids[1], capabilities=CAPS)
        assert replacement.task_id != second.task_id
        assert replacement.execution_id == second.execution_id
        assert claim_task(session, task_id=second.task_id, generation=second.generation,
            broker_task_id=second.broker_task_id, worker_identity="p23:obsolete") is None
    with db["factory"].begin() as session:
        with pytest.raises(AppError) as error:
            require_claim(session, old_claim)
        assert error.value.code == "file_processing_task_fenced"
    claim(db, replacement)
    with db["factory"].begin() as session:
        update_policy(session, principal=db["principal"], expected_revision=2,
            changes={"pdf_parser_max_concurrent": 2, "pdf_parser_max_pages": 500}, capabilities=CAPS)
        next_parser = claim_execution(session, run_id=ids[1], kind="parser", capabilities=CAPS,
                                      parent_generation=second.generation)
        assert next_parser is not None
    with db["factory"].begin() as session:
        rows = session.scalars(select(Execution)).all()
        assert len(rows) == 4 and all(row.released_at is None for row in rows)
        parsers = [row for row in rows if row.kind == "parser"]
        assert len(parsers) == 2 and all(row.state == "reserved" for row in parsers)
        assert all(row.policy_snapshot["pdf_parser_max_pages"] == 200 for row in parsers)
    # Parser reservations are retained. No container or stop receipt is invented.
