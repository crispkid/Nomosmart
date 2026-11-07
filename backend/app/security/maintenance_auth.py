"""Authenticate local maintenance with the active application auth contract."""
from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import IdentitySetting
from app.security.auth import build_identity_jwt_validator, is_token_revoked
from app.security.session_auth import principal_for_session, validate_session_secret


def validate_maintenance_input(payload):
    """Reject malformed private credentials before opening a DB transaction."""
    fields = {"session_cookie", "access_token"}.intersection(payload)
    if len(fields) != 1:
        raise AppError("file_processing_cli_input_invalid", "Supply exactly one maintenance credential", status_code=422)
    field = next(iter(fields))
    value = payload[field]
    limit = 200 if field == "session_cookie" else 32768
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        raise AppError("authentication_required", "A maintenance credential is required", status_code=401)
    return fields


def maintenance_principal(session, settings, payload):
    fields = validate_maintenance_input(payload)
    current = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
    if current is None:
        raise AppError("auth_configuration_unavailable", "Authentication configuration is unavailable", status_code=503)
    if current.configuration.get("auth_contract_revision") == 2:
        if fields != {"session_cookie"}:
            raise AppError("authentication_required", "An application session is required", status_code=401)
        row = validate_session_secret(settings, session, payload["session_cookie"])
        return principal_for_session(settings, session, row)
    # Explicit pre-protocol configuration only. A current deployment never
    # accepts an external JWT as a replacement for its server-owned session.
    token = payload.get("access_token")
    if fields != {"access_token"} or not isinstance(token, str) or not 1 <= len(token) <= 32768:
        raise AppError("authentication_required", "A legacy maintenance credential is required", status_code=401)
    principal = build_identity_jwt_validator(settings, current.configuration).validate(token)
    if is_token_revoked(session, principal, token):
        raise AppError("token_revoked", "Maintenance credential has been revoked", status_code=401)
    return principal
