from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import json
import secrets
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AuthCandidateEvidence, AuthConnectionSecret, AuthEmergencyAccess, AuthLoginFlow, AuthSession, AuthenticationIdentity, IdentitySetting, IdentitySyncRun, IdentityUnlockGrant, User
from app.db.session import get_db
from app.integrations.ldap_directory import LdapDirectory
from app.security.auth_configuration import ProtocolConfiguration, configuration, current_setting, read_secret, seal, stage_configuration, unseal
from app.security.context import IdentityContext, get_identity_context, resolve_identity_context
from app.security.oidc_protocol import metadata, oauth_client, start_flow
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.security.session_auth import digest, require_session
from app.services.audit import add_audit


router = APIRouter(prefix="/system/identity-settings", tags=["identity-settings"])
COMPLETION_COOKIE = "__Host-nomosmart_reauth"
SCOPE = "identity-settings"


def editor(context: IdentityContext) -> None:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)


def unlock(session: Session, context: IdentityContext) -> IdentityUnlockGrant:
    editor(context)
    row = session.scalar(select(IdentityUnlockGrant).where(IdentityUnlockGrant.user_id == context.user_id, IdentityUnlockGrant.session_id == context.principal.session_id, IdentityUnlockGrant.scope == SCOPE, IdentityUnlockGrant.revoked_at.is_(None), IdentityUnlockGrant.expires_at > datetime.now(UTC)).with_for_update())
    if row is None:
        raise AppError("identity_settings_locked", "Verify your identity before changing authentication settings", status_code=423)
    return row


def grant_unlock(request: Request, session: Session, user_id: UUID, auth: AuthSession, *, authenticated_at: datetime) -> IdentityUnlockGrant:
    from app.security.session_auth import principal_from_session
    principal = principal_from_session(request, session)
    latest = resolve_identity_context(session, principal)
    editor(latest)
    if latest.user_id != user_id or auth.id != UUID(principal.session_id):
        raise AppError("fresh_authentication_failed", "Authentication identity did not match", status_code=401)
    now = datetime.now(UTC)
    session.execute(update(IdentityUnlockGrant).where(IdentityUnlockGrant.user_id == user_id, IdentityUnlockGrant.session_id == str(auth.id), IdentityUnlockGrant.scope == SCOPE, IdentityUnlockGrant.revoked_at.is_(None)).values(revoked_at=now))
    row = IdentityUnlockGrant(id=uuid4(), user_id=user_id, session_id=str(auth.id), scope=SCOPE, auth_time=authenticated_at, expires_at=now + timedelta(minutes=10), created_at=now)
    session.add(row)
    add_audit(session, actor_user_id=user_id, action="auth.settings.unlock", resource_type="identity_settings", resource_id=None, result="success", request_id=request.state.request_id, summary={"method": auth.login_method})
    if auth.login_method == "emergency":
        from app.services.auth_alerts import emergency_alert
        emergency_alert(session, action="reauth", actor_user_id=user_id)
    return row


def candidate_digest(request: Request, session: Session, row: IdentitySetting) -> str:
    encrypted = session.scalars(select(AuthConnectionSecret).where(AuthConnectionSecret.setting_id == row.id).order_by(AuthConnectionSecret.purpose)).all()
    material = json.dumps(row.configuration, sort_keys=True, separators=(",", ":")) + "|" + "|".join(f"{secret.purpose}:{secret.key_id}:{secret.envelope}" for secret in encrypted)
    key = hmac.new(request.app.state.settings.auth_encryption_key_bytes, b"auth-candidate-receipt", sha256).digest()
    return hmac.new(key, material.encode(), sha256).hexdigest()


def candidate_evidence(request: Request, session: Session, row: IdentitySetting, auth: AuthSession, user_id: UUID) -> AuthCandidateEvidence:
    proof = AuthCandidateEvidence(id=uuid4(), setting_id=row.id, session_id=auth.id, user_id=user_id, candidate_digest=candidate_digest(request, session, row), expires_at=min(datetime.now(UTC) + timedelta(minutes=5), row.validated_at + timedelta(minutes=5)) if row.validated_at else datetime.now(UTC) + timedelta(minutes=5))
    session.add(proof)
    return proof


def needs_canary(previous: IdentitySetting, candidate: IdentitySetting) -> bool:
    old, new = configuration(previous), configuration(candidate)
    return old.auth_mode != new.auth_mode or new.auth_mode == "oidc" and old.oidc != new.oidc


class FreshAuthentication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str = "current"
    candidate_id: UUID | None = None
    username: str | None = Field(default=None, max_length=255)
    password: SecretStr | None = Field(default=None, max_length=4096)


class SecretOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str = "keep"
    value: SecretStr | None = Field(default=None, max_length=8192)


class CandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration: ProtocolConfiguration
    expected_revision: int = Field(ge=1)
    secrets: dict[str, SecretOperation] = Field(default_factory=dict)


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: UUID
    expected_revision: int = Field(ge=1)


class BindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: UUID
    issuer: str = Field(min_length=1, max_length=2048)
    subject: str = Field(min_length=1, max_length=255)
    user_id: UUID
    directory_object_id: str = Field(min_length=1, max_length=255)
    expected_revision: int = Field(ge=1)


@router.get("")
def get_settings(request: Request, response: Response, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> dict:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    current = current_setting(session)
    try:
        grant = unlock(session, context)
    except AppError:
        grant = None
    last_sync_success_at = session.scalar(select(func.max(IdentitySyncRun.completed_at)).where(IdentitySyncRun.status == "succeeded", IdentitySyncRun.source == configuration(current).directory.schema_type))
    configured = {purpose: True for purpose in session.scalars(select(AuthConnectionSecret.purpose).where(AuthConnectionSecret.setting_id == current.id))}
    response.headers["Cache-Control"] = "no-store"
    return {"state": "temporarily_unlocked" if grant else "validated_active_locked", "configuration": configuration(current).model_dump(mode="json"), "configuration_source": "database", "last_sync_success_at": last_sync_success_at.isoformat() if last_sync_success_at else None, "revision": current.revision, "secret_configured": bool(configured), "secrets": {purpose: {"configured": configured.get(purpose, False)} for purpose in ("ldap_bind_password", "oidc_client_secret")}, "unlock_expires_at": grant.expires_at.isoformat() if grant else None, "editable": grant is not None}


@router.post("/reauth/start")
def begin_reauthentication(payload: FreshAuthentication, request: Request, response: Response, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> dict:
    from app.api.routes.protocol_auth import throttle
    editor(context)
    if payload.purpose not in {"current", "candidate"}:
        raise AppError("validation_error", "Authentication purpose is invalid", status_code=422)
    auth = require_session(request, session)
    current = current_setting(session)
    target = current
    if payload.purpose == "candidate":
        unlock(session, context)
        target = session.get(IdentitySetting, payload.candidate_id) if payload.candidate_id else None
        if target is None or target.created_by != context.user_id or target.state != "validated_candidate_requires_login" or target.validated_at is None or datetime.now(UTC) >= target.validated_at + timedelta(minutes=5):
            raise AppError("identity_candidate_invalid", "Validate the authentication candidate again", status_code=409)
    cfg = configuration(target)
    throttle(request, session, str(context.user_id), purpose="fresh_auth")
    if auth.login_method == "emergency" and payload.purpose == "current":
        emergency = session.get(AuthEmergencyAccess, context.user_id)
        try:
            if not payload.password or not emergency or not emergency.password_verifier or not emergency.active_until or datetime.now(UTC) >= emergency.active_until:
                raise ValueError("disabled")
            PasswordHasher().verify(emergency.password_verifier, payload.password.get_secret_value())
        except (VerificationError, InvalidHashError, ValueError) as exc:
            raise AppError("invalid_credentials", "Fresh authentication failed", status_code=401) from exc
        grant = grant_unlock(request, session, context.user_id, auth, authenticated_at=datetime.now(UTC))
        session.commit()
        return {"unlocked": True, "expires_at": grant.expires_at.isoformat()}
    if cfg.auth_mode == "oidc":
        url = start_flow(request, response, session, target, purpose="candidate" if payload.purpose == "candidate" else "reauth", return_path="/system?tab=identity", initiating_session_id=auth.id, user_id=context.user_id)
        session.commit()
        return {"authorization_url": url}
    if not payload.username or not payload.password:
        raise AppError("credentials_required", "Enter your directory account and password", status_code=422)
    directory = LdapDirectory(request.app.state.settings, cfg.directory, read_secret(session, request.app.state.settings, target, "ldap_bind_password"))
    person = directory.authenticate(payload.username, payload.password.get_secret_value())
    user = session.scalar(select(User).where(User.directory_source_id == cfg.directory.source_id, User.directory_object_id == person.object_id))
    if user is None or user.id != context.user_id:
        raise AppError("fresh_authentication_failed", "Fresh authentication identity did not match", status_code=401)
    if payload.purpose == "candidate":
        candidate_evidence(request, session, target, auth, context.user_id)
        target.state = "validated_candidate"
        session.commit()
        return {"candidate_verified": True, "candidate_id": str(target.id)}
    grant = grant_unlock(request, session, context.user_id, auth, authenticated_at=datetime.now(UTC))
    session.commit()
    return {"unlocked": True, "expires_at": grant.expires_at.isoformat()}


def complete_oidc_reauthentication(request: Request, session: Session, flow: AuthLoginFlow, setting: IdentitySetting, user: User, claims: dict) -> Response:
    auth = require_session(request, session)
    if flow.initiating_session_id != auth.id or flow.user_id != auth.user_id or user.id != auth.user_id:
        raise AppError("fresh_authentication_failed", "Fresh authentication identity did not match", status_code=401)
    origin = request.app.state.settings.frontend_app_origin.rstrip("/")
    response = RedirectResponse(origin + "/system?tab=identity&reauth=success&reauth_purpose=" + flow.purpose, status_code=303)
    if flow.purpose == "candidate":
        from app.security.session_auth import principal_from_session
        context = resolve_identity_context(session, principal_from_session(request, session))
        unlock(session, context)
        if setting.created_by != user.id or setting.state != "validated_candidate_requires_login" or not setting.validated_at or datetime.now(UTC) >= setting.validated_at + timedelta(minutes=5) or setting.base_revision != current_setting(session).revision:
            raise AppError("identity_candidate_invalid", "Authentication candidate is no longer available", status_code=409)
        candidate_evidence(request, session, setting, auth, user.id)
        setting.state = "validated_candidate"
        return response
    marker = secrets.token_urlsafe(40)
    packet = {"completion_digest": digest(marker), "authenticated_at": int(claims["auth_time"])}
    flow.key_id, flow.verifier_ciphertext = seal(request.app.state.settings, json.dumps(packet), context=f"auth-flow:{flow.id}")
    flow.purpose = "reauth_complete"
    response.set_cookie(COMPLETION_COOKIE, f"{flow.id}:{marker}", max_age=300, secure=True, httponly=True, samesite="lax", path="/")
    return response


@router.post("/reauth/complete")
def finish_reauthentication(request: Request, response: Response, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> dict:
    editor(context)
    try:
        flow_id, marker = request.cookies.get(COMPLETION_COOKIE, "").split(":", 1)
        flow = session.scalar(select(AuthLoginFlow).where(AuthLoginFlow.id == UUID(flow_id)).with_for_update())
    except (ValueError, TypeError) as exc:
        raise AppError("fresh_authentication_failed", "Fresh authentication proof is unavailable", status_code=401) from exc
    if not flow or flow.purpose != "reauth_complete" or flow.user_id != context.user_id or str(flow.initiating_session_id) != context.principal.session_id or datetime.now(UTC) >= flow.expires_at:
        raise AppError("fresh_authentication_failed", "Fresh authentication proof is invalid", status_code=401)
    packet = json.loads(unseal(request.app.state.settings, flow.key_id, flow.verifier_ciphertext, context=f"auth-flow:{flow.id}"))
    if not hmac.compare_digest(digest(marker), packet["completion_digest"]):
        raise AppError("fresh_authentication_failed", "Fresh authentication proof is invalid", status_code=401)
    flow.purpose = "reauth_used"
    grant = grant_unlock(request, session, context.user_id, request.state.auth_session, authenticated_at=datetime.fromtimestamp(packet["authenticated_at"], UTC))
    session.commit()
    response.delete_cookie(COMPLETION_COOKIE, secure=True, httponly=True, samesite="lax", path="/")
    return {"unlocked": True, "expires_at": grant.expires_at.isoformat()}


@router.post("/lock", status_code=204)
def lock_settings(request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> Response:
    editor(context)
    session.execute(update(IdentityUnlockGrant).where(IdentityUnlockGrant.session_id == context.principal.session_id, IdentityUnlockGrant.scope == SCOPE, IdentityUnlockGrant.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    session.commit()
    return Response(status_code=204)


def validate_live(request: Request, session: Session, setting: IdentitySetting) -> None:
    cfg = configuration(setting)
    directory = LdapDirectory(request.app.state.settings, cfg.directory, read_secret(session, request.app.state.settings, setting, "ldap_bind_password"))
    directory.snapshot("people_and_groups")
    if cfg.auth_mode == "oidc":
        metadata(request, setting)
        with oauth_client(request, session, setting):
            pass


@router.post("/validate")
def validate_candidate(payload: CandidateRequest, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> dict:
    unlock(session, context)
    previous = current_setting(session)
    if previous.revision != payload.expected_revision:
        raise AppError("identity_revision_conflict", "Authentication settings have changed", status_code=409)
    changes: dict[str, str] = {}
    for purpose, operation in payload.secrets.items():
        if purpose not in {"ldap_bind_password", "oidc_client_secret"} or operation.operation not in {"keep", "replace", "clear"}:
            raise AppError("validation_error", "Credential operation is invalid", status_code=422)
        if operation.operation == "replace":
            if not operation.value or not operation.value.get_secret_value():
                raise AppError("validation_error", "Replacement credential is empty", status_code=422)
            changes[purpose] = operation.value.get_secret_value()
        elif operation.operation == "clear":
            changes[purpose] = ""
    candidate = stage_configuration(session, request.app.state.settings, payload.configuration, changes, context.user_id, previous=previous)
    try:
        validate_live(request, session, candidate)
        candidate.validated_at = datetime.now(UTC)
        requires_login = needs_canary(previous, candidate) or payload.configuration.auth_mode == "oidc" and "oidc_client_secret" in changes
        candidate.state = "validated_candidate_requires_login" if requires_login else "validated_candidate"
        if not requires_login:
            candidate_evidence(request, session, candidate, request.state.auth_session, context.user_id)
        add_audit(session, actor_user_id=context.user_id, action="auth.settings.validate", resource_type="identity_settings", resource_id=candidate.id, result="success", request_id=request.state.request_id, summary={"revision": candidate.revision, "candidate_login_required": requires_login})
        session.commit()
        return {"candidate_id": str(candidate.id), "revision": candidate.revision, "state": candidate.state, "candidate_login_required": requires_login}
    except AppError:
        session.rollback()
        raise


@router.put("")
def activate_candidate(payload: ActivationRequest, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> dict:
    unlock(session, context)
    session.execute(text("SELECT pg_advisory_xact_lock(4873662102)"))
    previous = current_setting(session)
    candidate = session.scalar(select(IdentitySetting).where(IdentitySetting.id == payload.candidate_id).with_for_update())
    if previous.revision != payload.expected_revision or not candidate or candidate.created_by != context.user_id or candidate.state != "validated_candidate" or candidate.base_revision != previous.revision:
        raise AppError("identity_revision_conflict", "Authentication settings must be validated again", status_code=409)
    evidence = session.scalar(select(AuthCandidateEvidence).where(AuthCandidateEvidence.setting_id == candidate.id, AuthCandidateEvidence.session_id == request.state.auth_session.id, AuthCandidateEvidence.user_id == context.user_id, AuthCandidateEvidence.consumed_at.is_(None), AuthCandidateEvidence.expires_at > datetime.now(UTC)).with_for_update())
    if not evidence or not hmac.compare_digest(evidence.candidate_digest, candidate_digest(request, session, candidate)):
        raise AppError("identity_candidate_invalid", "Authentication candidate evidence has expired", status_code=409)
    before, after = configuration(previous).model_dump(mode="json"), configuration(candidate).model_dump(mode="json")
    for key in ("sync_enabled", "sync_scope", "sync_schedule", "timezone", "display_name"):
        before.pop(key, None)
        after.pop(key, None)
    sensitive = before != after or any(not hmac.compare_digest(read_secret(session, request.app.state.settings, previous, purpose), read_secret(session, request.app.state.settings, candidate, purpose)) for purpose in ("ldap_bind_password", "oidc_client_secret"))
    previous.is_current, previous.is_last_known_good = False, True
    session.flush()
    candidate.is_current = True
    candidate.state = "validated_active_locked"
    candidate.session_revision = candidate.revision if sensitive else previous.session_revision or previous.revision
    evidence.consumed_at = datetime.now(UTC)
    if sensitive:
        session.execute(update(AuthSession).where(AuthSession.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
        session.execute(update(IdentityUnlockGrant).where(IdentityUnlockGrant.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    else:
        session.execute(update(IdentityUnlockGrant).where(IdentityUnlockGrant.session_id == context.principal.session_id, IdentityUnlockGrant.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    add_audit(session, actor_user_id=context.user_id, action="auth.settings.activate", resource_type="identity_settings", resource_id=candidate.id, result="success", request_id=request.state.request_id, summary={"revision": candidate.revision, "sessions_revoked": sensitive})
    session.commit()
    return {"revision": candidate.revision, "state": candidate.state, "reauthentication_required": sensitive}


@router.post("/identity-bindings")
def bind_identity(payload: BindingRequest, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> dict:
    unlock(session, context)
    current = current_setting(session)
    cfg = configuration(current)
    user = session.get(User, payload.user_id)
    if current.revision != payload.expected_revision or cfg.directory.source_id != payload.source_id or not cfg.oidc or cfg.oidc.issuer != payload.issuer:
        raise AppError("identity_revision_conflict", "Identity source does not match the active settings", status_code=409)
    if not user or user.directory_source_id != payload.source_id or user.directory_object_id != payload.directory_object_id:
        raise AppError("identity_binding_invalid", "Identity must match a synchronized directory person", status_code=422)
    binding_key = int.from_bytes(sha256(f"{payload.source_id}\0{payload.issuer}\0{payload.subject}".encode()).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": binding_key})
    existing = session.scalar(select(AuthenticationIdentity).where(AuthenticationIdentity.source_id == payload.source_id, AuthenticationIdentity.issuer == payload.issuer, AuthenticationIdentity.subject == payload.subject))
    if existing and existing.user_id != user.id:
        raise AppError("identity_binding_conflict", "This sign-in identity is already linked", status_code=409)
    if existing is None:
        existing = AuthenticationIdentity(id=uuid4(), source_id=payload.source_id, issuer=payload.issuer, subject=payload.subject, user_id=user.id)
        session.add(existing)
    add_audit(session, actor_user_id=context.user_id, action="auth.identity.bind", resource_type="user", resource_id=user.id, result="success", request_id=request.state.request_id, summary={"source_id": str(payload.source_id), "subject_fingerprint": digest(payload.subject)})
    session.commit()
    return {"user_id": str(user.id), "binding_id": str(existing.id)}


@router.get("/directory-providers")
def directory_providers(context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[dict]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    row = current_setting(session)
    cfg = configuration(row)
    return [{"id": str(cfg.directory.source_id), "name": cfg.directory.name, "vendor": cfg.directory.schema_type, "enabled": cfg.sync_enabled, "custom_user_search_filter": cfg.directory.user_filter, "config_hash": digest(json.dumps(cfg.directory.model_dump(mode="json"), sort_keys=True)), "checked_at": datetime.now(UTC).isoformat()}]


@router.get("/candidates/{candidate_id}")
def candidate_status(candidate_id: UUID, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> dict:
    unlock(session, context)
    row = session.get(IdentitySetting, candidate_id)
    if row is None or row.created_by != context.user_id or row.base_revision != current_setting(session).revision or not row.validated_at or datetime.now(UTC) >= row.validated_at + timedelta(minutes=5):
        raise AppError("identity_candidate_invalid", "Validate the authentication candidate again", status_code=409)
    return {"candidate_id": str(row.id), "state": row.state, "candidate_login_required": row.state == "validated_candidate_requires_login"}
