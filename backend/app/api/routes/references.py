from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.routes.documents import _pipeline_summary, _project_document
from app.domain.project_access import get_scoped_project as _get_scoped_project
from app.api.schemas import (
    DocumentReferenceCreatePayload,
    DocumentReferenceEventResponse,
    DocumentReferenceImportPayload,
    DocumentReferenceImportResponse,
    DocumentReferenceImportResult,
    DocumentReferenceResponse,
    DocumentReferenceUpdatePayload,
    DocumentUpdateResponse,
    ImpactedReferenceProject,
    ImpactedReferenceProjectsResponse,
    ReferenceExistingTargetResponse,
    ReferenceSourceDocumentResponse,
    ReferenceSourceProjectResponse,
    ReferenceSourceVersionResponse,
)
from app.core.errors import AppError
from app.db.models import Chunk, ChunkTag, Document, DocumentReference, DocumentReferenceEvent, DocumentVersion, DocumentVersionTag, OutboxEvent, PipelineRun, Project, ProjectMember, ProjectOwner, Tag, User
from app.db.session import get_db
from app.domain.document_imports import resolve_ocr_model
from app.domain.notifications import resolve_business_notifications
from app.domain.extraction_pipeline import AUTO_EXTRACTION_STEPS, initialize_pipeline_steps
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import require_project_scope
from app.services.audit import add_audit


router = APIRouter(tags=["document-references"])
REFERENCE_TARGET_WRITE_ROLES = frozenset({"owner", "editor"})


@router.get("/projects/{project_id}/document-references", response_model=list[DocumentReferenceResponse])
def list_project_document_references(project_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[DocumentReference]:
    project = _get_scoped_project(session, project_id, context)
    return list(session.scalars(select(DocumentReference).where(DocumentReference.target_project_id == project.id).order_by(DocumentReference.created_at.desc())))


@router.get("/projects/{project_id}/reference-sources", response_model=list[ReferenceSourceProjectResponse])
def list_project_reference_sources(project_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[ReferenceSourceProjectResponse]:
    target_project = _get_scoped_project(session, project_id, context)
    visible_project_ids = set(context.visible_project_ids)
    projects = list(session.scalars(select(Project).where(Project.id.in_(visible_project_ids), Project.id != target_project.id, Project.status == "active").order_by(Project.name)))
    responses: list[ReferenceSourceProjectResponse] = []
    for project in projects:
        documents = list(session.scalars(select(Document).where(Document.project_id == project.id, Document.is_deleted.is_(False)).order_by(Document.title)))
        document_responses: list[ReferenceSourceDocumentResponse] = []
        for document in documents:
            versions = _eligible_source_versions(session, document.id)
            if not versions:
                continue
            owner = session.get(User, document.created_by) if document.created_by else None
            duplicate = _duplicate_reference(session, target_project.id, project.id, document.id)
            duplicate_response = None
            if duplicate is not None:
                target_document = session.get(Document, duplicate.target_document_id)
                source_version = session.get(DocumentVersion, duplicate.source_version_id)
                duplicate_response = ReferenceExistingTargetResponse(
                    target_document_id=duplicate.target_document_id,
                    target_title=target_document.title if target_document else duplicate.source_document_name_snapshot,
                    source_version_label=source_version.version_label if source_version else "",
                )
            document_responses.append(
                ReferenceSourceDocumentResponse(
                    id=document.id,
                    title=document.title,
                    owner=owner.display_name if owner else None,
                    versions=[
                        ReferenceSourceVersionResponse(
                            id=version.id,
                            version_label=version.version_label,
                            status=version.status,
                            is_active=version.status == "active",
                            created_at=version.created_at,
                        )
                        for version in versions
                    ],
                    duplicate=duplicate_response,
                )
            )
        if document_responses:
            responses.append(ReferenceSourceProjectResponse(id=project.id, name=project.name, status=project.status, documents=document_responses))
    return responses


@router.post("/projects/{project_id}/document-references", response_model=DocumentReferenceResponse, status_code=201)
def create_project_document_reference(
    project_id: UUID,
    payload: DocumentReferenceCreatePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DocumentReference:
    target_project = _get_scoped_project(session, project_id, context)
    _require_target_reference_write(session, target_project.id, context)
    source_document, source_project, source_version = _source_triplet(session, payload.source_document_id, payload.source_version_id, context)
    target_document, target_version, pipeline, reference = _create_reference_document(
        session=session,
        target_project=target_project,
        source_project=source_project,
        source_document=source_document,
        source_version=source_version,
        mode="reference",
        actor_user_id=context.user_id,
        old_version_confirmed=source_version.status == "active",
        settings=request.app.state.settings,
    )
    add_audit(session, actor_user_id=context.user_id, action="document_reference.create", resource_type="document_reference", resource_id=reference.id if reference else target_document.id, result="success", request_id=request.state.request_id, summary={"target_project_id": str(target_project.id), "target_document_id": str(target_document.id), "target_version_id": str(target_version.id), "source_document_id": str(source_document.id), "source_version_id": str(source_version.id), "pipeline_id": str(pipeline.id) if pipeline else None})
    session.commit()
    session.refresh(reference)
    return reference


@router.post("/projects/{project_id}/document-references/import", response_model=DocumentReferenceImportResponse, status_code=201)
def import_project_document_references(
    project_id: UUID,
    payload: DocumentReferenceImportPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DocumentReferenceImportResponse:
    target_project = _get_scoped_project(session, project_id, context)
    _require_target_reference_write(session, target_project.id, context)
    if payload.mode == "reference" and len(payload.items) != 1:
        raise AppError("reference_mode_single_document", "Reference mode accepts exactly one source document", status_code=422)
    results: list[DocumentReferenceImportResult] = []
    for item in payload.items:
        try:
            source_document, source_project, source_version = _source_triplet(session, item.source_document_id, item.source_version_id, context)
            target_document, target_version, pipeline, reference = _create_reference_document(
                session=session,
                target_project=target_project,
                source_project=source_project,
                source_document=source_document,
                source_version=source_version,
                mode=payload.mode,
                actor_user_id=context.user_id,
                old_version_confirmed=item.old_version_confirmed,
                settings=request.app.state.settings,
            )
            add_audit(session, actor_user_id=context.user_id, action=f"document_reference.import.{payload.mode}", resource_type="document", resource_id=target_document.id, result="success", request_id=request.state.request_id, summary={"source_document_id": str(source_document.id), "source_version_id": str(source_version.id), "target_version_id": str(target_version.id), "reference_id": str(reference.id) if reference else None})
            session.commit()
            results.append(
                DocumentReferenceImportResult(
                    status="created",
                    document=_project_document(session, target_document, target_version, pipeline, visible_project_ids=set(context.visible_project_ids)),
                    reference=reference,
                )
            )
        except AppError as exc:
            session.rollback()
            results.append(DocumentReferenceImportResult(status="failed", error_code=exc.code, message=exc.message))
    return DocumentReferenceImportResponse(results=results)


@router.post("/document-references/{reference_id}/detach", response_model=DocumentReferenceResponse)
def detach_document_reference(reference_id: UUID, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> DocumentReference:
    reference = _scoped_reference(session, reference_id, context)
    _require_target_reference_write(session, reference.target_project_id, context)
    now = datetime.now(UTC)
    reference.status = "detached"
    reference.reference_mode = "detached"
    reference.updated_at = now
    for event in session.scalars(select(DocumentReferenceEvent).where(DocumentReferenceEvent.reference_id == reference.id, DocumentReferenceEvent.resolved_at.is_(None))):
        event.is_read = True
        event.resolved_at = now
    resolve_business_notifications(session, business_key=f"document-reference:{reference.id}", reason="reference_detached")
    add_audit(session, actor_user_id=context.user_id, action="document_reference.detach", resource_type="document_reference", resource_id=reference.id, result="success", request_id=request.state.request_id, summary={"target_project_id": str(reference.target_project_id), "source_document_id": str(reference.source_document_id)})
    session.commit()
    session.refresh(reference)
    return reference


@router.post("/document-references/{reference_id}/sync", response_model=DocumentReferenceEventResponse, status_code=202)
def request_document_reference_sync(reference_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> DocumentReferenceEvent:
    reference = _scoped_reference(session, reference_id, context)
    _require_target_reference_write(session, reference.target_project_id, context)
    latest_active = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == reference.source_document_id, DocumentVersion.status == "active").order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at)).limit(1))
    event = DocumentReferenceEvent(
        id=uuid4(),
        reference_id=reference.id,
        event_type="manual_sync_requested",
        source_project_id=reference.source_project_id,
        source_document_id=reference.source_document_id,
        old_source_version_id=reference.source_version_id,
        new_source_version_id=latest_active.id if latest_active else reference.source_version_id,
        message="Reference sync requested; target project results are not overwritten automatically.",
        is_read=False,
        created_at=datetime.now(UTC),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.post("/document-references/{reference_id}/update", response_model=DocumentUpdateResponse)
def update_document_reference_version(
    reference_id: UUID,
    payload: DocumentReferenceUpdatePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DocumentUpdateResponse:
    reference = _scoped_reference(session, reference_id, context)
    _require_target_reference_write(session, reference.target_project_id, context)
    source_document, source_project, source_version = _source_triplet(session, reference.source_document_id, payload.source_version_id, context)
    if source_version.document_id != reference.source_document_id:
        raise AppError("reference_source_mismatch", "Selected source version does not belong to the referenced document", status_code=422)
    if source_version.id == reference.source_version_id:
        target_document = session.get(Document, reference.target_document_id)
        target_version = _latest_target_version(session, reference.target_document_id)
        pipeline = _latest_pipeline(session, target_version.id) if target_version else None
        return DocumentUpdateResponse(document=_project_document(session, target_document, target_version, pipeline, visible_project_ids=set(context.visible_project_ids)), latest_pipeline=_pipeline_summary(pipeline) if pipeline else None, no_change=True, message="Reference already uses the selected source version.")
    target_project = _get_scoped_project(session, reference.target_project_id, context)
    target_document = session.get(Document, reference.target_document_id)
    if target_document is None:
        raise AppError("target_document_not_found", "Referenced target document was not found", status_code=404)
    target_version, pipeline = _create_next_reference_version(
        session=session,
        target_project=target_project,
        target_document=target_document,
        source_project=source_project,
        source_document=source_document,
        source_version=source_version,
        actor_user_id=context.user_id,
        old_version_confirmed=payload.old_version_confirmed,
        settings=request.app.state.settings,
    )
    old_source_version_id = reference.source_version_id
    reference.source_version_id = source_version.id
    reference.source_project_name_snapshot = source_project.name
    reference.source_document_name_snapshot = source_document.title
    reference.last_synced_at = datetime.now(UTC)
    reference.updated_at = reference.last_synced_at
    event = DocumentReferenceEvent(
        id=uuid4(),
        reference_id=reference.id,
        event_type="source_version_changed",
        source_project_id=reference.source_project_id,
        source_document_id=reference.source_document_id,
        old_source_version_id=old_source_version_id,
        new_source_version_id=source_version.id,
        message="Reference was updated to the selected source version.",
        is_read=True,
        resolved_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    session.add(event)
    add_audit(session, actor_user_id=context.user_id, action="document_reference.update_version", resource_type="document_reference", resource_id=reference.id, result="success", request_id=request.state.request_id, summary={"target_document_id": str(target_document.id), "target_version_id": str(target_version.id), "old_source_version_id": str(old_source_version_id), "new_source_version_id": str(source_version.id)})
    session.commit()
    return DocumentUpdateResponse(document=_project_document(session, target_document, target_version, pipeline, visible_project_ids=set(context.visible_project_ids)), latest_pipeline=_pipeline_summary(pipeline) if pipeline else None, no_change=False, message="Reference updated and extraction started.")


@router.get("/document-reference-events", response_model=list[DocumentReferenceEventResponse])
def list_document_reference_events(project_id: UUID | None = None, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[DocumentReferenceEvent]:
    scoped_projects = set(context.visible_project_ids)
    if project_id is not None:
        require_project_scope(project_id, scoped_projects)
        scoped_projects = {project_id}
    return list(
        session.scalars(
            select(DocumentReferenceEvent)
            .join(DocumentReference, DocumentReference.id == DocumentReferenceEvent.reference_id)
            .where(DocumentReference.target_project_id.in_(scoped_projects))
            .order_by(DocumentReferenceEvent.created_at.desc())
            .limit(100)
        )
    )


@router.get("/document-reference-events/impacted-projects", response_model=ImpactedReferenceProjectsResponse)
def impacted_reference_projects(source_document_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ImpactedReferenceProjectsResponse:
    source_document = session.get(Document, source_document_id)
    if source_document is None:
        raise AppError("source_document_not_found", "Source document was not found", status_code=404)
    require_project_scope(source_document.project_id, set(context.visible_project_ids))
    rows = session.execute(
        select(DocumentReference.target_project_id, func.count())
        .where(DocumentReference.source_document_id == source_document.id, DocumentReference.status == "active")
        .group_by(DocumentReference.target_project_id)
    ).all()
    return ImpactedReferenceProjectsResponse(source_document_id=source_document.id, projects=[ImpactedReferenceProject(target_project_id=project_id, reference_count=int(count)) for project_id, count in rows])


@router.post("/document-reference-events/{event_id}/resolve", response_model=DocumentReferenceEventResponse)
def resolve_document_reference_event(event_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> DocumentReferenceEvent:
    event = session.get(DocumentReferenceEvent, event_id)
    if event is None:
        raise AppError("document_reference_event_not_found", "Document reference event was not found", status_code=404)
    reference = session.get(DocumentReference, event.reference_id)
    if reference is None:
        raise AppError("document_reference_not_found", "Document reference was not found", status_code=404)
    require_project_scope(reference.target_project_id, set(context.visible_project_ids))
    _require_target_reference_write(session, reference.target_project_id, context)
    event.is_read = True
    event.resolved_at = datetime.now(UTC)
    resolve_business_notifications(session, business_key=f"document-reference:{reference.id}", reason="reference_event_resolved")
    session.commit()
    session.refresh(event)
    return event


def _create_reference_document(
    *,
    session: Session,
    target_project: Project,
    source_project: Project,
    source_document: Document,
    source_version: DocumentVersion,
    mode: str,
    actor_user_id: UUID,
    old_version_confirmed: bool,
    settings,
) -> tuple[Document, DocumentVersion, PipelineRun | None, DocumentReference | None]:
    if mode == "reference" and _duplicate_reference(session, target_project.id, source_project.id, source_document.id) is not None:
        raise AppError("document_reference_duplicate", "Document reference already exists in target project", status_code=409)
    now = datetime.now(UTC)
    target_document = Document(
        id=uuid4(),
        project_id=target_project.id,
        document_code=_next_document_code(session, target_project.id),
        title=source_document.title,
        source_type="project_reference" if mode == "reference" else "project_copy",
        status="inactive",
        is_deleted=False,
        created_by=actor_user_id,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(target_document)
    session.flush()
    target_version, pipeline = _create_next_reference_version(
        session=session,
        target_project=target_project,
        target_document=target_document,
        source_project=source_project,
        source_document=source_document,
        source_version=source_version,
        actor_user_id=actor_user_id,
        old_version_confirmed=old_version_confirmed,
        settings=settings,
        mode=mode,
    )
    reference = None
    if mode == "reference":
        reference = DocumentReference(
            id=uuid4(),
            target_project_id=target_project.id,
            target_document_id=target_document.id,
            source_project_id=source_project.id,
            source_document_id=source_document.id,
            source_version_id=source_version.id,
            source_project_name_snapshot=source_project.name,
            source_document_name_snapshot=source_document.title,
            reference_mode="linked",
            status="active",
            created_by=actor_user_id,
            last_synced_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(reference)
    return target_document, target_version, pipeline, reference


def _create_next_reference_version(
    *,
    session: Session,
    target_project: Project,
    target_document: Document,
    source_project: Project,
    source_document: Document,
    source_version: DocumentVersion,
    actor_user_id: UUID,
    old_version_confirmed: bool,
    settings,
    mode: str = "reference",
) -> tuple[DocumentVersion, PipelineRun | None]:
    if source_version.status != "active" and not old_version_confirmed:
        raise AppError("old_version_confirmation_required", "Selected source version is not active and requires confirmation", status_code=422)
    latest = _latest_target_version(session, target_document.id)
    working = session.scalar(
        select(DocumentVersion.id)
        .where(
            DocumentVersion.document_id == target_document.id,
            DocumentVersion.status.in_(("quarantine", "queued", "processing", "submission_ready", "pending_manager_review", "pending_owner_review", "approved")),
        )
        .limit(1)
    )
    if working is not None:
        raise AppError("document_update_working_version_exists", "A working version already exists for this referenced document", status_code=409)
    now = datetime.now(UTC)
    major = (latest.version_major if latest else 0) + 1
    ocr_model = resolve_ocr_model(session, target_project, None)
    source_text = _source_text_for_version(session, source_version)
    version = DocumentVersion(
        id=uuid4(),
        project_id=target_project.id,
        document_id=target_document.id,
        version_major=major,
        extraction_revision=0,
        version_label=f"v{major}.0",
        status="queued",
        original_file_name=source_version.original_file_name,
        canonical_extension=".md",
        mime_type="text/markdown",
        file_size=len(source_text.encode("utf-8")) if source_text else None,
        content_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest() if source_text else None,
        uploaded_at=now,
        original_snapshot_uri=source_version.original_snapshot_uri,
        ocr_model_id=ocr_model.id,
        ocr_config_version=ocr_model.config_version,
        chunk_strategy={
            "source": "project_reference" if mode == "reference" else "project_copy",
            "reference_mode": mode,
            "source_project_id": str(source_project.id),
            "source_document_id": str(source_document.id),
            "source_version_id": str(source_version.id),
            "source_version_label": source_version.version_label,
            "source_text": source_text,
            "source_text_origin": "source_chunks",
        },
        embedding_model_id=target_project.embedding_model_id,
        llm_model_id=target_project.llm_model_id,
        source_document_id=source_document.id,
        source_version_id=source_version.id,
        source_snapshot_created_at=now,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    pipeline = PipelineRun(
        id=uuid4(),
        project_id=target_project.id,
        document_id=target_document.id,
        document_version_id=version.id,
        project_generation=target_project.work_generation,
        run_type="document_extraction",
        status="queued",
        progress_percent=0,
        triggered_by=actor_user_id,
        created_at=now,
    )
    target_document.updated_at = now
    session.add_all([version, pipeline])
    session.flush()
    initialize_pipeline_steps(session, pipeline, ocr_model_id=ocr_model.id, ocr_name=ocr_model.name, force_ocr=False)
    session.flush()
    if mode == "copy":
        _copy_source_extraction(session, target_project, source_version, version, actor_user_id)
        _mark_steps_completed_before(session, pipeline.id, "build_embeddings")
    session.add(OutboxEvent(id=uuid4(), topic="document.extraction.requested", aggregate_type="pipeline_run", aggregate_id=pipeline.id, project_id=target_project.id, project_generation=target_project.work_generation, payload={"pipeline_run_id": str(pipeline.id), "project_id": str(target_project.id), "project_generation": target_project.work_generation}, status="pending", attempts=0, available_at=now, created_at=now))
    return version, pipeline


def _source_triplet(session: Session, source_document_id: UUID, source_version_id: UUID | None, context: IdentityContext) -> tuple[Document, Project, DocumentVersion]:
    source_document = session.get(Document, source_document_id)
    if source_document is None or source_document.is_deleted:
        raise AppError("source_document_not_found", "Source document was not found", status_code=404)
    require_project_scope(source_document.project_id, set(context.visible_project_ids))
    source_project = session.get(Project, source_document.project_id)
    if source_project is None or source_project.status != "active":
        raise AppError("source_project_not_found", "Source project was not found", status_code=404)
    source_version = session.get(DocumentVersion, source_version_id) if source_version_id else _latest_source_version(session, source_document.id)
    if source_version is None or source_version.document_id != source_document.id or source_version.project_id != source_project.id:
        raise AppError("source_version_not_found", "Source document version was not found", status_code=404)
    if source_version.status not in {"active", "inactive"}:
        raise AppError("source_version_not_available", "Only active or inactive source versions can be referenced", status_code=409)
    return source_document, source_project, source_version


def _eligible_source_versions(session: Session, document_id: UUID) -> list[DocumentVersion]:
    return list(
        session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id, DocumentVersion.status.in_(("active", "inactive")))
            .order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at))
        )
    )


def _latest_source_version(session: Session, document_id: UUID) -> DocumentVersion | None:
    active = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id, DocumentVersion.status == "active").order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at)).limit(1))
    if active is not None:
        return active
    return session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at)).limit(1))


def _latest_target_version(session: Session, document_id: UUID) -> DocumentVersion | None:
    return session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(desc(DocumentVersion.version_major), desc(DocumentVersion.extraction_revision), desc(DocumentVersion.created_at)).limit(1))


def _latest_pipeline(session: Session, version_id: UUID) -> PipelineRun | None:
    return session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version_id).order_by(desc(PipelineRun.created_at)).limit(1))


def _duplicate_reference(session: Session, target_project_id: UUID, source_project_id: UUID, source_document_id: UUID) -> DocumentReference | None:
    return session.scalar(
        select(DocumentReference)
        .where(
            DocumentReference.target_project_id == target_project_id,
            DocumentReference.source_project_id == source_project_id,
            DocumentReference.source_document_id == source_document_id,
        )
        .limit(1)
    )


def _source_text_for_version(session: Session, source_version: DocumentVersion) -> str:
    chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == source_version.id, Chunk.status == "active").order_by(Chunk.chunk_index)))
    if chunks:
        return "\n\n".join((chunk.markdown_content or chunk.content).strip() for chunk in chunks if (chunk.markdown_content or chunk.content).strip())
    strategy = source_version.chunk_strategy or {}
    source_text = strategy.get("source_text") or strategy.get("parsed_text")
    if isinstance(source_text, str) and source_text.strip():
        return source_text.strip()
    raise AppError("source_version_no_extractable_text", "Source version does not have extractable text or chunks", status_code=409)


def _copy_source_extraction(session: Session, target_project: Project, source_version: DocumentVersion, target_version: DocumentVersion, actor_user_id: UUID) -> None:
    source_chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == source_version.id, Chunk.status == "active").order_by(Chunk.chunk_index)))
    chunk_map: dict[UUID, UUID] = {}
    now = datetime.now(UTC)
    for index, source_chunk in enumerate(source_chunks, start=1):
        copied = Chunk(
            id=uuid4(),
            project_id=target_project.id,
            document_id=target_version.document_id,
            document_version_id=target_version.id,
            chunk_index=index,
            title=source_chunk.title,
            content=source_chunk.content,
            markdown_content=source_chunk.markdown_content,
            content_type=source_chunk.content_type,
            content_hash=source_chunk.content_hash,
            start_offset=source_chunk.start_offset,
            end_offset=source_chunk.end_offset,
            source_mapping=source_chunk.source_mapping,
            chunk_strategy={**(source_chunk.chunk_strategy or {}), "source": "copied", "copied_from_chunk_id": str(source_chunk.id), "copied_from_version_id": str(source_version.id)},
            embedding_model_id=target_project.embedding_model_id,
            token_count=source_chunk.token_count,
            confidence_score=source_chunk.confidence_score,
            status="active",
            is_manual_edited=False,
            edited_by=None,
            created_at=now,
            updated_at=now,
        )
        session.add(copied)
        chunk_map[source_chunk.id] = copied.id
    session.flush()
    _copy_document_tags(session, target_project.id, source_version.id, target_version.id, actor_user_id)
    for source_chunk_id, copied_chunk_id in chunk_map.items():
        _copy_chunk_tags(session, target_project.id, source_chunk_id, copied_chunk_id, actor_user_id)


def _copy_document_tags(session: Session, target_project_id: UUID, source_version_id: UUID, target_version_id: UUID, actor_user_id: UUID) -> None:
    rows = session.execute(select(DocumentVersionTag, Tag).join(Tag, DocumentVersionTag.tag_id == Tag.id).where(DocumentVersionTag.document_version_id == source_version_id)).all()
    for link, tag in rows:
        target_tag = _get_or_create_tag(session, target_project_id, tag.name)
        session.add(
            DocumentVersionTag(
                document_version_id=target_version_id,
                tag_id=target_tag.id,
                source="copied",
                confidence_score=link.confidence_score,
                metadata_={**(link.metadata_ or {}), "copied_from_tag_id": str(tag.id), "original_source": link.source, "source_version_id": str(source_version_id)},
                created_by=actor_user_id,
                created_at=datetime.now(UTC),
            )
        )


def _copy_chunk_tags(session: Session, target_project_id: UUID, source_chunk_id: UUID, target_chunk_id: UUID, actor_user_id: UUID) -> None:
    rows = session.execute(select(ChunkTag, Tag).join(Tag, ChunkTag.tag_id == Tag.id).where(ChunkTag.chunk_id == source_chunk_id)).all()
    for link, tag in rows:
        target_tag = _get_or_create_tag(session, target_project_id, tag.name)
        session.add(
            ChunkTag(
                chunk_id=target_chunk_id,
                tag_id=target_tag.id,
                source="copied",
                confidence_score=link.confidence_score,
                metadata_={**(link.metadata_ or {}), "copied_from_tag_id": str(tag.id), "copied_from_chunk_id": str(source_chunk_id), "original_source": link.source},
                created_by=actor_user_id,
                created_at=datetime.now(UTC),
            )
        )


def _get_or_create_tag(session: Session, project_id: UUID, name: str) -> Tag:
    tag = session.scalar(select(Tag).where(Tag.project_id == project_id, Tag.name == name))
    if tag is not None:
        return tag
    tag = Tag(id=uuid4(), project_id=project_id, name=name[:255], created_at=datetime.now(UTC))
    session.add(tag)
    session.flush()
    return tag


def _mark_steps_completed_before(session: Session, pipeline_id: UUID, start_step: str) -> None:
    steps = list(session.scalars(select(PipelineRun).where(PipelineRun.id == pipeline_id)))
    if not steps:
        return
    from app.db.models import PipelineRunStep

    cutoff = AUTO_EXTRACTION_STEPS.index(start_step)
    now = datetime.now(UTC)
    for step in session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline_id)):
        if step.step_name in AUTO_EXTRACTION_STEPS and AUTO_EXTRACTION_STEPS.index(step.step_name) < cutoff:
            step.status = "completed"
            step.progress_percent = 100
            step.completed_at = now


def _next_document_code(session: Session, project_id: UUID) -> str:
    count = session.scalar(select(func.count()).select_from(Document).where(Document.project_id == project_id)) or 0
    return f"DOC-{count + 1:06d}"


def _require_target_reference_write(session: Session, target_project_id: UUID, context: IdentityContext) -> None:
    require_project_scope(target_project_id, set(context.visible_project_ids))
    roles = set(
        session.scalars(
            select(ProjectMember.project_role).where(
                ProjectMember.project_id == target_project_id,
                ProjectMember.user_id == context.user_id,
            )
        )
    )
    if session.get(ProjectOwner, (target_project_id, context.user_id)) is not None:
        roles.add("owner")
    if roles & REFERENCE_TARGET_WRITE_ROLES:
        return
    raise AppError("project_reference_role_required", "Owner or Editor role on the target project is required for this operation", status_code=403)


def _scoped_reference(session: Session, reference_id: UUID, context: IdentityContext) -> DocumentReference:
    reference = session.get(DocumentReference, reference_id)
    if reference is None:
        raise AppError("document_reference_not_found", "Document reference was not found", status_code=404)
    require_project_scope(reference.target_project_id, set(context.visible_project_ids))
    return reference
