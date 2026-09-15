from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.documents import _project_document
from app.domain.project_access import get_scoped_project as _get_scoped_project
from app.api.schemas import DataSourceConnectionPayload, DataSourceConnectionTestResponse, DataSourceCreateResponse, DataSourceResponse, DataSyncRunResponse
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import DataConnection, DataSyncRun, Document, DocumentVersion, OutboxEvent, Project
from app.db.session import get_db
from app.domain.data_sync import compute_next_run_at, has_active_sync_run
from app.domain.connection_evidence import data_connection_fingerprint
from app.domain.connection_probes import probe_data_source_candidate, probe_stored_data_connection
from app.domain.document_imports import _next_document_code, _title_from_filename
from app.domain.uploads import canonical_extension, sanitize_original_filename, validate_source_extension
from app.security.context import IdentityContext, get_identity_context
from app.security.project_roles import PROJECT_EDITOR_ROLES, require_project_role
from app.services.audit import add_audit
from app.security.secrets import validate_runtime_secret_reference


router = APIRouter(prefix="/projects/{project_id}/data-sources", tags=["data-sources"])


def _lock_enqueue_project(session: Session, project_id: UUID) -> Project:
    """Fence new work against archival after scope/role authorization.

    Acquire the parent first and refresh cached state after any lock wait. The
    lock is held through the run/outbox commit, including duplicate-run checks.
    """
    project = session.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    if project.status != "active":
        raise AppError("project_archived", "Archived projects cannot synchronize data sources", status_code=409)
    return project


@router.post("/validate-connection", response_model=DataSourceConnectionTestResponse)
def validate_data_source_connection(
    project_id: UUID,
    payload: DataSourceConnectionPayload,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DataSourceConnectionTestResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required for data source configuration")
    _validate_data_source_payload(payload, settings=None)
    return DataSourceConnectionTestResponse(status="configuration_valid", detail_code="configuration_valid", message="Data source configuration is valid; no network connection was attempted.", credential_configured=bool(payload.credential or payload.credential_secret_ref))


@router.post("/test-connection", response_model=DataSourceConnectionTestResponse)
def test_data_source_connection(
    project_id: UUID,
    payload: DataSourceConnectionPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DataSourceConnectionTestResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required for data source configuration")
    _validate_data_source_payload(payload, settings=request.app.state.settings)
    try:
        probe = probe_data_source_candidate(request.app.state.settings, payload)
    except AppError as exc:
        add_audit(session, actor_user_id=context.user_id, action="data_source.connection_test", resource_type="project", resource_id=project.id, result="failed", request_id=request.state.request_id, summary={**_safe_payload_summary(payload), "detail_code": exc.code})
        session.commit()
        raise
    tested_at = datetime.now(UTC)
    result = DataSourceConnectionTestResponse(status="success", detail_code=probe.detail_code, message="Live data source connection test succeeded.", credential_configured=bool(payload.credential or payload.credential_secret_ref), fingerprint=probe.fingerprint, latency_ms=probe.latency_ms, tested_at=tested_at)
    add_audit(session, actor_user_id=context.user_id, action="data_source.connection_test", resource_type="project", resource_id=project.id, result="success", request_id=request.state.request_id, summary={**_safe_payload_summary(payload), "detail_code": probe.detail_code, "fingerprint": probe.fingerprint[:12], "latency_ms": probe.latency_ms})
    session.commit()
    return result


@router.post("/{data_source_id}/test", response_model=DataSourceConnectionTestResponse)
def test_saved_data_source_connection(
    project_id: UUID,
    data_source_id: UUID,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DataSourceConnectionTestResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required for data source testing")
    connection = session.get(DataConnection, data_source_id)
    if connection is None or connection.project_id != project.id:
        raise AppError("data_source_not_found", "Data source was not found", status_code=404)
    fingerprint = data_connection_fingerprint(connection)
    started = datetime.now(UTC)
    try:
        probe = probe_stored_data_connection(request.app.state.settings, connection)
    except AppError as exc:
        connection.last_test_status = "failed"
        connection.last_tested_at = datetime.now(UTC)
        connection.last_test_fingerprint = fingerprint
        connection.last_test_latency_ms = max(0, int((connection.last_tested_at - started).total_seconds() * 1000))
        connection.last_test_detail_code = exc.code
        connection.last_test_actor_id = context.user_id
        add_audit(session, actor_user_id=context.user_id, action="data_source.connection_test", resource_type="data_connection", resource_id=connection.id, result="failed", request_id=request.state.request_id, summary={"detail_code": exc.code, "fingerprint": fingerprint[:12], "latency_ms": connection.last_test_latency_ms})
        session.commit()
        raise
    connection.last_test_status = "success"
    connection.last_tested_at = datetime.now(UTC)
    connection.last_test_fingerprint = probe.fingerprint
    connection.last_test_latency_ms = probe.latency_ms
    connection.last_test_detail_code = probe.detail_code
    connection.last_test_actor_id = context.user_id
    add_audit(session, actor_user_id=context.user_id, action="data_source.connection_test", resource_type="data_connection", resource_id=connection.id, result="success", request_id=request.state.request_id, summary={"detail_code": probe.detail_code, "fingerprint": probe.fingerprint[:12], "latency_ms": probe.latency_ms})
    session.commit()
    return DataSourceConnectionTestResponse(status="success", detail_code=probe.detail_code, message="Live data source connection test succeeded.", credential_configured=bool(connection.credential_encrypted or connection.credential_secret_ref), fingerprint=probe.fingerprint, latency_ms=probe.latency_ms, tested_at=connection.last_tested_at)


@router.post("", response_model=DataSourceCreateResponse, status_code=201)
def create_data_source(
    project_id: UUID,
    payload: DataSourceConnectionPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DataSourceCreateResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required for data source creation")
    _validate_data_source_payload(payload, settings=request.app.state.settings)
    project = _lock_enqueue_project(session, project.id)
    now = datetime.now(UTC)
    document_id = uuid4()
    version_id = uuid4()
    connection_id = uuid4()
    remote_uri = _remote_uri(payload)
    credential_plaintext = _credential_plaintext(payload) if request.app.state.settings.app_env != "production" else None
    encrypted = EnvelopeCipher(request.app.state.settings.encryption_key_bytes).encrypt(credential_plaintext, context=f"data-source-connection:{connection_id}") if credential_plaintext else None
    connection = DataConnection(
        id=connection_id,
        project_id=project.id,
        service_type=payload.service_type,
        name=payload.name,
        connection_metadata=_connection_metadata(payload),
        credential_encrypted=encrypted,
        credential_secret_ref=payload.credential_secret_ref,
        source_identity=_source_identity(payload, remote_uri, document_id),
        schedule_mode=payload.schedule_mode,
        cron_expression=payload.cron_expression if payload.schedule_mode == "cron" else None,
        timezone=payload.timezone,
        enabled=True,
        last_sync_status="queued",
        next_run_at=compute_next_run_at(payload.cron_expression or "", payload.timezone, after=now) if payload.schedule_mode == "cron" else None,
        created_by=context.user_id,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    document = Document(
        id=document_id,
        project_id=project.id,
        document_code=_next_document_code(session, project.id),
        title=_title_from_filename(payload.file_name),
        source_type=f"{payload.service_type.lower()}_service",
        status="inactive",
        is_deleted=False,
        created_by=context.user_id,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id=version_id,
        project_id=project.id,
        document_id=document.id,
        version_major=1,
        extraction_revision=0,
        version_label="v1.0",
        status="draft",
        original_file_name=sanitize_original_filename(payload.file_name),
        canonical_extension=canonical_extension(payload.file_name),
        original_snapshot_uri=remote_uri,
        chunk_strategy={"source": "data_service", "service_type": payload.service_type},
        embedding_model_id=project.embedding_model_id,
        llm_model_id=project.llm_model_id,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    sync_run = DataSyncRun(
        id=uuid4(),
        data_connection_id=connection.id,
        document_id=document.id,
        project_generation=project.work_generation,
        trigger_type="initial",
        status="queued",
        remote_metadata={"service_type": payload.service_type, "remote_uri": remote_uri, "schedule_mode": payload.schedule_mode},
        document_version_id=version.id,
        retry_count=0,
        created_at=now,
    )
    session.add_all([connection, document])
    session.flush()
    session.add(version)
    session.flush()
    session.add(sync_run)
    session.add(OutboxEvent(topic="data_source.sync.requested", aggregate_type="data_sync_run", aggregate_id=sync_run.id, project_id=project.id, project_generation=project.work_generation, payload={"run_id": str(sync_run.id), "project_id": str(project.id), "project_generation": project.work_generation, "data_connection_id": str(connection.id)}, status="pending", attempts=0, available_at=now, created_at=now))
    add_audit(session, actor_user_id=context.user_id, action="data_source.create", resource_type="data_connection", resource_id=connection.id, result="success", request_id=request.state.request_id, summary={**_safe_payload_summary(payload), "document_id": str(document.id), "sync_run_id": str(sync_run.id)})
    session.commit()
    session.refresh(connection)
    session.refresh(document)
    session.refresh(version)
    session.refresh(sync_run)
    return DataSourceCreateResponse(
        data_source=_data_source_response(connection),
        document=_project_document(session, document, version, None, visible_project_ids=set(context.visible_project_ids)),
        sync_run=sync_run,
    )


@router.post("/{data_source_id}/sync", response_model=DataSyncRunResponse, status_code=202)
def queue_data_source_sync(
    project_id: UUID,
    data_source_id: UUID,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DataSyncRun:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project_id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required to sync data sources")
    project = _lock_enqueue_project(session, project.id)
    connection = session.get(DataConnection, data_source_id)
    if connection is None or connection.project_id != project_id:
        raise AppError("data_source_not_found", "Data source was not found", status_code=404)
    linked_document_id = connection.source_identity.get("document_id") if isinstance(connection.source_identity, dict) else None
    document = session.get(Document, UUID(str(linked_document_id))) if linked_document_id else None
    if document is not None and document.project_id != project_id:
        document = None
    if document is None:
        document = session.scalar(select(Document).where(Document.project_id == project_id, Document.source_type == f"{connection.service_type.lower()}_service").order_by(Document.created_at.desc()).limit(1))
    if document is None:
        raise AppError("data_source_document_not_found", "Data source document was not found", status_code=404)
    if has_active_sync_run(session, connection.id):
        raise AppError("data_source_sync_already_running", "A sync run is already queued or running for this data source", status_code=409)
    now = datetime.now(UTC)
    run = DataSyncRun(id=uuid4(), data_connection_id=connection.id, document_id=document.id, project_generation=project.work_generation, trigger_type="manual", status="queued", remote_metadata=connection.source_identity, retry_count=0, created_at=now)
    connection.last_sync_status = "queued"
    connection.updated_at = now
    session.add(run)
    session.add(OutboxEvent(topic="data_source.sync.requested", aggregate_type="data_sync_run", aggregate_id=run.id, project_id=project.id, project_generation=project.work_generation, payload={"run_id": str(run.id), "project_id": str(project_id), "project_generation": project.work_generation, "data_connection_id": str(connection.id)}, status="pending", attempts=0, available_at=now, created_at=now))
    add_audit(session, actor_user_id=context.user_id, action="data_source.sync.queue", resource_type="data_connection", resource_id=connection.id, result="success", request_id=request.state.request_id, summary={"sync_run_id": str(run.id), "document_id": str(document.id)})
    session.commit()
    session.refresh(run)
    return run


@router.get("/{data_source_id}/sync-runs", response_model=list[DataSyncRunResponse])
def list_data_source_sync_runs(
    project_id: UUID,
    data_source_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[DataSyncRun]:
    _project = _get_scoped_project(session, project_id, context)
    connection = session.get(DataConnection, data_source_id)
    if connection is None or connection.project_id != project_id:
        raise AppError("data_source_not_found", "Data source was not found", status_code=404)
    return list(session.scalars(select(DataSyncRun).where(DataSyncRun.data_connection_id == connection.id).order_by(DataSyncRun.created_at.desc()).limit(20)))


def _validate_data_source_payload(payload: DataSourceConnectionPayload, *, settings) -> None:
    if payload.service_type == "HTTP_API":
        _validate_http_source_payload(payload)
    else:
        if payload.service_type in {"FTP", "FTPS", "SFTP"} and not payload.host:
            raise AppError("data_source_host_required", "Remote file data source requires a host", status_code=422)
        if not payload.username:
            raise AppError("data_source_username_required", "Data source requires a username or access key", status_code=422)
    if payload.service_type == "S3" and not payload.bucket:
        raise AppError("data_source_bucket_required", "S3 data source requires a bucket", status_code=422)
    if payload.service_type == "S3" and (not payload.host or not payload.region):
        raise AppError("s3_connection_config_required", "S3 data source requires endpoint and region", status_code=422)
    if payload.service_type == "S3":
        s3_endpoint = urlparse(payload.host)
        if s3_endpoint.scheme not in {"http", "https"} or not s3_endpoint.hostname or s3_endpoint.username or s3_endpoint.password or s3_endpoint.query:
            raise AppError("s3_connection_endpoint_invalid", "S3 endpoint must be an HTTP(S) URL without credentials or query parameters", status_code=422)
    if payload.service_type == "SFTP" and not payload.verify_host_key:
        raise AppError("sftp_host_key_verification_required", "SFTP host-key verification is required", status_code=422)
    credential_required = payload.service_type != "HTTP_API" or payload.auth_mode in {"bearer", "api_key_header"}
    if credential_required and not (payload.credential or payload.credential_secret_ref):
        raise AppError("data_source_credential_required", "Data source requires a credential or secret reference", status_code=422)
    if payload.credential and payload.credential_secret_ref:
        raise AppError("data_source_credential_ambiguous", "Provide a mounted Secret reference or a credential, not both", status_code=422)
    if settings is not None and settings.app_env == "production" and payload.credential:
        raise AppError(
            "plaintext_data_source_credential_forbidden",
            "Production data-source credentials must use a mounted Secret reference",
            status_code=422,
        )
    if payload.credential_secret_ref:
        if settings is None:
            raise AppError("data_source_secret_ref_invalid", "Runtime Secret settings are unavailable", status_code=503)
        validate_runtime_secret_reference(settings, payload.credential_secret_ref)
    if payload.schedule_mode == "cron" and not _valid_five_field_cron(payload.cron_expression or ""):
        raise AppError("data_source_cron_invalid", "Data source schedule must be a five-field cron expression", status_code=422)
    try:
        sanitize_original_filename(payload.file_name)
        validate_source_extension(payload.file_name, http_response=payload.service_type == "HTTP_API")
    except ValueError as exc:
        raise AppError("data_source_file_invalid", "Data source file name or extension is invalid", status_code=422) from exc


def _valid_five_field_cron(value: str) -> bool:
    return len(value.split()) == 5 and all(re.match(r"^[\d*/,\-]+$", part) for part in value.split())


def _validate_http_source_payload(payload: DataSourceConnectionPayload) -> None:
    parsed = urlparse(payload.url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AppError("http_source_url_invalid", "HTTP/API source URL is invalid", status_code=422)
    if payload.auth_mode == "api_key_header" and not payload.api_key_header_name:
        raise AppError("http_source_header_required", "HTTP/API source API key header name is required", status_code=422)
    for header_name in payload.headers:
        lowered = header_name.lower().replace("_", "-")
        if lowered in {"authorization", "cookie", "set-cookie"} or any(part in lowered for part in ("api-key", "token", "secret", "password", "credential")) or not re.match(r"^[A-Za-z0-9_-]+$", header_name):
            raise AppError("http_source_header_invalid", "HTTP/API source header is invalid", status_code=422)
        if "\r" in payload.headers[header_name] or "\n" in payload.headers[header_name]:
            raise AppError("http_source_header_invalid", "HTTP/API source header is invalid", status_code=422)


def _remote_uri(payload: DataSourceConnectionPayload) -> str:
    if payload.service_type == "HTTP_API":
        return payload.url or ""
    path = str(PurePosixPath(payload.remote_path.strip("/") or ".") / sanitize_original_filename(payload.file_name))
    if payload.service_type == "S3":
        return f"s3://{payload.bucket}/{path}"
    scheme = payload.service_type.lower()
    return f"{scheme}://{payload.host}:{payload.port}/{path}"


def _connection_metadata(payload: DataSourceConnectionPayload) -> dict[str, object]:
    metadata = {
        "host": payload.host,
        "port": payload.port,
        "username": payload.username,
        "bucket": payload.bucket,
        "region": payload.region,
        "verify_tls": payload.verify_tls,
        "verify_host_key": payload.verify_host_key,
        "credential_configured": bool(payload.credential or payload.credential_secret_ref),
    }
    if payload.service_type == "S3":
        metadata["endpoint_url"] = payload.host
    if payload.service_type == "HTTP_API":
        metadata.update({
            "headers": payload.headers,
            "auth_mode": payload.auth_mode,
            "api_key_header_name": payload.api_key_header_name,
            "timeout_seconds": payload.timeout_seconds,
            "max_bytes": payload.max_bytes,
        })
    return metadata


def _source_identity(payload: DataSourceConnectionPayload, remote_uri: str, document_id: UUID) -> dict[str, object]:
    identity: dict[str, object] = {"remote_path": payload.remote_path, "file_name": payload.file_name, "remote_uri": remote_uri, "document_id": str(document_id)}
    if payload.service_type == "HTTP_API":
        identity["url"] = payload.url
    return identity


def _safe_payload_summary(payload: DataSourceConnectionPayload) -> dict[str, object]:
    return {
        "service_type": payload.service_type,
        "host_configured": bool(payload.host),
        "port": payload.port,
        "bucket_configured": bool(payload.bucket),
        "url_configured": bool(payload.url) if payload.service_type == "HTTP_API" else None,
        "auth_mode": payload.auth_mode if payload.service_type == "HTTP_API" else None,
        "headers_configured": len(payload.headers) if payload.service_type == "HTTP_API" else None,
        "remote_path_configured": bool(payload.remote_path),
        "file_extension": canonical_extension(payload.file_name),
        "schedule_mode": payload.schedule_mode,
        "cron_expression": payload.cron_expression if payload.schedule_mode == "cron" else None,
        "timezone": payload.timezone,
        "credential_configured": bool(payload.credential or payload.credential_secret_ref),
    }


def _credential_plaintext(payload: DataSourceConnectionPayload) -> str | None:
    if not payload.credential:
        return None
    if payload.service_type != "S3":
        return payload.credential
    stripped = payload.credential.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise AppError("s3_connection_credential_invalid", "S3 credential JSON is invalid", status_code=422) from exc
        if not isinstance(parsed, dict):
            raise AppError("s3_connection_credential_invalid", "S3 credential must be an object", status_code=422)
        return json.dumps(parsed, separators=(",", ":"), sort_keys=True)
    return json.dumps({"access_key": payload.username, "secret_key": payload.credential}, separators=(",", ":"), sort_keys=True)


def _data_source_response(connection: DataConnection) -> DataSourceResponse:
    return DataSourceResponse(
        id=connection.id,
        project_id=connection.project_id,
        service_type=connection.service_type,
        name=connection.name,
        connection_metadata=connection.connection_metadata,
        source_identity=connection.source_identity,
        schedule_mode=connection.schedule_mode,
        cron_expression=connection.cron_expression,
        timezone=connection.timezone,
        enabled=connection.enabled,
        last_sync_status=connection.last_sync_status,
        last_synced_at=connection.last_synced_at,
        next_run_at=connection.next_run_at,
        lock_version=connection.lock_version,
        created_by=connection.created_by,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
        credential_configured=bool(connection.credential_encrypted or connection.credential_secret_ref),
        last_test_status=connection.last_test_status,
        last_tested_at=connection.last_tested_at,
        last_test_fingerprint=connection.last_test_fingerprint,
        last_test_latency_ms=connection.last_test_latency_ms,
        last_test_detail_code=connection.last_test_detail_code,
        last_test_actor_id=connection.last_test_actor_id,
    )
