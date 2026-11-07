from __future__ import annotations

from inspect import getsource
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.api.routes.serving import _keyword_query_body
from app.db.models import Chunk, EmbeddingProfile
from app.api.routes.documents import _split_chunk
from app.domain import embeddings
from app.domain.chunk_representations import build_manual_chunk_representation
from app.domain.extraction_pipeline import _vector_index_mapping as staging_vector_index_mapping
from app.domain.retrieval_text import embedding_content_hash, provisional_retrieval_hash
from app.domain.review_publish import LiveOpenSearchPublishedAdapter, _vector_index_mapping, chunk_checksum


def _strategy() -> dict[str, object]:
    return {
        "structure_aware": True,
        "parser_version": "parser-test-v1",
        "chunker_version": "chunker-test-v1",
        "normalizer_version": "normalizer-test-v1",
        "tokenizer_version": "tokenizer-test-v1",
    }


def _chunk(*, retrieval_text: str | None, retrieval_hash: str | None) -> Chunk:
    return Chunk(
        id=uuid4(),
        project_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        chunk_index=1,
        title="Chunk",
        content="DISPLAY-ONLY **sentinel**",
        markdown_content="RAW-ONLY `sentinel`",
        display_markdown="DISPLAY-MARKDOWN-ONLY **sentinel**",
        retrieval_text=retrieval_text,
        embedding_content_hash=retrieval_hash,
        content_type="text",
        content_hash="0" * 64,
        source_mapping=[],
        chunk_strategy=_strategy(),
        status="active",
        is_manual_edited=False,
    )


def test_manual_representation_separates_markdown_display_and_retrieval_text() -> None:
    raw = (
        "1. **vLLM 擴容策略：** 監控 `vllm:num_requests_waiting`。\n"
        "2. **Triton 擴容策略：** 監控佇列等待時間。\n"
    )

    representation = build_manual_chunk_representation(
        raw_markdown=raw,
        document_title="企業級 MaaS 平台架構規劃書",
        inherited_heading_path=["平台架構", "擴容策略"],
    )

    assert representation.raw_markdown == raw
    assert representation.display_markdown == raw
    assert representation.display_text.startswith("1. vLLM 擴容策略：")
    assert "`" not in representation.display_text
    assert "**" not in representation.display_text
    assert representation.retrieval_text.startswith("文件：企業級 MaaS 平台架構規劃書\n章節：平台架構 > 擴容策略\n\n1.")
    assert "vllm:num_requests_waiting" in representation.retrieval_text
    assert "DISPLAY-ONLY" not in representation.retrieval_text
    assert representation.processing_metadata["parser_version"]
    assert representation.processing_metadata["normalizer_version"]
    assert representation.processing_metadata["tokenizer_version"]
    assert len(representation.embedding_content_hash) == 64


def test_strict_embedding_resolver_uses_only_retrieval_text_and_legacy_is_explicit() -> None:
    text = "文件：MaaS\n章節：擴容\n\n1. 監控 vllm:num_requests_waiting。"
    retrieval_hash = provisional_retrieval_hash(
        retrieval_text=text,
        normalizer_version="normalizer-test-v1",
        tokenizer_version="tokenizer-test-v1",
    )
    chunk = _chunk(retrieval_text=text, retrieval_hash=retrieval_hash)

    assert embeddings.resolve_embedding_retrieval_text(chunk) == text

    chunk.chunk_strategy = {key: value for key, value in _strategy().items() if key != "chunker_version"}
    with pytest.raises(AppError) as incomplete:
        embeddings.resolve_embedding_retrieval_text(chunk)
    assert incomplete.value.code == "retrieval_reprocessing_required"
    assert incomplete.value.details["missing_evidence"] == ["chunker_version"]

    chunk.chunk_strategy = _strategy()
    chunk.retrieval_text = None
    with pytest.raises(AppError) as missing:
        embeddings.resolve_embedding_retrieval_text(chunk)
    assert missing.value.code == "retrieval_reprocessing_required"
    assert embeddings.legacy_read_only_chunk_text(chunk) == "DISPLAY-ONLY **sentinel**"


def test_invalid_retrieval_evidence_stops_before_provider_boundary() -> None:
    chunk = _chunk(retrieval_text=None, retrieval_hash=None)
    with pytest.raises(AppError) as blocked:
        embeddings.resolve_embedding_retrieval_text(chunk)
    assert blocked.value.code == "retrieval_reprocessing_required"

    embed_source = getsource(embeddings.embed_chunks)
    assert embed_source.index("texts = [resolve_embedding_retrieval_text") < embed_source.index("response = _post_openai_embeddings")


def test_publish_writer_rejects_hash_mismatch_before_index_write() -> None:
    model_id = uuid4()
    profile = EmbeddingProfile(
        id=uuid4(),
        model_id=model_id,
        model_version="embedding-v1",
        vector_dimension=3,
        distance_method="cosine",
        chunk_strategy={},
        mapping_version=2,
    )
    chunk = _chunk(retrieval_text="文件：MaaS\n\n合法檢索文字", retrieval_hash="f" * 64)
    chunk.embedding_model_id = model_id
    version = SimpleNamespace(id=chunk.document_version_id, embedding_profile_id=profile.id, embedding_model_id=model_id)
    adapter = LiveOpenSearchPublishedAdapter(
        SimpleNamespace(
            opensearch_index_prefix="nomosmart-test",
            opensearch_url="https://opensearch.invalid",
            opensearch_ssl_context=None,
        )
    )
    index_attempts = 0

    def index_should_not_run(*_args, **_kwargs):
        nonlocal index_attempts
        index_attempts += 1
        raise AssertionError("Index creation must not run")

    adapter._ensure_index = index_should_not_run  # type: ignore[method-assign]
    with pytest.raises(AppError) as blocked:
        adapter.write_published_chunks(
            project_id=chunk.project_id,
            document=SimpleNamespace(id=chunk.document_id, title="MaaS"),
            version=version,
            chunks=[chunk],
            vectors=[[0.1, 0.2, 0.3]],
            profile=profile,
        )
    assert blocked.value.code == "retrieval_reprocessing_required"
    assert index_attempts == 0


def test_final_hash_is_bound_to_profile_before_indexing() -> None:
    text = "文件：MaaS\n\n合法檢索文字"
    model_id = uuid4()
    profile = EmbeddingProfile(
        id=uuid4(),
        model_id=model_id,
        model_version="embedding-v1",
        vector_dimension=3,
        distance_method="cosine",
        chunk_strategy={},
        mapping_version=2,
    )
    final_hash = embedding_content_hash(
        retrieval_text=text,
        embedding_model=str(model_id),
        embedding_model_version="embedding-v1",
        embedding_dimension=3,
        normalizer_version="normalizer-test-v1",
        tokenizer_version="tokenizer-test-v1",
    )
    chunk = _chunk(retrieval_text=text, retrieval_hash=final_hash)
    chunk.embedding_model_id = model_id

    assert embeddings.resolve_index_retrieval_text(chunk, profile=profile) == text
    checksum_before = chunk_checksum([chunk])
    chunk.display_markdown = "## Display-only renderer change"
    assert embeddings.resolve_index_retrieval_text(chunk, profile=profile) == text
    assert chunk_checksum([chunk]) == checksum_before
    assert _vector_index_mapping(profile)["mappings"]["properties"]["display_markdown"] == {"type": "text", "index": False}


def test_v2_keyword_and_mappings_use_only_normalized_retrieval_body() -> None:
    profile = SimpleNamespace(mapping_version=2, vector_dimension=3)
    project_id = uuid4()
    query = _keyword_query_body(
        project_id,
        "vLLM 擴容",
        [str(uuid4())],
        5,
        "staging",
        mapping_version=profile.mapping_version,
    )
    fields = query["query"]["bool"]["must"][0]["multi_match"]["fields"]
    assert fields == ["retrieval_text"]

    for mapping_factory in (staging_vector_index_mapping, _vector_index_mapping):
        properties = mapping_factory(profile)["mappings"]["properties"]
        assert properties["retrieval_text"] == {"type": "text"}
        for source_field in ("content", "display_text", "display_markdown", "markdown_content"):
            assert properties[source_field] == {"type": "text", "index": False}


def test_v1_keyword_and_mapping_keep_explicit_read_only_compatibility() -> None:
    profile = SimpleNamespace(mapping_version=1, vector_dimension=3)
    query = _keyword_query_body(
        uuid4(),
        "legacy",
        [str(uuid4())],
        5,
        "published",
        mapping_version=profile.mapping_version,
    )
    fields = query["query"]["bool"]["must"][0]["multi_match"]["fields"]
    assert fields == [
        "retrieval_text^3",
        "document_title^2",
        "heading_path^2",
        "display_text",
        "title",
        "content",
        "markdown_content^0.25",
    ]
    for mapping_factory in (staging_vector_index_mapping, _vector_index_mapping):
        properties = mapping_factory(profile)["mappings"]["properties"]
        assert properties["content"] == {"type": "text"}
        assert properties["display_text"] == {"type": "text"}
        assert properties["markdown_content"] == {"type": "text"}
        assert properties["display_markdown"] == {"type": "text", "index": False}


def test_manual_split_rebuilds_all_representations_from_exact_canonical_fragment() -> None:
    canonical = "1. **vLLM** 監控 `waiting`。\n2. **Triton** 監控佇列。\n"
    first_end = canonical.index("\n") + 1
    parent = _chunk(retrieval_text="legacy", retrieval_hash="0" * 64)
    parent.markdown_content = canonical
    parent.display_markdown = canonical
    parent.heading_path = ["MaaS", "擴容"]
    parent.heading_level = 2
    parent.start_offset = 0
    parent.end_offset = len(canonical)
    parent.revision = 0
    parent.lineage_id = parent.id
    mapping = {
        "source_anchor": "list-1",
        "markdown_start_offset": 0,
        "markdown_end_offset": len(canonical),
        "anchor_start_offset": 0,
        "anchor_end_offset": len(canonical),
    }

    split = _split_chunk(
        parent,
        0,
        first_end,
        "before",
        uuid4(),
        mapping,
        document_title="企業級 MaaS 平台架構規劃書",
        canonical_markdown=canonical,
    )

    assert split.markdown_content == canonical[:first_end]
    assert split.display_markdown == canonical[:first_end]
    assert split.content == "1. vLLM 監控 waiting。"
    assert split.retrieval_text.startswith("文件：企業級 MaaS 平台架構規劃書\n章節：MaaS > 擴容\n\n1.")
    assert "**" not in split.retrieval_text and "`" not in split.retrieval_text
    assert split.chunk_strategy["parser_version"]
    assert split.chunk_strategy["chunker_version"]
    assert split.chunk_strategy["normalizer_version"]
    assert split.chunk_strategy["tokenizer_version"]
    assert split.embedding_content_hash != "0" * 64
