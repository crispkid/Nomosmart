from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import SessionDraftCreatePayload, SessionDraftCreateResponse, SessionDraftRestorePayload, SessionDraftRestoreResponse
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import SessionExpiredFormDraft, SystemParameter, User
from app.db.session import get_db
from app.security.auth import JWTValidator, bearer, get_jwt_validator
from app.security.context import IdentityContext, get_identity_context
from app.services.logout import revoke_login_session
from app.services.audit import add_audit


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/oidc/config")
def oidc_config(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "issuer": settings.oidc_issuer_url,
        "client_id": settings.oidc_frontend_client_id,
        "audience": settings.oidc_audience,
        "authorization_flow": "authorization_code_pkce",
    }


@router.get("/me")
def current_user(
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    principal = context.principal
    user = session.get(User, context.user_id)
    if user is None:
        raise AppError("user_not_synchronized", "User has not been synchronized", status_code=403)
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="auth.login.success",
        resource_type="login_session",
        resource_id=None,
        result="success",
        request_id=request.state.request_id,
        summary={"issuer": principal.issuer, "subject_fingerprint": sha256(principal.subject.encode("utf-8")).hexdigest()},
    )
    session.commit()
    return {
        "user_id": str(context.user_id),
        "subject": principal.subject,
        "employee_id": principal.employee_id,
        "email": principal.email,
        "given_name": user.given_name,
        "family_name": user.family_name,
        "display_name": user.display_name,
        "groups": list(principal.groups),
        "permissions": [
            {
                "module_name": grant.module_name,
                "function_name": grant.function_name,
                "can_view": grant.can_view,
                "can_create": grant.can_create,
                "can_edit": grant.can_edit,
                "can_delete": grant.can_delete,
                "can_execute": grant.can_execute,
            }
            for grant in context.grants
        ],
        "visible_project_ids": [str(project_id) for project_id in sorted(context.visible_project_ids, key=str)],
    }


@router.post("/session-drafts", response_model=SessionDraftCreateResponse)
def create_session_draft(
    payload: SessionDraftCreatePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SessionDraftCreateResponse:
    ttl_minutes = _draft_ttl_minutes(session)
    if ttl_minutes == 0:
        raise AppError("session_draft_disabled", "Session-expired form draft recovery is disabled", status_code=422)
    return_path = _safe_return_path(payload.return_path)
    sanitized = _sanitize_draft_payload(payload.payload)
    now = datetime.now(UTC)
    draft = SessionExpiredFormDraft(
        user_id=context.user_id,
        form_key=payload.form_key,
        return_path=return_path,
        nonce_hash=_nonce_hash(payload.nonce),
        payload_encrypted=EnvelopeCipher(request.app.state.settings.encryption_key_bytes).encrypt(
            json.dumps(sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            context=f"session-draft:{context.user_id}:{return_path}:{payload.form_key}",
        ),
        field_count=len(sanitized),
        status="pending",
        metadata_json={"field_names": sorted(sanitized), "source": "auth.session_expired"},
        created_at=now,
        expires_at=now + timedelta(minutes=ttl_minutes),
    )
    session.add(draft)
    session.flush()
    session.commit()
    return SessionDraftCreateResponse(draft_id=draft.id, form_key=draft.form_key, return_path=draft.return_path, expires_at=draft.expires_at, field_count=draft.field_count)


@router.post("/session-drafts/{draft_id}/restore", response_model=SessionDraftRestoreResponse)
def restore_session_draft(
    draft_id: UUID,
    payload: SessionDraftRestorePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SessionDraftRestoreResponse:
    draft = _get_matching_draft(session, draft_id, context.user_id, payload.return_path, payload.nonce)
    decrypted = EnvelopeCipher(request.app.state.settings.encryption_key_bytes).decrypt(
        draft.payload_encrypted,
        context=f"session-draft:{context.user_id}:{draft.return_path}:{draft.form_key}",
    )
    draft.status = "restored"
    draft.restored_at = datetime.now(UTC)
    session.commit()
    return SessionDraftRestoreResponse(draft_id=draft.id, form_key=draft.form_key, return_path=draft.return_path, payload=json.loads(decrypted), expires_at=draft.expires_at)


@router.post("/session-drafts/{draft_id}/discard")
def discard_session_draft(
    draft_id: UUID,
    payload: SessionDraftRestorePayload,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    draft = _get_matching_draft(session, draft_id, context.user_id, payload.return_path, payload.nonce)
    draft.status = "discarded"
    draft.discarded_at = datetime.now(UTC)
    session.commit()
    return {"status": "discarded"}


@router.post("/logout")
def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    validator: JWTValidator = Depends(get_jwt_validator),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("authentication_required", "Bearer access token is required", status_code=401)
    principal = validator.validate(credentials.credentials)
    revoke_login_session(session, principal=principal, token=credentials.credentials, request_id=request.state.request_id)
    return {"status": "logged_out"}


SENSITIVE_DRAFT_KEY_PARTS = ("password", "otp", "token", "secret", "credential", "api_key", "apikey", "authorization", "bearer", "pkce", "private_key", "refresh")


def _draft_ttl_minutes(session: Session) -> int:
    row = session.scalar(select(SystemParameter).where(SystemParameter.key == "session_expired_form_draft_ttl_minutes"))
    return int(row.value if row is not None else 30)


def _safe_return_path(value: str) -> str:
    if not value.startswith("/") or value.startswith("//") or value.startswith("/auth/callback"):
        raise AppError("invalid_return_path", "Return path is invalid", status_code=422)
    return value


def _nonce_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _sanitize_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        normalized = key.lower().replace("-", "_")
        if any(part in normalized for part in SENSITIVE_DRAFT_KEY_PARTS):
            raise AppError("session_draft_sensitive_field", "Session draft contains a sensitive field", status_code=422, details={"field": key})
        if isinstance(value, str):
            sanitized[key] = value[:10000]
        elif isinstance(value, bool) or value is None:
            sanitized[key] = value
        elif isinstance(value, int | float):
            sanitized[key] = value
        elif isinstance(value, list) and all(isinstance(item, str | int | float | bool) or item is None for item in value):
            sanitized[key] = value[:100]
        else:
            raise AppError("session_draft_unsupported_field", "Session draft contains an unsupported field", status_code=422, details={"field": key})
    return sanitized


def _get_matching_draft(session: Session, draft_id: UUID, user_id: UUID, return_path: str, nonce: str) -> SessionExpiredFormDraft:
    draft = session.get(SessionExpiredFormDraft, draft_id)
    now = datetime.now(UTC)
    if draft is None or draft.user_id != user_id or draft.return_path != _safe_return_path(return_path) or draft.nonce_hash != _nonce_hash(nonce):
        raise AppError("session_draft_not_found", "Session draft was not found", status_code=404)
    if draft.status != "pending":
        raise AppError("session_draft_not_available", "Session draft is no longer available", status_code=409)
    if draft.expires_at <= now:
        draft.status = "expired"
        session.commit()
        raise AppError("session_draft_expired", "Session draft has expired", status_code=410)
    return draft
