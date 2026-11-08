"""CHG-422 NativeOCR settings validation + real PostgreSQL transaction tests.

Set CHG422_TEST_DATABASE_URL to an isolated migrated database. No authentication,
Provider, HTTP or cleanup success is inferred from these domain-level tests.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import (ApprovalRequest, Document, DocumentVersion, OutboxEvent, Project,
                           StagingRetentionJob, SystemParameter, User)
from app.domain import system_parameter_store as store
from app.domain.staging_retention import schedule_retention, retention_state, execute_retention


@pytest.fixture
def engine():
    url = os.environ.get("CHG422_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CHG422_TEST_DATABASE_URL: isolated live PostgreSQL is required")
    from uuid import UUID
    run = UUID(os.environ["CHG422_TEST_RUN_ID"])
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    assert parsed.database == "nomosmart422fresh" and parsed.username == "nomosmart" and parsed.host == "localhost"
    assert parsed.query["sslmode"] == "verify-full"
    engine = create_engine(url, connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=5000"})
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT run_id FROM current_test_control.ownership")) == run
        assert connection.scalar(text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")) is True
        assert connection.scalar(text("SELECT count(*) FROM system_parameter_section_revisions")) == 2
    with Session(engine) as session:
        original = store.snapshot(session)[0]
    try:
        yield engine
    finally:
        # Restore test-owned settings through real CAS updates, retaining audit and counters.
        with Session(engine) as session:
            actual, _, revisions, _, _, _ = store.snapshot(session)
            for section, keys in store.SECTIONS.items():
                patch = {key: original[key] for key in keys if actual[key] != original[key]}
                if patch:
                    store.update_sections(session, changes={section: patch}, expected={section: revisions[section]},
                        actor=None, request_id="CHG-422-native-test-cleanup", deployment_limit=10240)
            session.commit()
        engine.dispose()


def current(engine):
    with Session(engine) as session:
        values, _, revisions, _, _, _ = store.snapshot(session)
        return values, revisions


def change(engine, section, revision, values):
    with Session(engine) as session:
        changed = store.update_sections(session, changes={section: values}, expected={section: revision},
            actor=None, request_id="CHG-389-live", deployment_limit=10240)
        session.commit()
        return changed


@pytest.mark.parametrize("key,value", [
    ("max_upload_size_mb", True), ("max_upload_size_mb", "20"), ("max_upload_size_mb", None),
    ("max_upload_size_mb", 0), ("max_upload_size_mb", 10241),
    ("staging_index_ttl_days", 3651), ("staging_index_ttl_days", -1),
    ("session_expired_form_draft_ttl_minutes", 4), ("session_expired_form_draft_ttl_minutes", False),
    ("default_timezone", "invalid/not-a-zone"), ("default_timezone", ""), ("default_timezone", "A" * 4096),
    ("ocr_request_max_output_tokens", 0), ("ocr_document_max_tokens", 2147483648),
])
def test_native_invalid_values(key, value):
    with pytest.raises(AppError) as caught:
        store.validate({key: value})
    assert caught.value.code == "invalid_system_parameters"
    assert caught.value.status_code == 422


def test_native_boundaries():
    for upload, days in [(1, 1), (10240, 3650)]:
        store.validate({"max_upload_size_mb": upload, "staging_index_ttl_days": days,
                        "default_timezone": "UTC", "session_expired_form_draft_ttl_minutes": 0})
    with pytest.raises(AppError):
        store.validate({"ocr_request_max_output_tokens": 20, "ocr_document_max_tokens": 19})


def test_live_cross_section_concurrency(engine):
    values, revisions = current(engine)
    barrier = Barrier(2)
    def write(section, patch):
        barrier.wait(timeout=5)
        return change(engine, section, revisions[section], patch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(write, "general", {"default_timezone": "UTC" if values["default_timezone"] != "UTC" else "Asia/Taipei"})
        two = pool.submit(write, "documents", {"max_upload_size_mb": values["max_upload_size_mb"] + 1})
        assert one.result() and two.result()
    actual, _ = current(engine)
    assert actual["max_upload_size_mb"] == values["max_upload_size_mb"] + 1
    assert actual["default_timezone"] != values["default_timezone"]


def test_live_same_section_competition_and_aba(engine):
    values, revisions = current(engine)
    barrier = Barrier(2)
    def write(value):
        barrier.wait(timeout=5)
        try:
            change(engine, "general", revisions["general"], {"session_expired_form_draft_ttl_minutes": value})
            return "updated"
        except AppError as error:
            return error.code
    options = [value for value in (5, 10, 15) if value != values["session_expired_form_draft_ttl_minutes"]][:2]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, value) for value in options]
        assert sorted(future.result() for future in futures) == ["system_parameters_conflict", "updated"]
    _, second = current(engine)
    change(engine, "general", second["general"], {"session_expired_form_draft_ttl_minutes": values["session_expired_form_draft_ttl_minutes"]})
    after, final = current(engine)
    assert after["session_expired_form_draft_ttl_minutes"] == values["session_expired_form_draft_ttl_minutes"]
    assert final["general"] != revisions["general"]
    with pytest.raises(AppError, match="Settings changed"):
        change(engine, "general", revisions["general"], {"default_timezone": "UTC"})


def test_live_noop_rollback_allowlist_and_missing_revision(engine):
    values, versions = current(engine)
    assert change(engine, "general", versions["general"], {"default_timezone": values["default_timezone"]}) is False
    assert current(engine) == (values, versions)
    for patch in [{"staging_index_ttl_days": 1}, {"default_timezone": None}, {}]:
        with pytest.raises(AppError):
            change(engine, "general", versions["general"], patch)
        assert current(engine) == (values, versions)
    with Session(engine) as session, pytest.raises(AppError) as caught:
        store.update_sections(session, changes={"general": {"default_timezone": "UTC"}}, expected={},
            actor=None, request_id=None, deployment_limit=10240)
    assert caught.value.status_code == 428


def test_live_ocr_failure_atomic_and_platform_capacity(engine):
    before, revisions = current(engine)
    with pytest.raises(AppError):
        change(engine, "documents", revisions["documents"], {"max_upload_size_mb": 1,
            "ocr_request_max_output_tokens": before["ocr_document_max_tokens"] + 1})
    assert current(engine) == (before, revisions)
    with Session(engine) as session:
        with pytest.raises(AppError):
            store.update_sections(session, changes={"documents": {"max_upload_size_mb": 101}},
                expected={"documents": revisions["documents"]}, actor=None, request_id=None, deployment_limit=100)
        session.rollback()
        row = session.scalar(select(SystemParameter).where(SystemParameter.key == "max_upload_size_mb"))
        row.value = 20
        session.flush()
        deployment = Settings(max_upload_size_mb=100)
        snapshot = store.intake_settings(session, deployment)
        row.value = 10
        session.flush()
        assert snapshot.max_upload_size_mb == 20
        assert store.intake_settings(session, deployment).max_upload_size_mb == 10
        assert deployment.max_upload_size_mb == 100
        assert snapshot.upload_request_max_bytes == deployment.upload_request_max_bytes
        row.value = 101
        session.flush()
        with pytest.raises(AppError) as caught:
            store.intake_settings(session, deployment)
        assert caught.value.status_code == 503


def test_live_new_rejection_snapshot_and_no_early_cleanup(engine):
    """Native domain scheduling, not a simulated successful review/Provider workflow."""
    now = datetime.now(UTC)
    with Session(engine) as session:
        user = User(id=uuid4(), employee_id="Z389TEST", display_name="CHG389 test input", auth_source="local")
        project = Project(id=uuid4(), name="CHG389 isolated test input")
        session.add_all([user, project]); session.flush()
        document = Document(id=uuid4(), project_id=project.id, document_code="CHG389", title="Retention policy input", source_type="file_upload")
        session.add(document); session.flush()
        version = DocumentVersion(id=uuid4(), project_id=project.id, document_id=document.id,
            version_major=1, extraction_revision=0, version_label="v1.0", status="review_rejected")
        session.add(version); session.flush()
        request = ApprovalRequest(id=uuid4(), project_id=project.id, document_id=document.id,
            document_version_id=version.id, submitter_id=user.id, owner_user_id=user.id,
            status="rejected", submitted_at=now, created_at=now)
        session.add(request); session.flush()
        schedule_retention(session, version, request.id, now)
        session.flush()
        job = session.scalar(select(StagingRetentionJob).where(StagingRetentionJob.document_version_id == version.id))
        assert job.expires_at == now + timedelta(days=job.ttl_days)
        original_deadline = job.expires_at
        row = session.scalar(select(SystemParameter).where(SystemParameter.key == "staging_index_ttl_days"))
        row.value = 1 if row.value != 1 else 2
        session.flush()
        assert retention_state(session, version.id)["expires_at"] == original_deadline
        assert retention_state(session, version.id)["expired"] is False
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id))
        assert event.available_at == original_deadline
        execute_retention(session, Settings(), job.id)
        assert job.status == "scheduled"  # No OpenSearch access before real expiry.
        assert retention_state(session, uuid4()) is None  # No invented historical deadline.


def test_live_archival_retention_fk_compatibility(engine):
    """Native archival DB policy inputs, not successful external cleanup evidence."""
    from app.domain.project_archival import begin_project_archive, _purge_unfinished_database_rows
    from app.db.models import ProjectArchiveRun
    now = datetime.now(UTC)
    with Session(engine) as session:
        user = User(id=uuid4(), employee_id="Z389ARCH", display_name="CHG389 archive input", auth_source="local")
        project = Project(id=uuid4(), name="CHG389 archival DB input")
        session.add_all([user, project]); session.flush()
        document = Document(id=uuid4(), project_id=project.id, document_code="CHG389A",
            title="Archival policy input", source_type="file_upload")
        session.add(document); session.flush()
        version = DocumentVersion(id=uuid4(), project_id=project.id, document_id=document.id,
            version_major=1, extraction_revision=0, version_label="v1.0", status="review_rejected")
        session.add(version); session.flush()
        approval = ApprovalRequest(id=uuid4(), project_id=project.id, document_id=document.id,
            document_version_id=version.id, submitter_id=user.id, owner_user_id=user.id,
            status="rejected", submitted_at=now, created_at=now)
        session.add(approval); session.flush()
        schedule_retention(session, version, approval.id, now); session.flush()
        job = session.scalar(select(StagingRetentionJob).where(StagingRetentionJob.document_version_id == version.id))
        begin_project_archive(session, project_id=project.id, actor_user_id=user.id,
            lock_version=project.lock_version, confirmation_name=project.name, request_id="CHG389-archive-native")
        session.flush(); session.refresh(job)
        assert job.status == "cancelled" and job.error_code == "project_archived"
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id))
        assert event.status == "cancelled"
        execute_retention(session, Settings(), job.id)  # No external deletion for cancelled work.
        cleanup = session.scalar(select(ProjectArchiveRun).where(ProjectArchiveRun.project_id == project.id))
        assert cleanup is not None
        assert _purge_unfinished_database_rows(session, project.id, [version], cleanup_run_id=cleanup.id) == {"versions": 1, "documents": 1}
        session.flush()
        assert session.scalar(select(StagingRetentionJob.id).where(StagingRetentionJob.id == job.id)) is None
        assert session.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_id == job.id)) is None
        assert session.scalar(text("SELECT count(*) FROM audit_logs WHERE resource_id = :id AND action = 'staging.retention.cancelled'"),
            {"id": project.id}) == 1


def test_live_initialization_fail_closed(engine):
    with Session(engine) as session:
        row = session.scalar(select(SystemParameter).where(SystemParameter.key == "default_timezone"))
        session.delete(row); session.flush()
        with pytest.raises(AppError) as caught:
            store.snapshot(session)
        assert caught.value.status_code == 503


def test_live_opensearch_exact_scope_primitive(engine):
    """Real deletion primitive, NOT a substitute for the one-day expiry workflow."""
    import httpx
    from app.domain.staging_retention import _delete_staging_scope
    url = os.environ.get("CHG422_TEST_OPENSEARCH_URL")
    if not url:
        pytest.skip("CHG422_TEST_OPENSEARCH_URL: isolated OpenSearch is required")
    configured = get_settings()
    prefix = configured.opensearch_index_prefix + "-native-" + uuid4().hex
    index, published = prefix + "-staging-profile", prefix + "-published-profile"
    if os.environ.get("NOMOSMART_TEST_SCOPE"):
        from owned_service_scope import verify_owned_services
        verify_owned_services(configured)
        assert url == configured.opensearch_url, "current_owned_opensearch_endpoint_required"
    with httpx.Client(base_url=url, auth=(configured.opensearch_username.get_secret_value(), configured.opensearch_password.get_secret_value()), verify=configured.opensearch_httpx_verify,
                      timeout=30, trust_env=False) as client, Session(engine) as session:
        project = Project(id=uuid4(), name="CHG389 exact-scope native input")
        session.add(project); session.flush()
        document = Document(id=uuid4(), project_id=project.id, document_code=uuid4().hex,
            title="Native OpenSearch deletion input", source_type="file_upload")
        session.add(document); session.flush()
        version = DocumentVersion(id=uuid4(), project_id=project.id, document_id=document.id,
            version_major=1, extraction_revision=0, version_label="v1.0", status="review_rejected",
            extraction_artifact_uri="opensearch://" + index)
        session.add(version); session.flush()
        mapping = {"mappings": {"properties": {key: {"type": "keyword"} for key in ("project_id", "document_id", "document_version_id")}}}
        try:
            for name in (index, published):
                client.put("/" + name, json=mapping).raise_for_status()
            target = {"project_id": str(project.id), "document_id": str(document.id), "document_version_id": str(version.id)}
            inputs = {"target": target,
                "other-version": {**target, "document_version_id": str(uuid4())},
                "other-project": {**target, "project_id": str(uuid4())},
                "other-document": {**target, "document_id": str(uuid4())}}
            for key, body in inputs.items():
                client.put(f"/{index}/_doc/{key}?refresh=true", json=body).raise_for_status()
            client.put(f"/{published}/_doc/protected?refresh=true", json=target).raise_for_status()
            settings = configured.model_copy(update={"opensearch_url": url, "opensearch_index_prefix": prefix})
            assert _delete_staging_scope(session, settings, project, version) == [index]
            assert client.get(f"/{index}/_count").json()["count"] == 3
            assert client.get(f"/{index}/_doc/target").status_code == 404
            for key in ("other-version", "other-project", "other-document"):
                assert client.get(f"/{index}/_doc/{key}").status_code == 200
            assert client.get(f"/{published}/_count").json()["count"] == 1
            assert _delete_staging_scope(session, settings, project, version) == [index]
            version.extraction_artifact_uri = "opensearch://" + published
            with pytest.raises(AppError) as caught:
                _delete_staging_scope(session, settings, project, version)
            assert caught.value.code == "staging_retention_protected"
            assert client.get(f"/{published}/_count").json()["count"] == 1
        finally:
            for name in (index, published):
                response = client.delete("/" + name)
                assert response.status_code in (200, 404)


def test_native_duplicate_json_fields_are_rejected():
    from app.api.routes.system import _unique_pairs
    with pytest.raises(AppError) as caught:
        _unique_pairs([("max_upload_size_mb", 20), ("max_upload_size_mb", 30)])
    assert caught.value.status_code == 422


def test_live_draft_retention_reader_and_missing_version(engine):
    from app.api.routes.auth import _draft_ttl_minutes
    from app.db.models import SystemParameterSectionRevision
    with Session(engine) as session:
        row = session.scalar(select(SystemParameter).where(SystemParameter.key == "session_expired_form_draft_ttl_minutes"))
        row.value = 0; session.flush()
        assert _draft_ttl_minutes(session) == 0
        row.value = True; session.flush()
        with pytest.raises(AppError) as caught:
            _draft_ttl_minutes(session)
        assert caught.value.status_code == 503
        session.rollback()
        session.delete(session.get(SystemParameterSectionRevision, "general")); session.flush()
        with pytest.raises(AppError) as caught:
            store.snapshot(session)
        assert caught.value.status_code == 503


@pytest.mark.parametrize("field,value", [
    ("staging_retention_batch_size", True), ("staging_retention_batch_size", 0),
    ("staging_retention_lease_seconds", 29), ("staging_retention_retry_seconds", ""),
    ("staging_retention_recovery_seconds", "1.5"), ("staging_retention_recovery_seconds", 3601),
])
def test_native_retention_deployment_limits(field, value):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(**{field: value})
