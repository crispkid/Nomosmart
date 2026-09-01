from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import html
import re
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token


PARSER_VERSION = "markdown-it-py-4.2.0-gfm-v1"


@dataclass(frozen=True)
class DocumentNode:
    id: str
    type: str
    text: str
    markdown: str
    start_offset: int
    end_offset: int
    sequence: int
    heading_path: tuple[str, ...] = ()
    heading_level: int | None = None
    parent: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentStructure:
    raw_markdown: str
    nodes: tuple[DocumentNode, ...]
    parser_version: str
    warnings: tuple[dict[str, Any], ...] = ()

    def as_metadata(self) -> dict[str, Any]:
        return {
            "parser_version": self.parser_version,
            "node_count": len(self.nodes),
            "heading_count": sum(node.type == "heading" for node in self.nodes),
            "table_count": sum(node.type == "table" for node in self.nodes),
            "warning_count": len(self.warnings),
            "page_count": max((node.page_end or 0 for node in self.nodes), default=0),
            "warnings": list(self.warnings),
        }


class MarkdownStructureParser:
    def __init__(self) -> None:
        self._parser = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable(["table", "strikethrough"])

    @property
    def version(self) -> str:
        return PARSER_VERSION

    def parse(self, markdown: str, *, page_ranges: list[dict[str, int]] | None = None) -> DocumentStructure:
        raw = markdown if isinstance(markdown, str) else str(markdown)
        if not raw.strip():
            return DocumentStructure(raw_markdown=raw, nodes=(), parser_version=self.version, warnings=({"code": "markdown_empty"},))
        try:
            tokens = self._parser.parse(raw)
        except Exception as exc:  # pragma: no cover - markdown-it is intentionally fail-safe
            return self._fallback_document(raw, f"parser_failed:{type(exc).__name__}")

        line_offsets = _line_offsets(raw)
        root = _node(raw=raw, node_type="document", text="", start=0, end=len(raw), sequence=0, heading_path=(), heading_level=None)
        nodes: list[DocumentNode] = [root]
        warnings: list[dict[str, Any]] = []
        headings: list[str] = []
        heading_ids: list[str] = []
        index = 0
        sequence = 0

        while index < len(tokens):
            token = tokens[index]
            try:
                if token.type == "heading_open":
                    inline = tokens[index + 1] if index + 1 < len(tokens) else token
                    level = int(token.tag[1:]) if token.tag.startswith("h") else 1
                    text_value, inline_meta = _inline_value(inline)
                    headings = headings[: level - 1]
                    heading_ids = heading_ids[: level - 1]
                    while len(headings) < level - 1:
                        headings.append("")
                        heading_ids.append("")
                    headings.append(text_value)
                    start, end = _span(token, line_offsets, raw)
                    sequence += 1
                    node = _node(
                        raw=raw,
                        node_type="heading",
                        text=text_value,
                        start=start,
                        end=end,
                        sequence=sequence,
                        heading_path=tuple(item for item in headings if item),
                        heading_level=level,
                        parent=next((item for item in reversed(heading_ids) if item), root.id),
                        metadata=inline_meta,
                    )
                    nodes.append(node)
                    heading_ids.append(node.id)
                    index += 3
                    continue

                if token.type in {"bullet_list_open", "ordered_list_open"}:
                    close = _matching_close(tokens, index)
                    start, end = _span(token, line_offsets, raw)
                    list_start = _int_attr(token, "start", 1)
                    items = _list_items(tokens[index + 1 : close], ordered=token.type == "ordered_list_open", start=list_start)
                    sequence += 1
                    list_node = _node(
                        raw=raw,
                        node_type="list",
                        text="\n".join(item["text"] for item in items),
                        start=start,
                        end=end,
                        sequence=sequence,
                        heading_path=tuple(item for item in headings if item),
                        heading_level=_active_level(headings),
                        parent=next((item for item in reversed(heading_ids) if item), root.id),
                        metadata={"ordered": token.type == "ordered_list_open", "items": items, "start": list_start},
                    )
                    nodes.append(list_node)
                    child_specs = _list_item_specs(tokens[index + 1 : close], items, line_offsets, raw)
                    for item, item_start, item_end in child_specs:
                        sequence += 1
                        nodes.append(
                            _node(
                                raw=raw,
                                node_type="list_item",
                                text=str(item["text"]),
                                start=item_start,
                                end=item_end,
                                sequence=sequence,
                                heading_path=tuple(value for value in headings if value),
                                heading_level=_active_level(headings),
                                parent=list_node.id,
                                metadata={
                                    "ordered": token.type == "ordered_list_open",
                                    "ordinal": item["ordinal"],
                                    "inline_markdown": item.get("inline_markdown") or item["text"],
                                    "structural_child": True,
                                },
                            )
                        )
                    index = close + 1
                    continue

                if token.type == "table_open":
                    close = _matching_close(tokens, index)
                    start, end = _span(token, line_offsets, raw)
                    headers, rows, header_markdown, rows_markdown = _table(tokens[index + 1 : close])
                    sequence += 1
                    table_node = _node(
                        raw=raw,
                        node_type="table",
                        text=_table_visible_text(headers, rows),
                        start=start,
                        end=end,
                        sequence=sequence,
                        heading_path=tuple(item for item in headings if item),
                        heading_level=_active_level(headings),
                        parent=next((item for item in reversed(heading_ids) if item), root.id),
                        metadata={
                            "headers": headers,
                            "rows": rows,
                            "header_markdown": header_markdown,
                            "rows_markdown": rows_markdown,
                            "table_id": f"table-{sequence:04d}",
                        },
                    )
                    nodes.append(table_node)
                    for row in _table_row_specs(tokens[index + 1 : close], line_offsets, raw):
                        sequence += 1
                        row_node = _node(
                            raw=raw,
                            node_type="table_row",
                            text="\n".join(row["cells"]),
                            start=row["start"],
                            end=row["end"],
                            sequence=sequence,
                            heading_path=tuple(value for value in headings if value),
                            heading_level=_active_level(headings),
                            parent=table_node.id,
                            metadata={"header": row["header"], "row_index": row["row_index"], "structural_child": True},
                        )
                        nodes.append(row_node)
                        for column_index, (cell_text, cell_span) in enumerate(zip(row["cells"], row["cell_spans"], strict=True)):
                            sequence += 1
                            nodes.append(
                                _node(
                                    raw=raw,
                                    node_type="table_cell",
                                    text=cell_text,
                                    start=cell_span[0],
                                    end=cell_span[1],
                                    sequence=sequence,
                                    heading_path=tuple(value for value in headings if value),
                                    heading_level=_active_level(headings),
                                    parent=row_node.id,
                                    metadata={
                                        "header": row["header"],
                                        "column_index": column_index,
                                        "column_name": headers[column_index] if column_index < len(headers) else None,
                                        "inline_markdown": row["markdown_cells"][column_index] if column_index < len(row["markdown_cells"]) else cell_text,
                                        "structural_child": True,
                                    },
                                )
                            )
                    index = close + 1
                    continue

                if token.type == "blockquote_open":
                    close = _matching_close(tokens, index)
                    start, end = _span(token, line_offsets, raw)
                    blockquote_tokens = tokens[index + 1 : close]
                    text_value = _token_range_text(blockquote_tokens)
                    inline_markdown = "\n".join(
                        value.content for value in blockquote_tokens if value.type == "inline" and value.content
                    )
                    sequence += 1
                    nodes.append(
                        _node(
                            raw=raw,
                            node_type="blockquote",
                            text=text_value,
                            start=start,
                            end=end,
                            sequence=sequence,
                            heading_path=tuple(item for item in headings if item),
                            heading_level=_active_level(headings),
                            parent=next((item for item in reversed(heading_ids) if item), root.id),
                            metadata={"inline_markdown": inline_markdown} if inline_markdown else {},
                        )
                    )
                    index = close + 1
                    continue

                if token.type in {"fence", "code_block"}:
                    start, end = _span(token, line_offsets, raw)
                    sequence += 1
                    nodes.append(
                        _node(
                            raw=raw,
                            node_type="code_block",
                            text=token.content.rstrip("\n"),
                            start=start,
                            end=end,
                            sequence=sequence,
                            heading_path=tuple(item for item in headings if item),
                            heading_level=_active_level(headings),
                            parent=next((item for item in reversed(heading_ids) if item), root.id),
                            metadata={"language": token.info.strip().split(maxsplit=1)[0] if token.info.strip() else None},
                        )
                    )
                    index += 1
                    continue

                if token.type == "html_block":
                    start, end = _span(token, line_offsets, raw)
                    visible = _visible_html(token.content)
                    if visible:
                        sequence += 1
                        nodes.append(
                            _node(
                                raw=raw,
                                node_type="paragraph",
                                text=visible,
                                start=start,
                                end=end,
                                sequence=sequence,
                                heading_path=tuple(item for item in headings if item),
                                heading_level=_active_level(headings),
                                parent=next((item for item in reversed(heading_ids) if item), root.id),
                                metadata={"source_type": "html_block"},
                            )
                        )
                    index += 1
                    continue

                if token.type == "hr":
                    start, end = _span(token, line_offsets, raw)
                    sequence += 1
                    nodes.append(_node(raw=raw, node_type="horizontal_rule", text="", start=start, end=end, sequence=sequence, heading_path=tuple(item for item in headings if item), heading_level=_active_level(headings), parent=next((item for item in reversed(heading_ids) if item), root.id)))
                    index += 1
                    continue

                if token.type == "paragraph_open":
                    inline = tokens[index + 1] if index + 1 < len(tokens) else token
                    start, end = _span(token, line_offsets, raw)
                    text_value, inline_meta = _inline_value(inline)
                    images = inline_meta.get("images", [])
                    only_image = bool(images) and not _non_image_inline_text(inline)
                    sequence += 1
                    if only_image:
                        image = images[0]
                        image_node = _node(
                            raw=raw,
                            node_type="image",
                            text=str(image.get("caption") or ""),
                            start=start,
                            end=end,
                            sequence=sequence,
                            heading_path=tuple(item for item in headings if item),
                            heading_level=_active_level(headings),
                            parent=next((item for item in reversed(heading_ids) if item), root.id),
                            metadata={"url": image.get("url"), "caption": image.get("caption")},
                        )
                        nodes.append(image_node)
                        caption = str(image.get("caption") or "")
                        if caption:
                            caption_start, caption_end = _image_caption_span(raw, start, end)
                            sequence += 1
                            nodes.append(
                                _node(
                                    raw=raw,
                                    node_type="caption",
                                    text=caption,
                                    start=caption_start,
                                    end=caption_end,
                                    sequence=sequence,
                                    heading_path=tuple(item for item in headings if item),
                                    heading_level=_active_level(headings),
                                    parent=image_node.id,
                                    metadata={"url": image.get("url"), "structural_child": True},
                                )
                            )
                    else:
                        nodes.append(
                            _node(
                                raw=raw,
                                node_type="paragraph",
                                text=text_value,
                                start=start,
                                end=end,
                                sequence=sequence,
                                heading_path=tuple(item for item in headings if item),
                                heading_level=_active_level(headings),
                                parent=next((item for item in reversed(heading_ids) if item), root.id),
                                metadata=inline_meta,
                            )
                        )
                    index += 3
                    continue
            except Exception as exc:
                start, end = _span(token, line_offsets, raw)
                if end > start:
                    sequence += 1
                    fragment = raw[start:end]
                    nodes.append(_node(raw=raw, node_type="paragraph", text=visible_markdown_text(fragment), start=start, end=end, sequence=sequence, heading_path=tuple(item for item in headings if item), heading_level=_active_level(headings), metadata={"parse_warning": "block_fallback"}))
                    warnings.append({"code": "block_parse_fallback", "sequence": sequence, "token_type": token.type, "error": type(exc).__name__})
            index += 1

        if len(nodes) == 1:
            return self._fallback_document(raw, "no_structural_nodes")
        paged_nodes = tuple(_attach_page_range(node, page_ranges or []) for node in nodes)
        return DocumentStructure(raw_markdown=raw, nodes=paged_nodes, parser_version=self.version, warnings=tuple(warnings))

    def _fallback_document(self, raw: str, reason: str) -> DocumentStructure:
        text_value = visible_markdown_text(raw)
        root = _node(raw=raw, node_type="document", text="", start=0, end=len(raw), sequence=0, heading_path=(), heading_level=None)
        node = _node(raw=raw, node_type="paragraph", text=text_value, start=0, end=len(raw), sequence=1, heading_path=(), heading_level=None, parent=root.id, metadata={"parse_warning": reason})
        return DocumentStructure(raw_markdown=raw, nodes=(root, node), parser_version=self.version, warnings=({"code": reason, "sequence": 1},))


def visible_markdown_text(markdown: str) -> str:
    parser = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    tokens = parser.parse(markdown)
    parts = [_inline_value(token)[0] for token in tokens if token.type == "inline"]
    if not parts:
        parts = [_visible_html(token.content) if token.type == "html_block" else token.content for token in tokens if token.type in {"fence", "code_block", "html_block"}]
    text_value = "\n".join(part for part in parts if part)
    return _normalize_visible(text_value or markdown)


def repeated_page_boilerplate(pages: list[str], *, minimum_pages: int = 3, recurrence_ratio: float = 0.8) -> dict[str, list[str]]:
    """Detect only high-confidence repeated first/last lines on reliable pages."""

    if len(pages) < minimum_pages:
        return {"headers": [], "footers": []}
    first_lines: list[str] = []
    last_lines: list[str] = []
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        if not lines:
            continue
        first_lines.append(lines[0])
        last_lines.append(lines[-1])
    threshold = max(minimum_pages, int(len(pages) * recurrence_ratio + 0.9999))
    headers = [value for value in set(first_lines) if first_lines.count(value) >= threshold]
    footers = [value for value in set(last_lines) if last_lines.count(value) >= threshold]
    return {"headers": sorted(headers), "footers": sorted(footers)}


def mark_repeated_boilerplate(structure: DocumentStructure, values: set[str]) -> DocumentStructure:
    if not values:
        return structure
    nodes = tuple(
        replace(node, metadata={**node.metadata, "retrieval_excluded": "repeated_header_footer"})
        if node.text.strip() in values
        else node
        for node in structure.nodes
    )
    return replace(structure, nodes=nodes)


def _line_offsets(raw: str) -> list[int]:
    offsets = [0]
    for match in re.finditer("\n", raw):
        offsets.append(match.end())
    offsets.append(len(raw))
    return offsets


def _span(token: Token, offsets: list[int], raw: str) -> tuple[int, int]:
    if not token.map:
        return 0, 0
    start_line, end_line = token.map
    start = offsets[min(start_line, len(offsets) - 1)]
    end = offsets[min(end_line, len(offsets) - 1)]
    return start, min(end, len(raw))


def _node(*, raw: str, node_type: str, text: str, start: int, end: int, sequence: int, heading_path: tuple[str, ...], heading_level: int | None, parent: str | None = None, metadata: dict[str, Any] | None = None) -> DocumentNode:
    fragment = raw[start:end]
    digest = sha256(f"{sequence}:{node_type}:{start}:{end}:{fragment}".encode("utf-8")).hexdigest()[:12]
    return DocumentNode(
        id=f"node-{sequence:04d}-{digest}",
        type=node_type,
        text=text.rstrip("\n") if node_type == "code_block" else _normalize_visible(text),
        markdown=fragment,
        start_offset=start,
        end_offset=end,
        sequence=sequence,
        heading_path=heading_path,
        heading_level=heading_level,
        parent=parent,
        metadata=metadata or {},
    )


def _matching_close(tokens: list[Token], start: int) -> int:
    depth = 0
    open_type = tokens[start].type
    close_type = open_type.replace("_open", "_close")
    for index in range(start, len(tokens)):
        if tokens[index].type == open_type:
            depth += 1
        elif tokens[index].type == close_type:
            depth -= 1
            if depth == 0:
                return index
    return start


def _inline_value(token: Token) -> tuple[str, dict[str, Any]]:
    if token.type != "inline" or not token.children:
        return _normalize_visible(token.content), {}
    parts: list[str] = []
    links: list[dict[str, str]] = []
    images: list[dict[str, str]] = []
    link_url: str | None = None
    link_text: list[str] = []
    for child in token.children:
        if child.type == "link_open":
            link_url = child.attrGet("href") or ""
            link_text = []
        elif child.type == "link_close":
            links.append({"text": "".join(link_text).strip(), "url": link_url or ""})
            link_url = None
            link_text = []
        elif child.type == "image":
            caption = child.content or child.attrGet("alt") or ""
            images.append({"caption": caption, "url": child.attrGet("src") or ""})
            parts.append(caption)
            if link_url is not None:
                link_text.append(caption)
        elif child.type in {"text", "code_inline"}:
            value = child.content
            parts.append(value)
            if link_url is not None:
                link_text.append(value)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif child.type == "html_inline":
            parts.append(re.sub(r"<[^>]*>", "", html.unescape(child.content)))
    metadata: dict[str, Any] = {}
    if token.content:
        metadata["inline_markdown"] = token.content
    if links:
        metadata["links"] = links
    if images:
        metadata["images"] = images
    return _normalize_visible("".join(parts)), metadata


def _non_image_inline_text(token: Token) -> str:
    if not token.children:
        return token.content
    return "".join(child.content for child in token.children if child.type in {"text", "code_inline"}).strip()


def _list_items(tokens: list[Token], *, ordered: bool, start: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type != "list_item_open":
            index += 1
            continue
        close = _matching_close(tokens, index)
        body = tokens[index + 1 : close]
        direct_inline_level = token.level + 2
        direct_inline_tokens = [value for value in body if value.type == "inline" and value.level == direct_inline_level]
        current = [_inline_value(value)[0] for value in direct_inline_tokens]
        current_markdown = [value.content for value in direct_inline_tokens if value.content]
        child_lists: list[dict[str, Any]] = []
        child_index = 0
        while child_index < len(body):
            child = body[child_index]
            if child.type in {"bullet_list_open", "ordered_list_open"} and child.level == token.level + 1:
                child_close = _matching_close(body, child_index)
                child_ordered = child.type == "ordered_list_open"
                child_start = _int_attr(child, "start", 1)
                child_lists.append({
                    "ordered": child_ordered,
                    "start": child_start,
                    "items": _list_items(body[child_index + 1 : child_close], ordered=child_ordered, start=child_start),
                })
                child_index = child_close + 1
                continue
            child_index += 1
        ordinal = _token_info_int(token, start + len(items)) if ordered else len(items) + 1
        items.append({
            "text": _normalize_visible("\n".join(current)),
            "inline_markdown": "\n".join(current_markdown),
            "ordinal": ordinal,
            "child_lists": child_lists,
        })
        index = close + 1
    return items


def _list_item_specs(tokens: list[Token], items: list[dict[str, Any]], offsets: list[int], raw: str) -> list[tuple[dict[str, Any], int, int]]:
    specs: list[tuple[dict[str, Any], int, int]] = []
    depth = 0
    item_index = 0
    for token in tokens:
        if token.type == "list_item_open":
            if depth == 0 and item_index < len(items):
                start, end = _span(token, offsets, raw)
                specs.append((items[item_index], start, end))
                item_index += 1
            depth += 1
        elif token.type == "list_item_close":
            depth = max(0, depth - 1)
    return specs


def _table(tokens: list[Token]) -> tuple[list[str], list[list[str]], list[str], list[list[str]]]:
    headers: list[str] = []
    rows: list[list[str]] = []
    header_markdown: list[str] = []
    rows_markdown: list[list[str]] = []
    current: list[str] | None = None
    current_markdown: list[str] | None = None
    in_header = False
    for token in tokens:
        if token.type == "thead_open":
            in_header = True
        elif token.type == "thead_close":
            in_header = False
        elif token.type == "tr_open":
            current = []
            current_markdown = []
        elif token.type == "inline" and current is not None:
            current.append(_inline_value(token)[0])
            if current_markdown is not None:
                current_markdown.append(token.content)
        elif token.type == "tr_close" and current is not None:
            if in_header:
                headers = current
                header_markdown = current_markdown or list(current)
            else:
                rows.append(current)
                rows_markdown.append(current_markdown or list(current))
            current = None
            current_markdown = None
    return headers, rows, header_markdown, rows_markdown


def _table_row_specs(tokens: list[Token], offsets: list[int], raw: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    in_header = False
    row_index = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "thead_open":
            in_header = True
        elif token.type == "thead_close":
            in_header = False
        elif token.type == "tr_open":
            close = _matching_close(tokens, index)
            start, end = _span(token, offsets, raw)
            cells = [_inline_value(item)[0] for item in tokens[index + 1 : close] if item.type == "inline"]
            markdown_cells = [item.content for item in tokens[index + 1 : close] if item.type == "inline"]
            specs.append({
                "cells": cells,
                "markdown_cells": markdown_cells,
                "start": start,
                "end": end,
                "header": in_header,
                "row_index": 0 if in_header else row_index + 1,
                "cell_spans": _table_cell_spans(raw, start, end, len(cells)),
            })
            if not in_header:
                row_index += 1
            index = close
        index += 1
    return specs


def _table_cell_spans(raw: str, start: int, end: int, count: int) -> list[tuple[int, int]]:
    line = raw[start:end]
    pipes = [index for index, value in enumerate(line) if value == "|" and (index == 0 or line[index - 1] != "\\")]
    stripped_start = len(line) - len(line.lstrip())
    stripped_end = len(line.rstrip())
    boundaries = [0, *pipes, len(line)]
    segments: list[tuple[int, int]] = []
    for left, right in zip(boundaries, boundaries[1:]):
        segment_start = left + (1 if left in pipes else 0)
        segment_end = right
        while segment_start < segment_end and line[segment_start].isspace():
            segment_start += 1
        while segment_end > segment_start and line[segment_end - 1].isspace():
            segment_end -= 1
        if segment_start < segment_end:
            segments.append((start + segment_start, start + segment_end))
    if len(segments) != count or stripped_start >= stripped_end:
        return [(start, end)] * count
    return segments


def _image_caption_span(raw: str, start: int, end: int) -> tuple[int, int]:
    fragment = raw[start:end]
    match = re.search(r"!\[([^\]]*)\]", fragment)
    if not match:
        return start, end
    return start + match.start(1), start + match.end(1)


def _table_visible_text(headers: list[str], rows: list[list[str]]) -> str:
    rendered: list[str] = []
    for row in rows:
        rendered.append("\n".join(f"{header}：{row[index] if index < len(row) else ''}" for index, header in enumerate(headers)))
    return "\n\n".join(rendered)


def _token_range_text(tokens: list[Token]) -> str:
    return _normalize_visible("\n".join(_inline_value(token)[0] for token in tokens if token.type == "inline"))


def _normalize_visible(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in html.unescape(value or "").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _visible_html(value: str) -> str:
    return _normalize_visible(re.sub(r"<[^>]*>", "", html.unescape(value or "")))


def _active_level(headings: list[str]) -> int | None:
    return len(headings) if headings else None


def _attach_page_range(node: DocumentNode, ranges: list[dict[str, int]]) -> DocumentNode:
    pages = [
        int(item.get("page", index + 1))
        for index, item in enumerate(ranges)
        if isinstance(item, dict)
        and isinstance(item.get("start_offset"), int)
        and isinstance(item.get("end_offset"), int)
        and node.end_offset > int(item["start_offset"])
        and node.start_offset < int(item["end_offset"])
    ]
    if not pages:
        return node
    return replace(node, page_start=min(pages), page_end=max(pages))


def _int_attr(token: Token, name: str, default: int) -> int:
    value = token.attrGet(name)
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _token_info_int(token: Token, default: int) -> int:
    try:
        return int(token.info) if token.info else default
    except (TypeError, ValueError):
        return default
