from __future__ import annotations

import inspect
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.core.encryption import EnvelopeCipher
from app.db.models import EmbeddingBuild, EmbeddingBuildVector, FileScanRun, OutboxEvent, PipelineRunStep
from app.domain import document_imports
from app.domain.uploads import build_storage_identity, build_storage_key
from app.domain.data_sync import _CompensatingSnapshotStorage, _s3_connection_storage
from app.domain.document_imports import StoredObject
from app.db.models import DataConnection


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "development",
        "app_encryption_key": "a" * 64,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_scanner_modules_are_removed() -> None:
    root = Path(__file__).parents[2]
    assert not (root / "backend/app/domain/scanner.py").exists()
    assert not (root / "backend/app/domain/scan_worker.py").exists()


def test_canonical_storage_key_is_used_without_quarantine() -> None:
    project_id, document_id, version_id = uuid4(), uuid4(), uuid4()
    identity = build_storage_identity(b"content", "source.txt", salt=b"a" * 16)
    key = build_storage_key(str(project_id), str(document_id), str(version_id), identity)
    assert key.startswith(f"projects/{project_id}/documents/{document_id}/versions/{version_id}/source/")
    assert "quarantine" not in key


def test_s3_data_connection_builds_client_from_connection_credential_only() -> None:
    current = settings(s3_access_key_id="global-access", s3_secret_access_key="global-secret")
    project_id = uuid4()
    name = "isolated-s3"
    plaintext = '{"access_key":"connection-access","secret_key":"connection-secret","session_token":"session"}'
    connection_id = uuid4()
    connection = DataConnection(
        id=connection_id,
        project_id=project_id,
        service_type="S3",
        name=name,
        connection_metadata={"endpoint_url": "https://objects.example.test", "region": "ap-east-1", "bucket": "source", "verify_tls": True},
        credential_encrypted=EnvelopeCipher(current.encryption_key_bytes).encrypt(plaintext, context=f"data-source-connection:{connection_id}"),
        source_identity={"file_name": "source.txt"},
        schedule_mode="manual",
        timezone="Asia/Taipei",
        enabled=True,
        lock_version=1,
    )
    storage = _s3_connection_storage(current, connection)
    assert storage.config.endpoint_url == "https://objects.example.test"
    assert storage.config.region == "ap-east-1"
    assert storage.config.access_key == "connection-access"
    assert storage.config.secret_key == "connection-secret"
    assert storage.config.session_token == "session"
    assert storage.config.access_key != current.s3_access_key_id.get_secret_value()


def test_secure_ingestion_orm_and_migration_contract_match() -> None:
    assert {"quarantine_bucket", "quarantine_key", "accepted_bucket", "accepted_key", "claim_token", "lease_expires_at", "quarantine_deleted_at"} <= set(FileScanRun.__table__.columns.keys())
    assert {"claim_token", "lease_expires_at", "task_id"} <= set(OutboxEvent.__table__.columns.keys())
    assert {"artifact_fingerprint", "artifact_payload", "lease_expires_at"} <= set(PipelineRunStep.__table__.columns.keys())
    assert {"content_fingerprint", "model_id", "vector_dimension", "usage", "completed_at"} <= set(EmbeddingBuild.__table__.columns.keys())
    assert {"embedding_build_id", "chunk_id", "chunk_index", "vector", "vector_checksum"} <= set(EmbeddingBuildVector.__table__.columns.keys())
    migration = (Path(__file__).parents[2] / "sql/migrations/V021__secure_async_ingestion.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE embedding_build_vectors" in migration
    assert "uq_outbox_secure_ingestion_topic_aggregate" in migration


def test_document_import_domain_does_not_execute_extraction_in_request_path() -> None:
    source = inspect.getsource(document_imports)
    assert "execute_auto_extraction" not in source
    assert 'topic="file.scan.requested"' not in source
    assert 'topic="document.extraction.requested"' in source


def test_remote_sync_rolls_back_database_work_and_compensates_created_object() -> None:
    deleted: list[tuple[str, str]] = []

    class Storage:
        def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str | None) -> StoredObject:
            return StoredObject(bucket=bucket, key=key, etag="etag")

        def delete_object(self, *, bucket: str, key: str) -> None:
            deleted.append((bucket, key))

    storage = _CompensatingSnapshotStorage(Storage())
    storage.put_object(bucket="source", key="documents/version/source.txt", body=b"data", content_type="text/plain")
    assert storage.compensate() is True
    assert deleted == [("source", "documents/version/source.txt")]

    sync_source = (Path(__file__).parents[2] / "backend/app/domain/data_sync.py").read_text(encoding="utf-8")
    assert "with session.begin_nested():" in sync_source
    assert "data_sync_compensation_failed" in sync_source
