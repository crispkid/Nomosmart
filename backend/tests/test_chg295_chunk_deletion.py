"""Real PostgreSQL/OIDC deletion tests; stored inputs are not model execution.

Uses the existing disposable fixtures, never authentication overrides or current
MAAS data. No test here calls an Embedding/OCR/Chat Provider.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
import time
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    AIModel, AIModelUsageEvent, ApprovalRequest, AuditLog, ChatFeedbackEvent,
    ChatRecord, Chunk, ChunkTag, DocumentVersion, DocumentVersionTag,
    EmbeddingBuild, EmbeddingBuildVector, EmbeddingProfile, OutboxEvent,
    Project, Tag, ValidationRun, ValidationRunItem,
)
from test_chg293_project_content_and_chat_history import (
    authenticated, candidate_markdown, content_fingerprints, live_engine, scoped_data,
)


def _delete(case, actor="editor", chunk_id=None, lock=None):
    client, _, headers, _, _, _, version, _ = case["scope"]
    target = chunk_id or case["chunk"].id
    return client.delete(case["base"] + f"/chunks/{target}", headers=headers[actor],
        params={"lock_version": lock if lock is not None else version.lock_version})


def _other_chunk(case, *, version=None, index=2, status="active"):
    _, _, _, session, project, document, current, _ = case["scope"]
    row = Chunk(project_id=project.id, document_id=document.id,
        document_version_id=(version or current).id, chunk_index=index,
        content="Separate retained content", markdown_content="Separate **retained** content",
        content_hash=uuid4().hex, status=status)
    session.add(row); session.flush()
    return row


def _other_version(case):
    _, _, _, session, project, document, _, _ = case["scope"]
    row = DocumentVersion(project_id=project.id, document_id=document.id,
        version_major=2, extraction_revision=0, version_label="v2.0", status="submission_ready")
    session.add(row); session.flush()
    return row


def _stored_evidence(case):
    _, users, _, session, project, document, version, chats = case["scope"]
    target = case["chunk"]
    now = datetime.now(UTC)
    chat = chats["editor"]
    chat.reference_docs = [{"chunk_id": str(target.id), "document_id": str(document.id),
                            "document_version_id": str(version.id)}]
    model = AIModel(name="CHG295 stored ledger " + uuid4().hex, model_type="Chat",
        provider="stored-accounting-input", is_active=False)
    session.add(model); session.flush()
    run = ValidationRun(project_id=project.id, document_version_id=version.id,
        selected_document_ids=[str(version.id)], run_scope="document_staging", status="completed",
        created_by=users["owner"].id, total_count=2, completed_count=1, failed_count=1, created_at=now)
    session.add(run); session.flush()
    item = ValidationRunItem(run_id=run.id, question="Stored prior test input",
        selected_document_ids=[str(version.id)], reference_docs=chat.reference_docs,
        chat_record_id=chat.id, status="failed", is_current=False, created_at=now)
    session.add(item); session.flush()
    retained = ValidationRunItem(run_id=run.id, question="Unrelated retained test input",
        selected_document_ids=[str(version.id)], reference_docs=[], status="passed",
        parent_item_id=item.id, is_current=True, created_at=now,
        input_item_id=item.input_item_id, input_ordinal=item.input_ordinal,
        input_content_hash=item.input_content_hash, attempt=item.attempt + 1)
    session.add(retained); session.flush()
    usage = AIModelUsageEvent(model_id=model.id, model_type="Chat", provider=model.provider,
        project_id=project.id, document_id=document.id, document_version_id=version.id,
        chat_record_id=chat.id, validation_run_id=run.id, validation_run_item_id=item.id,
        source_channel="validation", usage_purpose="validation_answer", status="failed",
        attempted=True, input_tokens=100, output_tokens=12, total_tokens=112,
        estimated_cost=Decimal("0.00001234"), cost_currency="USD", cost_source="estimated", created_at=now)
    feedback = ChatFeedbackEvent(project_id=project.id, chat_record_id=chat.id, source="ui",
        feedback_value="incorrect", actor_user_id=users["editor"].id, created_at=now)
    session.add_all([usage, feedback]); session.commit()
    return chat, run, item, retained, usage, feedback


@pytest.mark.parametrize("actor", ["owner", "editor"])
def test_exact_deletion_retains_shared_tags_raw_other_versions(candidate_markdown, actor):
    case = candidate_markdown
    _, users, _, session, project, _, version, _ = case["scope"]
    target = case["chunk"]
    target_id = target.id
    other = _other_chunk(case)
    unrelated = _other_chunk(case, version=_other_version(case), index=1)
    tags = [Tag(project_id=project.id, name="CHG295 " + uuid4().hex, created_at=datetime.now(UTC)) for _ in range(4)]
    session.add_all(tags); session.flush()
    for tag in tags:
        session.add(ChunkTag(chunk_id=target.id, tag_id=tag.id, source="manual", created_by=users[actor].id, created_at=datetime.now(UTC)))
    for chunk, tag in ((other, tags[1]), (unrelated, tags[2])):
        session.add(ChunkTag(chunk_id=chunk.id, tag_id=tag.id, source="manual", created_at=datetime.now(UTC)))
    session.add(DocumentVersionTag(document_version_id=version.id, tag_id=tags[3].id, source="manual", created_at=datetime.now(UTC)))
    session.commit()
    orphan_id = tags[0].id
    other_snapshot = (unrelated.content, unrelated.chunk_index, unrelated.content_hash)
    lock = version.lock_version
    response = _delete(case, actor)
    assert response.status_code == 200, response.text
    assert response.json()["active_chunk_count"] == 1
    assert response.json()["chunk_artifact_status"] == "queued"
    assert response.json()["next_stage_allowed"] is False
    session.expire_all()
    assert session.get(Chunk, target_id) is None
    assert session.get(Tag, orphan_id) is None
    assert all(session.get(Tag, tag.id) is not None for tag in tags[1:])
    assert (unrelated.content, unrelated.chunk_index, unrelated.content_hash) == other_snapshot
    assert other.chunk_index == 1 and version.lock_version == lock + 1
    assert case["step"].artifact_payload == {"markdown": case["raw"]}
    assert session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == version.id)) is not None
    assert _delete(case, actor, target_id, lock).status_code == 404


def test_ledger_and_retry_history_survive_scoped_evidence_deletion(candidate_markdown):
    case = candidate_markdown
    _, _, _, session, _, _, version, others = case["scope"]
    target_id = case["chunk"].id
    chat, run, item, retained, usage, feedback = _stored_evidence(case)
    ids = [chat.id, item.id, usage.id, feedback.id]
    columns = [column.key for column in inspect(AIModelUsageEvent).columns
               if column.key not in {"chat_record_id", "validation_run_item_id", "metadata"}]
    before = {key: getattr(usage, key) for key in columns}
    count = session.scalar(text("SELECT count(*) FROM ai_model_usage_events"))
    response = _delete(case)
    assert response.status_code == 200, response.text
    assert response.json()["active_chunk_count"] == 0
    assert response.json()["chunk_artifact_status"] == "chunks_required"
    session.expire_all()
    assert session.get(Chunk, target_id) is None
    assert session.get(ChatRecord, ids[0]) is None
    assert session.get(ValidationRunItem, ids[1]) is None
    assert session.get(ChatFeedbackEvent, ids[3]) is None
    assert session.scalar(text("SELECT count(*) FROM ai_model_usage_events")) == count
    assert {key: getattr(usage, key) for key in columns} == before
    assert usage.chat_record_id is None and usage.validation_run_item_id is None
    assert usage.validation_run_id == run.id
    assert retained.parent_item_id is None and retained.status == "passed"
    assert (run.total_count, run.completed_count, run.failed_count) == (1, 1, 0)
    assert others["owner"].deleted_at is None and others["viewer"].deleted_at is None
    audits = list(session.scalars(select(AuditLog).where(AuditLog.action == "knowledge.chunk.reference.detach")))
    relevant = [row for row in audits if row.summary.get("deleted_chunk_id") == str(target_id)]
    assert {(row.resource_id, row.summary["field"], row.summary["target_id"]) for row in relevant} == {
        (ids[2], "chat_record_id", str(ids[0])), (ids[2], "validation_run_item_id", str(ids[1])),
        (retained.id, "parent_item_id", str(ids[1]))}
    assert case["raw"] not in json.dumps([row.summary for row in relevant])
    assert version.lock_version == 2


@pytest.mark.parametrize("kind", ["lineage", "chat", "chat_scope", "citations", "usage", "retry", "submitted", "unknown_fk"])
def test_protected_or_unprovable_reference_is_atomic_conflict(candidate_markdown, kind):
    case = candidate_markdown
    _, users, _, session, project, document, version, rows = case["scope"]
    chunk = case["chunk"]
    cleanup = None
    if kind == "lineage":
        _other_chunk(case, version=_other_version(case), index=1).parent_chunk_id = chunk.id
    elif kind in {"chat", "chat_scope", "citations"}:
        row = rows["editor"]
        row.reference_docs = [{"chunk_id": str(chunk.id)}]
        if kind == "chat":
            row.document_version_id = _other_version(case).id
        elif kind == "chat_scope":
            row.scope_mode = "published"
        else:
            row.reference_docs = [{"chunk_id": str(chunk.id), "document_version_id": str(uuid4())}]
    elif kind in {"usage", "retry"}:
        _, _, item, retained, usage, _ = _stored_evidence(case)
        other = _other_version(case)
        if kind == "usage":
            usage.document_version_id = other.id
        else:
            run = ValidationRun(project_id=project.id, document_version_id=other.id,
                selected_document_ids=[str(other.id)], run_scope="document_staging", status="completed",
                created_by=users["owner"].id, created_at=datetime.now(UTC))
            session.add(run); session.flush()
            retained.run_id = run.id
            retained.parent_item_id = item.id
    elif kind == "submitted":
        session.add(ApprovalRequest(project_id=project.id, document_id=document.id,
            document_version_id=version.id, submitter_id=users["editor"].id, status="cancelled",
            submitted_at=datetime.now(UTC), created_at=datetime.now(UTC)))
    else:
        # Only this module's random disposable schema; unknown cascades must deny.
        session.execute(text("CREATE TABLE chg295_unhandled_reference (id uuid PRIMARY KEY, chunk_id uuid REFERENCES chunks(id) ON DELETE CASCADE)"))
        session.execute(text("INSERT INTO chg295_unhandled_reference VALUES (:id, :chunk)"), {"id": uuid4(), "chunk": chunk.id})
        cleanup = "DROP TABLE chg295_unhandled_reference"
    session.commit()
    before = content_fingerprints(session)
    try:
        response = _delete(case)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "chunk_delete_reference_conflict"
        assert str(chunk.id) not in response.text and document.title not in response.text
        session.expire_all()
        assert content_fingerprints(session) == before
    finally:
        if cleanup:
            session.execute(text(cleanup)); session.commit()


@pytest.mark.parametrize("actor", ["viewer", "outsider"])
def test_unauthorized_delete_cannot_touch_data(candidate_markdown, actor):
    session = candidate_markdown["scope"][3]
    before = content_fingerprints(session)
    response = _delete(candidate_markdown, actor)
    assert response.status_code in {403, 404}, response.text
    assert content_fingerprints(session) == before


def test_real_constraint_failure_rolls_back_every_mutation(candidate_markdown):
    case = candidate_markdown
    _, _, _, session, _, _, _, _ = case["scope"]
    target_id = case["chunk"].id
    _stored_evidence(case)
    # Real DB constraint scoped to this exact test Chunk, not a fake Session.
    session.execute(text("ALTER TABLE audit_logs ADD CONSTRAINT chg295_reject_audit CHECK "
        f"(NOT (action = 'knowledge.chunk.delete' AND resource_id = '{target_id}'::uuid))"))
    session.commit()
    before = content_fingerprints(session)
    try:
        with pytest.raises(IntegrityError):
            _delete(case)
        session.expire_all()
        assert content_fingerprints(session) == before
        assert session.get(Chunk, target_id) is not None
    finally:
        session.execute(text("ALTER TABLE audit_logs DROP CONSTRAINT chg295_reject_audit")); session.commit()


def test_two_actual_delete_requests_commit_only_once(candidate_markdown):
    case = candidate_markdown
    _, _, _, session, _, _, version, _ = case["scope"]
    target_id, lock = case["chunk"].id, version.lock_version
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_delete, case, "editor", target_id, lock) for _ in range(2)]
        responses = [future.result(timeout=20) for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 404]
    session.expire_all()
    assert version.lock_version == lock + 1
    assert session.get(Chunk, target_id) is None
    assert len(list(session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == version.id)))) == 1


@pytest.mark.parametrize("foreign_build", [False, True])
def test_vector_storage_deletion_is_build_scoped(candidate_markdown, foreign_build):
    case = candidate_markdown
    _, _, _, session, project, document, version, _ = case["scope"]
    other = _other_chunk(case)
    model = AIModel(name=uuid4().hex, model_type="Embedding", provider="stored-vector-input", is_active=False)
    session.add(model); session.flush()
    profile = EmbeddingProfile(model_id=model.id, model_version="storage-test", vector_dimension=2,
        distance_method="cosine", chunk_strategy={}, mapping_version=1)
    session.add(profile); session.flush()
    build = EmbeddingBuild(project_id=project.id, document_id=document.id,
        document_version_id=(_other_version(case) if foreign_build else version).id,
        embedding_profile_id=profile.id, status="failed", chunk_count=2)
    session.add(build); session.flush()
    vectors = [EmbeddingBuildVector(embedding_build_id=build.id, chunk_id=chunk.id,
        chunk_index=i, vector=[0.2, 0.3], vector_checksum="0" * 64, token_count=1,
        created_at=datetime.now(UTC)) for i, chunk in enumerate([case["chunk"], other], 1)]
    session.add_all(vectors); session.commit()
    ids = [row.id for row in vectors]
    before = content_fingerprints(session)
    response = _delete(case)
    session.expire_all()
    if foreign_build:
        assert response.status_code == 409 and response.json()["code"] == "chunk_delete_reference_conflict"
        assert content_fingerprints(session) == before
    else:
        assert response.status_code == 200, response.text
        assert session.get(EmbeddingBuildVector, ids[0]) is None
        assert session.get(EmbeddingBuildVector, ids[1]).vector == [0.2, 0.3]
        assert session.get(EmbeddingBuild, build.id).status == "failed"


def test_staging_evidence_shared_fence_prevents_late_citations(candidate_markdown, live_engine):
    from app.api.routes.serving import _resolve_document_staging_scope
    case = candidate_markdown
    _, users, _, session, project, _, version, _ = case["scope"]
    project_id, version_id, target_id, actor_id = project.id, version.id, case["chunk"].id, users["editor"].id
    lock = version.lock_version
    session.commit()
    with Session(live_engine) as reader, ThreadPoolExecutor(max_workers=1) as pool:
        assert _resolve_document_staging_scope(reader, project_id, [version_id]) == {version_id}
        pending = pool.submit(_delete, case, "editor", target_id, lock)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                waiting = session.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted AND pid IN "
                    "(SELECT pid FROM pg_stat_activity WHERE datname=current_database())"))
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting and not pending.done(), "DELETE must wait for the real staging read transaction"
            # Persist stored evidence at the same boundary as generation; no Provider is simulated.
            chat = ChatRecord(project_id=project_id, document_version_id=version_id, scope_mode="document_staging", conversation_id=uuid4(),
                selected_document_version_ids=[str(version_id)], question="Stored concurrent evidence",
                answer="Storage-only input", reference_docs=[{"chunk_id": str(target_id)}],
                created_by=actor_id, created_at=datetime.now(UTC), asked_at=datetime.now(UTC))
            reader.add(chat); reader.flush(); chat_id = chat.id
            reader.commit()
        finally:
            reader.rollback()  # release the shared fence even when the assertion fails
        response = pending.result(timeout=15)
    assert response.status_code == 200, response.text
    session.expire_all()
    assert session.get(ChatRecord, chat_id) is None
    assert session.get(Chunk, target_id) is None


def test_authenticated_delete_obeys_parent_governance_lock_order(candidate_markdown, live_engine):
    from app.api.routes.documents import _ensure_tag_mutable
    case = candidate_markdown
    _, _, _, session, project, _, version, _ = case["scope"]
    project_id, version_id, chunk_id, lock = project.id, version.id, case["chunk"].id, version.lock_version
    session.commit()
    with Session(live_engine) as governance, ThreadPoolExecutor(max_workers=1) as pool:
        governance.execute(text("SET LOCAL lock_timeout='3s'"))
        governance.execute(text("SET LOCAL deadlock_timeout='100ms'"))
        project = governance.scalar(select(Project).where(Project.id == project_id).with_for_update())
        version = governance.get(DocumentVersion, version_id)
        pid = governance.scalar(text("SELECT pg_backend_pid()"))
        pending = pool.submit(_delete, case, "editor", chunk_id, lock)
        try:
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline:
                with live_engine.connect() as observer:
                    waiting = bool(observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))"), {"pid": pid}))
                if waiting or pending.done(): break
                time.sleep(0.01)
            assert waiting and not pending.done()
            # Must succeed while DELETE is waiting on this transaction's parent.
            _ensure_tag_mutable(governance, project, version, "knowledge.chunk_tag.add")
        finally:
            governance.rollback()
        response = pending.result(timeout=15)
    assert response.status_code == 200, response.text
    session.expire_all()
    assert session.get(Chunk, chunk_id) is None


@pytest.fixture
def graph_cleanup_scope(candidate_markdown):
    from app.core.config import Settings
    from app.domain.graph_projection import build_graph_projection
    from app.domain.graph_reconciliation import Neo4jProjectionStore
    from app.domain.extraction_pipeline import LiveOpenSearchStagingIndexAdapter, staging_index_name
    case = candidate_markdown
    _, _, _, session, project, document, version, _ = case["scope"]
    assert os.environ.get("CHG295_DATABASE_URL") and os.environ.get("NEO4J_URI")
    settings = Settings(_env_file=None, app_env="test", neo4j_username="", neo4j_password="",
        opensearch_username="", opensearch_password="", opensearch_staging_live_write=True,
        opensearch_index_prefix="chg295-" + uuid4().hex)
    store = Neo4jProjectionStore(settings)
    tag = Tag(project_id=project.id, name=uuid4().hex, created_at=datetime.now(UTC))
    session.add(tag); session.flush()
    session.add(ChunkTag(chunk_id=case["chunk"].id, tag_id=tag.id, source="manual", created_at=datetime.now(UTC)))
    session.commit()
    projection = build_graph_projection(session, project, document, version)
    # Stored canonical graph tests cleanup, not an ingestion/publish result.
    store.reconcile(projection)
    node_ids = [node["id"] for node in projection.graph["nodes"]]
    index = staging_index_name(settings.opensearch_index_prefix, project.id, version.id)
    other_index = settings.opensearch_index_prefix + "-unrelated"
    staging = LiveOpenSearchStagingIndexAdapter(settings)
    for name in (index, other_index):
        staging._request("PUT", settings.opensearch_url.rstrip("/") + "/" + name,
            b'{}', context=settings.opensearch_ssl_context, content_type="application/json")
    case.update(settings=settings, graph=store, tag_id=str(tag.id), graph_ids=node_ids,
                index=index, other_index=other_index, staging=staging)
    try:
        yield case
    finally:
        with store.connection() as graph:
            graph.run("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=case["graph_ids"]).consume()
        for name in (index, other_index):
            staging._request("DELETE", settings.opensearch_url.rstrip("/") + "/" + name,
                b"", context=settings.opensearch_ssl_context, content_type="application/json", allow_missing=True)


@pytest.mark.parametrize("unknown_edge", [False, True])
def test_zero_chunk_actual_graph_search_cleanup_retry_and_isolation(graph_cleanup_scope, unknown_edge):
    from app.core.errors import AppError
    from app.domain.chunk_artifacts import execute_chunk_artifact_reconciliation
    case = graph_cleanup_scope
    _, _, _, session, project, _, version, _ = case["scope"]
    target_id, version_id, project_id = str(case["chunk"].id), version.id, str(project.id)
    usage_count = session.scalar(text("SELECT count(*) FROM ai_model_usage_events"))
    if unknown_edge:
        with case["graph"].connection() as graph:
            graph.run("MATCH (c:Chunk {id:$id}) CREATE (x:Unmanaged {id:$other}) CREATE (c)-[:UNKNOWN]->(x)",
                id=target_id, other="unmanaged-" + target_id).consume()
        case["graph_ids"].append("unmanaged-" + target_id)
    assert _delete(case).status_code == 200
    session.expire_all()
    if unknown_edge:
        with pytest.raises(AppError) as failure:
            execute_chunk_artifact_reconciliation(session, version_id, case["settings"])
        assert failure.value.code == "graph_identity_conflict"
        assert version.chunk_strategy["chunk_artifacts"]["status"] == "failed"
        with case["graph"].connection() as graph:
            assert graph.run("MATCH (c:Chunk {id:$id}) RETURN count(c) AS n", id=target_id).single()["n"] == 1
            graph.run("MATCH (:Chunk {id:$id})-[r:UNKNOWN]->() DELETE r", id=target_id).consume()
    execute_chunk_artifact_reconciliation(session, version_id, case["settings"])
    execute_chunk_artifact_reconciliation(session, version_id, case["settings"])  # idempotent retry
    session.refresh(version)
    assert version.chunk_strategy["chunk_artifacts"]["status"] == "chunks_required"
    assert version.chunk_strategy["chunk_artifacts"]["reconciled_at"]
    assert not [node for node in version.chunk_strategy["graph_preview"]["nodes"] if node["type"] == "chunk"]
    assert session.scalar(text("SELECT count(*) FROM ai_model_usage_events")) == usage_count
    with case["graph"].connection() as graph:
        assert graph.run("MATCH (c:Chunk {id:$id}) RETURN count(c) AS n", id=target_id).single()["n"] == 0
        assert graph.run("MATCH (p:Project {id:$id}) RETURN count(p) AS n", id=project_id).single()["n"] == 1
        assert graph.run("MATCH (t:Tag {id:$id}) RETURN count(t) AS n", id=case["tag_id"]).single()["n"] == 1
    # Actual HTTP read-back, not the local receipt alone.
    import urllib.error
    import urllib.request
    base = case["settings"].opensearch_url.rstrip("/")
    with pytest.raises(urllib.error.HTTPError) as gone:
        urllib.request.urlopen(base + "/" + case["index"], timeout=5)
    assert gone.value.code == 404
    with urllib.request.urlopen(base + "/" + case["other_index"], timeout=5) as retained:
        assert retained.status == 200
