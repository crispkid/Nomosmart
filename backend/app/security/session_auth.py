"""Server-owned sessions with sliding user activity, never a fixed lifetime."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import secrets
from uuid import UUID, uuid4

from fastapi import Request, Response
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AuthEmergencyAccess, AuthSession, ExternalGroup, ExternalGroupUser, IdentityUnlockGrant, User
from app.security.auth_configuration import current_setting


SESSION_COOKIE = "__Host-nomosmart_session"
FLOW_COOKIE = "__Host-nomosmart_auth_flow"


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def csrf_token(raw_session: str) -> str:
    return hmac.new(raw_session.encode(), b"nomosmart-session-csrf-v2", sha256).hexdigest()


def require_origin(request: Request) -> None:
    expected = request.app.state.settings.frontend_app_origin.rstrip("/")
    if request.headers.get("origin") != expected or request.headers.get("sec-fetch-site") in {"cross-site", "none"}:
        raise AppError("csrf_invalid", "A same-origin request is required", status_code=403)


def require_csrf(request: Request, row: AuthSession) -> None:
    require_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not hmac.compare_digest(digest(supplied), row.csrf_digest):
        raise AppError("csrf_invalid", "Request verification failed", status_code=403)


def session_expiration(row: AuthSession, idle_seconds: int) -> datetime:
    expires = row.last_activity_at + timedelta(seconds=idle_seconds)
    return min(expires, row.emergency_expires_at) if row.emergency_expires_at else expires


def require_session(request: Request, session: Session, *, lock: bool = False) -> AuthSession:
    raw = request.cookies.get(SESSION_COOKIE, "")
    row = validate_session_secret(request.app.state.settings, session, raw, lock=lock)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, row)
    request.state.auth_session = row
    return row


def validate_session_secret(settings, session: Session, raw: str, *, lock: bool = False) -> AuthSession:
    """Shared server-side session checks for HTTP and private local maintenance."""
    if not isinstance(raw, str) or not raw or len(raw) > 200:
        raise AppError("authentication_required", "Sign-in is required", status_code=401)
    statement = select(AuthSession).where(AuthSession.secret_digest == digest(raw))
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(statement)
    return validate_session_row(settings, session, row)


def validate_session_row(settings, session: Session, row: AuthSession | None) -> AuthSession:
    """Apply the same session state checks after a trusted ID or secret lookup."""
    now = datetime.now(UTC)
    if row is None or row.revoked_at or now >= session_expiration(row, settings.auth_session_idle_seconds):
        raise AppError("session_expired", "Sign-in has expired", status_code=401)
    current = current_setting(session)
    # Scheduling-only revisions do not change the authenticated security contract.
    if row.config_revision != (current.session_revision or current.revision):
        raise AppError("session_revoked", "Sign-in has been revoked", status_code=401)
    user = session.get(User, row.user_id)
    if user is None or not user.is_active or user.locally_disabled or not user.directory_enabled:
        raise AppError("user_disabled", "User account is unavailable", status_code=403)
    if row.login_method == "emergency":
        emergency = session.get(AuthEmergencyAccess, row.user_id)
        if emergency is None or emergency.active_until is None or now >= emergency.active_until:
            raise AppError("session_revoked", "Emergency access has expired", status_code=401)
    return row


def issue_session(request: Request, response: Response, session: Session, user: User, *, method: str, emergency_expires_at: datetime | None = None, expected_setting_id: UUID | None = None) -> AuthSession:
    now = datetime.now(UTC)
    raw = secrets.token_urlsafe(48)
    session.execute(text("SELECT pg_advisory_xact_lock(4873662102)"))
    current = current_setting(session)
    if expected_setting_id is not None and current.id != expected_setting_id:
        raise AppError("session_revoked", "Authentication configuration has changed", status_code=401)
    user = session.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if user is None or not user.is_active or user.locally_disabled or not user.directory_enabled:
        raise AppError("user_disabled", "User account is unavailable", status_code=403)
    row = AuthSession(id=uuid4(), secret_digest=digest(raw), csrf_digest=digest(csrf_token(raw)), user_id=user.id, login_method=method, config_revision=current.session_revision or current.revision, authenticated_at=now, last_activity_at=now, emergency_expires_at=emergency_expires_at)
    session.add(row)
    # A browser-session cookie has no independent absolute age. The server is authoritative.
    response.set_cookie(SESSION_COOKIE, raw, secure=True, httponly=True, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return row


def revoke_session(session: Session, row: AuthSession) -> None:
    now = datetime.now(UTC)
    row.revoked_at = now
    session.execute(update(IdentityUnlockGrant).where(IdentityUnlockGrant.session_id == str(row.id), IdentityUnlockGrant.revoked_at.is_(None)).values(revoked_at=now))


def principal_from_session(request: Request, session: Session):
    row = require_session(request, session)
    return principal_for_session(request.app.state.settings, session, row)


def principal_for_session(settings, session: Session, row: AuthSession):
    from app.security.auth import IdentityPrincipal

    user = session.get(User, row.user_id)
    groups = tuple(session.scalars(select(ExternalGroup.external_group_id).join(ExternalGroupUser, ExternalGroupUser.external_group_id == ExternalGroup.id).where(ExternalGroupUser.user_id == row.user_id, ExternalGroup.is_active.is_(True))))
    return IdentityPrincipal(subject=str(row.user_id), employee_id=user.employee_id, email=user.email, display_name=user.display_name, groups=groups, session_id=str(row.id), auth_time=int(row.authenticated_at.timestamp()), issuer="nomosmart-session", audience="nomosmart", issued_at=row.authenticated_at, expires_at=session_expiration(row, settings.auth_session_idle_seconds), user_id=row.user_id, login_method=row.login_method)
