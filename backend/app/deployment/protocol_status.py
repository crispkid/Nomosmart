"""Read-only protocol configuration and normal-administrator onboarding evidence."""
from datetime import UTC, datetime
from sqlalchemy import select
from app.core.errors import AppError
from app.db.models import AuditLog, AuthSession, IdentitySyncRun, Role, RoleUser, User
from app.db.session import get_session_factory
from app.security.auth_configuration import configuration, current_setting, read_secret


def configuration_status(settings) -> str:
    with get_session_factory()() as session:
        current = current_setting(session)
        cfg = configuration(current)
        if not read_secret(session, settings, current, "ldap_bind_password"):
            raise AppError("directory_credential_required", "Directory credential is required", status_code=503)
        if cfg.auth_mode == "oidc" and cfg.oidc.client_auth_method != "none" and not read_secret(session, settings, current, "oidc_client_secret"):
            raise AppError("oidc_credential_required", "OIDC credential is required", status_code=503)
        return cfg.auth_mode


def normal_admin_evidence(session) -> dict:
    current = current_setting(session)
    cfg = configuration(current)
    run = session.scalar(select(IdentitySyncRun).where(IdentitySyncRun.status == "succeeded", IdentitySyncRun.source == cfg.directory.schema_type).order_by(IdentitySyncRun.completed_at.desc()))
    auth = session.scalar(select(AuthSession).join(User, User.id == AuthSession.user_id).join(RoleUser, RoleUser.user_id == User.id).join(Role, Role.id == RoleUser.role_id).where(AuthSession.login_method == cfg.auth_mode, AuthSession.config_revision == (current.session_revision or current.revision), AuthSession.revoked_at.is_(None), User.is_active.is_(True), User.locally_disabled.is_(False), User.directory_enabled.is_(True), User.directory_source_id == cfg.directory.source_id, Role.name == "system-admin", Role.is_active.is_(True), Role.deleted_at.is_(None), RoleUser.source == "external_sync").order_by(AuthSession.authenticated_at.desc()))
    if not run or not auth:
        raise AppError("normal_admin_login_required", "A synchronized normal administrator must sign in before finalization", status_code=503)
    from app.security.session_auth import session_expiration
    if datetime.now(UTC) >= session_expiration(auth, 1800):
        raise AppError("normal_admin_login_required", "Normal administrator sign-in has expired", status_code=503)
    if cfg.auth_mode == "oidc" and not session.scalar(select(AuditLog.id).where(AuditLog.actor_user_id == auth.user_id, AuditLog.action == "auth.settings.unlock", AuditLog.result == "success", AuditLog.created_at >= auth.authenticated_at)):
        raise AppError("normal_admin_reauthentication_required", "Normal OIDC administrator must verify fresh authentication before finalization", status_code=503)
    return {"status": "ready", "mode": cfg.auth_mode, "admin_user_id": str(auth.user_id), "sync_run_id": str(run.id)}
