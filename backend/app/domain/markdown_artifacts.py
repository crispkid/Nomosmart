from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import DocumentVersion, PipelineRun, PipelineRunStep
from app.domain.document_layout import renderable_source_anchors
from app.domain.markdown_structure import MarkdownStructureParser


MarkdownArtifactStatus = Literal["available", "processing", "missing", "failed", "invalid"]


@dataclass(frozen=True)
class MarkdownArtifactResult:
    status: MarkdownArtifactStatus
    reason_code: str | None
    text: str | None


@dataclass(frozen=True)
class SourceRange:
    start: int
    end: int


def resolve_markdown_artifact(session: Session, version: DocumentVersion, *, require_fingerprint: bool = False) -> MarkdownArtifactResult:
    pipeline = session.scalar(
        select(PipelineRun)
        .where(PipelineRun.document_version_id == version.id)
        .order_by(desc(PipelineRun.created_at))
        .limit(1)
    )
    if pipeline is None:
        return MarkdownArtifactResult("missing", "markdown_artifact_missing", None)

    step = session.scalar(
        select(PipelineRunStep).where(
            PipelineRunStep.run_id == pipeline.id,
            PipelineRunStep.step_name == "generate_markdown",
        )
    )
    if step is None:
        if pipeline.status in {"queued", "running", "processing", "waiting_action"}:
            return MarkdownArtifactResult("processing", "markdown_artifact_pending", None)
        return MarkdownArtifactResult("missing", "markdown_artifact_missing", None)
    if step.status in {"pending", "queued", "running", "processing", "waiting_action"}:
        return MarkdownArtifactResult("processing", "markdown_artifact_pending", None)
    if step.status == "failed":
        return MarkdownArtifactResult("failed", "markdown_artifact_step_failed", None)
    if step.status != "completed":
        return MarkdownArtifactResult("invalid", "markdown_artifact_invalid", None)

    expected_ref = markdown_artifact_ref(version.id)
    if version.markdown_artifact_uri != expected_ref or step.output_artifact_ref != expected_ref:
        return MarkdownArtifactResult("invalid", "markdown_artifact_version_mismatch", None)
    payload = step.artifact_payload
    markdown = payload.get("markdown") if isinstance(payload, dict) else None
    if not isinstance(markdown, str) or not markdown.strip():
        return MarkdownArtifactResult("invalid", "markdown_artifact_invalid", None)
    if require_fingerprint:
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        if not step.artifact_fingerprint or step.artifact_fingerprint != digest:
            return MarkdownArtifactResult("invalid", "markdown_artifact_invalid", None)
    return MarkdownArtifactResult("available", None, markdown)


def markdown_artifact_ref(version_id: UUID) -> str:
    return f"artifact://document_versions/{version_id}/generate_markdown"


def paragraph_source_ranges(markdown: str) -> dict[str, SourceRange]:
    ranges: dict[str, SourceRange] = {}
    cursor = 0
    index = 0
    for raw_part in re.split(r"\n\s*\n", markdown):
        content = raw_part.strip()
        if not content:
            continue
        start = markdown.find(content, cursor)
        if start < 0:
            continue
        index += 1
        end = start + len(content)
        ranges[f"paragraph-{index}"] = SourceRange(start, end)
        cursor = end
    return ranges


def normalize_source_mappings(
    content: str,
    source_mapping: list[Any] | None,
    markdown: str | None,
) -> list[dict[str, Any]]:
    mappings = [dict(item) for item in (source_mapping or []) if isinstance(item, dict)]
    if not mappings:
        return []
    anchors = paragraph_source_ranges(markdown) if markdown is not None else {}
    structure = MarkdownStructureParser().parse(markdown) if markdown is not None and any(
        mapping.get("mapping_content") == "markdown_fragment_v2" for mapping in mappings
    ) else None
    return [
        _normalize_structured_mapping(mapping, markdown, structure)
        if mapping.get("mapping_content") == "markdown_fragment_v2"
        else _normalize_mapping(content, mapping, markdown, anchors)
        for mapping in mappings
    ]


def _normalize_structured_mapping(
    mapping: dict[str, Any],
    markdown: str | None,
    structure,
) -> dict[str, Any]:
    result = dict(mapping)
    result["offset_unit"] = "unicode_code_point"
    if markdown is None or structure is None:
        return _unresolved(result, "markdown_artifact_unavailable")
    fragment_range = _range(mapping.get("markdown_start_offset"), mapping.get("markdown_end_offset"))
    if fragment_range is None or fragment_range.end > len(markdown):
        return _unresolved(result, "source_range_missing")
    fragment = markdown[fragment_range.start : fragment_range.end]
    expected_digest = mapping.get("markdown_fragment_sha256")
    actual_digest = hashlib.sha256(fragment.encode("utf-8")).hexdigest()
    if not isinstance(expected_digest, str) or expected_digest != actual_digest:
        return _unresolved(result, "markdown_fragment_hash_mismatch")

    anchor_ranges = renderable_source_anchors(
        structure,
        start_offset=fragment_range.start,
        end_offset=fragment_range.end,
    )
    if not anchor_ranges:
        return _unresolved(result, "source_anchor_unresolved")
    resolved_anchors = [str(value["source_anchor"]) for value in anchor_ranges]

    declared_anchors = mapping.get("source_anchors")
    if isinstance(declared_anchors, list):
        declared = _ordered_strings(declared_anchors)
        if declared != resolved_anchors:
            return _unresolved(result, "source_anchor_set_mismatch")
    declared_nodes = mapping.get("node_ids")
    if isinstance(declared_nodes, list):
        node_ids = set(_ordered_strings(declared_nodes))
        if any(anchor not in node_ids for anchor in resolved_anchors):
            return _unresolved(result, "source_anchor_set_mismatch")
    declared_first = mapping.get("source_anchor")
    if isinstance(declared_first, str) and declared_first and declared_first != resolved_anchors[0]:
        return _unresolved(result, "source_anchor_order_mismatch")

    first_range = anchor_ranges[0]
    result.update({
        "source_anchor": resolved_anchors[0],
        "source_anchors": resolved_anchors,
        "source_anchor_ranges": anchor_ranges,
        "offset_scope": "canonical_markdown",
        "markdown_start_offset": fragment_range.start,
        "markdown_end_offset": fragment_range.end,
        "anchor_start_offset": first_range["anchor_start_offset"],
        "anchor_end_offset": first_range["anchor_end_offset"],
        "mapping_status": "resolved",
    })
    result.pop("mapping_reason_code", None)
    return result


def _ordered_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return result


def resolve_manual_source_mapping(
    *,
    content: str,
    markdown: str,
    source_anchor: str,
    start_offset: int,
    end_offset: int,
    offset_scope: str,
    offset_unit: str,
) -> dict[str, Any] | None:
    if offset_unit != "unicode_code_point" or _range(start_offset, end_offset) is None:
        return None
    structure = MarkdownStructureParser().parse(markdown)
    if offset_scope == "canonical_markdown":
        if not _text_matches(markdown, SourceRange(start_offset, end_offset), content):
            return None
        ranges = renderable_source_anchors(structure, start_offset=start_offset, end_offset=end_offset)
        if not ranges:
            return None
        # The raw source viewer may select across blocks (or previously unchunked
        # text). The backend resolves the exact ordered AST identity, never a
        # substring guess. Legacy anchors still need to contain the start.
        legacy = paragraph_source_ranges(markdown).get(source_anchor)
        if source_anchor != ranges[0]["source_anchor"] and not (
            source_anchor == "markdown-document" or legacy and legacy.start <= start_offset < legacy.end
        ):
            return None
        return _normalize_structured_mapping({
            "source_anchor": ranges[0]["source_anchor"],
            "source_anchors": [item["source_anchor"] for item in ranges],
            "view_mode": "markdown",
            "start_offset": start_offset, "end_offset": end_offset,
            "markdown_start_offset": start_offset, "markdown_end_offset": end_offset,
            "mapping_content": "markdown_fragment_v2",
            "markdown_fragment_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }, markdown, structure)
    anchor = paragraph_source_ranges(markdown).get(source_anchor)
    if anchor is None:
        node = next((node for node in structure.nodes if node.id == source_anchor), None)
        if node is not None:
            anchor = SourceRange(node.start_offset, node.end_offset)
    if anchor is None:
        return None
    if offset_scope == "source_anchor":
        anchor_text = markdown[anchor.start : anchor.end]
        direct_range = SourceRange(start_offset, end_offset)
        if _text_matches(anchor_text, direct_range, content):
            anchor_range = direct_range
        else:
            return None
        markdown_range = SourceRange(anchor.start + anchor_range.start, anchor.start + anchor_range.end)
    else:
        return None
    # Persist the same canonical identity contract as automatically parsed chunks.
    resolved = resolve_manual_source_mapping(content=content, markdown=markdown,
        source_anchor="markdown-document", start_offset=markdown_range.start,
        end_offset=markdown_range.end, offset_scope="canonical_markdown", offset_unit=offset_unit)
    if resolved:
        resolved["view_mode"] = "original"
    return resolved


def _normalize_mapping(
    content: str,
    mapping: dict[str, Any],
    markdown: str | None,
    anchors: dict[str, SourceRange],
) -> dict[str, Any]:
    result = dict(mapping)
    result["offset_unit"] = "unicode_code_point"
    anchor_name = mapping.get("source_anchor")
    anchor = anchors.get(anchor_name) if isinstance(anchor_name, str) else None
    if markdown is None or anchor is None:
        return _unresolved(result, "markdown_artifact_unavailable" if markdown is None else "source_anchor_unresolved")

    comparison_content = content
    if mapping.get("mapping_content") == "markdown_fragment_v2":
        fragment_range = _range(mapping.get("markdown_start_offset"), mapping.get("markdown_end_offset"))
        if fragment_range is None or fragment_range.end > len(markdown):
            return _unresolved(result, "source_range_missing")
        comparison_content = markdown[fragment_range.start : fragment_range.end]
        expected_digest = mapping.get("markdown_fragment_sha256")
        actual_digest = hashlib.sha256(comparison_content.encode("utf-8")).hexdigest()
        if not isinstance(expected_digest, str) or expected_digest != actual_digest:
            return _unresolved(result, "markdown_fragment_hash_mismatch")

    explicit_markdown = _range(mapping.get("markdown_start_offset"), mapping.get("markdown_end_offset"))
    explicit_anchor = _range(mapping.get("anchor_start_offset"), mapping.get("anchor_end_offset"))
    explicit = _validated_pair(comparison_content, markdown, anchor, explicit_markdown, explicit_anchor)
    if explicit is not None:
        markdown_range, anchor_range = explicit
        return _resolved(result, markdown_range, anchor_range, str(mapping.get("offset_scope") or "canonical_markdown"))

    stored = _range(mapping.get("start_offset", mapping.get("start")), mapping.get("end_offset", mapping.get("end")))
    if stored is None:
        return _unresolved(result, "source_range_missing")

    candidates: list[tuple[SourceRange, SourceRange, str]] = []
    if _text_matches(markdown, stored, comparison_content) and anchor.start <= stored.start and stored.end <= anchor.end:
        candidates.append((stored, SourceRange(stored.start - anchor.start, stored.end - anchor.start), "canonical_markdown"))

    anchor_global = SourceRange(anchor.start + stored.start, anchor.start + stored.end)
    if 0 <= stored.start <= stored.end <= anchor.end - anchor.start and _text_matches(markdown, anchor_global, comparison_content):
        candidates.append((anchor_global, stored, "source_anchor"))

    unique: dict[tuple[int, int, int, int], tuple[SourceRange, SourceRange, str]] = {}
    for candidate in candidates:
        key = (candidate[0].start, candidate[0].end, candidate[1].start, candidate[1].end)
        unique.setdefault(key, candidate)
    if len(unique) != 1:
        return _unresolved(result, "source_range_ambiguous" if unique else "source_range_mismatch")
    markdown_range, anchor_range, inferred_scope = next(iter(unique.values()))
    declared_scope = mapping.get("offset_scope")
    if declared_scope is not None and declared_scope != inferred_scope:
        return _unresolved(result, "source_range_scope_mismatch")
    return _resolved(result, markdown_range, anchor_range, inferred_scope)


def _validated_pair(
    content: str,
    markdown: str,
    anchor: SourceRange,
    markdown_range: SourceRange | None,
    anchor_range: SourceRange | None,
) -> tuple[SourceRange, SourceRange] | None:
    if markdown_range is None and anchor_range is None:
        return None
    if markdown_range is None and anchor_range is not None:
        markdown_range = SourceRange(anchor.start + anchor_range.start, anchor.start + anchor_range.end)
    if anchor_range is None and markdown_range is not None:
        anchor_range = SourceRange(markdown_range.start - anchor.start, markdown_range.end - anchor.start)
    if markdown_range is None or anchor_range is None:
        return None
    if markdown_range.start != anchor.start + anchor_range.start or markdown_range.end != anchor.start + anchor_range.end:
        return None
    if not (anchor.start <= markdown_range.start <= markdown_range.end <= anchor.end):
        return None
    if not _text_matches(markdown, markdown_range, content):
        return None
    return markdown_range, anchor_range


def _range(start: object, end: object) -> SourceRange | None:
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
        return None
    if start < 0 or end <= start:
        return None
    return SourceRange(start, end)


def _text_matches(markdown: str, source_range: SourceRange, content: str) -> bool:
    return 0 <= source_range.start <= source_range.end <= len(markdown) and markdown[source_range.start : source_range.end] == content


def _resolved(result: dict[str, Any], markdown_range: SourceRange, anchor_range: SourceRange, scope: str) -> dict[str, Any]:
    result.update(
        {
            "offset_scope": scope,
            "markdown_start_offset": markdown_range.start,
            "markdown_end_offset": markdown_range.end,
            "anchor_start_offset": anchor_range.start,
            "anchor_end_offset": anchor_range.end,
            "mapping_status": "resolved",
        }
    )
    result.pop("mapping_reason_code", None)
    return result


def _unresolved(result: dict[str, Any], reason: str) -> dict[str, Any]:
    result.update(
        {
            "markdown_start_offset": None,
            "markdown_end_offset": None,
            "anchor_start_offset": None,
            "anchor_end_offset": None,
            "mapping_status": "unresolved",
            "mapping_reason_code": reason,
        }
    )
    return result
