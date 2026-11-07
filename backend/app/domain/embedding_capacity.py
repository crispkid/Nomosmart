"""Operator-configured model capabilities; never infer a model's hard limit."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.core.errors import AppError
from app.domain.model_tokenization import ModelTokenCounter


CHUNKING_ERROR_CODES = frozenset({"chunk_atomic_unit_too_large", "chunk_model_capacity_unavailable", "chunk_source_unresolved"})


@dataclass(frozen=True)
class EmbeddingInputContract:
    payload: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        return sha256(json.dumps(self.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

    @property
    def counter(self) -> ModelTokenCounter:
        return ModelTokenCounter(self.payload["tokenizer_encoding"], self.fingerprint)

    @property
    def limit(self) -> int:
        return self.payload["input_token_limit"]

    def snapshot(self) -> dict[str, Any]:
        return {**self.payload, "contract_sha256": self.fingerprint, "tokenizer_version": self.counter.version}


def resolve_input_contract(model, settings, *, saved: dict[str, Any] | None = None) -> EmbeddingInputContract:
    config = model.config if isinstance(model.config, dict) else {}
    name = str(config.get("model_name") or model.name).strip()
    provider = str(model.provider).strip().lower()
    path = settings.embedding_capabilities_file
    try:
        if not path:
            raise ValueError("capability catalog is not configured")
        raw = Path(path).read_bytes()
        catalog = json.loads(raw)
        if catalog.get("version") != 1 or not isinstance(catalog.get("models"), list):
            raise ValueError("invalid capability catalog")
        entries = [entry for entry in catalog["models"] if entry.get("provider", "").lower() == provider and entry.get("model_name") == name]
        if len(entries) > 1:
            raise ValueError("ambiguous model capability")
        known = entries[0] if entries else None
        declared = config.get("input_token_limit")
        encoding = config.get("tokenizer_encoding") or (known or {}).get("tokenizer_encoding")
        official = (known or {}).get("input_token_limit")
        if declared is not None and (type(declared) is not int or declared < 1):
            raise ValueError("input limit must be a positive integer")
        if known and (type(official) is not int or official < 1):
            raise ValueError("invalid model capacity")
        if known and declared is not None and declared > official:
            raise ValueError("configured limit exceeds verified model capacity")
        if known and encoding != known.get("tokenizer_encoding"):
            raise ValueError("tokenizer does not match verified model")
        limit = declared or official
        if type(limit) is not int or not encoding or (not known and declared is None):
            raise ValueError("model requires explicit capacity and tokenizer")
        counter = ModelTokenCounter(str(encoding))
        counter.count("")  # Verify package/asset without network or Provider.
        payload = {"version": 1, "model_id": str(model.id), "model_name": name,
                   "provider": provider, "config_version": model.config_version,
                   "input_token_limit": limit, "model_input_token_limit": official,
                   "tokenizer_encoding": str(encoding), "tokenizer_asset_version": counter.version,
                   "capacity_source": "catalog" if known else "model_config",
                   "catalog_sha256": sha256(raw).hexdigest()}
        contract = EmbeddingInputContract(payload)
        if saved is not None and saved != contract.snapshot():
            raise ValueError("saved model capability changed; new revision required")
        return contract
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise AppError("chunk_model_capacity_unavailable", "Verified model capacity is unavailable or changed", status_code=422) from exc


def chunking_error(code: str, *, contract: EmbeddingInputContract | None = None, unit=None,
                   input_tokens: int | None = None, canonical_sha256: str | None = None) -> AppError:
    metadata = unit.metadata if unit is not None else {}
    issue = {"code": code, "unit_type": unit.content_type if unit is not None else "document",
             "node_id": unit.node_ids[-1] if unit is not None and unit.node_ids else None,
             "table_id": metadata.get("table_id"), "row_start": metadata.get("row_start"), "row_end": metadata.get("row_end"),
             "start_offset": unit.start if unit is not None else 0, "end_offset": unit.end if unit is not None else 0,
             "offset_unit": "unicode_code_point", "canonical_sha256": canonical_sha256,
             "input_tokens": input_tokens, "input_token_limit": contract.limit if contract else None,
             "tokenizer_version": contract.counter.version if contract else None,
             "capacity_source": contract.payload["capacity_source"] if contract else "unavailable",
             "can_edit_content": False,
             "action_required": "configure_model" if code == "chunk_model_capacity_unavailable" else "edit_content" if code == "chunk_atomic_unit_too_large" else "check_source"}
    return AppError(code, "Document content requires adjustment" if code != "chunk_model_capacity_unavailable" else "Verified model capacity is unavailable or changed",
                    status_code=422, details={"chunking_issue": issue})


def validate_model_capacity_config(model, settings) -> None:
    if model.model_type == "Embedding" and {"input_token_limit", "tokenizer_encoding"}.intersection(model.config or {}):
        resolve_input_contract(model, settings)
