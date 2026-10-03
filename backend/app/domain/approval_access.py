from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, true
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ApprovalRequest, ApprovalTask, ProjectOwner, ReviewRecord, Role, RoleUser, User
from app.security.context import IdentityContext
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, has_menu_permission


def is_approval_auditor(session: Session, context: IdentityContext) -> bool:
    if not has_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW):
        return False
    return session.scalar(
        select(Role.id)
        .join(RoleUser, RoleUser.role_id == Role.id)
        .where(
            RoleUser.user_id == context.user_id,
            Role.name == "system-admin",
            Role.is_system.is_(True),
            Role.is_active.is_(True),
            Role.deleted_at.is_(None),
        )
        .limit(1)
    ) is not None


def approval_request_read_predicate(session: Session, context: IdentityContext):
    """Shared SQL visibility, evaluated before pagination or evidence access."""
    if is_approval_auditor(session, context):
        return true()
    now = datetime.now(UTC)
    assigned = select(ApprovalTask.id).where(
        ApprovalTask.approval_request_id == ApprovalRequest.id,
        ApprovalTask.assignee_user_id == context.user_id,
    ).exists()
    reviewed = select(ReviewRecord.id).where(
        ReviewRecord.document_version_id == ApprovalRequest.document_version_id,
        ReviewRecord.reviewer_id == context.user_id,
    ).exists()
    manager = select(User.id).where(
        User.id == ApprovalRequest.submitter_id,
        or_(
            User.manager_user_id == context.user_id,
            and_(
                User.manager_delegate_user_id == context.user_id,
                or_(User.manager_delegate_start_at.is_(None), User.manager_delegate_start_at <= now),
                or_(User.manager_delegate_end_at.is_(None), User.manager_delegate_end_at >= now),
            ),
        ),
    ).exists()
    owner = select(ProjectOwner.project_id).where(
        ProjectOwner.project_id == ApprovalRequest.project_id,
        ProjectOwner.user_id == context.user_id,
    ).exists()
    return and_(
        ApprovalRequest.project_id.in_(context.visible_project_ids),
        or_(ApprovalRequest.submitter_id == context.user_id, assigned, reviewed, manager, owner),
    )


def require_approval_read(session: Session, approval_request_id: UUID, context: IdentityContext) -> None:
    allowed = session.scalar(
        select(ApprovalRequest.id).where(
            ApprovalRequest.id == approval_request_id,
            approval_request_read_predicate(session, context),
        )
    )
    if allowed is None:
        raise AppError("approval_read_denied", "Approval is outside the current user's review scope", status_code=403)


def can_decide_approval(session: Session, task: ApprovalTask, context: IdentityContext) -> bool:
    if task.project_id not in context.visible_project_ids:
        return False
    if task.review_stage == "manager_review":
        return task.assignee_user_id == context.user_id
    if task.review_stage == "owner_review":
        return session.get(ProjectOwner, (task.project_id, context.user_id)) is not None
    return False
