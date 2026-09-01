from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.api.schemas import ProjectArchiveImpactResponse, ProjectArchiveRequest, ProjectCreate, ProjectMemberResponse, ProjectMemberUpdate, ProjectResponse, ProjectUpdate
from app.core.errors import AppError
from app.db.models import Document, DocumentVersion, Project, ProjectArchiveRun, ProjectMember, ProjectOwner, Role, RolePermission, RoleUser, User
from app.db.session import get_db
from app.security.context import IdentityContext, get_identity_context
from app.domain.project_access import get_scoped_project as _get_scoped_project, project_capabilities, require_project_owner as _require_project_owner, resolve_project_model as _resolve_model, resolve_project_models as _resolve_models
from app.domain.project_archival import archive_impact, begin_project_archive, retry_project_archive_cleanup
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, MENU_MODULE, PROJECT_ARCHIVE, PROJECT_MODULE, PermissionAction, has_permission, require_menu_permission
from app.services.audit import add_audit


router = APIRouter(prefix="/projects", tags=["projects"])
PROJECT_ROLES = frozenset({"owner", "editor", "viewer"})


def _validate_roles(roles: list[str]) -> set[str]:
    normalized = set(roles)
    if not normalized or not normalized.issubset(PROJECT_ROLES):
        raise AppError("invalid_project_role", "Project roles must be owner, editor, or viewer", status_code=422)
    return normalized


def _users_with_knowledge_project_view(session: Session, user_ids: set[UUID]) -> set[UUID]:
    if not user_ids:
        return set()
    return set(
        session.scalars(
            select(RoleUser.user_id)
            .join(RolePermission, RolePermission.role_id == RoleUser.role_id)
            .join(Role, Role.id == RoleUser.role_id)
            .where(
                RoleUser.user_id.in_(user_ids),
                Role.is_active.is_(True),
                Role.deleted_at.is_(None),
                RolePermission.module_name == MENU_MODULE,
                RolePermission.function_name == MENU_KNOWLEDGE_PROJECTS,
                RolePermission.can_view.is_(True),
            )
        )
    )


def _validate_project_member_candidates(session: Session, user_ids: set[UUID]) -> None:
    if not user_ids:
        return
    active_ids = set(session.scalars(select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True))).all())
    if active_ids != user_ids:
        raise AppError("invalid_project_member", "All project members must be active users", status_code=422)
    visible_menu_ids = _users_with_knowledge_project_view(session, user_ids)
    if visible_menu_ids != user_ids:
        raise AppError("invalid_project_member_permission", "Project members must have Knowledge Projects menu view permission", status_code=422)


def _reject_repeated_singletons(request: Request, names: tuple[str, ...]) -> None:
    repeated = [name for name in names if len(request.query_params.getlist(name)) > 1]
    if repeated:
        raise AppError(
            "repeated_project_query_parameter",
            "Project list singleton query parameters cannot be repeated",
            status_code=422,
            details={"parameters": repeated},
        )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _require_project_archive_authority(session: Session, project_id: UUID, context: IdentityContext) -> tuple[Project, bool]:
    require_menu_permission(list(context.grants), MENU_KNOWLEDGE_PROJECTS, PermissionAction.VIEW)
    if project_id not in context.visible_project_ids:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    project = session.get(Project, project_id)
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    is_owner = session.get(ProjectOwner, (project_id, context.user_id)) is not None
    can_execute = has_permission(
        list(context.grants),
        PROJECT_MODULE,
        PROJECT_ARCHIVE,
        PermissionAction.EXECUTE,
    )
    if not is_owner and not can_execute:
        raise AppError("project_archive_permission_required", "Project archive execute permission is required", status_code=403)
    return project, is_owner


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    request: Request,
    response: Response,
    status: Literal["active", "archived"] = Query(default="active"),
    q: str | None = Query(default=None, max_length=100),
    role: list[Literal["owner", "editor", "viewer"]] | None = Query(default=None),
    model_state: Literal["complete", "incomplete"] | None = Query(default=None),
    sort: Literal["updated_desc", "updated_asc", "name_asc", "name_desc"] = Query(default="updated_desc"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[Project]:
    require_menu_permission(list(context.grants), MENU_KNOWLEDGE_PROJECTS, PermissionAction.VIEW)
    _reject_repeated_singletons(request, ("status", "q", "model_state", "sort", "offset", "limit"))
    if not context.visible_project_ids:
        response.headers["X-Total-Count"] = "0"
        return []

    conditions = [Project.id.in_(context.visible_project_ids), Project.status == status]
    normalized_query = q.strip() if q else ""
    if normalized_query:
        pattern = f"%{_escape_like(normalized_query)}%"
        conditions.append(
            or_(
                Project.name.ilike(pattern, escape="\\"),
                func.coalesce(Project.description, "").ilike(pattern, escape="\\"),
            )
        )
    if role:
        role_conditions = []
        requested_roles = set(role)
        if "owner" in requested_roles:
            role_conditions.append(
                select(ProjectOwner.project_id)
                .where(ProjectOwner.project_id == Project.id, ProjectOwner.user_id == context.user_id)
                .exists()
            )
        member_roles = requested_roles - {"owner"}
        if member_roles:
            role_conditions.append(
                select(ProjectMember.project_id)
                .where(
                    ProjectMember.project_id == Project.id,
                    ProjectMember.user_id == context.user_id,
                    ProjectMember.project_role.in_(member_roles),
                )
                .exists()
            )
        conditions.append(or_(*role_conditions))
    model_complete = Project.llm_model_id.is_not(None) & Project.embedding_model_id.is_not(None) & Project.ocr_model_id.is_not(None)
    if model_state == "complete":
        conditions.append(model_complete)
    elif model_state == "incomplete":
        conditions.append(~model_complete)

    total = session.scalar(select(func.count()).select_from(Project).where(*conditions)) or 0
    response.headers["X-Total-Count"] = str(total)

    current_roles = (
        select(func.array_agg(ProjectMember.project_role))
        .where(ProjectMember.project_id == Project.id, ProjectMember.user_id == context.user_id)
        .correlate(Project)
        .scalar_subquery()
    )
    document_count = (
        select(func.count(Document.id))
        .where(Document.project_id == Project.id, Document.is_deleted.is_(False))
        .correlate(Project)
        .scalar_subquery()
    )
    published_version_count = (
        select(func.count(DocumentVersion.id))
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.project_id == Project.id,
            DocumentVersion.published_at.is_not(None),
            Document.is_deleted.is_(False),
        )
        .correlate(Project)
        .scalar_subquery()
    )
    document_activity = (
        select(func.max(Document.updated_at))
        .where(Document.project_id == Project.id, Document.is_deleted.is_(False))
        .correlate(Project)
        .scalar_subquery()
    )
    version_activity = (
        select(func.max(DocumentVersion.updated_at))
        .where(DocumentVersion.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )
    last_activity = func.greatest(
        Project.updated_at,
        func.coalesce(document_activity, Project.updated_at),
        func.coalesce(version_activity, Project.updated_at),
    )
    archive_cleanup_status = (
        select(ProjectArchiveRun.status)
        .where(ProjectArchiveRun.project_id == Project.id)
        .order_by(ProjectArchiveRun.queued_at.desc(), ProjectArchiveRun.id.desc())
        .limit(1)
        .correlate(Project)
        .scalar_subquery()
    )
    owner_exists = (
        select(ProjectOwner.project_id)
        .where(ProjectOwner.project_id == Project.id, ProjectOwner.user_id == context.user_id)
        .exists()
    )
    order_by = {
        "updated_desc": (last_activity.desc(), Project.id.desc()),
        "updated_asc": (last_activity.asc(), Project.id.asc()),
        "name_asc": (func.lower(Project.name).asc(), Project.id.asc()),
        "name_desc": (func.lower(Project.name).desc(), Project.id.desc()),
    }[sort]
    rows = session.execute(
        select(
            Project,
            current_roles.label("current_user_project_roles"),
            document_count.label("document_count"),
            published_version_count.label("published_version_count"),
            last_activity.label("last_activity_at"),
            archive_cleanup_status.label("archive_cleanup_status"),
            owner_exists.label("is_owner"),
        )
        .where(*conditions)
        .order_by(*order_by)
        .offset(offset)
        .limit(limit)
    ).all()
    projects: list[Project] = []
    for row in rows:
        project = row.Project
        project_roles = set(row.current_user_project_roles or [])
        if row.is_owner:
            project_roles.add("owner")
        project.current_user_project_roles = sorted(project_roles)
        project.document_count = int(row.document_count or 0)
        project.published_version_count = int(row.published_version_count or 0)
        project.last_activity_at = row.last_activity_at
        project.archive_cleanup_status = row.archive_cleanup_status
        project.is_owner = bool(row.is_owner)
        project.capabilities = project_capabilities(session, project, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids))
        projects.append(project)
    return projects


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    payload: ProjectCreate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> Project:
    require_menu_permission(list(context.grants), MENU_KNOWLEDGE_PROJECTS, PermissionAction.CREATE)
    llm_model_id, embedding_model_id, ocr_model_id = _resolve_models(
        session,
        llm_model_id=payload.llm_model_id,
        embedding_model_id=payload.embedding_model_id,
        ocr_model_id=payload.ocr_model_id,
    )
    assignments: dict[UUID, set[str]] = defaultdict(set)
    for member in payload.members:
        assignments[member.user_id].update(_validate_roles(member.roles))
    assignments[context.user_id].add("owner")
    user_ids = set(assignments)
    _validate_project_member_candidates(session, user_ids)

    now = datetime.now(UTC)
    project = Project(name=payload.name, description=payload.description, llm_model_id=llm_model_id, embedding_model_id=embedding_model_id, ocr_model_id=ocr_model_id, status="active", created_by=context.user_id, lock_version=1, created_at=now, updated_at=now)
    session.add(project)
    session.flush()
    for user_id, roles in assignments.items():
        for role in roles:
            session.add(ProjectMember(project_id=project.id, user_id=user_id, project_role=role, created_at=now))
        if "owner" in roles:
            session.add(ProjectOwner(project_id=project.id, user_id=user_id, created_at=now))
    add_audit(session, actor_user_id=context.user_id, action="project.create", resource_type="project", resource_id=project.id, result="success", request_id=request.state.request_id, summary={"name": project.name, "member_count": len(assignments)})
    session.commit()
    session.refresh(project)
    project.capabilities = project_capabilities(session, project, user_id=context.user_id, visible_project_ids={project.id})
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> Project:
    project = _get_scoped_project(session, project_id, context)
    project.capabilities = project_capabilities(session, project, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids))
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: UUID, payload: ProjectUpdate, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> Project:
    project = _get_scoped_project(session, project_id, context)
    _require_project_owner(session, project_id, context.user_id)
    if project.lock_version != payload.lock_version:
        raise AppError("stale_project_version", "Project was changed by another request", status_code=409)
    changes = payload.model_dump(exclude_unset=True, exclude={"lock_version"})
    model_fields = {"llm_model_id", "embedding_model_id", "ocr_model_id"}
    if model_fields.intersection(changes):
        llm_model_id, embedding_model_id, ocr_model_id = _resolve_models(
            session,
            llm_model_id=changes.get("llm_model_id", project.llm_model_id),
            embedding_model_id=changes.get("embedding_model_id", project.embedding_model_id),
            ocr_model_id=changes.get("ocr_model_id", project.ocr_model_id),
        )
        resolved_ids = {
            "llm_model_id": llm_model_id,
            "embedding_model_id": embedding_model_id,
            "ocr_model_id": ocr_model_id,
        }
        for field in model_fields.intersection(changes):
            changes[field] = resolved_ids[field]
    for field, value in changes.items():
        setattr(project, field, value)
    project.lock_version += 1
    project.updated_at = datetime.now(UTC)
    add_audit(session, actor_user_id=context.user_id, action="project.update", resource_type="project", resource_id=project.id, result="success", request_id=request.state.request_id, summary={"fields": sorted(changes)})
    session.commit()
    session.refresh(project)
    project.capabilities = project_capabilities(session, project, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids))
    return project


@router.get("/{project_id}/archive-impact", response_model=ProjectArchiveImpactResponse)
def get_project_archive_impact(project_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ProjectArchiveImpactResponse:
    project, _ = _require_project_archive_authority(session, project_id, context)
    if project.status != "active":
        raise AppError("project_archived", "Archived projects cannot be archived again", status_code=409)
    return ProjectArchiveImpactResponse(**archive_impact(session, project))


@router.post("/{project_id}/archive", response_model=ProjectResponse)
def archive_project(project_id: UUID, payload: ProjectArchiveRequest, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> Project:
    existing, is_owner = _require_project_archive_authority(session, project_id, context)
    if existing.status == "archived":
        if payload.confirmation_name != existing.name:
            raise AppError("project_confirmation_mismatch", "Project name confirmation does not match", status_code=422)
        existing.is_owner = is_owner
        existing.archive_cleanup_status = session.scalar(select(ProjectArchiveRun.status).where(ProjectArchiveRun.project_id == project_id).order_by(ProjectArchiveRun.queued_at.desc(), ProjectArchiveRun.id.desc()).limit(1))
        existing.capabilities = project_capabilities(session, existing, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids))
        return existing
    project = begin_project_archive(session, project_id=project_id, actor_user_id=context.user_id, lock_version=payload.lock_version, confirmation_name=payload.confirmation_name, request_id=request.state.request_id)
    session.commit()
    session.refresh(project)
    project.is_owner = is_owner
    project.capabilities = project_capabilities(session, project, user_id=context.user_id, visible_project_ids=set(context.visible_project_ids))
    project.archive_cleanup_status = "queued"
    return project


@router.delete("/{project_id}", response_model=ProjectResponse)
def legacy_archive_project(project_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> Project:
    _require_project_archive_authority(session, project_id, context)
    raise AppError("archive_confirmation_required", "Use the archive confirmation endpoint", status_code=409)


@router.post("/{project_id}/archive-cleanup/retry", response_model=ProjectResponse)
def retry_archive_cleanup(project_id: UUID, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> Project:
    project, is_owner = _require_project_archive_authority(session, project_id, context)
    if project.status != "archived":
        raise AppError("project_not_archived", "Only archived projects have cleanup runs", status_code=409)
    retry_project_archive_cleanup(session, project=project, actor_user_id=context.user_id, request_id=request.state.request_id)
    session.commit()
    session.refresh(project)
    project.is_owner = is_owner
    project.archive_cleanup_status = "queued"
    return project


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
def list_project_members(project_id: UUID, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[ProjectMemberResponse]:
    _get_scoped_project(session, project_id, context)
    rows = session.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(ProjectMember.project_id == project_id).order_by(User.display_name, ProjectMember.project_role)).all()
    grouped: dict[UUID, ProjectMemberResponse] = {}
    for membership, user in rows:
        existing = grouped.get(user.id)
        if existing is None:
            grouped[user.id] = ProjectMemberResponse(
                user_id=user.id,
                given_name=user.given_name,
                family_name=user.family_name,
                display_name=user.display_name,
                email=user.email,
                roles=[membership.project_role],
            )
        else:
            existing.roles.append(membership.project_role)
    return list(grouped.values())


@router.put("/{project_id}/members/{user_id}", response_model=list[ProjectMemberResponse])
def replace_project_member(project_id: UUID, user_id: UUID, payload: ProjectMemberUpdate, request: Request, context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> list[ProjectMemberResponse]:
    project = _get_scoped_project(session, project_id, context)
    _require_project_owner(session, project_id, context.user_id)
    if project.lock_version != payload.lock_version:
        raise AppError("stale_project_version", "Project was changed by another request", status_code=409)
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError("invalid_project_member", "Project member must be an active user", status_code=422)
    _validate_project_member_candidates(session, {user_id})
    roles = _validate_roles(payload.roles)
    was_owner = session.get(ProjectOwner, (project_id, user_id)) is not None
    if was_owner and "owner" not in roles:
        owner_count = session.scalar(select(func.count()).select_from(ProjectOwner).where(ProjectOwner.project_id == project_id))
        if owner_count == 1:
            raise AppError("last_project_owner", "A project must retain at least one Owner", status_code=409)
    session.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
    session.execute(delete(ProjectOwner).where(ProjectOwner.project_id == project_id, ProjectOwner.user_id == user_id))
    now = datetime.now(UTC)
    session.add_all([ProjectMember(project_id=project_id, user_id=user_id, project_role=role, created_at=now) for role in roles])
    if "owner" in roles:
        session.add(ProjectOwner(project_id=project_id, user_id=user_id, created_at=now))
    project.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action="project.member.replace", resource_type="project", resource_id=project_id, result="success", request_id=request.state.request_id, summary={"user_id": str(user_id), "roles": sorted(roles)})
    session.commit()
    return list_project_members(project_id, context, session)


@router.delete("/{project_id}/members/{user_id}", response_model=ProjectResponse)
def remove_project_member(project_id: UUID, user_id: UUID, request: Request, lock_version: int = Query(ge=1), context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> Project:
    project = _get_scoped_project(session, project_id, context)
    _require_project_owner(session, project_id, context.user_id)
    if project.lock_version != lock_version:
        raise AppError("stale_project_version", "Project was changed by another request", status_code=409)
    if session.get(ProjectOwner, (project_id, user_id)) is not None:
        owners = list(session.scalars(select(ProjectOwner).where(ProjectOwner.project_id == project_id)))
        if len(owners) <= 1:
            raise AppError("last_project_owner", "A project must retain at least one Owner", status_code=409)
    session.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
    session.execute(delete(ProjectOwner).where(ProjectOwner.project_id == project_id, ProjectOwner.user_id == user_id))
    project.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action="project.member.remove", resource_type="project", resource_id=project_id, result="success", request_id=request.state.request_id, summary={"user_id": str(user_id)})
    session.commit()
    session.refresh(project)
    return project
