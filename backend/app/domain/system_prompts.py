from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AIModel, SystemPrompt, SystemPromptVersion


SUPPORTED_PROMPT_MODEL_TYPES = {"Chat", "Judge"}
MAX_SYSTEM_PROMPT_LENGTH = 8000

DEFAULT_CHAT_SYSTEM_PROMPT = (
    "You are NomoSmart's enterprise knowledge assistant. Answer only from the provided published sources. "
    "If the sources are insufficient, say that the answer cannot be confirmed. Include concise citation markers like [1]."
)
DEFAULT_JUDGE_SYSTEM_PROMPT = "You are a strict validation judge. Return only JSON with keys score and reason. score must be between 0 and 1."


@dataclass(frozen=True)
class SystemPromptLayer:
    source: str
    version_id: UUID | None
    content_hash: str
    content_length: int
    order: int


@dataclass(frozen=True)
class SystemPromptResolution:
    content: str
    source: str
    version_id: UUID | None
    content_hash: str
    layers: tuple[SystemPromptLayer, ...]

    def metadata(self) -> list[dict[str, Any]]:
        return [
            {
                "source": layer.source,
                "version_id": str(layer.version_id) if layer.version_id else None,
                "content_hash": layer.content_hash,
                "content_length": layer.content_length,
                "order": layer.order,
            }
            for layer in self.layers
        ]


def system_prompt_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def backend_default_prompt(model_type: str) -> SystemPromptResolution:
    if model_type == "Chat":
        content = DEFAULT_CHAT_SYSTEM_PROMPT
    elif model_type == "Judge":
        content = DEFAULT_JUDGE_SYSTEM_PROMPT
    else:
        raise AppError("invalid_prompt_model_type", "System prompts are only supported for Chat and Judge models", status_code=422)
    content_hash = system_prompt_hash(content)
    layer = SystemPromptLayer(source="backend_default", version_id=None, content_hash=content_hash, content_length=len(content), order=1)
    return SystemPromptResolution(content=content, source="backend_default", version_id=None, content_hash=content_hash, layers=(layer,))


def resolve_system_prompt(session: Session, *, model: AIModel, model_type: str) -> SystemPromptResolution:
    if model_type not in SUPPORTED_PROMPT_MODEL_TYPES:
        raise AppError("invalid_prompt_model_type", "System prompts are only supported for Chat and Judge models", status_code=422)
    layers = [backend_default_prompt(model_type).layers[0]]
    content_blocks = [("backend_default", backend_default_prompt(model_type).content)]
    model_prompt = session.scalar(
        select(SystemPrompt).where(
            SystemPrompt.prompt_scope == "model",
            SystemPrompt.model_type == model_type,
            SystemPrompt.model_id == model.id,
            SystemPrompt.is_active.is_(True),
        )
    )
    if model_prompt is not None:
        model_layer, model_content = _layer_for_prompt(session, model_prompt, "model", len(layers) + 1)
        layers.append(model_layer)
        content_blocks.append(("model", model_content))
    global_prompt = session.scalar(
        select(SystemPrompt).where(
            SystemPrompt.prompt_scope == "global",
            SystemPrompt.model_type == model_type,
            SystemPrompt.is_active.is_(True),
        )
    )
    if global_prompt is not None:
        global_layer, global_content = _layer_for_prompt(session, global_prompt, "global", len(layers) + 1)
        layers.append(global_layer)
        content_blocks.append(("global", global_content))
    content = _combined_content(content_blocks)
    content_hash = system_prompt_hash(content)
    top_layer = layers[-1]
    return SystemPromptResolution(content=content, source=top_layer.source, version_id=top_layer.version_id, content_hash=content_hash, layers=tuple(layers))


def _layer_for_prompt(session: Session, prompt: SystemPrompt, source: str, order: int) -> tuple[SystemPromptLayer, str]:
    if prompt.current_version_id is None:
        raise AppError("system_prompt_version_required", "Active system prompt does not have a current version", status_code=409)
    version = session.get(SystemPromptVersion, prompt.current_version_id)
    if version is None or version.prompt_id != prompt.id or not version.is_active:
        raise AppError("system_prompt_version_invalid", "Active system prompt version is invalid", status_code=409)
    return SystemPromptLayer(source=source, version_id=version.id, content_hash=version.content_hash, content_length=len(version.content), order=order), version.content


def _combined_content(blocks: list[tuple[str, str]]) -> str:
    rendered = []
    for source, content in blocks:
        if not content:
            continue
        rendered.append(f"[{source}]\n{content.strip()}")
    return "\n\n".join(rendered)
