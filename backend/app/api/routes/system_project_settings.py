"""System management: project settings managed by administrators (CHG-486 PSET486-001..007).

Administrators with the System Management permission see every project's models, members and rerank switch here
and change them for one or many projects at once. Each project is processed in its own transaction; one project's
failure never undoes another (D486-10). The project settings page keeps its own Owner-only APIs (PSET486-007).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AIModel, Project, ProjectMember, ProjectOwner, User
from app.db.session import get_db
from app.domain.project_access import resolve_project_models
from app.domain.project_members import validate_project_member_candidates
from app.domain.retrieval_tuning import system_rerank_available
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.security.project_roles import canonical_project_role
from app.services.audit import add_audit

router = APIRouter(prefix="/system/project-settings", tags=["system"])
AUDIT_SOURCE = "system_project_settings"
MAX_BATCH_PROJECTS = 200
PROJECT_ROLES = frozenset({"owner", "editor", "viewer"})  # same set as the project settings page


class ProjectSettingsMember(BaseModel):
    user_id: UUID
    display_name: str
    email: str | None = None
    role: str


class ProjectSettingsModel(BaseModel):
    id: UUID
    name: str


class ProjectSettingsItem(BaseModel):
    id: UUID
    name: str
    status: str
    llm_model: ProjectSettingsModel | None = None
    embedding_model: ProjectSettingsModel | None = None
    ocr_model: ProjectSettingsModel | None = None
    owners: list[ProjectSettingsMember] = Field(default_factory=list)
    member_count: int = 0
    rerank_enabled: bool = False
    members: list[ProjectSettingsMember] | None = None


class ProjectSettingsPage(BaseModel):
    items: list[ProjectSettingsItem]
    total: int
    offset: int
    limit: int
    rerank_available: bool
    rerank_enabled_count: int = 0  # active projects whose switch is on (RERANK486-003 confirmation)


class ProjectSettingsBatch(BaseModel):
    action: Literal["set_models", "put_member", "remove_member", "set_rerank"]
    project_ids: list[UUID] = Field(min_length=1, max_length=MAX_BATCH_PROJECTS)
    llm_model_id: UUID | None = None
    embedding_model_id: UUID | None = None
    ocr_model_id: UUID | None = None
    user_id: UUID | None = None
    role: str | None = None
    rerank_enabled: bool | None = None


class ProjectSettingsResult(BaseModel):
    project_id: UUID
    status: Literal["updated", "unchanged", "failed"]
    error_code: str | None = None


class ProjectSettingsBatchResponse(BaseModel):
    results: list[ProjectSettingsResult]


@router.get("", response_model=ProjectSettingsPage)
def list_project_settings(
    q: str | None = Query(default=None, max_length=100),
    status: Literal["active", "archived"] = Query(default="active"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> ProjectSettingsPage:
    """PSET486-001: every project (no membership needed), names and settings only, never document content."""
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    query = select(Project).where(Project.status == status)
    if q and q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(Project.name.ilike(pattern, escape="\\"))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    projects = list(session.scalars(query.order_by(Project.name, Project.id).offset(offset).limit(limit)))
    enabled = session.scalar(select(func.count()).select_from(Project).where(Project.status == "active", Project.rerank_enabled.is_(True))) or 0
    return ProjectSettingsPage(items=_items(session, projects, with_members=False), total=total, offset=offset, limit=limit,
                               rerank_available=system_rerank_available(session), rerank_enabled_count=enabled)


@router.get("/{project_id}", response_model=ProjectSettingsItem)
def get_project_settings(project_id: UUID, context: IdentityContext = Depends(get_identity_context),
                         session: Session = Depends(get_db)) -> ProjectSettingsItem:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    project = session.get(Project, project_id)
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    return _items(session, [project], with_members=True)[0]


@router.post("/batch", response_model=ProjectSettingsBatchResponse)
def batch_project_settings(payload: ProjectSettingsBatch, request: Request, context: IdentityContext = Depends(get_identity_context),
                           session: Session = Depends(get_db)) -> ProjectSettingsBatchResponse:
    """PSET486-002..006: apply one change to each listed project; every project succeeds or fails on its own."""
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    _validate_batch(session, payload)
    results: list[ProjectSettingsResult] = []
    for project_id in dict.fromkeys(payload.project_ids):
        try:
            changed = _apply(session, payload, project_id, actor=context.user_id, request_id=request.state.request_id)
            session.commit()
            results.append(ProjectSettingsResult(project_id=project_id, status="updated" if changed else "unchanged"))
        except AppError as exc:
            session.rollback()
            results.append(ProjectSettingsResult(project_id=project_id, status="failed", error_code=exc.code))
    return ProjectSettingsBatchResponse(results=results)


def _validate_batch(session: Session, payload: ProjectSettingsBatch) -> None:
    if payload.action == "set_models":
        if payload.llm_model_id is None and payload.embedding_model_id is None and payload.ocr_model_id is None:
            raise AppError("project_model_required", "Choose at least one model to set", status_code=422)
    elif payload.action in ("put_member", "remove_member"):
        if payload.user_id is None:
            raise AppError("project_member_required", "Choose the user to add or remove", status_code=422)
        if payload.action == "put_member":
            if payload.role not in PROJECT_ROLES:
                raise AppError("invalid_project_role", "Project roles must be owner, editor, or viewer", status_code=422)
            validate_project_member_candidates(session, {payload.user_id})
    elif payload.action == "set_rerank":
        if payload.rerank_enabled is None:
            raise AppError("rerank_enabled_required", "rerank_enabled is required", status_code=422)
        if payload.rerank_enabled and not system_rerank_available(session):
            raise AppError("rerank_disabled_by_system", "Reranking is not enabled in the system settings", status_code=409)


def _apply(session: Session, payload: ProjectSettingsBatch, project_id: UUID, *, actor: UUID, request_id: str | None) -> bool:
    project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    if project.status != "active":
        raise AppError("project_archived", "Archived projects cannot be changed", status_code=409)
    if payload.action == "set_models":
        return _set_models(session, project, payload, actor=actor, request_id=request_id)
    if payload.action == "set_rerank":
        if project.rerank_enabled == payload.rerank_enabled:
            return False
        project.rerank_enabled = bool(payload.rerank_enabled)
        _audit(session, project.id, "project.rerank.update", {"rerank_enabled": project.rerank_enabled}, actor, request_id)
        return True
    if payload.action == "put_member":
        return _put_member(session, project, payload.user_id, payload.role, actor=actor, request_id=request_id)
    return _remove_member(session, project, payload.user_id, actor=actor, request_id=request_id)


def _set_models(session: Session, project: Project, payload: ProjectSettingsBatch, *, actor: UUID, request_id: str | None) -> bool:
    requested = {"llm_model_id": payload.llm_model_id, "embedding_model_id": payload.embedding_model_id, "ocr_model_id": payload.ocr_model_id}
    changes = {field: value for field, value in requested.items() if value is not None and getattr(project, field) != value}
    if not changes:
        return False
    # Same rules as the project settings page: the resulting set of three models must be active and valid.
    llm, embedding, ocr = resolve_project_models(
        session,
        llm_model_id=changes.get("llm_model_id", project.llm_model_id),
        embedding_model_id=changes.get("embedding_model_id", project.embedding_model_id),
        ocr_model_id=changes.get("ocr_model_id", project.ocr_model_id),
    )
    resolved = {"llm_model_id": llm, "embedding_model_id": embedding, "ocr_model_id": ocr}
    old = {field: str(getattr(project, field)) if getattr(project, field) else None for field in changes}
    for field in changes:
        setattr(project, field, resolved[field])
    project.lock_version += 1
    _audit(session, project.id, "project.update", {"fields": sorted(changes), "old": old,
                                                   "new": {field: str(resolved[field]) for field in changes}}, actor, request_id)
    return True


def _put_member(session: Session, project: Project, user_id: UUID, role: str, *, actor: UUID, request_id: str | None) -> bool:
    previous = canonical_project_role(set(session.scalars(select(ProjectMember.project_role).where(
        ProjectMember.project_id == project.id, ProjectMember.user_id == user_id))))
    if session.get(ProjectOwner, (project.id, user_id)) is not None:
        previous = "owner"
    if previous == role:
        return False
    if previous == "owner":
        _require_other_owner(session, project.id, user_id)
    session.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id))
    session.execute(delete(ProjectOwner).where(ProjectOwner.project_id == project.id, ProjectOwner.user_id == user_id))
    now = datetime.now(UTC)
    session.add(ProjectMember(project_id=project.id, user_id=user_id, project_role=role, created_at=now))
    if role == "owner":
        session.add(ProjectOwner(project_id=project.id, user_id=user_id, created_at=now))
    project.lock_version += 1
    _audit(session, project.id, "project.member.replace", {"user_id": str(user_id), "before_role": previous, "after_role": role,
                                                           "roles": [role]}, actor, request_id)
    return True


def _remove_member(session: Session, project: Project, user_id: UUID, *, actor: UUID, request_id: str | None) -> bool:
    is_member = session.scalar(select(func.count()).select_from(ProjectMember).where(
        ProjectMember.project_id == project.id, ProjectMember.user_id == user_id)) or 0
    is_owner = session.get(ProjectOwner, (project.id, user_id)) is not None
    if not is_member and not is_owner:
        return False
    if is_owner:
        _require_other_owner(session, project.id, user_id)
    session.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id))
    session.execute(delete(ProjectOwner).where(ProjectOwner.project_id == project.id, ProjectOwner.user_id == user_id))
    project.lock_version += 1
    _audit(session, project.id, "project.member.remove", {"user_id": str(user_id)}, actor, request_id)
    return True


def _require_other_owner(session: Session, project_id: UUID, user_id: UUID) -> None:
    """PSET486-004: a project keeps at least one Owner."""
    others = session.scalar(select(func.count()).select_from(ProjectOwner).where(
        ProjectOwner.project_id == project_id, ProjectOwner.user_id != user_id)) or 0
    if others < 1:
        raise AppError("last_project_owner", "A project must retain at least one Owner", status_code=409)


def _audit(session: Session, project_id: UUID, action: str, summary: dict, actor: UUID, request_id: str | None) -> None:
    add_audit(session, actor_user_id=actor, action=action, resource_type="project", resource_id=project_id, result="success",
              request_id=request_id, summary={**summary, "source": AUDIT_SOURCE})


def _items(session: Session, projects: list[Project], *, with_members: bool) -> list[ProjectSettingsItem]:
    if not projects:
        return []
    ids = [project.id for project in projects]
    model_ids = {value for project in projects for value in (project.llm_model_id, project.embedding_model_id, project.ocr_model_id) if value}
    models = {model.id: model for model in session.scalars(select(AIModel).where(AIModel.id.in_(model_ids)))} if model_ids else {}
    member_rows = session.execute(
        select(ProjectMember.project_id, ProjectMember.project_role, User.id, User.display_name, User.email)
        .join(User, User.id == ProjectMember.user_id).where(ProjectMember.project_id.in_(ids))
        .order_by(User.display_name, User.id)).all()
    owner_rows = session.execute(select(ProjectOwner.project_id, User.id, User.display_name, User.email)
                                 .join(User, User.id == ProjectOwner.user_id).where(ProjectOwner.project_id.in_(ids))
                                 .order_by(User.display_name, User.id)).all()
    roles: dict[UUID, dict[UUID, set[str]]] = {}
    people: dict[UUID, tuple[str, str | None]] = {}
    for project_id, role, user_id, name, email in member_rows:
        roles.setdefault(project_id, {}).setdefault(user_id, set()).add(role)
        people[user_id] = (name, email)
    for project_id, user_id, name, email in owner_rows:
        roles.setdefault(project_id, {}).setdefault(user_id, set()).add("owner")
        people[user_id] = (name, email)

    def model_ref(model_id: UUID | None) -> ProjectSettingsModel | None:
        model = models.get(model_id) if model_id else None
        return ProjectSettingsModel(id=model.id, name=model.name) if model is not None else None

    items: list[ProjectSettingsItem] = []
    for project in projects:
        members = [ProjectSettingsMember(user_id=user_id, display_name=people[user_id][0], email=people[user_id][1],
                                         role=canonical_project_role(user_roles) or "viewer")
                   for user_id, user_roles in roles.get(project.id, {}).items()]
        members.sort(key=lambda member: (member.display_name.lower(), str(member.user_id)))
        items.append(ProjectSettingsItem(
            id=project.id, name=project.name, status=project.status,
            llm_model=model_ref(project.llm_model_id), embedding_model=model_ref(project.embedding_model_id),
            ocr_model=model_ref(project.ocr_model_id),
            owners=[member for member in members if member.role == "owner"], member_count=len(members),
            rerank_enabled=project.rerank_enabled, members=members if with_members else None,
        ))
    return items
