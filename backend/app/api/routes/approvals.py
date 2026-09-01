from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ApprovalDecisionPayload,
    ApprovalChatEvidence,
    ApprovalChunkEvidence,
    ApprovalRejectPayload,
    ApprovalPendingPublishResponse,
    ApprovalRequestResponse,
    ApprovalRequestPage,
    ApprovalSummary,
    ApprovalTaskDetail,
    ApprovalTaskResponse,
    ApprovalTaskPage,
    DocumentLayoutArtifact,
    DocumentLayoutBlock,
    DocumentLayoutPage,
    DocumentSummary,
    DocumentVersionSummary,
    KnowledgeTagResponse,
    OriginalFileViewerMetadata,
    PublishResult,
    PublishVersionPayload,
    SwitchActiveVersionPayload,
)
from app.domain.chat_citations import compact_citation_view, hydrate_citation_groups
from app.domain.document_layout import hydrate_document_layout_inline_markdown
from app.core.errors import AppError
from app.core.cursor import cursor_filter_hash, decode_cursor, encode_cursor
from app.db.models import ActiveVersionManifest, ApprovalEvidenceManifest, ApprovalRequest, ApprovalTask, ChatRecord, Chunk, ChunkTag, Document, DocumentVersion, DocumentVersionTag, IdempotencyKey, Project, ProjectOwner, ReviewRecord, Tag, User
from app.db.session import get_db
from app.domain.public_api_controls import begin_idempotent_operation, complete_idempotent_operation
from app.domain.markdown_artifacts import normalize_source_mappings, resolve_markdown_artifact
from app.domain.markdown_structure import MarkdownStructureParser
from app.domain.review_publish import LiveNeo4jGraphSyncAdapter, LiveOpenSearchPublishedAdapter, approve_task, publish_version, reject_task, switch_active_version
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import require_project_scope


router = APIRouter(tags=["approvals"])


@router.get("/approvals/summary", response_model=ApprovalSummary)
def approval_summary(context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ApprovalSummary:
    pending = _pending_query(session, context)
    pending_rows = list(session.scalars(pending))
    my_submissions = session.scalar(select(func.count()).select_from(ApprovalRequest).join(Project, Project.id == ApprovalRequest.project_id).where(Project.status == "active", ApprovalRequest.submitter_id == context.user_id, ApprovalRequest.status.in_(("pending_manager_review", "pending_owner_review", "approved")))) or 0
    return ApprovalSummary(
        pending_total=len(pending_rows),
        pending_manager_review=sum(1 for task in pending_rows if task.review_stage == "manager_review"),
        pending_owner_review=sum(1 for task in pending_rows if task.review_stage == "owner_review"),
        my_submissions=my_submissions,
    )


@router.get("/approvals/pending", response_model=ApprovalTaskPage)
def pending_approvals(
    request: Request,
    project_id: UUID | None = None,
    document_id: UUID | None = None,
    editor_id: UUID | None = None,
    priority: str | None = Query(default=None, max_length=32),
    source_type: str | None = Query(default=None, max_length=50),
    stage: str | None = Query(default=None, max_length=32),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ApprovalTaskPage:
    return _task_page(
        session,
        request,
        context,
        namespace="approval-pending",
        statement=_pending_query(session, context),
        project_id=project_id,
        document_id=document_id,
        editor_id=editor_id,
        priority=priority,
        source_type=source_type,
        stage=stage,
        result=None,
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )


@router.get("/approvals/history", response_model=ApprovalTaskPage)
def approval_history(
    request: Request,
    project_id: UUID | None = None,
    document_id: UUID | None = None,
    editor_id: UUID | None = None,
    priority: str | None = Query(default=None, max_length=32),
    source_type: str | None = Query(default=None, max_length=50),
    stage: str | None = Query(default=None, max_length=32),
    result: str | None = Query(default=None, max_length=32),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ApprovalTaskPage:
    owner_project_ids = select(ProjectOwner.project_id).where(ProjectOwner.user_id == context.user_id)
    statement = (
        select(ApprovalTask)
        .join(Project, Project.id == ApprovalTask.project_id)
        .join(Document, Document.id == ApprovalTask.document_id)
        .join(ApprovalRequest, ApprovalRequest.id == ApprovalTask.approval_request_id)
        .where(
            Project.status == "active",
            ApprovalTask.project_id.in_(context.visible_project_ids),
            ApprovalTask.status.in_(("approved", "rejected", "cancelled")),
            or_(
                ApprovalTask.submitter_id == context.user_id,
                ApprovalTask.assignee_user_id == context.user_id,
                ApprovalTask.project_id.in_(owner_project_ids),
            ),
        )
    )
    return _task_page(
        session,
        request,
        context,
        namespace="approval-history",
        statement=statement,
        project_id=project_id,
        document_id=document_id,
        editor_id=editor_id,
        priority=priority,
        source_type=source_type,
        stage=stage,
        result=result,
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )


@router.get("/approvals/rejected", response_model=ApprovalTaskPage)
def rejected_approvals(
    request: Request,
    project_id: UUID | None = None,
    document_id: UUID | None = None,
    editor_id: UUID | None = None,
    priority: str | None = Query(default=None, max_length=32),
    source_type: str | None = Query(default=None, max_length=50),
    stage: str | None = Query(default=None, max_length=32),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ApprovalTaskPage:
    owner_project_ids = select(ProjectOwner.project_id).where(ProjectOwner.user_id == context.user_id)
    statement = (
        select(ApprovalTask)
        .join(Project, Project.id == ApprovalTask.project_id)
        .join(Document, Document.id == ApprovalTask.document_id)
        .join(ApprovalRequest, ApprovalRequest.id == ApprovalTask.approval_request_id)
        .where(
            Project.status == "active",
            ApprovalTask.project_id.in_(context.visible_project_ids),
            ApprovalTask.status == "rejected",
            or_(
                ApprovalTask.submitter_id == context.user_id,
                ApprovalTask.assignee_user_id == context.user_id,
                ApprovalTask.project_id.in_(owner_project_ids),
            ),
        )
    )
    return _task_page(
        session,
        request,
        context,
        namespace="approval-rejected",
        statement=statement,
        project_id=project_id,
        document_id=document_id,
        editor_id=editor_id,
        priority=priority,
        source_type=source_type,
        stage=stage,
        result="rejected",
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )


@router.get("/approvals/my-submissions", response_model=ApprovalRequestPage)
def my_submissions(
    request: Request,
    project_id: UUID | None = None,
    document_id: UUID | None = None,
    priority: str | None = Query(default=None, max_length=32),
    source_type: str | None = Query(default=None, max_length=50),
    result: str | None = Query(default=None, max_length=32),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ApprovalRequestPage:
    statement = (
        select(ApprovalRequest)
        .join(Project, Project.id == ApprovalRequest.project_id)
        .join(Document, Document.id == ApprovalRequest.document_id)
        .where(
            Project.status == "active",
            ApprovalRequest.project_id.in_(context.visible_project_ids),
            ApprovalRequest.submitter_id == context.user_id,
        )
    )
    return _request_page(
        session,
        request,
        context,
        statement=statement,
        project_id=project_id,
        document_id=document_id,
        priority=priority,
        source_type=source_type,
        result=result,
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )


@router.get("/approvals/pending-publish", response_model=list[ApprovalPendingPublishResponse])
def pending_publish_versions(context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[ApprovalPendingPublishResponse]:
    active_manifest_exists = select(ActiveVersionManifest.id).where(ActiveVersionManifest.document_version_id == DocumentVersion.id).exists()
    rows = session.execute(
        select(DocumentVersion, Document, Project, ApprovalRequest, User, ApprovalTask.id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(Project, Project.id == DocumentVersion.project_id)
        .join(ProjectOwner, and_(ProjectOwner.project_id == DocumentVersion.project_id, ProjectOwner.user_id == context.user_id))
        .outerjoin(ApprovalRequest, and_(ApprovalRequest.document_version_id == DocumentVersion.id, ApprovalRequest.status == "approved"))
        .outerjoin(User, User.id == ApprovalRequest.submitter_id)
        .outerjoin(ApprovalTask, and_(ApprovalTask.approval_request_id == ApprovalRequest.id, ApprovalTask.review_stage == "owner_review", ApprovalTask.status == "approved"))
        .where(
            Project.status == "active",
            DocumentVersion.project_id.in_(context.visible_project_ids),
            DocumentVersion.status == "approved",
            DocumentVersion.published_at.is_(None),
            ~active_manifest_exists,
        )
        .order_by(ApprovalRequest.approved_at.desc().nullslast(), DocumentVersion.updated_at.desc(), DocumentVersion.created_at.desc())
        .limit(100)
    )
    return [_pending_publish_response(version, document, project, request, submitter, owner_task_id) for version, document, project, request, submitter, owner_task_id in rows]


@router.get("/approval-requests", response_model=list[ApprovalRequestResponse])
def list_approval_requests(context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[ApprovalRequestResponse]:
    requests = list(session.scalars(select(ApprovalRequest).join(Project, Project.id == ApprovalRequest.project_id).where(Project.status == "active", ApprovalRequest.project_id.in_(context.visible_project_ids)).order_by(ApprovalRequest.submitted_at.desc()).limit(100)))
    return [_approval_request_response(session, request) for request in requests]


@router.get("/approval-requests/{approval_request_id}", response_model=ApprovalRequestResponse)
def get_approval_request(approval_request_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ApprovalRequestResponse:
    request = session.get(ApprovalRequest, approval_request_id)
    if request is None:
        raise AppError("approval_request_not_found", "Approval request was not found", status_code=404)
    require_project_scope(request.project_id, set(context.visible_project_ids))
    _require_active_project(session, request.project_id)
    return _approval_request_response(session, request)


@router.get("/approvals/{approval_task_id}", response_model=ApprovalTaskDetail)
def get_approval_task(approval_task_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ApprovalTaskDetail:
    task = _scoped_task(session, approval_task_id, context)
    request = session.get(ApprovalRequest, task.approval_request_id)
    document = session.get(Document, task.document_id)
    version = session.get(DocumentVersion, task.document_version_id)
    if request is None or document is None or version is None:
        raise AppError("approval_task_not_found", "Approval task was not found", status_code=404)
    latest_version = session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id, DocumentVersion.project_id == document.project_id)
        .order_by(DocumentVersion.created_at.desc())
        .limit(1)
    )
    latest_version_id = latest_version.id if latest_version is not None else version.id
    evidence_stale = latest_version_id != version.id
    read_only_reason = None
    if evidence_stale:
        read_only_reason = "version_changed"
    elif task.status != "pending":
        read_only_reason = "task_completed"
    records = list(session.scalars(select(ReviewRecord).where(ReviewRecord.document_version_id == task.document_version_id).order_by(ReviewRecord.created_at)))
    manifest_row = session.scalar(
        select(ApprovalEvidenceManifest).where(ApprovalEvidenceManifest.approval_request_id == request.id)
    )
    manifest = dict(manifest_row.manifest) if manifest_row is not None else None
    markdown_artifact = resolve_markdown_artifact(session, version)
    chunks = _manifest_chunk_evidence(manifest) if manifest is not None else _approval_chunk_evidence(session, task.document_version_id)
    chunks = [
        chunk.model_copy(update={"source_mapping": normalize_source_mappings(chunk.content, chunk.source_mapping, markdown_artifact.text)})
        for chunk in chunks
    ]
    markdown_available_count = sum(1 for chunk in chunks if chunk.markdown_content)
    missing_markdown_count = len(chunks) - markdown_available_count
    chat_records = (
        _manifest_chat_evidence(manifest)
        if manifest is not None
        else [
            ApprovalChatEvidence(
                id=row.id,
                conversation_id=row.conversation_id,
                conversation_title=row.conversation_title,
                scope_mode=row.scope_mode,
                document_version_id=row.document_version_id,
                selected_document_version_ids=sorted(_uuid_values(row.selected_document_version_ids), key=str),
                question=row.question,
                answer=row.answer,
                reference_docs=row.reference_docs,
                evaluation=row.evaluation,
                revision_suggestion=row.revision_suggestion,
                created_by=row.created_by,
                asked_at=row.asked_at,
                answered_at=row.answered_at,
            )
            for row in session.scalars(select(ChatRecord).where(ChatRecord.document_version_id == task.document_version_id, ChatRecord.scope_mode == "document_staging").order_by(ChatRecord.asked_at))
        ]
    )
    hydrated_chat_citations = hydrate_citation_groups(
        session,
        [record.reference_docs for record in chat_records],
        project_id=task.project_id,
        allowed_version_ids={task.document_version_id},
    )
    compact_chat_records: list[ApprovalChatEvidence] = []
    for record, citations in zip(chat_records, hydrated_chat_citations, strict=True):
        compact = compact_citation_view(record.answer, citations)
        compact_chat_records.append(
            ApprovalChatEvidence.model_validate(
                {
                    **record.model_dump(mode="python"),
                    "answer": compact.answer,
                    "reference_docs": compact.citations,
                }
            )
        )
    chat_records = compact_chat_records
    return ApprovalTaskDetail(
        task=task,
        request=request,
        document=_document_summary(document, version),
        version=_version_summary(version),
        latest_version_id=latest_version_id,
        evidence_stale=evidence_stale,
        read_only=evidence_stale or task.status != "pending",
        read_only_reason=read_only_reason,
        evidence_revision=manifest_row.evidence_revision if manifest_row is not None else request.evidence_revision,
        evidence_generated_at=manifest_row.generated_at if manifest_row is not None else None,
        evidence_verifiable=manifest_row is not None,
        evidence_manifest=manifest,
        original_file=_original_file_metadata(document.project_id, document.id, version),
        document_layout=_document_layout(version, markdown_artifact.text),
        source_text=_source_text(version, chunks),
        markdown_text=markdown_artifact.text,
        markdown_artifact_status=markdown_artifact.status,
        markdown_artifact_reason_code=markdown_artifact.reason_code,
        source_mapping_available=any(bool(chunk.source_mapping) for chunk in chunks),
        markdown_available_count=markdown_available_count,
        missing_markdown_count=missing_markdown_count,
        document_tags=_document_tag_details(session, version.id),
        review_records=records,
        chunks=chunks,
        chat_records=chat_records,
    )


@router.post("/approvals/{approval_task_id}/approve", response_model=ApprovalTaskResponse)
def approve(
    approval_task_id: UUID,
    payload: ApprovalDecisionPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ApprovalTaskResponse | dict[str, Any]:
    replay, idempotency_record = _begin_idempotent_operation(
        session=session,
        settings=request.app.state.settings,
        scope=f"approval.approve:{approval_task_id}:{context.user_id}",
        key=idempotency_key,
        request_payload={"approval_task_id": str(approval_task_id), "payload": payload.model_dump(mode="json")},
    )
    if replay is not None:
        return replay
    task = _scoped_task(session, approval_task_id, context, for_decision=True)
    _require_verifiable_evidence(session, task.approval_request_id)
    approve_task(session=session, actor_user_id=context.user_id, task=task, lock_version=payload.lock_version, comment=payload.comment, request_id=request.state.request_id)
    session.flush()
    response = _approval_task_response(session, task)
    _complete_idempotent_operation(
        idempotency_record,
        response.model_dump(mode="json"),
    )
    session.commit()
    return response


@router.post("/approvals/{approval_task_id}/reject", response_model=ApprovalTaskResponse)
def reject(
    approval_task_id: UUID,
    payload: ApprovalRejectPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ApprovalTaskResponse | dict[str, Any]:
    replay, idempotency_record = _begin_idempotent_operation(
        session=session,
        settings=request.app.state.settings,
        scope=f"approval.reject:{approval_task_id}:{context.user_id}",
        key=idempotency_key,
        request_payload={"approval_task_id": str(approval_task_id), "payload": payload.model_dump(mode="json")},
    )
    if replay is not None:
        return replay
    task = _scoped_task(session, approval_task_id, context, for_decision=True)
    reject_task(session=session, actor_user_id=context.user_id, task=task, lock_version=payload.lock_version, comment=payload.comment, request_id=request.state.request_id)
    session.flush()
    response = _approval_task_response(session, task)
    _complete_idempotent_operation(
        idempotency_record,
        response.model_dump(mode="json"),
    )
    session.commit()
    return response


@router.post("/document-versions/{version_id}/publish", response_model=PublishResult)
def publish_document_version(
    version_id: UUID,
    payload: PublishVersionPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> PublishResult:
    replay, idempotency_record = _begin_idempotent_operation(
        session=session,
        settings=request.app.state.settings,
        scope=f"document-version.publish:{version_id}:{context.user_id}",
        key=idempotency_key,
        request_payload={"version_id": str(version_id), "payload": payload.model_dump(mode="json")},
    )
    if replay is not None:
        return PublishResult.model_validate(replay)
    version = session.get(DocumentVersion, version_id)
    if version is None:
        raise AppError("document_version_not_found", "Document version was not found", status_code=404)
    require_project_scope(version.project_id, set(context.visible_project_ids))
    if session.get(ProjectOwner, (version.project_id, context.user_id)) is None:
        raise AppError("project_owner_required", "Project Owner relationship is required to publish", status_code=403)
    document = session.get(Document, version.document_id)
    if document is None:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    manifest, index_result, graph_job = publish_version(
        session=session,
        actor_user_id=context.user_id,
        document=document,
        version=version,
        lock_version=payload.lock_version,
        request_id=request.state.request_id,
        search_adapter=LiveOpenSearchPublishedAdapter(request.app.state.settings),
        graph_adapter=LiveNeo4jGraphSyncAdapter(request.app.state.settings),
    )
    result = PublishResult(document_version_id=version.id, status=version.status, active_manifest_id=manifest.id, publication_generation=manifest.publication_generation, opensearch_index=index_result.index_name, graph_sync_job_id=graph_job.id)
    _complete_idempotent_operation(idempotency_record, result.model_dump(mode="json"))
    session.commit()
    return result


@router.post("/document-versions/{version_id}/switch-active", response_model=PublishResult)
def switch_document_version_active(
    version_id: UUID,
    payload: SwitchActiveVersionPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> PublishResult:
    replay, idempotency_record = _begin_idempotent_operation(
        session=session,
        settings=request.app.state.settings,
        scope=f"document-version.switch-active:{version_id}:{context.user_id}",
        key=idempotency_key,
        request_payload={"version_id": str(version_id), "payload": payload.model_dump(mode="json")},
        required=True,
    )
    if replay is not None:
        return PublishResult.model_validate(replay)
    version = session.get(DocumentVersion, version_id)
    if version is None:
        raise AppError("document_version_not_found", "Document version was not found", status_code=404)
    require_project_scope(version.project_id, set(context.visible_project_ids))
    if session.get(ProjectOwner, (version.project_id, context.user_id)) is None:
        raise AppError("project_owner_required", "Project Owner relationship is required to switch active version", status_code=403)
    document = session.get(Document, version.document_id)
    if document is None:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    manifest, graph_job = switch_active_version(
        session=session,
        actor_user_id=context.user_id,
        document=document,
        version=version,
        lock_version=payload.lock_version,
        impact_confirmed=payload.impact_confirmed,
        audit_reason=payload.audit_reason,
        request_id=request.state.request_id,
    )
    result = PublishResult(document_version_id=version.id, status=version.status, active_manifest_id=manifest.id, publication_generation=manifest.publication_generation, opensearch_index="", graph_sync_job_id=graph_job.id)
    _complete_idempotent_operation(idempotency_record, result.model_dump(mode="json"))
    session.commit()
    return result


def _pending_query(session: Session, context: IdentityContext):
    owner_project_ids = select(ProjectOwner.project_id).where(ProjectOwner.user_id == context.user_id)
    return select(ApprovalTask).join(Project, Project.id == ApprovalTask.project_id).join(Document, Document.id == ApprovalTask.document_id).join(ApprovalRequest, ApprovalRequest.id == ApprovalTask.approval_request_id).where(
        Project.status == "active",
        ApprovalTask.status == "pending",
        ApprovalTask.project_id.in_(context.visible_project_ids),
        or_(
            and_(ApprovalTask.review_stage == "manager_review", ApprovalTask.assignee_user_id == context.user_id),
            and_(ApprovalTask.review_stage == "owner_review", ApprovalTask.project_id.in_(owner_project_ids)),
        ),
    )


def _approval_task_response(session: Session, task: ApprovalTask) -> ApprovalTaskResponse:
    project = session.get(Project, task.project_id)
    document = session.get(Document, task.document_id)
    version = session.get(DocumentVersion, task.document_version_id)
    submitter = session.get(User, task.submitter_id)
    approval_request = session.get(ApprovalRequest, task.approval_request_id)
    return ApprovalTaskResponse(
        id=task.id,
        approval_request_id=task.approval_request_id,
        project_id=task.project_id,
        project_name=project.name if project is not None else None,
        document_id=task.document_id,
        document_title=document.title if document is not None else None,
        document_version_id=task.document_version_id,
        version_label=version.version_label if version is not None else None,
        submitter_id=task.submitter_id,
        submitter_given_name=submitter.given_name if submitter is not None else None,
        submitter_family_name=submitter.family_name if submitter is not None else None,
        submitter_name=submitter.display_name if submitter is not None else None,
        submitter_email=submitter.email if submitter is not None else None,
        priority=approval_request.priority if approval_request is not None else "normal",
        source_type=document.source_type if document is not None else None,
        assignee_user_id=task.assignee_user_id,
        review_stage=task.review_stage,
        status=task.status,
        lock_version=task.lock_version,
        submitted_at=task.submitted_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
    )


def _approval_request_response(session: Session, request: ApprovalRequest) -> ApprovalRequestResponse:
    project = session.get(Project, request.project_id)
    document = session.get(Document, request.document_id)
    version = session.get(DocumentVersion, request.document_version_id)
    submitter = session.get(User, request.submitter_id)
    return ApprovalRequestResponse(
        id=request.id,
        project_id=request.project_id,
        project_name=project.name if project is not None else None,
        document_id=request.document_id,
        document_title=document.title if document is not None else None,
        document_version_id=request.document_version_id,
        version_label=version.version_label if version is not None else None,
        submitter_id=request.submitter_id,
        submitter_given_name=submitter.given_name if submitter is not None else None,
        submitter_family_name=submitter.family_name if submitter is not None else None,
        submitter_name=submitter.display_name if submitter is not None else None,
        submitter_email=submitter.email if submitter is not None else None,
        owner_user_id=request.owner_user_id,
        evidence_revision=request.evidence_revision,
        priority=request.priority,
        source_type=document.source_type if document is not None else None,
        status=request.status,
        current_task_id=request.current_task_id,
        submitted_at=request.submitted_at,
        approved_at=request.approved_at,
        published_at=request.published_at,
        cancelled_at=request.cancelled_at,
        created_at=request.created_at,
    )


def _task_page(
    session: Session,
    request: Request,
    context: IdentityContext,
    *,
    namespace: str,
    statement,
    project_id: UUID | None,
    document_id: UUID | None,
    editor_id: UUID | None,
    priority: str | None,
    source_type: str | None,
    stage: str | None,
    result: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    cursor: str | None,
    limit: int,
) -> ApprovalTaskPage:
    if project_id is not None:
        require_project_scope(project_id, set(context.visible_project_ids))
        statement = statement.where(ApprovalTask.project_id == project_id)
    if document_id is not None:
        statement = statement.where(ApprovalTask.document_id == document_id)
    if editor_id is not None:
        statement = statement.where(ApprovalTask.submitter_id == editor_id)
    if priority:
        statement = statement.where(ApprovalRequest.priority == priority)
    if source_type:
        statement = statement.where(Document.source_type == source_type)
    if stage:
        statement = statement.where(ApprovalTask.review_stage == stage)
    if result:
        statement = statement.where(ApprovalTask.status == result)
    if date_from:
        statement = statement.where(ApprovalTask.submitted_at >= date_from)
    if date_to:
        statement = statement.where(ApprovalTask.submitted_at <= date_to)
    filter_hash = cursor_filter_hash(
        {
            "actor": context.user_id,
            "project_id": project_id,
            "document_id": document_id,
            "editor_id": editor_id,
            "priority": priority,
            "source_type": source_type,
            "stage": stage,
            "result": result,
            "date_from": date_from,
            "date_to": date_to,
        }
    )
    if cursor:
        payload = decode_cursor(request.app.state.settings, namespace=namespace, value=cursor)
        if payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current approval filters", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(payload["submitted_at"]))
            cursor_id = UUID(str(payload["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                ApprovalTask.submitted_at < cursor_time,
                and_(ApprovalTask.submitted_at == cursor_time, ApprovalTask.id < cursor_id),
            )
        )
    rows = list(session.scalars(statement.order_by(ApprovalTask.submitted_at.desc(), ApprovalTask.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace=namespace,
            payload={"filter": filter_hash, "submitted_at": last.submitted_at.isoformat(), "id": str(last.id)},
        )
    return ApprovalTaskPage(items=[_approval_task_response(session, row) for row in rows], next_cursor=next_cursor)


def _request_page(
    session: Session,
    request: Request,
    context: IdentityContext,
    *,
    statement,
    project_id: UUID | None,
    document_id: UUID | None,
    priority: str | None,
    source_type: str | None,
    result: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    cursor: str | None,
    limit: int,
) -> ApprovalRequestPage:
    if project_id is not None:
        require_project_scope(project_id, set(context.visible_project_ids))
        statement = statement.where(ApprovalRequest.project_id == project_id)
    if document_id is not None:
        statement = statement.where(ApprovalRequest.document_id == document_id)
    if priority:
        statement = statement.where(ApprovalRequest.priority == priority)
    if source_type:
        statement = statement.where(Document.source_type == source_type)
    if result:
        statement = statement.where(ApprovalRequest.status == result)
    if date_from:
        statement = statement.where(ApprovalRequest.submitted_at >= date_from)
    if date_to:
        statement = statement.where(ApprovalRequest.submitted_at <= date_to)
    filter_hash = cursor_filter_hash(
        {
            "actor": context.user_id,
            "project_id": project_id,
            "document_id": document_id,
            "priority": priority,
            "source_type": source_type,
            "result": result,
            "date_from": date_from,
            "date_to": date_to,
        }
    )
    if cursor:
        payload = decode_cursor(request.app.state.settings, namespace="approval-my-submissions", value=cursor)
        if payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current approval filters", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(payload["submitted_at"]))
            cursor_id = UUID(str(payload["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                ApprovalRequest.submitted_at < cursor_time,
                and_(ApprovalRequest.submitted_at == cursor_time, ApprovalRequest.id < cursor_id),
            )
        )
    rows = list(session.scalars(statement.order_by(ApprovalRequest.submitted_at.desc(), ApprovalRequest.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="approval-my-submissions",
            payload={"filter": filter_hash, "submitted_at": last.submitted_at.isoformat(), "id": str(last.id)},
        )
    return ApprovalRequestPage(items=[_approval_request_response(session, row) for row in rows], next_cursor=next_cursor)


def _pending_publish_response(
    version: DocumentVersion,
    document: Document,
    project: Project,
    request: ApprovalRequest | None,
    submitter: User | None,
    owner_task_id: UUID | None,
) -> ApprovalPendingPublishResponse:
    return ApprovalPendingPublishResponse(
        approval_request_id=request.id if request is not None else None,
        approval_task_id=owner_task_id,
        project_id=version.project_id,
        project_name=project.name,
        document_id=version.document_id,
        document_title=document.title,
        document_version_id=version.id,
        version_label=version.version_label,
        version_status=version.status,
        lock_version=version.lock_version,
        submitter_id=request.submitter_id if request is not None else None,
        submitter_given_name=submitter.given_name if submitter is not None else None,
        submitter_family_name=submitter.family_name if submitter is not None else None,
        submitter_name=submitter.display_name if submitter is not None else None,
        submitter_email=submitter.email if submitter is not None else None,
        approved_at=request.approved_at if request is not None else None,
    )


def _scoped_task(session: Session, task_id: UUID, context: IdentityContext, *, for_decision: bool = False) -> ApprovalTask:
    task = session.get(ApprovalTask, task_id)
    if task is None:
        raise AppError("approval_task_not_found", "Approval task was not found", status_code=404)
    require_project_scope(task.project_id, set(context.visible_project_ids))
    _require_active_project(session, task.project_id)
    if for_decision and task.review_stage == "manager_review" and task.assignee_user_id != context.user_id:
        raise AppError("approval_assignee_required", "This approval task is assigned to another user", status_code=403)
    if for_decision and task.review_stage == "owner_review" and session.get(ProjectOwner, (task.project_id, context.user_id)) is None:
        raise AppError("project_owner_required", "Project Owner relationship is required for Owner review", status_code=403)
    return task


def _require_active_project(session: Session, project_id: UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    if project.status != "active":
        raise AppError("project_archived", "Archived projects cannot be opened or used", status_code=409)
    return project


def _require_verifiable_evidence(session: Session, approval_request_id: UUID) -> ApprovalEvidenceManifest:
    evidence = session.scalar(
        select(ApprovalEvidenceManifest).where(
            ApprovalEvidenceManifest.approval_request_id == approval_request_id
        )
    )
    if evidence is None:
        raise AppError(
            "approval_evidence_unavailable",
            "Immutable approval evidence is unavailable; this legacy request cannot be approved",
            status_code=409,
        )
    digest = hashlib.sha256(
        json.dumps(evidence.manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    if digest != evidence.manifest_hash or evidence.evidence_revision != digest:
        raise AppError(
            "approval_evidence_integrity_failed",
            "Approval evidence integrity verification failed",
            status_code=409,
        )
    return evidence


def _begin_idempotent_operation(
    *,
    session: Session,
    settings: Any,
    scope: str,
    key: str | None,
    request_payload: object,
    required: bool = False,
) -> tuple[dict[str, Any] | None, IdempotencyKey | None]:
    if not key:
        if required:
            begin_idempotent_operation(
                session,
                settings,
                scope=scope,
                raw_key=key,
                request_payload=request_payload,
            )
        return None, None
    replay, record = begin_idempotent_operation(
        session,
        settings,
        scope=scope,
        raw_key=key,
        request_payload=request_payload,
    )
    return (replay.body if replay is not None else None), record


def _complete_idempotent_operation(record: IdempotencyKey | None, response_summary: dict[str, Any]) -> None:
    if record is None:
        return
    complete_idempotent_operation(record, response_summary)


def _approval_chunk_evidence(session: Session, version_id: UUID) -> list[ApprovalChunkEvidence]:
    rows = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version_id, Chunk.status == "active").order_by(Chunk.chunk_index)))
    if not rows:
        return []
    return [
        _chunk_evidence(session, row)
        for row in rows
    ]


def _manifest_chunk_evidence(manifest: dict[str, Any]) -> list[ApprovalChunkEvidence]:
    return [
        ApprovalChunkEvidence(
            id=UUID(str(item["id"])),
            chunk_index=int(item["index"]),
            title=item.get("title"),
            content=str(item.get("content") or ""),
            markdown_content=item.get("markdown_content"),
            display_markdown=item.get("display_markdown"),
            content_type=str(item.get("type") or "text"),
            source_mapping=list(item.get("source_mapping") or []),
            token_count=item.get("token_count"),
            confidence_score=item.get("confidence"),
            lineage_id=UUID(str(item["lineage_id"])),
            parent_chunk_id=UUID(str(item["parent_chunk_id"])) if item.get("parent_chunk_id") else None,
            revision=int(item.get("revision") or 0),
            change_type=str(item.get("change_type") or "generated"),
            tags=[str(tag.get("name") or "") for tag in item.get("tags") or [] if tag.get("name")],
            tag_details=[],
        )
        for item in manifest.get("chunks") or []
    ]


def _manifest_chat_evidence(manifest: dict[str, Any]) -> list[ApprovalChatEvidence]:
    return [
        ApprovalChatEvidence(
            id=UUID(str(item["record_id"])),
            conversation_id=UUID(str(item["conversation_id"])),
            conversation_title=item.get("conversation_title"),
            scope_mode=item.get("surface"),
            document_version_id=UUID(str(item["document_version_id"])) if item.get("document_version_id") else None,
            selected_document_version_ids=sorted(_uuid_values(item.get("selected_document_version_ids")), key=str),
            question=str(item.get("question") or ""),
            answer=item.get("answer"),
            reference_docs=list(item.get("citations") or []),
            evaluation=str(item.get("evaluation") or "not_evaluated"),
            revision_suggestion=item.get("revision_suggestion"),
            created_by=UUID(str(item["created_by"])),
            asked_at=datetime.fromisoformat(str(item["asked_at"])),
            answered_at=datetime.fromisoformat(str(item["answered_at"])) if item.get("answered_at") else None,
        )
        for item in manifest.get("conversations") or []
    ]


def _uuid_values(values: list | None) -> set[UUID]:
    result: set[UUID] = set()
    for value in values or []:
        try:
            result.add(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return result


def _source_text(version: DocumentVersion, chunks: list[ApprovalChunkEvidence]) -> str | None:
    strategy = version.chunk_strategy or {}
    source_text = strategy.get("source_text")
    if isinstance(source_text, str) and source_text.strip():
        return source_text.strip()
    return None


def _original_file_metadata(project_id: UUID, document_id: UUID, version: DocumentVersion) -> OriginalFileViewerMetadata:
    extension = (version.canonical_extension or "").lower()
    base = f"/projects/{project_id}/documents/{document_id}/versions/{version.id}"
    original_url = f"{base}/original-file" if version.storage_bucket and version.storage_key else None
    viewer_type = "download_only" if original_url else "unsupported"
    preview_status = "unavailable"
    preview_error_code = None
    markdown_source_mode = "pipeline_markdown"

    if extension == ".pdf":
        preview_error_code = "direct_pdf_viewer_disabled"
    elif extension in {".doc", ".docx"}:
        preview_error_code = "direct_office_viewer_disabled"
    elif extension in {".txt", ".csv", ".json"}:
        preview_error_code = None if original_url else "original_file_missing"
    elif extension in {".md", ".markdown"}:
        viewer_type = "markdown"
        preview_status = "available" if original_url else "unavailable"
        preview_error_code = None if original_url else "original_file_missing"
        markdown_source_mode = "rendered_original_raw_markdown"
    else:
        preview_error_code = "preview_unsupported"

    return OriginalFileViewerMetadata(
        original_file_name=version.original_file_name,
        extension=extension or None,
        mime_type=version.mime_type,
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


def _chunk_evidence(session: Session, chunk: Chunk) -> ApprovalChunkEvidence:
    tag_details = _chunk_tag_details(session, chunk.id)
    return ApprovalChunkEvidence(
        id=chunk.id,
        chunk_index=chunk.chunk_index,
        title=chunk.title,
        content=chunk.content,
        markdown_content=chunk.markdown_content,
        display_markdown=chunk.display_markdown,
        content_type=chunk.content_type,
        source_mapping=chunk.source_mapping,
        token_count=chunk.token_count,
        confidence_score=float(chunk.confidence_score) if chunk.confidence_score is not None else None,
        lineage_id=chunk.lineage_id or chunk.id,
        parent_chunk_id=chunk.parent_chunk_id,
        revision=chunk.revision,
        change_type=chunk.change_type,
        tags=[tag.tag_text for tag in tag_details],
        tag_details=tag_details,
    )


def _version_summary(version: DocumentVersion) -> DocumentVersionSummary:
    return DocumentVersionSummary(
        id=version.id,
        version_label=version.version_label,
        status=version.status,
        original_file_name=version.original_file_name,
        canonical_extension=version.canonical_extension,
        mime_type=version.mime_type,
        file_size=version.file_size,
        storage_bucket=version.storage_bucket,
        storage_key=version.storage_key,
        ocr_model_id=version.ocr_model_id,
        ocr_config_version=version.ocr_config_version,
        lock_version=version.lock_version,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _document_summary(document: Document, version: DocumentVersion | None) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        project_id=document.project_id,
        document_code=document.document_code,
        title=document.title,
        source_type=document.source_type,
        status=document.status,
        created_by=document.created_by,
        lock_version=document.lock_version,
        created_at=document.created_at,
        updated_at=document.updated_at,
        latest_version=_version_summary(version) if version else None,
        latest_pipeline=None,
    )
