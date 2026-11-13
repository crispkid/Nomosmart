from uuid import UUID
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import String, cast, func, or_, select, update
from sqlalchemy.orm import Session

from app.api.schemas import UserLocalUpdate, UserRoleSummary, UserStatusUpdate, UserSummary
from app.core.errors import AppError
from app.domain.approval_access import eligible_manager_reviewer
from app.db.models import AuthSession, IdentityUnlockGrant, Role, RolePermission, RoleUser, User
from app.db.session import get_db
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, MENU_MODULE, MENU_SYSTEM_MANAGEMENT, PermissionAction, has_menu_permission, require_menu_permission
from app.services.audit import add_audit


router = APIRouter(prefix="/users", tags=["users"])


def _user_summaries(session: Session, users: list[User], context: IdentityContext) -> list[UserSummary]:
    summaries = [UserSummary.model_validate(user) for user in users]
    if not users or not has_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW):
        return summaries
    grouped: dict[UUID, dict[UUID, tuple[str, set[str]]]] = {}
    rows = session.execute(
        select(RoleUser.user_id, Role.id, Role.name, RoleUser.source)
        .join(Role, Role.id == RoleUser.role_id)
        .where(RoleUser.user_id.in_([user.id for user in users]), Role.is_active.is_(True), Role.deleted_at.is_(None))
    )
    for user_id, role_id, name, source in rows:
        roles = grouped.setdefault(user_id, {})
        roles.setdefault(role_id, (name, set()))[1].add(source)
    return [summary.model_copy(update={"roles": [
        UserRoleSummary(id=role_id, name=name, sources=sorted(sources))
        for role_id, (name, sources) in sorted(grouped.get(summary.id, {}).items(), key=lambda row: (row[1][0].casefold(), str(row[0])))
    ]}) for summary in summaries]


@router.get("", response_model=list[UserSummary])
def list_users(
    response: Response,
    scope: str = Query(default="system", pattern="^(system|project_members)$"),
    q: str | None = Query(default=None, max_length=100),
    auth_source: str | None = Query(default=None, max_length=100),
    is_active: bool | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[UserSummary]:
    if scope == "project_members":
        require_menu_permission(list(context.grants), MENU_KNOWLEDGE_PROJECTS, PermissionAction.VIEW)
        statement = (
                select(User)
                .join(RoleUser, RoleUser.user_id == User.id)
                .join(RolePermission, RolePermission.role_id == RoleUser.role_id)
                .join(Role, Role.id == RoleUser.role_id)
                .where(
                    User.is_active.is_(True),
                    Role.is_active.is_(True),
                    Role.deleted_at.is_(None),
                    RolePermission.module_name == MENU_MODULE,
                    RolePermission.function_name == MENU_KNOWLEDGE_PROJECTS,
                    RolePermission.can_view.is_(True),
                )
                .distinct()
        )
    else:
        require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
        statement = select(User)
    if q and q.strip():
        value = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{value}%"
        statement = statement.where(or_(*(column.ilike(pattern, escape="\\") for column in (User.display_name, User.given_name, User.family_name, User.email, User.employee_id, User.department, User.auth_source, User.keycloak_user_id, cast(User.id, String)))))
    if auth_source:
        statement = statement.where(User.auth_source == auth_source)
    if is_active is not None:
        statement = statement.where(User.is_active.is_(is_active))
    response.headers["X-Total-Count"] = str(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    users = list(session.scalars(statement.order_by(User.display_name, User.id).offset(offset).limit(limit)))
    return _user_summaries(session, users, context)


@router.get("/{user_id}", response_model=UserSummary)
def get_user(user_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> UserSummary:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    user = session.get(User, user_id)
    if user is None:
        raise AppError("user_not_found", "User was not found", status_code=404)
    return _user_summaries(session, [user], context)[0]


@router.put("/{user_id}", response_model=UserSummary)
def update_user_local_fields(
    user_id: UUID,
    payload: UserLocalUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> UserSummary:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    user = session.get(User, user_id)
    if user is None:
        raise AppError("user_not_found", "User was not found", status_code=404)
    changes = payload.model_dump(exclude_unset=True)
    delegate_id = changes.get("manager_delegate_user_id")
    if delegate_id is not None:
        delegate = session.get(User, delegate_id)
        if delegate is None or not eligible_manager_reviewer(session, delegate_id):
            raise AppError("invalid_manager_delegate", "Manager delegate must be active with application access", status_code=422)
    for field, value in changes.items():
        setattr(user, field, value)
    safe_changes = {key: str(value) if isinstance(value, UUID) else value for key, value in changes.items()}
    add_audit(session, actor_user_id=context.user_id, action="user.local.update", resource_type="user", resource_id=user.id, result="success", request_id=request.state.request_id, summary=safe_changes)
    session.commit()
    session.refresh(user)
    return _user_summaries(session, [user], context)[0]


@router.patch("/{user_id}/status", response_model=UserSummary)
def update_user_status(
    user_id: UUID,
    payload: UserStatusUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> UserSummary:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    user = session.get(User, user_id)
    if user is None:
        raise AppError("user_not_found", "User was not found", status_code=404)
    if user.auth_source == "emergency":
        raise AppError("emergency_deployment_only", "Emergency access is controlled by deployment procedures", status_code=403)
    old = user.is_active
    user.locally_disabled = not payload.is_active
    user.is_active = payload.is_active and user.directory_enabled
    if not user.is_active:
        now = datetime.now(UTC)
        session.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now))
        session.execute(update(IdentityUnlockGrant).where(IdentityUnlockGrant.user_id == user.id, IdentityUnlockGrant.revoked_at.is_(None)).values(revoked_at=now))
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="user.status.update",
        resource_type="user",
        resource_id=user.id,
        result="success",
        request_id=request.state.request_id,
        summary={"old_is_active": old, "new_is_active": user.is_active},
    )
    session.commit()
    session.refresh(user)
    return _user_summaries(session, [user], context)[0]
