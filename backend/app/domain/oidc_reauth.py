from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import jwt
from jwt import PyJWKClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import IdentityReauthFlow, IdentitySetting
from app.security.context import IdentityContext


FLOW_TTL = timedelta(minutes=5)
FRESH_AUTH_MAX_AGE_SECONDS = 300
COOKIE_NAME = "nomosmart_identity_reauth"


def begin_oidc_reauthentication(
    session: Session,
    settings: Settings,
    context: IdentityContext,
    *,
    scope: str,
    callback_path: str,
    return_path: str,
    now: datetime | None = None,
) -> dict[str, str]:
    if not context.principal.session_id:
        raise AppError("reauth_session_required", "The current Keycloak session cannot be rebound", status_code=401)
    current = now or datetime.now(UTC)
    state = token_urlsafe(32)
    nonce = token_urlsafe(32)
    verifier = token_urlsafe(48)
    flow_id = uuid4()
    issuer, jwks_url = _active_identity_endpoints(session, settings)
    redirect_uri = f"{settings.frontend_app_origin.rstrip('/')}{callback_path}"
    session.execute(
        update(IdentityReauthFlow)
        .where(
            IdentityReauthFlow.user_id == context.user_id,
            IdentityReauthFlow.session_id == context.principal.session_id,
            IdentityReauthFlow.scope == scope,
            IdentityReauthFlow.consumed_at.is_(None),
            IdentityReauthFlow.revoked_at.is_(None),
        )
        .values(revoked_at=current)
    )
    flow = IdentityReauthFlow(
        id=flow_id,
        user_id=context.user_id,
        subject=context.principal.subject,
        session_id=context.principal.session_id,
        scope=scope,
        state_digest=_digest(state),
        nonce_digest=_digest(nonce),
        pkce_verifier_encrypted=EnvelopeCipher(settings.encryption_key_bytes).encrypt(verifier, context=f"oidc-reauth:{flow_id}"),
        issuer_url=issuer,
        jwks_url=jwks_url,
        client_id=settings.oidc_frontend_client_id,
        redirect_uri=redirect_uri,
        return_path=return_path,
        expires_at=current + FLOW_TTL,
        created_at=current,
    )
    session.add(flow)
    challenge = base64.urlsafe_b64encode(sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    query = urlencode(
        {
            "client_id": flow.client_id,
            "redirect_uri": flow.redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "login",
            "max_age": "0",
        }
    )
    return {"authorization_url": f"{issuer.rstrip('/')}/protocol/openid-connect/auth?{query}"}


def authenticate_oidc_reauth_callback(
    session: Session,
    settings: Settings,
    *,
    scope: str,
    state: str,
    code: str,
    now: datetime | None = None,
) -> tuple[IdentityReauthFlow, str]:
    current = now or datetime.now(UTC)
    flow = session.scalar(
        select(IdentityReauthFlow)
        .where(
            IdentityReauthFlow.state_digest == _digest(state),
            IdentityReauthFlow.scope == scope,
        )
        .with_for_update()
    )
    _require_open_flow(flow, current)
    assert flow is not None
    verifier = EnvelopeCipher(settings.encryption_key_bytes).decrypt(flow.pkce_verifier_encrypted, context=f"oidc-reauth:{flow.id}")
    try:
        response = httpx.post(
            f"{flow.issuer_url.rstrip('/')}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "client_id": flow.client_id,
                "redirect_uri": flow.redirect_uri,
                "code": code,
                "code_verifier": verifier,
            },
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise AppError("oidc_reauth_provider_unavailable", "Keycloak reauthentication is unavailable", status_code=502) from exc
    if response.status_code >= 400:
        raise AppError("oidc_reauth_exchange_failed", "Keycloak reauthentication could not be completed", status_code=401)
    try:
        token_payload = response.json()
        if not isinstance(token_payload, dict) or not isinstance(token_payload.get("id_token"), str):
            raise ValueError("missing id_token")
        id_token = token_payload["id_token"]
        signing_key = PyJWKClient(flow.jwks_url, cache_keys=True).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token,
            key=signing_key,
            algorithms=["RS256", "ES256"],
            issuer=flow.issuer_url,
            audience=flow.client_id,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce", "auth_time"]},
        )
    except (KeyError, ValueError, jwt.PyJWTError) as exc:
        raise AppError("oidc_reauth_token_invalid", "Keycloak reauthentication token is invalid", status_code=401) from exc
    auth_time_value = claims.get("auth_time")
    if not isinstance(auth_time_value, int):
        raise AppError("oidc_reauth_token_invalid", "Keycloak reauthentication token is invalid", status_code=401)
    auth_time = datetime.fromtimestamp(auth_time_value, UTC)
    age = (current - auth_time).total_seconds()
    if claims.get("sub") != flow.subject or _digest(str(claims.get("nonce"))) != flow.nonce_digest or age < 0 or age > FRESH_AUTH_MAX_AGE_SECONDS:
        raise AppError("oidc_reauth_binding_invalid", "Keycloak reauthentication binding is invalid", status_code=401)
    completion_token = token_urlsafe(32)
    flow.completion_token_digest = _digest(completion_token)
    flow.authenticated_subject = str(claims["sub"])
    flow.authenticated_session_id = _optional_string(claims.get("sid"))
    flow.authenticated_auth_time = auth_time
    flow.authenticated_at = current
    return flow, completion_token


def consume_oidc_reauthentication(
    session: Session,
    context: IdentityContext,
    *,
    scope: str,
    completion_token: str | None,
    now: datetime | None = None,
) -> IdentityReauthFlow:
    current = now or datetime.now(UTC)
    if not completion_token or not context.principal.session_id:
        raise AppError("oidc_reauth_completion_required", "Keycloak reauthentication completion is required", status_code=401)
    flow = session.scalar(
        select(IdentityReauthFlow)
        .where(
            IdentityReauthFlow.completion_token_digest == _digest(completion_token),
            IdentityReauthFlow.scope == scope,
        )
        .with_for_update()
    )
    _require_open_flow(flow, current, require_authenticated=True)
    assert flow is not None
    if flow.user_id != context.user_id or flow.subject != context.principal.subject or flow.session_id != context.principal.session_id:
        raise AppError("oidc_reauth_binding_invalid", "Keycloak reauthentication binding is invalid", status_code=401)
    flow.consumed_at = current
    return flow


def _active_identity_endpoints(session: Session, settings: Settings) -> tuple[str, str]:
    row = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
    configuration = row.configuration if row is not None and isinstance(row.configuration, dict) else {}
    issuer = str(configuration.get("issuer_url") or settings.oidc_issuer_url).rstrip("/")
    jwks_url = str(configuration.get("jwks_url") or f"{issuer}/protocol/openid-connect/certs")
    return issuer, jwks_url


def _require_open_flow(flow: IdentityReauthFlow | None, now: datetime, *, require_authenticated: bool = False) -> None:
    if flow is None or flow.expires_at <= now or flow.revoked_at is not None or flow.consumed_at is not None:
        raise AppError("oidc_reauth_flow_invalid", "Keycloak reauthentication flow is invalid or expired", status_code=401)
    if require_authenticated and (flow.authenticated_at is None or flow.completion_token_digest is None or flow.authenticated_auth_time is None):
        raise AppError("oidc_reauth_completion_required", "Keycloak reauthentication completion is required", status_code=401)
    if not require_authenticated and flow.authenticated_at is not None:
        raise AppError("oidc_reauth_flow_replayed", "Keycloak reauthentication flow was already used", status_code=401)


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None
