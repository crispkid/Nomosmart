"""CHG-467 REVROUTE467-009..011: approval administration (list, reassign, administrative return).

Every route requires the independent permission Approval.ApprovalAdministration (execute); no other
permission implies it. Administrators can reassign the manager stage or return a submission; they can
never approve it, and there is no cancel.
"""
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.schemas import ApprovalAdministrationTask, ApprovalAdministrationTaskPage, ApprovalAdministrativeReturnPayload, ApprovalReassignPayload, ReviewRoutePerson
from app.core.errors import AppError
from app.db.models import ApprovalRequest, ApprovalTask, Document, DocumentVersion, Project, ProjectMember, ProjectOwner, User
from app.db.session import get_db
from app.domain.approval_access import eligible_manager_reviewer, reviewer_unavailable, unavailable_reviewer_ids
from app.domain.review_publish import MANAGER_REVIEW, _notify, reject_task
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import APPROVAL_ADMINISTRATION, APPROVAL_MODULE, PermissionAction, require_permission
from app.services.audit import add_audit

router = APIRouter(prefix="/approval-administration", tags=["approval-administration"])


def _require(context: IdentityContext) -> None:
    require_permission(list(context.grants), APPROVAL_MODULE, APPROVAL_ADMINISTRATION, PermissionAction.EXECUTE)


def _person(session: Session, user_id: UUID | None) -> ReviewRoutePerson | None:
    user = session.get(User, user_id) if user_id else None
    return ReviewRoutePerson(id=user.id, display_name=user.display_name) if user is not None else None


def _unattended_clause():
    return (ApprovalTask.review_stage == MANAGER_REVIEW) & or_(
        ApprovalTask.assignee_user_id.is_(None),
        ApprovalTask.assignee_user_id.in_(unavailable_reviewer_ids()),
        ~select(User.id).where(User.id == ApprovalTask.assignee_user_id).exists(),
    )


@router.get("/tasks", response_model=ApprovalAdministrationTaskPage)
def list_tasks(
    response: Response,
    unattended: bool | None = None,
    review_stage: str | None = Query(default=None, pattern="^(manager_review|owner_review)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ApprovalAdministrationTaskPage:
    _require(context)
    statement = (
        select(ApprovalTask, ApprovalRequest, Project, Document, DocumentVersion)
        .join(ApprovalRequest, ApprovalRequest.id == ApprovalTask.approval_request_id)
        .join(Project, Project.id == ApprovalTask.project_id)
        .join(Document, Document.id == ApprovalTask.document_id)
        .join(DocumentVersion, DocumentVersion.id == ApprovalTask.document_version_id)
        .where(ApprovalTask.status == "pending", Project.status == "active")
    )
    if review_stage:
        statement = statement.where(ApprovalTask.review_stage == review_stage)
    if unattended is True:
        statement = statement.where(_unattended_clause())
    elif unattended is False:
        statement = statement.where(~_unattended_clause())
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    rows = session.execute(statement.order_by(ApprovalTask.submitted_at, ApprovalTask.id).offset(offset).limit(limit)).all()
    items = [
        ApprovalAdministrationTask(
            id=task.id, approval_request_id=request.id, project_id=project.id, project_name=project.name,
            document_id=document.id, document_title=document.title, version_label=version.version_label,
            review_stage=task.review_stage, review_route=request.review_route,
            assignee=_person(session, task.assignee_user_id), submitter=_person(session, task.submitter_id),
            submitted_at=task.submitted_at, lock_version=task.lock_version,
            unattended=task.review_stage == MANAGER_REVIEW and reviewer_unavailable(session, task),
        )
        for task, request, project, document, version in rows
    ]
    return ApprovalAdministrationTaskPage(items=items, total=total)


def _pending_task(session: Session, task_id: UUID, lock_version: int) -> ApprovalTask:
    task = session.scalar(select(ApprovalTask).where(ApprovalTask.id == task_id).with_for_update())
    if task is None:
        raise AppError("approval_task_not_found", "Approval task was not found", status_code=404)
    project = session.get(Project, task.project_id)
    if project is None or project.status != "active":
        raise AppError("project_archived", "Archived projects cannot be opened or used", status_code=409)
    if task.status != "pending":
        raise AppError("approval_task_not_pending", "Approval task is no longer pending", status_code=409)
    if task.lock_version != lock_version:
        raise AppError("stale_approval_task", "Approval task was changed by another request", status_code=409)
    return task


def _task_response(session: Session, task: ApprovalTask) -> ApprovalAdministrationTask:
    request = session.get(ApprovalRequest, task.approval_request_id)
    project = session.get(Project, task.project_id)
    document = session.get(Document, task.document_id)
    version = session.get(DocumentVersion, task.document_version_id)
    return ApprovalAdministrationTask(
        id=task.id, approval_request_id=task.approval_request_id, project_id=task.project_id, project_name=project.name,
        document_id=task.document_id, document_title=document.title, version_label=version.version_label if version else None,
        review_stage=task.review_stage, review_route=request.review_route, assignee=_person(session, task.assignee_user_id),
        submitter=_person(session, task.submitter_id), submitted_at=task.submitted_at, lock_version=task.lock_version,
        unattended=task.status == "pending" and task.review_stage == MANAGER_REVIEW and reviewer_unavailable(session, task),
    )


@router.get("/tasks/{task_id}/reviewer-candidates", response_model=list[ReviewRoutePerson])
def reviewer_candidates(task_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[ReviewRoutePerson]:
    """D467-07: eligible reviewers for a reassignment (project members or Owners with application access)."""
    _require(context)
    task = session.get(ApprovalTask, task_id)
    if task is None:
        raise AppError("approval_task_not_found", "Approval task was not found", status_code=404)
    ids = set(session.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == task.project_id)))
    ids |= set(session.scalars(select(ProjectOwner.user_id).where(ProjectOwner.project_id == task.project_id)))
    ids -= {task.submitter_id, task.assignee_user_id}
    people = [session.get(User, user_id) for user_id in ids if eligible_manager_reviewer(session, user_id, task.project_id)]
    return [ReviewRoutePerson(id=user.id, display_name=user.display_name) for user in sorted(people, key=lambda u: (u.display_name, str(u.id)))]


@router.post("/tasks/{task_id}/reassign", response_model=ApprovalAdministrationTask)
def reassign_task(
    task_id: UUID,
    payload: ApprovalReassignPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ApprovalAdministrationTask:
    _require(context)
    reason = payload.reason.strip()
    if not reason:
        raise AppError("approval_administration_reason_required", "A reason is required", status_code=422)
    task = _pending_task(session, task_id, payload.lock_version)
    if task.review_stage != MANAGER_REVIEW:
        raise AppError("approval_reassign_stage_unsupported", "Only the manager review stage can be reassigned", status_code=409)
    target = payload.assignee_user_id
    if target in (task.submitter_id, task.assignee_user_id) or not eligible_manager_reviewer(session, target, task.project_id):
        raise AppError("approval_reassign_target_invalid", "The new reviewer must be an eligible project member other than the submitter and the current reviewer", status_code=422)
    previous = task.assignee_user_id
    task.assignee_user_id = target
    task.lock_version += 1
    version = session.get(DocumentVersion, task.document_version_id)
    label = version.version_label if version else ""
    payload_ids = {"approval_task_id": str(task.id), "document_version_id": str(task.document_version_id)}
    _notify(session, target, task.project_id, "review.manager.pending", "待主管審核", f"文件版本 {label} 已由系統管理者改派給您審核", payload_ids)
    _notify(session, task.submitter_id, task.project_id, "review.reassigned", "審核人已改派", f"文件版本 {label} 的審核人已由系統管理者改派", payload_ids)
    add_audit(session, actor_user_id=context.user_id, action="approval.administration.reassign", resource_type="approval_task",
              resource_id=task.id, result="success", request_id=request.state.request_id,
              summary={"previous_assignee_user_id": str(previous) if previous else None, "assignee_user_id": str(target),
                       "reason": reason, "at": datetime.now(UTC).isoformat()})
    session.commit()
    session.refresh(task)
    return _task_response(session, task)


@router.post("/tasks/{task_id}/return", response_model=ApprovalAdministrationTask)
def return_task(
    task_id: UUID,
    payload: ApprovalAdministrativeReturnPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ApprovalAdministrationTask:
    _require(context)
    reason = payload.reason.strip()
    if not reason:
        raise AppError("approval_administration_reason_required", "A reason is required", status_code=422)
    task = _pending_task(session, task_id, payload.lock_version)
    assignee = task.assignee_user_id
    reject_task(session=session, actor_user_id=context.user_id, task=task, lock_version=payload.lock_version,
                comment=reason, request_id=request.state.request_id, administration=True)
    if assignee and assignee != task.submitter_id:
        version = session.get(DocumentVersion, task.document_version_id)
        _notify(session, assignee, task.project_id, "review.returned_by_administration", "審核案件已由系統管理者退回",
                f"文件版本 {version.version_label if version else ''} 已由系統管理者退回",
                {"approval_task_id": str(task.id), "document_version_id": str(task.document_version_id)})
    session.commit()
    session.refresh(task)
    return _task_response(session, task)
