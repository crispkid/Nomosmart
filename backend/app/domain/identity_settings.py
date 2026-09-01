from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.api.schemas import IdentitySettingsCandidate
from app.core.errors import AppError


def validate_identity_candidate(candidate: IdentitySettingsCandidate, *, allow_http: bool) -> dict[str, object]:
    errors: dict[str, str] = {}
    for field in ("issuer_url", "discovery_url", "jwks_url"):
        value = getattr(candidate, field)
        parsed = urlparse(value)
        if parsed.scheme not in ({"http", "https"} if allow_http else {"https"}) or not parsed.netloc:
            errors[field] = "must be an absolute HTTPS URL" if not allow_http else "must be an absolute HTTP(S) URL"
    try:
        ZoneInfo(candidate.timezone)
    except ZoneInfoNotFoundError:
        errors["timezone"] = "must be a valid IANA timezone"
    if len(candidate.sync_schedule.split()) != 5:
        errors["sync_schedule"] = "must contain five Cron fields"
    if errors:
        raise AppError("invalid_identity_settings", "Identity settings are invalid", status_code=422, details=errors)
    return candidate.model_dump()


def validate_identity_candidate_live(candidate: IdentitySettingsCandidate, *, allow_http: bool) -> dict[str, object]:
    validated = validate_identity_candidate(candidate, allow_http=allow_http)
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            discovery_response = client.get(candidate.discovery_url)
            discovery_response.raise_for_status()
            discovery = discovery_response.json()
            jwks_response = client.get(candidate.jwks_url)
            jwks_response.raise_for_status()
            jwks = jwks_response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AppError("identity_provider_unavailable", "Identity provider validation failed", status_code=502) from exc
    if not isinstance(discovery, dict) or str(discovery.get("issuer") or "").rstrip("/") != candidate.issuer_url.rstrip("/"):
        raise AppError("identity_discovery_invalid", "OIDC discovery issuer does not match the candidate", status_code=422)
    discovered_jwks = discovery.get("jwks_uri")
    if not isinstance(discovered_jwks, str) or discovered_jwks.rstrip("/") != candidate.jwks_url.rstrip("/"):
        raise AppError("identity_discovery_invalid", "OIDC discovery JWKS URI does not match the candidate", status_code=422)
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list) or not jwks["keys"]:
        raise AppError("identity_jwks_invalid", "OIDC JWKS response does not contain signing keys", status_code=422)
    return validated


def require_fresh_auth(auth_time: int | None, session_id: str | None, *, now: datetime | None = None) -> None:
    effective_now = now or datetime.now(UTC)
    if auth_time is None or not session_id:
        raise AppError("fresh_authentication_required", "Fresh Keycloak authentication is required", status_code=401)
    age = effective_now.timestamp() - auth_time
    if age < 0 or age > 300:
        raise AppError("fresh_authentication_required", "Fresh Keycloak authentication is required", status_code=401)
