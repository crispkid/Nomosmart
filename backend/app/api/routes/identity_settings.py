from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.schemas import (
    DirectoryProviderFilterUpdate,
    DirectoryProviderResponse,
    IdentitySettingsCandidate,
    IdentitySettingsResponse,
)
from app.core.errors import AppError
from app.db.models import IdentitySetting, IdentityUnlockGrant
from app.db.session import get_db
from app.domain.directory_filters import directory_filter_hash, validate_directory_filter
from app.domain.identity_settings import validate_identity_candidate_live
from app.domain.oidc_reauth import COOKIE_NAME, authenticate_oidc_reauth_callback, begin_oidc_reauthentication, consume_oidc_reauthentication
from app.security.auth import build_identity_jwt_validator
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.integrations.keycloak import KeycloakAdminClient
from app.services.audit import add_audit


router = APIRouter(prefix="/system/identity-settings", tags=["identity-settings"])
SCOPE = "identity-settings"
SYSTEM_REAUTH_RESULT_PATH = "/system?tab=identity&reauth="


def _can_edit(context: IdentityContext) -> bool:
    try:
        require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
        return True
    except AppError:
        return False


def _deployment_configuration(settings: object) -> dict[str, object]:
    issuer = str(settings.oidc_issuer_url).rstrip("/")
    return {
        "issuer_url": issuer,
        "realm": issuer.rsplit("/", 1)[-1],
        "client_id": settings.oidc_frontend_client_id,
        "audience": settings.oidc_audience,
        "discovery_url": f"{issuer}/.well-known/openid-configuration",
        "jwks_url": f"{issuer}/protocol/openid-connect/certs",
        "enabled": True,
        "sync_enabled": settings.identity_sync_enabled,
        "sync_scope": settings.identity_sync_scope,
        "sync_schedule": settings.identity_sync_schedule,
        "timezone": settings.identity_sync_timezone,
    }


def _effective_configuration(settings: object, current: IdentitySetting | None) -> tuple[dict[str, object], str]:
    deployment = _deployment_configuration(settings)
    if current is None:
        return deployment, "deployment"
    return {**deployment, **current.configuration}, "database"


def _concurrency_key(settings: object) -> bytes:
    return bytes.fromhex(settings.app_encryption_key.get_secret_value())


def _keycloak_client(settings: object) -> KeycloakAdminClient:
    realm = str(settings.oidc_issuer_url).rstrip("/").rsplit("/", 1)[-1]
    return KeycloakAdminClient(
        base_url=settings.keycloak_admin_endpoint,
        realm=realm,
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
    )


def _require_unlock(session: Session, context: IdentityContext, *, lock: bool = False) -> IdentityUnlockGrant:
    now = datetime.now(UTC)
    statement = select(IdentityUnlockGrant).where(
        IdentityUnlockGrant.user_id == context.user_id,
        IdentityUnlockGrant.session_id == context.principal.session_id,
        IdentityUnlockGrant.scope == SCOPE,
        IdentityUnlockGrant.revoked_at.is_(None),
        IdentityUnlockGrant.expires_at > now,
    )
    if lock:
        statement = statement.with_for_update()
    grant = session.scalar(statement)
    if grant is None:
        raise AppError("identity_settings_locked", "Identity settings are locked", status_code=423)
    return grant


def _reauth_result_url(frontend_origin: str, result: str) -> str:
    if result not in {"success", "cancelled", "error"}:
        result = "error"
    return f"{frontend_origin.rstrip('/')}{SYSTEM_REAUTH_RESULT_PATH}{result}"


@router.get("", response_model=IdentitySettingsResponse)
def get_identity_settings(
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IdentitySettingsResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    current = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
    configuration, source = _effective_configuration(request.app.state.settings, current)
    return IdentitySettingsResponse(
        state=current.state if current is not None else "deployment_active_locked",
        configuration=configuration,
        configuration_source=source,
        secret_configured=bool(request.app.state.settings.oidc_client_secret.get_secret_value()),
        editable=_can_edit(context),
        revision=current.revision if current is not None else None,
    )


@router.get("/directory-providers", response_model=list[DirectoryProviderResponse])
def list_directory_providers(
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
) -> list[DirectoryProviderResponse]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    providers = _keycloak_client(request.app.state.settings).list_directory_providers(
        concurrency_key=_concurrency_key(request.app.state.settings)
    )
    return [DirectoryProviderResponse(**provider.__dict__) for provider in providers]


@router.put("/directory-providers/{provider_id}/filter", response_model=DirectoryProviderResponse)
def update_directory_provider_filter(
    provider_id: str,
    payload: DirectoryProviderFilterUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> DirectoryProviderResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    _require_unlock(session, context)
    validated_filter = validate_directory_filter(payload.custom_user_search_filter)
    new_hash = directory_filter_hash(validated_filter)
    try:
        provider, old_filter = _keycloak_client(request.app.state.settings).update_directory_provider_filter(
            provider_id,
            custom_user_search_filter=validated_filter,
            expected_config_hash=payload.config_hash,
            concurrency_key=_concurrency_key(request.app.state.settings),
        )
    except AppError as exc:
        add_audit(
            session,
            actor_user_id=context.user_id,
            action="identity_settings.directory_filter.update",
            resource_type="keycloak_directory_provider",
            resource_id=None,
            result="failed",
            request_id=request.state.request_id,
            summary={
                "provider_id": provider_id,
                "new_filter_hash": new_hash,
                "new_filter_length": len(validated_filter.encode("utf-8")),
                "error_code": exc.code,
            },
        )
        session.commit()
        raise
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="identity_settings.directory_filter.update",
        resource_type="keycloak_directory_provider",
        resource_id=None,
        result="success",
        request_id=request.state.request_id,
        summary={
            "provider_id": provider_id,
            "old_filter_hash": directory_filter_hash(old_filter),
            "new_filter_hash": new_hash,
            "old_filter_length": len(old_filter.encode("utf-8")),
            "new_filter_length": len(validated_filter.encode("utf-8")),
        },
    )
    session.commit()
    return DirectoryProviderResponse(**provider.__dict__)


@router.post("/reauth/start")
def start_reauthentication(
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    result = begin_oidc_reauthentication(
        session,
        request.app.state.settings,
        context,
        scope=SCOPE,
        callback_path="/api/backend/system/identity-settings/reauth/callback",
        return_path=f"{SYSTEM_REAUTH_RESULT_PATH}success",
    )
    add_audit(session, actor_user_id=context.user_id, action="identity_settings.reauth.start", resource_type="identity_settings", resource_id=None, result="success", request_id=request.state.request_id)
    session.commit()
    return result


@router.get("/reauth/callback", include_in_schema=False)
def reauthentication_callback(
    request: Request,
    state: str | None = Query(default=None, min_length=16, max_length=500),
    code: str | None = Query(default=None, min_length=1, max_length=4000),
    error: str | None = Query(default=None, max_length=200),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    settings = request.app.state.settings
    if error:
        result = "cancelled" if error == "access_denied" else "error"
        return RedirectResponse(_reauth_result_url(settings.frontend_app_origin, result), status_code=303)
    if not state or not code:
        return RedirectResponse(_reauth_result_url(settings.frontend_app_origin, "error"), status_code=303)
    try:
        flow, completion_token = authenticate_oidc_reauth_callback(session, settings, scope=SCOPE, state=state, code=code)
        add_audit(session, actor_user_id=flow.user_id, action="identity_settings.reauth.callback", resource_type="identity_reauth_flow", resource_id=flow.id, result="success", request_id=request.state.request_id)
        session.commit()
    except AppError:
        session.rollback()
        return RedirectResponse(_reauth_result_url(settings.frontend_app_origin, "error"), status_code=303)
    response = RedirectResponse(f"{settings.frontend_app_origin.rstrip('/')}{flow.return_path}", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        completion_token,
        max_age=300,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/api/backend/system/identity-settings/reauth",
    )
    return response


@router.post("/reauth/complete")
def complete_reauthentication(
    request: Request,
    response: Response,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    flow = consume_oidc_reauthentication(session, context, scope=SCOPE, completion_token=request.cookies.get(COOKIE_NAME))
    now = datetime.now(UTC)
    assert context.principal.session_id is not None
    assert flow.authenticated_auth_time is not None
    grant = IdentityUnlockGrant(user_id=context.user_id, session_id=context.principal.session_id, scope=SCOPE, auth_time=flow.authenticated_auth_time, expires_at=now + timedelta(minutes=10), created_at=now)
    session.add(grant)
    add_audit(session, actor_user_id=context.user_id, action="identity_settings.unlock", resource_type="identity_settings", resource_id=None, result="success", request_id=request.state.request_id, summary={"expires_at": grant.expires_at.isoformat()})
    session.commit()
    response.delete_cookie(COOKIE_NAME, path="/api/backend/system/identity-settings/reauth")
    return {"status": "temporarily_unlocked", "expires_at": grant.expires_at.isoformat()}


@router.post("/lock")
def lock_identity_settings(
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    now = datetime.now(UTC)
    session.execute(update(IdentityUnlockGrant).where(IdentityUnlockGrant.user_id == context.user_id, IdentityUnlockGrant.session_id == context.principal.session_id, IdentityUnlockGrant.scope == SCOPE, IdentityUnlockGrant.revoked_at.is_(None)).values(revoked_at=now))
    add_audit(session, actor_user_id=context.user_id, action="identity_settings.lock", resource_type="identity_settings", resource_id=None, result="success", request_id=request.state.request_id)
    session.commit()
    return {"status": "validated_active_locked"}


@router.post("/validate")
def validate_identity_settings(
    candidate: IdentitySettingsCandidate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
) -> dict[str, object]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    validated = validate_identity_candidate_live(candidate, allow_http=request.app.state.settings.app_env != "production")
    return {"valid": True, "configuration": validated}


@router.put("", response_model=IdentitySettingsResponse)
def activate_identity_settings(
    candidate: IdentitySettingsCandidate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IdentitySettingsResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    now = datetime.now(UTC)
    grant = _require_unlock(session, context, lock=True)
    configuration = validate_identity_candidate_live(candidate, allow_http=request.app.state.settings.app_env != "production")
    current = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)).with_for_update())
    revision = 1 if current is None else current.revision + 1
    if current is not None:
        current.is_current = False
        current.is_last_known_good = True
    row = IdentitySetting(revision=revision, state="validated_active_locked", configuration=configuration, secret_configured=bool(request.app.state.settings.oidc_client_secret.get_secret_value()), is_current=True, is_last_known_good=True, validated_at=now, created_by=context.user_id)
    session.add(row)
    grant.revoked_at = now
    session.flush()
    add_audit(session, actor_user_id=context.user_id, action="identity_settings.activate", resource_type="identity_settings", resource_id=row.id, result="success", request_id=request.state.request_id, summary={"revision": revision})
    session.commit()
    request.app.state.dynamic_jwt_revision = revision
    request.app.state.dynamic_jwt_validator = build_identity_jwt_validator(request.app.state.settings, configuration)
    return IdentitySettingsResponse(
        state=row.state,
        configuration=row.configuration,
        secret_configured=row.secret_configured,
        editable=True,
        configuration_source="database",
        revision=row.revision,
    )
