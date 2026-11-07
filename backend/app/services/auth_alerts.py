"""Immediate internal security notifications, independent of directory availability."""
from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import select
from app.db.models import Notification, Role, RoleUser, User


def emergency_alert(session, *, action: str, actor_user_id=None) -> int:
    recipients = set(session.scalars(select(RoleUser.user_id).join(Role, Role.id == RoleUser.role_id).join(User, User.id == RoleUser.user_id).where(Role.name == "system-admin", Role.is_active.is_(True), Role.deleted_at.is_(None), User.is_active.is_(True))))
    for recipient in recipients:
        session.add(Notification(id=uuid4(), recipient_user_id=recipient, notification_type="auth.emergency." + action, severity="critical", title="authEmergencyAlertTitle", message="authEmergencyAlert_" + action, action_type="configuration", action_payload={"tab": "identity", "actor_user_id": str(actor_user_id) if actor_user_id else None}, business_key="auth-emergency:" + str(uuid4()), is_read=False, created_at=datetime.now(UTC)))
    return len(recipients)


def directory_failure_alert(session, *, run_id, error_code: str) -> int:
    recipients = set(session.scalars(select(RoleUser.user_id).join(Role, Role.id == RoleUser.role_id).join(User, User.id == RoleUser.user_id).where(Role.name == "system-admin", Role.is_active.is_(True), Role.deleted_at.is_(None), User.is_active.is_(True))))
    for recipient in recipients:
        session.add(Notification(id=uuid4(), recipient_user_id=recipient, notification_type="auth.directory.sync_failed", severity="error", title="authDirectorySyncFailedTitle", message="authDirectorySyncFailedHelp", action_type="configuration", action_payload={"tab": "identity", "run_id": str(run_id), "error_code": error_code}, business_key="directory-sync:" + str(run_id), is_read=False, created_at=datetime.now(UTC)))
    return len(recipients)
