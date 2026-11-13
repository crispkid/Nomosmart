"""Deployment-only protocol initialization, explicit migration and recovery."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import secrets
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import AuthConnectionSecret, AuthEmergencyAccess, AuthLoginFlow, AuthSession, ExternalGroup, ExternalGroupRoleMapping, IdentitySetting, IdentitySyncRun, IdentityUnlockGrant, Role, RoleUser, SystemParameter, User
from app.db.session import get_session_factory
from app.integrations.ldap_directory import LdapDirectory
from app.security.auth_configuration import ProtocolConfiguration, configuration, current_setting, read_secret, seal, stage_configuration, store_secret, unseal
from app.services.audit import add_audit
from app.services.auth_alerts import emergency_alert
from app.services.directory_sync import reconcile_directory


def initialize(session, settings, cfg: ProtocolConfiguration, credentials: dict[str, str], admin_group_id: str, *, migration_bindings: dict | None = None):
    if session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True), IdentitySetting.configuration["auth_contract_revision"].as_integer() == 2)):
        raise AppError("auth_already_initialized", "Protocol authentication is already initialized", status_code=409)
    staged = stage_configuration(session, settings, cfg, credentials, None)
    directory = LdapDirectory(settings, cfg.directory, read_secret(session, settings, staged, "ldap_bind_password"))
    snapshot = directory.snapshot("people_and_groups")
    if cfg.auth_mode == "oidc":
        from app.security.oidc_protocol import metadata_for_settings
        metadata_for_settings(settings, staged)
    if not snapshot.people or admin_group_id not in {g.object_id for g in snapshot.groups}:
        raise AppError("bootstrap_directory_admin_missing", "The selected directory administrator group was not found", status_code=422)
    for binding in (migration_bindings or {}).get("users", []):
        user = session.get(User, UUID(binding["user_id"]))
        identifier = str(UUID(binding["directory_object_id"].strip("{}")))
        if user is None or identifier not in {p.object_id for p in snapshot.people} or user.directory_object_id and user.directory_object_id != identifier:
            raise AppError("directory_migration_invalid", "A legacy user binding could not be verified", status_code=422)
        user.directory_source_id, user.directory_object_id = cfg.directory.source_id, identifier
    for binding in (migration_bindings or {}).get("groups", []):
        group = session.get(ExternalGroup, UUID(binding["group_id"]))
        identifier = str(UUID(binding["directory_object_id"].strip("{}")))
        if group is None or identifier not in {g.object_id for g in snapshot.groups}:
            raise AppError("directory_migration_invalid", "A legacy group binding could not be verified", status_code=422)
        group.directory_source_id, group.external_group_id = cfg.directory.source_id, identifier
        group.source = group.identity_origin = cfg.directory.schema_type
    session.flush()
    run = IdentitySyncRun(id=uuid4(), source=cfg.directory.schema_type, configuration_revision=staged.revision, trigger_type="bootstrap", status="running", phase="reconciliation", requested_scope="people_and_groups", queued_at=datetime.now(UTC), started_at=datetime.now(UTC), users_created=0, users_updated=0, users_disabled=0, groups_created=0, groups_updated=0, role_memberships_updated=0, attempt=1)
    session.add(run)
    session.flush()
    reconcile_directory(session, run, snapshot)
    role = session.scalar(select(Role).where(Role.name == "system-admin", Role.is_active.is_(True), Role.deleted_at.is_(None)))
    group = session.scalar(select(ExternalGroup).where(ExternalGroup.directory_source_id == cfg.directory.source_id, ExternalGroup.external_group_id == admin_group_id))
    existing = session.scalar(select(ExternalGroupRoleMapping).where(ExternalGroupRoleMapping.role_id == role.id)) if role else None
    if role is None or existing and existing.external_group_id != group.id:
        raise AppError("bootstrap_admin_mapping_conflict", "Administrator group mapping requires operator review", status_code=409)
    if existing is None:
        session.add(ExternalGroupRoleMapping(id=uuid4(), external_group_id=group.id, role_id=role.id, created_at=datetime.now(UTC)))
        role.lock_version += 1
    session.flush()
    from app.services.role_memberships import reconcile_external_role_memberships
    run.role_memberships_updated = reconcile_external_role_memberships(session)
    session.flush()
    if not session.scalar(select(RoleUser.user_id).where(RoleUser.role_id == role.id, RoleUser.source == "external_sync")):
        raise AppError("bootstrap_directory_admin_missing", "The selected administrator group has no synchronized people", status_code=422)
    run.status, run.phase, run.completed_at = "succeeded", "completed", datetime.now(UTC)
    old = session.scalars(select(IdentitySetting).where(IdentitySetting.is_current.is_(True))).all()
    for row in old:
        row.is_current, row.is_last_known_good = False, True
    session.flush()
    staged.is_current, staged.state, staged.validated_at, staged.session_revision = True, "validated_active_locked", datetime.now(UTC), staged.revision
    add_audit(session, actor_user_id=None, action="deployment.auth.initialize", resource_type="identity_settings", resource_id=staged.id, result="success", request_id=None, summary={"source_id": str(cfg.directory.source_id), "revision": staged.revision, "sync_run_id": str(run.id), "onboarding": True})
    return staged


def emergency_enable(session, settings, *, password_file: Path) -> None:
    current_setting(session)
    username = settings.auth_emergency_username
    row = session.scalar(select(AuthEmergencyAccess).where(AuthEmergencyAccess.username == username).with_for_update())
    if row is None:
        user = User(id=uuid4(), keycloak_user_id=None, display_name="Emergency administrator", auth_source="emergency", is_active=True, directory_enabled=True, locally_disabled=False)
        session.add(user);session.flush()
        row = AuthEmergencyAccess(user_id=user.id, username=username)
        session.add(row)
    user = session.get(User, row.user_id)
    role = session.scalar(select(Role).where(Role.name == "system-admin", Role.is_active.is_(True), Role.deleted_at.is_(None)))
    if role is None:
        raise AppError("bootstrap_admin_role_missing", "Protected administrator role is unavailable", status_code=503)
    user.is_active, user.locally_disabled, user.directory_enabled = True, False, True
    link = session.scalar(select(RoleUser).where(RoleUser.role_id == role.id, RoleUser.user_id == user.id, RoleUser.source == "break_glass"))
    if link is None:
        session.add(RoleUser(role_id=role.id, user_id=user.id, source="break_glass"))
    password = secrets.token_urlsafe(40)
    row.password_verifier = PasswordHasher().hash(password)
    row.activated_at = datetime.now(UTC)
    row.active_until = row.activated_at + timedelta(seconds=settings.auth_emergency_ttl_seconds)
    session.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=row.activated_at))
    fd = os.open(password_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(password + "\n")
    session.flush()
    emergency_alert(session, action="enabled", actor_user_id=user.id)
    add_audit(session, actor_user_id=None, action="deployment.emergency.enable", resource_type="user", resource_id=user.id, result="success", request_id=None, summary={"expires_at": row.active_until.isoformat(), "alert_required": True})


def emergency_disable(session) -> int:
    now = datetime.now(UTC)
    rows = session.scalars(select(AuthEmergencyAccess).with_for_update()).all()
    for row in rows:
        row.password_verifier, row.active_until = None, None
        user = session.get(User, row.user_id)
        user.is_active = False
        session.execute(update(AuthSession).where(AuthSession.user_id == row.user_id, AuthSession.revoked_at.is_(None)).values(revoked_at=now))
        session.execute(update(IdentityUnlockGrant).where(IdentityUnlockGrant.user_id == row.user_id, IdentityUnlockGrant.revoked_at.is_(None)).values(revoked_at=now))
        emergency_alert(session, action="disabled", actor_user_id=row.user_id)
        add_audit(session, actor_user_id=None, action="deployment.emergency.disable", resource_type="user", resource_id=row.user_id, result="success", request_id=None, summary={"credential_removed": True})
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("initialize")
    init.add_argument("--configuration", type=Path, required=True)
    init.add_argument("--bind-password-file", type=Path, required=True)
    init.add_argument("--oidc-secret-file", type=Path)
    init.add_argument("--admin-group-id", required=True)
    init.add_argument("--migration-bindings", type=Path)
    enable = sub.add_parser("emergency-enable");enable.add_argument("--password-file", type=Path, required=True)
    sub.add_parser("emergency-disable")
    sub.add_parser("rotate-keys")
    sub.add_parser("finalize")
    sub.add_parser("restore-last-known-good")
    args = parser.parse_args()
    settings = get_settings()
    try:
        with get_session_factory().begin() as session:
            if args.action == "initialize":
                cfg = ProtocolConfiguration.model_validate_json(args.configuration.read_text())
                credentials = {"ldap_bind_password": args.bind_password_file.read_text().rstrip("\r\n")}
                if args.oidc_secret_file:
                    credentials["oidc_client_secret"] = args.oidc_secret_file.read_text().rstrip("\r\n")
                mapping = json.loads(args.migration_bindings.read_text()) if args.migration_bindings else None
                result = initialize(session, settings, cfg, credentials, str(UUID(args.admin_group_id)), migration_bindings=mapping)
                print(json.dumps({"state": result.state, "revision": result.revision, "onboarding": "requires_normal_admin_login"}))
            elif args.action == "emergency-enable":
                emergency_enable(session, settings, password_file=args.password_file)
                print(json.dumps({"state": "enabled", "ttl_seconds": settings.auth_emergency_ttl_seconds, "credential_printed": False}))
            elif args.action == "emergency-disable":
                print(json.dumps({"state": "disabled", "identities": emergency_disable(session)}))
            elif args.action == "finalize":
                from app.deployment.protocol_status import normal_admin_evidence
                result = normal_admin_evidence(session)
                emergency_disable(session)
                add_audit(session, actor_user_id=UUID(result["admin_user_id"]), action="auth.onboarding.completed", resource_type="identity_settings", resource_id=current_setting(session).id, result="success", request_id=None, summary={"mode": result["mode"], "sync_run_id": result["sync_run_id"]})
                print(json.dumps({"status": "ready", "normal_admin_login": "verified", "emergency": "disabled"}))
            elif args.action == "restore-last-known-good":
                current = current_setting(session)
                old = session.scalar(select(IdentitySetting).where(IdentitySetting.is_last_known_good.is_(True)).order_by(IdentitySetting.revision.desc()).with_for_update())
                if old is None:
                    raise AppError("auth_recovery_unavailable", "No verified previous configuration is available", status_code=409)
                for purpose in ("ldap_bind_password", "oidc_client_secret"):
                    read_secret(session, settings, old, purpose)
                cfg = configuration(old)
                LdapDirectory(settings, cfg.directory, read_secret(session, settings, old, "ldap_bind_password")).snapshot("people_and_groups")
                if cfg.auth_mode == "oidc":
                    from app.security.oidc_protocol import metadata_for_settings
                    metadata_for_settings(settings, old)
                current.is_current = False
                session.flush()
                old.is_current, old.is_last_known_good = True, False
                session.execute(update(AuthSession).where(AuthSession.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
                session.execute(update(IdentityUnlockGrant).where(IdentityUnlockGrant.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
                emergency_alert(session, action="restored")
                add_audit(session, actor_user_id=None, action="deployment.auth.restore", resource_type="identity_settings", resource_id=old.id, result="success", request_id=None, summary={"revision": old.revision})
                print(json.dumps({"status": "restored", "revision": old.revision, "sessions_revoked": True}))
            elif args.action == "rotate-keys":
                rows = session.scalars(select(AuthConnectionSecret).with_for_update()).all()
                count = 0
                for row in rows:
                    if row.key_id != settings.auth_encryption_key_id:
                        setting = session.get(IdentitySetting, row.setting_id)
                        value = read_secret(session, settings, setting, row.purpose)
                        store_secret(session, settings, setting, row.purpose, value)
                        count += 1
                flows = session.scalars(select(AuthLoginFlow).where(AuthLoginFlow.key_id != settings.auth_encryption_key_id, AuthLoginFlow.expires_at > datetime.now(UTC)).with_for_update()).all()
                for flow in flows:
                    plaintext = unseal(settings, flow.key_id, flow.verifier_ciphertext, context=f"auth-flow:{flow.id}")
                    flow.key_id, flow.verifier_ciphertext = seal(settings, plaintext, context=f"auth-flow:{flow.id}")
                emergency_alert(session, action="rotated")
                add_audit(session, actor_user_id=None, action="deployment.auth.rotate_keys", resource_type="identity_settings", resource_id=None, result="success", request_id=None, summary={"rotated": count, "active_key_id": settings.auth_encryption_key_id})
                print(json.dumps({"rotated_connection_secrets": count}))
        return 0
    except (AppError, ValueError, OSError) as exc:
        print(json.dumps({"state": "failed", "code": exc.code if isinstance(exc, AppError) else "bootstrap_input_invalid"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
