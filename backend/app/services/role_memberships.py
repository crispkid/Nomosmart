from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ExternalGroup, ExternalGroupRoleMapping, ExternalGroupUser, Role, RoleUser


IDENTITY_MEMBERSHIP_LOCK_KEY = 4_873_662_101


def normalized_group_path(value: str) -> str:
    path = value.strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return path.rstrip("/") or "/"


def identity_origin_for_path(path: str | None, *, ldap_group_path: str) -> str:
    normalized_path = normalized_group_path(path or "/")
    ldap_root = normalized_group_path(ldap_group_path)
    return "ldap" if ldap_root != "/" and normalized_path.startswith(f"{ldap_root}/") else "keycloak_local"


def acquire_identity_membership_lock(session: Session) -> None:
    acquired = session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": IDENTITY_MEMBERSHIP_LOCK_KEY})
    if acquired is False:
        raise AppError("identity_sync_already_running", "Identity synchronization or role mapping is already running", status_code=409)


def reconcile_external_role_memberships(
    session: Session,
    *,
    role_ids: Iterable[UUID] | None = None,
    now: datetime | None = None,
) -> int:
    selected_role_ids = frozenset(role_ids) if role_ids is not None else None
    if selected_role_ids == frozenset():
        return 0

    delete_statement = delete(RoleUser).where(RoleUser.source == "external_sync")
    if selected_role_ids is not None:
        delete_statement = delete_statement.where(RoleUser.role_id.in_(selected_role_ids))
    session.execute(delete_statement)

    membership_query = (
        select(ExternalGroupRoleMapping.role_id, ExternalGroupUser.user_id)
        .join(ExternalGroup, ExternalGroup.id == ExternalGroupRoleMapping.external_group_id)
        .join(Role, Role.id == ExternalGroupRoleMapping.role_id)
        .join(ExternalGroupUser, ExternalGroupUser.external_group_id == ExternalGroupRoleMapping.external_group_id)
        .where(
            ExternalGroup.identity_origin == "ldap",
            ExternalGroup.is_active.is_(True),
            Role.is_active.is_(True),
            Role.deleted_at.is_(None),
        )
    )
    if selected_role_ids is not None:
        membership_query = membership_query.where(ExternalGroupRoleMapping.role_id.in_(selected_role_ids))
    derived = {(role_id, user_id) for role_id, user_id in session.execute(membership_query)}
    timestamp = now or datetime.now(UTC)
    session.add_all(
        [
            RoleUser(
                role_id=role_id,
                user_id=user_id,
                source="external_sync",
                created_at=timestamp,
                updated_at=timestamp,
            )
            for role_id, user_id in sorted(derived, key=lambda item: (str(item[0]), str(item[1])))
        ]
    )
    return len(derived)
