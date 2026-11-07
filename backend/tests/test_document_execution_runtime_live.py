"""R20 genuine local PDF + disposable PostgreSQL lifecycle regression.

Replaces the retired Docker mailbox suite; no Provider and no fake stop receipt.
Existing live_db ownership guard is mandatory. Not run by source-only approval.
"""
from __future__ import annotations
from hashlib import sha256
import os
from pathlib import Path
import tempfile
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import DocumentVersion, FileProcessingExecution as Execution, PipelineRun
from app.domain.document_execution import begin_execution, claim_execution, execution_projection, record_progress, release_execution, transition_execution
from chg305_support import CAPS, initialize, live_db, runs
from pdf_local_samples import document


def invoke(db, method, admission, **kwargs):
    with db["factory"].begin() as session:
        return method(session, execution_id=admission.execution_id, generation=admission.generation, **kwargs)


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
def test_actual_parser_lifecycle_and_slot_release(live_db, terminal):
    from app.domain.document_execution import bind_local_workload  # Historical, unqualified retired contract.
    from app.domain.local_pdf.runner import LocalPDF
    from app.domain.local_pdf.errors import Rejected
    db = live_db
    initialize(db, timeout=60, pages=3, upload=1)
    body = b"%PDF-broken" if terminal == "failed" else document(1)
    run = runs(db, 1)[0]
    with db["factory"].begin() as session:
        pipeline = session.get(PipelineRun, run)
        session.get(DocumentVersion, pipeline.document_version_id).content_sha256 = sha256(body).hexdigest()
    with db["factory"].begin() as session:
        parent = claim_execution(session, run_id=run, kind="document", capabilities=CAPS)
    assert invoke(db, begin_execution, parent)
    with db["factory"].begin() as session:
        parser = claim_execution(session, run_id=run, kind="parser", capabilities=CAPS, parent_generation=parent.generation)
        values = dict(session.get(Execution, parser.execution_id).policy_snapshot)
    assert invoke(db, begin_execution, parser)
    with tempfile.TemporaryDirectory(prefix="r20-live-pdf-") as temporary:
        settings = Settings(_env_file=None).model_copy(update={"pdf_scratch_dir": str(Path(temporary).resolve())})
        runner = LocalPDF(settings, values, heartbeat=lambda: None, progress=lambda done,total: None)
        invoke(db, bind_local_workload, parser, worker_identity="r20-disposable-worker",
               worker_pid=os.getpid(), launch_uid=runner.launch_uid)
        with db["factory"].begin() as session:
            with pytest.raises(AppError) as error:
                bind_local_workload(session, execution_id=parser.execution_id, generation=uuid4(),
                    worker_identity="r20-disposable-worker", worker_pid=os.getpid(), launch_uid=runner.launch_uid)
            assert error.value.code == "file_processing_generation_stale"
        runner.setup()
        result = None
        try:
            if terminal == "failed":
                with pytest.raises(Rejected):
                    runner.run(body, "text", ["eng"])
            else:
                result = runner.run(body, "text", ["eng"])
                progress = dict(sequence=1, phase="parsing", completed=1, total=1, unit="pages")
                assert invoke(db, record_progress, parser, **progress)
                assert not invoke(db, record_progress, parser, **progress)
                for change in ({"completed": 0}, {"total": 2}, {"unit": "steps"}):
                    with pytest.raises(AppError):
                        invoke(db, record_progress, parser, **(progress | {"sequence": 2} | change))
        finally:
            runner.clean_parser()
            runner.store.close()
        stop = runner.stop_evidence(parser.generation)
        output = None if result is None else {"input_hash": sha256(body).hexdigest(),
            "generation": str(parser.generation), "complete": True, "output_hash": result["sha256"]}
        invoke(db, transition_execution, parser, state="stopping")
        for bad in ({}, stop | {"source": "runtime"}, stop | {"workload_uid": str(uuid4())},
                    stop | {"all_children_reaped": False}):
            with pytest.raises(AppError):
                invoke(db, release_execution, parser, terminal=terminal, stop_evidence=bad, output_evidence=output)
        with db["factory"]() as session:
            assert session.get(Execution, parser.execution_id).released_at is None
        if terminal == "completed":
            with pytest.raises(AppError):
                invoke(db, release_execution, parser, terminal=terminal, stop_evidence=stop, output_evidence=None)
        # 'cancelled' is an explicit domain cancellation before result publication,
        # after actual parsing and cleanup, not evidence of UI cancellation.
        invoke(db, release_execution, parser, terminal=terminal, stop_evidence=stop, output_evidence=output)
    with db["factory"]() as session:
        child = session.get(Execution, parser.execution_id)
        assert child.state == terminal and child.released_at is not None
        assert child.profile == "worker-local-v1" and child.image_digest is None
        assert session.get(Execution, parent.execution_id).released_at is None
        assert execution_projection(session, run)["phase"] == "processing"
