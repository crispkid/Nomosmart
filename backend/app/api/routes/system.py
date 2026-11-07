from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import BreakGlassStatusResponse, OperationsStatusResponse, SystemParametersPayload, SystemParametersUpdatePayload, UploadConfigResponse
from app.core.errors import AppError
from app.db.models import AuthEmergencyAccess, Role, RoleUser, SystemParameter
from app.db.session import get_db
from app.domain.system_parameters import SystemParameterValues
from app.domain.ocr_token_settings import (native_from_rows, legacy_page_from_rows, NativeOCRTokenSettings,
    NATIVE_KEYS as OCR_KEYS, PAGE_KEY, REQUEST_KEY, DOCUMENT_KEY, NATIVE_POLICY)
from app.domain.operations import build_operations_status
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.services.audit import add_audit


router = APIRouter(prefix="/system", tags=["system"])


def _rows_to_payload(rows: list[SystemParameter]) -> SystemParametersPayload:
    values = {row.key: row.value for row in rows}
    tokens, defaults = native_from_rows(rows), native_from_rows(rows, defaults=True)
    return SystemParametersPayload(
        ocr_page_max_output_tokens=legacy_page_from_rows(rows),
        ocr_request_max_output_tokens=tokens.request,
        ocr_token_budget_policy=NATIVE_POLICY,
        ocr_document_max_tokens=tokens.document,
        ocr_token_defaults={PAGE_KEY: legacy_page_from_rows(rows, defaults=True), REQUEST_KEY: defaults.request, DOCUMENT_KEY: defaults.document},
        ocr_token_settings_hash=tokens.content_hash,
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
    now = datetime.now(UTC)
    settings = request.app.state.settings
    row = session.scalar(select(AuthEmergencyAccess).where(AuthEmergencyAccess.username == settings.auth_emergency_username))
    configured = bool(row and row.password_verifier)
    enabled = bool(configured and row.active_until and row.active_until > now)
    mapped = bool(row and session.scalar(select(RoleUser.user_id).join(Role, Role.id == RoleUser.role_id).where(RoleUser.user_id == row.user_id, Role.name == "system-admin", RoleUser.source == "break_glass")))
    status = "attention_required" if enabled else "configured_disabled" if configured else "not_configured"
    return BreakGlassStatusResponse(username=settings.auth_emergency_username, status=status, detail_code="temporary_emergency_window" if enabled else "deployment_activation_required", configured=configured, enabled=enabled, local_account=True, system_admin_mapped=mapped, credential_update_required=False, required_actions=[], credential_source="deployment_secret", runbook_evidence="configured" if settings.break_glass_runbook_uri else "missing", alerting_evidence="configured", lifecycle_control="deployment_only", checked_at=now)


@router.put("/parameters", response_model=SystemParametersPayload)
def update_parameters(
    payload: SystemParametersUpdatePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SystemParametersPayload:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    core = payload.model_dump(exclude=set(OCR_KEYS) | {PAGE_KEY, "expected_ocr_token_settings_hash"})
    SystemParameterValues(**core).validate()
    rows = {row.key: row for row in session.scalars(select(SystemParameter).order_by(SystemParameter.key).with_for_update())}
    current = native_from_rows(list(rows.values()))
    native_from_rows(list(rows.values()), defaults=True)
    submitted = payload.model_dump(exclude_unset=True)
    if PAGE_KEY in submitted and submitted[PAGE_KEY] != legacy_page_from_rows(list(rows.values())):
        raise AppError("ocr_page_token_setting_retired", "Per-page OCR output setting is retired; use the request output setting", status_code=422)
    changed_ocr = set(submitted) & set(OCR_KEYS)
    if changed_ocr and payload.expected_ocr_token_settings_hash != current.content_hash:
        raise AppError("ocr_token_settings_conflict", "OCR output settings changed; reload before saving", status_code=409)
    NativeOCRTokenSettings(submitted.get(REQUEST_KEY, current.request), submitted.get(DOCUMENT_KEY, current.document))
    values = core | {key: submitted[key] for key in changed_ocr}
    old_values = {key: rows[key].value for key in values if key in rows}
    for key, value in values.items():
        if key not in rows:
            rows[key] = SystemParameter(key=key, value=value, default_value=value, value_type="integer", unit="minutes", description="Session-expired form draft retention")
            session.add(rows[key])
        rows[key].value = value
        rows[key].updated_by = context.user_id
    add_audit(session, actor_user_id=context.user_id, action="system.parameters.update", resource_type="system_parameters", resource_id=None, result="success", request_id=request.state.request_id, summary={"old": old_values, "new": values})
    session.commit()
    return _rows_to_payload(list(rows.values()))
