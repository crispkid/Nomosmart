from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select, true
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ApprovalRequest, ApprovalTask, ProjectMember, ProjectOwner, ReviewRecord, Role, RolePermission, RoleUser, User
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


def eligible_manager_reviewer(session: Session, user_id: UUID, project_id: UUID | None = None) -> bool:
    """Current application admission and scope, never retired Review flags."""
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return False
    admitted = session.scalar(select(RolePermission.id).join(RoleUser, RoleUser.role_id == RolePermission.role_id)
        .join(Role, Role.id == RolePermission.role_id).where(RoleUser.user_id == user_id,
            Role.is_active.is_(True), Role.deleted_at.is_(None),
            or_(RolePermission.can_view, RolePermission.can_create, RolePermission.can_edit,
                RolePermission.can_delete, RolePermission.can_execute)).limit(1))
    if admitted is None:
        return False
    return project_id is None or session.scalar(select(ProjectMember.user_id).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == user_id).limit(1)) is not None or session.get(ProjectOwner, (project_id, user_id)) is not None


def approval_request_read_predicate(session: Session, context: IdentityContext):
    """Shared SQL visibility, evaluated before pagination or evidence access."""
    if is_approval_auditor(session, context):
        return true()
    assigned = select(ApprovalTask.id).where(
        ApprovalTask.approval_request_id == ApprovalRequest.id,
        ApprovalTask.assignee_user_id == context.user_id,
    ).exists()
    original_manager = select(ApprovalTask.id).where(
        ApprovalTask.approval_request_id == ApprovalRequest.id,
        ApprovalTask.original_manager_user_id == context.user_id,
    ).exists()
    reviewed = select(ReviewRecord.id).where(
        ReviewRecord.document_version_id == ApprovalRequest.document_version_id,
        ReviewRecord.reviewer_id == context.user_id,
    ).exists()
    manager = select(User.id).where(
        User.id == ApprovalRequest.submitter_id,
        User.manager_user_id == context.user_id,
    ).exists()
    # CHG-480 DELEG480-004: manager delegates were removed; a former delegate reads only what another rule allows.
    owner = select(ProjectOwner.project_id).where(
        ProjectOwner.project_id == ApprovalRequest.project_id,
        ProjectOwner.user_id == context.user_id,
    ).exists()
    return and_(
        ApprovalRequest.project_id.in_(context.visible_project_ids),
        or_(ApprovalRequest.submitter_id == context.user_id, assigned, original_manager, reviewed, manager, owner),
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


def reviewer_unavailable(session: Session, task: ApprovalTask) -> bool:
    """F454-RETURN-01 RET454-002: the assigned reviewer's account no longer exists or is disabled."""
    if task.assignee_user_id is None:
        return True
    user = session.get(User, task.assignee_user_id)
    return user is None or not user.is_active or not user.directory_enabled or user.locally_disabled


def unavailable_reviewer_ids():
    """SQL: users who cannot act as reviewer (RET454-002); a missing user is handled by the caller."""
    return select(User.id).where(or_(User.is_active.is_(False), User.directory_enabled.is_(False), User.locally_disabled.is_(True)))


def other_owner_ids(session: Session, submitter_id: UUID, project_id: UUID) -> tuple[UUID, ...]:
    """CHG-471 SELFREV471-003/004: Project Owners other than the submitter who can decide the Owner stage."""
    return tuple(owner_id for owner_id in session.scalars(
        select(ProjectOwner.user_id).where(ProjectOwner.project_id == project_id).order_by(ProjectOwner.user_id))
        if owner_id != submitter_id and not reviewer_unavailable_id(session, owner_id)
        and eligible_manager_reviewer(session, owner_id, project_id))


def reviewer_unavailable_id(session: Session, user_id: UUID) -> bool:
    user = session.get(User, user_id)
    return user is None or not user.is_active or not user.directory_enabled or user.locally_disabled


def owner_stage_unattended(session: Session, task: ApprovalTask) -> bool:
    """SELFREV471-004: an Owner-stage task nobody but its own submitter could decide."""
    return task.review_stage == "owner_review" and not other_owner_ids(session, task.submitter_id, task.project_id)


def owner_fallback_reject(session: Session, task: ApprovalTask, context: IdentityContext) -> bool:
    """RET454-002: a Project Owner may return (never approve) a manager-review task whose reviewer is unavailable.

    SELFREV471-002: never the submitter's own submission."""
    return (task.review_stage == "manager_review" and task.status == "pending" and task.assignee_user_id != context.user_id
            and task.submitter_id != context.user_id
            and task.project_id in context.visible_project_ids
            and session.get(ProjectOwner, (task.project_id, context.user_id)) is not None
            and reviewer_unavailable(session, task))


def allowed_decisions(session: Session, task: ApprovalTask, context: IdentityContext) -> list[str]:
    if task.status != "pending":
        return []
    if can_decide_approval(session, task, context):
        return ["approve", "reject"]
    return ["reject"] if owner_fallback_reject(session, task, context) else []


def can_decide_approval(session: Session, task: ApprovalTask, context: IdentityContext) -> bool:
    if task.project_id not in context.visible_project_ids:
        return False
    if task.review_stage == "manager_review":
        return task.assignee_user_id == context.user_id
    if task.review_stage == "owner_review":
        if session.get(ProjectOwner, (task.project_id, context.user_id)) is None:
            return False
        # SELFREV471-001 (extends REVROUTE467-006 to every route): the submitter never decides their own submission.
        return task.submitter_id != context.user_id
    return False
