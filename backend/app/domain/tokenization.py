from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol


TOKEN_PATTERN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+(?:[-./][A-Za-z0-9_]+)*|[^\s]", re.UNICODE)


class TokenCounter(Protocol):
    @property
    def version(self) -> str: ...

    def count(self, text: str) -> int: ...

    def truncate(self, text: str, max_tokens: int) -> str: ...


@dataclass(frozen=True)
class UnicodeTokenCounter:
    """Deterministic tokenizer fallback when a provider tokenizer is unavailable.

    This counter is deliberately versioned and conservative for CJK. It is not
    presented as the provider's billable token count; callers persist the version
    so a later model-specific counter invalidates the embedding content hash.
    """

    model_name: str | None = None

    @property
    def version(self) -> str:
        suffix = f":{self.model_name}" if self.model_name else ""
        return f"unicode-regex-v1{suffix}"

    def count(self, text: str) -> int:
        return len(TOKEN_PATTERN.findall(text or ""))

    def truncate(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        matches = list(TOKEN_PATTERN.finditer(text or ""))
        if len(matches) <= max_tokens:
            return text
        return text[: matches[max_tokens - 1].end()].rstrip()


def sentence_ranges(text: str) -> list[tuple[int, int]]:
    """Return Unicode-safe sentence ranges without changing source text."""

    ranges: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"(?:[。！？!?；;]+|\.(?=\s|$)|\n+)", text):
        end = match.end()
        if text[start:end].strip():
            ranges.append((start, end))
        start = end
    if text[start:].strip():
        ranges.append((start, len(text)))
    return ranges or ([(0, len(text))] if text else [])


def token_windows(text: str, *, max_tokens: int) -> list[tuple[int, int]]:
    """Split source into lossless Unicode-safe windows at token boundaries."""

    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    matches = list(TOKEN_PATTERN.finditer(text or ""))
    if not matches:
        return [(0, len(text))] if text else []
    windows: list[tuple[int, int]] = []
    for index in range(0, len(matches), max_tokens):
        first = matches[index]
        last = matches[min(index + max_tokens, len(matches)) - 1]
        start = 0 if index == 0 else first.start()
        end = len(text) if index + max_tokens >= len(matches) else last.end()
        windows.append((start, end))
    return windows
