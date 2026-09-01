from __future__ import annotations

from uuid import uuid4

from app.domain.ai_provider import generate_rag_answer
from app.domain.system_prompts import SystemPromptLayer, SystemPromptResolution, system_prompt_hash


def test_generate_rag_answer_preserves_ordered_system_prompt_layers_without_citations() -> None:
    model_version_id = uuid4()
    global_version_id = uuid4()
    content = "[backend_default]\nbase\n\n[model]\nmodel\n\n[global]\nglobal"
    resolution = SystemPromptResolution(
        content=content,
        source="global",
        version_id=global_version_id,
        content_hash=system_prompt_hash(content),
        layers=(
            SystemPromptLayer(source="backend_default", version_id=None, content_hash=system_prompt_hash("base"), content_length=4, order=1),
            SystemPromptLayer(source="model", version_id=model_version_id, content_hash=system_prompt_hash("model"), content_length=5, order=2),
            SystemPromptLayer(source="global", version_id=global_version_id, content_hash=system_prompt_hash("global"), content_length=6, order=3),
        ),
    )

    result = generate_rag_answer(question="What is the policy?", citations=[], model=None, system_prompt=resolution)

    assert result.system_prompt_source == "global"
    assert result.system_prompt_version_id == global_version_id
    assert result.system_prompt_content_hash == resolution.content_hash
    assert result.system_prompt_layers == [
        {"source": "backend_default", "version_id": None, "content_hash": system_prompt_hash("base"), "content_length": 4, "order": 1},
        {"source": "model", "version_id": str(model_version_id), "content_hash": system_prompt_hash("model"), "content_length": 5, "order": 2},
        {"source": "global", "version_id": str(global_version_id), "content_hash": system_prompt_hash("global"), "content_length": 6, "order": 3},
    ]
