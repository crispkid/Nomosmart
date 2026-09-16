"""CHG295-B01: actual PostgreSQL lock ordering; no Provider or fake sessions.

Storage inputs exercise edit/reconciliation fencing, not successful generation.
The dedicated test database must be freshly migrated through V048 by the caller.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import os
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.routes.documents import _ensure_manual_edit_allowed, _ensure_tag_mutable
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import ChatRecord, Chunk, Document, DocumentVersion, OutboxEvent, Project, User
from app.domain.chunk_artifacts import execute_chunk_artifact_reconciliation, queue_chunk_artifact_reconciliation


@pytest.fixture(scope="module")
def database():
    url = os.environ.get("CHG295_BUG_DATABASE_URL")
    if not url:
        pytest.fail("BLOCKED: CHG295_BUG_DATABASE_URL must identify the fresh disposable test database")
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def candidate(database):
    project, document, version = uuid4(), uuid4(), uuid4()
    with Session(database) as session:
        session.add(Project(id=project, name="CHG295 lock-order input", status="active"))
        session.flush()
        session.add(Document(id=document, project_id=project, document_code=str(document), title="Stored input", source_type="file_upload"))
        session.flush()
        session.add(DocumentVersion(id=version, project_id=project, document_id=document,
            version_major=1, extraction_revision=0, version_label="v1.0", status="submission_ready", lock_version=1,
            # Deliberately obsolete generation exercises the real worker refusal
            # before any external adapter/Provider can run.
            chunk_strategy={"chunk_artifacts": {"revision": 1, "project_generation": 999, "status": "queued"}}))
        session.commit()
    # Outer stack owns/discards this entire new database after evidence capture.
    return project, document, version


def bounded(session):
    session.execute(text("SET LOCAL lock_timeout='3s'"))
    session.execute(text("SET LOCAL statement_timeout='8s'"))
    session.execute(text("SET LOCAL deadlock_timeout='100ms'"))


@pytest.mark.parametrize("operation", ["edit_enqueue", "reconcile"])
def test_parent_governance_lock_never_waits_on_a_child_held_by_waiting_writer(database, candidate, operation):
    project_id, _, version_id = candidate
    worker_pid = []
    failures = []

    def competing_writer():
        with Session(database) as session:
            bounded(session)
            worker_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            try:
                version = session.get(DocumentVersion, version_id)
                if operation == "edit_enqueue":
                    _ensure_manual_edit_allowed(session, version, 1)
                    version.lock_version += 1
                    queue_chunk_artifact_reconciliation(session, version, actor_user_id=None)
                    session.commit()
                else:
                    execute_chunk_artifact_reconciliation(session, version_id, Settings(_env_file=None, app_env="test"))
            except DBAPIError as exc:
                failures.append(getattr(exc.orig, "pgcode", None) or getattr(exc.orig, "sqlstate", None))
                session.rollback()

    with Session(database) as governance, ThreadPoolExecutor(max_workers=1) as pool:
        bounded(governance)
        project = governance.scalar(select(Project).where(Project.id == project_id).with_for_update())
        version = governance.get(DocumentVersion, version_id)
        owner_pid = governance.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(competing_writer)
        try:
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline:
                if worker_pid:
                    with database.connect() as observer:
                        waiting = owner_pid in observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": worker_pid[0]})
                    if waiting: break
                if future.done(): break
                time.sleep(0.01)
            assert waiting, "The actual writer must wait for this project's governance lock"
            # This actual production helper acquires Project -> Document -> Version.
            # A waiting writer must not already own Version and form a lock cycle.
            try:
                _ensure_tag_mutable(governance, project, version, "knowledge.chunk_tag.add")
            except DBAPIError as exc:
                failures.append(getattr(exc.orig, "pgcode", None) or getattr(exc.orig, "sqlstate", None))
        finally:
            governance.rollback()
        future.result(timeout=10)
    assert failures == [], f"Inverse parent/version locks caused actual PostgreSQL errors: {failures}"


@pytest.mark.parametrize("change,code", [("archive", "project_archived"), ("delete_document", "document_version_not_found"),
    ("review", "document_version_review_locked"), ("revision", "stale_document_version")])
def test_cached_scope_is_revalidated_before_candidate_mutation(database, candidate, change, code):
    project_id, document_id, version_id = candidate
    with Session(database) as writer:
        project = writer.get(Project, project_id)
        document = writer.get(Document, document_id)
        version = writer.get(DocumentVersion, version_id)
        assert project.status == "active" and not document.is_deleted
        with Session(database) as governance:
            if change == "archive":
                actor = User(id=uuid4(), keycloak_user_id=str(uuid4()), display_name="Stored actor")
                governance.add(actor); governance.flush()
                target = governance.get(Project, project_id)
                target.status, target.archived_at, target.archived_by = "archived", datetime.now(UTC), actor.id
            elif change == "delete_document":
                governance.get(Document, document_id).is_deleted = True
            elif change == "review":
                governance.get(DocumentVersion, version_id).status = "pending_manager_review"
            else:
                governance.get(DocumentVersion, version_id).lock_version += 1
            governance.commit()
        with pytest.raises(AppError) as denied:
            _ensure_manual_edit_allowed(writer, version, 1)
        assert denied.value.code == code
        writer.rollback()
        assert writer.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_id == version_id)) is None


def test_deleted_document_worker_refuses_before_external_artifacts(database, candidate):
    _, document_id, version_id = candidate
    with Session(database) as worker:
        document = worker.get(Document, document_id)
        assert not document.is_deleted
        with Session(database) as governance:
            governance.get(Document, document_id).is_deleted = True
            governance.commit()
        execute_chunk_artifact_reconciliation(worker, version_id, Settings(_env_file=None, app_env="test"))
        metadata = worker.get(DocumentVersion, version_id).chunk_strategy["chunk_artifacts"]
        assert metadata["status"] == "failed" and metadata["error_code"] == "chunk_artifact_scope_missing"


def test_staging_reader_parent_fk_commit_does_not_deadlock_waiting_edit(database, candidate):
    from app.api.routes.serving import _resolve_document_staging_scope
    project_id, document_id, version_id = candidate
    actor = uuid4()
    with Session(database) as setup:
        setup.add(User(id=actor, keycloak_user_id=str(actor), display_name="Stored actor"))
        setup.add(Chunk(id=uuid4(), project_id=project_id, document_id=document_id, document_version_id=version_id,
            chunk_index=1, content="Stored legacy candidate used only for FK/lock behavior", content_hash="input", status="active"))
        # Existing legacy candidate state: no completed build/vector is fabricated
        # and no model or generation result is asserted by this storage-only test.
        setup.get(DocumentVersion, version_id).chunk_strategy = {}
        setup.commit()
    worker_pid = []
    def writer():
        with Session(database) as session:
            bounded(session)
            worker_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            version = session.get(DocumentVersion, version_id)
            _ensure_manual_edit_allowed(session, version, 1)
            version.lock_version += 1
            queue_chunk_artifact_reconciliation(session, version, actor_user_id=actor)
            session.commit()
    with Session(database) as reader, ThreadPoolExecutor(max_workers=1) as pool:
        bounded(reader)
        assert _resolve_document_staging_scope(reader, project_id, [version_id]) == {version_id}
        reader_pid = reader.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(writer)
        try:
            waiting = False
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if worker_pid:
                    with database.connect() as observer:
                        waiting = reader_pid in observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": worker_pid[0]})
                    if waiting: break
                time.sleep(0.01)
            assert waiting
            # Exercise actual parent FKs at the same commit boundary, not a fake LLM.
            chat = ChatRecord(id=uuid4(), project_id=project_id, document_version_id=version_id,
                conversation_id=uuid4(), scope_mode="document_staging", selected_document_version_ids=[str(version_id)],
                question="Storage input", answer="Stored evidence, not generated", created_by=actor,
                asked_at=datetime.now(UTC), created_at=datetime.now(UTC))
            reader.add(chat); reader.flush(); chat_id = chat.id; reader.commit()
        finally:
            reader.rollback()
        future.result(timeout=10)
    with Session(database) as check:
        assert check.get(ChatRecord, chat_id) is not None
        assert check.get(DocumentVersion, version_id).lock_version == 2
