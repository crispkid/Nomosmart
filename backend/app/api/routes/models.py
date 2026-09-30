from datetime import UTC, datetime
import time
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.api.schemas import AIModelCreate, AIModelDeleteRequest, AIModelResponse, AIModelUpdate
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import AIModel, DocumentVersion, PipelineRun, Project, SystemPrompt
from app.db.session import get_db
from app.domain.connection_evidence import ai_model_connection_fingerprint, invalidate_model_connection_evidence
from app.domain.connection_probes import probe_ai_model
from app.domain.model_usage import record_model_usage, validate_pricing_config
from app.domain.ocr_timeout_policy import normalize_timeout_config
from app.security.context import IdentityContext, get_identity_context
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, MENU_SYSTEM_MANAGEMENT, PermissionAction, has_menu_permission, require_menu_permission
from app.services.audit import add_audit
from app.security.secrets import validate_runtime_secret_reference


router = APIRouter(prefix="/models", tags=["models"])
SUPPORTED_MODEL_TYPES = {"OCR", "Embedding", "Chat", "Judge"}
SECRET_CONFIG_KEYS = {"api_key", "apikey", "secret", "password", "credential", "authorization", "access_token", "refresh_token", "bearer_token", "auth_token"}
PROVIDER_ALIASES = {
    "openai": "OpenAI",
    "gemini": "Gemini",
    "google": "Gemini",
    "claude": "Claude",
    "anthropic": "Claude",
    "ollama": "Ollama",
    "vllm": "vLLM",
    "vllm-openai": "vLLM",
    "custom": "Custom",
    "generic": "Custom",
    "generic http": "Custom",
    "generic_http": "Custom",
}


@router.get("", response_model=list[AIModelResponse])
def list_models(
    response: Response,
    model_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> list[AIModel]:
    grants = list(context.grants)
    if not (
        has_menu_permission(grants, MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
        or has_menu_permission(grants, MENU_KNOWLEDGE_PROJECTS, PermissionAction.VIEW)
    ):
        require_menu_permission(grants, MENU_SYSTEM_MANAGEMENT, PermissionAction.VIEW)
    if model_type is not None and model_type not in SUPPORTED_MODEL_TYPES:
        raise AppError("invalid_model_type", "Model type is invalid", status_code=422)
    predicates = [AIModel.deleted_at.is_(None)]
    if model_type:
        predicates.append(AIModel.model_type == model_type)
    total = int(session.scalar(select(func.count()).select_from(AIModel).where(*predicates)) or 0)
    response.headers["X-Total-Count"] = str(total)
    statement = (
        select(AIModel)
        .where(*predicates)
        .order_by(AIModel.model_type, AIModel.name, AIModel.id)
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(statement))


@router.post("", response_model=AIModelResponse, status_code=201)
def create_model(
    payload: AIModelCreate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> AIModel:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.CREATE)
    if payload.model_type not in SUPPORTED_MODEL_TYPES:
        raise AppError("invalid_model_type", "Model type is invalid", status_code=422)
    provider = _normalize_provider(payload.provider)
    _validate_credential_input(request.app.state.settings, payload.api_key, payload.api_key_secret_ref)
    config = _normalized_config(
        provider=provider,
        model_type=payload.model_type,
        endpoint=payload.endpoint,
        config=payload.config,
        has_credential=bool(payload.api_key or payload.api_key_secret_ref),
        require_credential=payload.is_active or payload.is_default,
    )
    config = _normalize_model_pairings(session=session, model_type=payload.model_type, config=config, require_chat_pairing=True)
    model_id = uuid4()
    encrypted = None
    if payload.api_key and request.app.state.settings.app_env != "production":
        encrypted = EnvelopeCipher(request.app.state.settings.encryption_key_bytes).encrypt(payload.api_key, context=f"ai-model:{model_id}")
    if payload.is_default:
        session.execute(
            update(AIModel)
            .where(AIModel.model_type == payload.model_type, AIModel.deleted_at.is_(None))
            .values(is_default=False)
        )
    model = AIModel(
        id=model_id,
        name=payload.name,
        model_type=payload.model_type,
        provider=provider,
        endpoint=payload.endpoint,
        api_key_encrypted=encrypted,
        api_key_secret_ref=payload.api_key_secret_ref,
        is_active=payload.is_active,
        is_default=payload.is_default,
        config=config,
        config_version=1,
    )
    session.add(model)
    session.flush()
    add_audit(session, actor_user_id=context.user_id, action="ai_model.create", resource_type="ai_model", resource_id=model.id, result="success", request_id=request.state.request_id, summary={"name": model.name, "model_type": model.model_type, "api_key_configured": model.api_key_configured})
    session.commit()
    session.refresh(model)
    return model


@router.delete("/{model_id}", response_model=AIModelResponse)
def delete_model(
    model_id: UUID,
    payload: AIModelDeleteRequest,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> AIModel:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.DELETE)
    model = session.scalar(
        select(AIModel)
        .where(AIModel.id == model_id, AIModel.deleted_at.is_(None))
        .with_for_update()
    )
    if model is None:
        raise AppError("model_not_found", "Model was not found", status_code=404)
    if payload.confirmation_name != model.name:
        raise AppError("model_delete_confirmation_mismatch", "Model name confirmation does not match", status_code=422)
    if payload.config_version != model.config_version:
        raise AppError(
            "model_delete_version_conflict",
            "Model configuration changed; refresh before deleting",
            status_code=409,
        )

    dependencies = _current_model_dependencies(session=session, model=model)
    if dependencies:
        raise AppError(
            "model_in_use",
            "Model has active dependencies and cannot be deleted",
            status_code=409,
            details={"dependencies": dependencies},
        )

    cleaned_pairings = _remove_inactive_chat_pairings(session=session, embedding_model=model)
    model.is_active = False
    model.is_default = False
    model.deleted_at = datetime.now(UTC)
    model.deleted_by = context.user_id
    model.api_key_encrypted = None
    model.api_key_secret_ref = None
    invalidate_model_connection_evidence(model)
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="ai_model.delete",
        resource_type="ai_model",
        resource_id=model.id,
        result="success",
        request_id=request.state.request_id,
        summary={
            "name": model.name,
            "model_type": model.model_type,
            "credential_revoked": True,
            "inactive_chat_pairings_cleaned": cleaned_pairings,
        },
    )
    session.commit()
    session.refresh(model)
    return model


@router.put("/{model_id}", response_model=AIModelResponse)
def update_model(
    model_id: UUID,
    payload: AIModelUpdate,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> AIModel:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    model = session.scalar(select(AIModel).where(AIModel.id == model_id, AIModel.deleted_at.is_(None)))
    if model is None:
        raise AppError("model_not_found", "Model was not found", status_code=404)
    changes = payload.model_dump(exclude_unset=True)
    clear_credential = bool(changes.pop("clear_credential", False))
    clear_confirmation = changes.pop("credential_clear_confirmation", None)
    api_key_value = changes.pop("api_key", None)
    secret_ref_value = changes.pop("api_key_secret_ref", None)
    replacement_api_key = api_key_value if isinstance(api_key_value, str) and api_key_value.strip() else None
    replacement_secret_ref = secret_ref_value.strip() if isinstance(secret_ref_value, str) and secret_ref_value.strip() else None
    if clear_credential and (replacement_api_key or replacement_secret_ref):
        raise AppError(
            "model_credential_action_ambiguous",
            "Credential replacement and explicit clear are mutually exclusive",
            status_code=422,
        )
    if clear_credential and clear_confirmation != model.name:
        raise AppError(
            "model_credential_clear_confirmation_mismatch",
            "Model name confirmation does not match",
            status_code=422,
        )
    if not clear_credential and clear_confirmation is not None:
        raise AppError(
            "model_credential_action_ambiguous",
            "Credential clear confirmation requires the explicit clear action",
            status_code=422,
        )
    if replacement_api_key or replacement_secret_ref:
        _validate_credential_input(
            request.app.state.settings,
            replacement_api_key,
            replacement_secret_ref,
        )
    next_provider = _normalize_provider(changes.get("provider", model.provider))
    next_config = changes.get("config", model.config)
    next_endpoint = changes.get("endpoint", model.endpoint)
    if "endpoint" in changes and "config" not in changes and isinstance(next_config, dict):
        next_config = {**next_config, "base_url": next_endpoint}
    if replacement_api_key:
        next_has_credential = True
    elif replacement_secret_ref:
        next_has_credential = True
    elif clear_credential:
        next_has_credential = False
    else:
        next_has_credential = model.api_key_configured
    next_active = changes.get("is_active", model.is_active)
    next_default = changes.get("is_default", model.is_default)
    if clear_credential and _provider_requires_credential(next_provider) and (next_active or next_default):
        raise AppError(
            "active_model_credential_required",
            "Disable the model and remove its default status before clearing its credential",
            status_code=409,
        )
    if "provider" in changes or "config" in changes or "endpoint" in changes or replacement_api_key or replacement_secret_ref or clear_credential:
        changes["provider"] = next_provider
        changes["config"] = _normalized_config(
            provider=next_provider,
            model_type=model.model_type,
            endpoint=next_endpoint,
            config=next_config,
            has_credential=next_has_credential,
            require_credential=next_active or next_default,
        )
        changes["config"] = _normalize_model_pairings(session=session, model_type=model.model_type, config=changes["config"], require_chat_pairing=model.model_type == "Chat")
    old_authority = _credential_authority(model.provider, model.endpoint, model.config)
    new_authority = _credential_authority(next_provider, next_endpoint, changes.get("config", next_config))
    credential_confirmed = bool(replacement_api_key or replacement_secret_ref or clear_credential)
    if old_authority != new_authority and model.api_key_configured and not credential_confirmed:
        raise AppError("model_credential_reconfirmation_required", "Changing provider or endpoint requires credential confirmation", status_code=422)
    if not next_active and next_default:
        if changes.get("is_default") is True:
            raise AppError("inactive_model_cannot_be_default", "Inactive model cannot be the default", status_code=422)
        changes["is_default"] = False
    if changes.get("is_default") is True:
        session.execute(
            update(AIModel)
            .where(AIModel.model_type == model.model_type, AIModel.id != model.id, AIModel.deleted_at.is_(None))
            .values(is_default=False)
        )
    credential_changed = False
    if replacement_api_key:
        model.api_key_encrypted = EnvelopeCipher(request.app.state.settings.encryption_key_bytes).encrypt(replacement_api_key, context=f"ai-model:{model.id}")
        model.api_key_secret_ref = None
        credential_changed = True
    elif replacement_secret_ref:
        credential_changed = model.api_key_encrypted is not None or model.api_key_secret_ref != replacement_secret_ref
        model.api_key_encrypted = None
        model.api_key_secret_ref = replacement_secret_ref
    elif clear_credential:
        credential_changed = model.api_key_configured
        model.api_key_encrypted = None
        model.api_key_secret_ref = None
    meaningful_fields = {"name", "provider", "endpoint", "api_key_secret_ref", "is_active", "is_default", "config"}
    changed = False
    for field, value in changes.items():
        if field in meaningful_fields and getattr(model, field) != value:
            changed = True
        setattr(model, field, value)
    changed = changed or credential_changed
    if changed:
        model.config_version += 1
        invalidate_model_connection_evidence(model)
    add_audit(
        session,
        actor_user_id=context.user_id,
        action="ai_model.update",
        resource_type="ai_model",
        resource_id=model.id,
        result="success",
        request_id=request.state.request_id,
        summary={
            "fields": sorted(set(payload.model_fields_set) - {"api_key", "credential_clear_confirmation"}),
            "credential_action": "clear" if clear_credential else "replace" if replacement_api_key or replacement_secret_ref else "retain",
        },
    )
    session.commit()
    session.refresh(model)
    return model


def _validate_credential_input(settings, api_key: str | None, secret_ref: str | None) -> None:
    if api_key and secret_ref:
        raise AppError("model_credential_ambiguous", "Provide a mounted Secret reference or a credential, not both", status_code=422)
    if settings.app_env == "production" and api_key:
        raise AppError(
            "plaintext_model_credential_forbidden",
            "Production model credentials must use a mounted Secret reference",
            status_code=422,
        )
    if secret_ref:
        validate_runtime_secret_reference(settings, secret_ref)


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip()
    if not normalized:
        raise AppError("model_provider_required", "Model provider is required", status_code=422)
    return PROVIDER_ALIASES.get(normalized.lower(), normalized)


def _normalized_config(
    *,
    provider: str,
    model_type: str,
    endpoint: str | None,
    config: dict[str, object] | None,
    has_credential: bool,
    require_credential: bool = True,
) -> dict[str, object]:
    normalized = dict(config or {})
    _reject_secret_like_config(normalized)
    for candidate in (endpoint, normalized.get("base_url"), normalized.get("endpoint")):
        if candidate:
            _validate_model_endpoint(str(candidate))
    provider_key = provider.lower()
    if provider_key == "openai":
        if require_credential:
            _require_credential(provider, has_credential)
        _require_config(normalized, "model_name", provider)
        normalized.setdefault("base_url", endpoint or "https://api.openai.com/v1")
        if model_type in {"Chat", "Judge"} and "api_mode" in normalized:
            api_mode = str(normalized.get("api_mode") or "").strip().lower()
            if api_mode not in {"responses", "chat_completions"}:
                raise AppError(
                    "invalid_openai_api_mode",
                    "OpenAI Chat and Judge api_mode must be responses or chat_completions",
                    status_code=422,
                )
            normalized["api_mode"] = api_mode
        if model_type == "Embedding":
            normalized.setdefault("embedding_dimension", None)
        if model_type == "OCR":
            normalized.update(normalize_timeout_config(normalized))
    elif provider_key == "gemini":
        if require_credential:
            _require_credential(provider, has_credential)
        _require_config(normalized, "model_name", provider)
        normalized.setdefault("api_version", "v1beta")
    elif provider_key == "claude":
        if require_credential:
            _require_credential(provider, has_credential)
        _require_config(normalized, "model_name", provider)
        normalized.setdefault("anthropic_version", "2023-06-01")
        if endpoint:
            normalized.setdefault("base_url", endpoint)
    elif provider_key == "ollama":
        _require_config(normalized, "model_name", provider)
        normalized["base_url"] = str(normalized.get("base_url") or endpoint or "").strip()
        _require_config(normalized, "base_url", provider)
        normalized.setdefault("timeout_seconds", 120)
    elif provider_key == "vllm":
        _require_config(normalized, "model_name", provider)
        normalized["base_url"] = str(normalized.get("base_url") or endpoint or "").strip()
        _require_config(normalized, "base_url", provider)
        normalized.setdefault("openai_compatible", True)
        normalized.setdefault("timeout_seconds", 120)
    elif provider_key == "custom":
        if not endpoint and not normalized.get("endpoint"):
            raise AppError("model_endpoint_required", "Custom provider requires an endpoint", status_code=422)
        if endpoint:
            normalized.setdefault("endpoint", endpoint)
        normalized.setdefault("timeout_seconds", 120)
    else:
        # Legacy providers remain compatible but must not hide credentials in config.
        if endpoint:
            normalized.setdefault("endpoint", endpoint)
    normalized["provider"] = provider
    return validate_pricing_config(normalized)


def _validate_model_endpoint(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AppError("model_endpoint_invalid", "Model endpoint must be an HTTP(S) URL without credentials, query parameters or fragments", status_code=422)


def _normalize_model_pairings(*, session: Session, model_type: str, config: dict[str, object], require_chat_pairing: bool) -> dict[str, object]:
    normalized = dict(config)
    raw_pairings = normalized.get("paired_embedding_model_ids")
    if model_type != "Chat":
        normalized.pop("paired_embedding_model_ids", None)
        return normalized
    if raw_pairings is None:
        raw_pairings = []
    if not isinstance(raw_pairings, list):
        raise AppError("invalid_model_pairing", "Chat model paired embedding models must be a list", status_code=422)
    paired_ids: list[UUID] = []
    seen: set[UUID] = set()
    for raw_id in raw_pairings:
        try:
            paired_id = UUID(str(raw_id))
        except (TypeError, ValueError) as exc:
            raise AppError("invalid_model_pairing", "Chat model paired embedding model id is invalid", status_code=422) from exc
        if paired_id not in seen:
            paired_ids.append(paired_id)
            seen.add(paired_id)
    if require_chat_pairing and not paired_ids:
        raise AppError("invalid_model_pairing", "Chat model requires at least one paired Embedding model", status_code=422)
    if not paired_ids:
        normalized["paired_embedding_model_ids"] = []
        return normalized
    active_embedding_ids = set(
        session.scalars(
            select(AIModel.id).where(
                AIModel.id.in_(paired_ids),
                AIModel.model_type == "Embedding",
                AIModel.is_active.is_(True),
                AIModel.deleted_at.is_(None),
            )
        )
    )
    if active_embedding_ids != set(paired_ids):
        raise AppError("invalid_model_pairing", "Chat model paired embedding models must be active Embedding models", status_code=422)
    normalized["paired_embedding_model_ids"] = [str(paired_id) for paired_id in paired_ids]
    return normalized


def _current_model_dependencies(*, session: Session, model: AIModel) -> list[dict[str, object]]:
    dependencies: list[dict[str, object]] = []
    if model.is_default:
        dependencies.append({"type": "system_default", "count": 1})

    project_ids = list(
        session.scalars(
            select(Project.id)
            .where(
                Project.status != "archived",
                or_(
                    Project.llm_model_id == model.id,
                    Project.embedding_model_id == model.id,
                    Project.ocr_model_id == model.id,
                ),
            )
            .with_for_update()
        )
    )
    if project_ids:
        dependencies.append({"type": "current_project_assignment", "count": len(project_ids)})

    if model.model_type == "OCR":
        pipeline_ids = list(
            session.scalars(
                select(PipelineRun.id)
                .where(
                    PipelineRun.status.in_(("queued", "running")),
                    PipelineRun.document_version_id.in_(
                        select(DocumentVersion.id).where(DocumentVersion.ocr_model_id == model.id)
                    ),
                )
                .with_for_update()
            )
        )
        if pipeline_ids:
            dependencies.append({"type": "running_ocr_pipeline", "count": len(pipeline_ids)})

    prompt_ids = list(
        session.scalars(
            select(SystemPrompt.id)
            .where(
                SystemPrompt.prompt_scope == "model",
                SystemPrompt.model_id == model.id,
                SystemPrompt.is_active.is_(True),
            )
            .with_for_update()
        )
    )
    if prompt_ids:
        dependencies.append({"type": "active_system_prompt", "count": len(prompt_ids)})

    if model.model_type == "Embedding":
        paired_chat_count = 0
        active_chat_models = list(
            session.scalars(
                select(AIModel)
                .where(
                    AIModel.model_type == "Chat",
                    AIModel.is_active.is_(True),
                    AIModel.deleted_at.is_(None),
                )
                .with_for_update()
            )
        )
        model_id = str(model.id)
        for chat_model in active_chat_models:
            config = chat_model.config if isinstance(chat_model.config, dict) else {}
            pairings = config.get("paired_embedding_model_ids")
            if isinstance(pairings, list) and model_id in {str(item) for item in pairings}:
                paired_chat_count += 1
        if paired_chat_count:
            dependencies.append({"type": "active_chat_pairing", "count": paired_chat_count})

    return dependencies


def _remove_inactive_chat_pairings(*, session: Session, embedding_model: AIModel) -> int:
    if embedding_model.model_type != "Embedding":
        return 0
    cleaned = 0
    model_id = str(embedding_model.id)
    chat_models = list(
        session.scalars(
            select(AIModel)
            .where(
                AIModel.model_type == "Chat",
                AIModel.is_active.is_(False),
                AIModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
    )
    for chat_model in chat_models:
        config = dict(chat_model.config) if isinstance(chat_model.config, dict) else {}
        pairings = config.get("paired_embedding_model_ids")
        if not isinstance(pairings, list):
            continue
        next_pairings = [str(item) for item in pairings if str(item) != model_id]
        if len(next_pairings) == len(pairings):
            continue
        config["paired_embedding_model_ids"] = next_pairings
        chat_model.config = config
        chat_model.config_version += 1
        invalidate_model_connection_evidence(chat_model)
        cleaned += 1
    return cleaned


def _require_config(config: dict[str, object], key: str, provider: str) -> None:
    value = config.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise AppError("model_provider_config_required", f"{provider} requires {key}", status_code=422, details={"field": key})


def _require_credential(provider: str, has_credential: bool) -> None:
    if not has_credential:
        raise AppError("model_credential_required", f"{provider} requires an API key or secret reference", status_code=422)


def _provider_requires_credential(provider: str) -> bool:
    return provider.strip().lower() in {"openai", "gemini", "google", "claude", "anthropic"}


def _reject_secret_like_config(value: object, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = key.lower().replace("-", "_")
            if normalized_key in SECRET_CONFIG_KEYS or normalized_key.endswith("_secret") or normalized_key.endswith("_api_key"):
                raise AppError("model_config_secret_not_allowed", "Model config must not contain secrets; use API key or Secret Ref fields", status_code=422, details={"field": f"{path}.{key}"})
            _reject_secret_like_config(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_like_config(item, f"{path}[{index}]")


@router.post("/{model_id}/set-default", response_model=AIModelResponse)
def set_default_model(
    model_id: UUID,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> AIModel:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    model = session.scalar(select(AIModel).where(AIModel.id == model_id, AIModel.deleted_at.is_(None)))
    if model is None or not model.is_active:
        raise AppError("active_model_not_found", "Active model was not found", status_code=404)
    session.execute(
        update(AIModel)
        .where(AIModel.model_type == model.model_type, AIModel.deleted_at.is_(None))
        .values(is_default=False)
    )
    model.is_default = True
    add_audit(session, actor_user_id=context.user_id, action="ai_model.set_default", resource_type="ai_model", resource_id=model.id, result="success", request_id=request.state.request_id, summary={"model_type": model.model_type})
    session.commit()
    session.refresh(model)
    return model


@router.post("/{model_id}/test", response_model=AIModelResponse)
def record_connection_test(
    model_id: UUID,
    request: Request,
    context: IdentityContext = Depends(get_identity_context),
    session: Session = Depends(get_db),
) -> AIModel:
    require_menu_permission(list(context.grants), MENU_SYSTEM_MANAGEMENT, PermissionAction.EDIT)
    model = session.scalar(select(AIModel).where(AIModel.id == model_id, AIModel.deleted_at.is_(None)))
    if model is None:
        raise AppError("model_not_found", "Model was not found", status_code=404)
    started = time.monotonic()
    fingerprint = ai_model_connection_fingerprint(model)
    try:
        result = probe_ai_model(request.app.state.settings, model)
    except AppError as exc:
        model.last_test_status = "failed"
        model.last_tested_at = datetime.now(UTC)
        model.last_test_fingerprint = fingerprint
        model.last_test_latency_ms = max(0, int((time.monotonic() - started) * 1000))
        model.last_test_detail_code = exc.code
        model.last_test_actor_id = context.user_id
        record_model_usage(
            session,
            model=model,
            usage_purpose="connection_test",
            source_channel="system_management",
            status="failed",
            error_code=exc.code,
            latency_ms=model.last_test_latency_ms,
            actor_user_id=context.user_id,
            correlation_id=getattr(request.state, "request_id", None),
        )
        add_audit(session, actor_user_id=context.user_id, action="ai_model.connection_test", resource_type="ai_model", resource_id=model.id, result="failed", request_id=request.state.request_id, summary={"detail_code": exc.code, "fingerprint": fingerprint[:12], "latency_ms": model.last_test_latency_ms})
        session.commit()
        raise
    model.last_test_status = "success"
    model.last_tested_at = datetime.now(UTC)
    model.last_test_fingerprint = result.fingerprint
    model.last_test_latency_ms = result.latency_ms
    model.last_test_detail_code = result.detail_code
    model.last_test_actor_id = context.user_id
    record_model_usage(
        session,
        model=model,
        usage_purpose="connection_test",
        source_channel="system_management",
        status="success",
        latency_ms=result.latency_ms,
        actor_user_id=context.user_id,
        correlation_id=getattr(request.state, "request_id", None),
    )
    add_audit(session, actor_user_id=context.user_id, action="ai_model.connection_test", resource_type="ai_model", resource_id=model.id, result="success", request_id=request.state.request_id, summary={"detail_code": result.detail_code, "fingerprint": result.fingerprint[:12], "latency_ms": result.latency_ms})
    session.commit()
    session.refresh(model)
    return model


def _credential_authority(provider: str, endpoint: str | None, config: object) -> tuple[str, str, str, int | None]:
    values = config if isinstance(config, dict) else {}
    url = str(values.get("base_url") or endpoint or "")
    parsed = urlparse(url)
    return provider.strip().lower(), parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port
