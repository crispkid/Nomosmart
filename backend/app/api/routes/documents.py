from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from time import perf_counter
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import delete, desc, exists, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domain.project_access import get_scoped_project as _get_scoped_project, project_capabilities
from app.api.schemas import ApprovalChatEvidence, ApprovalChunkEvidence, ApprovalRequestResponse, ChunkEditPayload, DocumentLayoutArtifact, DocumentLayoutBlock, DocumentLayoutPage, DocumentReferenceSourceSummary, DocumentReextractPayload, DocumentReextractResponse, DocumentServiceSourceSummary, DocumentSummary, DocumentUpdateResponse, DocumentUploadResponse, DocumentUploadResult, DocumentVersionSummary, KnowledgeAutoTagPayload, KnowledgeDetailResponse, KnowledgeTagCreatePayload, KnowledgeTagResponse, LifecycleImpactResponse, LifecycleUpdatePayload, ManualChunkCreatePayload, OriginalFileViewerMetadata, PipelineRunDetail, PipelineStepSummary, PipelineSummary, ProcessingDebugChunk, ProcessingDebugNode, ProcessingDebugResponse, RetryPipelineStepPayload, StartExtractionPayload, StartExtractionResponse, SubmissionEvidenceResponse, SubmitReviewPayload
from app.core.errors import AppError
from app.db.models import AIModel, ActiveVersionManifest, ChatRecord, Chunk, ChunkTag, DataConnection, Document, DocumentReference, DocumentReferenceEvent, DocumentVersion, DocumentVersionTag, PipelineRun, PipelineRunStep, Project, Tag, ValidationRun
from app.db.session import get_db, get_session_factory
from app.domain.ai_provider import generate_knowledge_tags
from app.domain.chat_citations import compact_citation_view, hydrate_citation_groups
from app.domain.chunk_artifacts import chunk_artifact_state, lock_chunk_write_scope, queue_chunk_artifact_reconciliation
from app.domain.chunk_representations import build_manual_chunk_representation
from app.domain.chunk_deletion import delete_candidate_chunk, reference_conflict
from app.domain.document_imports import UploadedFilePayload, create_reextraction_revision, create_updated_file_version, create_uploaded_document, latest_versions, start_document_extraction
from app.domain.document_layout import hydrate_document_layout_inline_markdown
from app.domain.document_summary import document_summary_metadata
from app.domain.document_execution import execution_projection
from app.domain.extraction_pipeline import retry_failed_step
from app.domain.markdown_artifacts import normalize_source_mappings, resolve_manual_source_mapping, resolve_markdown_artifact
from app.domain.markdown_structure import MarkdownStructureParser
from app.domain.multipart_upload import MultipartPayload, parse_multipart as _parse_multipart
from app.domain.upload_stream import receive_upload
from app.domain.upload_content import UploadContent
from app.domain.public_api_controls import begin_idempotent_operation, complete_idempotent_operation, require_idempotency_key
from app.domain.model_usage import record_model_usage
from app.domain.reference_events import create_source_reference_events
from app.domain.review_publish import submit_review
from app.domain.submission_evidence import build_submission_evidence
from app.domain.system_prompts import resolve_system_prompt
from app.integrations.s3_storage import S3ObjectStorage
from app.security.context import IdentityContext, get_identity_context
from app.security.project_roles import PROJECT_EDITOR_ROLES, PROJECT_OWNER_ROLES, has_project_role, require_project_role
from app.services.audit import add_audit


router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])

REVIEW_LOCKED_VERSION_STATUSES = {"pending_manager_review", "pending_owner_review", "approved"}
PROCESSING_DEBUG_ROLES = PROJECT_EDITOR_ROLES | PROJECT_OWNER_ROLES


class _CompensatingStorage:
    def __init__(self, storage: S3ObjectStorage) -> None:
        self._storage = storage
        self._created: list[tuple[str, str]] = []
        self._uncertain_write = False
        self.commit_started = False

    def put_object(self, *, bucket: str, key: str, body: bytes | UploadContent, content_type: str | None):
        # Register BEFORE PUT: connection loss does not prove that S3 stored nothing.
        self._created.append((bucket, key))
        try:
            return self._storage.put_object(bucket=bucket, key=key, body=body, content_type=content_type)
        except Exception:
            # A remote in-flight PUT may complete after DELETE/HEAD. Retain explicit
            # cleanup-failed evidence rather than claiming an absent HEAD is proof.
            self._uncertain_write = True
            raise

    def compensate(self) -> bool:
        if self.commit_started and self._created:
            # COMMIT response loss is not proof of rollback. Never delete a source
            # that may already belong to a committed version/idempotency result.
            return False
        complete = not self._uncertain_write
        for bucket, key in reversed(self._created):
            try:
                self._storage.delete_object(bucket=bucket, key=key)
                try:
                    self._storage.object_status(bucket=bucket, key=key)
                except AppError as exc:
                    if exc.code != "s3_object_missing":
                        complete = False
                else:
                    complete = False
            except Exception:
                complete = False
        return complete


def _process_upload_item(
    *,
    session_factory,
    settings,
    project_id: UUID,
    actor_user_id: UUID,
    visible_project_ids: set[UUID],
    request_id: str,
    raw_key: str,
    index: int,
    file: UploadedFilePayload,
    requested_ocr_id: UUID | None,
    force_ocr: bool,
    start_extraction: bool,
) -> DocumentUploadResult:
    item_payload = {
        "index": index,
        "filename": file.filename,
        "content_type": file.content_type,
        "sha256": file.source.sha256,
        "ocr_model_id": str(requested_ocr_id) if requested_ocr_id else None,
        "force_ocr": force_ocr,
    }
    storage = _CompensatingStorage(S3ObjectStorage(settings))
    try:
        with session_factory() as item_session:
            project = item_session.get(Project, project_id)
            if project is None or project.status != "active":
                raise AppError("project_archived", "Archived projects cannot accept uploads", status_code=409)
            require_project_role(item_session, project.id, actor_user_id, visible_project_ids, PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required for document import")
            replay, item_record = begin_idempotent_operation(
                item_session,
                settings,
                scope=f"document-upload-item:{project.id}:{actor_user_id}:{index}",
                raw_key=raw_key,
                request_payload=item_payload,
            )
            if replay is not None:
                return DocumentUploadResult.model_validate(replay.body)
            document, version, pipeline = create_uploaded_document(
                session=item_session,
                settings=settings,
                storage=storage,
                project=project,
                actor_user_id=actor_user_id,
                file=file,
                requested_ocr_model_id=requested_ocr_id,
                force_ocr=force_ocr,
                start_extraction=start_extraction,
            )
            item_session.flush()
            result = DocumentUploadResult(
                index=index,
                filename=file.filename,
                status="success",
                document=_project_document(item_session, document, version, pipeline, visible_project_ids=visible_project_ids, capabilities=project_capabilities(item_session, project, user_id=actor_user_id, visible_project_ids=visible_project_ids)),
                started_extraction=pipeline is not None,
            )
            complete_idempotent_operation(item_record, result.model_dump(mode="json"))
            add_audit(
                item_session,
                actor_user_id=actor_user_id,
                action="document.upload.item",
                resource_type="document",
                resource_id=document.id,
                result="success",
                request_id=request_id,
                summary={"index": index, "filename_hash": hashlib.sha256(file.filename.encode("utf-8")).hexdigest()},
            )
            storage.commit_started = True
            item_session.commit()
            return result
    except AppError as exc:
        compensation_complete = storage.compensate()
        result = DocumentUploadResult(
            index=index,
            filename=file.filename,
            status="failed",
            error_code=exc.code if compensation_complete else "upload_compensation_failed",
            message=exc.message if compensation_complete else "Upload failed and object-store cleanup requires operator reconciliation",
        )
    except Exception:
        compensation_complete = storage.compensate()
        result = DocumentUploadResult(
            index=index,
            filename=file.filename,
            status="failed",
            error_code="upload_failed" if compensation_complete else "upload_compensation_failed",
            message="Upload failed" if compensation_complete else "Upload failed and object-store cleanup requires operator reconciliation",
        )

    with session_factory() as evidence_session:
        replay, item_record = begin_idempotent_operation(
            evidence_session,
            settings,
            scope=f"document-upload-item:{project_id}:{actor_user_id}:{index}",
            raw_key=raw_key,
            request_payload=item_payload,
        )
        if replay is not None:
            return DocumentUploadResult.model_validate(replay.body)
        complete_idempotent_operation(item_record, result.model_dump(mode="json"))
        add_audit(
            evidence_session,
            actor_user_id=actor_user_id,
            action="document.upload.item",
            resource_type="project",
            resource_id=project_id,
            result="failed",
            request_id=request_id,
            summary={"index": index, "error_code": result.error_code},
        )
        evidence_session.commit()
    return result


@router.get("", response_model=list[DocumentSummary])
def list_project_documents(project_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[DocumentSummary]:
    project = _get_scoped_project(session, project_id, context)
    capabilities = project_capabilities(session, project, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids))
    rows = latest_versions(session, project.id)
    metadata = document_summary_metadata(session, project.id, [document.id for document, _version, _pipeline in rows])
    return [_project_document(session, document, version, pipeline, visible_project_ids=set(context.visible_project_ids), capabilities=capabilities, summary_metadata=metadata) for document, version, pipeline in rows]


@router.post("/upload", response_model=DocumentUploadResponse, status_code=200)
async def upload_documents(
    project_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DocumentUploadResponse:
    project = await run_in_threadpool(_authorize_upload, session, project_id, context)
    raw_key = require_idempotency_key(idempotency_key)
    async with receive_upload(request) as payload:
        return await run_in_threadpool(_complete_upload_documents, project, request, raw_key, context, session, payload)


def _authorize_upload(session: Session, project_id: UUID, context: IdentityContext) -> Project:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required for document import")
    return project


def _complete_upload_documents(project: Project, request: Request, raw_key: str, context: IdentityContext, session: Session, payload: MultipartPayload) -> DocumentUploadResponse:
    requested_ocr_id = _optional_uuid(payload.fields.get("ocr_model_id"))
    force_ocr = payload.fields.get("force_ocr", "false").lower() == "true"
    if not payload.files:
        raise AppError("upload_file_required", "At least one file is required", status_code=422)
    request_payload = {
        "project_id": str(project.id),
        "ocr_model_id": str(requested_ocr_id) if requested_ocr_id else None,
        "force_ocr": force_ocr,
        "files": [
            {"index": index, "filename": file.filename, "content_type": file.content_type, "sha256": file.source.sha256}
            for index, file in enumerate(payload.files)
        ],
    }
    replay, request_record = begin_idempotent_operation(
        session,
        request.app.state.settings,
        scope=f"document-upload:{project.id}:{context.user_id}",
        raw_key=raw_key,
        request_payload=request_payload,
    )
    if replay is not None:
        return DocumentUploadResponse.model_validate(replay.body)
    session.commit()

    session_factory = get_session_factory()
    results: list[DocumentUploadResult] = []
    start_extraction = len(payload.files) == 1
    for index, file in enumerate(payload.files):
        results.append(
            _process_upload_item(
                session_factory=session_factory,
                settings=request.app.state.settings,
                project_id=project.id,
                actor_user_id=context.user_id,
                visible_project_ids=set(context.visible_project_ids),
                request_id=request.state.request_id,
                raw_key=raw_key,
                index=index,
                file=file,
                requested_ocr_id=requested_ocr_id,
                force_ocr=force_ocr,
                start_extraction=start_extraction,
            )
        )

    response = DocumentUploadResponse(
        request_id=request.state.request_id,
        success_count=sum(1 for item in results if item.status == "success"),
        failed_count=sum(1 for item in results if item.status == "failed"),
        results=results,
    )
    request_record = session.get(type(request_record), request_record.id)
    if request_record is None:
        raise AppError("idempotency_record_missing", "Upload idempotency record is unavailable", status_code=503)
    complete_idempotent_operation(request_record, response.model_dump(mode="json"))
    add_audit(session, actor_user_id=context.user_id, action="document.upload.batch", resource_type="project", resource_id=project.id, result="success", request_id=request.state.request_id, summary={"success_count": response.success_count, "failed_count": response.failed_count, "force_ocr": force_ocr})
    session.commit()
    return response


@router.post("/{document_id}/versions/update-file", response_model=DocumentUpdateResponse)
async def update_uploaded_document_file(
    project_id: UUID,
    document_id: UUID,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DocumentUpdateResponse:
    project, document = await run_in_threadpool(_authorize_update_file, session, project_id, document_id, context)
    async with receive_upload(request) as payload:
        return await run_in_threadpool(_complete_update_file, project, document, request, context, session, payload)


def _authorize_update_file(session: Session, project_id: UUID, document_id: UUID, context: IdentityContext) -> tuple[Project, Document]:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required for document update")
    document = session.get(Document, document_id)
    if document is None or document.project_id != project.id:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    return project, document


def _complete_update_file(project: Project, document: Document, request: Request, context: IdentityContext, session: Session, payload: MultipartPayload) -> DocumentUpdateResponse:
    if len(payload.files) != 1:
        raise AppError("single_update_file_required", "Exactly one replacement file is required", status_code=422)
    requested_ocr_id = _optional_uuid(payload.fields.get("ocr_model_id"))
    force_ocr = payload.fields.get("force_ocr", "false").lower() == "true"
    latest_before = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at)).limit(1))
    storage = _CompensatingStorage(S3ObjectStorage(request.app.state.settings))
    try:
        version, pipeline, no_change = create_updated_file_version(
            session=session,
            settings=request.app.state.settings,
            storage=storage,
            project=project,
            document=document,
            actor_user_id=context.user_id,
            file=payload.files[0],
            requested_ocr_model_id=requested_ocr_id,
            force_ocr=force_ocr,
        )
        if not no_change:
            create_source_reference_events(
                session,
                source_document=document,
                event_type="source_updated",
                old_source_version_id=latest_before.id if latest_before else None,
                new_source_version_id=version.id,
            )
        add_audit(
            session,
            actor_user_id=context.user_id,
            action="document.version.update_file",
            resource_type="document",
            resource_id=document.id,
            result="success",
            request_id=request.state.request_id,
            summary={"version_id": str(version.id), "no_change": no_change},
        )
        storage.commit_started = True
        session.commit()
    except Exception as exc:
        session.rollback()
        if not storage.compensate():
            raise AppError(
                "upload_compensation_failed",
                "Replacement upload failed and stored object cleanup did not complete",
                status_code=503,
            ) from exc
        raise
    session.refresh(document)
    session.refresh(version)
    if pipeline is not None:
        session.refresh(pipeline)
    message = "No content change detected; no new version was created." if no_change else "Replacement file accepted and extraction started."
    return DocumentUpdateResponse(
        document=_project_document(session, document, version, pipeline, visible_project_ids=set(context.visible_project_ids), capabilities=project_capabilities(session, project, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids))),
        latest_pipeline=_pipeline_summary(pipeline) if pipeline else None,
        no_change=no_change,
        message=message,
    )


@router.post("/{document_id}/re-extract", response_model=DocumentReextractResponse, status_code=201)
def reextract_document(
    project_id: UUID,
    document_id: UUID,
    payload: DocumentReextractPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DocumentReextractResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required to re-extract a document")
    replay, record = begin_idempotent_operation(
        session,
        request.app.state.settings,
        scope=f"document-reextract:{project.id}:{document_id}:{context.user_id}",
        raw_key=idempotency_key,
        request_payload={"document_id": str(document_id), "payload": payload.model_dump(mode="json")},
    )
    if replay is not None:
        return DocumentReextractResponse.model_validate(replay.body)
    document, version, pipeline = create_reextraction_revision(
        session=session,
        settings=request.app.state.settings,
        project=project,
        document_id=document_id,
        source_version_id=payload.source_version_id,
        source_content_sha256=payload.source_content_sha256,
        document_lock_version=payload.lock_version,
        actor_user_id=context.user_id,
        requested_ocr_model_id=payload.ocr_model_id,
        force_ocr=payload.force_ocr,
    )
    response = DocumentReextractResponse(
        document_id=document.id,
        source_version_id=payload.source_version_id,
        document_version_id=version.id,
        version_label=version.version_label,
        pipeline_run_id=pipeline.id,
        status=pipeline.status,
    )
    complete_idempotent_operation(record, response.model_dump(mode="json"), status_code=201)
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="document.reextract.queued",
        resource_type="document_version",
        resource_id=version.id,
        result="success",
        request_id=request.state.request_id,
        summary={"source_version_id": str(payload.source_version_id), "pipeline_run_id": str(pipeline.id)},
    )
    session.commit()
    return response


@router.post("/{document_id}/versions/{version_id}/extract", response_model=StartExtractionResponse)
def start_extraction(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    payload: StartExtractionPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> StartExtractionResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required to start extraction")
    document = session.get(Document, document_id)
    version = session.get(DocumentVersion, version_id)
    if document is None or version is None or document.project_id != project.id or version.document_id != document.id:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    _ensure_not_review_locked(version, "document.extraction.start")
    pipeline = start_document_extraction(session=session, settings=request.app.state.settings, project=project, document=document, version=version, actor_user_id=context.user_id, requested_ocr_model_id=payload.ocr_model_id, force_ocr=payload.force_ocr)
    add_audit(session, actor_user_id=context.user_id, action="document.extraction.start", resource_type="document", resource_id=document.id, result="success", request_id=request.state.request_id, summary={"version_id": str(version.id), "force_ocr": payload.force_ocr})
    session.commit()
    session.refresh(document)
    session.refresh(version)
    session.refresh(pipeline)
    return StartExtractionResponse(document=_project_document(session, document, version, pipeline, visible_project_ids=set(context.visible_project_ids), capabilities=project_capabilities(session, project, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids))), pipeline=_pipeline_summary(pipeline))


@router.post("/{document_id}/versions/{version_id}/submit-review", response_model=ApprovalRequestResponse, status_code=201)
def submit_document_version_review(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    payload: SubmitReviewPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
):
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_submit_review_role_required", message="Owner or Editor role is required to submit review")
    raw_key = require_idempotency_key(idempotency_key)
    replay, record = begin_idempotent_operation(
        session,
        request.app.state.settings,
        scope=f"document.submit-review:{version_id}:{context.user_id}",
        raw_key=raw_key,
        request_payload={"project_id": str(project_id), "document_id": str(document_id), "version_id": str(version_id), "payload": payload.model_dump(mode="json")},
    )
    if replay is not None:
        return replay
    project = session.scalar(select(Project).where(Project.id == project.id).with_for_update())
    document = session.scalar(select(Document).where(Document.id == document_id).with_for_update())
    version = session.get(DocumentVersion, version_id)
    if document is None or document.project_id != project.id:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    if version is None or version.document_id != document.id or version.project_id != project.id:
        raise AppError("document_version_not_found", "Document version was not found", status_code=404)
    version = session.scalar(select(DocumentVersion).where(DocumentVersion.id == version.id).with_for_update())
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_submit_review_role_required", message="Owner or Editor role is required to submit review")
    if version.lock_version != payload.lock_version:
        raise AppError("submission_evidence_stale", "Submission evidence changed; reload before submitting", status_code=409)
    projection = build_submission_evidence(session, project=project, document=document, version=version)
    if projection.evidence_revision != payload.evidence_revision:
        raise AppError("submission_evidence_stale", "Submission evidence changed; reload before submitting", status_code=409)
    if not projection.next_stage_allowed:
        raise AppError("submission_evidence_not_ready", "Submission evidence is not ready", status_code=409, details={"block_reasons": projection.block_reasons})
    approval = submit_review(
        session=session,
        actor_user_id=context.user_id,
        version=version,
        owner_user_id=payload.owner_user_id,
        request_id=request.state.request_id,
        evidence_revision=projection.evidence_revision,
        evidence_manifest=projection.manifest,
        evidence_generated_at=projection.generated_at,
    )
    session.flush()
    response = ApprovalRequestResponse.model_validate(approval)
    complete_idempotent_operation(record, response.model_dump(mode="json"), status_code=201)
    session.commit()
    session.refresh(approval)
    return response


@router.get(
    "/{document_id}/versions/{version_id}/submission-evidence",
    response_model=SubmissionEvidenceResponse,
)
def get_document_version_submission_evidence(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SubmissionEvidenceResponse:
    project = _get_scoped_project(session, project_id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    projection = build_submission_evidence(session, project=project, document=document, version=version)
    detail = _knowledge_detail_response(session, project, document, version, context)
    capabilities = project_capabilities(
        session,
        project,
        user_id=context.user_id,
        visible_project_ids=set(context.visible_project_ids),
    )
    chat_rows = list(
        session.scalars(
            select(ChatRecord)
            .where(
                ChatRecord.document_version_id == version.id,
                ChatRecord.scope_mode == "document_staging",
                ChatRecord.deleted_at.is_(None),
            )
            .order_by(ChatRecord.asked_at, ChatRecord.id)
        )
    )
    hydrated_chat_citations = hydrate_citation_groups(
        session,
        [row.reference_docs for row in chat_rows],
        project_id=project.id,
        allowed_version_ids={version.id},
    )
    chat_records: list[ApprovalChatEvidence] = []
    for row, citations in zip(chat_rows, hydrated_chat_citations, strict=True):
        compact = compact_citation_view(row.answer, citations)
        chat_records.append(
            ApprovalChatEvidence(
                id=row.id,
                conversation_id=row.conversation_id,
                conversation_title=row.conversation_title,
                scope_mode=row.scope_mode,
                document_version_id=row.document_version_id,
                selected_document_version_ids=sorted(
                    {
                        UUID(str(value))
                        for value in (row.selected_document_version_ids or [])
                        if value
                    },
                    key=str,
                ),
                question=row.question,
                answer=compact.answer,
                reference_docs=compact.citations,
                evaluation=row.evaluation,
                revision_suggestion=row.revision_suggestion,
                created_by=row.created_by,
                asked_at=row.asked_at,
                answered_at=row.answered_at,
            )
        )
    validation_runs = [
        {
            "id": str(run.id),
            "status": run.status,
            "run_scope": run.run_scope,
            "total_count": run.total_count,
            "completed_count": run.completed_count,
            "failed_count": run.failed_count,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
        }
        for run in session.scalars(
            select(ValidationRun)
            .where(
                ValidationRun.project_id == project.id,
                ValidationRun.document_version_id == version.id,
                ValidationRun.run_scope == "document_staging",
            )
            .order_by(ValidationRun.created_at, ValidationRun.id)
        )
    ]
    summary = projection.summary
    return SubmissionEvidenceResponse(
        detail=detail,
        evidence_revision=projection.evidence_revision,
        lock_version=version.lock_version,
        generated_at=projection.generated_at,
        next_stage_allowed=projection.next_stage_allowed,
        block_reasons=projection.block_reasons,
        can_submit_review=bool(capabilities["can_submit_review"]),
        creator=summary["creator"],
        manager=summary["manager"],
        owners=summary["owners"],
        models=summary["models"],
        content_type_counts=summary["content_type_counts"],
        chunk_count=summary["chunk_count"],
        tag_count=summary["tag_count"],
        average_confidence=summary["average_confidence"],
        graph=summary["graph"],
        chat_records=chat_records,
        validation_runs=validation_runs,
    )


@router.get("/{document_id}/lifecycle-impact", response_model=LifecycleImpactResponse)
def get_document_lifecycle_impact(
    project_id: UUID,
    document_id: UUID,
    status: str,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> LifecycleImpactResponse:
    project = _get_scoped_project(session, project_id, context)
    document = session.get(Document, document_id)
    if document is None or document.project_id != project.id:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    return _lifecycle_impact(session, document, status)


@router.patch("/{document_id}/lifecycle", response_model=DocumentSummary)
def update_document_lifecycle(
    project_id: UUID,
    document_id: UUID,
    payload: LifecycleUpdatePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DocumentSummary:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Project Owner or Editor relationship is required for document lifecycle changes")
    document = session.get(Document, document_id)
    if document is None or document.project_id != project.id:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    if document.lock_version != payload.lock_version:
        raise AppError("stale_document", "Document was changed by another request", status_code=409)
    if payload.status not in {"active", "inactive", "deleted"}:
        raise AppError("invalid_lifecycle_status", "Lifecycle status must be active, inactive, or deleted", status_code=422)
    impact = _lifecycle_impact(session, document, payload.status)
    if impact.requires_confirmation and not payload.impact_confirmed:
        raise AppError("impact_confirmation_required", "Lifecycle transition requires impact confirmation", status_code=422)
    manifest = session.scalar(select(ActiveVersionManifest).where(ActiveVersionManifest.document_id == document.id, ActiveVersionManifest.index_ready.is_(True)))
    if payload.status == "active" and manifest is None:
        raise AppError("active_manifest_required", "Document requires a ready active manifest before activation", status_code=409)
    if payload.status == "deleted":
        document.status = "deleted"
        document.is_deleted = True
    else:
        document.status = payload.status
        document.is_deleted = False
    document.lock_version += 1
    event_type = {"active": "source_activated", "inactive": "source_deactivated", "deleted": "source_deleted"}[payload.status]
    create_source_reference_events(session, source_document=document, event_type=event_type)
    add_audit(session, actor_user_id=context.user_id, action="document.lifecycle.update", resource_type="document", resource_id=document.id, result="success", request_id=request.state.request_id, summary={"status": payload.status, "reason": payload.reason, "impact": impact.model_dump(mode="json")})
    session.commit()
    version = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.created_at.desc()).limit(1))
    pipeline = session.scalar(select(PipelineRun).where(PipelineRun.document_id == document.id).order_by(PipelineRun.created_at.desc()).limit(1))
    return _project_document(session, document, version, pipeline, visible_project_ids=set(context.visible_project_ids), capabilities=project_capabilities(session, project, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids)))


@router.get("/{document_id}/versions/{version_id}/pipelines/{pipeline_id}", response_model=PipelineRunDetail)
def get_pipeline_detail(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    pipeline_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> PipelineRunDetail:
    project = _get_scoped_project(session, project_id, context)
    document, version, pipeline = _scoped_document_version_pipeline(session, project.id, document_id, version_id, pipeline_id)
    return _pipeline_detail(pipeline)


@router.get("/{document_id}/knowledge", response_model=KnowledgeDetailResponse)
def get_document_knowledge_detail(
    project_id: UUID,
    document_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    document = session.get(Document, document_id)
    if document is None or document.project_id != project.id:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    version = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document.id, DocumentVersion.project_id == project.id).order_by(DocumentVersion.created_at.desc()).limit(1))
    if version is None:
        raise AppError("document_version_not_found", "Document version was not found", status_code=404)
    return _knowledge_detail_response(session, project, document, version, context)


@router.get("/{document_id}/versions/{version_id}/processing-debug", response_model=ProcessingDebugResponse)
def get_processing_debug(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ProcessingDebugResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(
        session,
        project.id,
        context.user_id,
        set(context.visible_project_ids),
        PROCESSING_DEBUG_ROLES,
        code="processing_debug_role_required",
        message="Owner or Editor role is required to inspect processing diagnostics",
    )
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    artifact = resolve_markdown_artifact(session, version)
    nodes: list[ProcessingDebugNode] = []
    warnings: list[dict[str, object]] = []
    parser_version: str | None = None
    if artifact.text is not None:
        structure = MarkdownStructureParser().parse(artifact.text)
        parser_version = structure.parser_version
        warnings = list(structure.warnings)
        nodes = [
            ProcessingDebugNode(
                id=node.id,
                type=node.type,
                text=node.text,
                markdown=node.markdown,
                start_offset=node.start_offset,
                end_offset=node.end_offset,
                sequence=node.sequence,
                heading_path=list(node.heading_path),
                heading_level=node.heading_level,
                metadata=node.metadata,
            )
            for node in structure.nodes
        ]
    chunks = _active_chunks(session, project.id, document.id, version.id)
    chunk_debug = [
        ProcessingDebugChunk(
            id=chunk.id,
            chunk_index=chunk.chunk_index,
            sequence=chunk.sequence,
            stable_chunk_key=chunk.stable_chunk_key,
            raw_markdown=chunk.markdown_content,
            display_markdown=chunk.display_markdown,
            display_text=chunk.content,
            retrieval_text=chunk.retrieval_text,
            heading_path=list(chunk.heading_path or []),
            token_count=chunk.token_count,
            embedding_content_hash=chunk.embedding_content_hash,
            source_mapping=normalize_source_mappings(chunk.content, chunk.source_mapping, artifact.text),
            processing_metadata=chunk.chunk_strategy or {},
        )
        for chunk in chunks
    ]
    strategy = version.chunk_strategy or {}
    return ProcessingDebugResponse(
        document_id=document.id,
        document_version_id=version.id,
        markdown_artifact_status=artifact.status,
        raw_markdown=artifact.text,
        parser_version=parser_version or strategy.get("parser_version"),
        warnings=warnings,
        nodes=nodes,
        chunks=chunk_debug,
        processing_versions={
            key: strategy.get(key)
            for key in ("parser_version", "chunker_version", "normalizer_version", "tokenizer_version", "effective_chunk_config")
            if strategy.get(key) is not None
        },
    )


@router.post("/{document_id}/versions/{version_id}/chunks/manual", response_model=KnowledgeDetailResponse)
def create_manual_chunk(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    payload: ManualChunkCreatePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required to edit chunks")
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    _ensure_manual_edit_allowed(session, version, payload.lock_version)
    content = payload.content.strip()
    if not content:
        raise AppError("manual_chunk_blank", "Manual chunk content cannot be blank", status_code=422)
    if payload.end_offset <= payload.start_offset:
        raise AppError("manual_chunk_range_invalid", "Manual chunk range is invalid", status_code=422)
    markdown_artifact = resolve_markdown_artifact(session, version)
    expected_scope = "canonical_markdown" if payload.view_mode == "markdown" else "source_anchor"
    offset_scope = payload.offset_scope or expected_scope
    offset_unit = payload.offset_unit or "unicode_code_point"
    if markdown_artifact.text is None or (offset_scope != expected_scope and offset_scope != "canonical_markdown"):
        raise AppError("chunk_source_mapping_invalid", "Chunk source mapping could not be resolved", status_code=422)
    resolved_manual_mapping = resolve_manual_source_mapping(
        content=content,
        markdown=markdown_artifact.text,
        source_anchor=payload.source_anchor,
        start_offset=payload.start_offset,
        end_offset=payload.end_offset,
        offset_scope=offset_scope,
        offset_unit=offset_unit,
    )
    if resolved_manual_mapping is None:
        raise AppError("chunk_source_mapping_invalid", "Chunk source mapping could not be resolved", status_code=422)
    resolved_manual_mapping["view_mode"] = payload.view_mode
    chunks = _active_chunks(session, project.id, document.id, version.id)
    manual_start = int(resolved_manual_mapping["markdown_start_offset"])
    manual_end = int(resolved_manual_mapping["markdown_end_offset"])
    overlaps: list[tuple[Chunk, dict[str, object], int, int]] = []
    for chunk in chunks:
        normalized = normalize_source_mappings(chunk.content, chunk.source_mapping, markdown_artifact.text)
        mapping = next((item for item in normalized if item.get("mapping_status") == "resolved"
                        and int(item["markdown_start_offset"]) < manual_end
                        and int(item["markdown_end_offset"]) > manual_start), None)
        if mapping is None:
            continue
        start = int(mapping["markdown_start_offset"])
        end = int(mapping["markdown_end_offset"])
        if end <= manual_start or start >= manual_end:
            continue
        overlaps.append((chunk, mapping, start, end))

    overlap_ids = [str(chunk.id) for chunk, _mapping, _start, _end in overlaps]
    inherited = overlaps[0][0] if overlaps else None
    config_snapshot = _manual_chunk_config_snapshot(version)
    new_segments: list[Chunk] = []
    for chunk, mapping, start, end in overlaps:
        if start < manual_start:
            new_segments.append(_split_chunk(chunk, start, manual_start, "before", context.user_id, mapping, document_title=document.title, canonical_markdown=markdown_artifact.text, config_snapshot=config_snapshot))
        if end > manual_end:
            new_segments.append(_split_chunk(chunk, manual_end, end, "after", context.user_id, mapping, document_title=document.title, canonical_markdown=markdown_artifact.text, config_snapshot=config_snapshot))

    manual_raw_markdown = markdown_artifact.text[manual_start:manual_end]
    manual_representation = build_manual_chunk_representation(
        raw_markdown=manual_raw_markdown,
        document_title=document.title,
        inherited_heading_path=inherited.heading_path if inherited else None,
        inherited_heading_level=inherited.heading_level if inherited else None,
        content_type=inherited.content_type if inherited else None,
        config_snapshot=config_snapshot,
    )
    now = datetime.now(UTC)
    for chunk, _mapping, _start, _end in overlaps:
        chunk.status = "superseded"
        chunk.chunk_strategy = {**(chunk.chunk_strategy or {}), "superseded_by": "manual_chunk", "superseded_at": now.isoformat()}
    manual_chunk = Chunk(
        id=uuid4(),
        project_id=project.id,
        document_id=document.id,
        document_version_id=version.id,
        chunk_index=0,
        title=f"Manual Chunk",
        content=manual_representation.display_text,
        markdown_content=manual_representation.raw_markdown,
        display_markdown=manual_representation.display_markdown,
        retrieval_text=manual_representation.retrieval_text,
        embedding_content_hash=manual_representation.embedding_content_hash,
        content_type=manual_representation.content_type,
        content_hash=manual_representation.content_hash,
        section_path=" > ".join(manual_representation.heading_path) or None,
        heading_path=list(manual_representation.heading_path) or None,
        heading_level=manual_representation.heading_level,
        page_start=resolved_manual_mapping.get("page_start") or resolved_manual_mapping.get("page"),
        page_end=resolved_manual_mapping.get("page_end") or resolved_manual_mapping.get("page"),
        stable_chunk_key=manual_representation.stable_chunk_key,
        start_offset=manual_start,
        end_offset=manual_end,
        source_mapping=[resolved_manual_mapping],
        chunk_strategy={**manual_representation.processing_metadata, "source": "manual", "replaced_chunk_ids": overlap_ids},
        embedding_model_id=version.embedding_model_id,
        token_count=manual_representation.token_count,
        confidence_score=1,
        status="active",
        is_manual_edited=True,
        edited_by=context.user_id,
        lineage_id=uuid4(),
        revision=0,
        change_type="manual_create",
    )
    for index, item in enumerate([*new_segments, manual_chunk], start=_next_chunk_index(session, version.id)):
        item.chunk_index = index
        session.add(item)
    session.flush()
    _reindex_active_chunks(session, project.id, document.id, version.id)
    version.lock_version += 1
    reconciliation = queue_chunk_artifact_reconciliation(session, version, actor_user_id=context.user_id)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.chunk.manual_create", resource_type="document_version", resource_id=version.id, result="success", request_id=request.state.request_id, summary={"document_id": str(document.id), "manual_chunk_id": str(manual_chunk.id), "replaced_chunk_ids": overlap_ids, "start_offset": manual_start, "end_offset": manual_end, "content_length": len(content), "reconciliation_id": str(reconciliation.id)})
    session.commit()
    return _knowledge_detail_response(session, project, document, version, context)


@router.patch("/{document_id}/versions/{version_id}/chunks/{chunk_id}", response_model=KnowledgeDetailResponse)
def edit_chunk(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    chunk_id: UUID,
    payload: ChunkEditPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required to edit chunks")
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    _ensure_manual_edit_allowed(session, version, payload.lock_version)
    chunk = session.scalar(
        select(Chunk)
        .where(
            Chunk.id == chunk_id,
            Chunk.project_id == project.id,
            Chunk.document_id == document.id,
            Chunk.document_version_id == version.id,
            Chunk.status == "active",
        )
        .with_for_update()
    )
    if chunk is None:
        raise AppError("chunk_not_found", "Chunk was not found", status_code=404)
    content = payload.content.strip()
    if not content:
        raise AppError("manual_chunk_blank", "Manual chunk content cannot be blank", status_code=422)
    for mapping in payload.source_mapping:
        if not str(mapping.get("source_anchor") or "").strip():
            raise AppError("chunk_source_mapping_invalid", "Every source mapping requires a source anchor", status_code=422)
    raw_markdown = payload.markdown_content if payload.markdown_content is not None and payload.markdown_content.strip() else content
    representation = build_manual_chunk_representation(
        raw_markdown=raw_markdown,
        document_title=document.title,
        inherited_heading_path=chunk.heading_path,
        inherited_heading_level=chunk.heading_level,
        content_type=chunk.content_type,
        config_snapshot=_manual_chunk_config_snapshot(version),
    )
    now = datetime.now(UTC)
    replacement = Chunk(
        id=uuid4(),
        project_id=chunk.project_id,
        document_id=chunk.document_id,
        document_version_id=chunk.document_version_id,
        chunk_index=chunk.chunk_index,
        title=payload.title,
        content=representation.display_text,
        markdown_content=representation.raw_markdown,
        display_markdown=representation.display_markdown,
        retrieval_text=representation.retrieval_text,
        embedding_content_hash=representation.embedding_content_hash,
        content_type=representation.content_type,
        content_hash=representation.content_hash,
        section_path=" > ".join(representation.heading_path) or None,
        heading_path=list(representation.heading_path) or None,
        heading_level=representation.heading_level,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        sequence=chunk.sequence,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        source_mapping=payload.source_mapping,
        stable_chunk_key=representation.stable_chunk_key,
        chunk_strategy={**(chunk.chunk_strategy or {}), **representation.processing_metadata, "source": "manual_edit", "parent_chunk_id": str(chunk.id)},
        embedding_model_id=chunk.embedding_model_id,
        token_count=representation.token_count,
        confidence_score=1,
        status="active",
        is_manual_edited=True,
        edited_by=context.user_id,
        lineage_id=chunk.lineage_id or chunk.id,
        parent_chunk_id=chunk.id,
        revision=(chunk.revision or 0) + 1,
        change_type="manual_edit",
        created_at=now,
        updated_at=now,
    )
    chunk.status = "superseded"
    chunk.superseded_at = now
    # Release the active-index slot before INSERT, and only link back after the
    # replacement exists. Flushes share this transaction; no partial commit.
    session.flush()
    session.add(replacement)
    session.flush()
    chunk.superseded_by_id = replacement.id
    chunk.chunk_strategy = {**(chunk.chunk_strategy or {}), "superseded_by": str(replacement.id), "superseded_at": now.isoformat()}
    for tag in session.scalars(select(ChunkTag).where(ChunkTag.chunk_id == chunk.id)):
        session.add(
            ChunkTag(
                chunk_id=replacement.id,
                tag_id=tag.tag_id,
                source=tag.source,
                confidence_score=tag.confidence_score,
                metadata_=tag.metadata_,
                created_by=tag.created_by,
                created_at=tag.created_at,
            )
        )
    version.lock_version += 1
    reconciliation = queue_chunk_artifact_reconciliation(session, version, actor_user_id=context.user_id)
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="knowledge.chunk.edit",
        resource_type="chunk",
        resource_id=replacement.id,
        result="success",
        request_id=request.state.request_id,
        summary={"parent_chunk_id": str(chunk.id), "lineage_id": str(replacement.lineage_id), "revision": replacement.revision, "reconciliation_id": str(reconciliation.id)},
    )
    session.commit()
    return _knowledge_detail_response(session, project, document, version, context)


@router.delete("/{document_id}/versions/{version_id}/chunks/{chunk_id}", response_model=KnowledgeDetailResponse)
def delete_chunk(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    chunk_id: UUID,
    lock_version: int,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> KnowledgeDetailResponse:
    try:
        return _delete_chunk_transaction(project_id, document_id, version_id, chunk_id,
                                         lock_version, request, context, session)
    except DBAPIError as exc:
        session.rollback()
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code in {"23503", "40001", "40P01", "55P03"}:
            raise reference_conflict() from None
        raise
    except Exception:
        session.rollback()
        raise


def _delete_chunk_transaction(project_id: UUID, document_id: UUID, version_id: UUID,
                              chunk_id: UUID, lock_version: int, request: Request,
                              context: IdentityContext, session: Session) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required to delete chunks")
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    # Governance parents first, then Version before Chunk. Never hold Version
    # while waiting for Project owned by a tag/review/archive transaction.
    _lock_manual_edit_scope(session, version)
    chunk = session.scalar(select(Chunk).where(
        Chunk.id == chunk_id,
        Chunk.project_id == project.id,
        Chunk.document_id == document.id,
        Chunk.document_version_id == version.id,
        Chunk.status == "active",
    ).with_for_update())
    if chunk is None:
        raise AppError("chunk_not_found", "Chunk was not found", status_code=404)
    _ensure_manual_edit_allowed(session, version, lock_version)
    deleted_index = chunk.chunk_index
    lineage_id, revision = chunk.lineage_id, chunk.revision
    deleted = delete_candidate_chunk(session, version, chunk, actor_id=context.user_id,
                                     request_id=request.state.request_id)
    orphan_ids = _delete_orphan_tags(session, list(deleted.tag_ids))
    _reindex_active_chunks(session, project.id, document.id, version.id)
    version.lock_version += 1
    reconciliation = queue_chunk_artifact_reconciliation(session, version, actor_user_id=context.user_id)
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="knowledge.chunk.delete",
        resource_type="chunk",
        resource_id=chunk_id,
        result="success",
        request_id=request.state.request_id,
        summary={
            "project_id": str(project.id), "document_id": str(document.id), "document_version_id": str(version.id),
            "chunk_id": str(chunk_id), "chunk_index": deleted_index,
            "lineage_id": str(lineage_id), "revision": revision, "reconciliation_id": str(reconciliation.id),
            "orphan_tag_count": len(orphan_ids), "chat_count": deleted.chat_count,
            "validation_item_count": deleted.validation_item_count, "vector_count": deleted.vector_count,
        },
    )
    for tag_id in orphan_ids:
        add_audit(session, actor_user_id=context.user_id, action="knowledge.chunk.orphan_tag.delete",
                  resource_type="tag", resource_id=tag_id, result="success", request_id=request.state.request_id,
                  summary={"project_id": str(project.id), "document_version_id": str(version.id), "chunk_id": str(chunk_id)})
    session.commit()
    return _knowledge_detail_response(session, project, document, version, context)


@router.post("/{document_id}/versions/{version_id}/chunks/{chunk_id}/tags", response_model=KnowledgeDetailResponse)
def add_chunk_tag(project_id: UUID, document_id: UUID, version_id: UUID, chunk_id: UUID, payload: KnowledgeTagCreatePayload, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> KnowledgeDetailResponse:
    return _mutate_chunk_tag(project_id, document_id, version_id, chunk_id, payload.tag_text, "manual", request, context, session)


@router.delete("/{document_id}/versions/{version_id}/chunks/{chunk_id}/tags/{tag_id}", response_model=KnowledgeDetailResponse)
def delete_chunk_tag(project_id: UUID, document_id: UUID, version_id: UUID, chunk_id: UUID, tag_id: UUID, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    _require_tag_edit_permission(session, project.id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    _ensure_tag_mutable(session, project, version, "knowledge.chunk_tag.delete")
    chunk = _get_active_chunk(session, project.id, document.id, version.id, chunk_id)
    link = session.get(ChunkTag, (chunk.id, tag_id))
    if link is None:
        raise AppError("chunk_tag_not_found", "Chunk tag was not found", status_code=404)
    session.delete(link)
    _refresh_tag_preview(session, project, document, version)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.chunk_tag.delete", resource_type="chunk", resource_id=chunk.id, result="success", request_id=request.state.request_id, summary={"tag_id": str(tag_id)})
    session.commit()
    return _knowledge_detail_response(session, project, document, version, context)


@router.post("/{document_id}/versions/{version_id}/chunks/{chunk_id}/tags/auto", response_model=KnowledgeDetailResponse)
def auto_tag_chunk(project_id: UUID, document_id: UUID, version_id: UUID, chunk_id: UUID, payload: KnowledgeAutoTagPayload, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    _require_tag_edit_permission(session, project.id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    _ensure_tag_mutable(session, project, version, "knowledge.chunk_tag.auto")
    chunk = _get_active_chunk(session, project.id, document.id, version.id, chunk_id)
    result = _llm_tags(session, project, chunk.content, payload.max_tags, allow_empty=True, usage_purpose="chunk_auto_tag", actor_user_id=context.user_id, document_id=document.id, version_id=version.id, chunk_id=chunk.id, correlation_id=getattr(request.state, "request_id", None))
    _delete_rule_chunk_tags(session, chunk.id)
    for tag_text in _result_tags(result):
        _attach_chunk_tag(session, project.id, chunk.id, tag_text, "llm", context.user_id, _tag_metadata(result))
    _refresh_tag_preview(session, project, document, version)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.chunk_tag.auto", resource_type="chunk", resource_id=chunk.id, result="success", request_id=request.state.request_id, summary={"tag_count": len(_result_tags(result)), "llm_model_id": str(project.llm_model_id) if project.llm_model_id else None})
    session.commit()
    return _knowledge_detail_response(session, project, document, version, context)


@router.post("/{document_id}/versions/{version_id}/tags", response_model=KnowledgeDetailResponse)
def add_document_tag(project_id: UUID, document_id: UUID, version_id: UUID, payload: KnowledgeTagCreatePayload, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> KnowledgeDetailResponse:
    return _mutate_document_tag(project_id, document_id, version_id, payload.tag_text, "manual", request, context, session)


@router.delete("/{document_id}/versions/{version_id}/tags/{tag_id}", response_model=KnowledgeDetailResponse)
def delete_document_tag(project_id: UUID, document_id: UUID, version_id: UUID, tag_id: UUID, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    _require_tag_edit_permission(session, project.id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    _ensure_tag_mutable(session, project, version, "knowledge.document_tag.delete")
    link = session.get(DocumentVersionTag, (version.id, tag_id))
    if link is None:
        raise AppError("document_tag_not_found", "Document tag was not found", status_code=404)
    session.delete(link)
    _refresh_tag_preview(session, project, document, version)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.document_tag.delete", resource_type="document_version", resource_id=version.id, result="success", request_id=request.state.request_id, summary={"tag_id": str(tag_id)})
    session.commit()
    return _knowledge_detail_response(session, project, document, version, context)


@router.post("/{document_id}/versions/{version_id}/tags/auto", response_model=KnowledgeDetailResponse)
def auto_tag_document(project_id: UUID, document_id: UUID, version_id: UUID, payload: KnowledgeAutoTagPayload, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    _require_tag_edit_permission(session, project.id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    _ensure_tag_mutable(session, project, version, "knowledge.document_tag.auto")
    chunks = _active_chunks(session, project.id, document.id, version.id)
    text = "\n\n".join(chunk.content for chunk in chunks)[:12000]
    result = _llm_tags(session, project, text, payload.max_tags, usage_purpose="document_auto_tag", actor_user_id=context.user_id, document_id=document.id, version_id=version.id, correlation_id=getattr(request.state, "request_id", None))
    _delete_rule_document_tags(session, version.id)
    for tag_text in _result_tags(result):
        _attach_document_tag(session, project.id, version.id, tag_text, "llm", context.user_id, _tag_metadata(result))
    _refresh_tag_preview(session, project, document, version)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.document_tag.auto", resource_type="document_version", resource_id=version.id, result="success", request_id=request.state.request_id, summary={"tag_count": len(_result_tags(result)), "llm_model_id": str(project.llm_model_id) if project.llm_model_id else None})
    session.commit()
    return _knowledge_detail_response(session, project, document, version, context)


@router.get("/{document_id}/versions/{version_id}/original-file")
def stream_original_file(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
):
    project = _get_scoped_project(session, project_id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    remote = _stored_version_object(request, version)
    return _object_response(
        body=remote.body,
        content_type=version.mime_type or remote.content_type or _mime_type(version.canonical_extension),
        filename=version.original_file_name or f"{document.title}{version.canonical_extension or ''}",
        disposition="inline",
    )


@router.get("/{document_id}/versions/{version_id}/preview")
def stream_file_preview(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
):
    project = _get_scoped_project(session, project_id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    extension = (version.canonical_extension or "").lower()
    remote = _stored_version_object(request, version)
    if extension == ".pdf":
        return _object_response(body=remote.body, content_type="application/pdf", filename=version.original_file_name or f"{document.title}.pdf", disposition="inline")
    if extension in {".txt", ".md", ".markdown", ".csv", ".json"}:
        return _object_response(body=remote.body, content_type="text/plain; charset=utf-8", filename=version.original_file_name or f"{document.title}{extension}", disposition="inline")
    raise AppError("preview_unsupported", "Preview is not supported for this file type", status_code=415)


def _source_text(version: DocumentVersion, chunks: list[ApprovalChunkEvidence]) -> str | None:
    strategy = version.chunk_strategy or {}
    source_text = strategy.get("source_text")
    if isinstance(source_text, str) and source_text.strip():
        return source_text.strip()
    joined = "\n\n".join(chunk.content.strip() for chunk in chunks if chunk.content and chunk.content.strip())
    return joined or None


def _original_file_metadata(project_id: UUID, document_id: UUID, version: DocumentVersion) -> OriginalFileViewerMetadata:
    extension = (version.canonical_extension or "").lower()
    base = f"/projects/{project_id}/documents/{document_id}/versions/{version.id}"
    original_url = f"{base}/original-file" if version.storage_bucket and version.storage_key else None
    preview_url = f"{base}/preview" if version.storage_bucket and version.storage_key else None
    viewer_type = "download_only" if original_url else "unsupported"
    preview_status = "unavailable"
    preview_error_code = None
    markdown_source_mode = "pipeline_markdown"

    if extension == ".pdf":
        viewer_type = "download_only" if original_url else "unsupported"
        preview_status = "unavailable"
        preview_error_code = "direct_pdf_viewer_disabled"
    elif extension in {".doc", ".docx"}:
        viewer_type = "download_only" if original_url else "unsupported"
        preview_status = "unavailable"
        preview_error_code = "direct_office_viewer_disabled"
    elif extension in {".txt", ".csv", ".json"}:
        viewer_type = "download_only" if original_url else "unsupported"
        preview_status = "unavailable"
        preview_error_code = None if preview_url else "original_file_missing"
    elif extension in {".md", ".markdown"}:
        viewer_type = "markdown"
        preview_status = "available" if preview_url else "unavailable"
        preview_error_code = None if preview_url else "original_file_missing"
        markdown_source_mode = "rendered_original_raw_markdown"
    else:
        preview_error_code = "preview_unsupported"

    return OriginalFileViewerMetadata(
        original_file_name=version.original_file_name,
        extension=extension or None,
        mime_type=version.mime_type or _mime_type(extension),
        file_size=version.file_size,
        viewer_type=viewer_type,
        preview_status=preview_status,
        preview_error_code=preview_error_code,
        original_url=original_url,
        preview_url=None,
        download_url=original_url,
        markdown_source_mode=markdown_source_mode,
    )


def _document_layout(version: DocumentVersion, markdown_text: str | None = None) -> DocumentLayoutArtifact:
    strategy = version.chunk_strategy or {}
    raw = strategy.get("document_layout")
    if isinstance(raw, dict):
        hydrated = raw
        if markdown_text:
            try:
                hydrated = hydrate_document_layout_inline_markdown(raw, MarkdownStructureParser().parse(markdown_text))
            except Exception:
                hydrated = raw
        try:
            return DocumentLayoutArtifact.model_validate(hydrated)
        except Exception:
            return DocumentLayoutArtifact(status="failed", reason_code="layout_invalid", source="document_version.chunk_strategy")
    source_text = strategy.get("source_text")
    if isinstance(source_text, str) and source_text.strip():
        blocks = [_layout_block_from_text(index, content) for index, content in enumerate(_split_layout_text(source_text), start=1)]
        return DocumentLayoutArtifact(status="available", source="uploaded_text_snapshot", pages=[DocumentLayoutPage(page_number=1, width=794, height=1123, blocks=blocks)])
    return DocumentLayoutArtifact(status="missing", reason_code="layout_artifact_missing", source="document_version.chunk_strategy", pages=[])


def _split_layout_text(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _layout_block_from_text(index: int, content: str) -> DocumentLayoutBlock:
    stripped = content.strip()
    heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
    if heading:
        return DocumentLayoutBlock(id=f"paragraph-{index}", type="heading", source_anchor=f"paragraph-{index}", text=heading.group(2), level=len(heading.group(1)), confidence=1.0)
    if re.match(r"^[-*]\s+", stripped):
        items = [re.sub(r"^[-*]\s+", "", line.strip()) for line in stripped.splitlines() if line.strip()]
        return DocumentLayoutBlock(id=f"paragraph-{index}", type="list", source_anchor=f"paragraph-{index}", items=items, confidence=1.0)
    return DocumentLayoutBlock(id=f"paragraph-{index}", type="paragraph", source_anchor=f"paragraph-{index}", text=stripped, confidence=1.0)


def _scoped_document_version(session: Session, project_id: UUID, document_id: UUID, version_id: UUID) -> tuple[Document, DocumentVersion]:
    document = session.get(Document, document_id)
    version = session.get(DocumentVersion, version_id)
    if document is None or version is None or document.project_id != project_id or version.project_id != project_id or version.document_id != document.id or document.is_deleted or document.status == "deleted":
        raise AppError("document_version_not_found", "Document version was not found", status_code=404)
    return document, version


def _is_review_locked(version: DocumentVersion) -> bool:
    return version.status in REVIEW_LOCKED_VERSION_STATUSES


def _ensure_not_review_locked(version: DocumentVersion, action: str) -> None:
    if not _is_review_locked(version):
        return
    raise AppError(
        "document_version_review_locked",
        "Document version is locked while it is in review or waiting for publish",
        status_code=409,
        details={"version_id": str(version.id), "status": version.status, "action": action},
    )


def _stored_version_object(request: Request, version: DocumentVersion):
    if not version.storage_bucket or not version.storage_key:
        raise AppError("original_file_unavailable", "Original file is unavailable", status_code=404)
    storage = S3ObjectStorage(request.app.state.settings)
    return storage.get_object(bucket=version.storage_bucket, key=version.storage_key, max_bytes=request.app.state.settings.max_upload_size_mb * 1024 * 1024)


def _object_response(*, body: bytes, content_type: str, filename: str, disposition: str) -> StreamingResponse:
    safe_filename = filename.replace("\r", "").replace("\n", "")
    encoded = quote(safe_filename)
    return StreamingResponse(
        iter([body]),
        media_type=content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _mime_type(extension: str | None) -> str:
    if extension == ".pdf":
        return "application/pdf"
    if extension == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if extension == ".doc":
        return "application/msword"
    if extension in {".txt", ".md", ".markdown", ".csv", ".json"}:
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


@router.post("/{document_id}/versions/{version_id}/pipelines/{pipeline_id}/retry", response_model=PipelineRunDetail)
def retry_pipeline(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    pipeline_id: UUID,
    payload: RetryPipelineStepPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> PipelineRunDetail:
    project = _get_scoped_project(session, project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required to retry extraction")
    document, version, pipeline = _scoped_document_version_pipeline(session, project.id, document_id, version_id, pipeline_id)
    _ensure_not_review_locked(version, "document.pipeline.retry")
    pipeline = retry_failed_step(session=session, settings=request.app.state.settings, project=project, document=document, version=version, pipeline=pipeline, step_name=payload.step_name)
    add_audit(session, actor_user_id=context.user_id, action="document.pipeline.retry", resource_type="pipeline_run", resource_id=pipeline.id, result="success", request_id=request.state.request_id, summary={"document_id": str(document.id), "version_id": str(version.id), "step_name": payload.step_name})
    session.commit()
    return _pipeline_detail(pipeline)


def _knowledge_detail_response(session: Session, project: Project, document: Document, version: DocumentVersion, context: IdentityContext) -> KnowledgeDetailResponse:
    pipeline = session.scalar(select(PipelineRun).where(PipelineRun.document_id == document.id, PipelineRun.document_version_id == version.id).order_by(PipelineRun.created_at.desc()).limit(1))
    chunks = _active_chunks(session, project.id, document.id, version.id)
    pipeline_detail = _pipeline_detail(pipeline) if pipeline else None
    markdown_artifact = resolve_markdown_artifact(session, version)
    chunk_evidence = [_chunk_evidence(session, chunk, markdown_artifact.text) for chunk in chunks]
    source_text = _source_text(version, chunk_evidence)
    markdown_available_count = sum(1 for chunk in chunk_evidence if chunk.markdown_content)
    missing_markdown_count = len(chunk_evidence) - markdown_available_count
    manual_edit_enabled, manual_edit_reason = _manual_edit_state(session, version, pipeline, context)
    artifact_status, next_stage_allowed, next_stage_block_reason = chunk_artifact_state(version, len(chunks), session=session)
    published_ready = document.status == "active" and version.status == "active" and project.status == "active" and bool(session.scalar(
        select(ActiveVersionManifest.id).where(ActiveVersionManifest.project_id == project.id,
            ActiveVersionManifest.document_id == document.id, ActiveVersionManifest.document_version_id == version.id,
            ActiveVersionManifest.index_ready.is_(True)).limit(1)))
    has_history = bool(session.scalar(select(ChatRecord.id).where(ChatRecord.project_id == project.id,
        ChatRecord.document_version_id == version.id, ChatRecord.scope_mode == "document_staging",
        ChatRecord.deleted_at.is_(None)).limit(1)))
    chat_access = {"mode": "published" if published_ready else "staging" if next_stage_allowed else "history_only" if has_history else "unavailable",
        "document_version_id": version.id, "query_enabled": published_ready or next_stage_allowed,
        "reason_code": None if published_ready or next_stage_allowed else next_stage_block_reason}
    return KnowledgeDetailResponse(
        document=_project_document(session, document, version, pipeline, expose_storage=False, visible_project_ids=set(context.visible_project_ids), capabilities=project_capabilities(session, project, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids))),
        version=_version_summary(version, expose_storage=False),
        pipeline=pipeline_detail,
        original_file=_original_file_metadata(project.id, document.id, version),
        document_layout=_document_layout(version, markdown_artifact.text),
        source_text=source_text,
        markdown_text=markdown_artifact.text,
        markdown_artifact_status=markdown_artifact.status,
        markdown_artifact_reason_code=markdown_artifact.reason_code,
        source_mapping_available=any(bool(chunk.source_mapping) for chunk in chunk_evidence),
        markdown_available_count=markdown_available_count,
        missing_markdown_count=missing_markdown_count,
        manual_edit_enabled=manual_edit_enabled,
        manual_edit_reason=manual_edit_reason,
        tag_edit_reason=("review_locked" if _is_review_locked(version) else "published_tag_revision_required" if version.published_at is not None or version.status in {"active", "inactive"} else None),
        active_chunk_count=len(chunks),
        chunk_artifact_status=artifact_status,
        next_stage_allowed=next_stage_allowed,
        next_stage_block_reason=next_stage_block_reason,
        chat_access=chat_access,
        document_tags=_document_tag_details(session, version.id),
        chunks=chunk_evidence,
    )


def _manual_edit_state(session: Session, version: DocumentVersion, pipeline: PipelineRun | None, context: IdentityContext) -> tuple[bool, str | None]:
    if _is_review_locked(version):
        return False, "review_locked"
    if not has_project_role(session, version.project_id, context.user_id, PROJECT_EDITOR_ROLES):
        return False, "permission_denied"
    if version.status != "submission_ready":
        return False, "version_not_editable"
    if pipeline is not None and pipeline.status in {"queued", "running", "processing"}:
        return False, "pipeline_running"
    return True, None


def _lock_manual_edit_scope(session: Session, version: DocumentVersion) -> None:
    project, document, current = lock_chunk_write_scope(session, version)
    if project is None or project.status != "active":
        raise AppError("project_archived", "Archived projects cannot edit chunks", status_code=409)
    if document is None or document.is_deleted or document.status == "deleted" or current is None:
        raise AppError("document_version_not_found", "Document version was not found", status_code=404)


def _ensure_manual_edit_allowed(session: Session, version: DocumentVersion, lock_version: int) -> None:
    _lock_manual_edit_scope(session, version)
    if version.lock_version != lock_version:
        raise AppError("stale_document_version", "Document version was changed by another request", status_code=409)
    _ensure_not_review_locked(version, "knowledge.chunk.manual_create")
    if version.status != "submission_ready":
        raise AppError("document_version_not_editable", "Only a submission-ready candidate version can be edited", status_code=409)
    pipeline = session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version.id).order_by(PipelineRun.created_at.desc()).limit(1))
    if pipeline is not None and pipeline.status in {"queued", "running", "processing"}:
        raise AppError("manual_edit_pipeline_running", "Manual chunk editing is unavailable while the pipeline is running", status_code=409)


def _active_chunks(session: Session, project_id: UUID, document_id: UUID, version_id: UUID) -> list[Chunk]:
    return list(
        session.scalars(
            select(Chunk)
            .where(Chunk.project_id == project_id, Chunk.document_id == document_id, Chunk.document_version_id == version_id, Chunk.status == "active")
            .order_by(Chunk.chunk_index, Chunk.created_at)
        )
    )


def _get_active_chunk(session: Session, project_id: UUID, document_id: UUID, version_id: UUID, chunk_id: UUID) -> Chunk:
    chunk = session.scalar(select(Chunk).where(Chunk.id == chunk_id, Chunk.project_id == project_id, Chunk.document_id == document_id, Chunk.document_version_id == version_id, Chunk.status == "active"))
    if chunk is None:
        raise AppError("chunk_not_found", "Chunk was not found", status_code=404)
    return chunk


def _delete_orphan_tags(session: Session, candidate_tag_ids: list[UUID]) -> list[UUID]:
    deleted_ids: list[UUID] = []
    for tag_id in sorted(set(candidate_tag_ids), key=str):
        tag = session.scalar(select(Tag).where(Tag.id == tag_id).with_for_update())
        if tag is None:
            continue
        still_used = session.scalar(select(exists().where(ChunkTag.tag_id == tag_id))) or session.scalar(select(exists().where(DocumentVersionTag.tag_id == tag_id)))
        if still_used:
            continue
        session.delete(tag)
        session.flush()
        deleted_ids.append(tag_id)
    return deleted_ids




def _chunk_offsets(chunk: Chunk) -> tuple[int | None, int | None]:
    if chunk.start_offset is not None and chunk.end_offset is not None:
        return chunk.start_offset, chunk.end_offset
    for mapping in chunk.source_mapping or []:
        if not isinstance(mapping, dict):
            continue
        start = mapping.get("markdown_start_offset", mapping.get("start_offset", mapping.get("start")))
        end = mapping.get("markdown_end_offset", mapping.get("end_offset", mapping.get("end")))
        if isinstance(start, int) and isinstance(end, int):
            return start, end
    return None, None


def _same_source_anchor(chunk: Chunk, source_anchor: str) -> bool:
    for mapping in chunk.source_mapping or []:
        if isinstance(mapping, dict) and mapping.get("source_anchor") == source_anchor:
            return True
    return source_anchor in {"original-document", "markdown-document"}


def _manual_split_text(chunk: Chunk) -> str:
    return chunk.markdown_content or chunk.content


def _split_chunk(
    chunk: Chunk,
    start: int,
    end: int,
    segment: str,
    actor_user_id: UUID,
    resolved_mapping: dict[str, object] | None = None,
    *,
    document_title: str | None = None,
    canonical_markdown: str | None = None,
    config_snapshot: dict[str, object] | None = None,
) -> Chunk:
    resolved_mapping = resolved_mapping or next((item for item in (chunk.source_mapping or []) if isinstance(item, dict)), {})
    text = canonical_markdown if canonical_markdown is not None else _manual_split_text(chunk)
    source_start = resolved_mapping.get("markdown_start_offset")
    source_end = resolved_mapping.get("markdown_end_offset")
    if canonical_markdown is not None:
        raw_markdown = canonical_markdown[max(0, start):max(0, end)]
    elif isinstance(source_start, int) and not isinstance(source_start, bool) and isinstance(source_end, int) and not isinstance(source_end, bool) and source_end > source_start:
        rel_start = max(0, min(len(text), start - source_start))
        rel_end = max(rel_start, min(len(text), end - source_start))
        raw_markdown = text[rel_start:rel_end]
    else:
        chunk_start = chunk.start_offset if isinstance(chunk.start_offset, int) else start
        rel_start = max(0, min(len(text), start - chunk_start))
        rel_end = max(rel_start, min(len(text), end - chunk_start))
        raw_markdown = text[rel_start:rel_end]
    representation = build_manual_chunk_representation(
        raw_markdown=raw_markdown,
        document_title=document_title,
        inherited_heading_path=chunk.heading_path,
        inherited_heading_level=chunk.heading_level,
        content_type=chunk.content_type,
        config_snapshot=config_snapshot,
    )
    anchor = resolved_mapping.get("source_anchor")
    anchor_source_start = source_start if isinstance(source_start, int) and not isinstance(source_start, bool) else 0
    anchor_start = int(resolved_mapping.get("anchor_start_offset") or 0) + max(0, start - anchor_source_start)
    anchor_end = anchor_start + max(0, end - start)
    mapping = {
        **resolved_mapping,
        "source_anchor": anchor or "original-document",
        "start_offset": start,
        "end_offset": end,
        "offset_scope": "canonical_markdown",
        "offset_unit": "unicode_code_point",
        "markdown_start_offset": start,
        "markdown_end_offset": end,
        "anchor_start_offset": anchor_start,
        "anchor_end_offset": anchor_end,
        "mapping_status": "resolved",
    }
    mapping.pop("mapping_reason_code", None)
    if canonical_markdown is not None:
        mapping = resolve_manual_source_mapping(
            content=raw_markdown, markdown=canonical_markdown, source_anchor="markdown-document",
            start_offset=start, end_offset=end, offset_scope="canonical_markdown", offset_unit="unicode_code_point",
        )
        if mapping is None:
            raise AppError("chunk_source_mapping_invalid", "Split chunk source mapping is invalid", status_code=422)
    return Chunk(
        project_id=chunk.project_id,
        document_id=chunk.document_id,
        document_version_id=chunk.document_version_id,
        chunk_index=0,
        title=f"{chunk.title or 'Chunk'} ({segment})",
        content=representation.display_text,
        markdown_content=representation.raw_markdown,
        display_markdown=representation.display_markdown,
        retrieval_text=representation.retrieval_text,
        embedding_content_hash=representation.embedding_content_hash,
        content_type=representation.content_type,
        content_hash=representation.content_hash,
        section_path=" > ".join(representation.heading_path) or None,
        heading_path=list(representation.heading_path) or None,
        heading_level=representation.heading_level,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        start_offset=start,
        end_offset=end,
        source_mapping=[mapping],
        stable_chunk_key=representation.stable_chunk_key,
        chunk_strategy={**representation.processing_metadata, "source": "manual_split", "parent_chunk_id": str(chunk.id), "segment": segment},
        embedding_model_id=chunk.embedding_model_id,
        token_count=representation.token_count,
        confidence_score=chunk.confidence_score,
        status="active",
        is_manual_edited=True,
        edited_by=actor_user_id,
        lineage_id=chunk.lineage_id or chunk.id,
        parent_chunk_id=chunk.id,
        revision=(chunk.revision or 0) + 1,
        change_type="manual_split",
    )


def _manual_chunk_config_snapshot(version: DocumentVersion) -> dict[str, object] | None:
    strategy = version.chunk_strategy if isinstance(version.chunk_strategy, dict) else {}
    snapshot = strategy.get("effective_chunk_config")
    return snapshot if isinstance(snapshot, dict) else None


def _source_anchor_rank(source_anchor: str | None) -> int:
    if not source_anchor:
        return 0
    match = re.search(r"(?:paragraph|block|chunk)-(\d+)", source_anchor)
    if match:
        return int(match.group(1))
    match = re.search(r"page-(\d+)", source_anchor)
    if match:
        return int(match.group(1)) * 10_000
    return 0


def _chunk_source_sort_key(chunk: Chunk) -> tuple[int, int, int, datetime]:
    mapping = next((item for item in (chunk.source_mapping or []) if isinstance(item, dict)), {})
    source_anchor = mapping.get("source_anchor") if isinstance(mapping.get("source_anchor"), str) else None
    anchor_rank = _source_anchor_rank(source_anchor)
    paragraph = mapping.get("paragraph") if isinstance(mapping.get("paragraph"), int) else None
    page = mapping.get("page") if isinstance(mapping.get("page"), int) else None
    source_rank = anchor_rank or paragraph or ((page or 0) * 10_000) or chunk.chunk_index
    start, _ = _chunk_offsets(chunk)
    return source_rank, start if start is not None else 0, chunk.chunk_index, chunk.created_at


def _next_chunk_index(session: Session, version_id: UUID) -> int:
    max_index = session.scalar(select(func.max(Chunk.chunk_index)).where(Chunk.document_version_id == version_id))
    return (max_index or 0) + 1


def _reindex_active_chunks(session: Session, project_id: UUID, document_id: UUID, version_id: UUID) -> None:
    version_chunks = list(
        session.scalars(
            select(Chunk)
            .where(Chunk.project_id == project_id, Chunk.document_id == document_id, Chunk.document_version_id == version_id, Chunk.status == "active")
            .order_by(Chunk.chunk_index, Chunk.created_at)
        )
    )
    active_chunks = sorted([chunk for chunk in version_chunks if chunk.status == "active"], key=_chunk_source_sort_key)
    min_index = min((chunk.chunk_index for chunk in version_chunks), default=0)
    temporary_base = min(min_index, 0) - len(version_chunks) - 1_000
    for index, chunk in enumerate(version_chunks, start=1):
        chunk.chunk_index = temporary_base - index
    session.flush()
    for index, chunk in enumerate(active_chunks, start=1):
        chunk.chunk_index = index
    session.flush()


def _tag_details_query(session: Session, source_model, link_filter) -> list[KnowledgeTagResponse]:
    rows = session.execute(select(source_model, Tag).join(Tag, source_model.tag_id == Tag.id).where(link_filter, source_model.source != "rule").order_by(Tag.name)).all()
    return [
        KnowledgeTagResponse(
            tag_id=tag.id,
            tag_text=tag.name,
            source=link.source,
            confidence_score=float(link.confidence_score) if link.confidence_score is not None else None,
            metadata=link.metadata_ or {},
            created_by=link.created_by,
            created_at=link.created_at,
        )
        for link, tag in rows
    ]


def _chunk_tag_details(session: Session, chunk_id: UUID) -> list[KnowledgeTagResponse]:
    return _tag_details_query(session, ChunkTag, ChunkTag.chunk_id == chunk_id)


def _document_tag_details(session: Session, version_id: UUID) -> list[KnowledgeTagResponse]:
    return _tag_details_query(session, DocumentVersionTag, DocumentVersionTag.document_version_id == version_id)


def _delete_rule_chunk_tags(session: Session, chunk_id: UUID) -> None:
    session.execute(delete(ChunkTag).where(ChunkTag.chunk_id == chunk_id, ChunkTag.source == "rule"))


def _delete_rule_document_tags(session: Session, version_id: UUID) -> None:
    session.execute(delete(DocumentVersionTag).where(DocumentVersionTag.document_version_id == version_id, DocumentVersionTag.source == "rule"))


def _normalize_tag_text(tag_text: str) -> str:
    normalized = re.sub(r"\s+", " ", tag_text).strip()
    if not normalized:
        raise AppError("tag_text_blank", "Tag text cannot be blank", status_code=422)
    return normalized[:80]


def _ensure_tag_mutable(session: Session, project: Project, version: DocumentVersion, action: str) -> None:
    # Same lock order as formal graph synchronization; close publish/tag races.
    current = session.scalar(select(Project).where(Project.id == project.id).with_for_update().execution_options(populate_existing=True))
    if current is None or current.status != "active":
        raise AppError("project_archived", "Archived projects cannot edit tags", status_code=409)
    document = session.scalar(select(Document).where(Document.id == version.document_id).with_for_update().execution_options(populate_existing=True))
    if document is None or document.project_id != project.id or document.is_deleted:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    session.refresh(version, with_for_update=True)
    _ensure_not_review_locked(version, action)
    if version.published_at is not None or version.status in {"active", "inactive"}:
        raise AppError("published_tag_revision_required", "Published tags require a new reviewed version", status_code=409)


def _refresh_tag_preview(session: Session, project: Project, document: Document, version: DocumentVersion) -> None:
    from app.domain.extraction_pipeline import _graph_preview_artifact
    session.flush()
    version.chunk_strategy = {**(version.chunk_strategy or {}),
        "graph_tag_revision": int((version.chunk_strategy or {}).get("graph_tag_revision") or 0) + 1}
    version.chunk_strategy = {**version.chunk_strategy, "graph_preview": _graph_preview_artifact(
        session, project, document, version, _active_chunks(session, project.id, document.id, version.id))}


def _require_tag_edit_permission(session: Session, project_id: UUID, context: IdentityContext) -> None:
    require_project_role(session, project_id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required to edit tags")


def _get_or_create_tag(session: Session, project_id: UUID, tag_text: str) -> Tag:
    normalized = _normalize_tag_text(tag_text)
    tag = session.scalar(select(Tag).where(Tag.project_id == project_id, Tag.name == normalized))
    if tag is not None:
        return tag
    tag = Tag(project_id=project_id, name=normalized, created_at=datetime.now(UTC))
    session.add(tag)
    session.flush()
    return tag


def _attach_chunk_tag(session: Session, project_id: UUID, chunk_id: UUID, tag_text: str, source: str, actor_user_id: UUID, metadata: dict, confidence_score: float | None = None) -> None:
    tag = _get_or_create_tag(session, project_id, tag_text)
    link = session.get(ChunkTag, (chunk_id, tag.id))
    if link is None:
        session.add(ChunkTag(chunk_id=chunk_id, tag_id=tag.id, source=source, confidence_score=confidence_score, metadata_=metadata, created_by=actor_user_id, created_at=datetime.now(UTC)))
        return
    link.source = source
    link.confidence_score = confidence_score
    link.metadata_ = metadata
    link.created_by = actor_user_id


def _attach_document_tag(session: Session, project_id: UUID, version_id: UUID, tag_text: str, source: str, actor_user_id: UUID, metadata: dict, confidence_score: float | None = None) -> None:
    tag = _get_or_create_tag(session, project_id, tag_text)
    link = session.get(DocumentVersionTag, (version_id, tag.id))
    if link is None:
        session.add(DocumentVersionTag(document_version_id=version_id, tag_id=tag.id, source=source, confidence_score=confidence_score, metadata_=metadata, created_by=actor_user_id, created_at=datetime.now(UTC)))
        return
    link.source = source
    link.confidence_score = confidence_score
    link.metadata_ = metadata
    link.created_by = actor_user_id


def _mutate_chunk_tag(project_id: UUID, document_id: UUID, version_id: UUID, chunk_id: UUID, tag_text: str, source: str, request: Request, context: IdentityContext, session: Session) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    _require_tag_edit_permission(session, project.id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    _ensure_tag_mutable(session, project, version, "knowledge.chunk_tag.add")
    chunk = _get_active_chunk(session, project.id, document.id, version.id, chunk_id)
    _attach_chunk_tag(session, project.id, chunk.id, tag_text, source, context.user_id, {"source": source})
    _refresh_tag_preview(session, project, document, version)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.chunk_tag.add", resource_type="chunk", resource_id=chunk.id, result="success", request_id=request.state.request_id, summary={"tag_text": _normalize_tag_text(tag_text), "source": source})
    session.commit()
    return _knowledge_detail_response(session, project, document, version, context)


def _mutate_document_tag(project_id: UUID, document_id: UUID, version_id: UUID, tag_text: str, source: str, request: Request, context: IdentityContext, session: Session) -> KnowledgeDetailResponse:
    project = _get_scoped_project(session, project_id, context)
    _require_tag_edit_permission(session, project.id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    _ensure_tag_mutable(session, project, version, "knowledge.document_tag.add")
    _attach_document_tag(session, project.id, version.id, tag_text, source, context.user_id, {"source": source})
    _refresh_tag_preview(session, project, document, version)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.document_tag.add", resource_type="document_version", resource_id=version.id, result="success", request_id=request.state.request_id, summary={"tag_text": _normalize_tag_text(tag_text), "source": source})
    session.commit()
    return _knowledge_detail_response(session, project, document, version, context)


def _llm_tags(
    session: Session,
    project: Project,
    text: str,
    max_tags: int,
    *,
    allow_empty: bool = False,
    usage_purpose: str,
    actor_user_id: UUID,
    document_id: UUID,
    version_id: UUID,
    chunk_id: UUID | None = None,
    correlation_id: str | None = None,
):
    model = None
    if project.llm_model_id:
        model = session.get(AIModel, project.llm_model_id)
    if model is None or model.model_type != "Chat" or not model.is_active or model.deleted_at is not None:
        model = session.scalar(select(AIModel).where(AIModel.model_type == "Chat", AIModel.is_active.is_(True), AIModel.is_default.is_(True), AIModel.deleted_at.is_(None)).limit(1))
    if model is None:
        raise AppError("chat_model_required", "An active Chat LLM model is required for auto tagging", status_code=409)
    prompt = resolve_system_prompt(session, model=model, model_type="Chat")
    started = perf_counter()
    try:
        result = generate_knowledge_tags(text=text, model=model, max_tags=max_tags, system_prompt=prompt, allow_empty=allow_empty)
    except AppError as exc:
        record_model_usage(
            session,
            model=model,
            usage_purpose=usage_purpose,
            source_channel="knowledge_detail",
            status="failed",
            error_code=exc.code,
            latency_ms=max(0, int((perf_counter() - started) * 1000)),
            project_id=project.id,
            document_id=document_id,
            document_version_id=version_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
            metadata={"chunk_id": str(chunk_id)} if chunk_id else {"scope": "document"},
        )
        session.commit()
        raise
    record_model_usage(
        session,
        model=model,
        usage_purpose=usage_purpose,
        source_channel="knowledge_detail",
        status="success",
        token_usage=result.token_usage,
        latency_ms=max(0, int((perf_counter() - started) * 1000)),
        project_id=project.id,
        document_id=document_id,
        document_version_id=version_id,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
        metadata={"chunk_id": str(chunk_id)} if chunk_id else {"scope": "document"},
    )
    return result


def _result_tags(result) -> list[str]:
    try:
        parsed = json.loads(result.answer)
    except json.JSONDecodeError as exc:
        raise AppError("tagging_response_invalid", "Tagging response JSON is invalid", status_code=502) from exc
    if not isinstance(parsed, list):
        raise AppError("tagging_response_invalid", "Tagging response must be a JSON array", status_code=502)
    return [_normalize_tag_text(str(item)) for item in parsed if str(item).strip()]


def _tag_metadata(result) -> dict:
    return {
        "system_prompt_source": result.system_prompt_source,
        "system_prompt_version_id": str(result.system_prompt_version_id) if result.system_prompt_version_id else None,
        "system_prompt_content_hash": result.system_prompt_content_hash,
        "system_prompt_layers": result.system_prompt_layers,
        "prompt_version": result.prompt_version,
        "token_usage": result.token_usage,
    }


def _chunk_evidence(session: Session, chunk: Chunk, markdown_text: str | None = None) -> ApprovalChunkEvidence:
    tag_details = _chunk_tag_details(session, chunk.id)
    return ApprovalChunkEvidence(
        id=chunk.id,
        chunk_index=chunk.chunk_index,
        title=chunk.title,
        content=chunk.content,
        markdown_content=chunk.markdown_content,
        display_markdown=chunk.display_markdown,
        retrieval_text=chunk.retrieval_text,
        embedding_content_hash=chunk.embedding_content_hash,
        content_type=chunk.content_type,
        heading_path=list(chunk.heading_path or []),
        heading_level=chunk.heading_level,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        sequence=chunk.sequence,
        stable_chunk_key=chunk.stable_chunk_key,
        source_mapping=normalize_source_mappings(chunk.content, chunk.source_mapping, markdown_text),
        token_count=chunk.token_count,
        confidence_score=float(chunk.confidence_score) if chunk.confidence_score is not None else None,
        lineage_id=chunk.lineage_id or chunk.id,
        parent_chunk_id=chunk.parent_chunk_id,
        revision=chunk.revision,
        change_type=chunk.change_type,
        tags=[tag.tag_text for tag in tag_details],
        tag_details=tag_details,
    )


def _project_document(
    session: Session,
    document: Document,
    version: DocumentVersion | None,
    pipeline: PipelineRun | None,
    *,
    expose_storage: bool = True,
    visible_project_ids: set[UUID] | None = None,
    capabilities: dict[str, bool] | None = None,
    summary_metadata: dict | None = None,
) -> DocumentSummary:
    metadata = summary_metadata if summary_metadata is not None else document_summary_metadata(session, document.project_id, [document.id])
    versions = list(
        session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id, DocumentVersion.project_id == document.project_id)
            .order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at))
        )
    )
    return DocumentSummary(
        id=document.id,
        project_id=document.project_id,
        document_code=document.document_code,
        title=document.title,
        source_type=document.source_type,
        status=document.status,
        created_by=document.created_by,
        created_by_name=metadata["creators"].get(document.id),
        lock_version=document.lock_version,
        created_at=document.created_at,
        updated_at=document.updated_at,
        latest_version=_version_summary(version, expose_storage=expose_storage, metadata=metadata["versions"].get(version.id)) if version else None,
        versions=[_version_summary(row, expose_storage=expose_storage, metadata=metadata["versions"].get(row.id)) for row in versions],
        latest_pipeline=_pipeline_summary(pipeline) if pipeline else None,
        service_source=_service_source_summary(session, document),
        reference_source=_reference_source_summary(session, document, version, visible_project_ids),
        capabilities=capabilities or {},
    )


def _service_source_summary(session: Session, document: Document) -> DocumentServiceSourceSummary | None:
    connections = list(session.scalars(select(DataConnection).where(DataConnection.project_id == document.project_id)))
    for connection in connections:
        source_identity = connection.source_identity or {}
        if str(source_identity.get("document_id") or "") != str(document.id):
            continue
        location = str(source_identity.get("remote_uri") or source_identity.get("url") or source_identity.get("remote_path") or connection.name)
        file_name = str(source_identity.get("file_name") or "")
        if file_name and file_name not in location:
            location = f"{location.rstrip('/')}/{file_name}" if location else file_name
        return DocumentServiceSourceSummary(
            data_source_id=connection.id,
            service_type=connection.service_type,
            location=location,
            schedule_mode=connection.schedule_mode,
            cron_expression=connection.cron_expression,
            timezone=connection.timezone,
        )
    return None


def _reference_source_summary(session: Session, document: Document, version: DocumentVersion | None, visible_project_ids: set[UUID] | None) -> DocumentReferenceSourceSummary | None:
    reference = session.scalar(
        select(DocumentReference)
        .where(DocumentReference.target_document_id == document.id, DocumentReference.status != "detached")
        .order_by(desc(DocumentReference.updated_at), desc(DocumentReference.created_at))
        .limit(1)
    )
    if reference is None and (version is None or version.source_document_id is None or version.source_version_id is None):
        return None
    copied_source_document = session.get(Document, version.source_document_id) if reference is None and version and version.source_document_id else None
    source_project_id = reference.source_project_id if reference else copied_source_document.project_id if copied_source_document else None
    source_document_id = reference.source_document_id if reference else version.source_document_id  # type: ignore[union-attr]
    source_version_id = reference.source_version_id if reference else version.source_version_id  # type: ignore[union-attr]
    if source_project_id is None or source_document_id is None or source_version_id is None:
        return None
    source_project = session.get(Project, source_project_id)
    source_document = session.get(Document, source_document_id)
    source_version = session.get(DocumentVersion, source_version_id)
    latest_active = session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == source_document_id, DocumentVersion.status == "active")
        .order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at))
        .limit(1)
    )
    pending_count = 0
    detected_at = None
    if reference is not None:
        pending_count = session.scalar(select(func.count()).select_from(DocumentReferenceEvent).where(DocumentReferenceEvent.reference_id == reference.id, DocumentReferenceEvent.resolved_at.is_(None))) or 0
        latest_event = session.scalar(select(DocumentReferenceEvent).where(DocumentReferenceEvent.reference_id == reference.id).order_by(desc(DocumentReferenceEvent.created_at)).limit(1))
        detected_at = latest_event.created_at if latest_event else reference.last_synced_at or reference.updated_at
    has_access = source_project_id in visible_project_ids if visible_project_ids is not None else source_document is not None
    return DocumentReferenceSourceSummary(
        reference_id=reference.id if reference else None,
        source_project_id=source_project_id,
        source_document_id=source_document_id,
        source_version_id=source_version_id,
        project_name=source_project.name if source_project else (reference.source_project_name_snapshot if reference else ""),
        document_name=source_document.title if source_document else (reference.source_document_name_snapshot if reference else ""),
        snapshot_version=source_version.version_label if source_version else (version.version_label if version else ""),
        latest_active_version=latest_active.version_label if latest_active else None,
        has_access=has_access,
        status=reference.status if reference else "copied",
        detected_at=detected_at,
        pending_event_count=int(pending_count),
    )


def _lifecycle_impact(session: Session, document: Document, requested_status: str) -> LifecycleImpactResponse:
    reference_count = session.scalar(select(func.count()).select_from(DocumentReference).where(DocumentReference.source_document_id == document.id, DocumentReference.status == "active")) or 0
    active_version_count = session.scalar(select(func.count()).select_from(ActiveVersionManifest).where(ActiveVersionManifest.document_id == document.id, ActiveVersionManifest.index_ready.is_(True))) or 0
    requires_confirmation = requested_status in {"inactive", "deleted"} and (reference_count > 0 or active_version_count > 0)
    return LifecycleImpactResponse(document_id=document.id, requested_status=requested_status, impacted_reference_count=reference_count, impacted_active_version_count=active_version_count, requires_confirmation=requires_confirmation)


def _version_summary(version: DocumentVersion, *, expose_storage: bool = True, metadata: dict | None = None) -> DocumentVersionSummary:
    return DocumentVersionSummary(
        id=version.id,
        **(metadata or {}),
        version_label=version.version_label,
        status=version.status,
        original_file_name=version.original_file_name,
        canonical_extension=version.canonical_extension,
        mime_type=version.mime_type,
        file_size=version.file_size,
        storage_bucket=version.storage_bucket if expose_storage else None,
        storage_key=version.storage_key if expose_storage else None,
        ocr_model_id=version.ocr_model_id,
        ocr_config_version=version.ocr_config_version,
        lock_version=version.lock_version,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _pipeline_summary(pipeline: PipelineRun) -> PipelineSummary:
    session = Session.object_session(pipeline)
    return PipelineSummary(id=pipeline.id, status=pipeline.status, progress_percent=float(pipeline.progress_percent), current_step_name=pipeline.current_step_name, error_message=pipeline.error_message, started_at=pipeline.started_at, completed_at=pipeline.completed_at,
        execution=execution_projection(session, pipeline.id) if session else None)


def _pipeline_detail(pipeline: PipelineRun) -> PipelineRunDetail:
    steps = sorted(list(pipeline_steps_cache(pipeline)), key=lambda step: _step_order(step.step_name))
    return PipelineRunDetail(
        id=pipeline.id,
        project_id=pipeline.project_id,
        document_id=pipeline.document_id,
        document_version_id=pipeline.document_version_id,
        run_type=pipeline.run_type,
        status=pipeline.status,
        progress_percent=float(pipeline.progress_percent),
        current_step_name=pipeline.current_step_name,
        error_message=pipeline.error_message,
        started_at=pipeline.started_at,
        completed_at=pipeline.completed_at,
        steps=[_step_summary(step) for step in steps],
        execution=_pipeline_summary(pipeline).execution,
    )


def pipeline_steps_cache(pipeline: PipelineRun) -> list[PipelineRunStep]:
    session = Session.object_session(pipeline)
    if session is None:
        return []
    return list(session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id)))


def _step_summary(step: PipelineRunStep) -> PipelineStepSummary:
    return PipelineStepSummary(
        id=step.id,
        step_name=step.step_name,
        status=step.status,
        progress_percent=float(step.progress_percent),
        progress_message=step.progress_message,
        retry_count=step.retry_count,
        output_artifact_ref=step.output_artifact_ref,
        started_at=step.started_at,
        completed_at=step.completed_at,
        error_message=step.error_message,
    )


def _step_order(step_name: str) -> int:
    order = [
        "upload_received",
        "parse_document",
        "ocr_extract",
        "split_paragraphs",
        "chunk_knowledge",
        "generate_markdown",
        "auto_tag",
        "build_embeddings",
        "build_staging_index",
        "build_graph_preview",
        "prepare_submission",
        "manager_review",
        "owner_review",
        "publish",
        "production_index",
        "graph_sync",
    ]
    return order.index(step_name) if step_name in order else len(order)


def _scoped_document_version_pipeline(session: Session, project_id: UUID, document_id: UUID, version_id: UUID, pipeline_id: UUID) -> tuple[Document, DocumentVersion, PipelineRun]:
    document = session.get(Document, document_id)
    version = session.get(DocumentVersion, version_id)
    pipeline = session.get(PipelineRun, pipeline_id)
    if (
        document is None
        or version is None
        or pipeline is None
        or document.project_id != project_id
        or version.project_id != project_id
        or pipeline.project_id != project_id
        or version.document_id != document.id
        or pipeline.document_id != document.id
        or pipeline.document_version_id != version.id
    ):
        raise AppError("pipeline_not_found", "Pipeline was not found", status_code=404)
    return document, version, pipeline


def _optional_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise AppError("invalid_ocr_model", "OCR model id must be a UUID", status_code=422) from exc
