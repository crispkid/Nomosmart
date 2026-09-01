from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ProjectMember, ProjectOwner
from app.security.permissions import require_project_scope


PROJECT_OWNER_ROLES = frozenset({"owner"})
PROJECT_EDITOR_ROLES = frozenset({"owner", "editor"})
PROJECT_VIEWER_ROLES = frozenset({"owner", "editor", "viewer"})


def project_roles(session: Session, project_id: UUID, user_id: UUID) -> set[str]:
    roles = set(
        session.scalars(
            select(ProjectMember.project_role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
    )
    if session.get(ProjectOwner, (project_id, user_id)) is not None:
        roles.add("owner")
    return roles


def has_project_role(session: Session, project_id: UUID, user_id: UUID, allowed_roles: frozenset[str]) -> bool:
    return bool(project_roles(session, project_id, user_id) & allowed_roles)


def require_project_role(
    session: Session,
    project_id: UUID,
    user_id: UUID,
    visible_project_ids: set[UUID],
    allowed_roles: frozenset[str],
    *,
    code: str = "project_role_required",
    message: str = "Project role is required for this operation",
) -> None:
    require_project_scope(project_id, visible_project_ids)
    if has_project_role(session, project_id, user_id, allowed_roles):
        return
    raise AppError(code, message, status_code=403)
