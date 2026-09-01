from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Any


_MARKDOWN_HEADING = re.compile(r"^\s*#{1,6}(?:\s+|$)")
_LIST_PREFIX = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_VARIATION_SELECTORS = range(0xFE00, 0xFE10)
_EMOJI_MODIFIERS = range(0x1F3FB, 0x1F400)
_REGIONAL_INDICATORS = range(0x1F1E6, 0x1F200)


def fuse_ranked_hits(
    vector_hits: Sequence[dict[str, Any]],
    keyword_hits: Sequence[dict[str, Any]],
    *,
    rank_constant: int = 60,
) -> list[dict[str, Any]]:
    """Return a deterministic reciprocal-rank fusion over the complete union."""

    vector_rank, vector_by_id = _ranked_hits(vector_hits)
    keyword_rank, keyword_by_id = _ranked_hits(keyword_hits)
    fused: list[tuple[float, int, str, dict[str, Any]]] = []
    missing_rank = len(vector_hits) + len(keyword_hits) + 1

    for hit_id in set(vector_rank) | set(keyword_rank):
        v_rank = vector_rank.get(hit_id)
        k_rank = keyword_rank.get(hit_id)
        score = 0.0
        if v_rank is not None:
            score += 1.0 / (rank_constant + v_rank)
        if k_rank is not None:
            score += 1.0 / (rank_constant + k_rank)
        hit = dict(vector_by_id.get(hit_id) or keyword_by_id[hit_id])
        hit["_score"] = score
        fused.append(
            (
                score,
                min(v_rank or missing_rank, k_rank or missing_rank),
                hit_id,
                hit,
            )
        )

    fused.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[-1] for item in fused]


def is_markdown_heading_only(content: str | None) -> bool:
    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    return bool(lines) and all(_MARKDOWN_HEADING.match(line) for line in lines)


def is_structural_only(content: str | None, *, lead_in_grapheme_limit: int = 40) -> bool:
    text = (content or "").strip()
    if not text:
        return False
    if is_markdown_heading_only(text):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    line = lines[0]
    if not line.endswith((":", "：")):
        return False
    if _LIST_PREFIX.match(line) or "|" in line:
        return False
    return grapheme_length(line) <= lead_in_grapheme_limit


def grapheme_length(value: str) -> int:
    """Count the grapheme forms needed by the bounded structural classifier."""

    count = 0
    previous = ""
    regional_run = 0
    for character in value:
        codepoint = ord(character)
        is_regional = codepoint in _REGIONAL_INDICATORS
        extends_previous = (
            bool(previous)
            and (
                unicodedata.category(character).startswith("M")
                or codepoint in _VARIATION_SELECTORS
                or codepoint in _EMOJI_MODIFIERS
                or character == "\u200d"
                or previous == "\u200d"
                or (is_regional and regional_run % 2 == 1)
            )
        )
        if not extends_previous:
            count += 1
        regional_run = regional_run + 1 if is_regional else 0
        previous = character
    return count


def _ranked_hits(hits: Sequence[dict[str, Any]]) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    ranks: dict[str, int] = {}
    values: dict[str, dict[str, Any]] = {}
    for rank, hit in enumerate(hits, start=1):
        hit_id = _hit_identity(hit)
        if hit_id is None or hit_id in ranks:
            continue
        ranks[hit_id] = rank
        values[hit_id] = hit
    return ranks, values


def _hit_identity(hit: dict[str, Any]) -> str | None:
    value = hit.get("_id")
    return str(value) if value is not None and str(value) else None
