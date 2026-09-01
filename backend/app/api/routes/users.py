from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import UserLocalUpdate, UserStatusUpdate, UserSummary
from app.core.errors import AppError
from app.db.models import Role, RolePermission, RoleUser, User
from app.db.session import get_db
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, MENU_MODULE, MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.services.audit import add_audit


router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserSummary])
def list_users(
    scope: str = Query(default="system", pattern="^(system|project_members)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[User]:
    if scope == "project_members":
        require_menu_permission(list(context.grants), MENU_KNOWLEDGE_PROJECTS, PermissionAction.VIEW)
        return list(
            session.scalars(
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
                .order_by(User.display_name, User.id)
                .offset(offset)
                .limit(limit)
            )
        )
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    return list(session.scalars(select(User).order_by(User.display_name, User.id).offset(offset).limit(limit)))


@router.put("/{user_id}", response_model=UserSummary)
def update_user_local_fields(
    user_id: UUID,
    payload: UserLocalUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> User:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    user = session.get(User, user_id)
    if user is None:
        raise AppError("user_not_found", "User was not found", status_code=404)
    changes = payload.model_dump(exclude_unset=True)
    delegate_id = changes.get("manager_delegate_user_id")
    if delegate_id is not None:
        delegate = session.get(User, delegate_id)
        if delegate is None or not delegate.is_active:
            raise AppError("invalid_manager_delegate", "Manager delegate must be an active user", status_code=422)
    for field, value in changes.items():
        setattr(user, field, value)
    safe_changes = {key: str(value) if isinstance(value, UUID) else value for key, value in changes.items()}
    add_audit(session, actor_user_id=context.user_id, action="user.local.update", resource_type="user", resource_id=user.id, result="success", request_id=request.state.request_id, summary=safe_changes)
    session.commit()
    session.refresh(user)
    return user


@router.patch("/{user_id}/status", response_model=UserSummary)
def update_user_status(
    user_id: UUID,
    payload: UserStatusUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> User:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    user = session.get(User, user_id)
    if user is None:
        raise AppError("user_not_found", "User was not found", status_code=404)
    old = user.is_active
    user.is_active = payload.is_active
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
    return user
