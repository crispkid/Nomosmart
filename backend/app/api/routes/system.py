import json

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import BreakGlassStatusResponse, OperationsStatusResponse, SystemParametersPayload, SystemParametersUpdatePayload, UploadConfigResponse
from app.core.errors import AppError
from app.db.models import AuthEmergencyAccess, Role, RoleUser, SystemParameter
from app.db.session import get_db
from app.domain import system_parameter_store as store
from pydantic import ValidationError
from app.domain.ocr_token_settings import (NativeOCRTokenSettings, NATIVE_KEYS as OCR_KEYS,
    legacy_page_from_rows, PAGE_KEY, REQUEST_KEY, DOCUMENT_KEY, NATIVE_POLICY)
from app.domain.operations import build_operations_status
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.services.audit import add_audit


router = APIRouter(prefix="/system", tags=["system"])


def _payload(session, settings):
    values, defaults, revisions, metadata, _, _ = store.snapshot(session)
    tokens = NativeOCRTokenSettings(values[OCR_KEYS[0]], values[OCR_KEYS[1]])
    legacy_rows = list(session.scalars(select(SystemParameter).where(SystemParameter.key == PAGE_KEY)))
    legacy_value = legacy_page_from_rows(legacy_rows)
    legacy_default = legacy_page_from_rows(legacy_rows, defaults=True)
    return SystemParametersPayload(**values, ocr_page_max_output_tokens=legacy_value,
        ocr_token_budget_policy=NATIVE_POLICY,
        ocr_token_defaults={PAGE_KEY: legacy_default, **{key: defaults[key] for key in OCR_KEYS}},
        ocr_token_settings_hash=tokens.content_hash, section_revisions=revisions,
        parameter_defaults=defaults, parameter_metadata=metadata,
        deployment_max_upload_size_mb=settings.max_upload_size_mb)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AppError("invalid_system_parameters", "Duplicate JSON field", status_code=422)
        result[key] = value
    return result


async def _body(request):
    try:
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 16384:
                raise ValueError()
            raw.extend(chunk)
        value = json.loads(raw, object_pairs_hook=_unique_pairs)
        if type(value) is not dict:
            raise ValueError()
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise AppError("invalid_system_parameters", "Invalid settings payload", status_code=422)


@router.get("/parameters", response_model=SystemParametersPayload)
def get_parameters(request: Request, context: IdentityContext = Depends(get_identity_context),
                   session: Session = Depends(get_db)) -> SystemParametersPayload:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    return _payload(session, request.app.state.settings)


@router.patch("/parameters")
async def patch_parameters(request: Request, context: IdentityContext = Depends(get_identity_context),
                           session: Session = Depends(get_db)):
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    body = await _body(request)
    if "expected_revision" not in body:
        raise AppError("system_parameters_revision_required", "Reload settings before saving", status_code=428)
    section, values, expected = body.get("section"), body.get("values"), body.get("expected_revision")
    if (set(body) != {"section", "expected_revision", "values"} or not isinstance(section, str)
        or section not in store.SECTIONS or type(values) is not dict or not isinstance(expected, str)
        or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected)):
        raise AppError("invalid_system_parameters", "Invalid section update", status_code=422)
    return await run_in_threadpool(_patch_transaction, section, values, expected, request, context, session)


def _patch_transaction(section, values, expected, request, context, session):
    changed = store.update_sections(session, changes={section: values}, expected={section: expected},
        actor=context.user_id, request_id=request.state.request_id,
        deployment_limit=request.app.state.settings.max_upload_size_mb)
    data, defaults, revisions, metadata, _, _ = store.snapshot(session, [section])
    response = {"section": section, "values": data, "defaults": defaults,
                "revision": revisions[section], "parameter_metadata": metadata, "changed": changed}
    session.commit()
    return response


@router.get("/upload-config", response_model=UploadConfigResponse)
def get_upload_config(request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> UploadConfigResponse:
    effective = store.intake_settings(session, request.app.state.settings)
    return UploadConfigResponse(max_upload_size_mb=effective.max_upload_size_mb, deployment_max_upload_size_mb=request.app.state.settings.max_upload_size_mb)


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
async def update_parameters(request: Request, context: IdentityContext = Depends(get_identity_context),
                            session: Session = Depends(get_db)) -> SystemParametersPayload:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    body = await _body(request)
    expected = body.get("expected_section_revisions")
    if not isinstance(expected, dict) or set(expected) != set(store.SECTIONS):
        raise AppError("system_parameters_revision_required", "Reload settings before saving", status_code=428)
    try:
        payload = SystemParametersUpdatePayload.model_validate(body)
    except ValidationError as exc:
        raise AppError("invalid_system_parameters", "Invalid settings values", status_code=422,
                       details={"fields": [str(error["loc"][0]) for error in exc.errors()]}) from exc
    values = payload.model_dump(exclude_unset=True)
    ocr_changed = any(key in values for key in OCR_KEYS)
    if ocr_changed and not payload.expected_ocr_token_settings_hash:
        raise AppError("system_parameters_revision_required", "Reload OCR settings before saving", status_code=428)
    return await run_in_threadpool(_put_transaction, values, expected, payload, ocr_changed, request, context, session)


def _put_transaction(values, expected, payload, ocr_changed, request, context, session):
    if PAGE_KEY in values:
        legacy_rows = list(session.scalars(select(SystemParameter).where(SystemParameter.key == PAGE_KEY)))
        if values[PAGE_KEY] != legacy_page_from_rows(legacy_rows):
            raise AppError("ocr_page_token_setting_retired", "Per-page OCR output setting is retired; use the request output setting", status_code=422)
    store.update_sections(session, changes={section: {key: values[key] for key in keys if key in values}
        for section, keys in store.SECTIONS.items()}, expected=expected, actor=context.user_id,
        request_id=request.state.request_id, deployment_limit=request.app.state.settings.max_upload_size_mb,
        ocr_hash=payload.expected_ocr_token_settings_hash if ocr_changed else None)
    result = _payload(session, request.app.state.settings)
    session.commit()
    return result
