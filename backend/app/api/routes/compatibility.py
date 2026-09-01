from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domain.project_access import get_scoped_project as _get_scoped_project, require_project_owner as _require_project_owner, resolve_project_model as _resolve_model
from app.core.cursor import cursor_filter_hash, decode_cursor, encode_cursor
from app.core.errors import AppError
from app.db.models import (
    AIModel,
    ApprovalRequest,
    ApprovalTask,
    AuditLog,
    Chunk,
    Document,
    DocumentVersion,
    GraphSyncJob,
    OutboxEvent,
    PipelineRun,
    Project,
    ProjectOwner,
    ReviewRecord,
    ValidationQuestion,
    ValidationRun,
    ValidationRunItem,
)
from app.db.session import get_db
from app.domain.graph_sync_jobs import enqueue_graph_sync
from app.domain.public_api_controls import begin_idempotent_operation, complete_idempotent_operation
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.security.project_roles import PROJECT_EDITOR_ROLES, PROJECT_OWNER_ROLES, require_project_role
from app.services.audit import add_audit


router = APIRouter(tags=["compatibility"])


class ProjectEmbeddingSettingsResponse(BaseModel):
    project_id: UUID
    embedding_model_id: UUID
    model_name: str
    provider: str
    config_version: int
    last_test_status: str | None = None
    lock_version: int


class ProjectEmbeddingSettingsUpdate(BaseModel):
    embedding_model_id: UUID
    lock_version: int = Field(ge=1)


class DocumentVersionListItem(BaseModel):
    id: UUID
    project_id: UUID
    document_id: UUID
    version_label: str
    version_major: int
    extraction_revision: int
    status: str
    lock_version: int
    created_at: datetime
    updated_at: datetime


class PipelineRunListItem(BaseModel):
    id: UUID
    project_id: UUID
    document_id: UUID | None
    document_version_id: UUID | None
    run_type: str
    status: str
    progress_percent: float
    current_step_name: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class PipelineRunPage(BaseModel):
    items: list[PipelineRunListItem]
    next_cursor: str | None = None


class ApprovalCancellationResponse(BaseModel):
    approval_request_id: UUID
    status: str
    cancelled_at: datetime


class ReviewRecordListItem(BaseModel):
    id: UUID
    project_id: UUID
    document_id: UUID
    document_version_id: UUID
    review_stage: str
    reviewer_id: UUID
    status: str
    comment: str | None
    created_at: datetime


class ValidationQuestionCreate(BaseModel):
    project_id: UUID
    question: str = Field(min_length=1, max_length=4000)
    expected_answer: str | None = None
    expected_keywords: list[str] = Field(default_factory=list)
    category: str | None = Field(default=None, max_length=100)
    priority: str | None = Field(default=None, max_length=32)


class ValidationQuestionResponse(ValidationQuestionCreate):
    id: UUID
    created_by: UUID | None
    created_at: datetime


class ValidationCancellationResponse(BaseModel):
    validation_run_id: UUID
    status: str
    cancelled_item_count: int
    completed_at: datetime


class GraphSyncJobResponse(BaseModel):
    id: UUID
    project_id: UUID
    document_id: UUID
    document_version_id: UUID
    trigger_type: str
    status: str
    node_count: int
    edge_count: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class GraphSyncJobPage(BaseModel):
    items: list[GraphSyncJobResponse]
    next_cursor: str | None = None


class AuditLogResponse(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    result: str
    request_id: str | None
    summary: dict[str, Any]
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    next_cursor: str | None = None


@router.get("/projects/{project_id}/embedding-settings", response_model=ProjectEmbeddingSettingsResponse)
def get_project_embedding_settings(project_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ProjectEmbeddingSettingsResponse:
    project = _get_scoped_project(session, project_id, context)
    model = session.get(AIModel, project.embedding_model_id) if project.embedding_model_id else None
    if model is None or not model.is_active or model.deleted_at is not None or model.model_type != "Embedding":
        raise AppError("project_embedding_model_required", "Project has no active Embedding Model", status_code=409)
    return _embedding_settings_response(project, model)


@router.put("/projects/{project_id}/embedding-settings", response_model=ProjectEmbeddingSettingsResponse)
def update_project_embedding_settings(project_id: UUID, payload: ProjectEmbeddingSettingsUpdate, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ProjectEmbeddingSettingsResponse:
    project = _get_scoped_project(session, project_id, context)
    _require_project_owner(session, project.id, context.user_id)
    if project.lock_version != payload.lock_version:
        raise AppError("stale_project_version", "Project was changed by another request", status_code=409)
    model_id = _resolve_model(session, payload.embedding_model_id, "Embedding")
    model = session.get(AIModel, model_id)
    assert model is not None
    if model.last_test_status != "success":
        raise AppError("embedding_model_connection_test_required", "Embedding Model must pass a current connection test", status_code=409)
    project.embedding_model_id = model.id
    project.lock_version += 1
    project.updated_at = datetime.now(UTC)
    add_audit(session, actor_user_id=context.user_id, action="project.embedding_settings.update", resource_type="project", resource_id=project.id, result="success", request_id=request.state.request_id, summary={"embedding_model_id": str(model.id), "config_version": model.config_version})
    session.commit()
    return _embedding_settings_response(project, model)


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionListItem])
def list_document_versions(document_id: UUID, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200), context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[DocumentVersion]:
    document = session.get(Document, document_id)
    if document is None:
        raise AppError("document_not_found", "Document was not found", status_code=404)
    _get_scoped_project(session, document.project_id, context)
    return list(session.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id, DocumentVersion.project_id == document.project_id).order_by(DocumentVersion.version_major.desc(), DocumentVersion.extraction_revision.desc()).offset(offset).limit(limit)))


@router.get("/pipeline-runs", response_model=PipelineRunPage)
def list_pipeline_runs(
    request: Request,
    project_id: UUID | None = None,
    status: str | None = None,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> PipelineRunPage:
    visible = set(context.visible_project_ids)
    if project_id is not None:
        _get_scoped_project(session, project_id, context)
        visible = {project_id}
    if not visible:
        return PipelineRunPage(items=[])
    filter_hash = cursor_filter_hash({"actor": context.user_id, "project_id": project_id, "status": status})
    statement = select(PipelineRun).where(PipelineRun.project_id.in_(visible))
    if status:
        statement = statement.where(PipelineRun.status == status)
    if cursor:
        payload = decode_cursor(request.app.state.settings, namespace="pipeline-runs", value=cursor)
        if payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current pipeline filters", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(payload["created_at"]))
            cursor_id = UUID(str(payload["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                PipelineRun.created_at < cursor_time,
                (PipelineRun.created_at == cursor_time) & (PipelineRun.id < cursor_id),
            )
        )
    rows = list(session.scalars(statement.order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="pipeline-runs",
            payload={"filter": filter_hash, "created_at": last.created_at.isoformat(), "id": str(last.id)},
        )
    return PipelineRunPage(items=[_pipeline_response(row) for row in rows], next_cursor=next_cursor)


@router.post("/approval-requests/{approval_request_id}/cancel", response_model=ApprovalCancellationResponse)
def cancel_approval_request(approval_request_id: UUID, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ApprovalCancellationResponse:
    approval = session.scalar(select(ApprovalRequest).where(ApprovalRequest.id == approval_request_id).with_for_update())
    if approval is None:
        raise AppError("approval_request_not_found", "Approval request was not found", status_code=404)
    _get_scoped_project(session, approval.project_id, context)
    is_owner = session.get(ProjectOwner, (approval.project_id, context.user_id)) is not None
    if approval.submitter_id != context.user_id and not is_owner:
        raise AppError("approval_cancel_forbidden", "Only the submitter or Project Owner may cancel this request", status_code=403)
    if approval.status == "cancelled" and approval.cancelled_at is not None:
        return ApprovalCancellationResponse(approval_request_id=approval.id, status=approval.status, cancelled_at=approval.cancelled_at)
    if approval.status not in {"pending_manager_review", "pending_owner_review"}:
        raise AppError("approval_not_cancellable", "Approval request is no longer cancellable", status_code=409)
    now = datetime.now(UTC)
    tasks = list(session.scalars(select(ApprovalTask).where(ApprovalTask.approval_request_id == approval.id, ApprovalTask.status == "pending").with_for_update()))
    for task in tasks:
        task.status = "cancelled"
        task.completed_at = now
    approval.status = "cancelled"
    approval.cancelled_at = now
    approval.current_task_id = None
    version = session.get(DocumentVersion, approval.document_version_id)
    if version is not None and version.status in {"pending_manager_review", "pending_owner_review"}:
        version.status = "submission_ready"
        version.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action="approval_request.cancel", resource_type="approval_request", resource_id=approval.id, result="success", request_id=request.state.request_id, summary={"cancelled_task_count": len(tasks)})
    session.commit()
    return ApprovalCancellationResponse(approval_request_id=approval.id, status=approval.status, cancelled_at=now)


@router.get("/review-records", response_model=list[ReviewRecordListItem])
def list_review_records(project_id: UUID | None = None, document_id: UUID | None = None, document_version_id: UUID | None = None, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200), context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[ReviewRecord]:
    visible = set(context.visible_project_ids)
    if project_id is not None:
        _get_scoped_project(session, project_id, context)
        visible = {project_id}
    if not visible:
        return []
    statement = select(ReviewRecord).where(ReviewRecord.project_id.in_(visible))
    if document_id:
        statement = statement.where(ReviewRecord.document_id == document_id)
    if document_version_id:
        statement = statement.where(ReviewRecord.document_version_id == document_version_id)
    return list(session.scalars(statement.order_by(ReviewRecord.created_at.desc()).offset(offset).limit(limit)))


@router.get("/validation-questions", response_model=list[ValidationQuestionResponse])
def list_validation_questions(project_id: UUID, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200), context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[ValidationQuestion]:
    project = _get_scoped_project(session, project_id, context)
    return list(session.scalars(select(ValidationQuestion).where(ValidationQuestion.project_id == project.id).order_by(ValidationQuestion.created_at.desc()).offset(offset).limit(limit)))


@router.post("/validation-questions", response_model=ValidationQuestionResponse, status_code=201)
def create_validation_question(payload: ValidationQuestionCreate, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ValidationQuestion:
    project = _get_scoped_project(session, payload.project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_EDITOR_ROLES, code="project_editor_required", message="Owner or Editor role is required")
    question = ValidationQuestion(project_id=project.id, question=payload.question.strip(), expected_answer=payload.expected_answer, expected_keywords=payload.expected_keywords, category=payload.category, priority=payload.priority, created_by=context.user_id, created_at=datetime.now(UTC))
    session.add(question)
    session.flush()
    add_audit(session, actor_user_id=context.user_id, action="validation_question.create", resource_type="validation_question", resource_id=question.id, result="success", request_id=request.state.request_id, summary={"project_id": str(project.id)})
    session.commit()
    return question


@router.post("/validation-runs/{run_id}/cancel", response_model=ValidationCancellationResponse)
def cancel_validation_run(run_id: UUID, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ValidationCancellationResponse:
    run = session.scalar(select(ValidationRun).where(ValidationRun.id == run_id).with_for_update())
    if run is None:
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    _get_scoped_project(session, run.project_id, context)
    if run.run_scope == "document_staging":
        version = session.get(DocumentVersion, run.document_version_id) if run.document_version_id else None
        document = session.get(Document, version.document_id) if version else None
        if version is None or document is None or version.project_id != run.project_id or document.project_id != run.project_id:
            raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    elif run.run_scope != "project_chat":
        raise AppError("validation_run_not_found", "Validation run was not found", status_code=404)
    is_owner = session.get(ProjectOwner, (run.project_id, context.user_id)) is not None
    if run.created_by != context.user_id and not is_owner:
        raise AppError("validation_cancel_forbidden", "Only the creator or Project Owner may cancel this run", status_code=403)
    if run.status == "cancelled" and run.completed_at is not None:
        count = session.scalar(select(func.count()).select_from(ValidationRunItem).where(ValidationRunItem.run_id == run.id, ValidationRunItem.is_current.is_(True), ValidationRunItem.status == "cancelled")) or 0
        return ValidationCancellationResponse(validation_run_id=run.id, status=run.status, cancelled_item_count=int(count), completed_at=run.completed_at)
    if run.status not in {"queued", "running"}:
        raise AppError("validation_run_not_cancellable", "Validation run is no longer cancellable", status_code=409)
    now = datetime.now(UTC)
    items = list(session.scalars(select(ValidationRunItem).where(ValidationRunItem.run_id == run.id, ValidationRunItem.is_current.is_(True), ValidationRunItem.status.in_(("pending", "running"))).with_for_update()))
    for item in items:
        item.status = "cancelled"
        item.error_message = None
    run.status = "cancelled"
    run.completed_at = now
    events = list(session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_type == "validation_run", OutboxEvent.aggregate_id == run.id, OutboxEvent.status.in_(("pending", "dispatching"))).with_for_update()))
    for event in events:
        event.status = "cancelled"
        event.processed_at = now
        event.claim_token = None
        event.claimed_at = None
        event.lease_expires_at = None
    add_audit(session, actor_user_id=context.user_id, action="validation_run.cancel", resource_type="validation_run", resource_id=run.id, result="success", request_id=request.state.request_id, summary={"cancelled_item_count": len(items)})
    session.commit()
    return ValidationCancellationResponse(validation_run_id=run.id, status=run.status, cancelled_item_count=len(items), completed_at=now)


@router.get("/graph-sync-jobs", response_model=GraphSyncJobPage)
def list_graph_sync_jobs(
    request: Request,
    project_id: UUID | None = None,
    status: str | None = None,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> GraphSyncJobPage:
    visible = set(context.visible_project_ids)
    if project_id is not None:
        _get_scoped_project(session, project_id, context)
        visible = {project_id}
    if not visible:
        return GraphSyncJobPage(items=[])
    filter_hash = cursor_filter_hash({"actor": context.user_id, "project_id": project_id, "status": status})
    statement = select(GraphSyncJob).where(GraphSyncJob.project_id.in_(visible))
    if status:
        statement = statement.where(GraphSyncJob.status == status)
    if cursor:
        payload = decode_cursor(request.app.state.settings, namespace="graph-sync-jobs", value=cursor)
        if payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current graph sync filters", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(payload["created_at"]))
            cursor_id = UUID(str(payload["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                GraphSyncJob.created_at < cursor_time,
                (GraphSyncJob.created_at == cursor_time) & (GraphSyncJob.id < cursor_id),
            )
        )
    rows = list(session.scalars(statement.order_by(GraphSyncJob.created_at.desc(), GraphSyncJob.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="graph-sync-jobs",
            payload={"filter": filter_hash, "created_at": last.created_at.isoformat(), "id": str(last.id)},
        )
    return GraphSyncJobPage(items=rows, next_cursor=next_cursor)


@router.get("/audit-logs", response_model=AuditLogPage)
def list_audit_logs(
    request: Request,
    action: str | None = Query(default=None, max_length=150),
    resource_type: str | None = Query(default=None, max_length=100),
    result: str | None = Query(default=None, max_length=32),
    actor_user_id: UUID | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> AuditLogPage:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    filter_hash = cursor_filter_hash(
        {
            "action": action,
            "resource_type": resource_type,
            "result": result,
            "actor_user_id": actor_user_id,
        }
    )
    statement = select(AuditLog)
    if action:
        statement = statement.where(AuditLog.action == action)
    if resource_type:
        statement = statement.where(AuditLog.resource_type == resource_type)
    if result:
        statement = statement.where(AuditLog.result == result)
    if actor_user_id:
        statement = statement.where(AuditLog.actor_user_id == actor_user_id)
    if cursor:
        payload = decode_cursor(request.app.state.settings, namespace="audit-logs", value=cursor)
        if payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current audit filters", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(payload["created_at"]))
            cursor_id = UUID(str(payload["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                AuditLog.created_at < cursor_time,
                (AuditLog.created_at == cursor_time) & (AuditLog.id < cursor_id),
            )
        )
    rows = list(session.scalars(statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="audit-logs",
            payload={"filter": filter_hash, "created_at": last.created_at.isoformat(), "id": str(last.id)},
        )
    return AuditLogPage(
        items=[
            AuditLogResponse(
                id=row.id,
                actor_user_id=row.actor_user_id,
                action=row.action,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                result=row.result,
                request_id=row.request_id,
                summary=_redact_audit_summary(row.summary),
                created_at=row.created_at,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )


@router.post("/graph-sync-jobs/{job_id}/retry", response_model=GraphSyncJobResponse, status_code=202)
def retry_graph_sync_job(
    job_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> GraphSyncJob:
    job = session.scalar(select(GraphSyncJob).where(GraphSyncJob.id == job_id).with_for_update())
    if job is None:
        raise AppError("graph_sync_job_not_found", "Graph sync job was not found", status_code=404)
    project = _get_scoped_project(session, job.project_id, context)
    require_project_role(session, project.id, context.user_id, set(context.visible_project_ids), PROJECT_OWNER_ROLES, code="project_owner_required", message="Project Owner role is required")
    if job.status != "failed":
        raise AppError("graph_sync_retry_not_available", "Only failed graph sync jobs can be retried", status_code=409)
    document = session.get(Document, job.document_id)
    version = session.get(DocumentVersion, job.document_version_id)
    if document is None or version is None or document.project_id != project.id or version.project_id != project.id:
        raise AppError("graph_sync_resource_not_found", "Graph sync resource was not found", status_code=404)
    if session.scalar(select(Chunk.id).where(Chunk.document_version_id == version.id, Chunk.status == "active").limit(1)) is None:
        raise AppError("graph_sync_chunks_required", "Graph sync requires active chunks", status_code=409)

    replay, idempotency_record = begin_idempotent_operation(
        session,
        request.app.state.settings,
        scope=f"graph-sync.retry:{job.id}:{context.user_id}",
        raw_key=idempotency_key,
        request_payload={"job_id": str(job.id)},
    )
    if replay is not None:
        return GraphSyncJobResponse.model_validate(replay.body)

    retry_job = enqueue_graph_sync(
        session,
        project_id=job.project_id,
        document_id=job.document_id,
        document_version_id=job.document_version_id,
        trigger_type="manual_retry",
        requested_by_user_id=context.user_id,
        request_id=request.state.request_id,
        parent_job_id=job.id,
    )
    session.flush()
    response = GraphSyncJobResponse.model_validate(retry_job, from_attributes=True)
    complete_idempotent_operation(idempotency_record, response.model_dump(mode="json"), status_code=202)
    add_audit(session, actor_user_id=context.user_id, action="graph_sync.retry_queued", resource_type="graph_sync_job", resource_id=retry_job.id, result="success", request_id=request.state.request_id, summary={"parent_job_id": str(job.id)})
    session.commit()
    return retry_job


def _embedding_settings_response(project: Project, model: AIModel) -> ProjectEmbeddingSettingsResponse:
    return ProjectEmbeddingSettingsResponse(project_id=project.id, embedding_model_id=model.id, model_name=model.name, provider=model.provider, config_version=model.config_version, last_test_status=model.last_test_status, lock_version=project.lock_version)


def _pipeline_response(row: PipelineRun) -> PipelineRunListItem:
    return PipelineRunListItem(id=row.id, project_id=row.project_id, document_id=row.document_id, document_version_id=row.document_version_id, run_type=row.run_type, status=row.status, progress_percent=float(row.progress_percent), current_step_name=row.current_step_name, error_message=row.error_message, created_at=row.created_at, started_at=row.started_at, completed_at=row.completed_at)


def _redact_audit_summary(value: Any) -> Any:
    sensitive_fragments = (
        "secret",
        "token",
        "password",
        "credential",
        "api_key",
        "private_key",
        "content",
        "prompt",
        "question",
        "answer",
    )
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(fragment in str(key).lower() for fragment in sensitive_fragments)
                else _redact_audit_summary(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_audit_summary(item) for item in value[:100]]
    if isinstance(value, str) and len(value) > 1000:
        return value[:1000] + "…"
    return value
