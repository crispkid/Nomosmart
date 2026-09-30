from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.core.errors import AppError


class PermissionAction(StrEnum):
    VIEW = "view"
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    EXECUTE = "execute"


MENU_MODULE = "Menu"
MENU_KNOWLEDGE_PROJECTS = "KnowledgeProjects"
MENU_REPORTS = "Reports"
MENU_SYSTEM_MANAGEMENT = "SystemManagement"
PROJECT_MODULE = "Project"
PROJECT_ARCHIVE = "ProjectArchive"
REPORT_MODULE = "Report"
REPORT_MODEL_REPORT = "ModelReport"

MENU_PERMISSION_ACTIONS: dict[str, frozenset[PermissionAction]] = {
    MENU_KNOWLEDGE_PROJECTS: frozenset({PermissionAction.VIEW, PermissionAction.CREATE}),
    MENU_REPORTS: frozenset({PermissionAction.VIEW}),
    MENU_SYSTEM_MANAGEMENT: frozenset(
        {
            PermissionAction.VIEW,
            PermissionAction.CREATE,
            PermissionAction.EDIT,
            PermissionAction.DELETE,
        }
    ),
}

MANAGED_PERMISSION_ACTIONS: dict[tuple[str, str], frozenset[PermissionAction]] = {
    **{(MENU_MODULE, function_name): actions for function_name, actions in MENU_PERMISSION_ACTIONS.items()},
    (PROJECT_MODULE, PROJECT_ARCHIVE): frozenset({PermissionAction.EXECUTE}),
    (REPORT_MODULE, REPORT_MODEL_REPORT): frozenset({PermissionAction.VIEW}),
}


@dataclass(frozen=True)
class PermissionGrant:
    module_name: str
    function_name: str
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_execute: bool = False

    def allows(self, action: PermissionAction) -> bool:
        return {
            PermissionAction.VIEW: self.can_view,
            PermissionAction.CREATE: self.can_create,
            PermissionAction.EDIT: self.can_edit,
            PermissionAction.DELETE: self.can_delete,
            PermissionAction.EXECUTE: self.can_execute,
        }[action]


def has_permission(
    grants: list[PermissionGrant],
    module_name: str,
    function_name: str,
    action: PermissionAction,
) -> bool:
    return any(
        grant.module_name == module_name
        and grant.function_name == function_name
        and grant.allows(action)
        for grant in grants
    )


def has_application_access(grants: list[PermissionGrant] | tuple[PermissionGrant, ...]) -> bool:
    return any(
        grant.can_view
        or grant.can_create
        or grant.can_edit
        or grant.can_delete
        or grant.can_execute
        for grant in grants
    )


def require_application_access(grants: list[PermissionGrant] | tuple[PermissionGrant, ...]) -> None:
    if not has_application_access(grants):
        raise AppError(
            "application_access_denied",
            "Application access has not been granted",
            status_code=403,
        )


def require_permission(
    grants: list[PermissionGrant],
    module_name: str,
    function_name: str,
    action: PermissionAction,
) -> None:
    if not has_permission(grants, module_name, function_name, action):
        raise AppError("permission_denied", "Permission is required for this operation", status_code=403)


def has_menu_permission(grants: list[PermissionGrant], menu_name: str, action: PermissionAction) -> bool:
    return has_permission(grants, MENU_MODULE, menu_name, action)


def require_menu_permission(grants: list[PermissionGrant], menu_name: str, action: PermissionAction) -> None:
    require_permission(grants, MENU_MODULE, menu_name, action)


def supported_menu_action(menu_name: str, action: PermissionAction) -> bool:
    return action in MENU_PERMISSION_ACTIONS.get(menu_name, frozenset())


def require_project_scope(project_id: UUID, visible_project_ids: set[UUID]) -> None:
    if project_id not in visible_project_ids:
        raise AppError("project_scope_denied", "Project is outside the current user's scope", status_code=403)
