"""COPYTOK native preprocessing inputs; real local tokenizers, no Provider adapters."""
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AIModel
from app.domain.embedding_capacity import EmbeddingInputContract, resolve_input_contract
from app.domain.model_tokenization import ModelTokenCounter, local_encoding
from app.domain.reference_copy import _source_counter, _target_retrieval
from app.domain.retrieval_text import RetrievalTextNormalizer, provisional_retrieval_hash
from app.domain.structure_chunking import ChunkDraft, ChunkingConfig
from app.domain.tokenization import UnicodeTokenCounter


MODEL_ID = UUID("479fd83c-e4ea-4693-a1cf-4c23fae74062")
CATALOG = Path(__file__).resolve().parents[2] / "deploy/docker/embedding-capabilities.example.json"


def _contract(limit=None):
    config = {"model_name": "text-embedding-3-small"}
    if limit is not None:
        config["input_token_limit"] = limit
    model = AIModel(id=MODEL_ID, name="Copy tokenizer native input", provider="OpenAI",
                    model_type="Embedding", config_version=1, config=config, is_active=True)
    return resolve_input_contract(model, Settings(_env_file=None, embedding_capabilities_file=str(CATALOG)))


def _strategies():
    snapshot = _contract().snapshot()
    version = {"chunker_version": "structure-chunker-v3", "normalizer_version": "retrieval-normalizer-v2",
               "tokenizer_version": snapshot["tokenizer_version"], "embedding_input_contract": snapshot}
    return version, [deepcopy(version)]


def _draft():
    body = "中文與 emoji 🧩 保持完整。 Every complete sentence stays intact."
    return ChunkDraft(id=MODEL_ID, stable_chunk_key="", sequence=1, display_text=body,
                      display_markdown=body, raw_markdown=body, heading_path=("來源章節",),
                      heading_level=1, content_type="paragraph", start_offset=0,
                      end_offset=len(body), node_ids=(), token_count=0)


@pytest.mark.parametrize("mode", ["legacy", "model"])
def test_source_counter_preserves_explicit_preprocessing_and_target_context(mode):
    if mode == "legacy":
        counter = UnicodeTokenCounter()
        version = {"chunker_version": "structure-chunker-v2", "tokenizer_version": counter.version}
        chunks = [deepcopy(version)]
    else:
        version, chunks = _strategies()
        counter = _contract().counter
    source = _source_counter(version_strategy=version, chunk_strategies=chunks, model_id=MODEL_ID)
    assert type(source) is type(counter)
    assert source.version == counter.version
    config = ChunkingConfig(max_context_prefix_tokens=9)
    draft = _draft()
    original = RetrievalTextNormalizer(config=config, token_counter=source).normalize(
        draft, document_title="來源標題🧩與背景" * 10)
    target_contract = _contract(4096)
    target, count = _target_retrieval(draft, config=config, contract=target_contract,
                                     document_title="不同目標標題🧩與背景" * 10)
    assert original != target
    assert original.endswith(draft.display_text) and target.endswith(draft.display_text)
    assert "\ufffd" not in original + target
    encoding, _ = local_encoding("cl100k_base")
    assert count == len(encoding.encode_ordinary(target))
    assert target_contract.counter.count(target.split("\n\n", 1)[0]) <= config.max_context_prefix_tokens
    assert source.version != target_contract.counter.version
    assert provisional_retrieval_hash(retrieval_text=target, normalizer_version="retrieval-normalizer-v2",
        tokenizer_version=source.version) != provisional_retrieval_hash(retrieval_text=target,
        normalizer_version="retrieval-normalizer-v2", tokenizer_version=target_contract.counter.version)


@pytest.mark.parametrize("problem", ["missing_snapshot", "bad_hash", "unknown_encoding", "chunk_mismatch"])
def test_source_contract_rejects_unverifiable_evidence_without_unicode_fallback(problem):
    version, chunks = _strategies()
    if problem == "missing_snapshot":
        version.pop("embedding_input_contract")
    elif problem == "bad_hash":
        version["embedding_input_contract"]["contract_sha256"] = "0" * 64
    elif problem == "unknown_encoding":
        snapshot = version["embedding_input_contract"]
        snapshot["tokenizer_encoding"] = "not-a-local-copy-tokenizer"
        payload = {k: v for k, v in snapshot.items() if k not in {"contract_sha256", "tokenizer_version"}}
        snapshot["contract_sha256"] = EmbeddingInputContract(payload).fingerprint
        chunks = [deepcopy(version)]
    else:
        chunks[0]["embedding_input_contract"]["input_token_limit"] -= 1
    with pytest.raises(AppError) as caught:
        _source_counter(version_strategy=version, chunk_strategies=chunks, model_id=MODEL_ID)
    assert caught.value.code == "source_version_no_extractable_text"
    assert caught.value.status_code == 409


@pytest.mark.parametrize("excess", [0, 1])
def test_target_capacity_counts_complete_prefix_and_body(excess):
    draft = _draft()
    config = ChunkingConfig(max_context_prefix_tokens=16)
    title = "目標背景🧩" * 8
    expected = RetrievalTextNormalizer(config=config, token_counter=ModelTokenCounter("cl100k_base")).normalize(
        draft, document_title=title)
    tokens = ModelTokenCounter("cl100k_base").count(expected)
    assert tokens > ModelTokenCounter("cl100k_base").count(draft.display_text)
    contract = _contract(tokens - excess)
    if excess:
        with pytest.raises(AppError) as caught:
            _target_retrieval(draft, config=config, contract=contract, document_title=title)
        assert caught.value.code == "chunk_atomic_unit_too_large"
        assert caught.value.details["chunking_issue"]["input_tokens"] == tokens
    else:
        retrieval, actual = _target_retrieval(draft, config=config, contract=contract, document_title=title)
        assert retrieval == expected and actual == contract.limit
