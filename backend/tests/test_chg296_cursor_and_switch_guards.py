"""CHG-296 real SQL/OIDC/OpenSearch guard and response tests, no Provider.

The stored build/vector inputs below are deliberately controlled validation
inputs, NOT evidence of generation, publication or a successful active switch.
Every switch invocation in this file must fail before any serving mutation.
Run only in the fresh disposable stack required by CHG-296's approved plan.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
import socket
import time
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text

if os.environ.get("CHG296_ISOLATED") != "1":
    raise RuntimeError("BLOCKED: initialize a fresh CHG-296 isolated environment before test collection")

from test_live_backend_api_behavior import live_client, _canonical_chunk_input
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import (AIModel, ActiveVersionManifest, Chunk, Document, DocumentVersion,
    ChatRecord, EmbeddingBuild, EmbeddingBuildVector, EmbeddingProfile, Notification, Project, ProjectMember, ProjectOwner,
    ValidationRun, ValidationRunItem, IdentitySyncRun, IntegrationClient)
from app.db.session import get_session_factory
from app.domain.embeddings import _content_fingerprint, load_published_embeddings
from app.domain.retrieval_text import embedding_content_hash
from app.domain.review_publish import (LiveOpenSearchPublishedAdapter, _vector_index_mapping,
    switch_active_version)
from app.domain.search import vector_document_id


@pytest.fixture(autouse=True)
def isolated_only():
    assert os.environ.get("CHG296_ISOLATED") == "1", "BLOCKED: fresh CHG-296 stack required"
    assert "127.0.0.1" in get_settings().database_url.get_secret_value()


def page(client, headers, path, **params):
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload["has_more"], bool)
    assert payload["has_more"] == bool(payload["next_cursor"])
    assert isinstance(payload["items"], list)
    return payload


@pytest.mark.parametrize("count,limit", [(0, 2), (1, 2), (2, 2), (3, 2), (5, 1)])
def test_authenticated_notification_boundaries_and_traversal(live_client, count, limit):
    client, headers, user_id, _ = live_client
    kind = f"chg296-{uuid4().hex}"
    now = datetime.now(UTC)
    ids = []
    with get_session_factory().begin() as session:
        for index in range(count):
            row = Notification(id=uuid4(), recipient_user_id=UUID(user_id), notification_type=kind,
                severity="info", title="Stored paging input", message="Metadata only", is_read=False,
                created_at=now - timedelta(seconds=index))
            ids.append(str(row.id)); session.add(row)
    params = {"notification_type": kind, "limit": limit}
    first = result = page(client, headers, "/api/v1/notifications", **params)
    assert first["has_more"] == (count > limit)
    seen = [item["id"] for item in result["items"]]
    while result["has_more"]:
        result = page(client, headers, "/api/v1/notifications", **params, cursor=result["next_cursor"])
        seen.extend(item["id"] for item in result["items"])
    assert seen == ids
    if first["has_more"]:
        cursor = first["next_cursor"]
        assert client.get("/api/v1/notifications", headers=headers, params={**params, "cursor": "!" + cursor[1:]}).json()["code"] == "cursor_invalid"
        assert client.get("/api/v1/notifications", headers=headers, params={**params, "is_read": True, "cursor": cursor}).json()["code"] == "cursor_scope_mismatch"
        # A newly inserted row sorts ahead of the saved boundary, not into later pages.
        with get_session_factory().begin() as session:
            session.add(Notification(id=uuid4(), recipient_user_id=UUID(user_id), notification_type=kind,
                severity="info", title="New stored input", message="Not a snapshot promise", is_read=False,
                created_at=now + timedelta(seconds=1)))
        again = page(client, headers, "/api/v1/notifications", **params, cursor=cursor)
        assert [item["id"] for item in again["items"]] == ids[limit:limit * 2]


def test_all_cursor_openapi_contracts_and_existing_empty_endpoints(live_client):
    client, headers, _, _ = live_client
    schema = client.app.openapi()["components"]["schemas"]
    names = ["ApprovalTaskPage", "ApprovalRequestPage", "ProjectChatConversationPage", "IntegrationClientPage",
        "ValidationRunPage", "ValidationRunItemPage", "NotificationPage", "IdentitySyncRunPage",
        "PipelineRunPage", "GraphSyncJobPage", "AuditLogPage"]
    for name in names:
        assert schema[name]["properties"]["has_more"]["type"] == "boolean"
        assert "has_more" in schema[name]["required"]
        assert {"items", "next_cursor"} <= schema[name]["properties"].keys()
    for path in ("/api/v1/notifications", "/api/v1/identity-sync/runs", "/api/v1/pipeline-runs", "/api/v1/graph-sync-jobs",
                 "/api/v1/audit-logs", "/api/v1/approvals/pending", "/api/v1/approvals/history",
                 "/api/v1/approvals/my-submissions", "/api/v1/validation-runs", "/api/v1/integration-clients"):
        page(client, headers, path, limit=1)


@pytest.fixture
def stored_target(live_client):
    """Real stored rows for invalid-evidence testing; never a published workflow."""
    _, _, actor, _ = live_client
    now = datetime.now(UTC)
    with get_session_factory().begin() as session:
        model = AIModel(name=f"chg296-{uuid4()}", model_type="Embedding", provider="custom",
            endpoint="http://127.0.0.1:1/never-called", config={"model_name": "guard-input"}, config_version=1, is_active=True)
        session.add(model); session.flush()
        profile = EmbeddingProfile(model_id=model.id, model_version="guard-input", vector_dimension=3,
            distance_method="cosine", chunk_strategy={}, mapping_version=2)
        session.add(profile); session.flush()
        project = Project(name=f"chg296-{uuid4()}", status="active", embedding_model_id=model.id)
        session.add(project); session.flush()
        session.add(ProjectOwner(project_id=project.id, user_id=UUID(actor), created_at=now))
        session.add(ProjectMember(project_id=project.id, user_id=UUID(actor), project_role="owner", created_at=now))
        document = Document(project_id=project.id, document_code=str(uuid4()), title="Stored guard input",
            source_type="upload", status="active")
        session.add(document); session.flush()
        versions = [DocumentVersion(project_id=project.id, document_id=document.id, version_major=n,
            extraction_revision=0, version_label=f"v{n}.0", status="active" if n == 1 else "inactive",
            embedding_model_id=model.id, embedding_profile_id=profile.id, published_at=now, lock_version=1)
            for n in (1, 2)]
        session.add_all(versions); session.flush()
        current, target = versions
        chunk = Chunk(project_id=project.id, document_id=document.id, document_version_id=target.id,
            chunk_index=1, markdown_content="## Guard\n\nRead the original business wording.",
            content="Stored input", content_hash="initial", status="active", embedding_model_id=model.id)
        _canonical_chunk_input(chunk, document)
        strategy = chunk.chunk_strategy
        chunk.embedding_content_hash = embedding_content_hash(retrieval_text=chunk.retrieval_text,
            embedding_model=str(model.id), embedding_model_version=profile.model_version, embedding_dimension=3,
            normalizer_version=strategy["normalizer_version"], tokenizer_version=strategy["tokenizer_version"])
        session.add(chunk); session.flush()
        index = f"chg296-guard-{uuid4().hex}"
        old = EmbeddingBuild(project_id=project.id, document_id=document.id, document_version_id=current.id,
            embedding_profile_id=profile.id, build_revision=1, status="published", chunk_count=0)
        build = EmbeddingBuild(project_id=project.id, document_id=document.id, document_version_id=target.id,
            embedding_profile_id=profile.id, build_revision=1, status="published", chunk_count=1,
            model_id=model.id, vector_dimension=3, index_name=index,
            content_fingerprint=_content_fingerprint(model, [chunk], [chunk.retrieval_text]))
        session.add_all([old, build]); session.flush()
        # Numeric database input only; all switch attempts below are required to
        # FAIL. This row is never counted as successful embedding/publication.
        vector = [0.125, 0.25, 0.5]
        row = EmbeddingBuildVector(embedding_build_id=build.id, chunk_id=chunk.id, chunk_index=1, vector=vector,
            vector_checksum=hashlib.sha256(json.dumps(vector, separators=(",", ":")).encode()).hexdigest(),
            token_count=chunk.token_count, created_at=now)
        session.add(row)
        session.add(ActiveVersionManifest(project_id=project.id, document_id=document.id, document_version_id=current.id,
            embedding_profile_id=profile.id, embedding_build_id=old.id, publication_generation=1, index_ready=True))
        session.flush()
        return dict(actor=UUID(actor), project=project.id, document=document.id, target=target.id,
            chunk=chunk.id, build=build.id, vector=row.id, index=index)


def snapshot(session):
    # Exact row snapshots, not counts: failure must preserve values too.
    tables = ("documents", "document_versions", "active_version_manifests", "graph_sync_jobs", "outbox_events",
              "notifications", "notification_events", "audit_logs", "ai_model_usage_events",
              "embedding_builds", "embedding_build_vectors", "chunks")
    return {table: session.execute(text(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.id), '[]') FROM {table} t")).scalar()
            for table in tables}


def switch(session, data, **overrides):
    args = dict(session=session, actor_user_id=data["actor"], document=session.get(Document, data["document"]),
        version=session.get(DocumentVersion, data["target"]), lock_version=1, impact_confirmed=True,
        audit_reason="CHG-296 invalid-input guard only", request_id="chg296-guard", settings=get_settings())
    args.update(overrides)
    return switch_active_version(**args)


@pytest.mark.parametrize("defect,code", [
    ("legacy", "retrieval_reprocessing_required"), ("hash", "retrieval_reprocessing_required"),
    ("versions", "retrieval_reprocessing_required"), ("model", "canonical_embedding_build_invalid"),
    ("fingerprint", "canonical_embedding_build_invalid"), ("newer_staged", "canonical_embedding_build_invalid"),
    ("missing_vector", "canonical_embedding_build_invalid"), ("dimension", "canonical_embedding_build_invalid"),
    ("checksum", "canonical_embedding_build_invalid"), ("vector_mapping", "canonical_embedding_build_invalid"),
    ("extra_vector", "canonical_embedding_build_invalid"), ("scope", "canonical_embedding_build_invalid"),
    ("build_count", "canonical_embedding_build_invalid"), ("staged_only", "canonical_embedding_build_required"),
    ("missing_index", "published_index_not_ready"), ("inactive_extra", "published_index_not_ready"),
])
def test_invalid_target_refused_before_any_mutation(stored_target, defect, code):
    data = stored_target
    with get_session_factory()() as session:
        chunk = session.get(Chunk, data["chunk"])
        build = session.get(EmbeddingBuild, data["build"])
        row = session.get(EmbeddingBuildVector, data["vector"])
        if defect == "legacy": chunk.retrieval_text = None
        elif defect == "hash": chunk.embedding_content_hash = "f" * 64
        elif defect == "versions": chunk.chunk_strategy = {}
        elif defect == "model": build.model_id = None
        elif defect in ("fingerprint", "newer_staged"):
            if defect == "newer_staged":
                session.add(EmbeddingBuild(project_id=build.project_id, document_id=build.document_id,
                    document_version_id=build.document_version_id, embedding_profile_id=build.embedding_profile_id,
                    build_revision=2, status="staged", chunk_count=1, model_id=build.model_id,
                    vector_dimension=3, content_fingerprint=build.content_fingerprint))
            build.content_fingerprint = "a" * 64
        elif defect == "missing_vector": session.delete(row)
        elif defect == "dimension": row.vector = [0.5]
        elif defect == "checksum": row.vector_checksum = "b" * 64
        elif defect == "vector_mapping": row.chunk_index = 2
        elif defect in ("extra_vector", "inactive_extra"):
            extra = Chunk(project_id=chunk.project_id, document_id=chunk.document_id,
                document_version_id=chunk.document_version_id, chunk_index=2, content="Historical inactive input",
                content_hash="old", status="inactive")
            session.add(extra); session.flush()
            if defect == "extra_vector":
                session.add(EmbeddingBuildVector(embedding_build_id=build.id, chunk_id=extra.id, chunk_index=2,
                    vector=row.vector, vector_checksum=row.vector_checksum, token_count=1, created_at=datetime.now(UTC)))
        elif defect == "scope":
            foreign = Project(name=f"chg296-foreign-{uuid4()}", status="active")
            session.add(foreign); session.flush(); build.project_id = foreign.id
        elif defect == "build_count": build.chunk_count = 2
        elif defect == "staged_only": build.status = "staged"
        session.flush()
        before = snapshot(session)
        with pytest.raises(AppError) as denied: switch(session, data)
        assert denied.value.code == code
        assert not session.dirty and not session.new and not session.deleted
        assert snapshot(session) == before
        session.rollback()


@pytest.mark.parametrize("defect", ["mapping", "mapping_dimension", "missing", "extra", "wrong_id", "scope", "hash", "text", "vector", "versions", "consistent_storage_read"])
def test_real_opensearch_mismatch_is_read_only_and_atomic(stored_target, defect):
    data = stored_target
    settings = get_settings()
    with get_session_factory()() as session, httpx.Client(base_url=settings.opensearch_url, timeout=10) as http:
        build = session.get(EmbeddingBuild, data["build"])
        chunk = session.get(Chunk, data["chunk"])
        profile = session.get(EmbeddingProfile, build.embedding_profile_id)
        mapping = _vector_index_mapping(profile)
        if defect == "mapping": del mapping["mappings"]["properties"]["retrieval_text"]
        if defect == "mapping_dimension": mapping["mappings"]["properties"]["embedding_vector"]["dimension"] = 2
        assert http.put('/' + data["index"], json=mapping).status_code == 200
        try:
            source = dict(index_scope="published", project_id=str(data["project"]), document_id=str(data["document"]),
                document_version_id=str(data["target"]), chunk_id=str(chunk.id), chunk_index=1,
                embedding_profile_id=str(profile.id), embedding_model_id=str(profile.model_id), vector_dimension=3,
                mapping_version=2, version_status="published", embedding_content_hash=chunk.embedding_content_hash,
                retrieval_text=chunk.retrieval_text, embedding_vector=[0.125, 0.25, 0.5],
                **{key: chunk.chunk_strategy[key] for key in ("parser_version", "chunker_version", "normalizer_version", "tokenizer_version")})
            if defect == "scope": source["document_id"] = str(uuid4())
            if defect == "hash": source["embedding_content_hash"] = "f" * 64
            if defect == "text": source["retrieval_text"] += " changed"
            if defect == "vector": source["embedding_vector"] = [0.5, 0.25, 0.125]
            if defect == "versions": source["parser_version"] = "obsolete"
            doc_id = vector_document_id(profile.id, data["target"], chunk.id)
            if defect not in ("mapping", "mapping_dimension", "missing"):
                key = "wrong" if defect == "wrong_id" else doc_id
                assert http.put(f'/{data["index"]}/_doc/{key}?refresh=true', json=source).status_code == 201
            if defect == "extra":
                assert http.put(f'/{data["index"]}/_doc/extra?refresh=true', json=source).status_code == 201
            # Unrelated version in the shared index is never selected or changed.
            other = {"document_version_id": str(uuid4()), "retrieval_text": "Unrelated stored row"}
            assert http.put(f'/{data["index"]}/_doc/unrelated?refresh=true', json=other).status_code == 201
            before_index = http.get(f'/{data["index"]}/_search?size=20').json()["hits"]
            before = snapshot(session)
            if defect == "consistent_storage_read":
                # Validate read-back in isolation, never claim generation or run
                # a successful switch with manually stored vector inputs.
                batch = load_published_embeddings(session, project=session.get(Project, data["project"]),
                    version=session.get(DocumentVersion, data["target"]), chunks=[chunk], build=build)
                LiveOpenSearchPublishedAdapter(settings).verify_published_build(
                    document=session.get(Document, data["document"]), version=session.get(DocumentVersion, data["target"]),
                    chunks=[chunk], batch=batch)
            else:
                with pytest.raises(AppError) as denied: switch(session, data)
                assert denied.value.code == "published_index_evidence_invalid"
            assert snapshot(session) == before
            assert http.get(f'/{data["index"]}/_search?size=20').json()["hits"] == before_index
        finally:
            # Exact UUID-bound index created above, never a prefix cleanup.
            assert http.delete('/' + data["index"]).status_code == 200


@pytest.mark.parametrize("change,code", [("stale", "stale_document_version"), ("deleted", "document_not_found")])
def test_switch_waits_for_document_then_refreshes_before_child_lock(stored_target, change, code):
    data = stored_target
    worker_pid = []
    factory = get_session_factory()
    def contender():
        with factory() as session:
            # Cache old state before waiting to exercise populate_existing.
            document, version = session.get(Document, data["document"]), session.get(DocumentVersion, data["target"])
            worker_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            session.execute(text("SET LOCAL lock_timeout='6s'"))
            with pytest.raises(AppError) as denied: switch(session, data, document=document, version=version)
            assert denied.value.code == code
            session.rollback()
    with factory() as owner, ThreadPoolExecutor(max_workers=1) as pool:
        owner.execute(text("SET LOCAL lock_timeout='3s'"))
        document = owner.scalar(select(Document).where(Document.id == data["document"]).with_for_update())
        owner_pid = owner.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(contender)
        try:
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline and not future.done():
                if worker_pid:
                    with factory() as observer:
                        waiting = owner_pid in observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": worker_pid[0]})
                    if waiting: break
                time.sleep(0.01)
            assert waiting, "Switch must wait for Document before locking Version"
            version = owner.scalar(select(DocumentVersion).where(DocumentVersion.id == data["target"]).with_for_update())
            if change == "stale": version.lock_version += 1
            else: document.is_deleted = True
            owner.commit()
        finally:
            owner.rollback()
        future.result(timeout=10)


def test_canonical_read_validation_does_not_bind_version(stored_target):
    data = stored_target
    with get_session_factory()() as session:
        before = snapshot(session)
        result = load_published_embeddings(session, project=session.get(Project, data["project"]),
            version=session.get(DocumentVersion, data["target"]), chunks=[session.get(Chunk, data["chunk"])],
            build=session.get(EmbeddingBuild, data["build"]))
        assert result.build.id == data["build"] and not session.dirty
        assert snapshot(session) == before
        # Storage validation only. No publish/switch/Provider operation follows.


def test_real_connection_refusal_preserves_active_state(stored_target):
    # Bound but not listening is an actual unavailable TCP endpoint, not a mock.
    with socket.socket() as unavailable, get_session_factory()() as session:
        unavailable.bind(("127.0.0.1", 0))
        settings = get_settings().model_copy(update={"opensearch_url": f"http://127.0.0.1:{unavailable.getsockname()[1]}"})
        before = snapshot(session)
        with pytest.raises(AppError) as denied: switch(session, stored_target, settings=settings)
        assert denied.value.code == "opensearch_published_unavailable" and denied.value.status_code == 503
        assert snapshot(session) == before


def test_authenticated_owner_stale_and_legacy_refusals(stored_target, live_client):
    data = stored_target
    client, headers, _, _ = live_client
    path = f'/api/v1/document-versions/{data["target"]}/switch-active'
    def attempt(lock=1):
        return client.post(path, headers={**headers, "Idempotency-Key": uuid4().hex}, json={
            "lock_version": lock, "impact_confirmed": True, "audit_reason": "Stored guard acceptance"})
    with get_session_factory().begin() as session:
        session.get(Chunk, data["chunk"]).retrieval_text = None
    with get_session_factory()() as session:
        before = snapshot(session)
        assert attempt(0).json()["code"] == "validation_error"
        assert attempt(2).json()["code"] == "stale_document_version"
        result = attempt()
        assert result.status_code == 409 and result.json()["code"] == "retrieval_reprocessing_required"
        assert snapshot(session) == before
    # Removing the stored actor's Owner relationship leaves only viewer access.
    with get_session_factory().begin() as session:
        session.delete(session.get(ProjectOwner, (data["project"], data["actor"])))
        member = session.get(ProjectMember, (data["project"], data["actor"], "owner"))
        member.project_role = "viewer"
    with get_session_factory()() as session:
        before = snapshot(session)
        response = attempt()
        assert response.status_code == 403 and response.json()["code"] == "project_owner_required"
        assert snapshot(session) == before


def test_authenticated_chat_validation_identity_and_client_pages(stored_target, live_client):
    data = stored_target
    client, headers, _, _ = live_client
    now = datetime.now(UTC)
    prefix = f"chg296-{uuid4().hex}"
    with get_session_factory().begin() as session:
        runs = []
        for number in range(3):
            session.add(ChatRecord(project_id=data["project"], conversation_id=uuid4(),
                document_version_id=data["target"], scope_mode="document_staging", selected_document_version_ids=[str(data["target"])],
                question="Stored history input", answer="Not a generated answer", created_by=data["actor"],
                asked_at=now, created_at=now - timedelta(seconds=number)))
            run = ValidationRun(project_id=data["project"], document_version_id=data["target"], run_scope="document_staging",
                selected_document_ids=[str(data["target"])], status="queued", created_by=data["actor"],
                total_count=3, completed_count=0, failed_count=0, created_at=now - timedelta(seconds=number))
            session.add(run); session.flush(); runs.append(run.id)
            session.add(IdentitySyncRun(source="keycloak", status="failed", queued_at=now - timedelta(seconds=number)))
            session.add(IntegrationClient(name=f"{prefix}-{number}", status="inactive", api_key_hash=uuid4().hex + uuid4().hex,
                api_key_prefix="stored-no-key", created_at=now - timedelta(seconds=number)))
        for number in range(3):
            session.add(ValidationRunItem(run_id=runs[0], question="Stored pending input", status="pending",
                selected_document_ids=[str(data["target"])], input_ordinal=number, created_at=now))
    endpoints = [
        (f'/api/v1/projects/{data["project"]}/chat/conversations', {"scope_mode": "document_staging", "document_version_id": str(data["target"])}),
        (f'/api/v1/projects/{data["project"]}/chat/validation-runs', {"scope_mode": "document_staging", "document_version_id": str(data["target"])}),
        ('/api/v1/validation-runs', {"project_id": str(data["project"])}),
        (f'/api/v1/validation-runs/{runs[0]}/items', {}),
        ('/api/v1/integration-clients', {"name": prefix}),
    ]
    for path, params in endpoints:
        first = page(client, headers, path, **params, limit=2)
        assert len(first["items"]) == 2 and first["has_more"]
        last = page(client, headers, path, **params, limit=2, cursor=first["next_cursor"])
        assert len(last["items"]) == 1 and not last["has_more"]
        assert len({item["id"] for item in first["items"] + last["items"]}) == 3
    # Global admin identity history may contain other real test runs; still
    # verify actual continuation and filter binding without assuming totals.
    first = page(client, headers, '/api/v1/identity-sync/runs', limit=2, status="failed")
    assert first["has_more"] and len(first["items"]) == 2
    following = page(client, headers, '/api/v1/identity-sync/runs', limit=2, status="failed", cursor=first["next_cursor"])
    assert not ({item["id"] for item in first["items"]} & {item["id"] for item in following["items"]})
    response = client.get('/api/v1/identity-sync/runs', headers=headers, params={"status": "completed", "cursor": first["next_cursor"]})
    assert response.status_code == 422 and response.json()["code"] == "cursor_scope_mismatch"
