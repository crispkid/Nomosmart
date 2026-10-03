from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    IntegrationClientCreatePayload,
    IntegrationClientCreateResponse,
    IntegrationClientLifecyclePayload,
    IntegrationClientPage,
    IntegrationClientProjectScopesPayload,
    IntegrationClientResponse,
    IntegrationClientUpdatePayload,
    IntegrationClientUsageItem,
    IntegrationClientUsageSummary,
)
from app.core.errors import AppError
from app.core.cursor import cursor_filter_hash, decode_cursor, encode_cursor
from app.db.models import IntegrationClient, IntegrationClientProjectScope, Project, PublicApiRequestLog
from app.db.session import get_db
from app.domain.integration_api_keys import generate_api_key
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.services.audit import add_audit


router = APIRouter(prefix="/integration-clients", tags=["integration-clients"])


@router.get("", response_model=IntegrationClientPage)
def list_integration_clients(
    request: Request,
    status: str | None = Query(default=None, max_length=32),
    project_id: UUID | None = None,
    name: str | None = Query(default=None, max_length=255),
    expiry: str | None = Query(default=None, pattern=r"^(valid|expired|expiring_30d)$"),
    cursor: str | None = Query(default=None, max_length=2000),
    limit: int = Query(default=50, ge=1, le=100),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IntegrationClientPage:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    filters = {"status": status, "project_id": str(project_id) if project_id else None, "name": name, "expiry": expiry}
    filter_hash = cursor_filter_hash(filters)
    statement = select(IntegrationClient)
    if project_id is not None:
        statement = statement.join(IntegrationClientProjectScope).where(IntegrationClientProjectScope.project_id == project_id)
    if status:
        statement = statement.where(IntegrationClient.status == status)
    if name and name.strip():
        escaped = name.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(IntegrationClient.name.ilike(f"%{escaped}%", escape="\\"))
    now = datetime.now(UTC)
    if expiry == "expired":
        statement = statement.where(IntegrationClient.expires_at.is_not(None), IntegrationClient.expires_at <= now)
    elif expiry == "valid":
        statement = statement.where(or_(IntegrationClient.expires_at.is_(None), IntegrationClient.expires_at > now))
    elif expiry == "expiring_30d":
        statement = statement.where(IntegrationClient.expires_at > now, IntegrationClient.expires_at <= now + timedelta(days=30))
    if cursor:
        decoded = decode_cursor(request.app.state.settings, namespace="integration-clients", value=cursor)
        if decoded.get("filters") != filter_hash:
            raise AppError("cursor_filter_conflict", "Cursor does not match the requested filters", status_code=422)
        try:
            created_at = datetime.fromisoformat(str(decoded["created_at"]))
            cursor_id = UUID(str(decoded["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                IntegrationClient.created_at < created_at,
                and_(IntegrationClient.created_at == created_at, IntegrationClient.id < cursor_id),
            )
        )
    clients = list(session.scalars(statement.order_by(IntegrationClient.created_at.desc(), IntegrationClient.id.desc()).limit(limit + 1)))
    has_more = len(clients) > limit
    clients = clients[:limit]
    next_cursor = None
    if has_more and clients:
        last = clients[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="integration-clients",
            payload={"created_at": last.created_at.isoformat(), "id": str(last.id), "filters": filter_hash},
        )
    return IntegrationClientPage(items=[_client_response(session, client) for client in clients], next_cursor=next_cursor, has_more=has_more)


@router.post("", response_model=IntegrationClientCreateResponse, status_code=201)
def create_integration_client(
    payload: IntegrationClientCreatePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IntegrationClientCreateResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.CREATE)
    project_ids = _validate_project_ids(session, payload.project_ids)
    token, token_hash, token_prefix = generate_api_key()
    now = datetime.now(UTC)
    _validate_lifecycle(payload.valid_from, payload.expires_at)
    client = IntegrationClient(
        name=payload.name.strip(),
        description=_clean_optional(payload.description),
        status="active",
        api_key_hash=token_hash,
        api_key_prefix=token_prefix,
        api_key_version=1,
        contact_name=_clean_optional(payload.contact_name),
        contact_email=_clean_optional(payload.contact_email),
        contact_department=_clean_optional(payload.contact_department),
        valid_from=payload.valid_from,
        expires_at=payload.expires_at,
        rate_limit_config=_rate_limit_config(payload.requests_per_minute),
        created_by=context.user_id,
        updated_by=context.user_id,
        lock_version=1,
    )
    session.add(client)
    session.flush()
    _replace_project_scopes(session, client.id, project_ids, context.user_id)
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="integration_client.create",
        resource_type="integration_client",
        resource_id=client.id,
        result="success",
        request_id=request.state.request_id,
        summary={"project_ids": [str(project_id) for project_id in project_ids], "api_key_prefix": token_prefix},
    )
    session.commit()
    session.refresh(client)
    response = _client_response(session, client).model_dump()
    return IntegrationClientCreateResponse(**response, api_key=token)


@router.get("/{client_id}", response_model=IntegrationClientResponse)
def get_integration_client(client_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> IntegrationClientResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    return _client_response(session, _get_client(session, client_id))


@router.put("/{client_id}", response_model=IntegrationClientResponse)
def update_integration_client(
    client_id: UUID,
    payload: IntegrationClientUpdatePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IntegrationClientResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    client = _get_client(session, client_id, for_update=True)
    _assert_lock(client, payload.lock_version)
    if client.status == "revoked":
        raise AppError("integration_client_revoked", "Revoked API keys cannot be edited", status_code=409)
    next_valid_from = payload.valid_from if "valid_from" in payload.model_fields_set else client.valid_from
    next_expires_at = payload.expires_at if "expires_at" in payload.model_fields_set else client.expires_at
    _validate_lifecycle(next_valid_from, next_expires_at)
    if payload.name is not None:
        client.name = payload.name.strip()
    if "description" in payload.model_fields_set:
        client.description = _clean_optional(payload.description)
    if "contact_name" in payload.model_fields_set:
        client.contact_name = _clean_optional(payload.contact_name)
    if "contact_email" in payload.model_fields_set:
        client.contact_email = _clean_optional(payload.contact_email)
    if "contact_department" in payload.model_fields_set:
        client.contact_department = _clean_optional(payload.contact_department)
    if "valid_from" in payload.model_fields_set:
        client.valid_from = payload.valid_from
    if "expires_at" in payload.model_fields_set:
        client.expires_at = payload.expires_at
    if payload.requests_per_minute is not None:
        client.rate_limit_config = _rate_limit_config(payload.requests_per_minute)
    client.updated_by = context.user_id
    client.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action="integration_client.update", resource_type="integration_client", resource_id=client.id, result="success", request_id=request.state.request_id)
    session.commit()
    session.refresh(client)
    return _client_response(session, client)


@router.put("/{client_id}/project-scopes", response_model=IntegrationClientResponse)
def replace_integration_client_project_scopes(
    client_id: UUID,
    payload: IntegrationClientProjectScopesPayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IntegrationClientResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    client = _get_client(session, client_id, for_update=True)
    _assert_lock(client, payload.lock_version)
    if client.status == "revoked":
        raise AppError("integration_client_revoked", "Revoked API keys cannot be edited", status_code=409)
    project_ids = _validate_project_ids(session, payload.project_ids)
    _replace_project_scopes(session, client.id, project_ids, context.user_id)
    client.updated_by = context.user_id
    client.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action="integration_client.project_scopes.replace", resource_type="integration_client", resource_id=client.id, result="success", request_id=request.state.request_id, summary={"project_ids": [str(project_id) for project_id in project_ids]})
    session.commit()
    session.refresh(client)
    return _client_response(session, client)


@router.post("/{client_id}/keys/rotate", response_model=IntegrationClientCreateResponse)
def rotate_integration_client_key(
    client_id: UUID,
    payload: IntegrationClientLifecyclePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IntegrationClientCreateResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    client = _get_client(session, client_id, for_update=True)
    _assert_lock(client, payload.lock_version)
    if client.status == "revoked":
        raise AppError("integration_client_revoked", "Revoked API keys cannot be rotated", status_code=409)
    token, token_hash, token_prefix = generate_api_key()
    client.api_key_hash = token_hash
    client.api_key_prefix = token_prefix
    client.api_key_version += 1
    client.updated_by = context.user_id
    client.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action="integration_client.key.rotate", resource_type="integration_client", resource_id=client.id, result="success", request_id=request.state.request_id, summary={"api_key_prefix": token_prefix, "reason": payload.reason})
    session.commit()
    session.refresh(client)
    response = _client_response(session, client).model_dump()
    return IntegrationClientCreateResponse(**response, api_key=token)


@router.post("/{client_id}/activate", response_model=IntegrationClientResponse)
def activate_integration_client(
    client_id: UUID,
    payload: IntegrationClientLifecyclePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IntegrationClientResponse:
    return _set_client_status(client_id, "active", payload, request, context, session)


@router.post("/{client_id}/deactivate", response_model=IntegrationClientResponse)
def deactivate_integration_client(
    client_id: UUID,
    payload: IntegrationClientLifecyclePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IntegrationClientResponse:
    return _set_client_status(client_id, "inactive", payload, request, context, session)


@router.post("/{client_id}/revoke", response_model=IntegrationClientResponse)
def revoke_integration_client(
    client_id: UUID,
    payload: IntegrationClientLifecyclePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IntegrationClientResponse:
    return _set_client_status(client_id, "revoked", payload, request, context, session, required_action=PermissionAction.DELETE)


@router.delete("/{client_id}", response_model=IntegrationClientResponse)
def delete_integration_client(
    client_id: UUID,
    request: Request,
    lock_version: int = Query(ge=1),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IntegrationClientResponse:
    payload = IntegrationClientLifecyclePayload(lock_version=lock_version, reason="delete")
    return _set_client_status(client_id, "revoked", payload, request, context, session, required_action=PermissionAction.DELETE)


@router.get("/{client_id}/usage-summary", response_model=IntegrationClientUsageSummary)
def get_integration_client_usage_summary(client_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> IntegrationClientUsageSummary:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    client = _get_client(session, client_id)
    rows = list(session.scalars(select(PublicApiRequestLog).where(PublicApiRequestLog.integration_client_id == client.id).order_by(PublicApiRequestLog.created_at.desc()).limit(20)))
    return IntegrationClientUsageSummary(
        client_id=client.id,
        success_count=client.success_count,
        failure_count=client.failure_count,
        last_used_at=client.last_used_at,
        recent_requests=[
            IntegrationClientUsageItem(
                id=row.id,
                project_id=row.project_id,
                result=row.result,
                http_status=row.http_status,
                response_mode=row.response_mode,
                end_user_employee_id=row.end_user_employee_id,
                retrieval_status=row.retrieval_status,
                latency_ms=row.latency_ms,
                error_code=row.error_code,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


def _set_client_status(
    client_id: UUID,
    status: str,
    payload: IntegrationClientLifecyclePayload,
    request: Request,
    context: IdentityContext,
    session: Session,
    *,
    required_action: PermissionAction = PermissionAction.EDIT,
) -> IntegrationClientResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, required_action)
    client = _get_client(session, client_id, for_update=True)
    _assert_lock(client, payload.lock_version)
    now = datetime.now(UTC)
    if client.status == "revoked" and status != "revoked":
        raise AppError("integration_client_revoked", "Revoked API keys cannot be reactivated", status_code=409)
    if status == "active" and client.expires_at is not None and client.expires_at <= now:
        raise AppError("integration_client_expired", "Expired API keys cannot be activated until expiry is extended", status_code=409)
    client.status = status
    if status == "revoked":
        client.revoked_at = client.revoked_at or now
        client.revoked_by = context.user_id
        client.revocation_reason = _clean_optional(payload.reason)
    client.updated_by = context.user_id
    client.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action=f"integration_client.{status}", resource_type="integration_client", resource_id=client.id, result="success", request_id=getattr(request.state, "request_id", None), summary={"reason": payload.reason})
    session.commit()
    session.refresh(client)
    return _client_response(session, client)


def _get_client(session: Session, client_id: UUID, *, for_update: bool = False) -> IntegrationClient:
    statement = select(IntegrationClient).where(IntegrationClient.id == client_id)
    if for_update:
        statement = statement.with_for_update()
    client = session.scalar(statement)
    if client is None:
        raise AppError("integration_client_not_found", "Integration client was not found", status_code=404)
    return client


def _client_response(session: Session, client: IntegrationClient) -> IntegrationClientResponse:
    project_ids = list(session.scalars(select(IntegrationClientProjectScope.project_id).where(IntegrationClientProjectScope.client_id == client.id).order_by(IntegrationClientProjectScope.created_at)))
    requests_per_minute = client.rate_limit_config.get("requests_per_minute") if isinstance(client.rate_limit_config, dict) else None
    return IntegrationClientResponse(
        id=client.id,
        name=client.name,
        description=client.description,
        status=client.status,
        effective_status=_effective_status(client),
        api_key_prefix=client.api_key_prefix,
        api_key_version=client.api_key_version,
        contact_name=client.contact_name,
        contact_email=client.contact_email,
        contact_department=client.contact_department,
        valid_from=client.valid_from,
        expires_at=client.expires_at,
        revoked_at=client.revoked_at,
        revocation_reason=client.revocation_reason,
        requests_per_minute=int(requests_per_minute) if requests_per_minute is not None else None,
        project_ids=project_ids,
        last_used_at=client.last_used_at,
        last_used_project_id=client.last_used_project_id,
        success_count=client.success_count,
        failure_count=client.failure_count,
        lock_version=client.lock_version,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


def _effective_status(client: IntegrationClient) -> str:
    now = datetime.now(UTC)
    if client.status == "revoked":
        return "revoked"
    if client.expires_at is not None and client.expires_at <= now:
        return "expired"
    if client.valid_from is not None and client.valid_from > now:
        return "scheduled"
    return client.status


def _assert_lock(client: IntegrationClient, lock_version: int) -> None:
    if client.lock_version != lock_version:
        raise AppError("stale_lock_version", "The record was updated by another request", status_code=409)


def _validate_project_ids(session: Session, project_ids: list[UUID]) -> list[UUID]:
    unique_ids = list(dict.fromkeys(project_ids))
    if not unique_ids:
        raise AppError("integration_client_project_scope_required", "At least one project scope is required", status_code=422)
    projects = list(session.scalars(select(Project).where(Project.id.in_(unique_ids), Project.status == "active")))
    if {project.id for project in projects} != set(unique_ids):
        raise AppError("integration_client_project_scope_invalid", "Project scope contains unavailable projects", status_code=422)
    return unique_ids


def _replace_project_scopes(session: Session, client_id: UUID, project_ids: list[UUID], actor_user_id: UUID | None) -> None:
    session.execute(delete(IntegrationClientProjectScope).where(IntegrationClientProjectScope.client_id == client_id))
    now = datetime.now(UTC)
    for project_id in project_ids:
        session.add(IntegrationClientProjectScope(client_id=client_id, project_id=project_id, created_by=actor_user_id, created_at=now))


def _validate_lifecycle(valid_from: datetime | None, expires_at: datetime | None) -> None:
    if valid_from is not None and expires_at is not None and expires_at <= valid_from:
        raise AppError("integration_client_invalid_lifecycle", "Expiry must be after the valid-from time", status_code=422)


def _rate_limit_config(requests_per_minute: int | None) -> dict[str, int]:
    return {"requests_per_minute": int(requests_per_minute or 60)}


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
