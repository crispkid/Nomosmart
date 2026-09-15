"""CHG-297 real SQL/OIDC/API acceptance; no Provider or current environment.

Stored jobs/completions prove persistence and response contracts only, never
successful synchronization, embedding, graph execution or publication.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import os
import secrets
import time
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

if os.environ.get("CHG297_ISOLATED") != "1":
    raise RuntimeError("BLOCKED: initialize fresh CHG-297 services before collection")

from test_live_backend_api_behavior import live_client, _service_token
from test_chg296_cursor_and_switch_guards import stored_target
from app.api.routes.data_sources import _lock_enqueue_project
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.idempotency import canonical_request_hash, storage_scope
from app.db.models import (DataConnection, DataSyncRun, Document, DocumentVersion,
    GraphSyncJob, IdempotencyKey, OutboxEvent, Project, ProjectMember, ProjectOwner,
    RoleUser, User)
from app.db.session import get_session_factory
from app.domain.data_sync import queue_due_scheduled_data_syncs
from app.domain.public_api_controls import (begin_idempotent_operation,
    complete_idempotent_operation, fail_idempotent_operation, keyed_fingerprint)


@pytest.fixture(autouse=True)
def isolated_only():
    assert os.environ.get("CHG297_ISOLATED") == "1"
    assert "127.0.0.1" in get_settings().database_url.get_secret_value()


@pytest.fixture
def make_project(live_client):
    _, _, actor, _ = live_client
    def create(role="owner", generation=7):
        with get_session_factory().begin() as session:
            project = Project(name="CHG297-" + uuid4().hex, status="active", work_generation=generation)
            session.add(project); session.flush()
            if role:
                session.add(ProjectMember(project_id=project.id, user_id=UUID(actor),
                    project_role=role, created_at=datetime.now(UTC)))
            if role == "owner":
                session.add(ProjectOwner(project_id=project.id, user_id=UUID(actor), created_at=datetime.now(UTC)))
            return project.id
    return create


def payload(**changes):
    return {"service_type": "HTTP_API", "name": "CHG297-" + uuid4().hex,
        "host": "", "port": 443, "username": "", "file_name": "remote.md",
        "schedule_mode": "once", "url": "https://example.invalid/never-fetched.md",
        "auth_mode": "none", **changes}


def create_source(client, headers, project_id, **changes):
    response = client.post(f"/api/v1/projects/{project_id}/data-sources", headers=headers, json=payload(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def snapshot():
    tables = ("data_connections", "documents", "document_versions", "data_sync_runs",
        "outbox_events", "pipeline_runs", "graph_sync_jobs", "ai_model_usage_events",
        "active_version_manifests", "audit_logs", "idempotency_keys")
    with get_session_factory()() as session:
        return {table: session.scalar(text(
            f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.id), '[]') FROM {table} t")) for table in tables}


def assert_generation(run_id, generation):
    with get_session_factory()() as session:
        run = session.get(DataSyncRun, UUID(str(run_id)))
        events = list(session.scalars(select(OutboxEvent).where(
            OutboxEvent.aggregate_id == run.id, OutboxEvent.topic == "data_source.sync.requested")))
        assert len(events) == 1
        event = events[0]
        connection = session.get(DataConnection, run.data_connection_id)
        assert run.project_generation == event.project_generation == event.payload["project_generation"] == generation
        assert event.project_id == connection.project_id
        assert event.payload["project_id"] == str(connection.project_id)
        assert event.payload["run_id"] == str(run.id)
        assert run.status == "queued" and event.status == "pending"


@pytest.mark.parametrize("role", ["owner", "editor"])
@pytest.mark.parametrize("generation", [1, 7])
def test_initial_generation_and_existing_response(live_client, make_project, role, generation):
    client, headers, _, _ = live_client
    project = make_project(role, generation)
    before = snapshot()
    result = create_source(client, headers, project)
    assert_generation(result["sync_run"]["id"], generation)
    after = snapshot()
    for table in ("data_connections", "documents", "document_versions", "data_sync_runs", "outbox_events", "audit_logs"):
        assert len(after[table]) == len(before[table]) + 1
    for table in ("pipeline_runs", "graph_sync_jobs", "ai_model_usage_events", "active_version_manifests"):
        assert after[table] == before[table]
    assert result["sync_run"]["document_id"] == result["document"]["id"]
    assert "credential_encrypted" not in result["data_source"]


def test_manual_and_scheduled_generation_preserve_source_and_schedule(live_client, make_project):
    client, headers, _, _ = live_client
    project = make_project()
    result = create_source(client, headers, project, schedule_mode="cron", cron_expression="0 * * * *")
    cid = UUID(result["data_source"]["id"])
    path = f"/api/v1/projects/{project}/data-sources/{cid}/sync"
    before = snapshot()
    assert client.post(path, headers=headers).json()["code"] == "data_source_sync_already_running"
    assert snapshot() == before
    with get_session_factory().begin() as session:
        session.get(DataSyncRun, UUID(result["sync_run"]["id"])).status = "failed"
        session.get(Project, project).work_generation = 12
        connection = session.get(DataConnection, cid)
        original = (connection.source_identity, connection.connection_metadata, connection.cron_expression, connection.next_run_at)
    response = client.post(path, headers=headers)
    assert response.status_code == 202, response.text
    assert_generation(response.json()["id"], 12)
    with get_session_factory().begin() as session:
        connection = session.get(DataConnection, cid)
        assert (connection.source_identity, connection.connection_metadata, connection.cron_expression, connection.next_run_at) == original
        session.get(DataSyncRun, UUID(response.json()["id"])).status = "failed"
        connection.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        session.flush()
        queued = queue_due_scheduled_data_syncs(session)
        own = [run for run in queued if run.data_connection_id == cid]
        assert len(own) == 1 and own[0].trigger_type == "scheduled"
        scheduled_id = own[0].id
    assert_generation(scheduled_id, 12)


@pytest.mark.parametrize("role,archived,status", [("viewer", False, 403), (None, False, 403), ("owner", True, 409)])
def test_create_scope_and_archive_denials_are_atomic(live_client, make_project, role, archived, status):
    client, headers, _, _ = live_client
    project = make_project(role)
    if archived:
        with get_session_factory().begin() as session:
            row = session.get(Project, project)
            row.status = "archived"
            row.archived_at = datetime.now(UTC)
            row.archived_by = UUID(live_client[2])
    before = snapshot()
    result = client.post(f"/api/v1/projects/{project}/data-sources", headers=headers, json=payload())
    assert result.status_code == status, result.text
    assert snapshot() == before


def test_real_unique_constraint_failure_rolls_back_all_creation_rows(live_client, make_project):
    client, headers, _, _ = live_client
    project = make_project()
    # Existing valid row creates an actual next-code collision, not an injected
    # adapter failure or a changed database constraint.
    with get_session_factory().begin() as session:
        session.add(Document(project_id=project, document_code="DOC-000002", title="Existing collision input", source_type="upload"))
    before = snapshot()
    with pytest.raises(IntegrityError) as failure:
        client.post(f"/api/v1/projects/{project}/data-sources", headers=headers, json=payload())
    assert failure.value.orig.pgcode == "23505"
    assert snapshot() == before


def bounded(session):
    session.execute(text("SET LOCAL lock_timeout='4s'"))
    session.execute(text("SET LOCAL statement_timeout='8s'"))


@pytest.mark.parametrize("change", ["archive", "generation"])
def test_enqueue_parent_lock_refreshes_cached_state(make_project, live_client, change):
    project = make_project()
    worker_pids = []
    def waiting():
        with get_session_factory()() as session:
            bounded(session)
            cached = session.get(Project, project)
            assert cached.work_generation == 7
            worker_pids.append(session.scalar(text("SELECT pg_backend_pid()")))
            try:
                locked = _lock_enqueue_project(session, project)
                return locked.work_generation
            except AppError as exc:
                return exc.code
    with get_session_factory()() as owner, ThreadPoolExecutor(max_workers=1) as pool:
        bounded(owner)
        row = owner.scalar(select(Project).where(Project.id == project).with_for_update())
        owner_pid = owner.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(waiting)
        try:
            deadline = time.monotonic() + 3
            blocked = False
            while time.monotonic() < deadline:
                if worker_pids:
                    with get_session_factory()() as observer:
                        blocked = owner_pid in observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": worker_pids[0]})
                if blocked: break
                time.sleep(0.01)
            assert blocked, "enqueue must wait on actual parent lock"
            row.work_generation = 8
            if change == "archive":
                row.status = "archived"
                row.archived_at = datetime.now(UTC)
                row.archived_by = UUID(live_client[2])
            owner.commit()
        finally:
            owner.rollback()
        assert future.result(timeout=8) == ("project_archived" if change == "archive" else 8)


def test_concurrent_manual_queue_accepts_only_one_request(live_client, make_project):
    client, headers, _, _ = live_client
    project = make_project()
    result = create_source(client, headers, project)
    with get_session_factory().begin() as session:
        session.get(DataSyncRun, UUID(result["sync_run"]["id"])).status = "failed"
    path = f'/api/v1/projects/{project}/data-sources/{result["data_source"]["id"]}/sync'
    before = snapshot()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(path, headers=headers), range(2)))
    assert sorted(response.status_code for response in results) == [202, 409]
    after = snapshot()
    for table in ("data_sync_runs", "outbox_events", "audit_logs"):
        assert len(after[table]) == len(before[table]) + 1


@pytest.fixture
def other_identity(live_client):
    _, _, _, role = live_client
    settings = get_settings()
    issuer = settings.oidc_issuer_url.rstrip("/")
    realm = issuer.split("/")[-1]
    assert realm == os.environ["CHG295_ISOLATED_REALM"]
    base = settings.keycloak_admin_api_url.rstrip("/") + "/admin/realms/" + realm
    name, secret = "chg297-" + uuid4().hex, secrets.token_urlsafe(32)
    with httpx.Client(timeout=20) as http:
        auth = {"Authorization": "Bearer " + _service_token()}
        response = http.post(base + "/clients", headers=auth, json={"clientId": name,
            "secret": secret, "serviceAccountsEnabled": True, "publicClient": False,
            "standardFlowEnabled": False, "protocolMappers": [{"name": "aud", "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper", "config": {"included.custom.audience": settings.oidc_audience,
                    "access.token.claim": "true"}}]})
        response.raise_for_status()
        identity = response.headers["location"].split("/")[-1]
        try:
            response = http.get(base + f"/clients/{identity}/service-account-user", headers=auth)
            response.raise_for_status()
            subject = response.json()["id"]
            with get_session_factory().begin() as session:
                user = User(keycloak_user_id=subject, display_name="CHG297 second identity", is_active=True)
                session.add(user); session.flush()
                session.add(RoleUser(role_id=UUID(role), user_id=user.id, source="manual"))
                user_id = user.id
            response = http.post(issuer + "/protocol/openid-connect/token", data={
                "client_id": name, "client_secret": secret, "grant_type": "client_credentials"})
            response.raise_for_status()
            yield user_id, {"Authorization": "Bearer " + response.json()["access_token"]}
        finally:
            response = http.delete(base + f"/clients/{identity}", headers={"Authorization": "Bearer " + _service_token()})
            response.raise_for_status()


@pytest.mark.parametrize("count,limit", [(0, 2), (1, 2), (2, 2), (5, 2)])
def test_graph_job_safe_projection_and_cursor_isolation(live_client, make_project, other_identity, count, limit):
    client, headers, _, _ = live_client
    other, other_headers = other_identity
    project, foreign = make_project(), make_project(None)
    now = datetime.now(UTC)
    ids = []
    with get_session_factory().begin() as session:
        session.add(ProjectMember(project_id=project, user_id=other, project_role="viewer", created_at=now))
        for pid in (project, foreign):
            document = Document(project_id=pid, document_code=uuid4().hex, title="Stored graph input", source_type="upload")
            session.add(document); session.flush()
            version = DocumentVersion(project_id=pid, document_id=document.id, version_major=1, extraction_revision=0,
                version_label="v1.0", status="draft")
            session.add(version); session.flush()
            for index in range(count if pid == project else 1):
                job = GraphSyncJob(project_id=pid, document_id=document.id, document_version_id=version.id,
                    trigger_type="publication", status="queued", node_count=0, edge_count=0,
                    claim_token=uuid4(), created_at=now - timedelta(seconds=index))
                session.add(job); session.flush()
                if pid == project: ids.append(str(job.id))
    before = snapshot()
    path = "/api/v1/graph-sync-jobs"
    params = {"project_id": str(project), "status": "queued", "limit": limit}
    def fetch(h=headers, **extra):
        return client.get(path, headers=h, params={**params, **extra})
    result = fetch(); assert result.status_code == 200, result.text
    first = page = result.json(); seen = []
    while True:
        assert page["has_more"] == bool(page["next_cursor"])
        for item in page["items"]:
            assert set(item) == {"id", "project_id", "document_id", "document_version_id", "trigger_type",
                "status", "node_count", "edge_count", "error_message", "created_at", "completed_at"}
            seen.append(item["id"])
        if not page["has_more"]: break
        response = fetch(cursor=page["next_cursor"]); assert response.status_code == 200
        page = response.json()
    assert seen == ids
    if first["has_more"]:
        cursor = first["next_cursor"]
        for response in (fetch(cursor="!" + cursor[1:]), fetch(cursor=cursor, status="failed"), fetch(other_headers, cursor=cursor)):
            assert response.status_code == 422
            assert response.json()["code"] in {"cursor_invalid", "cursor_scope_mismatch"}
        assert fetch(cursor=cursor, project_id=str(foreign)).status_code == 403
    assert fetch(project_id=str(foreign)).status_code == 403
    assert snapshot() == before


@pytest.mark.parametrize("scope", ["x" * 99, "x" * 100, "x" * 101, "資料" * 60])
def test_storage_scope_boundary_and_real_varchar(scope):
    expected = scope if len(scope) <= 100 else "scope:v1:sha256:" + hashlib.sha256(scope.encode()).hexdigest()
    assert storage_scope(scope) == expected
    if len(scope) > 100: assert len(expected) == 80
    with get_session_factory()() as session:
        _, record = begin_idempotent_operation(session, get_settings(), scope=scope,
            raw_key=uuid4().hex, request_payload={"contract": "persistence"})
        assert record.scope == expected
        assert session.scalar(text("SELECT character_maximum_length FROM information_schema.columns WHERE table_name='idempotency_keys' AND column_name='scope'")) == 100
        session.rollback()


@pytest.mark.parametrize("prefix,parts", [("approval.approve", 2), ("approval.reject", 2), ("document-version.publish", 2),
    ("document-version.switch-active", 2), ("graph-sync.retry", 2), ("public-chat", 2),
    ("public-feedback", 2), ("document-upload", 2), ("document-upload-item", 2), ("document-reextract", 3),
    ("document.submit-review", 2)])
def test_existing_caller_scope_compatibility(prefix, parts):
    ids = [str(uuid4()) for _ in range(parts)]
    raw = ":".join([prefix, *ids])
    if prefix == "document-upload-item": raw += ":0"
    if prefix == "public-chat": raw += ":json"
    encoded = storage_scope(raw)
    assert encoded == raw if len(raw) <= 100 else len(encoded) == 80
    assert storage_scope(raw) == encoded
    assert storage_scope(raw + ":different-tail") != encoded
    assert storage_scope(raw.replace(ids[-1], str(uuid4()))) != encoded
    assert storage_scope("different-operation:" + ":".join(ids)) != encoded
    if prefix == "public-chat": assert storage_scope(raw.removesuffix("json") + "sse") != encoded


def test_short_legacy_and_long_replay_conflict_failure_and_identity():
    settings = get_settings()
    key = uuid4().hex
    target, actor = uuid4(), uuid4()
    short = f"approval.approve:{target}:{actor}"
    long = f"document-version.switch-active:{target}:{actor}"
    assert len(long) == 104
    now = datetime.now(UTC)
    body = {"contract": "stored-idempotency-state-only"}
    request = {"target": str(target), "value": 1}
    with get_session_factory().begin() as session:
        session.add(IdempotencyKey(scope=short, key=keyed_fingerprint(settings, "public-idempotency", key),
            request_hash=canonical_request_hash(request), status="completed", response_status=202,
            response_summary=body, created_at=now, completed_at=now, expires_at=now + timedelta(hours=1)))
    with get_session_factory().begin() as session:
        replay, old = begin_idempotent_operation(session, settings, scope=short, raw_key=key, request_payload=request)
        assert replay.body == body and replay.status_code == 202 and old.scope == short
        replay, record = begin_idempotent_operation(session, settings, scope=long, raw_key=key, request_payload=request)
        assert replay is None
        complete_idempotent_operation(record, body, status_code=202)
    with get_session_factory()() as session:
        replay, record = begin_idempotent_operation(session, settings, scope=long, raw_key=key, request_payload=request)
        assert replay.body == body and replay.status_code == 202
        for different in (long.replace(str(actor), str(uuid4())), long.replace(str(target), str(uuid4()))):
            other, _ = begin_idempotent_operation(session, settings, scope=different, raw_key=key, request_payload=request)
            assert other is None
        with pytest.raises(AppError) as conflict:
            begin_idempotent_operation(session, settings, scope=long, raw_key=key, request_payload={"value": 2})
        assert conflict.value.code == "idempotency_key_conflict"
        session.rollback()
    failed_key = uuid4().hex
    with get_session_factory().begin() as session:
        _, failed = begin_idempotent_operation(session, settings, scope=long, raw_key=failed_key, request_payload=request)
        fail_idempotent_operation(failed, AppError("contract_failed", "Stored failure", status_code=409))
    with get_session_factory()() as session:
        replay, _ = begin_idempotent_operation(session, settings, scope=long, raw_key=failed_key, request_payload=request)
        assert replay.status_code == 409 and replay.body["error"]["code"] == "contract_failed"


@pytest.mark.parametrize("raw_key", [None, "short", "x" * 256, "invalid key"])
def test_invalid_idempotency_key_never_persists(raw_key):
    before = snapshot()
    with get_session_factory()() as session, pytest.raises(AppError) as denied:
        begin_idempotent_operation(session, get_settings(), scope="x" * 104, raw_key=raw_key, request_payload={})
    assert denied.value.code == "idempotency_key_required" and denied.value.status_code == 422
    assert snapshot() == before


@pytest.mark.parametrize("expired", ["in_progress", "lease", "ttl"])
def test_existing_idempotency_lifecycle(expired):
    settings, key = get_settings(), uuid4().hex
    scope = "lifecycle:" + uuid4().hex * 4
    with get_session_factory().begin() as session:
        _, record = begin_idempotent_operation(session, settings, scope=scope, raw_key=key, request_payload={})
        identity = record.id
        if expired == "ttl": record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if expired == "lease": record.created_at = datetime.now(UTC) - timedelta(seconds=settings.public_api_idempotency_lease_seconds + 1)
    with get_session_factory()() as session:
        if expired == "ttl":
            replay, record = begin_idempotent_operation(session, settings, scope=scope, raw_key=key, request_payload={})
            assert replay is None and record.id != identity
        else:
            with pytest.raises(AppError) as denied:
                begin_idempotent_operation(session, settings, scope=scope, raw_key=key, request_payload={})
            assert denied.value.code == ("idempotency_key_expired" if expired == "lease" else "idempotency_key_in_progress")
        session.rollback()


def test_concurrent_long_scope_single_claim_and_conflict_reread():
    settings, key = get_settings(), uuid4().hex
    scope = "concurrent:" + uuid4().hex * 4
    pids = []
    def competing():
        with get_session_factory()() as session:
            bounded(session)
            pids.append(session.scalar(text("SELECT pg_backend_pid()")))
            try:
                begin_idempotent_operation(session, settings, scope=scope, raw_key=key, request_payload={})
                return "unexpected-second-claim"
            except AppError as error:
                return error.code
    with get_session_factory()() as first, ThreadPoolExecutor(max_workers=1) as pool:
        bounded(first)
        _, owned = begin_idempotent_operation(first, settings, scope=scope, raw_key=key, request_payload={})
        first_pid = first.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(competing)
        try:
            deadline = time.monotonic() + 3
            waiting = False
            while time.monotonic() < deadline:
                if pids:
                    with get_session_factory()() as observer:
                        waiting = first_pid in observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[0]})
                if waiting: break
                time.sleep(0.01)
            assert waiting, "second insert must reach real database uniqueness wait"
            first.commit()
        finally:
            first.rollback()
        assert future.result(timeout=8) == "idempotency_key_in_progress"
    with get_session_factory()() as session:
        rows = list(session.scalars(select(IdempotencyKey).where(IdempotencyKey.scope == storage_scope(scope))))
        assert len(rows) == 1 and rows[0].id == owned.id


def test_switch_missing_key_missing_target_and_guard_rollbacks(live_client):
    client, headers, _, _ = live_client
    before = snapshot()
    path = f"/api/v1/document-versions/{uuid4()}/switch-active"
    request = {"lock_version": 1, "impact_confirmed": True, "audit_reason": "CHG297 negative acceptance"}
    result = client.post(path, headers=headers, json=request)
    assert result.status_code == 422 and result.json()["code"] == "idempotency_key_required"
    result = client.post(path, headers={**headers, "Idempotency-Key": uuid4().hex}, json=request)
    assert result.status_code == 404 and result.json()["code"] == "document_version_not_found"
    assert snapshot() == before


@pytest.mark.parametrize("failure,code,status", [("stale", "stale_document_version", 409),
    ("legacy", "retrieval_reprocessing_required", 409), ("owner", "project_owner_required", 403)])
def test_switch_existing_guard_preserves_idempotency_and_business_state(live_client, stored_target, failure, code, status):
    from app.db.models import Chunk
    client, headers, _, _ = live_client
    data = stored_target
    with get_session_factory().begin() as session:
        session.get(Chunk, data["chunk"]).retrieval_text = None
        if failure == "owner":
            session.delete(session.get(ProjectOwner, (data["project"], data["actor"])))
            session.get(ProjectMember, (data["project"], data["actor"], "owner")).project_role = "viewer"
    before = snapshot()
    response = client.post(f'/api/v1/document-versions/{data["target"]}/switch-active',
        headers={**headers, "Idempotency-Key": uuid4().hex}, json={
            "lock_version": 2 if failure == "stale" else 1,
            "impact_confirmed": True, "audit_reason": "CHG297 negative guard input"})
    assert response.status_code == status and response.json()["code"] == code
    assert snapshot() == before


@pytest.mark.parametrize("role", ["viewer", "foreign", "archived"])
def test_manual_sync_denial_preserves_all_work(live_client, make_project, role):
    client, headers, actor, _ = live_client
    project = make_project()
    result = create_source(client, headers, project)
    with get_session_factory().begin() as session:
        session.get(DataSyncRun, UUID(result["sync_run"]["id"])).status = "failed"
        if role == "archived":
            row = session.get(Project, project)
            row.status, row.archived_at, row.archived_by = "archived", datetime.now(UTC), UUID(actor)
        else:
            session.delete(session.get(ProjectOwner, (project, UUID(actor))))
            member = session.get(ProjectMember, (project, UUID(actor), "owner"))
            if role == "viewer": member.project_role = "viewer"
            else: session.delete(member)
    before = snapshot()
    response = client.post(f'/api/v1/projects/{project}/data-sources/{result["data_source"]["id"]}/sync', headers=headers)
    assert response.status_code == (409 if role == "archived" else 403)
    assert snapshot() == before
