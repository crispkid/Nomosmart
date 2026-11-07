from __future__ import annotations

from pathlib import Path

import pytest

from app.api.routes.system_prompts import _validate_content
from app.core.errors import AppError


def test_system_prompt_content_rejects_blank_effective_versions() -> None:
    with pytest.raises(AppError) as caught:
        _validate_content(" \n\t ")

    assert caught.value.code == "system_prompt_blank"
    assert caught.value.status_code == 422


def test_system_prompt_content_allows_blank_inactive_placeholders() -> None:
    _validate_content(" \n\t ", allow_blank=True)


def test_system_prompt_deactivate_route_marks_versions_inactive() -> None:
    source = (Path(__file__).resolve().parents[1] / "app/api/routes/system_prompts.py").read_text(encoding="utf-8")

    assert "def deactivate_system_prompt" in source
    assert "update(SystemPromptVersion).where(SystemPromptVersion.prompt_id == prompt.id).values(is_active=False)" in source
