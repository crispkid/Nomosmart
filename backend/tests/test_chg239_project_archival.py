from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import AIModel, AIModelUsageEvent, DataConnection, DataSyncRun, Document, DocumentVersion, FileScanRun, OutboxEvent, PipelineRun, PipelineRunStep, Project, ProjectArchiveRun, ProjectOwner, User
from app.db.session import get_session_factory
from app.domain.project_archival import ARCHIVE_CLEANUP_TOPIC, COMPLETED_VERSION_STATUSES, _delete_unfinished_graph_artifacts, _delete_unfinished_s3_objects, _delete_unfinished_search_artifacts, _purge_unfinished_database_rows, _s3_uri, archive_impact, begin_project_archive
from app.domain.review_publish import LiveNeo4jGraphSyncAdapter, LiveOpenSearchPublishedAdapter
from app.integrations.s3_storage import S3ObjectStorage


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_chg239_migration_and_models_define_two_state_archive_lifecycle() -> None:
    migration = read("sql/migrations/V031__project_archive_lifecycle.sql")

    assert "CHECK (status IN ('active', 'archived'))" in migration
    assert "ADD COLUMN archived_at timestamptz" in migration
    assert "ADD COLUMN archived_by uuid REFERENCES users(id)" in migration
    assert "CREATE TABLE project_archive_runs" in migration
    assert "WHERE status IN ('queued', 'running')" in migration
    assert {"archived_at", "archived_by"} <= set(Project.__table__.columns.keys())
    assert {"status", "checkpoint", "attempt", "error_code", "lease_expires_at"} <= set(ProjectArchiveRun.__table__.columns.keys())


def test_chg239_archive_transaction_is_confirmed_and_revokes_runtime_access() -> None:
    routes = read("backend/app/api/routes/projects.py")
    domain = read("backend/app/domain/project_archival.py")
    public_api = read("backend/app/api/routes/public_api.py")

    assert 'status: Literal["active", "archived"]' in routes
    assert 'confirmation_name != project.name' in domain
    assert 'project.status = "archived"' in domain
    assert "delete(IntegrationClientProjectScope)" in domain
    assert "credential_encrypted=None" in domain
    assert "credential_secret_ref=None" in domain
    assert ARCHIVE_CLEANUP_TOPIC in domain
    assert 'project.status != "active"' in public_api
    assert '"archive_confirmation_required"' in routes


def test_chg239_live_postgresql_archive_transaction_is_atomic_and_idempotent() -> None:
    now = datetime.now(UTC)
    factory = get_session_factory()
    with factory() as session:
        actor = User(
            employee_id=f"Z{uuid4().hex[:9]}",
            keycloak_user_id=f"chg239-{uuid4()}",
            email=f"chg239-{uuid4()}@example.test",
            display_name="CHG-239 archive owner",
            auth_source="keycloak",
            is_active=True,
        )
        project = Project(name=f"CHG-239 {uuid4()}", description="live archive transaction", status="active", created_by=None, lock_version=1)
        session.add_all([actor, project])
        session.flush()
        project.created_by = actor.id
        session.add(ProjectOwner(project_id=project.id, user_id=actor.id, created_at=now))
        connection = DataConnection(
            project_id=project.id,
            service_type="http",
            name="CHG-239 source",
            connection_metadata={},
            credential_encrypted="encrypted-test-value",
            credential_secret_ref="test/secret",
            source_identity={},
            schedule_mode="manual",
            timezone="Asia/Taipei",
            enabled=True,
            created_by=actor.id,
        )
        session.add(connection)
        session.flush()

        document = Document(project_id=project.id, document_code=f"CHG239-{uuid4().hex[:8]}", title="Unfinished archive document", source_type="file_upload", status="inactive", created_by=actor.id)
        model = AIModel(name=f"chg239-model-{uuid4()}", model_type="Chat", provider="openai_compatible", is_active=True, is_default=False, config={})
        session.add_all([document, model])
        session.flush()
        version = DocumentVersion(project_id=project.id, document_id=document.id, version_major=1, extraction_revision=1, version_label="v1.0", status="draft", chunk_strategy={}, lock_version=1)
        session.add(version)
        session.flush()
        pipeline = PipelineRun(project_id=project.id, document_id=document.id, document_version_id=version.id, run_type="extraction", status="queued", progress_percent=0, triggered_by=actor.id, created_at=now)
        document_pipeline = PipelineRun(project_id=project.id, document_id=document.id, document_version_id=None, run_type="extraction", status="queued", progress_percent=0, triggered_by=actor.id, created_at=now)
        scan = FileScanRun(document_version_id=version.id, scanner_type="clamav", status="quarantine", created_at=now)
        sync = DataSyncRun(data_connection_id=connection.id, document_id=document.id, document_version_id=version.id, trigger_type="manual", status="queued", remote_metadata={}, created_at=now)
        session.add_all([pipeline, document_pipeline, scan, sync])
        session.flush()
        document_pipeline_step = PipelineRunStep(run_id=document_pipeline.id, step_name="parse_document", status="queued", progress_percent=0)
        session.add(document_pipeline_step)
        session.flush()
        usage = AIModelUsageEvent(
            model_id=model.id,
            model_type="Chat",
            provider=model.provider,
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            pipeline_run_id=document_pipeline.id,
            pipeline_step_id=document_pipeline_step.id,
            source_channel="test",
            usage_purpose="archive_cleanup",
            status="completed",
            attempted=True,
            raw_usage={},
            cost_source="unavailable",
            cost_metadata={},
            metadata_={},
            created_at=now,
        )
        session.add_all(
            [
                usage,
                OutboxEvent(topic="document.extraction.requested", aggregate_type="pipeline_run", aggregate_id=pipeline.id, payload={"pipeline_run_id": str(pipeline.id)}, status="pending", attempts=0, available_at=now, created_at=now),
                OutboxEvent(topic="file.scan.requested", aggregate_type="file_scan_run", aggregate_id=scan.id, payload={"scan_run_id": str(scan.id)}, status="pending", attempts=0, available_at=now, created_at=now),
                OutboxEvent(topic="data_source.sync.requested", aggregate_type="data_sync_run", aggregate_id=sync.id, payload={"run_id": str(sync.id)}, status="pending", attempts=0, available_at=now, created_at=now),
            ]
        )
        session.flush()

        impact = archive_impact(session, project)
        assert impact["lock_version"] == 1
        assert impact["completed_version_count"] == 0
        assert impact["unfinished_version_count"] == 1
        assert impact["deleted_document_count"] == 1
        assert impact["unfinished_pipeline_count"] == 2
        assert impact["unfinished_sync_count"] == 1

        archived = begin_project_archive(
            session,
            project_id=project.id,
            actor_user_id=actor.id,
            lock_version=1,
            confirmation_name=project.name,
            request_id="chg239-live-transaction",
        )
        session.flush()
        assert archived.status == "archived"
        assert archived.archived_by == actor.id
        assert archived.archived_at is not None
        assert archived.lock_version == 2
        assert connection.enabled is False
        assert connection.credential_encrypted is None
        assert connection.credential_secret_ref is None
        assert session.scalar(select(func.count()).select_from(ProjectArchiveRun).where(ProjectArchiveRun.project_id == project.id)) == 1
        run = session.scalar(select(ProjectArchiveRun).where(ProjectArchiveRun.project_id == project.id))
        assert run is not None
        assert session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.topic == ARCHIVE_CLEANUP_TOPIC, OutboxEvent.aggregate_id == run.id)) == 1

        repeated = begin_project_archive(
            session,
            project_id=project.id,
            actor_user_id=actor.id,
            lock_version=1,
            confirmation_name=project.name,
            request_id="chg239-live-transaction-repeated",
        )
        session.flush()
        assert repeated.id == archived.id
        assert session.scalar(select(func.count()).select_from(ProjectArchiveRun).where(ProjectArchiveRun.project_id == project.id)) == 1

        counts = _purge_unfinished_database_rows(session, project.id, [version])
        session.flush()
        assert counts == {"versions": 1, "documents": 1}
        assert session.get(DocumentVersion, version.id) is None
        assert session.get(Document, document.id) is None
        assert session.get(PipelineRun, pipeline.id) is None
        assert session.get(PipelineRun, document_pipeline.id) is None
        assert session.get(DataSyncRun, sync.id) is None
        assert session.scalar(select(func.count()).select_from(FileScanRun).where(FileScanRun.id == scan.id)) == 0
        session.refresh(usage)
        assert usage.document_id is None
        assert usage.document_version_id is None
        assert usage.pipeline_run_id is None
        assert usage.pipeline_step_id is None
        assert session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id.in_([pipeline.id, scan.id, sync.id]))) == 0
        session.rollback()


def test_chg239_cleanup_retains_only_published_active_or_inactive_versions() -> None:
    domain = read("backend/app/domain/project_archival.py")

    assert COMPLETED_VERSION_STATUSES == ("active", "inactive")
    assert "DocumentVersion.published_at.is_not(None)" in domain
    assert "DocumentVersion.status.in_(COMPLETED_VERSION_STATUSES)" in domain
    assert "_delete_unfinished_s3_objects" in domain
    assert "_delete_unfinished_search_artifacts" in domain
    assert "_delete_unfinished_graph_artifacts" in domain
    assert "_purge_unfinished_database_rows" in domain
    assert "_delete_unfinished_outbox_events" in domain
    assert _s3_uri("s3://bucket/path/to/file.pdf") == ("bucket", "path/to/file.pdf")
    assert _s3_uri("opensearch://staging-index") is None


def test_chg239_live_cross_store_cleanup_verifies_absence() -> None:
    settings = get_settings()
    version_id = uuid4()
    object_key = f"chg239-tests/{version_id}/unfinished.txt"
    index_name = f"chg239-test-{version_id}".lower()
    version = DocumentVersion(
        id=version_id,
        project_id=uuid4(),
        document_id=uuid4(),
        version_major=1,
        extraction_revision=1,
        version_label="v1.0",
        status="draft",
        storage_bucket=settings.s3_bucket,
        storage_key=object_key,
        extraction_artifact_uri=f"opensearch://{index_name}",
        chunk_strategy={},
        lock_version=1,
    )
    retained_version = DocumentVersion(
        id=uuid4(),
        project_id=uuid4(),
        document_id=uuid4(),
        version_major=1,
        extraction_revision=1,
        version_label="v1.0",
        status="active",
        published_at=datetime.now(UTC),
        storage_bucket=settings.s3_bucket,
        storage_key=object_key,
        extraction_artifact_uri=f"opensearch://{index_name}",
        chunk_strategy={},
        lock_version=1,
    )
    storage = S3ObjectStorage(settings)
    search = LiveOpenSearchPublishedAdapter(settings)
    graph = LiveNeo4jGraphSyncAdapter(settings)
    search_context = settings.opensearch_ssl_context

    storage.ensure_bucket(settings.s3_bucket)
    storage.put_object(bucket=settings.s3_bucket, key=object_key, body=b"CHG-239 unfinished", content_type="text/plain")
    search._request("PUT", f"{settings.opensearch_url.rstrip('/')}/{index_name}", b"{}", context=search_context, content_type="application/json")  # noqa: SLF001 - live integration setup
    driver = graph._driver()  # noqa: SLF001 - live integration setup
    try:
        with driver.session(database=settings.neo4j_database) as neo4j_session:
            neo4j_session.run("CREATE (:DocumentVersion {id: $version_id, status: 'staging'})", version_id=str(version_id)).consume()
        with get_session_factory()() as session:
            assert _delete_unfinished_s3_objects(settings, session, [version], [retained_version]) == 0
            assert _delete_unfinished_search_artifacts(settings, [version], [retained_version]) == 0
            assert storage.object_status(bucket=settings.s3_bucket, key=object_key)[1] is not None
            assert search.staging_index_exists(version=version) is True
            assert _delete_unfinished_s3_objects(settings, session, [version], []) == 1
            assert _delete_unfinished_search_artifacts(settings, [version], []) == 1
            assert _delete_unfinished_graph_artifacts(settings, [version]) == 1
        with pytest.raises(AppError, match="not found") as missing:
            storage.object_status(bucket=settings.s3_bucket, key=object_key)
        assert missing.value.code == "s3_object_missing"
        assert search.staging_index_exists(version=version) is False
        with driver.session(database=settings.neo4j_database) as neo4j_session:
            record = neo4j_session.run("MATCH (v:DocumentVersion {id: $version_id}) RETURN count(v) AS count", version_id=str(version_id)).single()
            assert record is not None and record["count"] == 0
    finally:
        storage.delete_object(bucket=settings.s3_bucket, key=object_key)
        search.delete_staging_documents(version=version)
        graph.delete_version(version_id=version_id)
        driver.close()


def test_chg239_workers_block_archived_project_writeback() -> None:
    worker = read("backend/app/worker.py")
    data_sync = read("backend/app/domain/data_sync.py")
    artifacts = read("backend/app/domain/chunk_artifacts.py")
    validation = read("backend/app/domain/validation_runner.py")
    publish = read("backend/app/domain/review_publish.py")

    assert "ARCHIVE_CLEANUP_TOPIC" in worker
    assert 'project.status != "active"' in worker
    assert 'project.status != "active"' in data_sync
    assert not (ROOT / "backend/app/domain/scan_worker.py").exists()
    assert 'project.status != "active"' in artifacts
    assert 'project.status != "active"' in validation
    assert 'project.status != "active"' in publish


def test_chg239_frontend_has_two_live_tabs_and_non_navigable_archive_cards() -> None:
    page = read("frontend/src/app/projects/page.tsx")
    api = read("frontend/src/lib/api.ts")
    zh = read("frontend/src/i18n/locales/zh.json")

    assert page.count('labelKey: "projectsTab') == 2
    assert 'id: "active"' in page
    assert 'id: "archived"' in page
    assert 'project.status === "active" ? <Link' in page
    assert "archiveConfirmation !== archiveTarget.name" in page
    assert "retryProjectArchiveCleanup" in page
    assert 'status: "active" | "archived" = "active"' in api
    assert '"projectsTabAll": "專案清單"' in zh
    assert '"projectsTabArchived": "已封存"' in zh
