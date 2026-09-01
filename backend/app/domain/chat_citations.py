from __future__ import annotations

import re
from copy import deepcopy
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Chunk


_CITATION_MARKER = re.compile(r"\[(\d+)\]")
_TRANSIENT_CITATION_FIELDS = {"display_markdown", "generation_text", "raw_markdown"}
_PERSISTED_CITATION_FIELDS = {
    "document_id",
    "document_version_id",
    "chunk_id",
    "chunk_index",
    "title",
    "score",
    "excerpt",
    "content_type",
    "heading_path",
    "page",
    "source_mapping",
    "index_name",
}


@dataclass(frozen=True)
class CompactCitationView:
    """Authorization-safe response copy of the sources an answer actually cites."""

    answer: str | None
    citations: list[Any]
    source_ordinals: tuple[int, ...]


class CitationStreamCompactor:
    """Incrementally apply the first-use citation mapping to streamed text."""

    def __init__(self, citation_count: int) -> None:
        self.citation_count = citation_count
        self._pending = ""
        self._source_ordinals: list[int] = []

    @property
    def source_ordinals(self) -> tuple[int, ...]:
        return tuple(self._source_ordinals)

    def feed(self, text: str) -> str:
        combined = self._pending + text
        self._pending = ""
        partial = re.search(r"\[\d*$", combined)
        if partial is not None:
            self._pending = combined[partial.start() :]
            combined = combined[: partial.start()]
        return _CITATION_MARKER.sub(self._replace_marker, combined)

    def finish(self) -> str:
        pending = self._pending
        self._pending = ""
        return pending

    def _replace_marker(self, match: re.Match[str]) -> str:
        source = int(match.group(1))
        if source < 1 or source > self.citation_count:
            _raise_invalid_markers(self.citation_count, [source])
        if source not in self._source_ordinals:
            self._source_ordinals.append(source)
        return f"[{self._source_ordinals.index(source) + 1}]"


def citation_persistence_payload(citation: Any) -> dict[str, Any]:
    """Return the compact audit form without authorized display bodies.

    Full display Markdown is hydrated only for an authorized response. It must
    not be copied into ChatRecord/validation/public-request persistence merely
    because the response model carries the transient presentation field.
    """

    if hasattr(citation, "model_dump"):
        payload = citation.model_dump(mode="json", exclude=_TRANSIENT_CITATION_FIELDS)
    elif isinstance(citation, dict):
        payload = deepcopy(citation)
    else:
        raise TypeError("citation must be a model or mapping")
    for field in _TRANSIENT_CITATION_FIELDS:
        payload.pop(field, None)
    return {field: payload[field] for field in _PERSISTED_CITATION_FIELDS if field in payload}


def validate_citation_markers(answer: str | None, citation_count: int) -> None:
    """Fail closed when a provider emits a numeric source marker outside 1..N."""

    markers = [int(value) for value in _CITATION_MARKER.findall(answer or "")]
    invalid = sorted({value for value in markers if value < 1 or value > citation_count})
    if invalid:
        _raise_invalid_markers(citation_count, invalid)


def compact_citation_view(answer: str | None, citations: Sequence[Any] | None) -> CompactCitationView:
    """Map valid raw source ordinals to consecutive response-only ordinals.

    Persisted provider answers and prompt candidates remain untouched. Invalid
    legacy markers are left verbatim so the existing UI mismatch treatment can
    fail closed without turning history reads into errors.
    """

    source_citations = list(citations or [])
    source_ordinals: list[int] = []
    for match in _CITATION_MARKER.finditer(answer or ""):
        ordinal = int(match.group(1))
        if 1 <= ordinal <= len(source_citations) and ordinal not in source_ordinals:
            source_ordinals.append(ordinal)

    display_ordinals = {source: display for display, source in enumerate(source_ordinals, start=1)}

    def replace_marker(match: re.Match[str]) -> str:
        source = int(match.group(1))
        display = display_ordinals.get(source)
        return f"[{display}]" if display is not None else match.group(0)

    compact_answer = _CITATION_MARKER.sub(replace_marker, answer) if answer is not None else None
    compact_citations = [deepcopy(source_citations[ordinal - 1]) for ordinal in source_ordinals]
    return CompactCitationView(
        answer=compact_answer,
        citations=compact_citations,
        source_ordinals=tuple(source_ordinals),
    )


def _raise_invalid_markers(citation_count: int, invalid: list[int]) -> None:
    raise AppError(
        "provider_response_contract_invalid",
        "Chat Model response citations do not match the available sources",
        status_code=502,
        details={"citation_count": citation_count, "invalid_source_ordinals": sorted(set(invalid))},
    )


def hydrate_citation_groups(
    session: Session,
    citation_groups: Sequence[list[Any] | None],
    *,
    project_id: UUID,
    allowed_version_ids: set[UUID],
) -> list[list[Any]]:
    """Hydrate authorized citation response copies with canonical Chunk data.

    The caller must establish actor/surface authorization before invoking this
    compatibility helper. Persisted JSON objects are never mutated, and any
    transient bodies found in legacy JSON are discarded before the authorized
    database projection is applied.
    """

    normalized_groups = [list(group or []) for group in citation_groups]
    if not normalized_groups or not allowed_version_ids:
        return [
            [_without_transient_bodies(item) if isinstance(item, dict) else item for item in group]
            for group in normalized_groups
        ]

    chunk_ids: set[UUID] = set()
    for group in normalized_groups:
        for citation in group:
            if not isinstance(citation, dict):
                continue
            chunk_id = _uuid_or_none(citation.get("chunk_id"))
            if chunk_id is not None:
                chunk_ids.add(chunk_id)

    chunks_by_id = (
        {
            chunk.id: chunk
            for chunk in session.scalars(
                select(Chunk).where(
                    Chunk.id.in_(chunk_ids),
                    Chunk.project_id == project_id,
                    Chunk.document_version_id.in_(allowed_version_ids),
                    Chunk.status == "active",
                )
            )
        }
        if chunk_ids
        else {}
    )

    hydrated_groups: list[list[Any]] = []
    for group in normalized_groups:
        hydrated: list[Any] = []
        for citation in group:
            if not isinstance(citation, dict):
                hydrated.append(citation)
                continue
            response_citation = _without_transient_bodies(citation)
            chunk = chunks_by_id.get(_uuid_or_none(response_citation.get("chunk_id")))
            if chunk is not None and _citation_matches_chunk(response_citation, chunk, allowed_version_ids):
                if response_citation.get("chunk_index") is None:
                    response_citation["chunk_index"] = chunk.chunk_index
                response_citation["display_markdown"] = chunk_display_markdown(chunk)
            hydrated.append(response_citation)
        hydrated_groups.append(hydrated)
    return hydrated_groups


def chunk_display_markdown(chunk: Chunk) -> str:
    """Return the presentation body without ever consulting retrieval text."""

    for value in (chunk.display_markdown, chunk.markdown_content, chunk.content):
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _without_transient_bodies(citation: dict[str, Any]) -> dict[str, Any]:
    # Treat legacy JSON as untrusted.  In particular, do not let historical
    # ``content``, ``markdown_content`` or ``retrieval_text`` keys bypass the
    # current Project/version/Chunk authorization and canonical hydration.
    return {field: citation[field] for field in _PERSISTED_CITATION_FIELDS if field in citation}


def _citation_matches_chunk(citation: dict[str, Any], chunk: Chunk, allowed_version_ids: set[UUID]) -> bool:
    document_id = _uuid_or_none(citation.get("document_id"))
    version_id = _uuid_or_none(citation.get("document_version_id"))
    return (
        document_id == chunk.document_id
        and version_id == chunk.document_version_id
        and version_id in allowed_version_ids
    )


def _uuid_or_none(value: Any) -> UUID | None:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None
