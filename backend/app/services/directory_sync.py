from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AuthSession, ExternalGroup, ExternalGroupRoleMapping, ExternalGroupUser, IdentitySyncRun, User
from app.integrations.ldap_directory import DirectorySnapshot
from app.services.role_memberships import acquire_identity_membership_lock, reconcile_external_role_memberships


def reconcile_directory(session: Session, run: IdentitySyncRun, snapshot: DirectorySnapshot) -> None:
    acquire_identity_membership_lock(session)
    now = datetime.now(UTC)
    people_selected = run.requested_scope in {"people", "people_and_groups"}
    groups_selected = run.requested_scope in {"groups", "people_and_groups"}
    users = {u.directory_object_id: u for u in session.scalars(select(User).where(User.directory_source_id == snapshot.source_id))}
    if people_selected:
        incoming = {person.object_id for person in snapshot.people}
        for person in snapshot.people:
            row = users.get(person.object_id)
            if row is None:
                # A source migration must be explicit; employee/email/DN guesses
                # must never replace an existing person's UUID or authority.
                if person.employee_id and session.scalar(select(User.id).where(User.employee_id == person.employee_id)):
                    raise AppError("directory_migration_required", "An existing identity requires an explicit directory binding", status_code=409)
                row = User(id=uuid4(), keycloak_user_id=None, directory_source_id=snapshot.source_id, directory_object_id=person.object_id, display_name=person.display_name, is_active=person.enabled, directory_enabled=person.enabled, locally_disabled=False, auth_source=snapshot.schema_type)
                session.add(row)
                users[person.object_id] = row
                run.users_created += 1
            else:
                run.users_updated += 1
            was_active = row.is_active
            row.directory_enabled = person.enabled
            row.is_active = person.enabled and not row.locally_disabled
            row.employee_id, row.email = person.employee_id, person.email
            row.given_name, row.family_name = person.given_name, person.family_name
            row.display_name, row.department, row.title = person.display_name, person.department, person.title
            row.ldap_dn, row.auth_source, row.last_synced_at = person.dn, snapshot.schema_type, now
            if was_active and not row.is_active:
                run.users_disabled += 1
                session.execute(update(AuthSession).where(AuthSession.user_id == row.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now))
        for identifier, row in users.items():
            if identifier not in incoming:
                if row.is_active:
                    run.users_disabled += 1
                row.directory_enabled, row.is_active, row.last_synced_at = False, False, now
                session.execute(update(AuthSession).where(AuthSession.user_id == row.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now))
        session.flush()
        by_dn = {row.ldap_dn.casefold(): row for row in users.values() if row.ldap_dn}
        for person in snapshot.people:
            manager = by_dn.get((person.manager_dn or "").casefold())
            users[person.object_id].manager_user_id = manager.id if manager and manager.id != users[person.object_id].id else None
    if groups_selected:
        groups = {g.external_group_id: g for g in session.scalars(select(ExternalGroup).where(ExternalGroup.directory_source_id == snapshot.source_id))}
        legacy_mapping = session.scalar(select(ExternalGroupRoleMapping.id).join(ExternalGroup, ExternalGroup.id == ExternalGroupRoleMapping.external_group_id).where(ExternalGroup.directory_source_id.is_(None), ExternalGroup.identity_origin.in_(["ldap", "ad"])))
        if legacy_mapping:
            raise AppError("directory_group_migration_required", "Existing group mappings require explicit source bindings", status_code=409)
        for incoming in snapshot.groups:
            group = groups.get(incoming.object_id)
            if group is None:
                group = ExternalGroup(id=uuid4(), source=snapshot.schema_type, directory_source_id=snapshot.source_id, external_group_id=incoming.object_id, group_name=incoming.name, identity_origin=snapshot.schema_type, is_active=True)
                session.add(group)
                groups[incoming.object_id] = group
                run.groups_created += 1
            else:
                run.groups_updated += 1
            group.group_dn, group.group_name = incoming.dn, incoming.name
            group.is_active, group.last_synced_at = True, now
            group.path = incoming.dn
        incoming_ids = {g.object_id for g in snapshot.groups}
        for key, group in groups.items():
            if key not in incoming_ids:
                group.is_active = False
                group.last_synced_at = now
        session.flush()
        group_ids = [group.id for group in groups.values()]
        if group_ids:
            session.execute(delete(ExternalGroupUser).where(ExternalGroupUser.external_group_id.in_(group_ids)))
        for person_id, memberships in snapshot.user_group_ids.items():
            person = users.get(person_id)
            if memberships and person is None:
                raise AppError("directory_people_sync_required", "Synchronize people before their group memberships", status_code=409)
            for group_id in memberships:
                group = groups.get(group_id)
                if group is None or not group.is_active:
                    raise AppError("directory_snapshot_invalid", "Group membership references an unavailable group", status_code=422)
                session.add(ExternalGroupUser(external_group_id=group.id, user_id=person.id, created_at=now))
        session.flush()
        run.role_memberships_updated = reconcile_external_role_memberships(session)
    session.flush()
