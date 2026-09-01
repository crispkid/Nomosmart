from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import DataConnection, DataSyncRun, Document, DocumentVersion, OutboxEvent, Project
from app.domain.document_imports import ObjectStorage, UploadedFilePayload, queue_document_extraction, validate_file_payload
from app.domain.reference_events import create_source_reference_events
from app.domain.uploads import build_storage_identity, build_storage_key, sanitize_original_filename, validate_source_extension
from app.integrations.remote_sources import FTPRemoteSourceClient, FTPSRemoteSourceClient, HTTPRemoteSourceClient, SFTPRemoteSourceClient
from app.integrations.s3_storage import S3ClientConfig, S3ObjectStorage
from app.services.audit import add_audit
from app.security.secrets import resolve_runtime_secret


RUNNING_SYNC_STATUSES = ("queued", "running")


class RemoteObjectStorage:
    def get_object(self, *, bucket: str, key: str, max_bytes: int | None = None):  # pragma: no cover - protocol
        raise NotImplementedError


class _CompensatingSnapshotStorage:
    """Track objects created by one sync attempt so a failed attempt leaves no orphan."""

    def __init__(self, storage: ObjectStorage) -> None:
        self._storage = storage
        self._created: list[tuple[str, str]] = []

    def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str | None):
        stored = self._storage.put_object(bucket=bucket, key=key, body=body, content_type=content_type)
        self._created.append((stored.bucket, stored.key))
        return stored

    def compensate(self) -> bool:
        delete_object = getattr(self._storage, "delete_object", None)
        if not callable(delete_object):
            return not self._created
        complete = True
        for bucket, key in reversed(self._created):
            try:
                delete_object(bucket=bucket, key=key)
            except Exception:
                complete = False
        return complete


def execute_data_source_sync(
    *,
    session: Session,
    settings: Settings,
    run_id: UUID,
    remote_storage: RemoteObjectStorage | None = None,
    snapshot_storage: ObjectStorage | None = None,
) -> DataSyncRun | None:
    run = session.get(DataSyncRun, run_id)
    if run is None:
        return None
    if run.status in {"success", "unchanged"}:
        return run
    connection = session.get(DataConnection, run.data_connection_id)
    document = session.get(Document, run.document_id)
    if connection is None or document is None:
        return _fail_run(session, run, connection, "data_source_missing", "Data source or document was not found")
    project = session.get(Project, connection.project_id)
    if project is None or project.status != "active":
        return _fail_run(session, run, connection, "project_archived", "Archived projects cannot synchronize data sources")
    now = datetime.now(UTC)
    run.status = "running"
    run.started_at = run.started_at or now
    run.error_code = None
    run.error_summary = None
    connection.last_sync_status = "running"
    connection.updated_at = now
    session.flush()
    snapshot = _CompensatingSnapshotStorage(snapshot_storage or S3ObjectStorage(settings))
    try:
        with session.begin_nested():
            return _execute_data_source_sync_attempt(
                session=session,
                settings=settings,
                run=run,
                connection=connection,
                document=document,
                project=project,
                remote_storage=remote_storage,
                snapshot=snapshot,
            )
    except AppError as exc:
        if not snapshot.compensate():
            return _fail_run(session, run, connection, "data_sync_compensation_failed", "Data source synchronization failed and object-store cleanup requires operator reconciliation")
        return _fail_run(session, run, connection, exc.code, exc.message)
    except Exception:
        if not snapshot.compensate():
            return _fail_run(session, run, connection, "data_sync_compensation_failed", "Data source synchronization failed and object-store cleanup requires operator reconciliation")
        return _fail_run(session, run, connection, "internal_failure", "Data source synchronization failed")


def _execute_data_source_sync_attempt(
    *,
    session: Session,
    settings: Settings,
    run: DataSyncRun,
    connection: DataConnection,
    document: Document,
    project: Project,
    remote_storage: RemoteObjectStorage | None,
    snapshot: _CompensatingSnapshotStorage,
) -> DataSyncRun:
    session.refresh(project)
    if project.status != "active":
        raise AppError("project_archived", "Archived projects cannot synchronize data sources", status_code=409)
    remote = _fetch_remote_object(settings=settings, connection=connection, remote_storage=remote_storage)
    original_name = _remote_file_name(connection)
    validate_file_payload(UploadedFilePayload(filename=original_name, content_type=remote.content_type, content=remote.body), settings)
    validate_source_extension(original_name, http_response=connection.service_type == "HTTP_API")
    identity = build_storage_identity(remote.body, original_name)
    latest = _latest_version(session, document.id)
    if latest is not None and latest.content_sha256 == identity.content_sha256:
        run.status = "unchanged"
        run.completed_at = datetime.now(UTC)
        run.content_fingerprint = identity.content_sha256
        run.document_version_id = latest.id
        run.remote_metadata = _remote_metadata(connection, remote, identity.content_sha256)
        connection.last_sync_status = "unchanged"
        connection.last_synced_at = run.completed_at
        connection.updated_at = run.completed_at
        add_audit(session, actor_user_id=None, action="data_source.sync.unchanged", resource_type="data_sync_run", resource_id=run.id, result="success", request_id=None, summary={"data_connection_id": str(connection.id), "document_id": str(document.id), "fingerprint": identity.content_sha256})
        return run
    version = latest if latest is not None and not latest.content_sha256 else None
    if version is None:
        version = _new_version(session, project, document, latest, original_name)
        session.add(version)
        session.flush()
    _store_version_source(settings=settings, storage=snapshot, project=project, document=document, version=version, original_name=original_name, remote=remote, identity=identity)
    queued_at = datetime.now(UTC)
    version.status = "ready_for_extraction"
    version.chunk_strategy = {**(version.chunk_strategy or {}), "data_sync_run_id": str(run.id), "previous_source_version_id": str(latest.id) if latest else None}
    version.updated_at = queued_at
    document.updated_at = queued_at
    queue_document_extraction(session, project=project, document=document, version=version)
    run.status = "success"
    run.completed_at = queued_at
    run.content_fingerprint = identity.content_sha256
    run.document_version_id = version.id
    run.remote_metadata = _remote_metadata(connection, remote, identity.content_sha256)
    connection.last_sync_status = "success"
    connection.last_synced_at = queued_at
    connection.updated_at = queued_at
    create_source_reference_events(session, source_document=document, event_type="source_updated", old_source_version_id=latest.id if latest else None, new_source_version_id=version.id)
    add_audit(session, actor_user_id=None, action="data_source.sync.success", resource_type="data_sync_run", resource_id=run.id, result="success", request_id=None, summary={"data_connection_id": str(connection.id), "document_id": str(document.id), "document_version_id": str(version.id), "fingerprint": identity.content_sha256})
    return run


def has_active_sync_run(session: Session, connection_id: UUID) -> bool:
    return bool(session.scalar(select(DataSyncRun.id).where(DataSyncRun.data_connection_id == connection_id, DataSyncRun.status.in_(RUNNING_SYNC_STATUSES)).limit(1)))


def queue_due_scheduled_data_syncs(session: Session, *, now: datetime | None = None) -> list[DataSyncRun]:
    current = now or datetime.now(UTC)
    queued: list[DataSyncRun] = []
    connections = list(session.scalars(select(DataConnection).join(Project, Project.id == DataConnection.project_id).where(DataConnection.enabled.is_(True), DataConnection.schedule_mode == "cron", Project.status == "active")))
    for connection in connections:
        try:
            next_due = connection.next_run_at or compute_next_run_at(connection.cron_expression or "", connection.timezone, after=current - timedelta(minutes=1))
        except AppError as exc:
            connection.last_sync_status = "failed"
            connection.updated_at = current
            add_audit(session, actor_user_id=None, action="data_source.schedule.failed", resource_type="data_connection", resource_id=connection.id, result="failed", request_id=None, summary={"error_code": exc.code})
            continue
        if next_due > current:
            connection.next_run_at = next_due
            continue
        try:
            connection.next_run_at = compute_next_run_at(connection.cron_expression or "", connection.timezone, after=current)
        except AppError as exc:
            connection.last_sync_status = "failed"
            connection.updated_at = current
            add_audit(session, actor_user_id=None, action="data_source.schedule.failed", resource_type="data_connection", resource_id=connection.id, result="failed", request_id=None, summary={"error_code": exc.code})
            continue
        connection.updated_at = current
        if has_active_sync_run(session, connection.id):
            continue
        document = _document_for_connection(session, connection)
        if document is None:
            connection.last_sync_status = "failed"
            add_audit(session, actor_user_id=None, action="data_source.schedule.failed", resource_type="data_connection", resource_id=connection.id, result="failed", request_id=None, summary={"error_code": "data_source_document_not_found"})
            continue
        project = session.get(Project, connection.project_id)
        if project is None or project.status != "active":
            continue
        run = DataSyncRun(id=uuid4(), data_connection_id=connection.id, document_id=document.id, project_generation=project.work_generation, trigger_type="scheduled", status="queued", remote_metadata=connection.source_identity, retry_count=0, created_at=current)
        connection.last_sync_status = "queued"
        session.add(run)
        session.flush()
        session.add(OutboxEvent(topic="data_source.sync.requested", aggregate_type="data_sync_run", aggregate_id=run.id, project_id=project.id, project_generation=project.work_generation, payload={"run_id": str(run.id), "project_id": str(project.id), "project_generation": project.work_generation, "data_connection_id": str(connection.id)}, status="pending", attempts=0, available_at=current, created_at=current))
        add_audit(session, actor_user_id=None, action="data_source.schedule.queue", resource_type="data_connection", resource_id=connection.id, result="success", request_id=None, summary={"sync_run_id": str(run.id), "document_id": str(document.id), "next_run_at": connection.next_run_at.isoformat()})
        queued.append(run)
    return queued


def compute_next_run_at(expression: str, timezone: str, *, after: datetime | None = None) -> datetime:
    fields = expression.split()
    if len(fields) != 5:
        raise AppError("data_source_cron_invalid", "Data source schedule must be a five-field cron expression", status_code=422)
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise AppError("data_source_timezone_invalid", "Data source timezone is invalid", status_code=422) from exc
    start = after or datetime.now(UTC)
    local = start.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    minute_set = _parse_cron_field(fields[0], 0, 59)
    hour_set = _parse_cron_field(fields[1], 0, 23)
    day_set = _parse_cron_field(fields[2], 1, 31)
    month_set = _parse_cron_field(fields[3], 1, 12)
    weekday_set = _parse_cron_field(fields[4], 0, 6, sunday_seven=True)
    for offset in range(0, 366 * 24 * 60):
        candidate = local + timedelta(minutes=offset)
        cron_weekday = (candidate.weekday() + 1) % 7
        if (
            candidate.minute in minute_set
            and candidate.hour in hour_set
            and candidate.day in day_set
            and candidate.month in month_set
            and cron_weekday in weekday_set
        ):
            return candidate.astimezone(UTC)
    raise AppError("data_source_cron_no_next_run", "Data source schedule has no next run within one year", status_code=422)


def _parse_cron_field(value: str, minimum: int, maximum: int, *, sunday_seven: bool = False) -> set[int]:
    result: set[int] = set()
    if not value:
        raise AppError("data_source_cron_invalid", "Data source schedule is invalid", status_code=422)
    for part in value.split(","):
        try:
            if part == "*":
                result.update(range(minimum, maximum + 1))
                continue
            if part.startswith("*/"):
                step = int(part[2:])
                if step <= 0:
                    raise AppError("data_source_cron_invalid", "Data source schedule is invalid", status_code=422)
                result.update(range(minimum, maximum + 1, step))
                continue
            if "-" in part:
                start_text, end_text = part.split("-", 1)
                start, end = int(start_text), int(end_text)
                if sunday_seven:
                    start = 0 if start == 7 else start
                    end = 0 if end == 7 else end
                if start > end:
                    raise AppError("data_source_cron_invalid", "Data source schedule is invalid", status_code=422)
                result.update(range(start, end + 1))
                continue
            item = int(part)
        except ValueError as exc:
            raise AppError("data_source_cron_invalid", "Data source schedule is invalid", status_code=422) from exc
        if sunday_seven and item == 7:
            item = 0
        result.add(item)
    if any(item < minimum or item > maximum for item in result):
        raise AppError("data_source_cron_invalid", "Data source schedule is invalid", status_code=422)
    return result


def _document_for_connection(session: Session, connection: DataConnection) -> Document | None:
    linked_document_id = connection.source_identity.get("document_id") if isinstance(connection.source_identity, dict) else None
    document = session.get(Document, UUID(str(linked_document_id))) if linked_document_id else None
    if document is not None and document.project_id == connection.project_id:
        return document
    return None


def _fetch_remote_object(*, settings: Settings, connection: DataConnection, remote_storage: RemoteObjectStorage | None):
    if remote_storage is not None:
        return _fetch_injected_remote_object(settings=settings, connection=connection, remote_storage=remote_storage)
    metadata = connection.connection_metadata or {}
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if connection.service_type == "S3":
        bucket = str(metadata.get("bucket") or "").strip()
        if not bucket:
            raise AppError("s3_connection_bucket_required", "S3 connection bucket is required", status_code=422)
        return _s3_connection_storage(settings, connection).get_object(bucket=bucket, key=_remote_object_key(connection), max_bytes=max_bytes)
    if connection.service_type in {"FTP", "FTPS", "SFTP"}:
        credential = _decrypted_credential(settings, connection)
        common = {
            "host": str(metadata.get("host") or ""),
            "port": int(metadata.get("port") or (21 if connection.service_type == "FTP" else 22)),
            "username": str(metadata.get("username") or ""),
            "credential": credential,
            "remote_path": str((connection.source_identity or {}).get("remote_path") or ""),
            "file_name": _remote_file_name(connection),
            "timeout_seconds": int(metadata.get("timeout_seconds") or 30),
            "max_bytes": max_bytes,
        }
        if connection.service_type == "FTP":
            return FTPRemoteSourceClient().get_object(**common)
        if connection.service_type == "FTPS":
            return FTPSRemoteSourceClient().get_object(**common)
        return SFTPRemoteSourceClient().get_object(**common, verify_host_key=bool(metadata.get("verify_host_key", True)), known_hosts_path=settings.sftp_known_hosts_path)
    if connection.service_type == "HTTP_API":
        return HTTPRemoteSourceClient().get_object(
            url=str((connection.source_identity or {}).get("url") or ""),
            headers=_http_headers(settings, connection),
            timeout_seconds=int(metadata.get("timeout_seconds") or 30),
            verify_tls=bool(metadata.get("verify_tls", True)),
            max_bytes=int(metadata.get("max_bytes") or max_bytes),
            allowed_hosts=settings.http_source_allowed_hostnames,
            allowed_networks=settings.http_source_allowed_networks,
        )
    raise AppError("unsupported_protocol", "This protocol is not supported by the current sync worker", status_code=422)


def _fetch_injected_remote_object(*, settings: Settings, connection: DataConnection, remote_storage: RemoteObjectStorage):
    metadata = connection.connection_metadata or {}
    if connection.service_type == "S3":
        bucket = str(metadata.get("bucket") or "").strip()
        if not bucket:
            raise AppError("s3_connection_bucket_required", "S3 connection bucket is required", status_code=422)
        key = _remote_object_key(connection)
    else:
        bucket = str(metadata.get("bucket") or connection.service_type.lower())
        key = _remote_object_key(connection)
    return remote_storage.get_object(bucket=bucket, key=key, max_bytes=settings.max_upload_size_mb * 1024 * 1024)


def _decrypted_credential(settings: Settings, connection: DataConnection) -> str:
    if connection.credential_secret_ref:
        return resolve_runtime_secret(settings, connection.credential_secret_ref)
    if connection.credential_encrypted:
        if settings.app_env == "production":
            raise AppError("legacy_data_source_credential_forbidden", "Legacy data-source credentials are not permitted in production", status_code=503)
        cipher = EnvelopeCipher(settings.encryption_key_bytes)
        try:
            return cipher.decrypt(connection.credential_encrypted, context=f"data-source-connection:{connection.id}")
        except AppError:
            return cipher.decrypt(connection.credential_encrypted, context=f"data-source:{connection.project_id}:{connection.name}")
    raise AppError("data_source_credential_required", "Data source credential is not configured", status_code=503)


def _s3_connection_storage(settings: Settings, connection: DataConnection) -> S3ObjectStorage:
    metadata = connection.connection_metadata or {}
    endpoint = str(metadata.get("endpoint_url") or "").strip()
    region = str(metadata.get("region") or "").strip()
    if not endpoint or not region:
        raise AppError("s3_connection_config_required", "S3 connection endpoint and region are required", status_code=422)
    raw = _connection_credential_json(settings, connection)
    access_key = str(raw.get("access_key") or "").strip()
    secret_key = str(raw.get("secret_key") or "").strip()
    if not access_key or not secret_key:
        raise AppError("s3_connection_credential_invalid", "S3 connection credential is incomplete", status_code=422)
    verify_value = metadata.get("verify_tls", True)
    verify_tls = verify_value if isinstance(verify_value, bool) else str(verify_value).strip().lower() not in {"0", "false", "no", "off"}
    return S3ObjectStorage(S3ClientConfig(
        endpoint_url=endpoint,
        region=region,
        access_key=access_key,
        secret_key=secret_key,
        verify_tls=verify_tls,
        session_token=str(raw.get("session_token") or "").strip() or None,
    ))


def _connection_credential_json(settings: Settings, connection: DataConnection) -> dict[str, object]:
    if connection.credential_secret_ref:
        plaintext = resolve_runtime_secret(settings, connection.credential_secret_ref)
    elif connection.credential_encrypted:
        if settings.app_env == "production":
            raise AppError("legacy_data_source_credential_forbidden", "Legacy data-source credentials are not permitted in production", status_code=503)
        cipher = EnvelopeCipher(settings.encryption_key_bytes)
        try:
            plaintext = cipher.decrypt(connection.credential_encrypted, context=f"data-source-connection:{connection.id}")
        except AppError:
            plaintext = cipher.decrypt(connection.credential_encrypted, context=f"data-source:{connection.project_id}:{connection.name}")
    else:
        raise AppError("data_source_credential_required", "Data source credential is not configured", status_code=503)
    try:
        payload = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise AppError("s3_connection_credential_invalid", "S3 connection credential must be a JSON object", status_code=422) from exc
    if not isinstance(payload, dict):
        raise AppError("s3_connection_credential_invalid", "S3 connection credential must be a JSON object", status_code=422)
    return payload

def _http_headers(settings: Settings, connection: DataConnection) -> dict[str, str]:
    metadata = connection.connection_metadata or {}
    configured_headers = metadata.get("headers") if isinstance(metadata.get("headers"), dict) else {}
    headers = {str(key): str(value) for key, value in configured_headers.items() if _safe_header_name(str(key)) and not _sensitive_header_name(str(key))}
    auth_mode = str(metadata.get("auth_mode") or "none")
    if auth_mode == "bearer":
        headers["authorization"] = f"Bearer {_decrypted_credential(settings, connection)}"
    elif auth_mode == "api_key_header":
        header_name = str(metadata.get("api_key_header_name") or "X-API-Key")
        if not _safe_header_name(header_name):
            raise AppError("http_source_header_invalid", "HTTP/API source header name is invalid", status_code=422)
        headers[header_name] = _decrypted_credential(settings, connection)
    return headers


def _safe_header_name(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "-_" for character in value)


def _sensitive_header_name(value: str) -> bool:
    lowered = value.lower().replace("_", "-")
    return lowered in {"authorization", "cookie", "set-cookie"} or any(part in lowered for part in ("api-key", "token", "secret", "password", "credential"))


def _remote_object_key(connection: DataConnection) -> str:
    identity = connection.source_identity or {}
    if connection.service_type == "HTTP_API":
        return str(identity.get("url") or "")
    remote_path = str(identity.get("remote_path") or "").strip("/")
    file_name = sanitize_original_filename(str(identity.get("file_name") or connection.name))
    if remote_path:
        return str(PurePosixPath(remote_path) / file_name)
    return file_name


def _remote_file_name(connection: DataConnection) -> str:
    identity = connection.source_identity or {}
    return sanitize_original_filename(str(identity.get("file_name") or connection.name))


def _latest_version(session: Session, document_id: UUID) -> DocumentVersion | None:
    return session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at)).limit(1))


def _new_version(session: Session, project: Project, document: Document, latest: DocumentVersion | None, original_name: str) -> DocumentVersion:
    now = datetime.now(UTC)
    major = (latest.version_major if latest else 0) + 1
    return DocumentVersion(
        id=uuid4(),
        project_id=project.id,
        document_id=document.id,
        version_major=major,
        extraction_revision=0,
        version_label=f"v{major}.0",
        status="draft",
        original_file_name=original_name,
        canonical_extension=None,
        chunk_strategy={"source": "data_service", "service_type": document.source_type},
        embedding_model_id=project.embedding_model_id,
        llm_model_id=project.llm_model_id,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )


def _store_version_source(*, settings: Settings, storage: ObjectStorage, project: Project, document: Document, version: DocumentVersion, original_name: str, remote, identity) -> None:
    storage_key = build_storage_key(str(project.id), str(document.id), str(version.id), identity)
    stored = storage.put_object(bucket=settings.s3_bucket, key=storage_key, body=remote.body, content_type=remote.content_type)
    version.original_file_name = original_name
    version.canonical_extension = identity.canonical_extension
    version.mime_type = remote.content_type
    version.file_size = len(remote.body)
    version.content_sha256 = identity.content_sha256
    version.storage_name_salt = identity.storage_name_salt
    version.storage_name_hash = identity.storage_name_hash
    version.storage_bucket = stored.bucket
    version.storage_key = stored.key
    version.storage_etag = stored.etag
    version.uploaded_at = datetime.now(UTC)
    version.original_snapshot_uri = f"s3://{stored.bucket}/{stored.key}"
    version.chunk_strategy = {**(version.chunk_strategy or {}), "source": "data_service", "sync_adapter": document.source_type.replace("_service", "")}


def _remote_metadata(connection: DataConnection, remote, fingerprint: str) -> dict[str, object]:
    return {
        "service_type": connection.service_type,
        "remote_uri": (connection.source_identity or {}).get("remote_uri"),
        "remote_key": _remote_object_key(connection),
        "etag": remote.etag,
        "content_type": remote.content_type,
        "content_length": remote.content_length if remote.content_length is not None else len(remote.body),
        "content_fingerprint": fingerprint,
    }


def _fail_run(session: Session, run: DataSyncRun, connection: DataConnection | None, code: str, summary: str) -> DataSyncRun:
    now = datetime.now(UTC)
    run.status = "failed"
    run.completed_at = now
    run.error_code = code
    run.error_summary = summary
    run.retry_count = (run.retry_count or 0) + 1
    if connection is not None:
        connection.last_sync_status = "failed"
        connection.updated_at = now
    add_audit(session, actor_user_id=None, action="data_source.sync.failed", resource_type="data_sync_run", resource_id=run.id, result="failed", request_id=None, summary={"data_connection_id": str(run.data_connection_id), "document_id": str(run.document_id), "error_code": code})
    return run
