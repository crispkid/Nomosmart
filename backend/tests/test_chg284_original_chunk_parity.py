from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from app.domain.document_layout import build_document_layout, hydrate_document_layout_inline_markdown
from app.domain.markdown_artifacts import normalize_source_mappings
from app.domain.markdown_structure import MarkdownStructureParser


SOURCE = """# 企業級 MaaS 平台

本 MaaS 平台旨在打造一座具備超高吞吐量、低延遲且符合嚴格合規標準的企業級 AI 推論工廠。架構設計嚴守以下三大核心原則：

1. **控制與資料平面分離：** 將 API 路由管理與底層 GPU 高速運算網路徹底物理隔離。
2. **適材適用的雙軌推論：** 針對大型語言模型與傳統機器學習模型採取分流部署。
3. **零信任與精準問責：** 全面落實身分委派與治理框架。
"""


def _fixture():
    structure = MarkdownStructureParser().parse(SOURCE)
    paragraph = next(node for node in structure.nodes if node.type == "paragraph")
    list_node = next(node for node in structure.nodes if node.type == "list")
    fragment = SOURCE[paragraph.start_offset : list_node.end_offset]
    node_ids = [
        node.id
        for node in structure.nodes
        if paragraph.start_offset <= node.start_offset and node.end_offset <= list_node.end_offset
    ]
    mapping = {
        "source": "canonical-markdown-structure",
        "source_anchor": paragraph.id,
        "node_ids": node_ids,
        "offset_scope": "canonical_markdown",
        "offset_unit": "unicode_code_point",
        "markdown_start_offset": paragraph.start_offset,
        "markdown_end_offset": list_node.end_offset,
        "anchor_start_offset": 0,
        "anchor_end_offset": len(fragment),
        "mapping_status": "resolved",
        "mapping_content": "markdown_fragment_v2",
        "markdown_fragment_sha256": sha256(fragment.encode("utf-8")).hexdigest(),
    }
    return structure, paragraph, list_node, fragment, mapping


def test_multi_block_mapping_resolves_only_renderable_anchors() -> None:
    structure, paragraph, list_node, fragment, mapping = _fixture()

    resolved = normalize_source_mappings(fragment, [mapping], SOURCE)[0]

    assert resolved["mapping_status"] == "resolved"
    assert resolved["source_anchors"] == [paragraph.id, list_node.id]
    assert [item["source_anchor"] for item in resolved["source_anchor_ranges"]] == [paragraph.id, list_node.id]
    assert resolved["anchor_end_offset"] == paragraph.end_offset - paragraph.start_offset
    assert resolved["anchor_end_offset"] < len(fragment)
    assert all(node.id not in resolved["source_anchors"] for node in structure.nodes if node.type == "list_item")
    assert SOURCE[resolved["markdown_start_offset"] : resolved["markdown_end_offset"]] == fragment


def test_declared_renderable_anchor_mismatch_fails_closed() -> None:
    _, paragraph, _, fragment, mapping = _fixture()
    inconsistent = {**mapping, "source_anchors": [paragraph.id]}

    resolved = normalize_source_mappings(fragment, [inconsistent], SOURCE)[0]

    assert resolved["mapping_status"] == "unresolved"
    assert resolved["mapping_reason_code"] == "source_anchor_set_mismatch"


def test_layout_preserves_inline_markdown_for_paragraph_and_list_items() -> None:
    structure, paragraph, list_node, _, _ = _fixture()
    artifact = build_document_layout(structure)
    blocks = [block for page in artifact["pages"] for block in page["blocks"]]
    paragraph_block = next(block for block in blocks if block["source_anchor"] == paragraph.id)
    list_block = next(block for block in blocks if block["source_anchor"] == list_node.id)

    assert paragraph_block["inline_markdown"] == paragraph.markdown.strip()
    assert [item["inline_markdown"] for item in list_block["list_items"]] == [
        "**控制與資料平面分離：** 將 API 路由管理與底層 GPU 高速運算網路徹底物理隔離。",
        "**適材適用的雙軌推論：** 針對大型語言模型與傳統機器學習模型採取分流部署。",
        "**零信任與精準問責：** 全面落實身分委派與治理框架。",
    ]


def test_legacy_layout_is_hydrated_read_only_from_canonical_structure() -> None:
    structure, paragraph, list_node, _, _ = _fixture()
    artifact = build_document_layout(structure)
    legacy = deepcopy(artifact)
    for page in legacy["pages"]:
        for block in page["blocks"]:
            block.pop("inline_markdown", None)
            for item in block.get("list_items") or []:
                item.pop("inline_markdown", None)
    baseline = deepcopy(legacy)

    hydrated = hydrate_document_layout_inline_markdown(legacy, structure)
    blocks = [block for page in hydrated["pages"] for block in page["blocks"]]

    assert legacy == baseline
    assert next(block for block in blocks if block["source_anchor"] == paragraph.id)["inline_markdown"]
    list_block = next(block for block in blocks if block["source_anchor"] == list_node.id)
    assert list_block["list_items"][0]["inline_markdown"].startswith("**控制與資料平面分離：**")


def test_hydration_does_not_invent_markdown_when_visible_text_differs() -> None:
    structure, _, list_node, _, _ = _fixture()
    legacy = build_document_layout(structure)
    list_block = next(
        block
        for page in legacy["pages"]
        for block in page["blocks"]
        if block["source_anchor"] == list_node.id
    )
    list_block["list_items"][0]["text"] = "OCR content changed"
    list_block["list_items"][0].pop("inline_markdown", None)

    hydrated = hydrate_document_layout_inline_markdown(legacy, structure)
    hydrated_list = next(
        block
        for page in hydrated["pages"]
        for block in page["blocks"]
        if block["source_anchor"] == list_node.id
    )

    assert hydrated_list["list_items"][0]["text"] == "OCR content changed"
    assert "inline_markdown" not in hydrated_list["list_items"][0]


def test_legacy_table_and_image_semantics_are_hydrated_without_layout_changes() -> None:
    source = """| **Key** | Value |
| --- | --- |
| Mode | **Live** |

![Architecture diagram](diagram.png)
"""
    structure = MarkdownStructureParser().parse(source)
    legacy = build_document_layout(structure)
    for page in legacy["pages"]:
        for block in page["blocks"]:
            block.pop("table_header_markdown", None)
            block.pop("rows_markdown", None)
            block.pop("caption_markdown", None)
    baseline = deepcopy(legacy)

    hydrated = hydrate_document_layout_inline_markdown(legacy, structure)
    blocks = [block for page in hydrated["pages"] for block in page["blocks"]]
    table = next(block for block in blocks if block["type"] == "table")
    image = next(block for block in blocks if block["type"] == "image")

    assert legacy == baseline
    assert table["table_header_markdown"] == ["**Key**", "Value"]
    assert table["rows_markdown"] == [["Mode", "**Live**"]]
    assert image["caption_markdown"] == "Architecture diagram"
