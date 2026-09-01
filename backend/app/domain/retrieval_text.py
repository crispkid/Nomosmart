from __future__ import annotations

from hashlib import sha256
import json
import re

from app.domain.structure_chunking import ChunkDraft, ChunkingConfig
from app.domain.tokenization import TokenCounter, UnicodeTokenCounter


NORMALIZER_VERSION = "retrieval-normalizer-v2"


class RetrievalTextNormalizer:
    def __init__(self, *, config: ChunkingConfig | None = None, token_counter: TokenCounter | None = None) -> None:
        self.config = config or ChunkingConfig()
        self.token_counter = token_counter or UnicodeTokenCounter()

    @property
    def version(self) -> str:
        return NORMALIZER_VERSION

    def normalize(self, chunk: ChunkDraft, *, document_title: str | None) -> str:
        prefix: list[str] = []
        if self.config.document_title_context_enabled and document_title and document_title.strip():
            prefix.append(f"文件：{document_title.strip()}")
        if self.config.heading_context_enabled and chunk.heading_path:
            prefix.append(f"章節：{' > '.join(chunk.heading_path[-self.config.max_heading_depth:])}")
        prefix_text = self.token_counter.truncate("\n".join(prefix), self.config.max_context_prefix_tokens)
        body = chunk.display_text.rstrip("\n") if chunk.content_type == "code_block" else _normalize_body(chunk.display_text)
        if prefix_text and body:
            return f"{prefix_text}\n\n{body}"
        return prefix_text or body


def embedding_content_hash(
    *,
    retrieval_text: str,
    embedding_model: str,
    embedding_model_version: str,
    embedding_dimension: int,
    normalizer_version: str,
    tokenizer_version: str,
) -> str:
    payload = {
        "retrieval_text": retrieval_text,
        "embedding_model": embedding_model,
        "embedding_model_version": embedding_model_version,
        "embedding_dimension": embedding_dimension,
        "normalizer_version": normalizer_version,
        "tokenizer_version": tokenizer_version,
    }
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def provisional_retrieval_hash(*, retrieval_text: str, normalizer_version: str, tokenizer_version: str) -> str:
    """Hash preprocessing before an embedding profile/model is resolved."""

    payload = {"retrieval_text": retrieval_text, "normalizer_version": normalizer_version, "tokenizer_version": tokenizer_version}
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _normalize_body(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in (value or "").splitlines()]
    normalized: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if normalized and not blank:
                normalized.append("")
            blank = True
        else:
            normalized.append(line.strip())
            blank = False
    return "\n".join(normalized).strip()
