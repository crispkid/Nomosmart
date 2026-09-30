from __future__ import annotations

from copy import deepcopy
from math import ceil
import re
import unicodedata
from typing import Any

from app.domain.markdown_structure import DocumentNode, DocumentStructure


LAYOUT_VERSION = "document-layout-v2"
PAGINATOR_VERSION = "structure-paginator-v2"
DEFAULT_PAGE_WIDTH = 794
DEFAULT_PAGE_HEIGHT = 1123
DEFAULT_PAGE_BUDGET = 910
_TEXT_LINE_UNITS = 48
_NON_RENDERABLE_NODE_TYPES = {"document", "list_item", "table_row", "table_cell", "caption", "page_break"}


def is_renderable_layout_node(node: DocumentNode) -> bool:
    """Return whether a canonical structure node owns an interactive layout block."""

    return node.type not in _NON_RENDERABLE_NODE_TYPES and not node.metadata.get("structural_child")


def renderable_source_anchors(
    structure: DocumentStructure,
    *,
    start_offset: int,
    end_offset: int,
) -> list[dict[str, int | str]]:
    """Resolve exact top-level layout anchors intersecting one canonical range."""

    anchors: list[dict[str, int | str]] = []
    for node in structure.nodes:
        if not is_renderable_layout_node(node):
            continue
        start = max(start_offset, node.start_offset)
        end = min(end_offset, node.end_offset)
        if end <= start:
            continue
        anchors.append({
            "source_anchor": node.id,
            "markdown_start_offset": start,
            "markdown_end_offset": end,
            "anchor_start_offset": start - node.start_offset,
            "anchor_end_offset": end - node.start_offset,
        })
    return anchors


def build_document_layout(
    structure: DocumentStructure,
    *,
    page_budget: int = DEFAULT_PAGE_BUDGET,
) -> dict[str, Any]:
    """Build a deterministic, lossless layout artifact from structural nodes."""

    if page_budget < 96:
        raise ValueError("page_budget must be at least 96")
    source_blocks = [
        _block_from_node(node)
        for node in structure.nodes
        if is_renderable_layout_node(node)
    ]
    warnings: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    for source in source_blocks:
        try:
            parts = _split_block(source, page_budget)
        except Exception as exc:  # pragma: no cover - defensive fallback is intentional
            fallback = _fallback_block(source)
            parts = [fallback]
            warnings.append({"code": "layout_block_fallback", "block_id": source["id"], "error": type(exc).__name__})
        count = len(parts)
        visible_offset = 0
        for index, part in enumerate(parts, start=1):
            rendered = _finalize_continuation(part, source=source, index=index, count=count, visible_offset=visible_offset)
            visible_offset += len(_block_visible_text(part))
            if estimated_layout_block_height(rendered) > page_budget:
                warnings.append({"code": "layout_block_grow_required", "block_id": rendered["id"], "block_type": rendered["type"]})
            blocks.append(rendered)
    pages = paginate_layout_blocks(blocks, page_budget=page_budget)
    return {
        "status": "available",
        "reason_code": None,
        "source": f"{structure.parser_version}:{PAGINATOR_VERSION}",
        "layout_version": LAYOUT_VERSION,
        "pagination": {
            "paginator_version": PAGINATOR_VERSION,
            "page_budget": page_budget,
            "page_width": DEFAULT_PAGE_WIDTH,
            "page_height": DEFAULT_PAGE_HEIGHT,
            "lossless_overflow_policy": "grow",
        },
        "warnings": warnings,
        "pages": pages,
    }


def hydrate_document_layout_inline_markdown(
    artifact: dict[str, Any],
    structure: DocumentStructure,
) -> dict[str, Any]:
    """Add canonical inline semantics to a legacy layout without persisting it.

    Pagination, visible text, block identity and source ranges remain byte-for-
    value compatible with the stored artifact. Formatting is copied only when
    the canonical node and the visible legacy value agree.
    """

    hydrated = deepcopy(artifact)
    source_blocks = {
        node.id: _block_from_node(node)
        for node in structure.nodes
        if is_renderable_layout_node(node)
    }
    pages = hydrated.get("pages") if isinstance(hydrated.get("pages"), list) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            anchor = block.get("source_anchor")
            source = source_blocks.get(anchor) if isinstance(anchor, str) else None
            if source is not None:
                _hydrate_layout_block(block, source)
    return hydrated


def _hydrate_layout_block(block: dict[str, Any], source: dict[str, Any]) -> None:
    if block.get("type") != source.get("type"):
        return
    block_type = block.get("type")
    if block_type == "list":
        target_items = block.get("list_items") if isinstance(block.get("list_items"), list) else []
        source_items = source.get("list_items") if isinstance(source.get("list_items"), list) else []
        _hydrate_list_items(target_items, source_items)
        return
    if block_type == "table":
        if block.get("table_header") == source.get("table_header"):
            block["table_header_markdown"] = deepcopy(source.get("table_header_markdown") or source.get("table_header") or [])
        source_rows = source.get("rows") if isinstance(source.get("rows"), list) else []
        source_rows_markdown = source.get("rows_markdown") if isinstance(source.get("rows_markdown"), list) else []
        markdown_rows: list[list[str]] = []
        cursor = 0
        for row in block.get("rows") or []:
            matched = next((index for index in range(cursor, len(source_rows)) if source_rows[index] == row), None)
            if matched is None:
                markdown_rows.append([str(cell) for cell in row])
                continue
            markdown = source_rows_markdown[matched] if matched < len(source_rows_markdown) else row
            markdown_rows.append([str(cell) for cell in markdown])
            cursor = matched + 1
        block["rows_markdown"] = markdown_rows
        return
    if block_type == "image":
        if block.get("caption") == source.get("caption"):
            block["caption_markdown"] = source.get("caption_markdown") or source.get("caption")
        return
    if block.get("text") == source.get("text") and source.get("inline_markdown"):
        block["inline_markdown"] = source["inline_markdown"]


def _hydrate_list_items(targets: list[Any], sources: list[Any]) -> None:
    source_cursor = 0
    for target in targets:
        if not isinstance(target, dict):
            continue
        matched: dict[str, Any] | None = None
        for index in range(source_cursor, len(sources)):
            candidate = sources[index]
            if not isinstance(candidate, dict):
                continue
            if candidate.get("value") == target.get("value") and candidate.get("text") == target.get("text"):
                matched = candidate
                source_cursor = index + 1
                break
        if matched is None:
            continue
        if matched.get("inline_markdown"):
            target["inline_markdown"] = matched["inline_markdown"]
        target_child_lists = target.get("child_lists") if isinstance(target.get("child_lists"), list) else []
        source_child_lists = matched.get("child_lists") if isinstance(matched.get("child_lists"), list) else []
        for target_list, source_list in zip(target_child_lists, source_child_lists):
            if not isinstance(target_list, dict) or not isinstance(source_list, dict):
                continue
            target_children = target_list.get("items") if isinstance(target_list.get("items"), list) else []
            source_children = source_list.get("items") if isinstance(source_list.get("items"), list) else []
            _hydrate_list_items(target_children, source_children)


def paginate_layout_blocks(
    blocks: list[dict[str, Any]],
    *,
    page_budget: int = DEFAULT_PAGE_BUDGET,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_height = 0
    for block in blocks:
        height = estimated_layout_block_height(block)
        if current and current_height + height > page_budget:
            pages.append(_page(len(pages) + 1, current))
            current = []
            current_height = 0
        current.append(block)
        current_height += height
        if height > page_budget:
            pages.append(_page(len(pages) + 1, current))
            current = []
            current_height = 0
    if current or not pages:
        pages.append(_page(len(pages) + 1, current))
    return pages


def estimated_layout_block_height(block: dict[str, Any]) -> int:
    block_type = str(block.get("type") or "paragraph")
    if block_type == "heading":
        return 30 + _wrapped_lines(str(block.get("text") or ""), line_units=36) * 38
    if block_type == "list":
        list_items = _list_items(block)
        return 28 + sum(_list_item_height(item) for item in list_items)
    if block_type == "table":
        header = [str(value) for value in block.get("table_header") or []]
        rows = block.get("rows") if isinstance(block.get("rows"), list) else []
        columns = max(1, len(header), max((len(row) for row in rows if isinstance(row, list)), default=0))
        cell_units = max(12, _TEXT_LINE_UNITS // columns)
        header_height = _table_row_height(header, cell_units) if header else 0
        return 34 + header_height + sum(_table_row_height([str(cell) for cell in row], cell_units) for row in rows if isinstance(row, list))
    if block_type == "code":
        return 34 + max(1, str(block.get("text") or "").count("\n") + 1) * 25
    if block_type == "blockquote":
        return 34 + _wrapped_lines(str(block.get("text") or ""), line_units=44) * 29
    if block_type == "image":
        return 176
    if block_type == "horizontal_rule":
        return 32
    return 26 + _wrapped_lines(str(block.get("text") or ""), line_units=_TEXT_LINE_UNITS) * 30


def _block_from_node(node: DocumentNode) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": node.id,
        "type": _layout_type(node.type),
        "source_anchor": node.id,
        "text": node.text or None,
        "inline_markdown": node.metadata.get("inline_markdown"),
        "level": node.heading_level,
        "items": [],
        "rows": [],
        "caption": None,
        "confidence": 1.0,
        "bbox": None,
        "source_start_offset": node.start_offset,
        "source_end_offset": node.end_offset,
    }
    if node.type == "list":
        items = [dict(item) for item in node.metadata.get("items", []) if isinstance(item, dict)]
        base.update({
            "text": None,
            "items": [str(item.get("text") or "") for item in items],
            "list_ordered": bool(node.metadata.get("ordered")),
            "list_start": int(node.metadata.get("start") or 1),
            "list_items": [
                _layout_list_item(item, fallback_value=index)
                for index, item in enumerate(items, start=int(node.metadata.get("start") or 1))
            ],
        })
    elif node.type == "table":
        base.update({
            "text": None,
            "table_header": [str(value) for value in node.metadata.get("headers", [])],
            "table_header_markdown": [str(value) for value in node.metadata.get("header_markdown", [])],
            "rows": [[str(cell) for cell in row] for row in node.metadata.get("rows", []) if isinstance(row, list)],
            "rows_markdown": [
                [str(cell) for cell in row]
                for row in node.metadata.get("rows_markdown", [])
                if isinstance(row, list)
            ],
        })
    elif node.type == "code_block":
        base.update({"type": "code", "code_language": node.metadata.get("language")})
    elif node.type == "image":
        caption = str(node.metadata.get("caption") or node.text or "")
        base.update({"text": None, "caption": caption, "caption_markdown": caption, "image_source": node.metadata.get("url")})
    elif node.type == "horizontal_rule":
        base["text"] = None
    return base


def _layout_type(node_type: str) -> str:
    return {
        "code_block": "code",
        "blockquote": "blockquote",
        "horizontal_rule": "horizontal_rule",
    }.get(node_type, node_type if node_type in {"heading", "paragraph", "list", "table", "image", "caption", "code"} else "unknown")


def _split_block(block: dict[str, Any], budget: int) -> list[dict[str, Any]]:
    if estimated_layout_block_height(block) <= budget:
        return [deepcopy(block)]
    block_type = block["type"]
    if block_type in {"paragraph", "blockquote"}:
        parts = _split_text(str(block.get("text") or ""), block_type=block_type, budget=budget)
        return [
            {**deepcopy(block), "text": part, "inline_markdown": block.get("inline_markdown") if len(parts) == 1 else None}
            for part in parts
        ]
    if block_type == "list":
        return _split_list(block, budget)
    if block_type == "table":
        return _split_table(block, budget)
    if block_type == "code":
        return _split_code(block, budget)
    return [deepcopy(block)]


def _split_text(text: str, *, block_type: str, budget: int) -> list[str]:
    if not text:
        return [""]
    segments = _sentence_segments(text)
    parts: list[str] = []
    pending = ""
    for segment in segments:
        candidate = pending + segment
        if pending and _text_height(candidate, block_type) > budget:
            parts.append(pending)
            pending = ""
        if _text_height(segment, block_type) > budget:
            fragments = _hard_split_text(segment, block_type=block_type, budget=budget)
            parts.extend(fragments[:-1])
            pending = fragments[-1]
        else:
            pending += segment
    if pending or not parts:
        parts.append(pending)
    return parts


def _sentence_segments(text: str) -> list[str]:
    matches = re.findall(r".*?(?:\r\n|\r|\n|[。！？!?；;]+\s*|$)", text, flags=re.DOTALL)
    segments = [match for match in matches if match]
    return segments or [text]


def _hard_split_text(text: str, *, block_type: str, budget: int) -> list[str]:
    parts: list[str] = []
    remaining = text
    while remaining and _text_height(remaining, block_type) > budget:
        low, high = 1, len(remaining)
        while low < high:
            midpoint = (low + high + 1) // 2
            if _text_height(remaining[:midpoint], block_type) <= budget:
                low = midpoint
            else:
                high = midpoint - 1
        split_at = max(1, low)
        preferred = max(
            remaining.rfind("\n", 0, split_at + 1),
            remaining.rfind(" ", 0, split_at + 1),
            remaining.rfind("，", 0, split_at + 1),
            remaining.rfind(",", 0, split_at + 1),
        )
        if preferred >= split_at // 2:
            split_at = preferred + 1
        parts.append(remaining[:split_at])
        remaining = remaining[split_at:]
    parts.append(remaining)
    return parts


def _split_list(block: dict[str, Any], budget: int) -> list[dict[str, Any]]:
    items = _list_items(block)
    batches: list[list[dict[str, Any]]] = []
    pending: list[dict[str, Any]] = []
    for item in items:
        candidate = [*pending, item]
        if pending and _list_height(candidate) > budget:
            batches.append(pending)
            pending = []
        if _list_height([item]) > budget and not item.get("child_lists"):
            fragments = _split_text(str(item.get("text") or ""), block_type="paragraph", budget=max(96, budget - 56))
            for fragment_index, fragment in enumerate(fragments):
                fragment_item = {
                    **deepcopy(item),
                    "text": fragment,
                    "inline_markdown": None,
                    "continuation": fragment_index > 0 or bool(item.get("continuation")),
                }
                batches.append([fragment_item])
        else:
            pending.append(deepcopy(item))
    if pending or not batches:
        batches.append(pending)
    results: list[dict[str, Any]] = []
    for batch in batches:
        result = deepcopy(block)
        result["list_items"] = batch
        result["items"] = [str(item.get("text") or "") for item in batch]
        result["list_start"] = next((int(item["value"]) for item in batch if item.get("value") is not None), int(block.get("list_start") or 1))
        results.append(result)
    return results


def _split_table(block: dict[str, Any], budget: int) -> list[dict[str, Any]]:
    rows = [row for row in block.get("rows", []) if isinstance(row, list)]
    batches: list[list[list[str]]] = []
    pending: list[list[str]] = []
    for row in rows:
        normalized = [str(cell) for cell in row]
        candidate = [*pending, normalized]
        trial = {**block, "rows": candidate}
        if pending and estimated_layout_block_height(trial) > budget:
            batches.append(pending)
            pending = []
        trial = {**block, "rows": [normalized]}
        if estimated_layout_block_height(trial) > budget:
            batches.append([normalized])
        else:
            pending.append(normalized)
    if pending or not batches:
        batches.append(pending)
    rows_markdown = block.get("rows_markdown") if isinstance(block.get("rows_markdown"), list) else []
    markdown_by_row = {
        tuple(str(cell) for cell in row): [str(cell) for cell in markdown_row]
        for row, markdown_row in zip(rows, rows_markdown)
        if isinstance(row, list) and isinstance(markdown_row, list)
    }
    return [
        {
            **deepcopy(block),
            "rows": batch,
            "rows_markdown": [markdown_by_row.get(tuple(row), list(row)) for row in batch],
        }
        for batch in batches
    ]


def _split_code(block: dict[str, Any], budget: int) -> list[dict[str, Any]]:
    lines = str(block.get("text") or "").split("\n")
    batches: list[list[str]] = []
    pending: list[str] = []
    for line in lines:
        candidate = [*pending, line]
        if pending and estimated_layout_block_height({**block, "text": "\n".join(candidate)}) > budget:
            batches.append(pending)
            pending = [line]
        else:
            pending = candidate
    if pending or not batches:
        batches.append(pending)
    return [{**deepcopy(block), "text": "\n".join(batch)} for batch in batches]


def _finalize_continuation(
    block: dict[str, Any],
    *,
    source: dict[str, Any],
    index: int,
    count: int,
    visible_offset: int,
) -> dict[str, Any]:
    result = deepcopy(block)
    original_id = str(source["id"])
    result["id"] = original_id if count == 1 else f"{original_id}-continuation-{index}"
    result["continuation_of"] = original_id
    result["continuation_index"] = index
    result["continuation_count"] = count
    result["continuation_text_start"] = visible_offset
    result["continuation_text_end"] = visible_offset + len(_block_visible_text(block))
    return result


def _fallback_block(source: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(source)
    result["type"] = "paragraph"
    result["text"] = _block_visible_text(source)
    result["items"] = []
    result["rows"] = []
    result["list_items"] = []
    result["table_header"] = []
    return result


def _block_visible_text(block: dict[str, Any]) -> str:
    if block.get("type") == "list":
        return "".join(_list_item_visible_text(item) for item in _list_items(block))
    if block.get("type") == "table":
        return "".join(str(cell) for row in block.get("rows", []) if isinstance(row, list) for cell in row)
    if block.get("type") == "image":
        return str(block.get("caption") or "")
    return str(block.get("text") or "")


def _list_items(block: dict[str, Any]) -> list[dict[str, Any]]:
    values = block.get("list_items")
    if isinstance(values, list) and all(isinstance(item, dict) for item in values):
        return [dict(item) for item in values]
    start = int(block.get("list_start") or 1)
    return [
        {"text": str(text), "value": start + index, "children": [], "child_lists": [], "continuation": False}
        for index, text in enumerate(block.get("items") or [])
    ]


def _layout_list_item(item: dict[str, Any], *, fallback_value: int) -> dict[str, Any]:
    child_lists = []
    for child_list in item.get("child_lists") or []:
        if not isinstance(child_list, dict):
            continue
        child_start = int(child_list.get("start") or 1)
        child_items = [value for value in child_list.get("items") or [] if isinstance(value, dict)]
        child_lists.append({
            "ordered": bool(child_list.get("ordered")),
            "start": child_start,
            "items": [
                _layout_list_item(value, fallback_value=index)
                for index, value in enumerate(child_items, start=child_start)
            ],
        })
    return {
        "text": str(item.get("text") or ""),
        "inline_markdown": str(item.get("inline_markdown") or item.get("text") or ""),
        "value": int(item.get("ordinal") or fallback_value),
        "children": [],
        "child_lists": child_lists,
        "continuation": False,
    }


def _list_item_visible_text(item: dict[str, Any]) -> str:
    nested = "".join(
        _list_item_visible_text(child)
        for child_list in item.get("child_lists") or []
        if isinstance(child_list, dict)
        for child in child_list.get("items") or []
        if isinstance(child, dict)
    )
    return f"{item.get('text') or ''}{nested}"


def _text_height(text: str, block_type: str) -> int:
    return estimated_layout_block_height({"type": block_type, "text": text})


def _list_height(items: list[dict[str, Any]]) -> int:
    return estimated_layout_block_height({"type": "list", "list_items": items})


def _list_item_height(item: dict[str, Any]) -> int:
    own = 24 + _wrapped_lines(str(item.get("text") or ""), line_units=42) * 27
    nested = sum(
        18 + sum(_list_item_height(child) for child in child_list.get("items") or [] if isinstance(child, dict))
        for child_list in item.get("child_lists") or []
        if isinstance(child_list, dict)
    )
    return own + nested


def _wrapped_lines(text: str, *, line_units: int) -> int:
    if not text:
        return 1
    return sum(max(1, ceil(_display_units(line) / line_units)) for line in text.split("\n"))


def _display_units(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1 for character in text)


def _table_row_height(cells: list[str], cell_units: int) -> int:
    return 18 + max((_wrapped_lines(cell, line_units=cell_units) for cell in cells), default=1) * 24


def _page(page_number: int, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "page_number": page_number,
        "width": DEFAULT_PAGE_WIDTH,
        "height": DEFAULT_PAGE_HEIGHT,
        "blocks": blocks,
    }
