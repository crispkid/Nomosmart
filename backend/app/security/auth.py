from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import logging
from typing import Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import IdentitySetting, RevokedAuthToken
from app.db.session import get_db


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IdentityPrincipal:
    subject: str
    employee_id: str | None
    email: str | None
    display_name: str | None
    groups: tuple[str, ...]
    session_id: str | None
    auth_time: int | None
    issuer: str = ""
    audience: str = ""
    token_id: str | None = None
    issued_at: datetime = datetime.fromtimestamp(0, UTC)
    expires_at: datetime = datetime.fromtimestamp(0, UTC)


class JWTValidator:
    def __init__(self, settings: Settings, *, jwk_client: PyJWKClient | None = None) -> None:
        self.settings = settings
        self.jwk_client = jwk_client or PyJWKClient(
            settings.oidc_jwks_endpoint,
            cache_keys=True,
        )

    def validate(self, token: str, *, signing_key: Any | None = None) -> IdentityPrincipal:
        try:
            key = signing_key or self.jwk_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256", "ES256"],
                issuer=self.settings.oidc_issuer_url,
                audience=self.settings.oidc_audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            logger.warning("Access token rejected: expired signature")
            raise AppError("token_expired", "Access token has expired", status_code=401) from exc
        except jwt.ImmatureSignatureError as exc:
            logger.warning("Access token rejected: token not active")
            raise AppError("token_not_active", "Access token is not active", status_code=401) from exc
        except jwt.PyJWTError as exc:
            missing_claim = getattr(exc, "claim", None)
            if missing_claim:
                logger.warning("Access token rejected: %s missing %s", exc.__class__.__name__, missing_claim)
            else:
                logger.warning("Access token rejected: %s", exc.__class__.__name__)
            raise AppError("invalid_token", "Access token is invalid", status_code=401) from exc
        groups = claims.get("groups") or []
        if not isinstance(groups, list):
            groups = []
        audience = claims.get("aud")
        if isinstance(audience, list):
            audience_value = " ".join(str(item) for item in audience)
        else:
            audience_value = str(audience)
        return IdentityPrincipal(
            subject=str(claims["sub"]),
            employee_id=_optional_string(claims.get("employee_id")),
            email=_optional_string(claims.get("email")),
            display_name=_optional_string(claims.get("name")),
            groups=tuple(str(group) for group in groups),
            session_id=_optional_string(claims.get("sid")),
            auth_time=claims.get("auth_time") if isinstance(claims.get("auth_time"), int) else None,
            issuer=str(claims["iss"]),
            audience=audience_value,
            token_id=_optional_string(claims.get("jti")),
            issued_at=_timestamp_to_datetime(claims["iat"]),
            expires_at=_timestamp_to_datetime(claims["exp"]),
        )


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _timestamp_to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromtimestamp(int(value), UTC)


bearer = HTTPBearer(auto_error=False)


def get_jwt_validator(request: Request, session: Session = Depends(get_db)) -> JWTValidator:
    injected = getattr(request.app.state, "jwt_validator", None)
    if injected is not None:
        return injected
    current = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
    revision = current.revision if current is not None else 0
    cached_revision = getattr(request.app.state, "dynamic_jwt_revision", None)
    cached_validator = getattr(request.app.state, "dynamic_jwt_validator", None)
    if cached_validator is not None and cached_revision == revision:
        return cached_validator
    validator = build_identity_jwt_validator(request.app.state.settings, current.configuration if current is not None else {})
    request.app.state.dynamic_jwt_revision = revision
    request.app.state.dynamic_jwt_validator = validator
    return validator


def build_identity_jwt_validator(settings: Settings, configuration: dict[str, Any]) -> JWTValidator:
    issuer = str(configuration.get("issuer_url") or settings.oidc_issuer_url).rstrip("/")
    audience = str(configuration.get("audience") or settings.oidc_audience)
    configured_jwks = settings.oidc_jwks_url if issuer == settings.oidc_issuer_url.rstrip("/") else ""
    jwks_url = str(configuration.get("jwks_url") or configured_jwks or f"{issuer}/protocol/openid-connect/certs")
    effective = settings.model_copy(update={"oidc_issuer_url": issuer, "oidc_audience": audience})
    return JWTValidator(effective, jwk_client=PyJWKClient(jwks_url, cache_keys=True))


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    validator: JWTValidator = Depends(get_jwt_validator),
    session: Session = Depends(get_db),
) -> IdentityPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("authentication_required", "Bearer access token is required", status_code=401)
    principal = validator.validate(credentials.credentials)
    if is_token_revoked(session, principal, credentials.credentials):
        raise AppError("token_revoked", "Access token has been revoked", status_code=401)
    return principal


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def token_identity(principal: IdentityPrincipal, token: str) -> str:
    if principal.token_id:
        material = f"jti|{principal.issuer}|{principal.token_id}"
    else:
        material = (
            f"fallback|{principal.issuer}|{principal.subject}|{principal.audience}|"
            f"{int(principal.issued_at.timestamp())}|{int(principal.expires_at.timestamp())}|{token_digest(token)}"
        )
    return sha256(material.encode("utf-8")).hexdigest()


def is_token_revoked(session: Session, principal: IdentityPrincipal, token: str) -> bool:
    identity = token_identity(principal, token)
    now = datetime.now(UTC)
    return session.scalar(
        select(RevokedAuthToken.id).where(
            RevokedAuthToken.token_identity == identity,
            RevokedAuthToken.expires_at > now,
        )
    ) is not None
