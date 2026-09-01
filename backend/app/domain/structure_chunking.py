from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
import re
from typing import Any
from uuid import UUID, uuid5

from app.domain.markdown_structure import DocumentNode, DocumentStructure, visible_markdown_text
from app.domain.tokenization import TokenCounter, UnicodeTokenCounter, sentence_ranges, token_windows


CHUNKER_VERSION = "structure-chunker-v2"
DISPLAY_PROJECTION_VERSION = "markdown-display-projection-v1"


@dataclass(frozen=True)
class ChunkingConfig:
    target_chunk_tokens: int = 500
    max_chunk_tokens: int = 700
    min_chunk_tokens: int = 80
    chunk_overlap_tokens: int = 60
    heading_context_enabled: bool = True
    max_heading_depth: int = 4
    max_context_prefix_tokens: int = 96
    document_title_context_enabled: bool = True
    table_chunk_max_rows: int = 10
    remove_repeated_header_footer: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.min_chunk_tokens <= self.target_chunk_tokens <= self.max_chunk_tokens:
            raise ValueError("chunk token limits must satisfy min <= target <= max")
        if not 0 <= self.chunk_overlap_tokens < self.max_chunk_tokens:
            raise ValueError("chunk overlap must be smaller than max")
        if self.max_heading_depth < 1 or self.max_context_prefix_tokens < 1 or self.table_chunk_max_rows < 1:
            raise ValueError("heading, prefix and table limits must be positive")

    def snapshot(self) -> dict[str, Any]:
        return {
            "target_chunk_tokens": self.target_chunk_tokens,
            "max_chunk_tokens": self.max_chunk_tokens,
            "min_chunk_tokens": self.min_chunk_tokens,
            "chunk_overlap_tokens": self.chunk_overlap_tokens,
            "heading_context_enabled": self.heading_context_enabled,
            "max_heading_depth": self.max_heading_depth,
            "max_context_prefix_tokens": self.max_context_prefix_tokens,
            "document_title_context_enabled": self.document_title_context_enabled,
            "table_chunk_max_rows": self.table_chunk_max_rows,
            "remove_repeated_header_footer": self.remove_repeated_header_footer,
        }


@dataclass(frozen=True)
class ChunkDraft:
    id: UUID
    stable_chunk_key: str
    sequence: int
    display_text: str
    display_markdown: str
    raw_markdown: str
    heading_path: tuple[str, ...]
    heading_level: int | None
    content_type: str
    start_offset: int
    end_offset: int
    node_ids: tuple[str, ...]
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    previous_chunk_id: UUID | None = None
    next_chunk_id: UUID | None = None


@dataclass(frozen=True)
class _Unit:
    display: str
    display_markdown: str
    start: int
    end: int
    heading_path: tuple[str, ...]
    heading_level: int | None
    content_type: str
    node_ids: tuple[str, ...]
    metadata: dict[str, Any]


class StructureAwareChunker:
    def __init__(self, *, config: ChunkingConfig | None = None, token_counter: TokenCounter | None = None) -> None:
        self.config = config or ChunkingConfig()
        self.token_counter = token_counter or UnicodeTokenCounter()

    @property
    def version(self) -> str:
        return CHUNKER_VERSION

    def chunk(self, structure: DocumentStructure, *, document_key: str, version_id: UUID) -> list[ChunkDraft]:
        units: list[_Unit] = []
        for node in structure.nodes:
            if node.type in {"document", "heading", "list_item", "table_row", "table_cell", "caption", "horizontal_rule", "page_break"} or node.metadata.get("retrieval_excluded"):
                continue
            if node.type == "table":
                units.extend(self._table_units(node, structure))
            elif node.type == "list":
                units.extend(self._list_units(node, structure))
            elif node.type == "code_block":
                units.extend(self._code_units(node))
            elif self.token_counter.count(node.text) > self.config.max_chunk_tokens:
                units.extend(self._long_node_units(node))
            else:
                display = _node_display(node)
                if display:
                    units.append(_unit_from_node(node, display))

        grouped: list[list[_Unit]] = []
        pending: list[_Unit] = []
        pending_tokens = 0
        pending_path: tuple[str, ...] | None = None
        for unit in units:
            unit_tokens = self.token_counter.count(unit.display)
            isolated = unit.content_type in {"table", "code", "code_block"}
            incompatible = pending and (unit.heading_path != pending_path or isolated or pending[0].content_type in {"table", "code", "code_block"})
            over_target = pending and pending_tokens + unit_tokens > self.config.target_chunk_tokens
            if incompatible or over_target:
                grouped.append(pending)
                pending = []
                pending_tokens = 0
                pending_path = None
            if isolated:
                grouped.append([unit])
                continue
            pending.append(unit)
            pending_tokens += unit_tokens
            pending_path = unit.heading_path
        if pending:
            grouped.append(pending)

        drafts = [self._draft(group, index + 1, structure, document_key, version_id) for index, group in enumerate(grouped) if group]
        return [replace(draft, previous_chunk_id=drafts[index - 1].id if index else None, next_chunk_id=drafts[index + 1].id if index + 1 < len(drafts) else None) for index, draft in enumerate(drafts)]

    def _table_units(self, node: DocumentNode, structure: DocumentStructure) -> list[_Unit]:
        headers = [str(item) for item in node.metadata.get("headers", [])]
        rows = [[str(cell) for cell in row] for row in node.metadata.get("rows", []) if isinstance(row, list)]
        table_id = str(node.metadata.get("table_id") or node.id)
        table_rows = sorted(
            (
                child
                for child in structure.nodes
                if child.type == "table_row" and child.parent == node.id
            ),
            key=lambda child: child.start_offset,
        )
        header_row = next((child for child in table_rows if child.metadata.get("header")), None)
        body_rows = [child for child in table_rows if not child.metadata.get("header")]
        header_markdown = _table_header_markdown(node, header_row, body_rows)
        units: list[_Unit] = []
        batch: list[list[str]] = []
        batch_nodes: list[DocumentNode] = []
        row_start = 1
        for row_number, row in enumerate(rows, start=1):
            row_display = _semantic_table(headers, [row])
            row_node = body_rows[row_number - 1] if row_number <= len(body_rows) else None
            if self.token_counter.count(row_display) > self.config.max_chunk_tokens:
                if batch:
                    units.append(
                        _table_batch_unit(
                            node,
                            batch,
                            batch_nodes,
                            headers=headers,
                            header_markdown=header_markdown,
                            table_id=table_id,
                            row_start=row_start,
                            row_end=row_number - 1,
                        )
                    )
                    batch = []
                    batch_nodes = []
                header_context = f"表格欄位：{'、'.join(headers)}" if headers else "表格"
                available = max(1, self.config.max_chunk_tokens - self.token_counter.count(header_context))
                fragments = token_windows(row_display, max_tokens=available)
                for fragment_index, (fragment_start, fragment_end) in enumerate(fragments, start=1):
                    fragment = row_display[fragment_start:fragment_end]
                    row_markdown = row_node.markdown.rstrip("\n") if row_node is not None else _markdown_table_row(row)
                    start = row_node.start_offset + min(fragment_start, max(0, len(row_node.markdown) - 1)) if row_node is not None else node.start_offset
                    end = row_node.end_offset if row_node is not None else node.end_offset
                    units.append(
                        _Unit(
                            display=f"{header_context}\n\n{fragment}",
                            display_markdown=f"{header_markdown}\n{row_markdown}".strip(),
                            start=start,
                            end=end,
                            heading_path=node.heading_path,
                            heading_level=node.heading_level,
                            content_type="table",
                            node_ids=tuple(value for value in (node.id, row_node.id if row_node else None) if value),
                            metadata={
                                **node.metadata,
                                "page_start": row_node.page_start if row_node is not None else node.page_start,
                                "page_end": row_node.page_end if row_node is not None else node.page_end,
                                "headers": headers,
                                "table_id": table_id,
                                "row_start": row_number,
                                "row_end": row_number,
                                "row_fragment": fragment_index,
                            },
                        )
                    )
                row_start = row_number + 1
                continue
            candidate = [*batch, row]
            display = _semantic_table(headers, candidate)
            if batch and (len(candidate) > self.config.table_chunk_max_rows or self.token_counter.count(display) > self.config.max_chunk_tokens):
                units.append(
                    _table_batch_unit(
                        node,
                        batch,
                        batch_nodes,
                        headers=headers,
                        header_markdown=header_markdown,
                        table_id=table_id,
                        row_start=row_start,
                        row_end=row_number - 1,
                    )
                )
                batch = [row]
                batch_nodes = [row_node] if row_node is not None else []
                row_start = row_number
            else:
                batch = candidate
                if row_node is not None:
                    batch_nodes.append(row_node)
        if batch or not rows:
            units.append(
                _table_batch_unit(
                    node,
                    batch,
                    batch_nodes,
                    headers=headers,
                    header_markdown=header_markdown,
                    table_id=table_id,
                    row_start=row_start,
                    row_end=len(rows),
                )
            )
        return units

    def _list_units(self, node: DocumentNode, structure: DocumentStructure) -> list[_Unit]:
        items = [item for item in node.metadata.get("items", []) if isinstance(item, dict)]
        ordered = bool(node.metadata.get("ordered"))
        rendered = [_render_list_item(item, ordered=ordered, fallback=index) for index, item in enumerate(items, start=1)]
        item_nodes = sorted(
            (
                child
                for child in structure.nodes
                if child.type == "list_item" and child.parent == node.id
            ),
            key=lambda child: child.start_offset,
        )
        units: list[_Unit] = []
        batch: list[str] = []
        batch_nodes: list[DocumentNode] = []
        for item_index, value in enumerate(rendered):
            item_node = item_nodes[item_index] if item_index < len(item_nodes) else None
            candidate = [*batch, value]
            if batch and self.token_counter.count("\n".join(candidate)) > self.config.max_chunk_tokens:
                units.append(_list_batch_unit(node, batch, batch_nodes, ordered=ordered))
                batch = [value]
                batch_nodes = [item_node] if item_node is not None else []
            else:
                batch = candidate
                if item_node is not None:
                    batch_nodes.append(item_node)
        if batch:
            units.append(_list_batch_unit(node, batch, batch_nodes, ordered=ordered))
        return units

    def _code_units(self, node: DocumentNode) -> list[_Unit]:
        if self.token_counter.count(node.text) <= self.config.max_chunk_tokens:
            return [_unit_from_node(node, node.text)]
        content_start = node.markdown.find(node.text)
        if content_start < 0:
            content_start = 0
        ranges = _code_ranges(node.text, self.config.max_chunk_tokens, self.token_counter)
        language = str(node.metadata.get("language") or "").strip()
        units: list[_Unit] = []
        for part_index, (local_start, local_end) in enumerate(ranges, start=1):
            fragment = node.text[local_start:local_end]
            if fragment.endswith("\n"):
                fragment = fragment[:-1]
            units.append(
                _Unit(
                    display=fragment,
                    display_markdown=_fenced_code(fragment, language),
                    start=node.start_offset + content_start + local_start,
                    end=node.start_offset + content_start + local_end,
                    heading_path=node.heading_path,
                    heading_level=node.heading_level,
                    content_type=node.type,
                    node_ids=(node.id,),
                    metadata={
                        **node.metadata,
                        "page_start": node.page_start,
                        "page_end": node.page_end,
                        "split_reason": "max_chunk_tokens",
                        "code_fragment": part_index,
                        "code_fragment_count": len(ranges),
                    },
                )
            )
        return units

    def _long_node_units(self, node: DocumentNode) -> list[_Unit]:
        raw = node.markdown
        segment_limit = max(1, self.config.max_chunk_tokens - self.config.chunk_overlap_tokens)
        ranges: list[tuple[int, int]] = []
        for sentence_start, sentence_end in sentence_ranges(raw):
            sentence = raw[sentence_start:sentence_end]
            if self.token_counter.count(visible_markdown_text(sentence)) <= segment_limit:
                ranges.append((sentence_start, sentence_end))
                continue
            ranges.extend((sentence_start + start, sentence_start + end) for start, end in token_windows(sentence, max_tokens=segment_limit))
        batches: list[tuple[int, int]] = []
        start: int | None = None
        end = 0
        for sentence_start, sentence_end in ranges:
            candidate_start = sentence_start if start is None else start
            candidate_raw = raw[candidate_start:sentence_end]
            if start is not None and self.token_counter.count(visible_markdown_text(candidate_raw)) > segment_limit:
                batches.append((start, end))
                start = sentence_start
            elif start is None:
                start = sentence_start
            end = sentence_end
        if start is not None:
            batches.append((start, end))
        units: list[_Unit] = []
        for batch_index, (local_start, local_end) in enumerate(batches):
            if batch_index and self.config.chunk_overlap_tokens:
                overlap_start = local_start
                for previous_start, previous_end in reversed(ranges):
                    if previous_end > local_start:
                        continue
                    candidate = raw[previous_start:local_start]
                    if self.token_counter.count(visible_markdown_text(candidate)) > self.config.chunk_overlap_tokens:
                        break
                    overlap_start = previous_start
                local_start = overlap_start
            fragment = raw[local_start:local_end]
            display = visible_markdown_text(fragment)
            units.append(_Unit(display=display, display_markdown=fragment, start=node.start_offset + local_start, end=node.start_offset + local_end, heading_path=node.heading_path, heading_level=node.heading_level, content_type=node.type, node_ids=(node.id,), metadata={"split_reason": "max_chunk_tokens"}))
        return units

    def _draft(self, units: list[_Unit], sequence: int, structure: DocumentStructure, document_key: str, version_id: UUID) -> ChunkDraft:
        start = min(unit.start for unit in units)
        end = max(unit.end for unit in units)
        display = "\n\n".join(unit.display for unit in units if unit.display).strip()
        display_markdown = "\n\n".join(unit.display_markdown.strip("\n") for unit in units if unit.display_markdown).strip()
        content_types = {unit.content_type for unit in units}
        content_type = next(iter(content_types)) if len(content_types) == 1 else "mixed"
        heading_path = units[0].heading_path[-self.config.max_heading_depth :]
        metadata: dict[str, Any] = {
            "parser_version": structure.parser_version,
            "chunker_version": self.version,
            "tokenizer_version": self.token_counter.version,
            "display_projection_version": DISPLAY_PROJECTION_VERSION,
            "node_types": [unit.content_type for unit in units],
            "config": self.config.snapshot(),
        }
        page_starts = [int(unit.metadata["page_start"]) for unit in units if isinstance(unit.metadata.get("page_start"), int)]
        page_ends = [int(unit.metadata["page_end"]) for unit in units if isinstance(unit.metadata.get("page_end"), int)]
        if page_starts:
            metadata["page_start"] = min(page_starts)
        if page_ends:
            metadata["page_end"] = max(page_ends)
        if len(units) == 1:
            metadata.update(units[0].metadata)
        stable_payload = {
            "document_key": document_key,
            "sequence": sequence,
            "raw_sha256": sha256(structure.raw_markdown[start:end].encode("utf-8")).hexdigest(),
            "display_sha256": sha256(display.encode("utf-8")).hexdigest(),
            "heading_path": heading_path,
            "content_type": content_type,
            "parser_version": structure.parser_version,
            "chunker_version": self.version,
            "tokenizer_version": self.token_counter.version,
            "config": self.config.snapshot(),
        }
        stable_key = sha256(json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return ChunkDraft(
            id=uuid5(version_id, stable_key),
            stable_chunk_key=stable_key,
            sequence=sequence,
            display_text=display,
            display_markdown=display_markdown,
            raw_markdown=structure.raw_markdown[start:end],
            heading_path=heading_path,
            heading_level=units[0].heading_level,
            content_type=content_type,
            start_offset=start,
            end_offset=end,
            node_ids=tuple(node_id for unit in units for node_id in unit.node_ids),
            token_count=self.token_counter.count(display),
            metadata=metadata,
        )


def _unit_from_node(
    node: DocumentNode,
    display: str,
    *,
    display_markdown: str | None = None,
    content_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> _Unit:
    return _Unit(
        display=display,
        display_markdown=node.markdown if display_markdown is None else display_markdown,
        start=node.start_offset,
        end=node.end_offset,
        heading_path=node.heading_path,
        heading_level=node.heading_level,
        content_type=content_type or node.type,
        node_ids=(node.id,),
        metadata={**node.metadata, "page_start": node.page_start, "page_end": node.page_end, **(metadata or {})},
    )


def _node_display(node: DocumentNode) -> str:
    if node.type == "blockquote":
        return f"備註：{node.text}"
    if node.type == "image":
        return f"圖片說明：{node.text}" if node.text else ""
    return node.text


def _render_list_item(item: dict[str, Any], *, ordered: bool, fallback: int) -> str:
    marker = f"{int(item.get('ordinal') or fallback)}." if ordered else "-"
    lines = [f"{marker} {str(item.get('text') or '').strip()}".strip()]
    for child_list in item.get("child_lists", []):
        if not isinstance(child_list, dict):
            continue
        child_ordered = bool(child_list.get("ordered"))
        for child_index, child in enumerate(child_list.get("items", []), start=int(child_list.get("start") or 1)):
            if not isinstance(child, dict):
                continue
            rendered = _render_list_item(child, ordered=child_ordered, fallback=child_index)
            lines.extend(f"  {line}" for line in rendered.splitlines())
    return "\n".join(lines)


def _semantic_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return f"表格欄位：{'、'.join(headers)}" if headers else "表格"
    rendered: list[str] = []
    for row in rows:
        rendered.append("\n".join(f"{header}：{row[index] if index < len(row) else ''}" for index, header in enumerate(headers)))
    return "\n\n".join(rendered)


def _list_batch_unit(node: DocumentNode, displays: list[str], item_nodes: list[DocumentNode], *, ordered: bool) -> _Unit:
    if item_nodes:
        start = item_nodes[0].start_offset
        end = item_nodes[-1].end_offset
        markdown = "\n".join(item.markdown.rstrip("\n") for item in item_nodes)
        page_starts = [item.page_start for item in item_nodes if item.page_start is not None]
        page_ends = [item.page_end for item in item_nodes if item.page_end is not None]
        node_ids = (node.id, *(item.id for item in item_nodes))
    else:
        start = node.start_offset
        end = node.end_offset
        markdown = "\n".join(displays)
        page_starts = [node.page_start] if node.page_start is not None else []
        page_ends = [node.page_end] if node.page_end is not None else []
        node_ids = (node.id,)
    metadata = {
        **node.metadata,
        "ordered": ordered,
        "item_count": len(displays),
        "page_start": min(page_starts) if page_starts else node.page_start,
        "page_end": max(page_ends) if page_ends else node.page_end,
    }
    return _Unit(
        display="\n".join(displays),
        display_markdown=markdown,
        start=start,
        end=end,
        heading_path=node.heading_path,
        heading_level=node.heading_level,
        content_type="list",
        node_ids=node_ids,
        metadata=metadata,
    )


def _table_batch_unit(
    node: DocumentNode,
    rows: list[list[str]],
    row_nodes: list[DocumentNode],
    *,
    headers: list[str],
    header_markdown: str,
    table_id: str,
    row_start: int,
    row_end: int,
) -> _Unit:
    if row_nodes:
        start = row_nodes[0].start_offset
        end = row_nodes[-1].end_offset
        row_markdown = "\n".join(row.markdown.rstrip("\n") for row in row_nodes)
        page_starts = [row.page_start for row in row_nodes if row.page_start is not None]
        page_ends = [row.page_end for row in row_nodes if row.page_end is not None]
        node_ids = (node.id, *(row.id for row in row_nodes))
    else:
        start = node.start_offset
        end = node.end_offset
        row_markdown = "\n".join(_markdown_table_row(row) for row in rows)
        page_starts = [node.page_start] if node.page_start is not None else []
        page_ends = [node.page_end] if node.page_end is not None else []
        node_ids = (node.id,)
    display_markdown = "\n".join(value for value in (header_markdown, row_markdown) if value).strip()
    return _Unit(
        display=_semantic_table(headers, rows),
        display_markdown=display_markdown,
        start=start,
        end=end,
        heading_path=node.heading_path,
        heading_level=node.heading_level,
        content_type="table",
        node_ids=node_ids,
        metadata={
            **node.metadata,
            "page_start": min(page_starts) if page_starts else node.page_start,
            "page_end": max(page_ends) if page_ends else node.page_end,
            "headers": headers,
            "table_id": table_id,
            "row_start": row_start,
            "row_end": row_end,
        },
    )


def _table_header_markdown(node: DocumentNode, header_row: DocumentNode | None, body_rows: list[DocumentNode]) -> str:
    if header_row is None:
        headers = [str(value) for value in node.metadata.get("headers", [])]
        return "\n".join((_markdown_table_row(headers), _markdown_table_delimiter(len(headers))))
    relative_start = max(0, header_row.end_offset - node.start_offset)
    relative_end = max(relative_start, (body_rows[0].start_offset if body_rows else node.end_offset) - node.start_offset)
    between = node.markdown[relative_start:relative_end]
    delimiter = next((line.rstrip() for line in between.splitlines() if "-" in line and "|" in line), "")
    if not delimiter:
        headers = [str(value) for value in node.metadata.get("headers", [])]
        delimiter = _markdown_table_delimiter(len(headers))
    return f"{header_row.markdown.rstrip()}\n{delimiter}".strip()


def _markdown_table_row(values: list[str]) -> str:
    escaped = [value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ") for value in values]
    return f"| {' | '.join(escaped)} |"


def _markdown_table_delimiter(column_count: int) -> str:
    return f"| {' | '.join('---' for _ in range(max(1, column_count)))} |"


def _fenced_code(content: str, language: str) -> str:
    longest = max((len(value) for value in re.findall(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{content}\n{fence}"


def _code_ranges(content: str, max_tokens: int, token_counter: TokenCounter) -> list[tuple[int, int]]:
    line_ranges: list[tuple[int, int]] = []
    cursor = 0
    for line in content.splitlines(keepends=True):
        end = cursor + len(line)
        if token_counter.count(line) <= max_tokens:
            line_ranges.append((cursor, end))
        else:
            line_ranges.extend((cursor + start, cursor + stop) for start, stop in token_windows(line, max_tokens=max_tokens))
        cursor = end
    if cursor < len(content):
        line_ranges.append((cursor, len(content)))
    if not line_ranges and content:
        line_ranges = token_windows(content, max_tokens=max_tokens)
    grouped: list[tuple[int, int]] = []
    pending_start: int | None = None
    pending_end = 0
    for start, end in line_ranges:
        candidate_start = start if pending_start is None else pending_start
        if pending_start is not None and token_counter.count(content[candidate_start:end]) > max_tokens:
            grouped.append((pending_start, pending_end))
            pending_start = start
        elif pending_start is None:
            pending_start = start
        pending_end = end
    if pending_start is not None:
        grouped.append((pending_start, pending_end))
    return grouped
