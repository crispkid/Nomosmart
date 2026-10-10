"""Exact, versioned tokenizer loaded only from verified local build assets."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path

from app.core.errors import AppError


@lru_cache(maxsize=8)
def local_encoding(name: str):
    import tiktoken

    root = Path(__file__).resolve().parents[1] / "tokenizers"
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest["tiktoken_version"] != importlib.metadata.version("tiktoken"):
            raise ValueError("tokenizer package version mismatch")
        entry = manifest["encodings"][name]
        path = root / entry["file"]
        if path.parent != root:
            raise ValueError("invalid tokenizer asset path")
        data = path.read_bytes()
        if sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("tokenizer asset checksum mismatch")
        ranks = {base64.b64decode(token, validate=True): int(rank)
                 for token, rank in (line.split() for line in data.splitlines() if line)}
        encoding = tiktoken.Encoding(name=name, pat_str=entry["pat_str"],
                                    mergeable_ranks=ranks, special_tokens=entry["special_tokens"])
        return encoding, f"tiktoken:{manifest['tiktoken_version']}:{name}:{entry['sha256']}"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AppError("chunk_model_capacity_unavailable", "Verified model tokenizer is unavailable", status_code=422) from exc


@dataclass(frozen=True)
class ModelTokenCounter:
    encoding_name: str
    contract_hash: str = ""

    @property
    def version(self) -> str:
        _, version = local_encoding(self.encoding_name)
        return f"{version}:{self.contract_hash}" if self.contract_hash else version

    def count(self, text: str) -> int:
        # Documents containing spellings of special tokens are ordinary text.
        encoding, _ = local_encoding(self.encoding_name)
        return len(encoding.encode_ordinary(text or ""))

    def truncate(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        encoding, _ = local_encoding(self.encoding_name)
        tokens = encoding.encode_ordinary(text or "")
        if len(tokens) <= max_tokens:
            return text
        # Used for bounded contextual prefixes only; do not introduce U+FFFD at
        # a multibyte boundary, or use token truncation on document body text.
        data = b"".join(encoding.decode_single_token_bytes(token) for token in tokens[:max_tokens])
        result = data.decode("utf-8", errors="ignore").rstrip()
        while result and self.count(result) > max_tokens:
            result = result[:-1]
        return result
