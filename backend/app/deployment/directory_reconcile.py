from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import ExternalGroup, ExternalGroupRoleMapping, Role, RoleUser, User
from app.deployment.bootstrap import (
    BootstrapFailure,
    DeploymentBootstrapSettings,
    _realm_name,
    _reconcile_identity_database,
)
from app.integrations.keycloak import KeycloakAdminClient
from app.services.audit import add_audit
from app.services.role_memberships import (
    acquire_identity_membership_lock,
    reconcile_external_role_memberships,
)
from sqlalchemy import create_engine


def _designated_keycloak_user_id(
    client: KeycloakAdminClient,
    *,
    username: str,
    external_group: str,
) -> str:
    snapshot = client.snapshot()
    users = [
        row
        for row in snapshot.users
        if str(row.get("username") or "").casefold() == username.casefold()
    ]
    if len(users) != 1:
        raise BootstrapFailure("directory_admin_identity_invalid")
    user = users[0]
    user_id = str(user.get("id") or "")
    if not user_id or not user.get("federationLink") or not bool(user.get("enabled", False)):
        raise BootstrapFailure("directory_admin_not_active_federated_user")
    matching_group_ids = {
        str(group.get("id") or "")
        for group in snapshot.groups
        if str(group.get("name") or "").casefold() == external_group.casefold()
        or str(group.get("path") or "").rstrip("/").casefold().endswith(
            f"/{external_group}".casefold()
        )
    }
    if not matching_group_ids or not matching_group_ids.intersection(
        snapshot.user_group_ids.get(user_id, frozenset())
    ):
        raise BootstrapFailure("directory_admin_group_membership_missing")
    return user_id


def reconcile_directory_role_mapping(
    settings: DeploymentBootstrapSettings,
) -> dict[str, object]:
    username = settings.deployment_finalization_admin_username.strip()
    group_name = settings.deployment_finalization_admin_group.strip()
    role_name = "system-admin"
    if not username or not group_name:
        raise BootstrapFailure("directory_reconcile_config_missing")
    client = KeycloakAdminClient(
        base_url=settings.keycloak_admin_endpoint,
        realm=_realm_name(settings),
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
    )
    keycloak_user_id = _designated_keycloak_user_id(
        client,
        username=username,
        external_group=group_name,
    )
    client.verify_ldap_group_mapper_path(settings.keycloak_ldap_group_path)
    _reconcile_identity_database(settings, client=client)

    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        with Session(engine) as session:
            acquire_identity_membership_lock(session)
            groups = session.scalars(
                select(ExternalGroup).where(
                    ExternalGroup.group_name == group_name,
                    ExternalGroup.identity_origin == "ldap",
                    ExternalGroup.is_active.is_(True),
                )
            ).all()
            roles = session.scalars(
                select(Role).where(
                    Role.name == role_name,
                    Role.is_active.is_(True),
                    Role.deleted_at.is_(None),
                )
            ).all()
            if len(groups) != 1 or len(roles) != 1:
                raise BootstrapFailure("directory_group_or_role_ambiguous")
            group, role = groups[0], roles[0]
            conflicting = session.scalars(
                select(ExternalGroupRoleMapping).where(
                    or_(
                        ExternalGroupRoleMapping.external_group_id == group.id,
                        ExternalGroupRoleMapping.role_id == role.id,
                    )
                )
            ).all()
            if conflicting and any(
                row.external_group_id != group.id or row.role_id != role.id
                for row in conflicting
            ):
                raise BootstrapFailure("directory_role_mapping_conflict")
            created = not conflicting
            if created:
                session.add(
                    ExternalGroupRoleMapping(
                        external_group_id=group.id,
                        role_id=role.id,
                        created_by=None,
                        created_at=datetime.now(UTC),
                    )
                )
                role.lock_version += 1
                session.flush()
            reconcile_external_role_memberships(
                session,
                role_ids=(role.id,),
                now=datetime.now(UTC),
            )
            admin = session.scalar(
                select(User).where(
                    User.keycloak_user_id == keycloak_user_id,
                    User.auth_source == "ldap",
                    User.is_active.is_(True),
                )
            )
            if admin is None:
                raise BootstrapFailure("directory_admin_database_identity_missing")
            membership = session.scalar(
                select(RoleUser).where(
                    RoleUser.user_id == admin.id,
                    RoleUser.role_id == role.id,
                    RoleUser.source == "external_sync",
                )
            )
            if membership is None:
                raise BootstrapFailure("directory_admin_role_membership_missing")
            if created:
                add_audit(
                    session,
                    actor_user_id=None,
                    action="deployment.directory.role_mapping",
                    resource_type="external_group",
                    resource_id=group.id,
                    result="success",
                    request_id=None,
                    summary={
                        "provider": "keycloak",
                        "group": group_name,
                        "role": role_name,
                        "designated_admin": username,
                    },
                )
            session.commit()
            return {
                "status": "ready",
                "group": group_name,
                "role": role_name,
                "designated_admin": username,
                "membership_source": "external_sync",
                "mapping_created": created,
            }
    finally:
        engine.dispose()


def main() -> int:
    try:
        print(
            json.dumps(
                reconcile_directory_role_mapping(DeploymentBootstrapSettings()),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except BootstrapFailure as exc:
        print(json.dumps({"status": "failed", "code": exc.code}, sort_keys=True), file=sys.stderr)
        return 1
    except Exception:
        print(
            json.dumps(
                {"status": "failed", "code": "directory_reconcile_failed"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
