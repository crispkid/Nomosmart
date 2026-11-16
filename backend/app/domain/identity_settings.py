from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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


def require_fresh_auth(auth_time: int | None, session_id: str | None, *, now: datetime | None = None) -> None:
    effective_now = now or datetime.now(UTC)
    if auth_time is None or not session_id:
        raise AppError("fresh_authentication_required", "Fresh authentication is required", status_code=401)
    age = effective_now.timestamp() - auth_time
    if age < 0 or age > 300:
        raise AppError("fresh_authentication_required", "Fresh authentication is required", status_code=401)
