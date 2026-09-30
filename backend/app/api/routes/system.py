from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import BreakGlassStatusResponse, OperationsStatusResponse, SystemParametersPayload, UploadConfigResponse
from app.core.errors import AppError
from app.db.models import SystemParameter
from app.db.session import get_db
from app.domain.system_parameters import SystemParameterValues
from app.domain.operations import build_operations_status
from app.integrations.keycloak import KeycloakAdminClient, KeycloakBreakGlassStatus
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.services.audit import add_audit


router = APIRouter(prefix="/system", tags=["system"])


def _keycloak_realm(issuer_url: str) -> str:
    return issuer_url.rstrip("/").rsplit("/", 1)[-1]


def _break_glass_deployment_evidence(settings) -> tuple[str, str, str]:
    runbook = "configured" if settings.break_glass_runbook_uri.strip() else "missing"
    alerting = "configured" if settings.break_glass_alerting_evidence.strip() else "missing"
    return runbook, alerting, "deployment_only"


def _break_glass_response(row: KeycloakBreakGlassStatus, *, checked_at: datetime, settings) -> BreakGlassStatusResponse:
    runbook_evidence, alerting_evidence, lifecycle_control = _break_glass_deployment_evidence(settings)
    status = row.status
    detail_code = row.detail_code
    if status == "configured_disabled" and (runbook_evidence == "missing" or alerting_evidence == "missing"):
        status = "attention_required"
        detail_code = "deployment_evidence_missing"
    return BreakGlassStatusResponse(
        username=row.username,
        status=status,  # type: ignore[arg-type]
        detail_code=detail_code,
        configured=row.configured,
        enabled=row.enabled,
        local_account=row.local_account,
        system_admin_mapped=row.system_admin_mapped,
        credential_update_required=row.credential_update_required,
        required_actions=list(row.required_actions),
        credential_source=row.credential_source,
        runbook_evidence=runbook_evidence,
        alerting_evidence=alerting_evidence,
        lifecycle_control=lifecycle_control,
        checked_at=checked_at,
    )


def _rows_to_payload(rows: list[SystemParameter]) -> SystemParametersPayload:
    values = {row.key: row.value for row in rows}
    return SystemParametersPayload(
        max_upload_size_mb=int(values["max_upload_size_mb"]),
        default_timezone=str(values["default_timezone"]),
        staging_index_ttl_days=int(values["staging_index_ttl_days"]),
        session_expired_form_draft_ttl_minutes=int(values.get("session_expired_form_draft_ttl_minutes", 30)),
    )


@router.get("/parameters", response_model=SystemParametersPayload)
def get_parameters(
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SystemParametersPayload:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    rows = list(session.scalars(select(SystemParameter).order_by(SystemParameter.key)))
    return _rows_to_payload(rows)


@router.get("/upload-config", response_model=UploadConfigResponse)
def get_upload_config(request: Request, context: IdentityContext = Depends(get_identity_context)) -> UploadConfigResponse:
    return UploadConfigResponse(max_upload_size_mb=request.app.state.settings.max_upload_size_mb)


@router.get("/status", response_model=OperationsStatusResponse)
def get_status(
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> OperationsStatusResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    return build_operations_status(session, request.app.state.settings)


@router.get("/break-glass/status", response_model=BreakGlassStatusResponse)
def get_break_glass_status(
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> BreakGlassStatusResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    settings = request.app.state.settings
    checked_at = datetime.now(UTC)
    username = settings.break_glass_username.strip()
    runbook_evidence, alerting_evidence, lifecycle_control = _break_glass_deployment_evidence(settings)
    if not username:
        response = BreakGlassStatusResponse(
            username=None,
            status="not_configured",
            detail_code="username_missing",
            configured=False,
            enabled=None,
            local_account=None,
            system_admin_mapped=None,
            credential_update_required=None,
            required_actions=[],
            credential_source="deployment_secret",
            runbook_evidence=runbook_evidence,
            alerting_evidence=alerting_evidence,
            lifecycle_control=lifecycle_control,
            checked_at=checked_at,
        )
        add_audit(session, actor_user_id=context.user_id, action="system.break_glass.status", resource_type="break_glass", resource_id=None, result="failure", request_id=request.state.request_id, summary={"detail_code": response.detail_code})
        session.commit()
        return response
    if not settings.keycloak_sync_client_secret.get_secret_value():
        response = BreakGlassStatusResponse(
            username=username,
            status="unavailable",
            detail_code="keycloak_service_account_secret_missing",
            configured=False,
            enabled=None,
            local_account=None,
            system_admin_mapped=None,
            credential_update_required=None,
            required_actions=[],
            credential_source="deployment_secret",
            runbook_evidence=runbook_evidence,
            alerting_evidence=alerting_evidence,
            lifecycle_control=lifecycle_control,
            checked_at=checked_at,
        )
        add_audit(session, actor_user_id=context.user_id, action="system.break_glass.status", resource_type="break_glass", resource_id=None, result="failure", request_id=request.state.request_id, summary={"detail_code": response.detail_code})
        session.commit()
        return response
    try:
        client = KeycloakAdminClient(
            base_url=settings.keycloak_admin_endpoint,
            realm=_keycloak_realm(settings.oidc_issuer_url),
            client_id=settings.keycloak_sync_client_id,
            client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
        )
        response = _break_glass_response(
            client.break_glass_status(username, system_admin_group=settings.break_glass_system_admin_group),
            checked_at=checked_at,
            settings=settings,
        )
        add_audit(session, actor_user_id=context.user_id, action="system.break_glass.status", resource_type="break_glass", resource_id=None, result="success" if response.status == "configured_disabled" else "failure", request_id=request.state.request_id, summary={"status": response.status, "detail_code": response.detail_code})
        session.commit()
        return response
    except AppError as exc:
        response = BreakGlassStatusResponse(
            username=username,
            status="unavailable",
            detail_code=exc.code,
            configured=False,
            enabled=None,
            local_account=None,
            system_admin_mapped=None,
            credential_update_required=None,
            required_actions=[],
            credential_source="deployment_secret",
            runbook_evidence=runbook_evidence,
            alerting_evidence=alerting_evidence,
            lifecycle_control=lifecycle_control,
            checked_at=checked_at,
        )
        add_audit(session, actor_user_id=context.user_id, action="system.break_glass.status", resource_type="break_glass", resource_id=None, result="failure", request_id=request.state.request_id, summary={"detail_code": response.detail_code})
        session.commit()
        return response


@router.put("/parameters", response_model=SystemParametersPayload)
def update_parameters(
    payload: SystemParametersPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SystemParametersPayload:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    validated = SystemParameterValues(**payload.model_dump()).validate()
    rows = {row.key: row for row in session.scalars(select(SystemParameter).with_for_update())}
    old_values = {key: row.value for key, row in rows.items()}
    for key, value in payload.model_dump().items():
        if key not in rows:
            rows[key] = SystemParameter(key=key, value=value, default_value=value, value_type="integer", unit="minutes", description="Session-expired form draft retention")
            session.add(rows[key])
        rows[key].value = value
        rows[key].updated_by = context.user_id
    add_audit(session, actor_user_id=context.user_id, action="system.parameters.update", resource_type="system_parameters", resource_id=None, result="success", request_id=request.state.request_id, summary={"old": old_values, "new": payload.model_dump()})
    session.commit()
    return SystemParametersPayload(**validated.__dict__)
