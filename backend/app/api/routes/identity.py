from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import ExternalGroupResponse, ExternalGroupRoleMappingResponse, IdentitySyncRunPage, IdentitySyncRunResponse
from app.core.cursor import cursor_filter_hash, decode_cursor, encode_cursor
from app.core.errors import AppError
from app.db.models import ExternalGroup, ExternalGroupRoleMapping, ExternalGroupUser, IdentitySyncRun
from app.db.session import get_db
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.services.identity_sync_jobs import (
    active_identity_run,
    create_identity_sync_run,
    effective_identity_sync_scope,
    identity_runtime_status,
    recover_stale_identity_runs,
)


router = APIRouter(tags=["identity"])


@router.post("/identity-sync/run", response_model=IdentitySyncRunResponse, status_code=202)
def queue_identity_sync(
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IdentitySyncRun:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    settings = request.app.state.settings
    recovered = recover_stale_identity_runs(session, settings, request_id=request.state.request_id)
    if recovered:
        session.commit()
    if not identity_runtime_status(settings)["worker_available"]:
        raise AppError(
            "identity_sync_worker_unavailable",
            "Background identity synchronization service is unavailable",
            status_code=503,
        )
    try:
        run = create_identity_sync_run(
            session,
            trigger_type="manual",
            actor_user_id=context.user_id,
            request_id=request.state.request_id,
            requested_scope=effective_identity_sync_scope(session, settings),
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        active = active_identity_run(session)
        raise AppError(
            "identity_sync_already_running",
            "Identity synchronization is already queued or running",
            status_code=409,
            details={"run_id": str(active.id) if active else None, "status": active.status if active else "active"},
        ) from exc
    session.refresh(run)
    return run


@router.get("/identity-sync/runs", response_model=IdentitySyncRunPage)
def list_identity_sync_runs(
    request: Request,
    status: str | None = Query(default=None, max_length=32),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IdentitySyncRunPage:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    filter_hash = cursor_filter_hash({"status": status})
    statement = select(IdentitySyncRun).options(selectinload(IdentitySyncRun.provider_results))
    if status:
        statement = statement.where(IdentitySyncRun.status == status)
    if cursor:
        payload = decode_cursor(request.app.state.settings, namespace="identity-sync-runs", value=cursor)
        if payload.get("filter") != filter_hash:
            raise AppError("cursor_scope_mismatch", "Cursor does not match the current identity sync filters", status_code=422)
        try:
            cursor_time = datetime.fromisoformat(str(payload["queued_at"]))
            cursor_id = UUID(str(payload["id"]))
        except (KeyError, ValueError) as exc:
            raise AppError("cursor_invalid", "Cursor is invalid or no longer applies", status_code=422) from exc
        statement = statement.where(
            or_(
                IdentitySyncRun.queued_at < cursor_time,
                (IdentitySyncRun.queued_at == cursor_time) & (IdentitySyncRun.id < cursor_id),
            )
        )
    rows = list(session.scalars(statement.order_by(IdentitySyncRun.queued_at.desc(), IdentitySyncRun.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            request.app.state.settings,
            namespace="identity-sync-runs",
            payload={"filter": filter_hash, "queued_at": last.queued_at.isoformat(), "id": str(last.id)},
        )
    return IdentitySyncRunPage(items=rows, next_cursor=next_cursor)


@router.get("/identity-sync/runs/{run_id}", response_model=IdentitySyncRunResponse)
def get_identity_sync_run(
    run_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> IdentitySyncRun:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    run = session.scalar(
        select(IdentitySyncRun)
        .options(selectinload(IdentitySyncRun.provider_results))
        .where(IdentitySyncRun.id == run_id)
    )
    if run is None:
        raise AppError("identity_sync_run_not_found", "Identity synchronization run was not found", status_code=404)
    return run


@router.get("/external-groups", response_model=list[ExternalGroupResponse])
def list_external_groups(
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[ExternalGroupResponse]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    member_counts = (
        select(ExternalGroupUser.external_group_id, func.count(ExternalGroupUser.user_id).label("member_count"))
        .group_by(ExternalGroupUser.external_group_id)
        .subquery()
    )
    rows = session.execute(
        select(
            ExternalGroup,
            func.coalesce(member_counts.c.member_count, 0),
            ExternalGroupRoleMapping.role_id,
        )
        .outerjoin(member_counts, member_counts.c.external_group_id == ExternalGroup.id)
        .outerjoin(ExternalGroupRoleMapping, ExternalGroupRoleMapping.external_group_id == ExternalGroup.id)
        .order_by(ExternalGroup.path, ExternalGroup.group_name)
    )
    return [
        ExternalGroupResponse.model_validate(
            {
                **ExternalGroupResponse.model_validate(group).model_dump(),
                "member_count": int(member_count),
                "mapped_role_id": mapped_role_id,
            }
        )
        for group, member_count, mapped_role_id in rows
    ]


@router.get("/external-group-role-mappings", response_model=list[ExternalGroupRoleMappingResponse])
def list_external_group_role_mappings(
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[ExternalGroupRoleMappingResponse]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    rows = list(session.scalars(select(ExternalGroupRoleMapping).order_by(ExternalGroupRoleMapping.external_group_id, ExternalGroupRoleMapping.role_id)))
    return [ExternalGroupRoleMappingResponse(external_group_id=row.external_group_id, role_id=row.role_id) for row in rows]
