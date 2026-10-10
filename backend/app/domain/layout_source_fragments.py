"""Exact, read-only canonical positions for layout continuations.

Continuation identity and full ordered sequences disambiguate repeated rows.
Nothing is recovered using fuzzy text or a first-occurrence match.
"""
from collections import defaultdict
import re

from markdown_it import MarkdownIt
from app.domain.markdown_structure import DocumentStructure, _inline_value
from app.domain.inline_source_positions import inline_positions

_INLINE = MarkdownIt("commonmark", {"html": True}).enable(["strikethrough"])


def _fragment(block, kind, path, start, end, *, repeated=False):
    return {"fragment_id": f"{block['id']}:{kind}:{'.'.join(map(str, path))}",
            "kind": kind, "ordinal_path": path, "start_offset": start,
            "end_offset": end, "offset_unit": "unicode_code_point",
            "repeated_context": repeated}


def _cell_spans(raw, start, end, count):
    line = raw[start:end].rstrip("\r\n")
    pipes = []
    for i, ch in enumerate(line):
        if ch != "|":
            continue
        backslashes = 0
        cursor = i - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            pipes.append(i)
    segments = [(a + (1 if a in pipes else 0), b)
                for a, b in zip([0, *pipes], [*pipes, len(line)])]
    if pipes and not line[:pipes[0]].strip():
        segments = segments[1:]
    if pipes and not line[pipes[-1] + 1:].strip():
        segments = segments[:-1]
    if len(segments) != count:
        return []
    result = []
    for a, b in segments:
        while a < b and line[a].isspace():
            a += 1
        while b > a and line[b - 1].isspace():
            b -= 1
        result.append((start + a, start + b))
    return result


def attach_source_fragments(artifact: dict, structure: DocumentStructure) -> dict:
    raw = structure.raw_markdown
    nodes = {node.id: node for node in structure.nodes}
    children = defaultdict(list)
    for node in structure.nodes:
        children[node.parent].append(node)
    groups = defaultdict(list)
    for page in artifact.get("pages", []):
        for block in page.get("blocks", []):
            block["source_fragments"] = []
            groups[block.get("source_anchor")].append(block)
    for anchor, unsorted in groups.items():
        node = nodes.get(anchor)
        if node is None:
            continue
        blocks = sorted(unsorted, key=lambda b: b.get("continuation_index") or 1)
        count = len(blocks)
        if count > 1 and (any(b.get("continuation_count") != count for b in blocks)
                          or [b.get("continuation_index") for b in blocks] != list(range(1, count + 1))):
            continue
        if any(b.get("source_start_offset") not in (None, node.start_offset)
               or b.get("source_end_offset") not in (None, node.end_offset) for b in blocks):
            continue
        if node.type == "table":
            _table_fragments(blocks, node, children[node.id], raw)
        elif node.type == "list":
            _list_fragments(blocks, node, children[node.id], raw)
        elif node.type == "code_block":
            _text_fragments(blocks, node, raw)
        elif count == 1:
            kind = "code" if node.type == "code_block" else "image" if node.type == "image" else "text"
            blocks[0]["source_fragments"] = [_fragment(blocks[0], kind, [], node.start_offset, node.end_offset)]
        elif node.type in {"paragraph", "blockquote", "code_block"}:
            _text_fragments(blocks, node, raw)
    return artifact


def _table_fragments(blocks, node, row_nodes, raw):
    expected_rows = node.metadata.get("rows", [])
    if [row for b in blocks for row in b.get("rows", [])] != expected_rows:
        return
    if any(b.get("table_header", []) != node.metadata.get("headers", []) for b in blocks):
        return
    rows = sorted((r for r in row_nodes if r.type == "table_row"), key=lambda r: r.metadata["row_index"])
    headers = [r for r in rows if r.metadata.get("header")]
    body = [r for r in rows if not r.metadata.get("header")]
    if len(body) != len(expected_rows) or len(headers) > 1:
        return
    cursor = 0
    for block_index, block in enumerate(blocks):
        fragments = []
        if headers:
            header = headers[0]
            for col, (start, end) in enumerate(_cell_spans(raw, header.start_offset, header.end_offset,
                                                        len(block.get("table_header", [])))):
                if end > start:
                    fragments.append(_fragment(block, "table_header", [col], start, end, repeated=block_index > 0))
        for row_index, row in enumerate(block.get("rows", [])):
            source = body[cursor]
            spans = _cell_spans(raw, source.start_offset, source.end_offset, len(row))
            if len(spans) != len(row) or any(
                _inline_value(_INLINE.parseInline(raw[start:end])[0])[0].strip() != str(cell).strip()
                for cell, (start, end) in zip(row, spans)
            ):
                # Refuse one uncertain row rather than manufacture positions.
                for candidate in blocks:
                    candidate["source_fragments"] = []
                return
            for col, (start, end) in enumerate(spans):
                if end > start:
                    fragments.append(_fragment(block, "table_cell", [row_index, col], start, end))
            cursor += 1
        block["source_fragments"] = fragments


def _list_fragments(blocks, node, item_nodes, raw):
    sources = sorted((n for n in item_nodes if n.type == "list_item"), key=lambda n: n.start_offset)
    expected = node.metadata.get("items", [])
    if len(sources) != len(expected):
        return
    items = [(b, i, item) for b in blocks for i, item in enumerate(b.get("list_items", []))]
    cursor = 0
    for source, expected_item in zip(sources, expected):
        text = str(expected_item.get("text") or "")
        parts = []
        assembled = ""
        while cursor < len(items):
            block, index, item = items[cursor]
            candidate = assembled + str(item.get("text") or "")
            if not text.startswith(candidate):
                return
            parts.append((block, index, item))
            assembled = candidate
            cursor += 1
            if assembled == text:
                break
        if assembled != text:
            return
        if len(parts) == 1:
            block, index, _ = parts[0]
            block["source_fragments"].append(_fragment(block, "list_item", [index], source.start_offset, source.end_offset))
        else:
            source_raw = raw[source.start_offset:source.end_offset]
            marker = re.match(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+", source_raw)
            body = source_raw[marker.end():] if marker else ""
            positions = inline_positions(body, text) if marker else None
            if positions is None:
                continue
            visible = 0
            for block, index, item in parts:
                size = len(str(item.get("text") or ""))
                block["source_fragments"].extend(_projected_fragments(block, "list_item", [index],
                    positions[visible:visible + size], source.start_offset + marker.end(), raw))
                visible += size
    if cursor != len(items):
        for block in blocks:
            block["source_fragments"] = []


def _text_fragments(blocks, node, raw):
    parts = [str(b.get("text") or "") for b in blocks]
    joiner = "\n" if node.type == "code_block" else ""
    if joiner.join(parts) != node.text:
        return
    source = raw[node.start_offset:node.end_offset]
    if node.type == "code_block":
        tokens = _INLINE.parse(source)
        code = next((t for t in tokens if t.type in {"fence", "code_block"}), None)
        if code is None or code.content.rstrip("\n") != node.text:
            return
        lines = source.splitlines(keepends=True)
        visible_lines = code.content.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        candidates = []
        for index in range(len(lines) - len(visible_lines) + 1):
            positions = []
            for i, text in enumerate(visible_lines):
                line = lines[index + i]
                prefix = line[:-len(text)] if text else line
                if not line.endswith(text) or prefix.strip():
                    break
                start = offsets[index + i] + len(prefix)
                positions.extend((ch, start + j, start + j + 1) for j, ch in enumerate(text))
            else:
                candidates.append(positions[:len(node.text)])
        if len(candidates) != 1:
            return
        visible = 0
        for block, part in zip(blocks, parts):
            block["source_fragments"] = _projected_fragments(block, "code", [],
                candidates[0][visible:visible + len(part)], node.start_offset, raw)
            visible += len(part) + len(joiner)
        return
    # This is exact inside one verified node, and only unique occurrences are
    # accepted. Rich continuations without a unique source stay unmapped.
    if not node.text:
        return
    if source.count(node.text) != 1:
        positions = inline_positions(source, node.text)
        if positions is None:
            return
        visible = 0
        for block, part in zip(blocks, parts):
            block["source_fragments"] = _projected_fragments(block, "text", [],
                positions[visible:visible + len(part)], node.start_offset, raw)
            visible += len(part)
        return
    position = node.start_offset + source.index(node.text)
    for block, part in zip(blocks, parts):
        end = position + len(part)
        block["source_fragments"] = [_fragment(block, "code" if node.type == "code_block" else "text", [], position, end)]
        position = end + len(joiner)


def _projected_fragments(block, kind, path, positions, base, canonical):
    result = []
    for index, (ch, start, end) in enumerate(positions):
        start, end = base + start, base + end
        previous = result[-1] if result else None
        if (previous and previous["end_offset"] == start
                and canonical[start:end] == ch
                and previous.get("direct", False)):
            previous["end_offset"] = end
            previous["text_end_offset"] = index + 1
        else:
            fragment = _fragment(block, kind, path, start, end)
            fragment.update(fragment_id=f"{fragment['fragment_id']}:{index}",
                            text_start_offset=index, text_end_offset=index + 1,
                            direct=canonical[start:end] == ch)
            result.append(fragment)
    for fragment in result:
        fragment.pop("direct", None)
    return result
