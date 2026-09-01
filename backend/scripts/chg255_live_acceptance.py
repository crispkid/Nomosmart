from __future__ import annotations

import os
from pathlib import Path
import sys
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import ExternalGroup, ExternalGroupUser, IdentitySyncRun, User
from app.integrations.keycloak import KeycloakSnapshot
from app.services.identity_sync import reconcile_snapshot


def _user(user_id: str, display_name: str) -> dict[str, object]:
    return {
        "id": user_id,
        "username": user_id,
        "displayName": display_name,
        "enabled": True,
        "attributes": {},
    }


def main() -> None:
    database_url = os.environ.get("CHG255_TEST_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("CHG255_TEST_DATABASE_URL is required for disposable PostgreSQL acceptance")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            existing_user = User(
                keycloak_user_id="chg255-existing-user",
                display_name="Existing User",
                auth_source="keycloak",
                is_active=True,
            )
            existing_group = ExternalGroup(
                source="keycloak",
                external_group_id="chg255-existing-group",
                group_name="Existing Group",
                path="/ldap/existing",
                identity_origin="ldap",
                is_active=True,
            )
            session.add_all((existing_user, existing_group))
            session.flush()
            session.add(ExternalGroupUser(external_group_id=existing_group.id, user_id=existing_user.id, created_at=datetime.now(UTC)))
            people_run = IdentitySyncRun(
                source="keycloak",
                status="running",
                trigger_type="manual",
                requested_scope="people",
                phase="reconciliation",
            )
            session.add(people_run)
            session.flush()

            people_snapshot = KeycloakSnapshot(
                users=(
                    _user("chg255-existing-user", "Updated User"),
                    _user("chg255-new-user", "New User"),
                ),
                groups=(
                    {"id": "chg255-ignored-group", "name": "Ignored Group", "path": "/ldap/ignored"},
                ),
                user_group_ids={
                    "chg255-existing-user": frozenset({"chg255-ignored-group"}),
                    "chg255-new-user": frozenset(),
                },
            )
            reconcile_snapshot(session, people_run, people_snapshot, requested_scope="people")
            session.flush()
            session.expire_all()
            assert session.scalar(select(func.count()).select_from(User)) == 2
            assert session.scalar(select(User.display_name).where(User.keycloak_user_id == "chg255-existing-user")) == "Updated User"
            assert session.scalar(select(func.count()).select_from(ExternalGroup)) == 1
            assert session.scalar(select(ExternalGroup.group_name)) == "Existing Group"
            assert session.scalar(select(func.count()).select_from(ExternalGroupUser)) == 1
            assert people_run.groups_created == 0
            assert people_run.role_memberships_updated == 0

            groups_run = IdentitySyncRun(
                source="keycloak",
                status="running",
                trigger_type="manual",
                requested_scope="groups",
                phase="reconciliation",
            )
            session.add(groups_run)
            session.flush()
            groups_snapshot = KeycloakSnapshot(
                users=(
                    _user("chg255-existing-user", "Must Not Replace Profile"),
                    _user("chg255-unknown-user", "Unknown User"),
                ),
                groups=(
                    {"id": "chg255-hr-group", "name": "hr", "path": "/ldap/hr"},
                ),
                user_group_ids={
                    "chg255-existing-user": frozenset({"chg255-hr-group"}),
                    "chg255-unknown-user": frozenset({"chg255-hr-group"}),
                },
            )
            reconcile_snapshot(session, groups_run, groups_snapshot, requested_scope="groups")
            session.flush()
            session.expire_all()
            assert session.scalar(select(func.count()).select_from(User)) == 2
            assert session.scalar(select(User.display_name).where(User.keycloak_user_id == "chg255-existing-user")) == "Updated User"
            assert session.scalar(select(User.id).where(User.keycloak_user_id == "chg255-unknown-user")) is None
            assert session.scalar(select(ExternalGroup.is_active).where(ExternalGroup.external_group_id == "chg255-existing-group")) is False
            hr_group_id = session.scalar(select(ExternalGroup.id).where(ExternalGroup.external_group_id == "chg255-hr-group"))
            assert hr_group_id is not None
            assert session.scalar(select(func.count()).select_from(ExternalGroupUser).where(ExternalGroupUser.external_group_id == hr_group_id)) == 1
            assert groups_run.users_created == 0
            assert groups_run.users_updated == 0
            assert groups_run.users_disabled == 0
            assert groups_run.groups_created == 1
            session.rollback()
    finally:
        engine.dispose()
    print("chg255-live: people/group scope preservation passed on disposable PostgreSQL")


if __name__ == "__main__":
    main()
