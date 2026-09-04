from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.contracts import empty_project_capabilities
from app.db.models import AIModel, Project, ProjectMember, ProjectOwner
from app.security.context import IdentityContext
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, PermissionAction, require_menu_permission, require_project_scope
from app.security.project_roles import PROJECT_EDITOR_ROLES, PROJECT_OWNER_ROLES, PROJECT_VIEWER_ROLES, canonical_project_role, has_project_role


PROJECT_MODEL_GROUP_KEYS = (
    "model_group",
    "modelGroup",
    "model_family",
    "modelFamily",
    "deployment_group",
    "deploymentGroup",
    "project_group",
    "projectGroup",
)


def require_project_owner(session: Session, project_id: UUID, user_id: UUID) -> None:
    if session.get(ProjectOwner, (project_id, user_id)) is None:
        raise AppError("project_owner_required", "Project Owner relationship is required", status_code=403)


def resolve_project_model(session: Session, requested_id: UUID | None, model_type: str) -> UUID:
    if requested_id is not None:
        model = session.get(AIModel, requested_id)
        if model is None or not model.is_active or model.deleted_at is not None or model.model_type != model_type:
            raise AppError("invalid_project_model", f"Active {model_type} model is required", status_code=422)
        return model.id
    model_id = session.scalar(select(AIModel.id).where(AIModel.model_type == model_type, AIModel.is_active.is_(True), AIModel.is_default.is_(True), AIModel.deleted_at.is_(None)))
    if model_id is None:
        raise AppError("project_model_required", f"A default {model_type} model is not configured", status_code=422)
    return model_id


def _model_pair_key(model: AIModel) -> str:
    config = model.config if isinstance(model.config, dict) else {}
    for key in PROJECT_MODEL_GROUP_KEYS:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return f"group:{value.strip().lower()}"
    return f"provider:{model.provider.strip().lower()}"


def _chat_accepts_embedding(chat_model: AIModel, embedding_model: AIModel) -> bool:
    config = chat_model.config if isinstance(chat_model.config, dict) else {}
    configured_ids = config.get("paired_embedding_model_ids")
    if isinstance(configured_ids, list):
        paired_ids = {
            value.strip().lower()
            for value in configured_ids
            if isinstance(value, str) and value.strip()
        }
        if paired_ids:
            return str(embedding_model.id).lower() in paired_ids
    return _model_pair_key(chat_model) == _model_pair_key(embedding_model)


def resolve_project_models(
    session: Session,
    *,
    llm_model_id: UUID | None,
    ocr_model_id: UUID | None,
    embedding_model_id: UUID | None,
) -> tuple[UUID, UUID, UUID]:
    """Resolve the required active project model set before any project writes."""

    requested_models = (
        ("chat", "Chat", llm_model_id),
        ("ocr", "OCR", ocr_model_id),
        ("embedding", "Embedding", embedding_model_id),
    )
    resolved: dict[str, AIModel] = {}
    missing_model_types: list[str] = []
    for public_type, database_type, requested_id in requested_models:
        model = session.get(AIModel, requested_id) if requested_id is not None else None
        if model is None or not model.is_active or model.deleted_at is not None or model.model_type != database_type:
            missing_model_types.append(public_type)
            continue
        resolved[public_type] = model

    if missing_model_types:
        raise AppError(
            "project_model_configuration_required",
            "Active Chat, OCR, and Embedding models are required",
            status_code=422,
            details={"missing_model_types": missing_model_types},
        )

    chat_model = resolved["chat"]
    ocr_model = resolved["ocr"]
    embedding_model = resolved["embedding"]
    if not _chat_accepts_embedding(chat_model, embedding_model):
        raise AppError(
            "project_model_pair_required",
            "The selected Chat model requires a compatible active Embedding model",
            status_code=422,
            details={"llm_model_id": str(chat_model.id), "embedding_model_id": str(embedding_model.id)},
        )

    return chat_model.id, embedding_model.id, ocr_model.id


def get_scoped_project(session: Session, project_id: UUID, context: IdentityContext) -> Project:
    require_menu_permission(list(context.grants), MENU_KNOWLEDGE_PROJECTS, PermissionAction.VIEW)
    require_project_scope(project_id, set(context.visible_project_ids))
    project = session.get(Project, project_id)
    if project is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    if project.status == "archived":
        raise AppError("project_archived", "Archived projects cannot be opened or used", status_code=409)
    return project


def project_capabilities(
    session: Session,
    project: Project,
    *,
    user_id: UUID,
    visible_project_ids: set[UUID],
    current_user_project_roles: set[str] | None = None,
) -> dict[str, bool]:
    capabilities = empty_project_capabilities()
    if project.status != "active" or project.id not in visible_project_ids:
        return capabilities
    if current_user_project_roles is None:
        can_view = has_project_role(session, project.id, user_id, PROJECT_VIEWER_ROLES)
        can_edit = has_project_role(session, project.id, user_id, PROJECT_EDITOR_ROLES)
        is_owner = has_project_role(session, project.id, user_id, PROJECT_OWNER_ROLES)
    else:
        roles = set(current_user_project_roles)
        can_view = bool(roles & PROJECT_VIEWER_ROLES)
        can_edit = bool(roles & PROJECT_EDITOR_ROLES)
        is_owner = bool(roles & PROJECT_OWNER_ROLES)
    capabilities.update(
        {
            "can_upload": can_edit,
            "can_update_source": can_edit,
            "can_start_extraction": can_edit,
            "can_reextract": can_edit,
            "can_edit_chunks": can_edit,
            "can_create_reference": can_edit,
            "can_sync_source": can_edit,
            "can_view_graph": can_view,
            "can_submit_review": can_edit,
            "can_manage_lifecycle": is_owner,
        }
    )
    return capabilities


def project_response_projection(
    session: Session,
    project: Project,
    *,
    user_id: UUID,
    visible_project_ids: set[UUID],
    current_user_project_roles: set[str] | None = None,
    is_owner: bool | None = None,
) -> Project:
    """Attach the current request's authoritative project access projection."""

    roles = (
        set(current_user_project_roles)
        if current_user_project_roles is not None
        else set(
            session.scalars(
                select(ProjectMember.project_role).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == user_id,
                )
            )
        )
    )
    resolved_is_owner = (
        is_owner
        if is_owner is not None
        else session.get(ProjectOwner, (project.id, user_id)) is not None
    )
    if resolved_is_owner:
        roles.add("owner")

    canonical_role = canonical_project_role(roles)
    roles = {canonical_role} if canonical_role is not None else set()

    project.is_owner = resolved_is_owner
    project.current_user_project_roles = sorted(roles)
    project.capabilities = project_capabilities(
        session,
        project,
        user_id=user_id,
        visible_project_ids=visible_project_ids,
        current_user_project_roles=roles,
    )
    return project
