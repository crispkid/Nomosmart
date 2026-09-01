from __future__ import annotations

from app.domain.document_layout import build_document_layout, estimated_layout_block_height
from app.domain.markdown_structure import MarkdownStructureParser


def _blocks(artifact: dict[str, object], block_type: str) -> list[dict[str, object]]:
    pages = artifact["pages"]
    assert isinstance(pages, list)
    return [block for page in pages for block in page["blocks"] if block["type"] == block_type]


def test_oversized_paragraph_is_lossless_deterministic_and_budgeted() -> None:
    paragraph = "第一段說明需要完整保留。" * 48 + "inline code vllm:num_requests_waiting must remain exact."
    structure = MarkdownStructureParser().parse(f"# 容量治理\n\n{paragraph}\n")

    first = build_document_layout(structure, page_budget=220)
    second = build_document_layout(structure, page_budget=220)

    assert first == second
    assert first["layout_version"] == "document-layout-v2"
    paragraphs = _blocks(first, "paragraph")
    assert len(paragraphs) > 1
    assert "".join(str(block["text"]) for block in paragraphs) == paragraph
    assert len({block["source_anchor"] for block in paragraphs}) == 1
    assert [block["continuation_index"] for block in paragraphs] == list(range(1, len(paragraphs) + 1))
    assert all(block["continuation_count"] == len(paragraphs) for block in paragraphs)
    assert all(estimated_layout_block_height(block) <= 220 for block in paragraphs)


def test_ordered_list_continuations_preserve_ordinals_and_text() -> None:
    source = "3. 第三項目\n4. 第四項目內容很長，" + ("必須完整保留。" * 36) + "\n7. 第七項目\n"
    artifact = build_document_layout(MarkdownStructureParser().parse(source), page_budget=190)
    lists = _blocks(artifact, "list")

    assert len(lists) >= 2
    assert all(block["list_ordered"] is True for block in lists)
    items = [item for block in lists for item in block["list_items"]]
    assert items[0]["value"] == 3
    assert items[-1]["value"] == 7
    assert "".join(item["text"] for item in items if item["value"] == 4) == "第四項目內容很長，" + ("必須完整保留。" * 36)


def test_nested_lists_preserve_ordering_and_parent_child_relationships() -> None:
    source = "1. Parent\n   - Nested bullet\n\n     3. Nested ordered\n2. Next\n"
    artifact = build_document_layout(MarkdownStructureParser().parse(source), page_budget=500)
    root = _blocks(artifact, "list")[0]["list_items"]

    assert [item["text"] for item in root] == ["Parent", "Next"]
    bullet = root[0]["child_lists"][0]
    assert bullet["ordered"] is False
    assert bullet["items"][0]["text"] == "Nested bullet"
    ordered = bullet["items"][0]["child_lists"][0]
    assert ordered["ordered"] is True
    assert ordered["start"] == 3
    assert ordered["items"][0]["value"] == 3


def test_large_table_repeats_header_without_losing_rows() -> None:
    rows = [f"| 方案 {index} | {index}.1% | {index} 年 |" for index in range(1, 13)]
    source = "| 產品 | 利率 | 期間 |\n| --- | ---: | ---: |\n" + "\n".join(rows)
    artifact = build_document_layout(MarkdownStructureParser().parse(source), page_budget=210)
    tables = _blocks(artifact, "table")

    assert len(tables) > 1
    assert all(block["table_header"] == ["產品", "利率", "期間"] for block in tables)
    assert [row for block in tables for row in block["rows"]] == [
        [f"方案 {index}", f"{index}.1%", f"{index} 年"] for index in range(1, 13)
    ]


def test_fenced_code_splits_on_lines_and_preserves_language_and_literal_citation() -> None:
    code = "\n".join(f"metric_{index}: `[1]`" for index in range(24))
    source = f"```yaml\n{code}\n```\n"
    artifact = build_document_layout(MarkdownStructureParser().parse(source), page_budget=180)
    blocks = _blocks(artifact, "code")

    assert len(blocks) > 1
    assert all(block["code_language"] == "yaml" for block in blocks)
    assert "\n".join(str(block["text"]) for block in blocks) == code


def test_blockquote_horizontal_rule_and_legacy_safe_metadata_are_additive() -> None:
    source = "> 備註內容\n\n---\n\n一般內容\n"
    artifact = build_document_layout(MarkdownStructureParser().parse(source), page_budget=500)

    assert _blocks(artifact, "blockquote")[0]["text"] == "備註內容"
    assert len(_blocks(artifact, "horizontal_rule")) == 1
    assert artifact["pagination"]["page_budget"] == 500
    assert artifact["warnings"] == []
