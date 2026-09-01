from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ProjectMember, ProjectOwner, Role, RolePermission, RoleUser, User
from app.db.session import get_db
from app.security.auth import IdentityPrincipal, get_current_principal
from app.security.permissions import PermissionGrant, require_application_access
from app.services.audit import add_audit


@dataclass(frozen=True)
class IdentityContext:
    user_id: UUID
    principal: IdentityPrincipal
    grants: tuple[PermissionGrant, ...]
    visible_project_ids: frozenset[UUID]


def application_access_denied_audit_summary(principal: IdentityPrincipal) -> dict[str, object]:
    return {
        "issuer": principal.issuer,
        "subject_fingerprint": sha256(principal.subject.encode("utf-8")).hexdigest(),
        "session_fingerprint": sha256(principal.session_id.encode("utf-8")).hexdigest() if principal.session_id else None,
        "reason": "no_effective_permission",
    }


def resolve_identity_context(session: Session, principal: IdentityPrincipal) -> IdentityContext:
    user = session.scalar(select(User).where(User.keycloak_user_id == principal.subject))
    if user is None:
        raise AppError("user_not_synchronized", "User has not been synchronized", status_code=403)
    if not user.is_active:
        raise AppError("user_disabled", "User account is disabled", status_code=403)
    permission_rows = session.execute(
        select(RolePermission)
        .join(RoleUser, RoleUser.role_id == RolePermission.role_id)
        .join(Role, Role.id == RolePermission.role_id)
        .where(RoleUser.user_id == user.id, Role.is_active.is_(True), Role.deleted_at.is_(None))
    ).scalars()
    grants = tuple(
        PermissionGrant(
            row.module_name,
            row.function_name,
            row.can_view,
            row.can_create,
            row.can_edit,
            row.can_delete,
            row.can_execute,
        )
        for row in permission_rows
    )
    member_projects = session.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all()
    owner_projects = session.scalars(select(ProjectOwner.project_id).where(ProjectOwner.user_id == user.id)).all()
    return IdentityContext(user.id, principal, grants, frozenset((*member_projects, *owner_projects)))


def get_identity_context(
    request: Request,
    principal: IdentityPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> IdentityContext:
    context = resolve_identity_context(session, principal)
    try:
        require_application_access(context.grants)
    except AppError:
        add_audit(
            session,
            actor_user_id=context.user_id,
            action="auth.application_access_denied",
            resource_type="login_session",
            resource_id=None,
            result="denied",
            request_id=request.state.request_id,
            summary=application_access_denied_audit_summary(principal),
        )
        session.commit()
        raise
    return context
