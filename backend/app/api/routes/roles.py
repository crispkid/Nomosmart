from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import PermissionMatrixResponse, PermissionMatrixUpdate, PermissionValue, RoleCreate, RoleExternalGroupMappingResponse, RoleExternalGroupMappingUpdate, RoleResponse, RoleUpdate, RoleUserResponse, RoleUsersResponse, RoleUsersUpdate
from app.core.errors import AppError
from app.db.models import ExternalGroup, ExternalGroupRoleMapping, Role, RolePermission, RoleUser, User
from app.db.session import get_db
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MANAGED_PERMISSION_ACTIONS, MENU_KNOWLEDGE_PROJECTS, MENU_MODULE, MENU_REPORTS, MENU_SYSTEM_MANAGEMENT, PROJECT_ARCHIVE, PROJECT_MODULE, REPORT_MODEL_REPORT, REPORT_MODULE, PermissionAction, require_menu_permission
from app.services.audit import add_audit
from app.services.role_memberships import acquire_identity_membership_lock, reconcile_external_role_memberships


router = APIRouter(prefix="/roles", tags=["roles"])
MENU_MATRIX_FUNCTIONS = frozenset({MENU_KNOWLEDGE_PROJECTS, MENU_REPORTS, MENU_SYSTEM_MANAGEMENT})
MANAGED_MATRIX_KEYS = frozenset((*((MENU_MODULE, function_name) for function_name in MENU_MATRIX_FUNCTIONS), (PROJECT_MODULE, PROJECT_ARCHIVE), (REPORT_MODULE, REPORT_MODEL_REPORT)))


def _managed_permission_filter():
    return or_(
        and_(RolePermission.module_name == MENU_MODULE, RolePermission.function_name.in_(MENU_MATRIX_FUNCTIONS)),
        and_(RolePermission.module_name == PROJECT_MODULE, RolePermission.function_name == PROJECT_ARCHIVE),
        and_(RolePermission.module_name == REPORT_MODULE, RolePermission.function_name == REPORT_MODEL_REPORT),
    )


@router.get("", response_model=list[RoleResponse])
def list_roles(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[Role]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    return list(
        session.scalars(
            select(Role)
            .where(Role.deleted_at.is_(None))
            .order_by(Role.name, Role.id)
            .offset(offset)
            .limit(limit)
        )
    )


@router.post("", response_model=RoleResponse, status_code=201)
def create_role(
    payload: RoleCreate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> Role:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.CREATE)
    if session.scalar(select(Role.id).where(Role.name == payload.name, Role.deleted_at.is_(None))):
        raise AppError("role_name_conflict", "Role name already exists", status_code=409)
    role = Role(name=payload.name, description=payload.description, is_active=True, is_system=False)
    session.add(role)
    try:
        session.flush()
        add_audit(session, actor_user_id=context.user_id, action="role.create", resource_type="role", resource_id=role.id, result="success", request_id=request.state.request_id, summary={"name": role.name})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AppError("role_name_conflict", "Role name already exists", status_code=409) from exc
    session.refresh(role)
    return role


@router.put("/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> Role:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    requested_fields = payload.model_fields_set - {"lock_version"}
    lifecycle_change = "is_active" in requested_fields
    if not requested_fields:
        raise AppError("role_update_empty", "Role update must include a change", status_code=422)
    if lifecycle_change and (requested_fields != {"is_active"} or payload.is_active is None):
        raise AppError("invalid_role_lifecycle_update", "Role lifecycle changes must be standalone", status_code=422)
    if lifecycle_change:
        acquire_identity_membership_lock(session)

    role = session.scalar(select(Role).where(Role.id == role_id, Role.deleted_at.is_(None)).with_for_update())
    if role is None:
        raise AppError("role_not_found", "Role was not found", status_code=404)
    if role.lock_version != payload.lock_version:
        raise AppError("stale_role_version", "Role was changed by another request", status_code=409)
    changes = payload.model_dump(exclude_unset=True, exclude={"lock_version"})
    if role.is_system and (lifecycle_change or ("name" in changes and changes["name"] != role.name)):
        raise AppError("system_role_protected", "The system-admin role name and active state are protected", status_code=409)

    if lifecycle_change:
        next_active = bool(payload.is_active)
        if next_active == role.is_active:
            raise AppError("role_state_unchanged", "Role is already in the requested state", status_code=409)
        mapping = session.scalar(select(ExternalGroupRoleMapping).where(ExternalGroupRoleMapping.role_id == role.id).with_for_update())
        role.is_active = next_active
        role.lock_version += 1
        session.flush()
        derived_member_count = reconcile_external_role_memberships(session, role_ids=(role.id,))
        action = "role.enable" if next_active else "role.disable"
        add_audit(
            session,
            actor_user_id=context.user_id,
            action=action,
            resource_type="role",
            resource_id=role.id,
            result="success",
            request_id=request.state.request_id,
            summary={
                "external_group_id": str(mapping.external_group_id) if mapping is not None else None,
                "derived_member_count": derived_member_count,
            },
        )
        session.commit()
    else:
        if not role.is_active:
            raise AppError("inactive_role_read_only", "Inactive roles are read-only", status_code=409)
        if "name" in changes and changes["name"] is None:
            raise AppError("invalid_role_name", "Role name cannot be null", status_code=422)
        if "name" in changes and changes["name"] != role.name and session.scalar(
            select(Role.id).where(Role.name == changes["name"], Role.deleted_at.is_(None), Role.id != role.id)
        ):
            raise AppError("role_name_conflict", "Role name already exists", status_code=409)
        for field, value in changes.items():
            setattr(role, field, value)
        role.lock_version += 1
        add_audit(session, actor_user_id=context.user_id, action="role.update", resource_type="role", resource_id=role.id, result="success", request_id=request.state.request_id, summary=changes)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise AppError("role_name_conflict", "Role name already exists", status_code=409) from exc
    session.refresh(role)
    return role


@router.delete("/{role_id}", response_model=RoleResponse)
def delete_role(
    role_id: UUID,
    request: Request,
    lock_version: int = Query(ge=1),
    confirmation_name: str = Query(min_length=1, max_length=100),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> Role:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.DELETE)
    acquire_identity_membership_lock(session)
    role = session.scalar(select(Role).where(Role.id == role_id, Role.deleted_at.is_(None)).with_for_update())
    if role is None:
        raise AppError("role_not_found", "Role was not found", status_code=404)
    if role.is_system:
        raise AppError("system_role_protected", "System roles cannot be deleted", status_code=409)
    if confirmation_name != role.name:
        raise AppError("role_confirmation_mismatch", "Confirmation name does not match the role", status_code=422)
    if role.lock_version != lock_version:
        raise AppError("stale_role_version", "Role was changed by another request", status_code=409)
    mapping = session.scalar(select(ExternalGroupRoleMapping).where(ExternalGroupRoleMapping.role_id == role.id).with_for_update())
    released_group_id = mapping.external_group_id if mapping is not None else None
    if mapping is not None:
        session.delete(mapping)
    role.is_active = False
    role.deleted_at = datetime.now(UTC)
    role.deleted_by = context.user_id
    role.lock_version += 1
    session.flush()
    reconcile_external_role_memberships(session, role_ids=(role.id,))
    add_audit(session, actor_user_id=context.user_id, action="role.delete", resource_type="role", resource_id=role.id, result="success", request_id=request.state.request_id, summary={"released_external_group_id": str(released_group_id) if released_group_id else None})
    session.commit()
    session.refresh(role)
    return role


@router.put("/{role_id}/external-group-mapping", response_model=RoleExternalGroupMappingResponse)
def set_external_group_mapping(
    role_id: UUID,
    payload: RoleExternalGroupMappingUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> RoleExternalGroupMappingResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    acquire_identity_membership_lock(session)
    role = session.scalar(select(Role).where(Role.id == role_id, Role.deleted_at.is_(None)).with_for_update())
    if role is None:
        raise AppError("role_not_found", "Role was not found", status_code=404)
    if not role.is_active:
        raise AppError("inactive_role_read_only", "Inactive roles are read-only", status_code=409)
    if role.lock_version != payload.lock_version:
        raise AppError("stale_role_version", "Role was changed by another request", status_code=409)

    current = session.scalar(select(ExternalGroupRoleMapping).where(ExternalGroupRoleMapping.role_id == role.id).with_for_update())
    previous_group_id = current.external_group_id if current is not None else None
    external_group: ExternalGroup | None = None
    if payload.external_group_id is not None:
        external_group = session.scalar(select(ExternalGroup).where(ExternalGroup.id == payload.external_group_id).with_for_update())
        if external_group is None:
            raise AppError("external_group_not_found", "External group was not found", status_code=404)
        if not external_group.is_active or external_group.identity_origin != "ldap":
            raise AppError("invalid_ldap_group_mapping", "Mappings require an active LDAP group", status_code=422)
        occupied = session.scalar(
            select(ExternalGroupRoleMapping).where(
                ExternalGroupRoleMapping.external_group_id == external_group.id,
                ExternalGroupRoleMapping.role_id != role.id,
            )
        )
        if occupied is not None:
            raise AppError("external_group_already_mapped", "LDAP group is already mapped to another Local role", status_code=409)

    if current is not None and current.external_group_id != payload.external_group_id:
        session.delete(current)
        session.flush()
        current = None
    if payload.external_group_id is not None and current is None:
        session.add(
            ExternalGroupRoleMapping(
                external_group_id=payload.external_group_id,
                role_id=role.id,
                created_by=context.user_id,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()

    derived_member_count = reconcile_external_role_memberships(session, role_ids=(role.id,))
    role.lock_version += 1
    action = "role.external_group_mapping.unmap" if payload.external_group_id is None else "role.external_group_mapping.set"
    add_audit(
        session,
        actor_user_id=context.user_id,
        action=action,
        resource_type="role",
        resource_id=role.id,
        result="success",
        request_id=request.state.request_id,
        summary={
            "previous_external_group_id": str(previous_group_id) if previous_group_id else None,
            "external_group_id": str(payload.external_group_id) if payload.external_group_id else None,
            "derived_member_count": derived_member_count,
        },
    )
    session.commit()
    return RoleExternalGroupMappingResponse(
        role_id=role.id,
        external_group_id=payload.external_group_id,
        lock_version=role.lock_version,
        derived_member_count=derived_member_count,
    )


@router.get("/{role_id}/permissions", response_model=PermissionMatrixResponse)
def get_permissions(
    role_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> PermissionMatrixResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    role = session.scalar(select(Role).where(Role.id == role_id, Role.deleted_at.is_(None)))
    if role is None:
        raise AppError("role_not_found", "Role was not found", status_code=404)
    rows = list(
        session.scalars(
            select(RolePermission)
            .where(RolePermission.role_id == role_id, _managed_permission_filter())
            .order_by(RolePermission.module_name, RolePermission.function_name)
        )
    )
    return PermissionMatrixResponse(lock_version=role.lock_version, permissions=[PermissionValue.model_validate(row, from_attributes=True) for row in rows])


@router.put("/{role_id}/permissions", response_model=PermissionMatrixResponse)
def replace_permissions(
    role_id: UUID,
    payload: PermissionMatrixUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> PermissionMatrixResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    role = session.scalar(select(Role).where(Role.id == role_id, Role.deleted_at.is_(None)).with_for_update())
    if role is None:
        raise AppError("role_not_found", "Role was not found", status_code=404)
    if role.lock_version != payload.lock_version:
        raise AppError("stale_role_version", "Role was changed by another request", status_code=409)
    if not role.is_active:
        raise AppError("inactive_role_read_only", "Inactive roles are read-only", status_code=409)
    _validate_managed_permissions(payload.permissions)
    keys = [(item.module_name, item.function_name) for item in payload.permissions]
    if len(keys) != len(set(keys)):
        raise AppError("duplicate_permission", "Permission matrix contains duplicate functions", status_code=422)
    session.execute(delete(RolePermission).where(RolePermission.role_id == role_id, _managed_permission_filter()))
    now = datetime.now(UTC)
    rows = [RolePermission(role_id=role_id, **_normalized_managed_permission(item), created_at=now, updated_at=now) for item in payload.permissions]
    session.add_all(rows)
    role.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action="role.permissions.replace", resource_type="role", resource_id=role_id, result="success", request_id=request.state.request_id, summary={"permission_count": len(rows)})
    session.commit()
    return PermissionMatrixResponse(lock_version=role.lock_version, permissions=[PermissionValue.model_validate(row, from_attributes=True) for row in rows])


@router.get("/{role_id}/users", response_model=RoleUsersResponse)
def get_role_users(
    role_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> RoleUsersResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    role = session.scalar(select(Role).where(Role.id == role_id, Role.deleted_at.is_(None)))
    if role is None:
        raise AppError("role_not_found", "Role was not found", status_code=404)
    rows = list(session.scalars(select(RoleUser).where(RoleUser.role_id == role_id).order_by(RoleUser.source, RoleUser.user_id)))
    return RoleUsersResponse(lock_version=role.lock_version, users=[RoleUserResponse(user_id=row.user_id, source=row.source) for row in rows])


@router.put("/{role_id}/users", response_model=RoleUsersResponse)
def replace_manual_role_users(
    role_id: UUID,
    payload: RoleUsersUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> RoleUsersResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    role = session.scalar(select(Role).where(Role.id == role_id, Role.deleted_at.is_(None)).with_for_update())
    if role is None:
        raise AppError("role_not_found", "Role was not found", status_code=404)
    if role.lock_version != payload.lock_version:
        raise AppError("stale_role_version", "Role was changed by another request", status_code=409)
    if not role.is_active:
        raise AppError("inactive_role_read_only", "Inactive roles are read-only", status_code=409)
    user_ids = set(payload.user_ids)
    if user_ids:
        active_ids = set(session.scalars(select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True))).all())
        if active_ids != user_ids:
            raise AppError("invalid_role_users", "All manual role users must be active", status_code=422)
    session.execute(delete(RoleUser).where(RoleUser.role_id == role_id, RoleUser.source == "manual"))
    now = datetime.now(UTC)
    session.add_all([RoleUser(role_id=role_id, user_id=user_id, source="manual", created_at=now, updated_at=now) for user_id in sorted(user_ids, key=str)])
    role.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action="role.users.replace", resource_type="role", resource_id=role_id, result="success", request_id=request.state.request_id, summary={"manual_user_count": len(user_ids)})
    session.commit()
    rows = list(session.scalars(select(RoleUser).where(RoleUser.role_id == role_id).order_by(RoleUser.source, RoleUser.user_id)))
    return RoleUsersResponse(lock_version=role.lock_version, users=[RoleUserResponse(user_id=row.user_id, source=row.source) for row in rows])


def _validate_managed_permissions(permissions: list[PermissionValue]) -> None:
    invalid = [item for item in permissions if (item.module_name, item.function_name) not in MANAGED_MATRIX_KEYS]
    if invalid:
        raise AppError("unsupported_permission_matrix_row", "Permission matrix contains an unsupported row", status_code=422)
    for item in permissions:
        allowed_actions = MANAGED_PERMISSION_ACTIONS[(item.module_name, item.function_name)]
        requested_actions = {
            PermissionAction.VIEW: item.can_view,
            PermissionAction.CREATE: item.can_create,
            PermissionAction.EDIT: item.can_edit,
            PermissionAction.DELETE: item.can_delete,
            PermissionAction.EXECUTE: item.can_execute,
        }
        if any(enabled and action not in allowed_actions for action, enabled in requested_actions.items()):
            raise AppError("unsupported_permission_action", "Permission row contains an unsupported action", status_code=422)


def _normalized_managed_permission(item: PermissionValue) -> dict[str, object]:
    allowed_actions = MANAGED_PERMISSION_ACTIONS[(item.module_name, item.function_name)]
    return {
        "module_name": item.module_name,
        "function_name": item.function_name,
        "can_view": item.can_view if PermissionAction.VIEW in allowed_actions else False,
        "can_create": item.can_create if PermissionAction.CREATE in allowed_actions else False,
        "can_edit": item.can_edit if PermissionAction.EDIT in allowed_actions else False,
        "can_delete": item.can_delete if PermissionAction.DELETE in allowed_actions else False,
        "can_execute": item.can_execute if PermissionAction.EXECUTE in allowed_actions else False,
    }
