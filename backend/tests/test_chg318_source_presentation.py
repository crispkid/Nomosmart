"""Native parser/provenance/state algorithms, not Provider or API acceptance."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest

from app.domain.document_layout import build_document_layout, hydrate_document_layout_inline_markdown, renderable_source_anchors
from app.domain.inline_source_positions import inline_positions
from app.domain.markdown_artifacts import normalize_source_mappings
from app.domain.markdown_structure import MarkdownStructureParser
from app.domain.ocr_presentation import ocr_call_state
from app.domain.structure_chunking import StructureAwareChunker


def mapping_for(source):
    structure = MarkdownStructureParser().parse(source)
    draft = StructureAwareChunker().chunk(structure, document_key="native-source", version_id=uuid4())[0]
    anchors = renderable_source_anchors(structure, start_offset=draft.start_offset, end_offset=draft.end_offset)
    return structure, draft, {"mapping_content": "markdown_fragment_v2", "node_ids": list(draft.node_ids),
        "source_anchor": anchors[0]["source_anchor"], "source_anchors": [a["source_anchor"] for a in anchors],
        "markdown_start_offset": draft.start_offset, "markdown_end_offset": draft.end_offset,
        "markdown_fragment_sha256": sha256(draft.raw_markdown.encode()).hexdigest()}


def test_structural_gap_is_not_a_missing_retrieval_unit():
    source = "第一段。\n\n---\n\n第二段 😀。\n\n# 範圍外\n\n其他來源。\n"
    structure, draft, mapping = mapping_for(source)
    assert len(mapping["source_anchors"]) > len(mapping["node_ids"])
    result = normalize_source_mappings(draft.display_text, [mapping], source)[0]
    assert result["mapping_status"] == "resolved"
    outside = structure.nodes[-1].id
    for changed in ({"node_ids": [*mapping["node_ids"], outside]},
                    {"node_ids": ["unknown-node"]}, {"node_ids": []},
                    {"source_anchors": list(reversed(mapping["source_anchors"]))},
                    {"source_anchor": outside}, {"markdown_fragment_sha256": "0" * 64},
                    {"markdown_end_offset": len(source) + 1}):
        assert normalize_source_mappings(draft.display_text, [{**mapping, **changed}], source)[0]["mapping_status"] == "unresolved"


@pytest.mark.parametrize("status,pipeline,claim,lease,state", [
    ("running", "running", True, 30, "in_flight"),
    ("running", "running", True, -1, "unconfirmed"),
    ("running", "running", False, 30, "unconfirmed"),
    ("failed", "failed", True, 30, "unconfirmed"),
    ("running", "failed", True, 30, "unconfirmed"),
])
def test_intent_classification_preserves_unknown_guard(status, pipeline, claim, lease, state):
    now = datetime(2026, 10, 8, tzinfo=UTC)
    assert ocr_call_state(has_intent=True, step_status=status, pipeline_status=pipeline,
        claim_token=uuid4() if claim else None, lease_expires_at=now + timedelta(seconds=lease), now=now) == state
    assert ocr_call_state(has_intent=False, step_status=status, pipeline_status=pipeline,
        claim_token=None, lease_expires_at=None, now=now) == "idle"


def test_ordered_duplicate_table_rows_keep_distinct_exact_positions():
    source = "| 標題 | 說明 |\n| --- | --- |\n" + "| 😀 | **相同列** é<br>1. 內容 |\n" * 8
    structure = MarkdownStructureParser().parse(source)
    artifact = build_document_layout(structure, page_budget=96)
    before = [(p["page_number"], [(b["id"], b["rows"]) for b in p["blocks"]]) for p in artifact["pages"]]
    hydrated = hydrate_document_layout_inline_markdown(artifact, structure)
    assert before == [(p["page_number"], [(b["id"], b["rows"]) for b in p["blocks"]]) for p in hydrated["pages"]]
    cells = [f for p in hydrated["pages"] for b in p["blocks"] for f in b["source_fragments"] if f["kind"] == "table_cell"]
    assert len(cells) == 16
    assert len({(f["start_offset"], f["end_offset"]) for f in cells}) == 16
    assert all(source[f["start_offset"]:f["end_offset"]] for f in cells)
    headers = [f for p in hydrated["pages"] for b in p["blocks"] for f in b["source_fragments"] if f["kind"] == "table_header"]
    assert headers and any(f["repeated_context"] for f in headers)


def test_inline_provenance_uses_codepoints_and_exact_semantic_roundtrip():
    raw = "**段落** &amp; 😀 é\n&nbsp;下一行"
    positions = inline_positions(raw, "段落 & 😀 é\n下一行")
    assert positions is not None
    assert "".join(char for char, *_ in positions) == "段落 & 😀 é\n下一行"
    assert all(0 <= start < end <= len(raw) for _, start, end in positions)
    emoji = next((start, end) for char, start, end in positions if char == "😀")
    assert raw[emoji[0]:emoji[1]] == "😀"
    assert inline_positions(raw, "不同文字") is None


def test_mutated_continuation_order_is_not_guessed():
    source = "| A | B |\n|---|---|\n" + "| one | two |\n" * 8
    structure = MarkdownStructureParser().parse(source)
    artifact = build_document_layout(structure, page_budget=96)
    blocks = [b for p in artifact["pages"] for b in p["blocks"]]
    assert len(blocks) > 1
    blocks[1]["continuation_index"] = 1
    hydrated = hydrate_document_layout_inline_markdown(artifact, structure)
    assert all(not b["source_fragments"] for p in hydrated["pages"] for b in p["blocks"])


def test_indented_code_maps_visible_lines_without_guessing_indentation():
    source = "    value = '😀'\n    print(value)\n    done = True\n"
    structure = MarkdownStructureParser().parse(source)
    layout = hydrate_document_layout_inline_markdown(build_document_layout(structure), structure)
    block = layout["pages"][0]["blocks"][0]
    assert block["type"] == "code" and len(block["source_fragments"]) == 3
    for fragment in block["source_fragments"]:
        assert source[fragment["start_offset"]:fragment["end_offset"]] == block["text"][fragment["text_start_offset"]:fragment["text_end_offset"]]
