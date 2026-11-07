"""Real Worker-local PDF/DB regression SOURCE; requires a new R20 scope.

One actual parser, no Provider. Run in its own separately approved disposable DB
and installed local tools, not after a failed scenario that left occupied tasks. Preserve
unknown execution evidence on failure for the campaign's exact cleanup.
"""
from __future__ import annotations
from datetime import UTC, datetime
import hashlib
import json
import os
import stat
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.models import DocumentVersion, FileProcessingExecution as Execution, PipelineRun, Project
from app.domain.file_processing_dispatch import (
    claim_task, configured_capabilities, finalize_task, prepare_dispatch, quiesce_task,
)
from chg305_support import initialize, runs
from chg305_v051_scope import load_case
from chg305_v051_support import isolated_case, live_db_v051


def private_bytes(path, maximum=16384):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        assert (stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid()
            and stat.S_IMODE(meta.st_mode) == 0o600 and meta.st_nlink == 1 and 0 < meta.st_size <= maximum)
        data = stream.read(maximum+1)
    assert len(data) <= maximum
    return data


@pytest.fixture
def approved_pdf_case(request):
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_pdf_client_support import current_pdf_client
        return current_pdf_client(request)
    path = os.environ.get("CHG305_PDF_CLIENT_SCOPE")
    expected = os.environ.get("CHG305_PDF_CLIENT_SCOPE_SHA256")
    if not path or not expected:
        pytest.fail("BLOCKED: new one-parser client acceptance scope required")
    data = private_bytes(path)
    assert hashlib.sha256(data).hexdigest() == expected
    scope = json.loads(data)
    assert set(scope) == {"schema", "disposable", "allow_one_parser", "deployment_id", "ownership_run_id",
        "expires_at", "execution_profile", "database", "pdf_file", "pdf_sha256", "pdf_bytes",
        "expected_page_sha256", "languages", "policy", "source_sha256"}
    assert type(scope["schema"]) is int and scope["schema"] == 2
    assert scope["disposable"] is True and scope["allow_one_parser"] is True
    assert 0 < (datetime.fromisoformat(scope["expires_at"]) - datetime.now(UTC)).total_seconds() <= 900
    root = Path(__file__).resolve().parents[1]
    sources = {"app/domain/pdf_processing.py", "app/domain/local_pdf/runner.py", "app/domain/local_pdf/process.py",
               "app/domain/local_pdf/files.py", "app/domain/local_pdf/tool_exec.py",
               "app/domain/document_execution.py", "tests/test_chg305_pdf_processing_live.py"}
    assert set(scope["source_sha256"]) == sources
    for name, digest in scope["source_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    settings = get_settings()
    assert scope["execution_profile"] == "worker-local-v1"
    db_scope, db_case = load_case(request.node.nodeid)
    assert db_case["scenario"] == "pdf_client"
    assert db_scope["run_id"] == scope["ownership_run_id"]
    assert UUID(db_scope["deployment_id"]) == UUID(scope["deployment_id"])
    assert db_case["database"] == scope["database"]
    target = make_url(settings.database_url.get_secret_value())
    assert {"host": target.host, "port": target.port, "database": target.database,
            "username": target.username} == scope["database"]
    db = request.getfixturevalue("live_db_v051")  # One-use real DB ownership check; no cleanup.
    return db, settings, scope


def test_actual_client_bind_progress_and_complete_with_autoflush_disabled(approved_pdf_case):
    from app.domain.pdf_processing import PDFProcessing
    db, settings, scope = approved_pdf_case
    assert set(scope["policy"]) == {"timeout", "pages", "upload"}
    assert type(scope["pdf_bytes"]) is int and 1 <= scope["pdf_bytes"] <= 16 * 1024**2
    body = private_bytes(scope["pdf_file"], maximum=scope["pdf_bytes"])
    assert len(body) == scope["pdf_bytes"] and hashlib.sha256(body).hexdigest() == scope["pdf_sha256"]
    assert isinstance(scope["expected_page_sha256"], list) and scope["expected_page_sha256"]
    capabilities = configured_capabilities(settings)
    initialize(db, capabilities=capabilities, **scope["policy"])
    run_id = runs(db, 1)[0]
    with db["factory"].begin() as session:
        run = session.get(PipelineRun, run_id)
        session.get(DocumentVersion, run.document_version_id).content_sha256 = scope["pdf_sha256"]
    with db["factory"].begin() as session:
        dispatch = prepare_dispatch(session, run_id=run_id, capabilities=capabilities)
    with db["factory"].begin() as session:
        claim = claim_task(session, task_id=dispatch.task_id, generation=dispatch.generation,
            broker_task_id=dispatch.broker_task_id, worker_identity="isolated-r20-worker:one-parser")
    with db["factory"]() as session:
        assert session.autoflush is False
        with PDFProcessing(session=session, settings=settings, claim=claim, program="text",
                           language_resolver=lambda: scope["languages"]) as pdf:
            pages = pdf.text_pages(body)
            assert [hashlib.sha256(page.encode("utf-8")).hexdigest() for page in pages] == scope["expected_page_sha256"]
            parser_id, launch_uid = pdf.admission.execution_id, pdf.local.launch_uid
            assert pdf.released
    with db["factory"]() as session:
        child, parent = session.get(Execution, parser_id), session.get(Execution, claim.execution_id)
        assert child.state == "completed" and child.released_at is not None
        assert child.workload_uid == launch_uid and child.image_digest is None
        assert child.profile == "worker-local-v1" and child.stop_evidence["source"] == "local_process"
        assert child.progress_revision >= 1 and child.unit == "pages"
        assert child.output_evidence["complete"] is True
        assert parent.state == "running" and parent.released_at is None
    # No extraction/Provider was started. Cancel this synthetic scope through its
    # actual generation fence, then use the trusted epilogue rather than asserting
    # submission_ready or injecting a stopped receipt.
    with db["factory"].begin() as session:
        run = session.get(PipelineRun, run_id)
        session.get(Project, run.project_id).work_generation += 1
    with db["factory"].begin() as session:
        quiesce_task(session, claim, disposition="cancelled")
    with db["factory"].begin() as session:
        assert finalize_task(session, claim.task_id)
    # Retain evidence; the separately approved campaign owns final resource cleanup.
