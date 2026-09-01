from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.api.schemas import ApprovalChunkEvidence, ProcessingDebugChunk
from app.core.errors import AppError
from app.db.models import Chunk
from app.domain.extraction_pipeline import LiveOpenSearchStagingIndexAdapter, _staging_chunk_document, _vector_index_mapping
from app.domain.markdown_structure import MarkdownStructureParser
from app.domain.retrieval_text import RetrievalTextNormalizer, embedding_content_hash
from app.domain.structure_chunking import ChunkingConfig, DISPLAY_PROJECTION_VERSION, StructureAwareChunker
from app.domain.tokenization import UnicodeTokenCounter


VERSION_ID = UUID("11111111-1111-1111-1111-111111111111")


def _chunks(markdown: str, *, config: ChunkingConfig):
    structure = MarkdownStructureParser().parse(markdown)
    counter = UnicodeTokenCounter()
    chunks = StructureAwareChunker(config=config, token_counter=counter).chunk(
        structure,
        document_key="DOC-CHG283",
        version_id=VERSION_ID,
    )
    return structure, chunks, RetrievalTextNormalizer(config=config, token_counter=counter)


def test_display_markdown_is_distinct_from_exact_raw_and_normalized_retrieval_text() -> None:
    markdown = "# 容量治理\n\n1. **vLLM 擴容策略：** 監控 `vllm:num_requests_waiting`。\n2. *Triton* 可 Scale to Zero。\n"
    config = ChunkingConfig(target_chunk_tokens=60, max_chunk_tokens=80, min_chunk_tokens=4, chunk_overlap_tokens=0)
    _structure, chunks, normalizer = _chunks(markdown, config=config)

    assert len(chunks) == 1
    chunk = chunks[0]
    retrieval_text = normalizer.normalize(chunk, document_title="MaaS 架構規劃書")

    assert chunk.raw_markdown == markdown[markdown.index("1.") :]
    assert "**vLLM 擴容策略：**" in chunk.display_markdown
    assert "`vllm:num_requests_waiting`" in chunk.display_markdown
    assert chunk.display_text.startswith("1. vLLM 擴容策略： 監控 vllm:num_requests_waiting")
    assert retrieval_text.startswith("文件：MaaS 架構規劃書\n章節：容量治理")
    assert "**" not in retrieval_text
    assert "`" not in retrieval_text
    assert chunk.metadata["display_projection_version"] == DISPLAY_PROJECTION_VERSION


def test_split_ordered_list_projection_preserves_selected_source_items_and_nesting() -> None:
    markdown = (
        "3. **Parent** `x` alpha beta gamma\n"
        "   - Nested *bullet*\n\n"
        "     3. Nested ordered\n"
        "4. Next delta epsilon zeta eta theta\n"
        "7. Last item longer words one two three four\n"
    )
    config = ChunkingConfig(target_chunk_tokens=20, max_chunk_tokens=30, min_chunk_tokens=3, chunk_overlap_tokens=0)
    _structure, chunks, _normalizer = _chunks(markdown, config=config)

    assert len(chunks) == 2
    assert "3. **Parent** `x`" in chunks[0].display_markdown
    assert "Nested *bullet*" in chunks[0].display_markdown
    assert "4. Next" in chunks[0].display_markdown
    assert "7. Last" not in chunks[0].display_markdown
    assert chunks[1].display_markdown == "7. Last item longer words one two three four"
    assert "3. Parent" not in chunks[1].display_markdown
    assert chunks[0].raw_markdown == markdown[: markdown.index("7. Last")]
    assert chunks[1].raw_markdown == markdown[markdown.index("7. Last") :]


def test_split_table_projection_repeats_exact_header_and_only_selected_rows() -> None:
    markdown = (
        "| **產品** | `利率` |\n"
        "|---|---:|\n"
        "| A方案 | 2.1% |\n"
        "| B方案 | **2.3%** |\n"
        "| C方案 | 2.5% |\n"
    )
    config = ChunkingConfig(target_chunk_tokens=20, max_chunk_tokens=30, min_chunk_tokens=3, chunk_overlap_tokens=0, table_chunk_max_rows=2)
    _structure, chunks, normalizer = _chunks(markdown, config=config)

    assert len(chunks) == 2
    assert all(chunk.display_markdown.startswith("| **產品** | `利率` |\n|---|---:|") for chunk in chunks)
    assert "A方案" in chunks[0].display_markdown and "B方案" in chunks[0].display_markdown
    assert "C方案" not in chunks[0].display_markdown
    assert "C方案" in chunks[1].display_markdown
    assert "A方案" not in chunks[1].display_markdown and "B方案" not in chunks[1].display_markdown
    assert chunks[0].raw_markdown == "| A方案 | 2.1% |\n| B方案 | **2.3%** |\n"
    assert "產品：C方案" in normalizer.normalize(chunks[1], document_title="產品表")
    assert "|---" not in normalizer.normalize(chunks[1], document_title="產品表")


def test_split_fenced_code_projection_repeats_language_fence_and_preserves_only_selected_lines() -> None:
    code_lines = [f"metric_{index}: `[1]`" for index in range(12)]
    markdown = "```yaml\n" + "\n".join(code_lines) + "\n```\n"
    config = ChunkingConfig(target_chunk_tokens=6, max_chunk_tokens=8, min_chunk_tokens=2, chunk_overlap_tokens=0)
    _structure, chunks, _normalizer = _chunks(markdown, config=config)

    assert len(chunks) > 1
    assert all(chunk.display_markdown.startswith("```yaml\n") and chunk.display_markdown.endswith("\n```") for chunk in chunks)
    assert "\n".join(chunk.display_text for chunk in chunks) == "\n".join(code_lines)
    for index, chunk in enumerate(chunks):
        own_lines = chunk.display_text.splitlines()
        assert all(line in chunk.display_markdown for line in own_lines)
        other_lines = [line for line in code_lines if line not in own_lines]
        assert all(line not in chunk.display_markdown for line in other_lines)
        assert chunk.metadata["code_fragment"] == index + 1


def test_v047_and_additive_backend_contract_do_not_backfill_legacy_rows() -> None:
    assert "display_markdown" in Chunk.__table__.columns
    assert "display_markdown" in ApprovalChunkEvidence.model_fields
    assert "display_markdown" in ProcessingDebugChunk.model_fields

    migration = (Path(__file__).parents[2] / "sql/migrations/V047__markdown_display_and_retrieval_only_embedding.sql").read_text(encoding="utf-8")
    normalized = " ".join(migration.lower().split())
    assert "alter table chunks add column display_markdown text" in normalized
    assert "update chunks" not in normalized
    assert "delete from chunks" not in normalized
    assert "data_reprocessed', false" in normalized
    assert normalized.count("insert into audit_logs") == 1


def test_staging_serializes_unindexed_display_markdown_and_never_falls_back_to_content() -> None:
    retrieval_text = "文件：測試\n\nnormalized retrieval"
    model_id = UUID("66666666-6666-6666-6666-666666666666")
    chunk = SimpleNamespace(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        chunk_index=1,
        title="Chunk",
        content="plain display sentinel",
        markdown_content="**raw sentinel**",
        display_markdown="**display sentinel**",
        retrieval_text=retrieval_text,
        content_type="paragraph",
        heading_path=["測試"],
        section_path=None,
        heading_level=1,
        page_start=1,
        page_end=1,
        sequence=1,
        stable_chunk_key="a" * 64,
        embedding_model_id=model_id,
        embedding_content_hash=embedding_content_hash(
            retrieval_text=retrieval_text,
            embedding_model=str(model_id),
            embedding_model_version="embedding-v1",
            embedding_dimension=2,
            normalizer_version="normalizer-v1",
            tokenizer_version="tokenizer-v1",
        ),
        chunk_strategy={
            "parser_version": "parser-v1",
            "chunker_version": "chunker-v1",
            "normalizer_version": "normalizer-v1",
            "tokenizer_version": "tokenizer-v1",
        },
    )
    project = SimpleNamespace(id=UUID("33333333-3333-3333-3333-333333333333"))
    document = SimpleNamespace(id=UUID("44444444-4444-4444-4444-444444444444"), title="測試文件")
    version = SimpleNamespace(id=VERSION_ID, embedding_model_id=model_id, status="staging")
    profile = SimpleNamespace(
        id=UUID("55555555-5555-5555-5555-555555555555"),
        model_id=model_id,
        model_version="embedding-v1",
        vector_dimension=2,
        mapping_version=2,
    )

    payload = _staging_chunk_document(project, document, version, chunk, [0.1, 0.2], profile)
    assert payload["retrieval_text"] == "文件：測試\n\nnormalized retrieval"
    assert payload["display_markdown"] == "**display sentinel**"
    mapping = _vector_index_mapping(profile)["mappings"]["properties"]
    assert mapping["display_markdown"] == {"type": "text", "index": False}

    chunk.retrieval_text = " "
    with pytest.raises(AppError) as missing:
        _staging_chunk_document(project, document, version, chunk, [0.1, 0.2], profile)
    assert missing.value.code == "retrieval_reprocessing_required"


def test_staging_hash_mismatch_fails_before_existing_index_delete() -> None:
    model_id = UUID("66666666-6666-6666-6666-666666666666")
    chunk = SimpleNamespace(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        retrieval_text="文件：測試\n\nnormalized retrieval",
        embedding_model_id=model_id,
        embedding_content_hash="f" * 64,
        chunk_strategy={
            "parser_version": "parser-v1",
            "chunker_version": "chunker-v1",
            "normalizer_version": "normalizer-v1",
            "tokenizer_version": "tokenizer-v1",
        },
    )
    profile = SimpleNamespace(
        id=UUID("55555555-5555-5555-5555-555555555555"),
        model_id=model_id,
        model_version="embedding-v1",
        vector_dimension=2,
        mapping_version=2,
    )
    adapter = LiveOpenSearchStagingIndexAdapter(
        SimpleNamespace(opensearch_staging_live_write=True, opensearch_index_prefix="nomosmart-test")
    )
    delete_calls = 0

    def delete_should_not_run(**_kwargs) -> None:
        nonlocal delete_calls
        delete_calls += 1

    adapter.delete_version = delete_should_not_run  # type: ignore[method-assign]
    with pytest.raises(AppError) as blocked:
        adapter.write_chunks(
            project=SimpleNamespace(id=UUID("33333333-3333-3333-3333-333333333333")),
            document=SimpleNamespace(id=UUID("44444444-4444-4444-4444-444444444444"), title="測試"),
            version=SimpleNamespace(id=VERSION_ID),
            chunks=[chunk],
            vectors=[[0.1, 0.2]],
            profile=profile,
        )
    assert blocked.value.code == "retrieval_reprocessing_required"
    assert delete_calls == 0
