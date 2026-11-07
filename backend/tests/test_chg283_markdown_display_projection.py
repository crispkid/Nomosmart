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
from test_chg305_r20_r13_index_evidence import corpus  # noqa: F401


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
    # Genuine persisted vectors supply native serializer input. This does not
    # create a staged build/index or claim a new Provider execution.
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import Session
    from app.db.models import ActiveVersionManifest, Document, DocumentVersion, EmbeddingBuild, Project
    from app.domain.embeddings import load_published_embeddings, load_staging_embeddings
    from current_live_support import load_current_context

    current = load_current_context()
    scope = current["staging"]
    engine = create_engine(current["database_url"], hide_parameters=True)
    if current.get("serializer_corpus_reference") is not None:
        from sqlalchemy.orm import sessionmaker
        from current_native_workspace_support import retained_adapter_publication
        assert current["serializer_corpus_reference"] == current["current_adapters_publication_ref"] == 'retained-publication.json'
        scope = retained_adapter_publication(sessionmaker(engine))
    fingerprint = text("""SELECT md5(jsonb_build_object(
        'version',(SELECT to_jsonb(v) FROM document_versions v WHERE v.id=:version),
        'chunks',(SELECT jsonb_agg(to_jsonb(c) ORDER BY c.id) FROM chunks c WHERE c.document_version_id=:version),
        'manifest',(SELECT to_jsonb(m) FROM active_version_manifests m WHERE m.document_version_id=:version)
        )::text)""")
    version_id = UUID(scope["version_id"])
    try:
        with Session(engine, autoflush=False) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            before = session.scalar(fingerprint, {"version": version_id})
            version = session.get(DocumentVersion, version_id)
            assert version is not None
            project = session.get(Project, version.project_id)
            document = session.get(Document, version.document_id)
            assert str(project.id) == scope["project_id"] and str(document.id) == scope["document_id"]
            manifest = session.scalar(select(ActiveVersionManifest).where(
                ActiveVersionManifest.document_version_id == version.id))
            chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id,
                Chunk.status == "active").order_by(Chunk.chunk_index)))
            if version.published_at is not None:
                assert version.status == "active" and manifest is not None
                assert manifest.index_ready and manifest.publication_generation > 0
                build = session.get(EmbeddingBuild, manifest.embedding_build_id)
                batch = load_published_embeddings(session, project=project, version=version, chunks=chunks, build=build)
            else:
                assert manifest is None
                batch = load_staging_embeddings(session, project=project, version=version, chunks=chunks)
            assert len(batch.vectors) == len(chunks) and len(batch.vectors[0]) == batch.profile.vector_dimension
            eligible = [(c, v) for c, v in zip(chunks, batch.vectors, strict=True)
                        if c.display_markdown != c.content and c.retrieval_text != c.content]
            assert eligible, "BLOCKED: an actual formatted chunk and genuine vectors are required"
            chunk, vector = eligible[0]
            original = chunk.retrieval_text
            assert original and original.strip() and chunk.display_markdown
            payload = _staging_chunk_document(project, document, version, chunk, vector, batch.profile)
            assert payload["retrieval_text"] == original
            assert payload["display_markdown"] == chunk.display_markdown
            mapping = _vector_index_mapping(batch.profile)["mappings"]["properties"]
            assert mapping["display_markdown"] == {"type": "text", "index": False}
            try:
                chunk.retrieval_text = " "
                with pytest.raises(AppError) as missing:
                    _staging_chunk_document(project, document, version, chunk, vector, batch.profile)
                assert missing.value.code == "retrieval_reprocessing_required"
            finally:
                chunk.retrieval_text = original
                session.rollback()
            session.execute(text("SET TRANSACTION READ ONLY"))
            assert session.scalar(fingerprint, {"version": version_id}) == before
    finally:
        engine.dispose()


def test_staging_hash_mismatch_fails_before_existing_index_delete(corpus) -> None:
    adapter, source, request = corpus
    # Use a real persisted version/profile and genuine generated vectors. The
    # isolated index's UUID and document bytes prove that no deletion occurred.
    before_index=request('GET','')
    ids=[f"{source['version'].id}:{chunk.id}" for chunk in source['chunks']]
    before_documents=request('POST','/_mget',{'ids':ids})
    chunk=source['chunks'][0]
    original=chunk.embedding_content_hash
    chunk.embedding_content_hash='0'*64 if original!='0'*64 else '1'*64
    try:
        with pytest.raises(AppError) as blocked:
            adapter.write_chunks(**source)
        assert blocked.value.code == "retrieval_reprocessing_required"
        after_index=request('GET','')
        assert after_index.keys()==before_index.keys()
        assert {name:row['settings']['index']['uuid'] for name,row in after_index.items()}=={
            name:row['settings']['index']['uuid'] for name,row in before_index.items()}
        assert request('POST','/_mget',{'ids':ids})==before_documents
    finally:
        chunk.embedding_content_hash=original
