from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AuthAttemptWindow, AuthEmergencyAccess, AuthSession, ExternalGroup, ExternalGroupUser, IdentitySetting, User
from app.db.session import get_db
from app.integrations.ldap_directory import LdapDirectory
from app.security.auth_configuration import configuration, current_setting, read_secret
from app.security.context import IdentityContext, get_identity_context
from app.security.oidc_protocol import consume_flow, discard_failed_flow, resolve_oidc_user, safe_return_path, start_flow
from app.security.session_auth import SESSION_COOKIE, FLOW_COOKIE, csrf_token, digest, issue_session, require_origin, require_session, revoke_session, session_expiration
from app.services.audit import add_audit
from app.services.auth_alerts import emergency_alert


router = APIRouter(prefix="/auth", tags=["auth"])
LOGIN_BROWSER_COOKIE = "__Host-nomosmart_login_browser"


class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=4096)


class OidcStart(BaseModel):
    return_to: str = Field(default="/", max_length=2048)


def login_browser(request: Request, response: Response) -> str:
    marker = request.cookies.get(LOGIN_BROWSER_COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,64}", marker):
        marker = secrets.token_urlsafe(32)
        response.set_cookie(LOGIN_BROWSER_COOKIE, marker, max_age=3600, secure=True, httponly=True, samesite="lax", path="/")
    return marker


def throttle(request: Request, session: Session, username: str, *, purpose: str = "login") -> None:
    now = datetime.now(UTC)
    address = request.client.host if request.client else ""
    settings = request.app.state.settings
    rules = [(purpose + "|" + address + "|" + username.casefold(), settings.auth_login_attempts_per_minute), ("auth-ingress|" + address, settings.auth_ingress_attempts_per_minute)]
    exceeded = False
    for identity, limit in rules:
        key = digest(identity)
        statement = insert(AuthAttemptWindow).values(key_digest=key, started_at=now, attempts=1)
        stale = AuthAttemptWindow.started_at <= now - timedelta(minutes=1)
        statement = statement.on_conflict_do_update(index_elements=[AuthAttemptWindow.key_digest], set_={"attempts": case((stale, 1), else_=AuthAttemptWindow.attempts + 1), "started_at": case((stale, now), else_=AuthAttemptWindow.started_at)}).returning(AuthAttemptWindow.attempts)
        exceeded = session.scalar(statement) > limit or exceeded
    session.commit()
    if exceeded:
        raise AppError("auth_rate_limited", "Too many authentication attempts", status_code=429)


@router.get("/config")
def public_config(request: Request, response: Response, session: Session = Depends(get_db)) -> dict:
    row = current_setting(session)
    cfg = configuration(row)
    login_browser(request, response)
    response.headers["Cache-Control"] = "no-store"
    return {"mode": cfg.auth_mode, "display_name": cfg.display_name, "idle_timeout_seconds": 1800, "absolute_timeout_seconds": None, "auth_contract_revision": 2, "capabilities": {"server_session": True, "refresh": False, "silent_sso": False, "upstream_logout": False}}


@router.get("/session")
def session_state(request: Request, response: Response, session: Session = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    raw = request.cookies.get(SESSION_COOKIE, "")
    row = session.scalar(select(AuthSession).where(AuthSession.secret_digest == digest(raw))) if raw else None
    valid = False
    if row:
        try:
            require_session(request, session)
            valid = True
        except AppError as exc:
            if exc.code not in {"session_expired", "session_revoked", "user_disabled"}:
                raise
    # No account/profile information is returned here. The token also permits an
    # expired/disabled browser session to execute its own CSRF-protected logout.
    return {"authenticated": valid, "csrf_token": csrf_token(raw) if row else None, "idle_expires_at": session_expiration(row, request.app.state.settings.auth_session_idle_seconds).isoformat() if row else None, "mode": row.login_method if valid else None}


@router.get("/oidc/config")
def legacy_oidc_config(response: Response, session: Session = Depends(get_db)) -> dict:
    cfg = configuration(current_setting(session))
    if cfg.auth_mode != "oidc":
        raise AppError("auth_mode_unavailable", "OIDC sign-in is unavailable", status_code=409)
    response.headers["Cache-Control"] = "no-store"
    return {"issuer": cfg.oidc.issuer, "client_id": cfg.oidc.client_id, "authorization_flow": "authorization_code_pkce", "server_session": True}


@router.post("/login")
def ldap_login(payload: LoginPayload, request: Request, response: Response, session: Session = Depends(get_db)) -> dict:
    require_origin(request)
    setting = current_setting(session)
    cfg = configuration(setting)
    if cfg.auth_mode != "ldap":
        raise AppError("auth_mode_unavailable", "LDAP sign-in is unavailable", status_code=409)
    throttle(request, session, payload.username)
    try:
        directory = LdapDirectory(request.app.state.settings, cfg.directory, read_secret(session, request.app.state.settings, setting, "ldap_bind_password"))
        person = directory.authenticate(payload.username, payload.password.get_secret_value())
        user = session.scalar(select(User).where(User.directory_source_id == cfg.directory.source_id, User.directory_object_id == person.object_id))
        if user is None:
            raise AppError("user_not_synchronized", "User has not been synchronized", status_code=403)
        row = issue_session(request, response, session, user, method="ldap", expected_setting_id=setting.id)
        add_audit(session, actor_user_id=user.id, action="auth.login.success", resource_type="auth_session", resource_id=row.id, result="success", request_id=request.state.request_id, summary={"method": "ldap"})
        session.commit()
        return {"authenticated": True, "idle_expires_at": session_expiration(row, request.app.state.settings.auth_session_idle_seconds).isoformat()}
    except AppError as exc:
        session.rollback()
        add_audit(session, actor_user_id=None, action="auth.login.failed", resource_type="auth_session", resource_id=None, result="denied", request_id=request.state.request_id, summary={"method": "ldap", "code": exc.code, "identity_fingerprint": digest(payload.username.casefold())})
        session.commit()
        raise


@router.post("/oidc/start")
def oidc_start(payload: OidcStart, request: Request, response: Response, session: Session = Depends(get_db)) -> dict:
    require_origin(request)
    setting = current_setting(session)
    if configuration(setting).auth_mode != "oidc":
        raise AppError("auth_mode_unavailable", "OIDC sign-in is unavailable", status_code=409)
    throttle(request, session, login_browser(request, response), purpose="oidc_start")
    url = start_flow(request, response, session, setting, return_path=payload.return_to)
    session.commit()
    return {"authorization_url": url}


@router.get("/oidc/callback")
def oidc_callback(request: Request, state: str = "", code: str = "", error: str = "", session: Session = Depends(get_db)) -> Response:
    origin = request.app.state.settings.frontend_app_origin.rstrip("/")
    cookie_name = FLOW_COOKIE + "_" + digest(state)[:24]
    try:
        if error:
            discard_failed_flow(request, session, state)
            raise AppError("oidc_authentication_failed", "OIDC sign-in could not be verified", status_code=401)
        flow, setting, claims = consume_flow(request, session, state=state, code=code)
        user = resolve_oidc_user(session, setting, claims, persist=flow.purpose == "login")
        if flow.purpose != "login":
            from app.api.routes.protocol_identity import complete_oidc_reauthentication
            response = complete_oidc_reauthentication(request, session, flow, setting, user, claims)
        else:
            if not setting.is_current:
                raise AppError("session_revoked", "Authentication configuration has changed", status_code=401)
            response = RedirectResponse(origin + safe_return_path(flow.return_path), status_code=303)
            row = issue_session(request, response, session, user, method="oidc", expected_setting_id=setting.id)
            add_audit(session, actor_user_id=user.id, action="auth.login.success", resource_type="auth_session", resource_id=row.id, result="success", request_id=request.state.request_id, summary={"method": "oidc"})
        session.commit()
    except AppError as exc:
        session.rollback()
        add_audit(session, actor_user_id=None, action="auth.oidc.failed", resource_type="auth_flow", resource_id=None, result="denied", request_id=request.state.request_id, summary={"code": exc.code, "stage": getattr(exc, "auth_stage", None), "cause_type": type(exc.__cause__).__name__ if exc.__cause__ else None})
        session.commit()
        response = RedirectResponse(origin + "/login", status_code=303)
        response.set_cookie("nomosmart_login_notice", "account_unavailable" if exc.status_code == 403 else "oidc_error", max_age=60, secure=True, httponly=True, samesite="lax", path="/")
    response.delete_cookie(cookie_name, path="/", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/me")
def current_user(request: Request, response: Response, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> dict:
    user = session.get(User, context.user_id)
    row = request.state.auth_session
    response.headers["Cache-Control"] = "no-store"
    return {"user_id": str(user.id), "subject": str(user.id), "employee_id": user.employee_id, "email": user.email, "given_name": user.given_name, "family_name": user.family_name, "display_name": user.display_name, "groups": list(context.principal.groups), "permissions": [{"module_name": grant.module_name, "function_name": grant.function_name, "can_view": grant.can_view, "can_create": grant.can_create, "can_edit": grant.can_edit, "can_delete": grant.can_delete, "can_execute": grant.can_execute} for grant in context.grants], "visible_project_ids": [str(value) for value in sorted(context.visible_project_ids, key=str)], "mode": row.login_method, "csrf_token": csrf_token(request.cookies[SESSION_COOKIE]), "idle_expires_at": session_expiration(row, request.app.state.settings.auth_session_idle_seconds).isoformat()}


@router.post("/activity")
def activity(request: Request, response: Response, session: Session = Depends(get_db)) -> dict:
    row = require_session(request, session, lock=True)
    row.last_activity_at = datetime.now(UTC)
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"last_activity_at": row.last_activity_at.isoformat(), "idle_expires_at": session_expiration(row, request.app.state.settings.auth_session_idle_seconds).isoformat()}


@router.post("/logout", status_code=204)
def logout(request: Request, session: Session = Depends(get_db)) -> Response:
    from app.security.session_auth import require_csrf
    require_origin(request)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    raw = request.cookies.get(SESSION_COOKIE, "")
    row = session.scalar(select(AuthSession).where(AuthSession.secret_digest == digest(raw)).with_for_update()) if raw else None
    if row:
        require_csrf(request, row)
        revoke_session(session, row)
        add_audit(session, actor_user_id=row.user_id, action="auth.logout", resource_type="auth_session", resource_id=row.id, result="success", request_id=request.state.request_id, summary={"method": row.login_method})
        session.commit()
    response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax", path="/")
    return response


@router.post("/emergency/login")
def emergency_login(payload: LoginPayload, request: Request, response: Response, session: Session = Depends(get_db)) -> dict:
    require_origin(request)
    throttle(request, session, payload.username, purpose="emergency")
    row = session.scalar(select(AuthEmergencyAccess).where(AuthEmergencyAccess.username == payload.username))
    now = datetime.now(UTC)
    try:
        if row is None or row.active_until is None or now >= row.active_until or not row.password_verifier:
            raise ValueError("disabled")
        PasswordHasher().verify(row.password_verifier, payload.password.get_secret_value())
    except (ValueError, VerificationError, InvalidHashError) as exc:
        raise AppError("invalid_credentials", "Emergency sign-in could not be verified", status_code=401) from exc
    user = session.get(User, row.user_id)
    auth = issue_session(request, response, session, user, method="emergency", emergency_expires_at=row.active_until)
    emergency_alert(session, action="login", actor_user_id=user.id)
    add_audit(session, actor_user_id=user.id, action="auth.emergency.login", resource_type="auth_session", resource_id=auth.id, result="success", request_id=request.state.request_id, summary={"activation_expires_at": row.active_until.isoformat(), "alert_required": True})
    session.commit()
    return {"authenticated": True, "idle_expires_at": row.active_until.isoformat()}
