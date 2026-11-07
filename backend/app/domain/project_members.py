from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Project, ProjectOwner, Role, RolePermission, RoleUser, User
from app.domain.project_access import get_scoped_project, require_project_owner
from app.security.context import IdentityContext
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, MENU_MODULE


@dataclass(frozen=True)
class ProjectMemberCandidateSearch:
    users: list[User]
    total: int
    ineligible_match_count: int


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _knowledge_project_view_exists_for_user() -> object:
    return (
        select(RoleUser.user_id)
        .join(RolePermission, RolePermission.role_id == RoleUser.role_id)
        .join(Role, Role.id == RoleUser.role_id)
        .where(
            RoleUser.user_id == User.id,
            Role.is_active.is_(True),
            Role.deleted_at.is_(None),
            RolePermission.module_name == MENU_MODULE,
            RolePermission.function_name == MENU_KNOWLEDGE_PROJECTS,
            RolePermission.can_view.is_(True),
        )
        .correlate(User)
        .exists()
    )


def users_with_knowledge_project_view(session: Session, user_ids: set[UUID]) -> set[UUID]:
    if not user_ids:
        return set()
    return set(
        session.scalars(
            select(RoleUser.user_id)
            .join(RolePermission, RolePermission.role_id == RoleUser.role_id)
            .join(Role, Role.id == RoleUser.role_id)
            .where(
                RoleUser.user_id.in_(user_ids),
                Role.is_active.is_(True),
                Role.deleted_at.is_(None),
                RolePermission.module_name == MENU_MODULE,
                RolePermission.function_name == MENU_KNOWLEDGE_PROJECTS,
                RolePermission.can_view.is_(True),
            )
        )
    )


def validate_project_member_candidates(session: Session, user_ids: set[UUID]) -> None:
    if not user_ids:
        return
    active_ids = set(session.scalars(select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True))).all())
    if active_ids != user_ids:
        raise AppError("invalid_project_member", "All project members must be active users", status_code=422)
    if users_with_knowledge_project_view(session, user_ids) != user_ids:
        raise AppError("invalid_project_member_permission", "Project members must have Knowledge Projects menu view permission", status_code=422)


def search_project_member_candidates(
    session: Session,
    *,
    query: str,
    offset: int,
    limit: int,
) -> ProjectMemberCandidateSearch:
    normalized_query = query.strip()
    if not normalized_query:
        raise AppError("project_member_query_required", "Project member search requires a non-blank query", status_code=422)
    pattern = f"%{_escape_like(normalized_query)}%"
    given_family = func.concat_ws(" ", User.given_name, User.family_name)
    family_given = func.concat_ws(" ", User.family_name, User.given_name)
    given_family_compact = func.concat(func.coalesce(User.given_name, ""), func.coalesce(User.family_name, ""))
    family_given_compact = func.concat(func.coalesce(User.family_name, ""), func.coalesce(User.given_name, ""))
    ldap_rdn_alias = func.split_part(func.split_part(func.coalesce(User.ldap_dn, ""), ",", 1), "=", 2)
    matches_query = or_(
        func.coalesce(User.display_name, "").ilike(pattern, escape="\\"),
        func.coalesce(User.given_name, "").ilike(pattern, escape="\\"),
        func.coalesce(User.family_name, "").ilike(pattern, escape="\\"),
        given_family.ilike(pattern, escape="\\"),
        family_given.ilike(pattern, escape="\\"),
        given_family_compact.ilike(pattern, escape="\\"),
        family_given_compact.ilike(pattern, escape="\\"),
        func.coalesce(User.email, "").ilike(pattern, escape="\\"),
        func.coalesce(User.employee_id, "").ilike(pattern, escape="\\"),
        func.coalesce(User.keycloak_user_id, "").ilike(pattern, escape="\\"),
        func.split_part(func.coalesce(User.email, ""), "@", 1).ilike(pattern, escape="\\"),
        ldap_rdn_alias.ilike(pattern, escape="\\"),
    )
    eligible = _knowledge_project_view_exists_for_user()
    base_conditions = (User.is_active.is_(True), matches_query)
    total = session.scalar(select(func.count()).select_from(User).where(*base_conditions, eligible)) or 0
    ineligible_match_count = session.scalar(select(func.count()).select_from(User).where(*base_conditions, ~eligible)) or 0
    users = list(
        session.scalars(
            select(User)
            .where(*base_conditions, eligible)
            .order_by(func.lower(User.display_name), func.lower(func.coalesce(User.email, "")), User.id)
            .offset(offset)
            .limit(limit)
        )
    )
    return ProjectMemberCandidateSearch(
        users=users,
        total=int(total),
        ineligible_match_count=int(ineligible_match_count),
    )


def lock_project_for_member_mutation(session: Session, project_id: UUID, context: IdentityContext) -> Project:
    get_scoped_project(session, project_id, context)
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    require_project_owner(session, project_id, context.user_id)
    return project


def reject_protected_owner_mutation(
    session: Session,
    *,
    project_id: UUID,
    target_user_id: UUID,
    actor_user_id: UUID,
) -> None:
    if session.get(ProjectOwner, (project_id, target_user_id)) is None:
        return
    owner_count = session.scalar(select(func.count()).select_from(ProjectOwner).where(ProjectOwner.project_id == project_id)) or 0
    if owner_count <= 1:
        raise AppError("last_project_owner", "A project must retain at least one Owner", status_code=409)
    if target_user_id == actor_user_id:
        raise AppError("project_owner_self_protected", "Project Owners cannot change or remove their own Owner membership", status_code=409)
