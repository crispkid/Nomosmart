from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.security.secrets import resolve_runtime_secret
from app.db.models import AIModel, Chunk, DocumentVersion, EmbeddingBuild, EmbeddingBuildVector, EmbeddingProfile, Project
from app.domain.model_usage import record_model_usage
from app.domain.retrieval_text import embedding_content_hash, provisional_retrieval_hash
from app.domain.tokenization import UnicodeTokenCounter


@dataclass(frozen=True)
class EmbeddingBatch:
    model: AIModel
    profile: EmbeddingProfile
    vectors: list[list[float]]
    usage: dict[str, Any]
    build: EmbeddingBuild
    adapter_source: str = "openai-compatible-embedding-adapter"


def embed_chunks(
    session: Session,
    *,
    project: Project,
    version: DocumentVersion,
    chunks: list[Chunk],
    settings: Settings | None = None,
) -> EmbeddingBatch:
    if not chunks:
        raise AppError("embedding_chunks_required", "No chunks are available for embedding", status_code=409)
    model = _active_embedding_model(session, project, version)
    existing_profile = session.get(EmbeddingProfile, version.embedding_profile_id) if version.embedding_profile_id else None
    texts = [resolve_embedding_retrieval_text(chunk, model=model, profile=existing_profile) for chunk in chunks]
    content_fingerprint = _content_fingerprint(model, chunks, texts)
    existing = _completed_build(session, version, content_fingerprint)
    if existing is not None:
        return _load_embedding_batch(session, model, version, chunks, existing, texts=texts)
    started = perf_counter()
    try:
        response = _post_openai_embeddings(model, settings or get_settings(), texts)
    except AppError as exc:
        record_model_usage(
            session,
            model=model,
            usage_purpose="embedding_build",
            source_channel="pipeline",
            status="failed",
            error_code=exc.code,
            latency_ms=max(0, int((perf_counter() - started) * 1000)),
            project_id=project.id,
            document_id=version.document_id,
            document_version_id=version.id,
            chunk_count=len(chunks),
        )
        raise
    vectors = _openai_embedding_vectors(response)
    if len(vectors) != len(chunks):
        raise AppError("embedding_result_count_mismatch", "Embedding adapter returned an unexpected vector count", status_code=502)
    profile = _profile_for_vectors(session, model, version, vectors, chunks=chunks)
    for chunk, vector, retrieval_text in zip(chunks, vectors, texts, strict=True):
        checksum = hashlib.sha256(json.dumps(vector, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        strategy = chunk.chunk_strategy if isinstance(chunk.chunk_strategy, dict) else {}
        normalizer_version = str(strategy["normalizer_version"])
        tokenizer_version = str(strategy["tokenizer_version"])
        chunk.embedding_content_hash = embedding_content_hash(
            retrieval_text=retrieval_text,
            embedding_model=str(model.id),
            embedding_model_version=model_name(model),
            embedding_dimension=profile.vector_dimension,
            normalizer_version=normalizer_version,
            tokenizer_version=tokenizer_version,
        )
        chunk.embedding_model_id = model.id
        chunk.embedding_vector_ref = f"embedding://profiles/{profile.id}/versions/{version.id}/chunks/{chunk.id}#{checksum}"
        chunk.token_count = estimated_tokens(retrieval_text)
    version.embedding_model_id = model.id
    version.embedding_profile_id = profile.id
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    build = _persist_embedding_build(session, model, profile, version, chunks, texts, vectors, content_fingerprint, usage)
    record_model_usage(
        session,
        model=model,
        usage_purpose="embedding_build",
        source_channel="pipeline",
        status="success",
        token_usage=usage,
        latency_ms=max(0, int((perf_counter() - started) * 1000)),
        project_id=project.id,
        document_id=version.document_id,
        document_version_id=version.id,
        vector_count=len(vectors),
        chunk_count=len(chunks),
        metadata={"embedding_build_id": str(build.id)},
    )
    return EmbeddingBatch(model=model, profile=profile, vectors=vectors, usage=usage, build=build)


def load_canonical_embeddings(session: Session, *, project: Project, version: DocumentVersion, chunks: list[Chunk]) -> EmbeddingBatch:
    if not chunks:
        raise AppError("embedding_chunks_required", "No chunks are available for embedding", status_code=409)
    model = _active_embedding_model(session, project, version)
    profile = session.get(EmbeddingProfile, version.embedding_profile_id) if version.embedding_profile_id else None
    texts = [resolve_embedding_retrieval_text(chunk, model=model, profile=profile) for chunk in chunks]
    content_fingerprint = _content_fingerprint(model, chunks, texts)
    build = _completed_build(session, version, content_fingerprint)
    if build is None:
        raise AppError("canonical_embedding_build_required", "A completed canonical embedding build is required before indexing", status_code=409)
    return _load_embedding_batch(session, model, version, chunks, build, texts=texts)


def embed_query(
    session: Session,
    *,
    profile: EmbeddingProfile,
    question: str,
    settings: Settings | None = None,
    project_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    source_channel: str = "chat_test",
    correlation_id: str | None = None,
) -> tuple[AIModel, list[float]]:
    model = session.get(AIModel, profile.model_id)
    if model is None or not model.is_active or model.deleted_at is not None:
        raise AppError("embedding_provider_required", "An active Embedding Provider is required for hybrid retrieval", status_code=409)
    text = question.strip()
    if not text:
        raise AppError("query_text_required", "Question text is required for retrieval", status_code=422)
    started = perf_counter()
    try:
        response = _post_openai_embeddings(model, settings or get_settings(), [text])
    except AppError as exc:
        record_model_usage(
            session,
            model=model,
            usage_purpose="query_embedding",
            source_channel=source_channel,
            status="failed",
            error_code=exc.code,
            latency_ms=max(0, int((perf_counter() - started) * 1000)),
            project_id=project_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )
        if source_channel in {"chat_test", "public_api", "validation"}:
            session.commit()
        raise
    vectors = _openai_embedding_vectors(response)
    if len(vectors) != 1:
        raise AppError("query_embedding_failed", "Embedding Provider returned an invalid query vector", status_code=502)
    vector = vectors[0]
    if len(vector) != profile.vector_dimension:
        raise AppError("embedding_profile_mismatch", "Query embedding dimension does not match the retrieval profile", status_code=409)
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    record_model_usage(
        session,
        model=model,
        usage_purpose="query_embedding",
        source_channel=source_channel,
        status="success",
        token_usage=usage,
        latency_ms=max(0, int((perf_counter() - started) * 1000)),
        project_id=project_id,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
        vector_count=1,
    )
    return model, vector


def model_name(model: AIModel) -> str:
    value = _string((model.config or {}).get("model_name") or model.name)
    if not value:
        raise AppError("embedding_model_name_required", "Embedding Model model_name is required", status_code=422)
    return value


def estimated_tokens(text: str) -> int:
    return max(1, UnicodeTokenCounter().count(text))


def _content_fingerprint(model: AIModel, chunks: list[Chunk], texts: list[str]) -> str:
    config = model.config if isinstance(model.config, dict) else {}
    structure_aware = any((chunk.chunk_strategy or {}).get("structure_aware") or (chunk.chunk_strategy or {}).get("source") == "structure_aware" for chunk in chunks)
    configured_mapping_version = _int(config.get("mapping_version"), default=2 if structure_aware else 1)
    mapping_version = max(2, configured_mapping_version) if structure_aware else configured_mapping_version
    payload = {
        "model_id": str(model.id),
        "config_version": model.config_version,
        "model_name": model_name(model),
        "requested_dimension": _int(config.get("dimensions") or config.get("embedding_dimension"), default=0),
        "mapping_version": mapping_version,
        "chunks": [_fingerprint_chunk(chunk, text) for chunk, text in zip(chunks, texts, strict=True)],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _fingerprint_chunk(chunk: Chunk, text: str) -> dict[str, object]:
    strategy = chunk.chunk_strategy if isinstance(chunk.chunk_strategy, dict) else {}
    normalizer_version = str(strategy["normalizer_version"])
    tokenizer_version = str(strategy["tokenizer_version"])
    return {
        "id": str(chunk.id),
        "index": chunk.chunk_index,
        "stable_chunk_key": chunk.stable_chunk_key,
        "preprocessing_hash": provisional_retrieval_hash(
            retrieval_text=text,
            normalizer_version=normalizer_version,
            tokenizer_version=tokenizer_version,
        ),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "normalizer_version": normalizer_version,
        "tokenizer_version": tokenizer_version,
    }


def _completed_build(session: Session, version: DocumentVersion, content_fingerprint: str) -> EmbeddingBuild | None:
    return session.scalar(select(EmbeddingBuild).where(
        EmbeddingBuild.document_version_id == version.id,
        EmbeddingBuild.content_fingerprint == content_fingerprint,
        EmbeddingBuild.status.in_(("completed", "staged", "published")),
    ).order_by(desc(EmbeddingBuild.build_revision)).limit(1))


def _persist_embedding_build(
    session: Session,
    model: AIModel,
    profile: EmbeddingProfile,
    version: DocumentVersion,
    chunks: list[Chunk],
    texts: list[str],
    vectors: list[list[float]],
    content_fingerprint: str,
    usage: dict[str, Any],
) -> EmbeddingBuild:
    latest_revision = session.scalar(select(EmbeddingBuild.build_revision).where(EmbeddingBuild.document_version_id == version.id, EmbeddingBuild.embedding_profile_id == profile.id).order_by(desc(EmbeddingBuild.build_revision)).limit(1)) or 0
    now = datetime.now(UTC)
    token_count = sum(chunk.token_count or estimated_tokens(text) for chunk, text in zip(chunks, texts, strict=True))
    vector_checksums = [hashlib.sha256(json.dumps(vector, separators=(",", ":")).encode("utf-8")).hexdigest() for vector in vectors]
    build = EmbeddingBuild(
        id=uuid4(),
        project_id=version.project_id,
        document_id=version.document_id,
        document_version_id=version.id,
        embedding_profile_id=profile.id,
        build_revision=latest_revision + 1,
        status="completed",
        chunk_count=len(chunks),
        checksum=hashlib.sha256("".join(vector_checksums).encode("ascii")).hexdigest(),
        content_fingerprint=content_fingerprint,
        model_id=model.id,
        vector_dimension=profile.vector_dimension,
        token_count=token_count,
        usage=usage,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(build)
    session.flush()
    for chunk, text, vector, checksum in zip(chunks, texts, vectors, vector_checksums, strict=True):
        session.add(EmbeddingBuildVector(
            id=uuid4(),
            embedding_build_id=build.id,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            vector=vector,
            vector_checksum=checksum,
            token_count=chunk.token_count or estimated_tokens(text),
            created_at=now,
        ))
    return build


def _load_embedding_batch(session: Session, model: AIModel, version: DocumentVersion, chunks: list[Chunk], build: EmbeddingBuild, *, texts: list[str] | None = None) -> EmbeddingBatch:
    profile = session.get(EmbeddingProfile, build.embedding_profile_id)
    if profile is None or build.model_id != model.id or build.vector_dimension != profile.vector_dimension:
        raise AppError("canonical_embedding_build_invalid", "Canonical embedding build metadata is invalid", status_code=409)
    resolved_texts = texts or [resolve_embedding_retrieval_text(chunk, model=model, profile=profile) for chunk in chunks]
    expected_fingerprint = _content_fingerprint(model, chunks, resolved_texts)
    if build.content_fingerprint != expected_fingerprint:
        raise AppError("canonical_embedding_build_invalid", "Canonical embedding build fingerprint is invalid", status_code=409)
    rows = list(session.scalars(select(EmbeddingBuildVector).where(EmbeddingBuildVector.embedding_build_id == build.id).order_by(EmbeddingBuildVector.chunk_index)))
    ordered_chunks = sorted(chunks, key=lambda chunk: chunk.chunk_index)
    if len(rows) != len(ordered_chunks) or build.chunk_count != len(ordered_chunks):
        raise AppError("canonical_embedding_build_invalid", "Canonical embedding vector count is invalid", status_code=409)
    vectors: list[list[float]] = []
    for row, chunk in zip(rows, ordered_chunks, strict=True):
        if row.chunk_id != chunk.id or row.chunk_index != chunk.chunk_index or len(row.vector) != profile.vector_dimension:
            raise AppError("canonical_embedding_build_invalid", "Canonical embedding vector mapping is invalid", status_code=409)
        checksum = hashlib.sha256(json.dumps(row.vector, separators=(",", ":")).encode("utf-8")).hexdigest()
        if checksum != row.vector_checksum:
            raise AppError("canonical_embedding_build_invalid", "Canonical embedding vector checksum is invalid", status_code=409)
        vectors.append([float(value) for value in row.vector])
    version.embedding_model_id = model.id
    version.embedding_profile_id = profile.id
    return EmbeddingBatch(model=model, profile=profile, vectors=vectors, usage=build.usage or {}, build=build, adapter_source="canonical-embedding-build")


def _active_embedding_model(session: Session, project: Project, version: DocumentVersion) -> AIModel:
    model_id = version.embedding_model_id or project.embedding_model_id
    model = session.get(AIModel, model_id) if model_id is not None else None
    if model is None or not model.is_active or model.deleted_at is not None:
        raise AppError("embedding_model_required", "An active Embedding Model is required", status_code=409)
    provider = model.provider.strip().lower()
    if provider not in {"openai", "vllm", "custom"}:
        raise AppError("embedding_provider_unsupported", "Embedding Model provider is not supported", status_code=422, details={"provider": model.provider})
    return model


def _profile_for_vectors(session: Session, model: AIModel, version: DocumentVersion, vectors: list[list[float]], *, chunks: list[Chunk] | None = None) -> EmbeddingProfile:
    dimension = len(vectors[0]) if vectors else 0
    if dimension <= 0 or any(len(vector) != dimension for vector in vectors):
        raise AppError("embedding_dimension_invalid", "Embedding adapter returned invalid vector dimensions", status_code=502)
    config = model.config if isinstance(model.config, dict) else {}
    model_version = model_name(model)
    distance_method = _string(config.get("distance_method") or "cosine") or "cosine"
    structure_aware = bool((version.chunk_strategy or {}).get("structure_aware")) or any(
        bool((chunk.chunk_strategy or {}).get("structure_aware")) for chunk in (chunks or [])
    )
    configured_mapping_version = _int(config.get("mapping_version"), default=2 if structure_aware else 1)
    mapping_version = max(2, configured_mapping_version) if structure_aware else configured_mapping_version
    profile = session.scalar(
        select(EmbeddingProfile).where(
            EmbeddingProfile.model_id == model.id,
            EmbeddingProfile.model_version == model_version,
            EmbeddingProfile.vector_dimension == dimension,
            EmbeddingProfile.distance_method == distance_method,
            EmbeddingProfile.mapping_version == mapping_version,
        )
    )
    if profile is None:
        profile = EmbeddingProfile(
            id=uuid4(),
            model_id=model.id,
            model_version=model_version,
            vector_dimension=dimension,
            distance_method=distance_method,
            chunk_strategy=version.chunk_strategy or {},
            mapping_version=mapping_version,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(profile)
        session.flush()
    return profile


def _post_openai_embeddings(model: AIModel, settings: Settings, texts: list[str]) -> dict[str, Any]:
    config = model.config if isinstance(model.config, dict) else {}
    body: dict[str, Any] = {"model": model_name(model), "input": texts}
    dimensions = _int(config.get("dimensions") or config.get("embedding_dimension"), default=0)
    if dimensions > 0:
        body["dimensions"] = dimensions
    request = urllib.request.Request(
        openai_embeddings_url(_string(config.get("base_url") or model.endpoint or "https://api.openai.com/v1")),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **_embedding_auth_headers(model, settings)},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout(config, default=60), context=_ssl_context(config)) as response:  # noqa: S310 - operator-configured model endpoint
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AppError("embedding_adapter_provider_rejected", "Embedding adapter provider rejected the request", status_code=502, details={"status_code": exc.code}) from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise AppError("embedding_adapter_unavailable", "Embedding adapter endpoint is unavailable", status_code=503) from exc


def openai_embeddings_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    lowered = normalized.lower()
    if lowered.endswith("/embeddings"):
        return normalized
    if lowered.endswith("/responses"):
        normalized = normalized[: -len("/responses")]
    if lowered.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    return f"{normalized}/embeddings"


def _embedding_auth_headers(model: AIModel, settings: Settings) -> dict[str, str]:
    api_key = _resolve_model_api_key(model, settings)
    if not api_key:
        raise AppError("embedding_adapter_credential_required", "Embedding adapter API key is required", status_code=409)
    return {"Authorization": f"Bearer {api_key}"}


def _resolve_model_api_key(model: AIModel, settings: Settings) -> str | None:
    if model.api_key_secret_ref:
        return resolve_runtime_secret(settings, model.api_key_secret_ref)
    if model.api_key_encrypted:
        if settings.app_env == "production":
            raise AppError("legacy_model_credential_forbidden", "Legacy model credentials are not permitted in production", status_code=503)
        cipher = EnvelopeCipher(settings.encryption_key_bytes)
        contexts = [f"ai-model:{model.id}", f"ai-model:{model.name}"]
        last_error: AppError | None = None
        for context in contexts:
            try:
                return cipher.decrypt(model.api_key_encrypted, context=context)
            except AppError as exc:
                last_error = exc
        if last_error:
            raise last_error
    return None


def _openai_embedding_vectors(payload: dict[str, Any]) -> list[list[float]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise AppError("embedding_response_invalid", "Embedding adapter response did not contain data", status_code=502)
    ordered = sorted(data, key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0)
    vectors: list[list[float]] = []
    for item in ordered:
        if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
            raise AppError("embedding_response_invalid", "Embedding adapter response did not contain vectors", status_code=502)
        try:
            vectors.append([float(value) for value in item["embedding"]])
        except (TypeError, ValueError) as exc:
            raise AppError("embedding_response_invalid", "Embedding adapter vector contains invalid values", status_code=502) from exc
    return vectors


def resolve_embedding_retrieval_text(
    chunk: Chunk,
    *,
    model: AIModel | None = None,
    profile: EmbeddingProfile | None = None,
) -> str:
    """Resolve the sole valid input for a new or rebuilt embedding.

    This deliberately rejects legacy display/raw fallbacks.  Legacy rows remain
    readable through :func:`legacy_read_only_chunk_text`, but must be reprocessed
    before any Provider, vector-build, or index-write path can use them.
    """

    text = (chunk.retrieval_text or "").strip()
    strategy = chunk.chunk_strategy if isinstance(chunk.chunk_strategy, dict) else {}
    required_versions = ("parser_version", "chunker_version", "normalizer_version", "tokenizer_version")
    missing = [name for name in required_versions if not str(strategy.get(name) or "").strip()]
    content_hash = str(chunk.embedding_content_hash or "").strip().lower()
    if not text or missing or len(content_hash) != 64 or any(character not in "0123456789abcdef" for character in content_hash):
        _raise_reprocessing_required(chunk, missing=missing, reason="retrieval_evidence_missing")

    normalizer_version = str(strategy["normalizer_version"])
    tokenizer_version = str(strategy["tokenizer_version"])
    allowed_hashes = {
        provisional_retrieval_hash(
            retrieval_text=text,
            normalizer_version=normalizer_version,
            tokenizer_version=tokenizer_version,
        )
    }
    if model is not None and profile is not None:
        allowed_hashes.add(
            embedding_content_hash(
                retrieval_text=text,
                embedding_model=str(model.id),
                embedding_model_version=model_name(model),
                embedding_dimension=profile.vector_dimension,
                normalizer_version=normalizer_version,
                tokenizer_version=tokenizer_version,
            )
        )
    if content_hash not in allowed_hashes:
        _raise_reprocessing_required(chunk, missing=[], reason="retrieval_hash_mismatch")
    return text


def resolve_index_retrieval_text(chunk: Chunk, *, profile: EmbeddingProfile) -> str:
    """Validate the final model/dimension-bound retrieval evidence for indexing."""

    if chunk.embedding_model_id != profile.model_id:
        _raise_reprocessing_required(chunk, missing=[], reason="embedding_model_mismatch")
    text = (chunk.retrieval_text or "").strip()
    strategy = chunk.chunk_strategy if isinstance(chunk.chunk_strategy, dict) else {}
    missing = [name for name in ("parser_version", "chunker_version", "normalizer_version", "tokenizer_version") if not str(strategy.get(name) or "").strip()]
    if not text or missing:
        _raise_reprocessing_required(chunk, missing=missing, reason="retrieval_evidence_missing")
    expected = embedding_content_hash(
        retrieval_text=text,
        embedding_model=str(profile.model_id),
        embedding_model_version=profile.model_version,
        embedding_dimension=profile.vector_dimension,
        normalizer_version=str(strategy["normalizer_version"]),
        tokenizer_version=str(strategy["tokenizer_version"]),
    )
    if chunk.embedding_content_hash != expected:
        _raise_reprocessing_required(chunk, missing=[], reason="retrieval_hash_mismatch")
    return text


def legacy_read_only_chunk_text(chunk: Chunk) -> str:
    """Compatibility projection for already-active legacy reads only.

    Embedding and index writers must never call this resolver.
    """

    return (chunk.retrieval_text or chunk.content or chunk.markdown_content or "").strip()


def _raise_reprocessing_required(chunk: Chunk, *, missing: list[str], reason: str) -> None:
    raise AppError(
        "retrieval_reprocessing_required",
        "Chunk retrieval representations must be reprocessed before embedding or indexing",
        status_code=409,
        details={"chunk_id": str(chunk.id), "reason": reason, "missing_evidence": missing},
    )


def _ssl_context(config: dict[str, object]) -> ssl.SSLContext | None:
    if not _verify_tls(config):
        return ssl._create_unverified_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        return None


def _timeout(config: dict[str, object], *, default: int = 60) -> int:
    return max(1, min(_int(config.get("timeout_seconds") or config.get("timeout"), default=default), 300))


def _verify_tls(config: dict[str, object]) -> bool:
    value = config.get("verify_tls", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return True


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(value: object, *, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
