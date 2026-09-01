from __future__ import annotations

from uuid import UUID
from types import SimpleNamespace
from pathlib import Path

import pytest

from app.domain.markdown_structure import MarkdownStructureParser, mark_repeated_boilerplate, repeated_page_boilerplate
from app.domain.markdown_artifacts import normalize_source_mappings
from app.domain.retrieval_text import RetrievalTextNormalizer, embedding_content_hash
from app.domain.retrieval_evaluation import RetrievalExpectation, RetrievalHit, evaluate_retrieval
from app.domain.structure_chunking import ChunkingConfig, StructureAwareChunker
from app.domain.tokenization import UnicodeTokenCounter


SAMPLE = """# 房貸

## 提前清償

### 違約金

申請人須符合以下條件：

1. 年滿 **18 歲**
2. 具有身分證

> 外籍人士另依相關規定辦理。

| 產品 | 利率 |
|---|---:|
| A方案 | 2.1% |
| B方案 | 2.3% |

![房貸申請流程](image-001.png)

```sql
SELECT * FROM CUSTOMER;
```
"""


def _pipeline(markdown: str = SAMPLE):
    parser = MarkdownStructureParser()
    structure = parser.parse(markdown)
    config = ChunkingConfig(
        target_chunk_tokens=80,
        max_chunk_tokens=120,
        min_chunk_tokens=8,
        chunk_overlap_tokens=12,
        max_heading_depth=4,
        max_context_prefix_tokens=40,
        table_chunk_max_rows=10,
    )
    counter = UnicodeTokenCounter()
    chunks = StructureAwareChunker(config=config, token_counter=counter).chunk(
        structure,
        document_key="DOC001",
        version_id=UUID("11111111-1111-1111-1111-111111111111"),
    )
    normalizer = RetrievalTextNormalizer(config=config, token_counter=counter)
    return structure, chunks, [normalizer.normalize(chunk, document_title="房貸產品說明書") for chunk in chunks]


def test_parser_preserves_raw_markdown_and_structural_semantics():
    structure, _chunks, _texts = _pipeline()

    assert structure.raw_markdown == SAMPLE
    assert [node.type for node in structure.nodes].count("heading") == 3
    assert structure.nodes[0].type == "document"
    assert structure.nodes[0].markdown == SAMPLE
    assert [node.type for node in structure.nodes].count("list_item") == 2
    assert [node.type for node in structure.nodes].count("table_row") == 3
    assert [node.type for node in structure.nodes].count("table_cell") == 6
    caption = next(node for node in structure.nodes if node.type == "caption")
    image_node = next(node for node in structure.nodes if node.type == "image")
    assert caption.parent == image_node.id
    assert caption.markdown == "房貸申請流程"
    assert any(node.type == "list" and node.metadata["ordered"] is True for node in structure.nodes)
    table = next(node for node in structure.nodes if node.type == "table")
    assert table.metadata["headers"] == ["產品", "利率"]
    assert table.metadata["rows"][0] == ["A方案", "2.1%"]
    assert any(node.type == "blockquote" and "外籍人士" in node.text for node in structure.nodes)
    code = next(node for node in structure.nodes if node.type == "code_block")
    assert code.metadata["language"] == "sql"
    assert "SELECT * FROM CUSTOMER;" in code.text
    image = next(node for node in structure.nodes if node.type == "image")
    assert image.text == "房貸申請流程"
    assert image.metadata["url"] == "image-001.png"
    for node in structure.nodes:
        assert structure.raw_markdown[node.start_offset : node.end_offset] == node.markdown


def test_code_block_preserves_indentation_in_display_and_retrieval_text():
    markdown = "# SQL\n\n```python\nif ready:\n    run_job()\n```\n"
    structure, chunks, texts = _pipeline(markdown)
    code = next(node for node in structure.nodes if node.type == "code_block")
    assert code.text == "if ready:\n    run_job()"
    code_index = next(index for index, chunk in enumerate(chunks) if chunk.content_type == "code_block")
    assert "if ready:\n    run_job()" in chunks[code_index].display_text
    assert "if ready:\n    run_job()" in texts[code_index]


def test_header_only_table_remains_a_retrievable_semantic_unit():
    structure = MarkdownStructureParser().parse("# 欄位\n\n| 名稱 | 說明 |\n|---|---|\n")
    config = ChunkingConfig(target_chunk_tokens=30, max_chunk_tokens=45, min_chunk_tokens=4, chunk_overlap_tokens=0)
    chunks = StructureAwareChunker(config=config, token_counter=UnicodeTokenCounter()).chunk(
        structure,
        document_key="HEADER-ONLY",
        version_id=UUID("99999999-9999-9999-9999-999999999999"),
    )
    assert len(chunks) == 1
    assert chunks[0].display_text == "表格欄位：名稱、說明"


def test_string_boolean_chunk_configuration_is_not_truthy_by_accident():
    from app.domain.extraction_pipeline import _config_bool

    assert _config_bool("false", True) is False
    assert _config_bool("YES", False) is True
    with pytest.raises(ValueError, match="true/false"):
        _config_bool("sometimes", True)


def test_html_and_strikethrough_keep_visible_business_text_without_tags():
    structure = MarkdownStructureParser().parse("# 文件\n\n<div>保留 <strong>業務文字</strong></div>\n\n~~舊名稱~~\n")
    visible = "\n".join(node.text for node in structure.nodes)
    assert "保留 業務文字" in visible
    assert "舊名稱" in visible
    assert "<div>" not in visible
    assert "~~" not in visible


def test_heading_context_is_inherited_without_markdown_formatting_noise():
    _structure, chunks, texts = _pipeline()

    body_chunk = next(chunk for chunk in chunks if "申請人須符合" in chunk.display_text)
    assert body_chunk.heading_path == ("房貸", "提前清償", "違約金")
    retrieval = texts[chunks.index(body_chunk)]
    assert "文件：房貸產品說明書" in retrieval
    assert "章節：房貸 > 提前清償 > 違約金" in retrieval
    assert "年滿 18 歲" in retrieval
    assert "**" not in retrieval
    assert "###" not in retrieval


def test_table_normalization_retains_header_row_relationship():
    _structure, chunks, texts = _pipeline()

    table_index = next(index for index, chunk in enumerate(chunks) if chunk.content_type == "table")
    table_text = texts[table_index]
    assert "產品：A方案" in table_text
    assert "利率：2.1%" in table_text
    assert "產品：B方案" in table_text
    assert "|---" not in table_text


def test_unrelated_heading_sections_never_merge_and_short_section_keeps_context():
    markdown = """# 房貸

## 違約金

免收。

## 延遲繳款

延遲繳款規定。
"""
    _structure, chunks, texts = _pipeline(markdown)

    assert len(chunks) == 2
    assert chunks[0].heading_path == ("房貸", "違約金")
    assert chunks[1].heading_path == ("房貸", "延遲繳款")
    assert "章節：房貸 > 違約金" in texts[0]
    assert "免收。" in texts[0]
    assert "延遲繳款" not in chunks[0].display_text


def test_large_table_batches_repeat_headers():
    rows = "\n".join(f"| P{index} | {index}.1% |" for index in range(1, 8))
    markdown = f"# 方案\n\n| 產品 | 利率 |\n|---|---:|\n{rows}\n"
    parser = MarkdownStructureParser()
    structure = parser.parse(markdown)
    config = ChunkingConfig(target_chunk_tokens=30, max_chunk_tokens=45, min_chunk_tokens=4, chunk_overlap_tokens=0, table_chunk_max_rows=2)
    chunks = StructureAwareChunker(config=config, token_counter=UnicodeTokenCounter()).chunk(
        structure,
        document_key="TABLE",
        version_id=UUID("22222222-2222-2222-2222-222222222222"),
    )

    table_chunks = [chunk for chunk in chunks if chunk.content_type == "table"]
    assert len(table_chunks) == 4
    assert all(chunk.metadata["headers"] == ["產品", "利率"] for chunk in table_chunks)
    assert [(chunk.metadata["row_start"], chunk.metadata["row_end"]) for chunk in table_chunks] == [(1, 2), (3, 4), (5, 6), (7, 7)]


def test_oversized_single_table_row_keeps_column_context_in_every_fragment():
    markdown = "# 方案\n\n| 產品 | 說明 |\n|---|---|\n| A | " + ("超長說明" * 80) + " |\n"
    structure = MarkdownStructureParser().parse(markdown)
    config = ChunkingConfig(target_chunk_tokens=35, max_chunk_tokens=45, min_chunk_tokens=4, chunk_overlap_tokens=0, table_chunk_max_rows=10)
    chunks = StructureAwareChunker(config=config, token_counter=UnicodeTokenCounter()).chunk(
        structure,
        document_key="LONG-TABLE",
        version_id=UUID("88888888-8888-8888-8888-888888888888"),
    )
    assert len(chunks) > 1
    assert all(chunk.display_text.startswith("表格欄位：產品、說明") for chunk in chunks)
    assert all(chunk.token_count <= config.max_chunk_tokens for chunk in chunks)


def test_processing_debug_route_is_explicit_and_role_protected():
    from app.api.routes import documents

    route = next(route for route in documents.router.routes if route.path.endswith("/processing-debug"))
    assert route.methods == {"GET"}
    assert documents.PROCESSING_DEBUG_ROLES
    assert documents.PROCESSING_DEBUG_ROLES == documents.PROJECT_EDITOR_ROLES | documents.PROJECT_OWNER_ROLES


def test_v046_is_additive_and_does_not_reprocess_existing_chunks():
    from app.db.models import Chunk

    expected = {
        "retrieval_text",
        "embedding_content_hash",
        "heading_path",
        "heading_level",
        "page_start",
        "page_end",
        "sequence",
        "stable_chunk_key",
    }
    assert expected <= set(Chunk.__table__.columns.keys())
    migration = (Path(__file__).parents[2] / "sql/migrations/V046__structure_aware_retrieval_chunks.sql").read_text(encoding="utf-8")
    normalized = " ".join(migration.lower().split())
    assert "alter table chunks" in normalized
    assert "update chunks" not in normalized
    assert "delete from chunks" not in normalized
    assert "data_reprocessed', false" in normalized


def test_structure_aware_embedding_profile_never_reuses_mapping_v1():
    from app.domain.embeddings import _profile_for_vectors

    class Session:
        def __init__(self) -> None:
            self.added = []

        def scalar(self, _statement):
            return None

        def add(self, value):
            self.added.append(value)

        def flush(self):
            return None

    session = Session()
    model = SimpleNamespace(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        name="embedding",
        config={"model_name": "embedding-v1", "mapping_version": 1},
    )
    version = SimpleNamespace(chunk_strategy={"structure_aware": True})
    profile = _profile_for_vectors(session, model, version, [[0.1, 0.2, 0.3]])
    assert profile.mapping_version == 2
    assert profile.vector_dimension == 3


def test_embedding_build_fingerprint_does_not_drift_after_final_hash_is_persisted():
    from app.domain.embeddings import _content_fingerprint

    model = SimpleNamespace(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        config_version="v1",
        name="embedding-model",
        config={"model_name": "text-embedding-test", "mapping_version": 2, "dimensions": 8},
    )
    chunk = SimpleNamespace(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        chunk_index=1,
        stable_chunk_key="c" * 64,
        embedding_content_hash="provisional-value",
        chunk_strategy={"structure_aware": True, "normalizer_version": "n2", "tokenizer_version": "t2"},
    )
    before = _content_fingerprint(model, [chunk], ["文件：測試\n\n內容"])
    chunk.embedding_content_hash = "f" * 64
    after = _content_fingerprint(model, [chunk], ["文件：測試\n\n內容"])

    assert after == before


def test_canonical_markdown_artifact_precedes_structure_parsing_and_chunking():
    from app.domain.extraction_pipeline import AUTO_EXTRACTION_STEPS, _canonical_markdown_source

    assert AUTO_EXTRACTION_STEPS.index("ocr_extract") < AUTO_EXTRACTION_STEPS.index("generate_markdown")
    assert AUTO_EXTRACTION_STEPS.index("generate_markdown") < AUTO_EXTRACTION_STEPS.index("split_paragraphs")
    assert AUTO_EXTRACTION_STEPS.index("split_paragraphs") < AUTO_EXTRACTION_STEPS.index("chunk_knowledge")
    text, source = _canonical_markdown_source({
        "generate_markdown": SimpleNamespace(payload={"markdown": "# Canonical\n", "adapter_source": "stored-artifact"}),
        "parse_document": SimpleNamespace(payload={"canonical_markdown": "# Parser\n"}),
    })
    assert text == "# Canonical\n"
    assert source == "stored-artifact"


def test_deterministic_identity_and_embedding_hash_invalidation():
    _structure, first, texts = _pipeline()
    _structure, second, second_texts = _pipeline()

    assert [(item.id, item.stable_chunk_key) for item in first] == [(item.id, item.stable_chunk_key) for item in second]
    assert texts == second_texts
    base = embedding_content_hash(
        retrieval_text=texts[0],
        embedding_model="text-embedding-test",
        embedding_model_version="1",
        embedding_dimension=1024,
        normalizer_version="retrieval-normalizer-v2",
        tokenizer_version="unicode-regex-v1",
    )
    same_display = embedding_content_hash(
        retrieval_text=texts[0],
        embedding_model="text-embedding-test",
        embedding_model_version="1",
        embedding_dimension=1024,
        normalizer_version="retrieval-normalizer-v2",
        tokenizer_version="unicode-regex-v1",
    )
    changed_retrieval = embedding_content_hash(
        retrieval_text=texts[0] + " 補充",
        embedding_model="text-embedding-test",
        embedding_model_version="1",
        embedding_dimension=1024,
        normalizer_version="retrieval-normalizer-v2",
        tokenizer_version="unicode-regex-v1",
    )
    changed_model = embedding_content_hash(
        retrieval_text=texts[0],
        embedding_model="text-embedding-test",
        embedding_model_version="2",
        embedding_dimension=1024,
        normalizer_version="retrieval-normalizer-v2",
        tokenizer_version="unicode-regex-v1",
    )
    assert base == same_display
    assert changed_retrieval != base
    assert changed_model != base


def test_config_rejects_invalid_token_boundaries():
    with pytest.raises(ValueError):
        ChunkingConfig(target_chunk_tokens=700, max_chunk_tokens=500)
    with pytest.raises(ValueError):
        ChunkingConfig(min_chunk_tokens=600, target_chunk_tokens=500)


def test_ordered_list_explicit_start_is_preserved():
    structure = MarkdownStructureParser().parse("# 規則\n\n3. 第三項\n4. 第四項\n")
    list_node = next(node for node in structure.nodes if node.type == "list")
    assert list_node.metadata["start"] == 3
    assert [item["ordinal"] for item in list_node.metadata["items"]] == [3, 4]


def test_retrieval_evaluation_reports_recall_mrr_and_top_k_hit_rate():
    cases = [
        (
            RetrievalExpectation(query="A方案利率", expected_document_id="doc-table", expected_section=("產品方案",), expected_chunk_id="table-1"),
            [
                RetrievalHit(document_id="other", chunk_id="x"),
                RetrievalHit(document_id="doc-table", chunk_id="table-1", heading_path=("產品方案",)),
            ],
        ),
        (
            RetrievalExpectation(query="提前清償", expected_document_id="doc-loan", expected_section=("房貸", "提前清償", "違約金")),
            [RetrievalHit(document_id="doc-loan", chunk_id="loan-1", heading_path=("房貸", "提前清償", "違約金"))],
        ),
    ]
    metrics = evaluate_retrieval(cases, k=2)

    assert metrics.case_count == 2
    assert metrics.recall_at_k == 1.0
    assert metrics.top_k_hit_rate == 1.0
    assert metrics.mean_reciprocal_rank == 0.75


def test_pipeline_persists_raw_display_retrieval_and_resolvable_source_mapping(caplog):
    from app.core.config import Settings
    from app.domain.extraction_pipeline import _create_structure_chunks

    class Session:
        def __init__(self) -> None:
            self.added = []

        def execute(self, _statement):
            return None

        def add(self, value):
            self.added.append(value)

        def flush(self):
            return None

    session = Session()
    project = SimpleNamespace(id=UUID("33333333-3333-3333-3333-333333333333"))
    document = SimpleNamespace(id=UUID("44444444-4444-4444-4444-444444444444"), title="房貸產品說明書")
    version = SimpleNamespace(
        id=UUID("55555555-5555-5555-5555-555555555555"),
        embedding_model_id=None,
        chunk_strategy={},
        chunk_size=None,
        chunk_overlap=None,
    )
    caplog.set_level("INFO", logger="app.domain.extraction_pipeline")
    sensitive_sentinel = "SENSITIVE-CHG281-DO-NOT-LOG"
    markdown = f"# 房貸\n\n## 違約金\n\n年收入須達 **30 萬元**。{sensitive_sentinel}\n"

    chunks = _create_structure_chunks(session, Settings(_env_file=None), project, document, version, markdown)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.content == f"年收入須達 30 萬元。{sensitive_sentinel}"
    assert chunk.markdown_content == f"年收入須達 **30 萬元**。{sensitive_sentinel}\n"
    assert chunk.retrieval_text == f"文件：房貸產品說明書\n章節：房貸 > 違約金\n\n年收入須達 30 萬元。{sensitive_sentinel}"
    assert chunk.heading_path == ["房貸", "違約金"]
    assert chunk.stable_chunk_key and len(chunk.stable_chunk_key) == 64
    assert chunk.embedding_content_hash and len(chunk.embedding_content_hash) == 64
    mapping = normalize_source_mappings(chunk.content, chunk.source_mapping, markdown)[0]
    assert mapping["mapping_status"] == "resolved"
    assert mapping["source_anchors"] == [mapping["source_anchor"]]
    assert chunk.source_mapping[0]["source_anchors"] == [mapping["source_anchor"]]
    assert chunk.source_mapping[0]["source_anchor_ranges"][0]["anchor_end_offset"] == len(chunk.markdown_content)
    assert markdown[mapping["markdown_start_offset"] : mapping["markdown_end_offset"]] == chunk.markdown_content
    assert version.chunk_strategy["structure_aware"] is True
    assert sensitive_sentinel not in caplog.text
    record = next(record for record in caplog.records if record.message == "structure_aware_chunks_created")
    assert record.chunk_count == 1
    assert record.parser_version.startswith("markdown-it-py")


def test_mapping_v2_and_keyword_contract_prioritize_retrieval_fields():
    from app.api.routes.serving import _keyword_query_body
    from app.domain.extraction_pipeline import _vector_index_mapping

    mapping = _vector_index_mapping(SimpleNamespace(vector_dimension=3, mapping_version=2))["mappings"]["properties"]
    assert mapping["retrieval_text"]["type"] == "text"
    assert mapping["display_text"] == {"type": "text", "index": False}
    assert mapping["stable_chunk_key"]["type"] == "keyword"
    assert mapping["embedding_vector"]["dimension"] == 3
    query = _keyword_query_body(
        UUID("66666666-6666-6666-6666-666666666666"),
        "提前清償",
        ["version"],
        5,
        "staging",
        mapping_version=2,
    )
    fields = query["query"]["bool"]["must"][0]["multi_match"]["fields"]
    assert fields == ["retrieval_text"]


def test_long_paragraph_uses_sentence_then_token_boundaries_without_data_loss():
    markdown = "# 長文\n\n" + "第一句很重要。" * 80 + "UNBROKEN" * 120
    structure = MarkdownStructureParser().parse(markdown)
    config = ChunkingConfig(target_chunk_tokens=35, max_chunk_tokens=45, min_chunk_tokens=4, chunk_overlap_tokens=5)
    chunks = StructureAwareChunker(config=config, token_counter=UnicodeTokenCounter()).chunk(
        structure,
        document_key="LONG",
        version_id=UUID("77777777-7777-7777-7777-777777777777"),
    )

    assert len(chunks) > 1
    assert all(chunk.token_count <= config.max_chunk_tokens for chunk in chunks)
    assert chunks[-1].raw_markdown.endswith("UNBROKEN" * 120)


def test_repeated_header_footer_requires_reliable_cross_page_recurrence():
    pages = [
        "中國信託銀行\n第一頁內容\n第 1 頁 / 共 3 頁",
        "中國信託銀行\n第二頁內容\n第 2 頁 / 共 3 頁",
        "中國信託銀行\n第三頁內容\n第 3 頁 / 共 3 頁",
    ]
    detected = repeated_page_boilerplate(pages)
    assert detected["headers"] == ["中國信託銀行"]
    assert detected["footers"] == []
    assert repeated_page_boilerplate(pages[:2]) == {"headers": [], "footers": []}


def test_reliable_page_ranges_are_metadata_and_repeated_header_is_excluded_only_from_chunks():
    pages = [f"中國信託銀行\n\n第 {index} 頁內容" for index in range(1, 4)]
    markdown = "\n\n".join(pages)
    ranges = []
    cursor = 0
    for index, page in enumerate(pages, start=1):
        ranges.append({"page": index, "start_offset": cursor, "end_offset": cursor + len(page)})
        cursor += len(page) + 2
    structure = MarkdownStructureParser().parse(markdown, page_ranges=ranges)
    marked = mark_repeated_boilerplate(structure, {"中國信託銀行"})
    chunks = StructureAwareChunker(config=ChunkingConfig(target_chunk_tokens=40, max_chunk_tokens=60, min_chunk_tokens=4, chunk_overlap_tokens=5), token_counter=UnicodeTokenCounter()).chunk(
        marked,
        document_key="PAGES",
        version_id=UUID("99999999-9999-9999-9999-999999999999"),
    )
    assert marked.raw_markdown == markdown
    assert {node.page_start for node in marked.nodes if "頁內容" in node.text} == {1, 2, 3}
    assert all("中國信託銀行" not in chunk.display_text for chunk in chunks)
