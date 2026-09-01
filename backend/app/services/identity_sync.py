from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ExternalGroup, ExternalGroupUser, IdentitySyncRun, Role, RoleUser, User
from app.integrations.keycloak import KeycloakSnapshot
from app.services.role_memberships import acquire_identity_membership_lock, identity_origin_for_path, normalized_group_path, reconcile_external_role_memberships


EMPLOYEE_ID = re.compile(r"^Z.{0,9}$")
@dataclass(frozen=True)
class NormalizedUser:
    keycloak_id: str
    employee_id: str | None
    ldap_dn: str | None
    email: str | None
    given_name: str | None
    family_name: str | None
    display_name: str | None
    department: str | None
    title: str | None
    manager_ldap_dn: str | None
    manager_employee_id: str | None
    enabled: bool
    auth_source: str
    username: str


def _attribute(item: dict[str, Any], name: str) -> str | None:
    values = (item.get("attributes") or {}).get(name)
    if isinstance(values, list) and values:
        return str(values[0])
    if isinstance(values, str):
        return values
    return None


def _normalize_dn(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized.lower() if normalized else None


def normalize_snapshot(snapshot: KeycloakSnapshot) -> tuple[list[NormalizedUser], list[dict[str, Any]]]:
    users: list[NormalizedUser] = []
    seen_ids: set[str] = set()
    seen_employees: set[str] = set()
    for item in snapshot.users:
        keycloak_id = item.get("id")
        if not isinstance(keycloak_id, str) or not keycloak_id or keycloak_id in seen_ids:
            raise AppError("identity_snapshot_invalid", "Keycloak snapshot contains an invalid or duplicate user id", status_code=422)
        seen_ids.add(keycloak_id)
        employee_id = _attribute(item, "employee_id")
        if employee_id and (not EMPLOYEE_ID.fullmatch(employee_id) or employee_id in seen_employees):
            raise AppError("identity_snapshot_invalid", "Keycloak snapshot contains an invalid or duplicate employee id", status_code=422)
        if employee_id:
            seen_employees.add(employee_id)
        given_name = str(item.get("firstName") or "").strip() or None
        family_name = str(item.get("lastName") or "").strip() or None
        source_display_name = str(item.get("displayName") or "").strip() or None
        display_name = " ".join(value for value in (given_name, family_name) if value) or source_display_name
        username = str(item.get("username") or "").strip()
        if not display_name and not username:
            raise AppError("identity_snapshot_invalid", "Keycloak snapshot contains a user without a display name", status_code=422)
        ldap_dn = _attribute(item, "ldap_dn") or _attribute(
            item, "LDAP_ENTRY_DN"
        )
        auth_source = (
            "ldap"
            if ldap_dn or bool(item.get("federationLink"))
            else "keycloak"
        )
        users.append(
            NormalizedUser(
                keycloak_id=keycloak_id,
                employee_id=employee_id,
                ldap_dn=ldap_dn,
                email=item.get("email"),
                given_name=given_name,
                family_name=family_name,
                display_name=display_name,
                department=_attribute(item, "department"),
                title=_attribute(item, "title"),
                manager_ldap_dn=_attribute(item, "manager"),
                manager_employee_id=_attribute(item, "manager_employee_id"),
                enabled=bool(item.get("enabled", True)),
                auth_source=auth_source,
                username=username,
            )
        )

    groups: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for item in snapshot.groups:
        group_id = item.get("id")
        name = item.get("name")
        if not isinstance(group_id, str) or not group_id or group_id in seen_groups or not isinstance(name, str) or not name:
            raise AppError("identity_snapshot_invalid", "Keycloak snapshot contains an invalid or duplicate group", status_code=422)
        seen_groups.add(group_id)
        groups.append(item)
    unknown = set().union(*snapshot.user_group_ids.values()) - seen_groups if snapshot.user_group_ids else set()
    if unknown:
        raise AppError("identity_snapshot_invalid", "Keycloak snapshot references an unknown group", status_code=422)
    return users, groups


def reconcile_snapshot(
    session: Session,
    run: IdentitySyncRun,
    snapshot: KeycloakSnapshot,
    *,
    ldap_group_path: str = "/ldap",
    break_glass_username: str = "",
    requested_scope: str = "people_and_groups",
    now: datetime | None = None,
    acquire_lock: bool = True,
) -> IdentitySyncRun:
    if requested_scope not in {"people", "groups", "people_and_groups"}:
        raise AppError("identity_sync_scope_invalid", "Identity synchronization scope was invalid", status_code=422)
    normalized_users, normalized_groups = normalize_snapshot(snapshot)
    apply_people = requested_scope in {"people", "people_and_groups"}
    apply_groups = requested_scope in {"groups", "people_and_groups"}
    if acquire_lock:
        acquire_identity_membership_lock(session)
    timestamp = now or datetime.now(UTC)
    existing_users = {row.keycloak_user_id: row for row in session.scalars(select(User)).all()}
    user_by_keycloak: dict[str, User] = dict(existing_users) if not apply_people else {}
    created = updated = disabled = 0
    if apply_people:
        for item in normalized_users:
            user = existing_users.get(item.keycloak_id)
            if user is None:
                user = User(
                    keycloak_user_id=item.keycloak_id,
                    given_name=item.given_name,
                    family_name=item.family_name,
                    display_name=item.display_name or item.username,
                    auth_source=item.auth_source,
                    is_active=item.enabled,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(user)
                session.flush()
                created += 1
            else:
                updated += 1
            user.employee_id = item.employee_id
            user.ldap_dn = item.ldap_dn
            user.email = item.email
            user.given_name = item.given_name
            user.family_name = item.family_name
            user.display_name = item.display_name or user.display_name or item.username
            user.department = item.department
            user.title = item.title
            user.auth_source = item.auth_source
            is_break_glass = bool(break_glass_username) and item.auth_source == "keycloak" and item.username.casefold() == break_glass_username.casefold()
            user.is_active = item.enabled or is_break_glass
            user.last_synced_at = timestamp
            user.updated_at = timestamp
            user_by_keycloak[item.keycloak_id] = user
        snapshot_user_ids = set(user_by_keycloak)
        for keycloak_id, user in existing_users.items():
            if keycloak_id not in snapshot_user_ids and user.is_active:
                user.is_active = False
                user.last_synced_at = timestamp
                user.updated_at = timestamp
                disabled += 1

        by_employee = {user.employee_id: user for user in user_by_keycloak.values() if user.employee_id}
        by_ldap_dn = {_normalize_dn(user.ldap_dn): user for user in user_by_keycloak.values() if _normalize_dn(user.ldap_dn)}
        normalized_by_id = {item.keycloak_id: item for item in normalized_users}
        for keycloak_id, user in user_by_keycloak.items():
            normalized = normalized_by_id[keycloak_id]
            manager = by_ldap_dn.get(_normalize_dn(normalized.manager_ldap_dn))
            if manager is None and normalized.manager_employee_id in by_employee:
                manager = by_employee[normalized.manager_employee_id]
            user.manager_user_id = manager.id if manager else None

    existing_groups = {row.external_group_id: row for row in session.scalars(select(ExternalGroup).where(ExternalGroup.source == "keycloak")).all()}
    group_by_external: dict[str, ExternalGroup] = {}
    groups_created = groups_updated = 0
    derived_count = 0
    if apply_groups:
        for item in normalized_groups:
            external_id = str(item["id"])
            group = existing_groups.get(external_id)
            if group is None:
                group = ExternalGroup(source="keycloak", external_group_id=external_id, group_name=str(item["name"]), created_at=timestamp, updated_at=timestamp)
                session.add(group)
                session.flush()
                groups_created += 1
            else:
                groups_updated += 1
            group.group_name = str(item["name"])
            group.path = item.get("path")
            group.group_dn = _attribute(item, "ldap_dn")
            group.identity_origin = identity_origin_for_path(group.path, ldap_group_path=ldap_group_path)
            group.is_active = True
            group.last_synced_at = timestamp
            group.updated_at = timestamp
            group_by_external[external_id] = group
        for external_id, group in existing_groups.items():
            if external_id not in group_by_external:
                group.is_active = False
                group.last_synced_at = timestamp

        session.execute(delete(ExternalGroupUser))
        memberships: list[ExternalGroupUser] = []
        for keycloak_id, group_ids in snapshot.user_group_ids.items():
            user = user_by_keycloak.get(keycloak_id)
            if user is None:
                continue
            memberships.extend(ExternalGroupUser(external_group_id=group_by_external[group_id].id, user_id=user.id, created_at=timestamp) for group_id in group_ids)
        session.add_all(memberships)

        session.flush()
        derived_count = reconcile_external_role_memberships(session, now=timestamp)

    break_glass_name = break_glass_username.strip().casefold()
    if break_glass_name and apply_groups:
        break_glass_identity = next((item for item in normalized_users if item.username.casefold() == break_glass_name and item.auth_source == "keycloak"), None)
        break_glass_user = user_by_keycloak.get(break_glass_identity.keycloak_id) if break_glass_identity is not None else None
        break_glass_group = next(
            (
                item
                for item in normalized_groups
                if normalized_group_path(str(item.get("path") or "")) == "/system-admin"
                and identity_origin_for_path(str(item.get("path") or ""), ldap_group_path=ldap_group_path) == "keycloak_local"
            ),
            None,
        )
        break_glass_group_id = str(break_glass_group.get("id")) if break_glass_group is not None else ""
        is_protected_group_member = bool(
            break_glass_identity is not None
            and break_glass_group_id
            and break_glass_group_id in snapshot.user_group_ids.get(break_glass_identity.keycloak_id, frozenset())
        )
        system_admin_role = session.scalar(select(Role).where(Role.name == "system-admin", Role.is_system.is_(True), Role.deleted_at.is_(None)))
        if break_glass_user is None or not is_protected_group_member or system_admin_role is None:
            raise AppError("break_glass_membership_unavailable", "Break-glass role membership could not be reconciled", status_code=422)
        session.execute(delete(RoleUser).where(RoleUser.source == "break_glass"))
        session.add(RoleUser(role_id=system_admin_role.id, user_id=break_glass_user.id, source="break_glass", created_at=timestamp, updated_at=timestamp))
    elif break_glass_name and apply_people:
        break_glass_identity = next((item for item in normalized_users if item.username.casefold() == break_glass_name and item.auth_source == "keycloak"), None)
        if break_glass_identity is None or user_by_keycloak.get(break_glass_identity.keycloak_id) is None:
            raise AppError("break_glass_membership_unavailable", "Break-glass account could not be reconciled", status_code=422)

    run.status = "succeeded"
    run.phase = "completed"
    run.completed_at = timestamp
    run.users_created = created
    run.users_updated = updated
    run.users_disabled = disabled
    run.groups_created = groups_created
    run.groups_updated = groups_updated
    run.role_memberships_updated = derived_count
    run.error_code = None
    run.error_message = None
    return run
