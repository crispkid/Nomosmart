from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.schemas import SystemPromptActivatePayload, SystemPromptCreate, SystemPromptResponse, SystemPromptVersionCreate, SystemPromptVersionResponse
from app.core.errors import AppError
from app.db.models import AIModel, SystemPrompt, SystemPromptVersion
from app.db.session import get_db
from app.domain.system_prompts import MAX_SYSTEM_PROMPT_LENGTH, SUPPORTED_PROMPT_MODEL_TYPES, system_prompt_hash
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_SYSTEM_MANAGEMENT, PermissionAction, require_menu_permission
from app.services.audit import add_audit


router = APIRouter(prefix="/system-prompts", tags=["system-prompts"])
model_prompt_router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[SystemPromptResponse])
def list_system_prompts(
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[SystemPromptResponse]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    prompts = list(session.scalars(select(SystemPrompt).order_by(SystemPrompt.prompt_scope, SystemPrompt.model_type, SystemPrompt.created_at)))
    return [_prompt_response(session, prompt) for prompt in prompts]


@router.post("", response_model=SystemPromptResponse, status_code=201)
def create_system_prompt(
    payload: SystemPromptCreate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SystemPromptResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.CREATE)
    _validate_prompt_payload(session, payload.prompt_scope, payload.model_type, payload.model_id, payload.content, allow_blank=not payload.is_active)
    existing = _find_prompt(session, prompt_scope=payload.prompt_scope, model_type=payload.model_type, model_id=payload.model_id)
    if existing is not None:
        raise AppError("system_prompt_exists", "System prompt already exists for this scope", status_code=409)
    prompt = SystemPrompt(
        prompt_scope=payload.prompt_scope,
        model_type=payload.model_type,
        model_id=payload.model_id,
        is_active=payload.is_active,
        created_by=context.user_id,
        updated_by=context.user_id,
    )
    session.add(prompt)
    session.flush()
    version = _add_version(session, prompt, payload, context.user_id, request.state.request_id)
    prompt.current_version_id = version.id
    session.flush()
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="system_prompt.create",
        resource_type="system_prompt",
        resource_id=prompt.id,
        result="success",
        request_id=request.state.request_id,
        summary=_audit_summary(prompt, version),
    )
    session.commit()
    return _prompt_response(session, prompt)


@router.get("/{prompt_id}/versions", response_model=list[SystemPromptVersionResponse])
def list_system_prompt_versions(
    prompt_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[SystemPromptVersion]:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    _get_prompt(session, prompt_id)
    return list(session.scalars(select(SystemPromptVersion).where(SystemPromptVersion.prompt_id == prompt_id).order_by(SystemPromptVersion.version_number.desc())))


@router.post("/{prompt_id}/versions", response_model=SystemPromptResponse, status_code=201)
def create_system_prompt_version(
    prompt_id: UUID,
    payload: SystemPromptVersionCreate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SystemPromptResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    _validate_content(payload.content)
    prompt = _get_prompt(session, prompt_id, for_update=True)
    _assert_prompt_model_live(session, prompt)
    version = _add_version(session, prompt, payload, context.user_id, request.state.request_id)
    prompt.current_version_id = version.id
    prompt.is_active = payload.is_active
    prompt.updated_by = context.user_id
    prompt.lock_version += 1
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="system_prompt.version.create",
        resource_type="system_prompt",
        resource_id=prompt.id,
        result="success",
        request_id=request.state.request_id,
        summary=_audit_summary(prompt, version),
    )
    session.commit()
    return _prompt_response(session, prompt)


@router.post("/{prompt_id}/activate", response_model=SystemPromptResponse)
def activate_system_prompt(
    prompt_id: UUID,
    payload: SystemPromptActivatePayload,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SystemPromptResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    prompt = _get_prompt(session, prompt_id, for_update=True)
    _assert_prompt_model_live(session, prompt)
    version_id = payload.version_id or prompt.current_version_id
    if version_id is None:
        raise AppError("system_prompt_version_required", "System prompt does not have a version to activate", status_code=409)
    version = session.get(SystemPromptVersion, version_id)
    if version is None or version.prompt_id != prompt.id:
        raise AppError("system_prompt_version_not_found", "System prompt version was not found", status_code=404)
    _validate_content(version.content)
    session.execute(update(SystemPromptVersion).where(SystemPromptVersion.prompt_id == prompt.id).values(is_active=False))
    version.is_active = True
    prompt.current_version_id = version.id
    prompt.is_active = True
    prompt.updated_by = context.user_id
    prompt.lock_version += 1
    add_audit(session, actor_user_id=context.user_id, action="system_prompt.activate", resource_type="system_prompt", resource_id=prompt.id, result="success", request_id=request.state.request_id, summary=_audit_summary(prompt, version))
    session.commit()
    return _prompt_response(session, prompt)


@router.post("/{prompt_id}/deactivate", response_model=SystemPromptResponse)
def deactivate_system_prompt(
    prompt_id: UUID,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SystemPromptResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    prompt = _get_prompt(session, prompt_id, for_update=True)
    _assert_prompt_model_live(session, prompt)
    prompt.is_active = False
    prompt.updated_by = context.user_id
    prompt.lock_version += 1
    session.execute(update(SystemPromptVersion).where(SystemPromptVersion.prompt_id == prompt.id).values(is_active=False))
    current = session.get(SystemPromptVersion, prompt.current_version_id) if prompt.current_version_id else None
    add_audit(session, actor_user_id=context.user_id, action="system_prompt.deactivate", resource_type="system_prompt", resource_id=prompt.id, result="success", request_id=request.state.request_id, summary=_audit_summary(prompt, current))
    session.commit()
    return _prompt_response(session, prompt)


@model_prompt_router.get("/{model_id}/system-prompt", response_model=SystemPromptResponse)
def get_model_system_prompt(
    model_id: UUID,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SystemPromptResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    model = session.get(AIModel, model_id)
    if model is None or model.deleted_at is not None:
        raise AppError("model_not_found", "Model was not found", status_code=404)
    if model.model_type not in SUPPORTED_PROMPT_MODEL_TYPES:
        raise AppError("invalid_prompt_model_type", "System prompts are only supported for Chat and Judge models", status_code=422)
    prompt = _find_prompt(session, prompt_scope="model", model_type=model.model_type, model_id=model.id)
    if prompt is None:
        raise AppError("system_prompt_not_found", "System prompt was not found", status_code=404)
    return _prompt_response(session, prompt)


@model_prompt_router.put("/{model_id}/system-prompt", response_model=SystemPromptResponse)
def upsert_model_system_prompt(
    model_id: UUID,
    payload: SystemPromptVersionCreate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> SystemPromptResponse:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    model = session.get(AIModel, model_id)
    if model is None or model.deleted_at is not None:
        raise AppError("model_not_found", "Model was not found", status_code=404)
    _validate_prompt_payload(session, "model", model.model_type, model.id, payload.content, allow_blank=not payload.is_active)
    prompt = _find_prompt(session, prompt_scope="model", model_type=model.model_type, model_id=model.id)
    created = False
    if prompt is None:
        prompt = SystemPrompt(
            prompt_scope="model",
            model_type=model.model_type,
            model_id=model.id,
            is_active=payload.is_active,
            created_by=context.user_id,
            updated_by=context.user_id,
        )
        session.add(prompt)
        session.flush()
        created = True
    else:
        prompt.updated_by = context.user_id
        prompt.lock_version += 1
    version = _add_version(session, prompt, payload, context.user_id, request.state.request_id)
    prompt.current_version_id = version.id
    prompt.is_active = payload.is_active
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="system_prompt.model.upsert",
        resource_type="system_prompt",
        resource_id=prompt.id,
        result="success",
        request_id=request.state.request_id,
        summary={**_audit_summary(prompt, version), "created": created},
    )
    session.commit()
    return _prompt_response(session, prompt)


def _find_prompt(session: Session, *, prompt_scope: str, model_type: str, model_id: UUID | None) -> SystemPrompt | None:
    statement = select(SystemPrompt).where(SystemPrompt.prompt_scope == prompt_scope)
    if prompt_scope == "global":
        statement = statement.where(SystemPrompt.model_type == model_type, SystemPrompt.model_id.is_(None))
    else:
        statement = statement.where(SystemPrompt.model_id == model_id)
    return session.scalar(statement)


def _get_prompt(session: Session, prompt_id: UUID, *, for_update: bool = False) -> SystemPrompt:
    statement = select(SystemPrompt).where(SystemPrompt.id == prompt_id)
    if for_update:
        statement = statement.with_for_update()
    prompt = session.scalar(statement)
    if prompt is None:
        raise AppError("system_prompt_not_found", "System prompt was not found", status_code=404)
    return prompt


def _assert_prompt_model_live(session: Session, prompt: SystemPrompt) -> None:
    if prompt.prompt_scope != "model" or prompt.model_id is None:
        return
    model = session.get(AIModel, prompt.model_id)
    if model is None or model.deleted_at is not None:
        raise AppError("model_not_found", "Model was not found", status_code=404)


def _validate_prompt_payload(session: Session, prompt_scope: str, model_type: str, model_id: UUID | None, content: str, *, allow_blank: bool = False) -> None:
    _validate_content(content, allow_blank=allow_blank)
    if model_type not in SUPPORTED_PROMPT_MODEL_TYPES:
        raise AppError("invalid_prompt_model_type", "System prompts are only supported for Chat and Judge models", status_code=422)
    if prompt_scope == "global":
        if model_id is not None:
            raise AppError("system_prompt_model_id_not_allowed", "Global system prompts cannot reference a model", status_code=422)
        return
    if model_id is None:
        raise AppError("system_prompt_model_required", "Model-specific system prompts require a model", status_code=422)
    model = session.get(AIModel, model_id)
    if model is None or model.deleted_at is not None:
        raise AppError("model_not_found", "Model was not found", status_code=404)
    if model.model_type != model_type:
        raise AppError("system_prompt_model_type_mismatch", "System prompt model type must match the target model", status_code=422)


def _validate_content(content: str, *, allow_blank: bool = False) -> None:
    if len(content) > MAX_SYSTEM_PROMPT_LENGTH:
        raise AppError("system_prompt_too_long", "System prompt cannot exceed 8000 characters", status_code=422, details={"max_length": MAX_SYSTEM_PROMPT_LENGTH})
    if not allow_blank and not content.strip():
        raise AppError("system_prompt_blank", "System prompt cannot be blank", status_code=422)


def _add_version(session: Session, prompt: SystemPrompt, payload: SystemPromptVersionCreate, actor_user_id: UUID | None, request_id: str | None) -> SystemPromptVersion:
    session.execute(update(SystemPromptVersion).where(SystemPromptVersion.prompt_id == prompt.id).values(is_active=False))
    next_number = (session.scalar(select(func.max(SystemPromptVersion.version_number)).where(SystemPromptVersion.prompt_id == prompt.id)) or 0) + 1
    version = SystemPromptVersion(
        prompt_id=prompt.id,
        version_number=next_number,
        content=payload.content,
        content_hash=system_prompt_hash(payload.content),
        is_active=payload.is_active,
        change_reason=payload.change_reason,
        created_by=actor_user_id,
        request_id=request_id,
        created_at=datetime.now(UTC),
    )
    session.add(version)
    session.flush()
    return version


def _prompt_response(session: Session, prompt: SystemPrompt) -> SystemPromptResponse:
    versions = list(session.scalars(select(SystemPromptVersion).where(SystemPromptVersion.prompt_id == prompt.id).order_by(SystemPromptVersion.version_number.desc())))
    current = next((version for version in versions if version.id == prompt.current_version_id), None)
    return SystemPromptResponse(
        id=prompt.id,
        prompt_scope=prompt.prompt_scope,
        model_type=prompt.model_type,
        model_id=prompt.model_id,
        is_active=prompt.is_active,
        current_version_id=prompt.current_version_id,
        current_version_number=current.version_number if current else None,
        content=current.content if current else "",
        content_length=len(current.content) if current else 0,
        content_hash=current.content_hash if current else None,
        lock_version=prompt.lock_version,
        created_by=prompt.created_by,
        updated_by=prompt.updated_by,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
        versions=versions,
    )


def _audit_summary(prompt: SystemPrompt, version: SystemPromptVersion | None) -> dict[str, object]:
    return {
        "prompt_scope": prompt.prompt_scope,
        "model_type": prompt.model_type,
        "model_id": str(prompt.model_id) if prompt.model_id else None,
        "is_active": prompt.is_active,
        "version_id": str(version.id) if version else None,
        "version_number": version.version_number if version else None,
        "version_is_active": version.is_active if version else None,
        "content_hash": version.content_hash if version else None,
        "content_length": len(version.content) if version else 0,
    }
