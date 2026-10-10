"""v3 chunking: complete source units first, exact final-input capacity second."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from uuid import UUID, uuid5

from app.domain.embedding_capacity import EmbeddingInputContract, chunking_error
from app.domain.markdown_structure import DocumentNode, DocumentStructure, visible_markdown_text
from app.domain.retrieval_text import RetrievalTextNormalizer
from app.domain.structure_chunking import (ChunkDraft, ChunkingConfig, StructureAwareChunker, _Unit,
    _node_display, _unit_from_node, _table_batch_unit, _table_header_markdown, _list_batch_unit,
    _render_list_item, _fenced_code)
from app.domain.tokenization import complete_sentence_ranges


INTEGRITY_CHUNKER_VERSION = "structure-chunker-v3"


class IntegrityAwareChunker(StructureAwareChunker):
    def __init__(self, *, contract: EmbeddingInputContract, document_title: str,
                 config: ChunkingConfig | None = None):
        super().__init__(config=config, token_counter=contract.counter)
        self.contract = contract
        self.document_title = document_title
        self.normalizer = RetrievalTextNormalizer(config=self.config, token_counter=self.token_counter)
        self.canonical_sha256 = ""

    @property
    def version(self) -> str:
        return INTEGRITY_CHUNKER_VERSION

    def _input(self, unit: _Unit) -> str:
        return self.normalizer.normalize_parts(unit.display, heading_path=unit.heading_path,
                                              content_type=unit.content_type, document_title=self.document_title)

    def _fits(self, unit: _Unit) -> bool:
        return self.token_counter.count(self._input(unit)) <= self.contract.limit

    def _require(self, unit: _Unit, code: str = "chunk_atomic_unit_too_large") -> None:
        if not self._fits(unit) or code == "chunk_source_unresolved":
            raise chunking_error(code, contract=self.contract, unit=unit,
                                 input_tokens=self.token_counter.count(self._input(unit)), canonical_sha256=self.canonical_sha256)

    def chunk(self, structure: DocumentStructure, *, document_key: str, version_id: UUID) -> list[ChunkDraft]:
        self.canonical_sha256 = sha256(structure.raw_markdown.encode()).hexdigest()
        units: list[_Unit] = []
        excluded = {"document", "heading", "list_item", "table_row", "table_cell", "caption", "horizontal_rule", "page_break"}
        for node in structure.nodes:
            if node.type in excluded or node.metadata.get("retrieval_excluded"):
                continue
            if node.type == "table":
                units.extend(self._table_units(node, structure))
            elif node.type == "list":
                units.extend(self._list_units(node, structure))
            elif node.type == "code_block":
                units.extend(self._code_units(node))
            else:
                whole = _unit_from_node(node, _node_display(node))
                if not whole.display:
                    continue
                units.extend([whole] if self._fits(whole) else self._text_units(node))

        groups: list[list[_Unit]] = []
        pending: list[_Unit] = []
        for unit in units:
            self._require(unit)
            isolated = unit.content_type in {"table", "code", "code_block"}
            candidate = self._combined([*pending, unit])
            incompatible = pending and (unit.heading_path != pending[0].heading_path or isolated or pending[0].content_type in {"table", "code", "code_block"})
            if pending and (incompatible or self.token_counter.count(candidate.display) > self.config.target_chunk_tokens or not self._fits(candidate)):
                groups.append(pending)
                pending = []
            if isolated:
                groups.append([unit])
            else:
                pending.append(unit)
        if pending:
            groups.append(pending)
        drafts = [self._draft(group, index + 1, structure, document_key, version_id) for index, group in enumerate(groups)]
        for draft in drafts:
            unit = _Unit(draft.display_text, draft.display_markdown, draft.start_offset, draft.end_offset,
                         draft.heading_path, draft.heading_level, draft.content_type, draft.node_ids, draft.metadata)
            self._require(unit)  # Check the exact final representation, including joins.
        return [replace(draft, previous_chunk_id=drafts[index - 1].id if index else None,
                        next_chunk_id=drafts[index + 1].id if index + 1 < len(drafts) else None)
                for index, draft in enumerate(drafts)]

    def _combined(self, units: list[_Unit]) -> _Unit:
        first = units[0]
        types = {unit.content_type for unit in units}
        return replace(first, display="\n\n".join(unit.display for unit in units).strip(),
                       content_type=next(iter(types)) if len(types) == 1 else "mixed",
                       end=units[-1].end)

    def _draft(self, units, sequence, structure, document_key, version_id):
        draft = super()._draft(units, sequence, structure, document_key, version_id)
        if len(units) == 1 and units[0].content_type == "code_block":
            display = units[0].display.rstrip("\n")
            key = sha256((draft.stable_chunk_key + ":" + sha256(display.encode()).hexdigest()).encode()).hexdigest()
            draft = replace(draft, id=uuid5(version_id, key), stable_chunk_key=key,
                            display_text=display, token_count=self.token_counter.count(display))
        return draft

    def _fragment(self, node: DocumentNode, start: int, end: int) -> _Unit:
        raw = node.markdown[start:end]
        return replace(_unit_from_node(node, visible_markdown_text(raw), display_markdown=raw),
                       start=node.start_offset + start, end=node.start_offset + end,
                       metadata={**node.metadata, "page_start": node.page_start, "page_end": node.page_end, "split_reason": "model_capacity"})

    def _text_units(self, node: DocumentNode) -> list[_Unit]:
        ranges = complete_sentence_ranges(node.markdown)
        for start, end in ranges:
            self._require(self._fragment(node, start, end))
        batches: list[tuple[int, int]] = []
        start, end = ranges[0]
        for next_start, next_end in ranges[1:]:
            candidate = self._fragment(node, start, next_end)
            if self.token_counter.count(candidate.display) > self.config.max_chunk_tokens or not self._fits(candidate):
                batches.append((start, end))
                start = next_start
            end = next_end
        batches.append((start, end))
        units: list[_Unit] = []
        for index, (start, end) in enumerate(batches):
            if index and self.config.chunk_overlap_tokens:
                for previous_start, previous_end in reversed(ranges):
                    if previous_end > start:
                        continue
                    overlap = visible_markdown_text(node.markdown[previous_start:start])
                    if self.token_counter.count(overlap) > self.config.chunk_overlap_tokens:
                        break
                    if self._fits(self._fragment(node, previous_start, end)):
                        start = previous_start
                    else:
                        break
            units.append(self._fragment(node, start, end))
        return units

    def _list_units(self, node: DocumentNode, structure: DocumentStructure) -> list[_Unit]:
        items = [item for item in node.metadata.get("items", []) if isinstance(item, dict)]
        item_nodes = sorted((child for child in structure.nodes if child.type == "list_item" and child.parent == node.id), key=lambda child: child.start_offset)
        ordered = bool(node.metadata.get("ordered"))
        displays = [_render_list_item(item, ordered=ordered, fallback=index) for index, item in enumerate(items, 1)]
        if len(items) != len(item_nodes):
            self._require(_unit_from_node(node, node.text), "chunk_source_unresolved")
        whole = _list_batch_unit(node, displays, item_nodes, ordered=ordered)
        if self._fits(whole):
            return [whole]
        units: list[_Unit] = []
        for display, item in zip(displays, item_nodes, strict=True):
            unit = _list_batch_unit(node, [display], [item], ordered=ordered)
            units.extend([unit] if self._fits(unit) else self._text_units(item))
        return units

    def _table_units(self, node: DocumentNode, structure: DocumentStructure) -> list[_Unit]:
        headers = [str(value) for value in node.metadata.get("headers", [])]
        rows = [[str(cell) for cell in row] for row in node.metadata.get("rows", []) if isinstance(row, list)]
        nodes = sorted((child for child in structure.nodes if child.type == "table_row" and child.parent == node.id), key=lambda child: child.start_offset)
        header = next((child for child in nodes if child.metadata.get("header")), None)
        bodies = [child for child in nodes if not child.metadata.get("header")]
        if len(rows) != len(bodies) or header is None:
            self._require(_unit_from_node(node, node.text), "chunk_source_unresolved")
        header_markdown = _table_header_markdown(node, header, bodies)
        table_id = str(node.metadata.get("table_id") or node.id)

        def batch(start: int, end: int) -> _Unit:
            unit = _table_batch_unit(node, rows[start:end], bodies[start:end], headers=headers,
                header_markdown=header_markdown, table_id=table_id, row_start=start + 1, row_end=end)
            return replace(unit, metadata={**unit.metadata, "repeated_context": {"header_node_id": header.id,
                "start_offset": header.start_offset, "end_offset": header.end_offset},
                "row_source_ranges": [{"start_offset": row.start_offset, "end_offset": row.end_offset, "node_id": row.id} for row in bodies[start:end]]})

        whole = batch(0, len(rows))
        if self._fits(whole):
            return [whole]
        for index in range(len(rows)):
            self._require(batch(index, index + 1))
        # A reliable contiguous group is kept whole when it fits. Without group
        # provenance each row is an independent atomic unit; no text guessing.
        groups: list[tuple[int, int]] = []
        start = 0
        while start < len(rows):
            end = start + 1
            key = bodies[start].metadata.get("business_group_id")
            while key and end < len(rows) and bodies[end].metadata.get("business_group_id") == key:
                end += 1
            if self._fits(batch(start, end)):
                groups.append((start, end))
            else:
                groups.extend((index, index + 1) for index in range(start, end))
            start = end
        units: list[_Unit] = []
        start, end = groups[0]
        for next_start, next_end in groups[1:]:
            candidate = batch(start, next_end)
            if (next_end - start > self.config.table_chunk_max_rows or
                self.token_counter.count(candidate.display) > self.config.max_chunk_tokens or not self._fits(candidate)):
                units.append(batch(start, end))
                start = next_start
            end = next_end
        units.append(batch(start, end))
        return units

    def _code_units(self, node: DocumentNode) -> list[_Unit]:
        whole = _unit_from_node(node, node.text)
        if self._fits(whole):
            return [whole]
        content_start = node.markdown.find(node.text)
        if content_start < 0:
            self._require(whole, "chunk_source_unresolved")
        language = str(node.metadata.get("language") or "")
        units: list[_Unit] = []
        def part(start, end):
            body = node.text[start:end]
            return replace(whole, display=body.rstrip("\n"), display_markdown=_fenced_code(body, language),
                           start=node.start_offset + content_start + start, end=node.start_offset + content_start + end)
        start = end = 0
        for line in node.text.splitlines(keepends=True):
            next_end = end + len(line)
            self._require(part(end, next_end))
            candidate = part(start, next_end)
            if end > start and (self.token_counter.count(candidate.display) > self.config.max_chunk_tokens or not self._fits(candidate)):
                units.append(part(start, end))
                start = end
            end = next_end
        if end > start:
            units.append(part(start, end))
        return units
