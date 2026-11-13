"""OIDC relying party: protocol metadata and server-owned code flows."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hmac
import json
import secrets
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4

from authlib.integrations.httpx_client import OAuth2Client
from authlib.common.errors import AuthlibBaseError
import httpx
import jwt
from fastapi import Request, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AuthenticationIdentity, AuthLoginFlow, IdentitySetting, User
from app.security.auth_configuration import configuration, read_secret, seal, unseal
from app.security.auth_network import PinnedAuthTransport, tls_context, validate_endpoint
from app.security.session_auth import FLOW_COOKIE, digest


def safe_return_path(value: str) -> str:
    if not value.startswith("/") or value.startswith("//") or "\\" in value or any(ord(c) < 32 for c in value):
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path.startswith(("/auth", "/api/", "/login")):
        return "/"
    return value[:2048]


def metadata(request: Request, setting: IdentitySetting) -> dict:
    return metadata_for_settings(request.app.state.settings, setting)


def metadata_for_settings(settings, setting: IdentitySetting) -> dict:
    config = configuration(setting).oidc
    if config is None:
        raise AppError("auth_mode_unavailable", "OIDC sign-in is unavailable", status_code=409)
    discovery_url = config.discovery_url or config.issuer + "/.well-known/openid-configuration"
    validate_endpoint(settings, discovery_url)
    try:
        with httpx.Client(timeout=settings.auth_network_timeout_seconds, transport=PinnedAuthTransport(settings, config.ca_reference), trust_env=False, follow_redirects=False) as client:
            response = client.get(discovery_url)
            response.raise_for_status()
            document = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise AppError("identity_provider_unavailable", "OIDC service is unavailable", status_code=503) from exc
    if not isinstance(document, dict) or document.get("issuer") != config.issuer:
        raise AppError("identity_discovery_invalid", "OIDC issuer did not match the configured issuer", status_code=422)
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(document.get(name), str):
            raise AppError("identity_discovery_invalid", "OIDC metadata is incomplete", status_code=422)
        validate_endpoint(settings, document[name])
    if "S256" not in document.get("code_challenge_methods_supported", []):
        raise AppError("oidc_capability_missing", "OIDC service must support PKCE S256", status_code=422)
    if config.client_auth_method != "none" and config.client_auth_method not in document.get("token_endpoint_auth_methods_supported", ["client_secret_basic"]):
        raise AppError("oidc_capability_missing", "OIDC client authentication method is unsupported", status_code=422)
    for name in ("userinfo_endpoint", "end_session_endpoint"):
        if document.get(name):
            validate_endpoint(settings, document[name])
    if config.token_url:
        validate_endpoint(settings, config.token_url)
        document["token_endpoint"] = config.token_url
    if config.jwks_url:
        validate_endpoint(settings, config.jwks_url)
        document["jwks_uri"] = config.jwks_url
    return document


def callback_uri(request: Request) -> str:
    return request.app.state.settings.frontend_app_origin.rstrip("/") + "/api/backend/auth/oidc/callback"


def oauth_client(request: Request, session: Session, setting: IdentitySetting) -> OAuth2Client:
    config = configuration(setting).oidc
    secret = read_secret(session, request.app.state.settings, setting, "oidc_client_secret")
    if config.client_auth_method != "none" and not secret:
        raise AppError("oidc_credential_required", "OIDC client credential is required", status_code=503)
    return OAuth2Client(client_id=config.client_id, client_secret=secret or None, token_endpoint_auth_method=config.client_auth_method, scope=config.scopes, redirect_uri=callback_uri(request), code_challenge_method="S256", timeout=request.app.state.settings.auth_network_timeout_seconds, transport=PinnedAuthTransport(request.app.state.settings, config.ca_reference), trust_env=False, follow_redirects=False)


def start_flow(request: Request, response: Response, session: Session, setting: IdentitySetting, *, purpose: str = "login", return_path: str = "/", initiating_session_id: UUID | None = None, user_id: UUID | None = None) -> str:
    document = metadata(request, setting)
    existing = [key for key in request.cookies if key.startswith(FLOW_COOKIE + "_")]
    if len(existing) >= 4:
        raise AppError("auth_flow_limit", "Too many sign-in attempts are active", status_code=429)
    state, nonce, verifier, marker = (secrets.token_urlsafe(40) for _ in range(4))
    now, flow_id = datetime.now(UTC), uuid4()
    packet = {"verifier": verifier, "marker_digest": digest(marker)}
    key_id, envelope = seal(request.app.state.settings, json.dumps(packet), context=f"auth-flow:{flow_id}")
    row = AuthLoginFlow(id=flow_id, state_digest=digest(state), nonce_digest=digest(nonce), verifier_ciphertext=envelope, key_id=key_id, setting_id=setting.id, purpose=purpose, initiating_session_id=initiating_session_id, user_id=user_id, return_path=safe_return_path(return_path), created_at=now, expires_at=now + timedelta(seconds=request.app.state.settings.auth_flow_ttl_seconds))
    session.add(row)
    with oauth_client(request, session, setting) as client:
        parameters = {"nonce": nonce}
        if purpose != "login":
            parameters.update(prompt="login", max_age=0)
        url, _ = client.create_authorization_url(document["authorization_endpoint"], state=state, code_verifier=verifier, **parameters)
    response.set_cookie(FLOW_COOKIE + "_" + digest(state)[:24], marker, max_age=300, secure=True, httponly=True, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return url


def consume_flow(request: Request, session: Session, *, state: str, code: str) -> tuple[AuthLoginFlow, IdentitySetting, dict]:
    row = session.scalar(select(AuthLoginFlow).where(AuthLoginFlow.state_digest == digest(state)).with_for_update())
    now = datetime.now(UTC)
    if not state or not code or row is None or row.consumed_at or now >= row.expires_at:
        raise AppError("oidc_state_invalid", "OIDC sign-in could not be verified", status_code=401)
    packet = json.loads(unseal(request.app.state.settings, row.key_id, row.verifier_ciphertext, context=f"auth-flow:{row.id}"))
    marker = request.cookies.get(FLOW_COOKIE + "_" + digest(state)[:24], "")
    if not marker or not hmac.compare_digest(digest(marker), packet["marker_digest"]):
        raise AppError("oidc_state_invalid", "OIDC sign-in could not be verified", status_code=401)
    row.consumed_at = now
    # Consume before the external exchange, so an unknown result is never replayed.
    session.commit()
    setting = session.get(IdentitySetting, row.setting_id)
    config = configuration(setting).oidc
    document = metadata(request, setting)
    stage = "token_exchange"
    try:
        with oauth_client(request, session, setting) as client:
            tokens = client.fetch_token(document["token_endpoint"], grant_type="authorization_code", code=code, code_verifier=packet["verifier"])
            id_token = tokens.get("id_token")
            if not isinstance(id_token, str):
                raise ValueError("ID Token required")
            stage = "jwks_fetch"
            jwks = client.request("GET", document["jwks_uri"], withhold_token=True)
            jwks.raise_for_status()
            stage = "id_token_validation"
            header = jwt.get_unverified_header(id_token)
            allowed = {"RS256", "ES256", "PS256", "EdDSA"} & set(document.get("id_token_signing_alg_values_supported", []))
            if header.get("alg") not in allowed:
                raise ValueError("Unsupported signing algorithm")
            keys = [key for key in jwt.PyJWKSet.from_dict(jwks.json()).keys if key.public_key_use in {None, "sig"} and (not header.get("kid") or key.key_id == header["kid"]) and key.algorithm_name == header["alg"]]
            if len(keys) != 1:
                raise ValueError("No unique signing key")
            claims = jwt.decode(id_token, keys[0].key, algorithms=[header["alg"]], issuer=config.issuer, audience=config.client_id, options={"require": ["iss", "sub", "aud", "iat", "exp", "nonce"]})
            if not isinstance(claims["sub"], str) or not claims["sub"] or len(claims["sub"]) > 255 or not hmac.compare_digest(digest(str(claims["nonce"])), row.nonce_digest):
                raise ValueError("Invalid identity or nonce")
            if (isinstance(claims["aud"], list) and len(claims["aud"]) > 1 or "azp" in claims) and claims.get("azp") != config.client_id:
                raise ValueError("Invalid authorized party")
            if row.purpose != "login":
                auth_time = claims.get("auth_time")
                if type(auth_time) is not int or not int(row.created_at.timestamp()) - 5 <= auth_time <= int(now.timestamp()) + 5:
                    raise ValueError("Fresh authentication required")
            if config.mapping_claim not in claims and document.get("userinfo_endpoint") and tokens.get("access_token"):
                stage = "userinfo_validation"
                info = client.get(document["userinfo_endpoint"])
                info.raise_for_status()
                attributes = info.json()
                if attributes.get("sub") != claims["sub"]:
                    raise ValueError("UserInfo identity mismatch")
                if config.mapping_claim in attributes:
                    claims[config.mapping_claim] = attributes[config.mapping_claim]
            return row, setting, claims
    except (AuthlibBaseError, httpx.HTTPError, jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        error = AppError("oidc_authentication_failed", "OIDC sign-in could not be verified", status_code=401)
        error.auth_stage = stage
        raise error from exc


def resolve_oidc_user(session: Session, setting: IdentitySetting, claims: dict, *, persist: bool = True) -> User:
    config = configuration(setting)
    if persist:
        from hashlib import sha256
        key = int.from_bytes(sha256(f"{config.directory.source_id}\0{config.oidc.issuer}\0{claims['sub']}".encode()).digest()[:8], "big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    binding = session.scalar(select(AuthenticationIdentity).where(AuthenticationIdentity.source_id == config.directory.source_id, AuthenticationIdentity.issuer == config.oidc.issuer, AuthenticationIdentity.subject == claims["sub"]))
    if binding:
        user = session.get(User, binding.user_id)
    else:
        identifier = claims.get(config.oidc.mapping_claim)
        if not isinstance(identifier, str) or not identifier:
            raise AppError("identity_binding_required", "An administrator must link this sign-in identity", status_code=403)
        if config.oidc.mapping_attribute == "object_id":
            try:
                identifier = str(UUID(identifier.strip("{}")))
            except ValueError as exc:
                raise AppError("identity_binding_required", "Sign-in identity does not match the directory", status_code=403) from exc
            condition = User.directory_object_id == identifier
        else:
            condition = User.employee_id == identifier
        matches = session.scalars(select(User).where(User.directory_source_id == config.directory.source_id, condition)).all()
        if len(matches) != 1:
            raise AppError("identity_binding_required", "An administrator must link this sign-in identity", status_code=403)
        user = matches[0]
        if persist:
            session.add(AuthenticationIdentity(id=uuid4(), source_id=config.directory.source_id, issuer=config.oidc.issuer, subject=claims["sub"], user_id=user.id))
    if user is None or user.directory_source_id != config.directory.source_id or not user.is_active or user.locally_disabled or not user.directory_enabled:
        raise AppError("user_disabled", "User account is unavailable", status_code=403)
    return user


def discard_failed_flow(request: Request, session: Session, state: str) -> None:
    row = session.scalar(select(AuthLoginFlow).where(AuthLoginFlow.state_digest == digest(state)).with_for_update())
    if row is None or row.consumed_at or datetime.now(UTC) >= row.expires_at:
        return
    packet = json.loads(unseal(request.app.state.settings, row.key_id, row.verifier_ciphertext, context=f"auth-flow:{row.id}"))
    marker = request.cookies.get(FLOW_COOKIE + "_" + digest(state)[:24], "")
    if marker and hmac.compare_digest(digest(marker), packet.get("marker_digest", "")):
        row.consumed_at = datetime.now(UTC)
        session.commit()
