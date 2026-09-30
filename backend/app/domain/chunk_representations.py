from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any
from uuid import UUID, uuid5

from app.core.errors import AppError
from app.domain.markdown_structure import MarkdownStructureParser, visible_markdown_text
from app.domain.retrieval_text import RetrievalTextNormalizer, provisional_retrieval_hash
from app.domain.structure_chunking import CHUNKER_VERSION, ChunkDraft, ChunkingConfig, StructureAwareChunker
from app.domain.tokenization import UnicodeTokenCounter


DISPLAY_PROJECTION_VERSION = "markdown-display-projection-v1"
MANUAL_REPRESENTATION_VERSION = "manual-chunk-representation-v1"


@dataclass(frozen=True)
class ManualChunkRepresentation:
    """The four deliberately separate representations of a manual Chunk.

    ``raw_markdown`` is exact trace evidence, ``display_markdown`` is renderer
    input, ``display_text`` is the compatibility/LLM projection, and only
    ``retrieval_text`` may later be submitted to an embedding Provider.
    """

    raw_markdown: str
    display_markdown: str
    display_text: str
    retrieval_text: str
    content_type: str
    heading_path: tuple[str, ...]
    heading_level: int | None
    token_count: int
    content_hash: str
    stable_chunk_key: str
    embedding_content_hash: str
    processing_metadata: dict[str, Any]


def build_manual_chunk_representation(
    *,
    raw_markdown: str,
    document_title: str | None,
    inherited_heading_path: tuple[str, ...] | list[str] | None = None,
    inherited_heading_level: int | None = None,
    content_type: str | None = None,
    config_snapshot: dict[str, Any] | None = None,
) -> ManualChunkRepresentation:
    """Parse and normalize a validated manual canonical Markdown fragment.

    The function intentionally has no shortcut accepting a pre-normalized
    ``retrieval_text``.  Every manual create/edit/split therefore crosses the
    same parser and retrieval-normalizer boundary.
    """

    if not isinstance(raw_markdown, str) or not raw_markdown.strip():
        raise AppError("manual_chunk_blank", "Manual chunk content cannot be blank", status_code=422)

    config = chunking_config_from_snapshot(config_snapshot)
    parser = MarkdownStructureParser()
    structure = parser.parse(raw_markdown)
    counter = UnicodeTokenCounter()
    drafts = StructureAwareChunker(config=config, token_counter=counter).chunk(
        structure,
        document_key=sha256(raw_markdown.encode("utf-8")).hexdigest(),
        version_id=UUID("00000000-0000-0000-0000-000000000283"),
    )

    display_parts = [draft.display_text for draft in drafts if draft.display_text.strip()]
    display_text = "\n\n".join(display_parts).strip() or visible_markdown_text(raw_markdown).strip()
    if not display_text:
        raise AppError("manual_chunk_representation_invalid", "Manual Markdown did not produce display text", status_code=422)

    inherited_path = tuple(str(value).strip() for value in (inherited_heading_path or ()) if str(value).strip())
    parsed_path = _deepest_heading_path(drafts)
    heading_path = _merge_heading_paths(inherited_path, parsed_path)
    heading_level = inherited_heading_level
    if parsed_path:
        heading_level = next((draft.heading_level for draft in reversed(drafts) if draft.heading_path == parsed_path and draft.heading_level is not None), heading_level)

    resolved_types = {draft.content_type for draft in drafts if draft.content_type}
    resolved_type = content_type or (next(iter(resolved_types)) if len(resolved_types) == 1 else "mixed")
    stable_payload = {
        "document_title": (document_title or "").strip(),
        "raw_sha256": sha256(raw_markdown.encode("utf-8")).hexdigest(),
        "display_sha256": sha256(raw_markdown.encode("utf-8")).hexdigest(),
        "text_sha256": sha256(display_text.encode("utf-8")).hexdigest(),
        "heading_path": heading_path,
        "content_type": resolved_type,
        "parser_version": parser.version,
        "chunker_version": CHUNKER_VERSION,
        "normalizer_version": RetrievalTextNormalizer(config=config, token_counter=counter).version,
        "tokenizer_version": counter.version,
        "config": config.snapshot(),
    }
    stable_key = sha256(json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    draft = ChunkDraft(
        id=uuid5(UUID("00000000-0000-0000-0000-000000000283"), stable_key),
        stable_chunk_key=stable_key,
        sequence=1,
        display_text=display_text,
        display_markdown=raw_markdown,
        raw_markdown=raw_markdown,
        heading_path=heading_path,
        heading_level=heading_level,
        content_type=resolved_type,
        start_offset=0,
        end_offset=len(raw_markdown),
        node_ids=tuple(node.id for node in structure.nodes if node.type != "document"),
        token_count=counter.count(display_text),
        metadata={},
    )
    normalizer = RetrievalTextNormalizer(config=config, token_counter=counter)
    retrieval_text = normalizer.normalize(draft, document_title=document_title).strip()
    if not retrieval_text:
        raise AppError("manual_chunk_representation_invalid", "Manual Markdown did not produce retrieval text", status_code=422)

    processing_metadata = {
        "parser_version": parser.version,
        "chunker_version": CHUNKER_VERSION,
        "normalizer_version": normalizer.version,
        "tokenizer_version": counter.version,
        "display_projection_version": DISPLAY_PROJECTION_VERSION,
        "manual_representation_version": MANUAL_REPRESENTATION_VERSION,
        "effective_chunk_config": config.snapshot(),
        "parse_warnings": list(structure.warnings),
        "structure_aware": True,
    }
    preprocessing_hash = provisional_retrieval_hash(
        retrieval_text=retrieval_text,
        normalizer_version=normalizer.version,
        tokenizer_version=counter.version,
    )
    return ManualChunkRepresentation(
        raw_markdown=raw_markdown,
        display_markdown=raw_markdown,
        display_text=display_text,
        retrieval_text=retrieval_text,
        content_type=resolved_type,
        heading_path=heading_path,
        heading_level=heading_level,
        token_count=counter.count(retrieval_text),
        content_hash=sha256(display_text.encode("utf-8")).hexdigest(),
        stable_chunk_key=stable_key,
        embedding_content_hash=preprocessing_hash,
        processing_metadata=processing_metadata,
    )


def chunking_config_from_snapshot(snapshot: dict[str, Any] | None) -> ChunkingConfig:
    if not isinstance(snapshot, dict):
        return ChunkingConfig()
    allowed = {
        "target_chunk_tokens",
        "max_chunk_tokens",
        "min_chunk_tokens",
        "chunk_overlap_tokens",
        "heading_context_enabled",
        "max_heading_depth",
        "max_context_prefix_tokens",
        "document_title_context_enabled",
        "table_chunk_max_rows",
        "remove_repeated_header_footer",
    }
    values = {key: snapshot[key] for key in allowed if key in snapshot}
    try:
        return ChunkingConfig(**values)
    except (TypeError, ValueError):
        raise AppError("manual_chunk_config_invalid", "Manual chunk configuration is invalid", status_code=409) from None


def _deepest_heading_path(drafts: list[ChunkDraft]) -> tuple[str, ...]:
    paths = [draft.heading_path for draft in drafts if draft.heading_path]
    return max(paths, key=len, default=())


def _merge_heading_paths(inherited: tuple[str, ...], parsed: tuple[str, ...]) -> tuple[str, ...]:
    if not parsed:
        return inherited
    if not inherited:
        return parsed
    maximum_overlap = min(len(inherited), len(parsed))
    for size in range(maximum_overlap, 0, -1):
        if inherited[-size:] == parsed[:size]:
            return (*inherited, *parsed[size:])
    return (*inherited, *parsed)
