"""CHG-299: real S3/PostgreSQL/OIDC; no Provider or extraction worker.

Manual extraction acceptance stops at the genuine queued API contract. Stored
model/active-binding inputs below are never evidence of OCR or publication.
Run only on a fresh disposable V048 stack, serially with other API suites.
"""
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from urllib.parse import urlparse
from uuid import UUID, uuid4
from xml.etree import ElementTree

import httpx
import pytest
from sqlalchemy import select, text

if os.environ.get("CHG299_ISOLATED") != "1":
    raise RuntimeError("BLOCKED: CHG-299 requires its approved disposable services")

from test_live_backend_api_behavior import live_client, _assert_live_s3_sync_contract
from app.core.config import get_settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import (AIModel, ActiveVersionManifest, DataConnection, DataSyncRun,
    Document, DocumentVersion, EmbeddingBuild, EmbeddingProfile, OutboxEvent,
    PipelineRun, Project, ProjectMember, ProjectOwner)
from app.db.session import get_session_factory
from app.domain.data_sync import compute_next_run_at, queue_due_scheduled_data_syncs
from app.integrations.s3_storage import S3ObjectStorage
from app.worker import run_data_source_sync


@pytest.fixture(autouse=True)
def isolated_only():
    assert os.environ.get("CHG299_ISOLATED") == "1"
    assert "127.0.0.1" in get_settings().database_url.get_secret_value()
    assert urlparse(get_settings().s3_endpoint_url).hostname == "127.0.0.1"


@pytest.fixture
def make_project(live_client):
    _, _, actor, _ = live_client
    def create(role="owner"):
        with get_session_factory().begin() as session:
            project = Project(name="CHG299-" + uuid4().hex, status="active", work_generation=7)
            session.add(project); session.flush()
            session.add(ProjectMember(project_id=project.id, user_id=UUID(actor),
                project_role=role, created_at=datetime.now(UTC)))
            if role == "owner":
                session.add(ProjectOwner(project_id=project.id, user_id=UUID(actor), created_at=datetime.now(UTC)))
            return project.id
    return create


@pytest.fixture
def source(live_client, make_project):
    client, headers, _, _ = live_client
    settings = get_settings()
    storage = S3ObjectStorage(settings)
    storage.ensure_bucket(settings.s3_bucket)
    def create(*, role="owner", body=b"# Original\n\nSource text before manual extraction.",
               filename="remote.md", content_type="text/markdown", scheduled=False):
        project = make_project(role)
        prefix = "chg299/" + uuid4().hex
        key = prefix + "/" + filename
        if body is not None:
            storage.put_object(bucket=settings.s3_bucket, key=key, body=body, content_type=content_type)
        response = client.post(f"/api/v1/projects/{project}/data-sources", headers=headers, json={
            "name": "CHG299-" + uuid4().hex, "service_type": "S3",
            "host": settings.s3_endpoint_url, "port": urlparse(settings.s3_endpoint_url).port,
            "username": settings.s3_access_key_id.get_secret_value(),
            "credential": settings.s3_secret_access_key.get_secret_value(),
            "bucket": settings.s3_bucket, "region": settings.s3_region,
            "verify_tls": settings.s3_verify_tls, "remote_path": prefix, "file_name": filename,
            "schedule_mode": "cron" if scheduled else "once",
            "cron_expression": "*/5 * * * *" if scheduled else None, "timezone": "Asia/Taipei"})
        assert response.status_code == 201, response.text
        result = response.json()
        return dict(project=project, connection=UUID(result["data_source"]["id"]),
            document=UUID(result["document"]["id"]), run=UUID(result["sync_run"]["id"]),
            key=key, body=body, storage=storage)
    return create


def rows(table, where="true"):
    # Allowlisted callers only; actual rows rather than synthetic success flags.
    with get_session_factory()() as session:
        return session.scalar(text(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.id), '[]') FROM {table} t WHERE {where}"))


def downstream():
    tables = ("pipeline_runs", "pipeline_run_steps", "file_scan_runs", "ai_model_usage_events",
        "chunks", "embedding_builds", "embedding_build_vectors", "active_version_manifests", "graph_sync_jobs")
    result = {name: rows(name) for name in tables}
    result["extraction_outbox"] = rows("outbox_events", "topic = 'document.extraction.requested'")
    return result


def keys(storage):
    settings = get_settings()
    # ListObjects v1 needs no query parameters and uses the same signed request
    # contract as this client. Its object-only signer does not sign V2 queries.
    url = storage.config.endpoint_url.rstrip("/") + "/" + settings.s3_bucket + "/"
    headers = storage._signed_headers("GET", url, b"", datetime.now(UTC), None)
    response = httpx.get(url, headers=headers, verify=storage.config.verify_tls, timeout=15)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    assert root.findtext("{*}IsTruncated") == "false", "Test bucket exceeded one list page"
    return sorted(node.text for node in root.findall("{*}Contents/{*}Key"))


def execute(data, run_id=None):
    target = run_id or data["run"]
    # Execute only this exact sync task, never drain the shared outbox or run OCR.
    run_data_source_sync(str(target))
    with get_session_factory()() as session:
        run = session.get(DataSyncRun, target)
        if run.status in {"success", "unchanged", "failed"}:
            action = "failed" if run.status == "failed" else run.status
            audit = session.execute(text("SELECT result, summary FROM audit_logs "
                "WHERE resource_id = :id AND action = :action"),
                {"id": target, "action": "data_source.sync." + action}).all()
            assert len(audit) == 1
            assert audit[0].result == ("failed" if run.status == "failed" else "success")
            assert audit[0].summary["data_connection_id"] == str(data["connection"])
            if run.status == "failed":
                assert audit[0].summary["error_code"] == run.error_code
            else:
                assert audit[0].summary["fingerprint"] == run.content_fingerprint
        return run.status, run.error_code, run.document_version_id


def sync_again(live_client, data):
    client, headers, _, _ = live_client
    response = client.post(f"/api/v1/projects/{data['project']}/data-sources/{data['connection']}/sync", headers=headers)
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"])


def versions(data):
    return rows("document_versions", f"document_id = '{data['document']}'")


def assert_source(data, version_id, body):
    with get_session_factory()() as session:
        version = session.get(DocumentVersion, version_id)
        assert version.status == "ready_for_extraction"
        assert version.ocr_model_id is None
        assert version.content_sha256 == hashlib.sha256(body).hexdigest()
        remote = data["storage"].get_object(bucket=version.storage_bucket, key=version.storage_key)
        assert remote.body == body
        assert version.storage_key != data["key"]
        return version.storage_key


@pytest.mark.parametrize("role", ["owner", "editor"])
def test_api_first_sync_reuses_placeholder_without_ocr_or_downstream_work(source, role):
    data = source(role=role)
    placeholder = versions(data)
    assert len(placeholder) == 1 and placeholder[0]["status"] == "draft"
    assert placeholder[0]["content_sha256"] is None
    before = downstream()
    previous_keys = keys(data["storage"])
    status, code, version_id = execute(data)
    assert (status, code) == ("success", None)
    assert str(version_id) == placeholder[0]["id"]
    assert len(versions(data)) == 1
    snapshot_key = assert_source(data, version_id, data["body"])
    assert set(keys(data["storage"])) - set(previous_keys) == {snapshot_key}
    assert downstream() == before
    # Delivery replay is idempotent and does not fetch/write a second snapshot.
    after = versions(data), keys(data["storage"]), downstream()
    assert execute(data) == ("success", None, version_id)
    assert (versions(data), keys(data["storage"]), downstream()) == after


def test_unchanged_then_changed_source_preserves_prior_snapshot_and_active_binding(source, live_client):
    data = source()
    assert execute(data)[0] == "success"
    first = versions(data)[0]
    # Controlled database preservation input, NOT a claimed published build.
    with get_session_factory().begin() as session:
        model = AIModel(name="CHG299-binding-" + uuid4().hex, model_type="Embedding", provider="custom")
        session.add(model); session.flush()
        profile = EmbeddingProfile(model_id=model.id, model_version="preservation-input", vector_dimension=3,
            distance_method="cosine", chunk_strategy={}, mapping_version=1)
        session.add(profile); session.flush()
        build = EmbeddingBuild(project_id=data["project"], document_id=data["document"],
            document_version_id=UUID(first["id"]), embedding_profile_id=profile.id,
            build_revision=1, status="staged", chunk_count=0)
        session.add(build); session.flush()
        session.add(ActiveVersionManifest(project_id=data["project"], document_id=data["document"],
            document_version_id=UUID(first["id"]), embedding_profile_id=profile.id,
            embedding_build_id=build.id, publication_generation=1, index_ready=False))
        session.get(DocumentVersion, UUID(first["id"])).status = "active"
    before = downstream(), versions(data), keys(data["storage"])
    status, code, same = execute(data, sync_again(live_client, data))
    assert (status, code, str(same)) == ("unchanged", None, first["id"])
    assert (downstream(), versions(data), keys(data["storage"])) == before
    changed = b"# Revised\n\nChanged source must wait for manual extraction."
    data["storage"].put_object(bucket=get_settings().s3_bucket, key=data["key"], body=changed, content_type="text/markdown")
    status, code, version_id = execute(data, sync_again(live_client, data))
    assert (status, code) == ("success", None)
    assert version_id != same
    assert_source(data, version_id, changed)
    current = versions(data)
    assert len(current) == 2 and sorted(v["version_major"] for v in current) == [1, 2]
    assert next(v for v in current if v["id"] == first["id"]) == before[1][0]
    assert data["storage"].get_object(bucket=first["storage_bucket"], key=first["storage_key"]).body == data["body"]
    assert downstream() == before[0]


@pytest.mark.parametrize("kind,expected", [
    ("missing", "remote_file_not_found"), ("empty", "empty_upload_file"),
    ("invalid_utf8", "invalid_file_signature"), ("invalid_pdf", "invalid_file_signature"),
    ("database_constraint", "internal_failure"),
])
def test_real_source_failure_and_post_write_transaction_compensation(source, kind, expected):
    args = {"missing": {"body": None}, "empty": {"body": b""},
        "invalid_utf8": {"body": b"\xff\xfe"}, "invalid_pdf": {"filename": "bad.pdf", "body": b"not a PDF"},
        # S3 accepts this header; PostgreSQL's existing varchar(255) rejects it
        # after the actual snapshot PUT. No injected exception or DDL.
        "database_constraint": {"content_type": "text/" + "x" * 300}}[kind]
    data = source(**args)
    before = versions(data), downstream(), keys(data["storage"])
    status, code, _ = execute(data)
    assert (status, code) == ("failed", expected)
    assert (versions(data), downstream(), keys(data["storage"])) == before


@pytest.fixture
def ocr_model():
    # A real stored local OCR configuration. No execution or fake Provider result.
    with get_session_factory().begin() as session:
        model = AIModel(name="CHG299-local-ocr-" + uuid4().hex, model_type="OCR", provider="tesseract",
            is_active=True, is_default=False, config={"languages": ["eng"]})
        session.add(model); session.flush()
        return model.id


def test_failed_changed_version_compensates_new_snapshot_only(source, live_client):
    data = source()
    assert execute(data)[0] == "success"
    before = versions(data), downstream(), keys(data["storage"])
    data["storage"].put_object(bucket=get_settings().s3_bucket, key=data["key"],
        body=b"Changed body with real database-invalid metadata", content_type="text/" + "x" * 300)
    assert execute(data, sync_again(live_client, data))[:2] == ("failed", "internal_failure")
    assert (versions(data), downstream(), keys(data["storage"])) == before
    original = before[0][0]
    assert data["storage"].get_object(bucket=original["storage_bucket"], key=original["storage_key"]).body == data["body"]


@pytest.mark.parametrize("defect,code", [("bucket", "s3_connection_bucket_required"),
    ("region", "s3_connection_config_required"), ("missing", "data_source_credential_required"),
    ("invalid_json", "s3_connection_credential_invalid"), ("array", "s3_connection_credential_invalid"),
    ("incomplete", "s3_connection_credential_invalid")])
def test_stored_source_configuration_errors_fail_without_artifacts(source, defect, code):
    data = source()
    with get_session_factory().begin() as session:
        connection = session.get(DataConnection, data["connection"])
        if defect in {"bucket", "region"}:
            connection.connection_metadata = {**connection.connection_metadata, defect: ""}
        elif defect == "missing":
            connection.credential_encrypted = None
        else:
            plaintext = {"invalid_json": "not-json", "array": "[]", "incomplete": "{}"}[defect]
            connection.credential_encrypted = EnvelopeCipher(get_settings().encryption_key_bytes).encrypt(
                plaintext, context=f"data-source-connection:{connection.id}")
    before = versions(data), downstream(), keys(data["storage"])
    assert execute(data)[:2] == ("failed", code)
    assert (versions(data), downstream(), keys(data["storage"])) == before


def test_existing_legacy_encryption_context_and_string_tls_remain_compatible(source):
    data = source()
    settings = get_settings()
    with get_session_factory().begin() as session:
        connection = session.get(DataConnection, data["connection"])
        connection.credential_encrypted = EnvelopeCipher(settings.encryption_key_bytes).encrypt(json.dumps({
            "access_key": settings.s3_access_key_id.get_secret_value(),
            "secret_key": settings.s3_secret_access_key.get_secret_value()}),
            context=f"data-source:{connection.project_id}:{connection.name}")
        connection.connection_metadata = {**connection.connection_metadata, "verify_tls": "false"}
    before = downstream()
    status, code, version = execute(data)
    assert (status, code) == ("success", None)
    assert_source(data, version, data["body"])
    assert downstream() == before


@pytest.mark.parametrize("weekday", ["7", "7-7"])
def test_cron_range_list_and_sunday_preserve_next_run(weekday):
    assert compute_next_run_at(f"5,10 0-1 * * {weekday}", "UTC",
        after=datetime(2026, 9, 12, 23, 59, tzinfo=UTC)) == datetime(2026, 9, 13, 0, 5, tzinfo=UTC)


def test_impossible_cron_fails_without_work():
    with pytest.raises(AppError) as error:
        compute_next_run_at("0 0 31 2 *", "UTC", after=datetime(2026, 9, 12, tzinfo=UTC))
    assert error.value.code == "data_source_cron_no_next_run"


def extraction_path(data, version):
    return f"/api/v1/projects/{data['project']}/documents/{data['document']}/versions/{version}/extract"


@pytest.mark.parametrize("guard,code", [("missing_ocr", "ocr_model_required"),
    ("invalid_ocr", "invalid_ocr_model"), ("missing_source", "document_source_unavailable"),
    ("not_ready", "document_version_not_ready"), ("viewer", "project_editor_required")])
def test_manual_extraction_guards_remain_effective(source, live_client, ocr_model, guard, code):
    data = source()
    status, _, version = execute(data)
    assert status == "success"
    client, headers, actor, _ = live_client
    payload = {"ocr_model_id": str(ocr_model)}
    if guard == "missing_ocr":
        payload = {}
    if guard == "invalid_ocr":
        payload = {"ocr_model_id": str(uuid4())}
    with get_session_factory().begin() as session:
        if guard == "missing_source":
            session.get(DocumentVersion, version).storage_key = None
        if guard == "not_ready":
            session.get(DocumentVersion, version).status = "submission_ready"
        if guard == "viewer":
            member = session.scalar(select(ProjectMember).where(ProjectMember.project_id == data["project"]))
            member.project_role = "viewer"
            owner = session.scalar(select(ProjectOwner).where(ProjectOwner.project_id == data["project"]))
            session.delete(owner)
    before = downstream(), versions(data)
    response = client.post(extraction_path(data, version), headers=headers, json=payload)
    assert response.status_code in {403, 409, 422}, response.text
    assert response.json()["code"] == code
    assert (downstream(), versions(data)) == before


@pytest.mark.parametrize("role", ["owner", "editor"])
def test_explicit_manual_extraction_queues_exactly_once_without_execution(source, live_client, ocr_model, role):
    data = source(role=role)
    status, _, version = execute(data)
    assert status == "success"
    client, headers, actor, _ = live_client
    before = downstream()
    response = client.post(extraction_path(data, version), headers=headers, json={"ocr_model_id": str(ocr_model)})
    assert response.status_code == 200, response.text
    after = downstream()
    assert len(after["pipeline_runs"]) == len(before["pipeline_runs"]) + 1
    assert len(after["pipeline_run_steps"]) > len(before["pipeline_run_steps"])
    assert len(after["extraction_outbox"]) == len(before["extraction_outbox"]) + 1
    for table in ("file_scan_runs", "ai_model_usage_events", "chunks", "embedding_builds",
                  "embedding_build_vectors", "active_version_manifests", "graph_sync_jobs"):
        assert after[table] == before[table]
    with get_session_factory()() as session:
        pipeline = session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version))
        assert pipeline.status == "queued" and pipeline.project_generation == 7
        assert pipeline.triggered_by == UUID(actor)
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == pipeline.id))
        assert event.status == "pending" and event.project_generation == 7
        assert session.get(DocumentVersion, version).ocr_model_id == ocr_model
    duplicate = client.post(extraction_path(data, version), headers=headers, json={"ocr_model_id": str(ocr_model)})
    assert duplicate.status_code == 409
    assert downstream() == after


def test_scheduled_sync_and_generation_fence(source, live_client):
    data = source(scheduled=True)
    assert execute(data)[0] == "success"
    with get_session_factory().begin() as session:
        connection = session.get(DataConnection, data["connection"])
        identity = dict(connection.source_identity)
        connection.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        queued = queue_due_scheduled_data_syncs(session, now=datetime.now(UTC))
        own = [run for run in queued if run.data_connection_id == connection.id]
        assert len(own) == 1 and own[0].project_generation == 7
        scheduled_id = own[0].id
        assert connection.source_identity == identity
        assert connection.cron_expression == "*/5 * * * *"
    before = downstream()
    assert execute(data, scheduled_id)[0] == "unchanged"
    stale_id = sync_again(live_client, data)
    with get_session_factory().begin() as session:
        session.get(Project, data["project"]).work_generation = 8
    before_source = versions(data), keys(data["storage"])
    assert execute(data, stale_id)[:2] == ("cancelled", "project_work_generation_stale")
    assert (versions(data), keys(data["storage"])) == before_source
    assert downstream() == before


def test_original_broad_case4_s3_segment_unchanged_assertions(live_client, make_project):
    _, _, actor, _ = live_client
    _assert_live_s3_sync_contract(get_settings(), get_session_factory(), make_project(), actor)
