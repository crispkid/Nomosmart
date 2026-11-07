"""Real DB concurrency/fencing; deliberately not complete pipeline/runtime proof."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.db.models import FileProcessingExecution as Execution
from app.domain.document_execution import begin_execution, claim_execution, execution_projection, record_progress, release_execution, transition_execution
from app.domain.file_processing_settings import update_policy
from chg305_support import CAPS, initialize, live_db, runs


def claim(db, run_id, kind="document", parent_generation=None):
    with db["factory"].begin() as session:
        return claim_execution(session, run_id=run_id, kind=kind, capabilities=CAPS, parent_generation=parent_generation)


def invoke(db, method, admission, **kwargs):
    with db["factory"].begin() as session:
        return method(session, execution_id=admission.execution_id, generation=admission.generation, **kwargs)


def test_25_real_contenders_global_10_and_duplicate_start(live_db):
    db = live_db
    initialize(db)
    ids = runs(db, 25)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda run: claim(db, run), ids))
    accepted = [item for item in results if item]
    assert len(accepted) == 10
    with db["factory"].begin() as session:
        assert session.scalar(select(func.count()).select_from(Execution)) == 10
        assert session.scalar(select(func.count()).select_from(Execution).where(Execution.kind == "parser")) == 0
    one = accepted[0]
    with ThreadPoolExecutor(max_workers=8) as pool:
        started = list(pool.map(lambda _: invoke(db, begin_execution, one), range(8)))
    assert started.count(True) == 1
    again = claim(db, ids[results.index(one)])
    assert not again.created and again.execution_id == one.execution_id


def test_downscale_keeps_eight_running_and_snapshot(live_db):
    db = live_db
    first = initialize(db)
    ids = runs(db, 10)
    accepted = [claim(db, run) for run in ids[:8]]
    for item in accepted:
        assert invoke(db, begin_execution, item)
    with db["factory"].begin() as session:
        update_policy(session, principal=db["principal"], expected_revision=1,
            changes={"document_processing_max_concurrent": 5}, capabilities=CAPS)
    assert claim(db, ids[8]) is None
    with db["factory"].begin() as session:
        rows = session.scalars(select(Execution)).all()
        assert len(rows) == 8 and all(row.state == "running" for row in rows)
        assert all(row.policy_hash == first.settings.content_hash and row.policy_snapshot["_schema_version"] == 2 and row.policy_snapshot["document_processing_timeout_seconds"] == 120 for row in rows)


def test_two_documents_one_parser_uses_latest_cap_and_parent_resources(live_db):
    db = live_db
    initialize(db)
    with db["factory"].begin() as session:
        update_policy(session, principal=db["principal"], expected_revision=1,
            changes={"document_processing_max_concurrent": 2}, capabilities=CAPS)
    ids = runs(db, 3)
    a, b = claim(db, ids[0]), claim(db, ids[1])
    assert claim(db, ids[2]) is None
    assert invoke(db, begin_execution, a) and invoke(db, begin_execution, b)
    # OCRSIM-009: no new parser reservation is legal. The document slot and
    # stop/recovery protections remain actual database behavior.
    with pytest.raises(AppError) as retired:
        claim(db, ids[0], "parser", a.generation)
    assert retired.value.code == "file_processing_parser_retired"
    invoke(db, transition_execution, a, state="stopping")
    assert claim(db, ids[2]) is None
    invoke(db, transition_execution, a, state="recovery_required", error_code="worker_response_lost")
    assert claim(db, ids[2]) is None
    with db["factory"].begin() as session:
        assert session.scalar(select(func.count()).select_from(Execution).where(Execution.kind == "document", Execution.released_at.is_(None))) == 2
        assert session.scalar(select(func.count()).select_from(Execution).where(Execution.kind == "parser")) == 0


def test_missing_and_stale_parent_generation_rejected(live_db):
    db = live_db
    initialize(db)
    run = runs(db, 1)[0]
    with pytest.raises(AppError):
        claim(db, run, "parser", uuid4())
    doc = claim(db, run)
    with pytest.raises(AppError):
        claim(db, run, "parser", doc.generation)
    invoke(db, begin_execution, doc)
    with pytest.raises(AppError):
        claim(db, run, "parser", uuid4())
    with db["factory"].begin() as session:
        with pytest.raises(AppError):
            begin_execution(session, execution_id=doc.execution_id, generation=uuid4())


def test_progress_truthful_monotonic_scoped_projection(live_db):
    db = live_db
    initialize(db)
    run, old = runs(db, 2)
    doc = claim(db, run)
    invoke(db, begin_execution, doc)
    assert invoke(db, record_progress, doc, sequence=1, phase="processing", completed=0, total=None, unit="steps")
    assert not invoke(db, record_progress, doc, sequence=1, phase="processing", completed=0, total=None, unit="steps")
    assert not invoke(db, record_progress, doc, sequence=2, phase="processing", completed=1, total=3, unit="steps")
    with pytest.raises(AppError):
        invoke(db, record_progress, doc, sequence=3, phase="processing", completed=4, total=3, unit="steps")
    with db["factory"].begin() as session:
        assert execution_projection(session, old) is None
        projection = execution_projection(session, run)
        assert projection["total_units"] is None
        assert "policy_snapshot" not in projection and "workload_id" not in projection
        assert projection["poll_interval_seconds"] == 2


def test_lost_heartbeat_never_releases_and_requires_stop_evidence(live_db):
    db = live_db
    initialize(db)
    ids = runs(db, 2)
    doc = claim(db, ids[0])
    invoke(db, begin_execution, doc)
    with db["factory"].begin() as session:
        session.get(Execution, doc.execution_id).heartbeat_at = datetime.now(UTC) - timedelta(days=1)
    invoke(db, transition_execution, doc, state="recovery_required", error_code="worker_heartbeat_expired")
    assert claim(db, ids[1]) is None
    with pytest.raises(AppError):
        invoke(db, release_execution, doc, terminal="failed", stop_evidence={"stopped": False})
    with db["factory"].begin() as session:
        assert session.get(Execution, doc.execution_id).released_at is None


def test_invalid_transition_workload_and_unstarted_release(live_db):
    from app.domain import document_execution
    assert not hasattr(document_execution, "bind_workload"), "Retired runtime binding must not return"
    db = live_db
    initialize(db)
    run = runs(db, 1)[0]
    doc = claim(db, run)
    with pytest.raises(AppError):
        invoke(db, transition_execution, doc, state="completed")
    with pytest.raises(AppError):
        invoke(db, release_execution, doc, terminal="completed", stop_evidence={})
    with pytest.raises(AppError) as retired:
        claim(db, run, "parser", doc.generation)
    assert retired.value.code == "file_processing_parser_retired"
    with pytest.raises(AppError):
        invoke(db, transition_execution, doc, state="recovery_required", error_code="untrusted document text\n")
