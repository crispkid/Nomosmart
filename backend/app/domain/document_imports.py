from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AIModel, Document, DocumentVersion, OutboxEvent, PipelineRun, Project
from app.domain.extraction_pipeline import ensure_no_active_pipeline, initialize_pipeline_steps
from app.domain.docx_security import inspect_docx_package
from app.domain.uploads import build_storage_identity, build_storage_key, sanitize_original_filename, validate_source_extension


MAX_TITLE_LENGTH = 500
@dataclass(frozen=True)
class UploadedFilePayload:
    filename: str
    content_type: str | None
    content: bytes


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    etag: str | None = None


class ObjectStorage:
    def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str | None) -> StoredObject:  # pragma: no cover - protocol
        raise NotImplementedError


def validate_file_payload(file: UploadedFilePayload, settings: Settings) -> tuple[str, str]:
    original_name = sanitize_original_filename(file.filename)
    if not file.content:
        raise AppError("empty_upload_file", "Uploaded file is empty", status_code=422)
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(file.content) > max_bytes:
        raise AppError("upload_too_large", f"Uploaded file exceeds {settings.max_upload_size_mb} MB", status_code=413)
    try:
        validate_source_extension(original_name)
        identity = build_storage_identity(file.content, original_name)
    except ValueError as exc:
        raise AppError("unsupported_upload_type", "Uploaded file type is not supported", status_code=422) from exc
    _validate_magic(file.content, identity.canonical_extension)
    return original_name, identity.canonical_extension


def _validate_magic(content: bytes, extension: str) -> None:
    if extension == ".pdf" and not content.startswith(b"%PDF"):
        raise AppError("invalid_file_signature", "PDF file signature is invalid", status_code=422)
    if extension == ".docx":
        inspect_docx_package(content, max_source_bytes=max(len(content), 1))
    if extension in {".txt", ".md"}:
        try:
            content[:8192].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AppError("invalid_file_signature", "Text file must be UTF-8 compatible", status_code=422) from exc


def resolve_ocr_model(session: Session, project: Project, requested_ocr_model_id: UUID | None) -> AIModel:
    if requested_ocr_model_id is not None:
        model = session.get(AIModel, requested_ocr_model_id)
        if model is None or not model.is_active or model.deleted_at is not None or model.model_type != "OCR":
            raise AppError("invalid_ocr_model", "An active OCR model is required", status_code=422)
        return _require_ocr_model_credential(model)
    if project.ocr_model_id is not None:
        model = session.get(AIModel, project.ocr_model_id)
        if model is not None and model.is_active and model.deleted_at is None and model.model_type == "OCR":
            return _require_ocr_model_credential(model)
    model = session.scalar(select(AIModel).where(AIModel.model_type == "OCR", AIModel.is_active.is_(True), AIModel.is_default.is_(True), AIModel.deleted_at.is_(None)))
    if model is None or model.deleted_at is not None:
        raise AppError("ocr_model_required", "A default OCR model is not configured", status_code=422)
    return _require_ocr_model_credential(model)


def _require_ocr_model_credential(model: AIModel) -> AIModel:
    if model.provider.strip().lower() in {"openai", "gemini", "google", "claude", "anthropic"} and not model.api_key_configured:
        raise AppError(
            "ocr_model_credential_required",
            "The selected remote OCR model requires a configured credential",
            status_code=409,
        )
    return model


def ocr_execution_snapshot(model: AIModel, *, force_ocr: bool) -> dict[str, object]:
    config = model.config or {}
    return {
        "model_id": str(model.id),
        "config_version": model.config_version,
        "provider": model.provider,
        "endpoint_configured": bool(model.endpoint),
        "languages": config.get("languages") or config.get("language") or [],
        "timeout_seconds": config.get("timeout_seconds", config.get("timeout", 30)),
        "retry_count": config.get("retry_count", config.get("retries", 1)),
        "concurrency": config.get("concurrency", 1),
        "force_ocr": force_ocr,
        "force_ocr_confirmed": force_ocr,
    }


def source_text_snapshot(file: UploadedFilePayload, extension: str) -> str | None:
    if extension not in {".txt", ".md"}:
        return None
    try:
        text = file.content.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    return text or None


def create_uploaded_document(
    *,
    session: Session,
    settings: Settings,
    storage: ObjectStorage,
    project: Project,
    actor_user_id: UUID,
    file: UploadedFilePayload,
    requested_ocr_model_id: UUID | None,
    force_ocr: bool,
    start_extraction: bool,
) -> tuple[Document, DocumentVersion, PipelineRun | None]:
    original_name, _ = validate_file_payload(file, settings)
    identity = build_storage_identity(file.content, original_name)
    source_text = source_text_snapshot(file, identity.canonical_extension)
    ocr_model = resolve_ocr_model(session, project, requested_ocr_model_id)
    now = datetime.now(UTC)
    document_id = uuid4()
    version_id = uuid4()
    document = Document(
        id=document_id,
        project_id=project.id,
        document_code=_next_document_code(session, project.id),
        title=_title_from_filename(original_name),
        source_type="file_upload",
        status="inactive",
        is_deleted=False,
        created_by=actor_user_id,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    storage_key = build_storage_key(str(project.id), str(document_id), str(version_id), identity)
    stored = storage.put_object(bucket=settings.s3_bucket, key=storage_key, body=file.content, content_type=file.content_type)
    version = DocumentVersion(
        id=version_id,
        project_id=project.id,
        document_id=document_id,
        version_major=1,
        extraction_revision=0,
        version_label="v1.0",
        status="ready_for_extraction",
        original_file_name=original_name,
        canonical_extension=identity.canonical_extension,
        mime_type=file.content_type,
        file_size=len(file.content),
        content_sha256=identity.content_sha256,
        storage_name_salt=identity.storage_name_salt,
        storage_name_hash=identity.storage_name_hash,
        storage_bucket=stored.bucket,
        storage_key=stored.key,
        storage_etag=stored.etag,
        uploaded_at=now,
        original_snapshot_uri=f"s3://{stored.bucket}/{stored.key}",
        ocr_model_id=ocr_model.id,
        ocr_config_version=ocr_model.config_version,
        chunk_strategy={
            "source": "project_default",
            "force_ocr": force_ocr,
            "adapter_source": "live-only-required",
            "ocr_snapshot": ocr_execution_snapshot(ocr_model, force_ocr=force_ocr),
            **({"source_text": source_text, "source_text_origin": "uploaded_file_utf8"} if source_text else {}),
        },
        embedding_model_id=project.embedding_model_id,
        llm_model_id=project.llm_model_id,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add_all([document, version])
    session.flush()
    pipeline = None
    if start_extraction:
        pipeline = start_document_extraction(
            session=session,
            settings=settings,
            project=project,
            document=document,
            version=version,
            actor_user_id=actor_user_id,
            requested_ocr_model_id=requested_ocr_model_id,
            force_ocr=force_ocr,
        )
    return document, version, pipeline


def create_updated_file_version(
    *,
    session: Session,
    settings: Settings,
    storage: ObjectStorage,
    project: Project,
    document: Document,
    actor_user_id: UUID,
    file: UploadedFilePayload,
    requested_ocr_model_id: UUID | None,
    force_ocr: bool,
) -> tuple[DocumentVersion, PipelineRun | None, bool]:
    if document.project_id != project.id or document.source_type != "file_upload":
        raise AppError("document_update_not_supported", "Only uploaded files can be updated with a replacement file", status_code=409)
    original_name, _ = validate_file_payload(file, settings)
    identity = build_storage_identity(file.content, original_name)
    latest = _latest_document_version(session, document.id)
    if latest is not None and latest.content_sha256 == identity.content_sha256:
        return latest, None, True
    working = session.scalar(
        select(DocumentVersion.id)
        .where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.status.in_(("quarantine", "queued", "processing", "submission_ready", "pending_manager_review", "pending_owner_review", "approved")),
        )
        .limit(1)
    )
    if working is not None:
        raise AppError("document_update_working_version_exists", "A working version already exists for this document", status_code=409)
    source_text = source_text_snapshot(file, identity.canonical_extension)
    ocr_model = resolve_ocr_model(session, project, requested_ocr_model_id)
    now = datetime.now(UTC)
    major = (latest.version_major if latest else 0) + 1
    version_id = uuid4()
    storage_key = build_storage_key(str(project.id), str(document.id), str(version_id), identity)
    stored = storage.put_object(bucket=settings.s3_bucket, key=storage_key, body=file.content, content_type=file.content_type)
    version = DocumentVersion(
        id=version_id,
        project_id=project.id,
        document_id=document.id,
        version_major=major,
        extraction_revision=0,
        version_label=f"v{major}.0",
        status="ready_for_extraction",
        original_file_name=original_name,
        canonical_extension=identity.canonical_extension,
        mime_type=file.content_type,
        file_size=len(file.content),
        content_sha256=identity.content_sha256,
        storage_name_salt=identity.storage_name_salt,
        storage_name_hash=identity.storage_name_hash,
        storage_bucket=stored.bucket,
        storage_key=stored.key,
        storage_etag=stored.etag,
        uploaded_at=now,
        original_snapshot_uri=f"s3://{stored.bucket}/{stored.key}",
        ocr_model_id=ocr_model.id,
        ocr_config_version=ocr_model.config_version,
        chunk_strategy={
            "source": "file_update",
            "previous_version_id": str(latest.id) if latest else None,
            "force_ocr": force_ocr,
            "adapter_source": "live-only-required",
            "ocr_snapshot": ocr_execution_snapshot(ocr_model, force_ocr=force_ocr),
            **({"source_text": source_text, "source_text_origin": "uploaded_file_utf8"} if source_text else {}),
        },
        embedding_model_id=project.embedding_model_id,
        llm_model_id=project.llm_model_id,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    document.updated_at = now
    session.add(version)
    session.flush()
    pipeline = start_document_extraction(
        session=session,
        settings=settings,
        project=project,
        document=document,
        version=version,
        actor_user_id=actor_user_id,
        requested_ocr_model_id=requested_ocr_model_id,
        force_ocr=force_ocr,
    )
    return version, pipeline, False


def start_document_extraction(
    *,
    session: Session,
    settings: Settings,
    project: Project,
    document: Document,
    version: DocumentVersion,
    actor_user_id: UUID,
    requested_ocr_model_id: UUID | None,
    force_ocr: bool,
) -> PipelineRun:
    if (version.canonical_extension or "").lower() == ".doc":
        raise AppError("legacy_doc_reextraction_unsupported", "Legacy DOC files cannot be re-extracted; upload a DOCX replacement", status_code=422)
    if version.status not in {"draft", "ready_for_extraction"}:
        raise AppError("document_version_not_ready", "Document version is not ready for extraction", status_code=409)
    ensure_no_active_pipeline(session, version.id)
    ocr_model = resolve_ocr_model(session, project, requested_ocr_model_id)
    if not version.storage_bucket or not version.storage_key:
        raise AppError("document_source_unavailable", "Document source object is unavailable", status_code=409)
    now = datetime.now(UTC)
    version.status = "queued"
    version.ocr_model_id = ocr_model.id
    version.ocr_config_version = ocr_model.config_version
    version.chunk_strategy = {**(version.chunk_strategy or {}), "force_ocr": force_ocr, "adapter_source": "live-only-required", "ocr_snapshot": ocr_execution_snapshot(ocr_model, force_ocr=force_ocr)}
    version.updated_at = now
    pipeline = PipelineRun(
        id=uuid4(),
        project_id=project.id,
        document_id=document.id,
        document_version_id=version.id,
        project_generation=project.work_generation,
        run_type="document_extraction",
        status="queued",
        progress_percent=0,
        current_step_name=None,
        triggered_by=actor_user_id,
        created_at=now,
    )
    session.add(pipeline)
    session.flush()
    initialize_pipeline_steps(session, pipeline, ocr_model_id=ocr_model.id, ocr_name=ocr_model.name, force_ocr=force_ocr)
    session.flush()
    enqueue_outbox(session, project=project, topic="document.extraction.requested", aggregate_type="pipeline_run", aggregate_id=pipeline.id, payload={"pipeline_run_id": str(pipeline.id)})
    return pipeline


def create_reextraction_revision(
    *,
    session: Session,
    settings: Settings,
    project: Project,
    document_id: UUID,
    source_version_id: UUID,
    source_content_sha256: str,
    document_lock_version: int,
    actor_user_id: UUID,
    requested_ocr_model_id: UUID | None,
    force_ocr: bool,
) -> tuple[Document, DocumentVersion, PipelineRun]:
    document = session.scalar(
        select(Document).where(Document.id == document_id, Document.project_id == project.id).with_for_update()
    )
    if document is None or document.is_deleted:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    if document.lock_version != document_lock_version:
        raise AppError("stale_document_version", "Document was changed by another request", status_code=409)
    source = session.get(DocumentVersion, source_version_id)
    if source is None or source.document_id != document.id or source.project_id != project.id:
        raise AppError("document_version_not_found", "Source document version was not found", status_code=404)
    if not source.content_sha256 or source.content_sha256.lower() != source_content_sha256.lower():
        raise AppError("source_fingerprint_conflict", "Source content changed; reload before re-extraction", status_code=409)
    if source.status not in {"active", "inactive", "submission_ready", "approved"}:
        raise AppError("reextraction_source_not_ready", "Source version is not eligible for re-extraction", status_code=409)
    existing_work = session.scalar(
        select(DocumentVersion.id)
        .where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.status.in_(("quarantine", "queued", "processing", "pending_manager_review", "pending_owner_review")),
        )
        .limit(1)
    )
    if existing_work is not None:
        raise AppError("document_reextraction_in_progress", "A working version already exists for this document", status_code=409)
    revision = int(
        session.scalar(
            select(func.coalesce(func.max(DocumentVersion.extraction_revision), -1)).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.version_major == source.version_major,
            )
        )
        or 0
    ) + 1
    now = datetime.now(UTC)
    version = DocumentVersion(
        id=uuid4(),
        project_id=project.id,
        document_id=document.id,
        version_major=source.version_major,
        extraction_revision=revision,
        version_label=f"v{source.version_major}.{revision}",
        status="ready_for_extraction",
        original_file_name=source.original_file_name,
        canonical_extension=source.canonical_extension,
        mime_type=source.mime_type,
        file_size=source.file_size,
        content_sha256=source.content_sha256,
        storage_name_salt=source.storage_name_salt,
        storage_name_hash=source.storage_name_hash,
        storage_bucket=source.storage_bucket,
        storage_key=source.storage_key,
        storage_etag=source.storage_etag,
        uploaded_at=source.uploaded_at,
        original_snapshot_uri=source.original_snapshot_uri,
        chunk_strategy={
            **(source.chunk_strategy or {}),
            "source": "same_source_reextraction",
            "source_version_id": str(source.id),
        },
        embedding_model_id=project.embedding_model_id or source.embedding_model_id,
        embedding_profile_id=source.embedding_profile_id,
        llm_model_id=project.llm_model_id or source.llm_model_id,
        source_document_id=document.id,
        source_version_id=source.id,
        source_snapshot_created_at=now,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(version)
    session.flush()
    document.lock_version += 1
    document.updated_at = now
    pipeline = start_document_extraction(
        session=session,
        settings=settings,
        project=project,
        document=document,
        version=version,
        actor_user_id=actor_user_id,
        requested_ocr_model_id=requested_ocr_model_id,
        force_ocr=force_ocr,
    )
    return document, version, pipeline


def queue_document_extraction(
    session: Session,
    *,
    project: Project,
    document: Document,
    version: DocumentVersion,
) -> PipelineRun:
    existing = session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version.id, PipelineRun.status.in_(("queued", "running", "submission_ready"))).limit(1))
    if existing is not None:
        return existing
    model = session.get(AIModel, version.ocr_model_id) if version.ocr_model_id else None
    if model is None:
        raise AppError("ocr_model_required", "An active OCR model is required", status_code=422)
    now = datetime.now(UTC)
    pipeline = PipelineRun(
        id=uuid4(),
        project_id=project.id,
        document_id=document.id,
        document_version_id=version.id,
        project_generation=project.work_generation,
        run_type="document_extraction",
        status="queued",
        progress_percent=0,
        triggered_by=document.created_by,
        created_at=now,
    )
    version.status = "queued"
    session.add(pipeline)
    session.flush()
    initialize_pipeline_steps(session, pipeline, ocr_model_id=model.id, ocr_name=model.name, force_ocr=bool((version.chunk_strategy or {}).get("force_ocr")))
    enqueue_outbox(session, project=project, topic="document.extraction.requested", aggregate_type="pipeline_run", aggregate_id=pipeline.id, payload={"pipeline_run_id": str(pipeline.id)})
    return pipeline


def enqueue_outbox(session: Session, *, project: Project, topic: str, aggregate_type: str, aggregate_id: UUID, payload: dict[str, str]) -> OutboxEvent:
    event = OutboxEvent(
        id=uuid4(),
        topic=topic,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        project_id=project.id,
        project_generation=project.work_generation,
        payload={**payload, "project_id": str(project.id), "project_generation": project.work_generation},
        status="pending",
        attempts=0,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    session.add(event)
    return event


def _next_document_code(session: Session, project_id: UUID) -> str:
    count = session.scalar(select(func.count()).select_from(Document).where(Document.project_id == project_id)) or 0
    return f"DOC-{count + 1:06d}"


def _title_from_filename(filename: str) -> str:
    title = re.sub(r"\.[^.]+$", "", filename).strip() or filename
    return title[:MAX_TITLE_LENGTH]


def latest_versions(session: Session, project_id: UUID) -> list[tuple[Document, DocumentVersion | None, PipelineRun | None]]:
    documents = list(session.scalars(select(Document).where(Document.project_id == project_id, Document.is_deleted.is_(False)).order_by(desc(Document.updated_at), Document.title)))
    rows: list[tuple[Document, DocumentVersion | None, PipelineRun | None]] = []
    for document in documents:
        version = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision)).limit(1))
        pipeline = None
        if version is not None:
            pipeline = session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version.id).order_by(desc(PipelineRun.created_at)).limit(1))
        rows.append((document, version, pipeline))
    return rows


def _latest_document_version(session: Session, document_id: UUID) -> DocumentVersion | None:
    return session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at)).limit(1))
