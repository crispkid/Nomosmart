from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import resource
import shlex
import shutil
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.security.secrets import resolve_runtime_secret
from app.db.models import AIModel, Chunk, ChunkTag, Document, DocumentVersion, DocumentVersionTag, EmbeddingProfile, OutboxEvent, PipelineRun, PipelineRunStep, Project, Tag
from app.domain.ai_provider import AIProviderResult, generate_knowledge_tags
from app.domain.document_layout import build_document_layout, estimated_layout_block_height, paginate_layout_blocks, renderable_source_anchors
from app.domain.embeddings import embed_chunks, estimated_tokens, load_canonical_embeddings, model_name, resolve_index_retrieval_text
from app.domain.model_usage import record_model_usage
from app.domain.markdown_structure import MarkdownStructureParser, mark_repeated_boilerplate, repeated_page_boilerplate
from app.domain.office_parser import parse_office_document
from app.domain.retrieval_text import NORMALIZER_VERSION, RetrievalTextNormalizer, provisional_retrieval_hash
from app.domain.structure_chunking import CHUNKER_VERSION, ChunkingConfig, StructureAwareChunker
from app.domain.system_prompts import resolve_system_prompt
from app.domain.tokenization import UnicodeTokenCounter


logger = logging.getLogger(__name__)


MAX_STEP_RETRIES = 3
EXTERNAL_SIDE_EFFECT_STEPS = {"ocr_extract", "auto_tag", "build_embeddings", "build_staging_index"}
AUTO_EXTRACTION_STEPS = (
    "upload_received",
    "parse_document",
    "ocr_extract",
    "generate_markdown",
    "split_paragraphs",
    "chunk_knowledge",
    "auto_tag",
    "build_embeddings",
    "build_staging_index",
    "build_graph_preview",
    "prepare_submission",
)
STEP_WEIGHTS = {
    "upload_received": 3,
    "parse_document": 17,
    "ocr_extract": 10,
    "split_paragraphs": 8,
    "chunk_knowledge": 14,
    "generate_markdown": 10,
    "auto_tag": 8,
    "build_embeddings": 12,
    "build_staging_index": 10,
    "build_graph_preview": 5,
    "prepare_submission": 3,
}
REVIEW_AND_PUBLICATION_STEPS = (
    "manager_review",
    "owner_review",
    "publish",
    "production_index",
    "graph_sync",
)


@dataclass(frozen=True)
class PipelineArtifact:
    ref: str
    payload: dict[str, object]


@dataclass(frozen=True)
class StagingIndexResult:
    index_name: str
    document_ids: list[str]
    adapter_source: str
    status: str = "written"
    error: str | None = None


@dataclass(frozen=True)
class OCRResult:
    text: str
    adapter_source: str
    skipped: bool = False
    reason: str | None = None
    metadata: dict[str, object] | None = None


class StagingIndexAdapter(Protocol):
    def write_chunks(self, *, project: Project, document: Document, version: DocumentVersion, chunks: list[Chunk], vectors: list[list[float]], profile: EmbeddingProfile) -> StagingIndexResult:
        raise NotImplementedError


class OCRAdapter(Protocol):
    def extract_text(self, *, model: AIModel | None, version: DocumentVersion, parsed_text: str, force_ocr: bool, reliable_text_layer: bool) -> OCRResult:
        raise NotImplementedError


class LiveOnlyOCRAdapter:
    def extract_text(self, *, model: AIModel | None, version: DocumentVersion, parsed_text: str, force_ocr: bool, reliable_text_layer: bool) -> OCRResult:
        snapshot = _ocr_snapshot(model, version, force_ocr)
        if reliable_text_layer and not force_ocr:
            return OCRResult(text=parsed_text, adapter_source="reliable-text-layer", skipped=True, reason="reliable_text_layer", metadata=snapshot)
        raise AppError("ocr_adapter_not_configured", "OCR adapter endpoint is not configured", status_code=422)


class GenericHTTPOCRAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract_text(self, *, model: AIModel | None, version: DocumentVersion, parsed_text: str, force_ocr: bool, reliable_text_layer: bool) -> OCRResult:
        if model is None or not model.endpoint:
            raise AppError("ocr_adapter_not_configured", "OCR adapter endpoint is not configured", status_code=422)
        snapshot = _ocr_snapshot(model, version, force_ocr)
        timeout = int(snapshot["timeout_seconds"])
        retries = int(snapshot["retry_count"])
        media_inputs = _docx_ocr_inputs(self.settings, version) if (version.canonical_extension or "").lower() == ".docx" else []
        body = json.dumps(
            {
                "source_uri": None if media_inputs else version.original_snapshot_uri,
                "file_name": version.original_file_name,
                "media_inputs": [
                    {
                        "file_name": item[0],
                        "content_type": item[1],
                        "file_data": f"data:{item[1]};base64,{b64encode(item[2]).decode('ascii')}",
                    }
                    for item in media_inputs
                ],
                "parsed_text": parsed_text,
                "force_ocr": force_ocr,
                "reliable_text_layer": reliable_text_layer,
                "languages": snapshot["languages"],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(model.endpoint, data=body, method="POST", headers={"content-type": "application/json"})
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-configured OCR endpoint
                    payload = json.loads(response.read().decode("utf-8"))
                text = str(payload.get("text") or "").strip()
                if not text:
                    raise AppError("ocr_adapter_empty_result", "OCR adapter returned no text", status_code=502)
                usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
                return OCRResult(text=text, adapter_source="generic-http-ocr-adapter", skipped=False, metadata={**snapshot, "attempt": attempt + 1, "usage": usage})
            except AppError:
                raise
            except (TimeoutError, urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                if attempt >= retries:
                    raise AppError("ocr_adapter_unavailable", "OCR adapter endpoint is unavailable", status_code=503) from exc
        raise AppError("ocr_adapter_unavailable", "OCR adapter endpoint is unavailable", status_code=503)


class OpenAIOCRAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract_text(self, *, model: AIModel | None, version: DocumentVersion, parsed_text: str, force_ocr: bool, reliable_text_layer: bool) -> OCRResult:
        if model is None:
            raise AppError("ocr_adapter_not_configured", "OCR adapter endpoint is not configured", status_code=422)
        if reliable_text_layer and not force_ocr and parsed_text.strip():
            return OCRResult(text=parsed_text, adapter_source="reliable-text-layer", skipped=True, reason="reliable_text_layer", metadata=_ocr_snapshot(model, version, force_ocr))
        snapshot = _ocr_snapshot(model, version, force_ocr)
        if (version.canonical_extension or "").lower() == ".docx":
            inputs = _docx_ocr_inputs(self.settings, version)
        else:
            source = _load_source_object(self.settings, version)
            inputs = [(version.original_file_name or f"document{version.canonical_extension or ''}", source.content_type or version.mime_type or _mime_type_for(version), source.body)]
        payload = _openai_ocr_payload(model, version, inputs, parsed_text)
        response = _post_openai_ocr(model, self.settings, payload, timeout_seconds=int(snapshot["timeout_seconds"]))
        markdown = _openai_ocr_markdown(response)
        if not _valid_markdown_ocr_text(markdown):
            raise AppError("ocr_adapter_invalid_markdown", "OCR adapter returned invalid Markdown text", status_code=502)
        return OCRResult(
            text=markdown,
            adapter_source="openai-ocr-adapter",
            skipped=False,
            metadata={
                **snapshot,
                "response_format": "markdown",
                "input_content_types": sorted({item[1] for item in inputs}),
                "input_files": len(inputs),
                "input_bytes": sum(len(item[2]) for item in inputs),
                "usage": response.get("usage") if isinstance(response.get("usage"), dict) else {},
            },
        )


class TesseractOCRAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract_text(self, *, model: AIModel | None, version: DocumentVersion, parsed_text: str, force_ocr: bool, reliable_text_layer: bool) -> OCRResult:
        snapshot = _ocr_snapshot(model, version, force_ocr)
        if reliable_text_layer and not force_ocr and parsed_text.strip():
            return OCRResult(
                text=parsed_text,
                adapter_source="reliable-text-layer",
                skipped=True,
                reason="reliable_text_layer",
                metadata=snapshot,
            )
        _require_tesseract_runtime(self.settings)
        inputs = _tesseract_inputs(self.settings, version)
        languages = _tesseract_languages(snapshot)
        deadline = perf_counter() + self.settings.tesseract_timeout_seconds
        texts: list[str] = []
        page_count = 0
        input_bytes = sum(len(item[2]) for item in inputs)
        with tempfile.TemporaryDirectory(prefix="nomosmart-tesseract-") as temp_root:
            root = Path(temp_root)
            root.chmod(0o700)
            pages: list[Path] = []
            for index, (file_name, content_type, body) in enumerate(inputs, start=1):
                extension = _tesseract_extension(file_name, content_type)
                input_path = root / f"input-{index:04d}{extension}"
                input_path.write_bytes(body)
                input_path.chmod(0o600)
                if extension == ".pdf":
                    prefix = root / f"page-{index:04d}"
                    _run_ocr_sandbox(
                        self.settings,
                        root,
                        [
                            *shlex.split(self.settings.tesseract_pdf_command),
                            "-png",
                            "-r",
                            "200",
                            str(input_path),
                            str(prefix),
                        ],
                        deadline=deadline,
                        error_code="ocr_pdf_render_failed",
                    )
                    rendered = sorted(root.glob(f"{prefix.name}-*.png"))
                    if not rendered:
                        raise AppError("ocr_pdf_render_failed", "PDF OCR rendering produced no pages", status_code=422)
                    pages.extend(rendered)
                else:
                    pages.append(input_path)
            if len(pages) > self.settings.tesseract_max_pages:
                raise AppError("ocr_page_limit_exceeded", "OCR input exceeds the page limit", status_code=422)
            for page in pages:
                completed = _run_ocr_sandbox(
                    self.settings,
                    root,
                    [
                        *shlex.split(self.settings.tesseract_command),
                        str(page),
                        "stdout",
                        "-l",
                        languages,
                        "--dpi",
                        "200",
                    ],
                    deadline=deadline,
                    error_code="ocr_tesseract_failed",
                )
                try:
                    text = completed.stdout.decode("utf-8").strip()
                except UnicodeDecodeError as exc:
                    raise AppError("ocr_tesseract_output_invalid", "Tesseract output is not UTF-8", status_code=502) from exc
                if text:
                    texts.append(text)
                page_count += 1
        markdown = "\n\n".join(texts).strip()
        if not markdown:
            raise AppError("ocr_adapter_empty_result", "Tesseract returned no text", status_code=422)
        return OCRResult(
            text=markdown,
            adapter_source="sandboxed-tesseract",
            skipped=False,
            metadata={
                **snapshot,
                "engine_version": _tesseract_version(self.settings),
                "languages": languages.split("+"),
                "input_files": len(inputs),
                "input_bytes": input_bytes,
                "pages_processed": page_count,
                "page_ranges": _joined_page_ranges(texts),
                "sandbox_network": "disabled",
            },
        )


class UnsupportedOCRAdapter:
    def extract_text(self, *, model: AIModel | None, version: DocumentVersion, parsed_text: str, force_ocr: bool, reliable_text_layer: bool) -> OCRResult:
        provider = model.provider if model is not None else "unknown"
        raise AppError("ocr_provider_unsupported", "OCR Model provider is not supported by the OCR adapter", status_code=422, details={"provider": provider})


class LiveOpenSearchStagingIndexAdapter:
    """Live-only staging adapter for configured Development OpenSearch."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def write_chunks(self, *, project: Project, document: Document, version: DocumentVersion, chunks: list[Chunk], vectors: list[list[float]], profile: EmbeddingProfile) -> StagingIndexResult:
        index = staging_index_name(self.settings.opensearch_index_prefix, project.id, version.id)
        document_ids = [f"{version.id}:{chunk.id}" for chunk in chunks]
        if not self.settings.opensearch_staging_live_write:
            raise AppError("opensearch_staging_not_configured", "OpenSearch staging live write is not configured", status_code=503)
        _validate_staging_inputs(chunks, vectors, profile)
        self.delete_version(project_id=project.id, version_id=version.id)
        self._write_live(index, project, document, version, chunks, vectors, profile)
        return StagingIndexResult(index_name=index, document_ids=document_ids, adapter_source="live-opensearch-staging-adapter")

    def delete_version(self, *, project_id: UUID, version_id: UUID) -> None:
        if not self.settings.opensearch_staging_live_write:
            raise AppError("opensearch_staging_not_configured", "OpenSearch staging live write is not configured", status_code=503)
        index = staging_index_name(self.settings.opensearch_index_prefix, project_id, version_id)
        base = self.settings.opensearch_url.rstrip("/")
        context = self.settings.opensearch_ssl_context
        self._request("DELETE", f"{base}/{index}", b"", context=context, content_type="application/json", allow_missing=True)

    def _write_live(self, index: str, project: Project, document: Document, version: DocumentVersion, chunks: list[Chunk], vectors: list[list[float]], profile: EmbeddingProfile) -> None:
        _validate_staging_inputs(chunks, vectors, profile)
        base = self.settings.opensearch_url.rstrip("/")
        context = self.settings.opensearch_ssl_context
        self._ensure_index(base, index, profile, context)
        lines: list[str] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            doc_id = f"{version.id}:{chunk.id}"
            lines.append(json.dumps({"index": {"_index": index, "_id": doc_id}}, ensure_ascii=False))
            lines.append(
                json.dumps(
                    _staging_chunk_document(project, document, version, chunk, vector, profile),
                    ensure_ascii=False,
                )
            )
        body = ("\n".join(lines) + "\n").encode("utf-8")
        self._request("POST", f"{base}/_bulk", body, context=context, content_type="application/x-ndjson")

    def _request(self, method: str, url: str, body: bytes, *, context: ssl.SSLContext | None, content_type: str, allow_missing: bool = False) -> None:
        request = urllib.request.Request(url, data=body, method=method, headers={"content-type": content_type})
        username = self.settings.opensearch_username.get_secret_value()
        password = self.settings.opensearch_password.get_secret_value()
        if username or password:
            token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            request.add_header("authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(request, timeout=5, context=context) as response:  # noqa: S310 - Development endpoint is operator configured
                if response.status >= 400:
                    raise AppError("opensearch_staging_write_failed", "OpenSearch staging write failed", status_code=502)
        except urllib.error.HTTPError as exc:
            if allow_missing and exc.code == 404:
                return
            raise AppError("opensearch_staging_write_failed", "OpenSearch staging write failed", status_code=502) from exc
        except OSError as exc:
            raise AppError("opensearch_staging_unavailable", "OpenSearch staging endpoint is unavailable", status_code=503) from exc

    def _ensure_index(self, base: str, index: str, profile: EmbeddingProfile, context: ssl.SSLContext | None) -> None:
        mapping = _vector_index_mapping(profile)
        try:
            self._request("PUT", f"{base}/{index}", json.dumps(mapping).encode("utf-8"), context=context, content_type="application/json")
        except AppError:
            self._request("PUT", f"{base}/{index}/_mapping", json.dumps(mapping["mappings"]).encode("utf-8"), context=context, content_type="application/json")
        self._verify_vector_mapping(base, index, profile, context)

    def _verify_vector_mapping(self, base: str, index: str, profile: EmbeddingProfile, context: ssl.SSLContext | None) -> None:
        request = self._request_with_auth("GET", f"{base}/{index}/_mapping", b"", context=context, content_type="application/json")
        try:
            with urllib.request.urlopen(request, timeout=5, context=context) as response:  # noqa: S310 - Development endpoint is operator configured
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AppError("vector_index_not_ready", "OpenSearch staging vector mapping could not be verified", status_code=503) from exc
        properties = next(iter(payload.values()), {}).get("mappings", {}).get("properties", {})
        vector_field = properties.get("embedding_vector") if isinstance(properties, dict) else None
        if not isinstance(vector_field, dict) or vector_field.get("dimension") != profile.vector_dimension:
            raise AppError("vector_index_not_ready", "OpenSearch staging vector mapping is not ready", status_code=409)

    def _request_with_auth(self, method: str, url: str, body: bytes, *, context: ssl.SSLContext | None, content_type: str) -> urllib.request.Request:
        request = urllib.request.Request(url, data=body, method=method, headers={"content-type": content_type})
        username = self.settings.opensearch_username.get_secret_value()
        password = self.settings.opensearch_password.get_secret_value()
        if username or password:
            token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            request.add_header("authorization", f"Basic {token}")
        return request


def _validate_staging_inputs(chunks: list[Chunk], vectors: list[list[float]], profile: EmbeddingProfile) -> None:
    if len(vectors) != len(chunks):
        raise AppError("embedding_result_count_mismatch", "Embedding vector count does not match chunk count", status_code=409)
    for chunk, vector in zip(chunks, vectors, strict=True):
        if len(vector) != profile.vector_dimension:
            raise AppError("embedding_profile_mismatch", "Chunk vector dimension does not match the staging index profile", status_code=409)
        resolve_index_retrieval_text(chunk, profile=profile)


def _staging_chunk_document(
    project: Project,
    document: Document,
    version: DocumentVersion,
    chunk: Chunk,
    vector: list[float],
    profile: EmbeddingProfile,
) -> dict[str, object]:
    return {
        "index_scope": "staging",
        "project_id": str(project.id),
        "document_id": str(document.id),
        "document_version_id": str(version.id),
        "chunk_id": str(chunk.id),
        "chunk_index": chunk.chunk_index,
        "title": chunk.title,
        "document_title": document.title,
        "content": chunk.content,
        "display_text": chunk.content,
        "retrieval_text": resolve_index_retrieval_text(chunk, profile=profile),
        "markdown_content": chunk.markdown_content,
        "display_markdown": chunk.display_markdown,
        "content_type": chunk.content_type,
        "heading_path": chunk.heading_path or ([chunk.section_path] if chunk.section_path else []),
        "heading_level": chunk.heading_level,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "sequence": chunk.sequence or chunk.chunk_index,
        "stable_chunk_key": chunk.stable_chunk_key,
        "embedding_content_hash": chunk.embedding_content_hash,
        "parser_version": (chunk.chunk_strategy or {}).get("parser_version"),
        "chunker_version": (chunk.chunk_strategy or {}).get("chunker_version"),
        "normalizer_version": (chunk.chunk_strategy or {}).get("normalizer_version"),
        "tokenizer_version": (chunk.chunk_strategy or {}).get("tokenizer_version"),
        "embedding_vector": vector,
        "embedding_profile_id": str(profile.id),
        "embedding_model_id": str(version.embedding_model_id) if version.embedding_model_id else None,
        "vector_dimension": profile.vector_dimension,
        "mapping_version": profile.mapping_version,
        "version_status": version.status,
        "adapter_source": "live-opensearch-staging-adapter",
    }


def staging_index_name(prefix: str, project_id: UUID, version_id: UUID) -> str:
    return f"{prefix}-staging-p{str(project_id)[:8]}-v{str(version_id)[:8]}".lower()


def _vector_index_mapping(profile: EmbeddingProfile) -> dict[str, object]:
    mapping_version = int(getattr(profile, "mapping_version", 1) or 1)
    source_text_mapping = (
        {"type": "text", "index": False}
        if mapping_version >= 2
        else {"type": "text"}
    )
    return {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                "index_scope": {"type": "keyword"},
                "project_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "document_version_id": {"type": "keyword"},
                "chunk_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
                "title": {"type": "text"},
                "document_title": {"type": "text"},
                "content": dict(source_text_mapping),
                "display_text": dict(source_text_mapping),
                "retrieval_text": {"type": "text"},
                "markdown_content": dict(source_text_mapping),
                # Renderer source is never a retrieval field, including while
                # reading legacy profiles.
                "display_markdown": {"type": "text", "index": False},
                "content_type": {"type": "keyword"},
                "heading_path": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "heading_level": {"type": "integer"},
                "page_start": {"type": "integer"},
                "page_end": {"type": "integer"},
                "sequence": {"type": "integer"},
                "stable_chunk_key": {"type": "keyword"},
                "embedding_content_hash": {"type": "keyword"},
                "parser_version": {"type": "keyword"},
                "chunker_version": {"type": "keyword"},
                "normalizer_version": {"type": "keyword"},
                "tokenizer_version": {"type": "keyword"},
                "embedding_vector": {
                    "type": "knn_vector",
                    "dimension": profile.vector_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                    },
                },
                "embedding_profile_id": {"type": "keyword"},
                "embedding_model_id": {"type": "keyword"},
                "vector_dimension": {"type": "integer"},
                "mapping_version": {"type": "integer"},
                "version_status": {"type": "keyword"},
                "adapter_source": {"type": "keyword"},
            }
        },
    }


def initialize_pipeline_steps(session: Session, pipeline: PipelineRun, *, ocr_model_id: UUID | None, ocr_name: str, force_ocr: bool) -> None:
    for step_name in (*AUTO_EXTRACTION_STEPS, *REVIEW_AND_PUBLICATION_STEPS):
        session.add(
            PipelineRunStep(
                run_id=pipeline.id,
                step_name=step_name,
                status="running" if step_name == "upload_received" else "pending",
                progress_percent=100 if step_name == "upload_received" else 0,
                progress_message=_step_message(step_name, ocr_name, force_ocr),
                model_id=ocr_model_id if step_name == "ocr_extract" else None,
            )
        )


def execute_auto_extraction(
    *,
    session: Session,
    settings: Settings,
    project: Project,
    document: Document,
    version: DocumentVersion,
    pipeline: PipelineRun,
    staging_adapter: StagingIndexAdapter | None = None,
    ocr_adapter: OCRAdapter | None = None,
    start_step: str | None = None,
    durable: bool = False,
) -> PipelineRun:
    adapter = staging_adapter or LiveOpenSearchStagingIndexAdapter(settings)
    ocr = ocr_adapter or _default_ocr_adapter(session, version, settings=settings)
    steps = _steps_for_run(session, pipeline.id)
    if start_step is not None:
        _reset_from_step(session, version.id, steps, start_step)
    artifacts: dict[str, PipelineArtifact] = {
        name: PipelineArtifact(ref=step.output_artifact_ref or _artifact_ref(version, name), payload=step.artifact_payload)
        for name, step in steps.items()
        if step.status == "completed" and isinstance(step.artifact_payload, dict)
    }
    completed_weight = sum(STEP_WEIGHTS.get(step.step_name, 0) for step in steps.values() if step.status == "completed" and step.step_name in AUTO_EXTRACTION_STEPS)
    for step_name in AUTO_EXTRACTION_STEPS:
        step = steps[step_name]
        if step.status == "completed":
            continue
        if durable:
            lease_seconds = max(settings.ingestion_worker_lease_seconds, 900) if step_name in EXTERNAL_SIDE_EFFECT_STEPS else settings.ingestion_worker_lease_seconds
            step, claim_state = _claim_step(session, pipeline.id, step_name, lease_seconds)
            steps[step_name] = step
            if claim_state == "completed":
                if isinstance(step.artifact_payload, dict):
                    artifacts[step_name] = PipelineArtifact(ref=step.output_artifact_ref or _artifact_ref(version, step_name), payload=step.artifact_payload)
                continue
            if claim_state == "busy":
                return pipeline
            if claim_state == "ambiguous":
                safe = "External step outcome is ambiguous after worker interruption; authorized retry is required"
                _fail_step(step, safe)
                pipeline.status = "failed"
                pipeline.error_message = safe
                pipeline.current_step_name = step_name
                version.status = "failed"
                session.commit()
                return pipeline
            session.commit()
        else:
            _start_step(step)
        try:
            artifact = _execute_step(session, settings, adapter, ocr, project, document, version, pipeline, step_name, artifacts)
        except Exception as exc:  # noqa: BLE001 - convert adapter/internal failures into safe pipeline errors
            safe = _safe_error(exc)
            _fail_step(step, safe)
            pipeline.status = "failed"
            pipeline.error_message = safe
            pipeline.current_step_name = step_name
            pipeline.progress_percent = float(min(completed_weight, 99))
            version.status = "failed"
            version.updated_at = datetime.now(UTC)
            if durable:
                session.commit()
            return pipeline
        if artifact is not None:
            artifacts[step_name] = artifact
            step.output_artifact_ref = artifact.ref
        _complete_step(step, artifact)
        completed_weight += STEP_WEIGHTS.get(step_name, 0)
        pipeline.progress_percent = float(min(completed_weight, 99))
        pipeline.current_step_name = step_name
        if durable:
            session.commit()
    now = datetime.now(UTC)
    pipeline.status = "submission_ready"
    pipeline.progress_percent = 100
    pipeline.current_step_name = "prepare_submission"
    pipeline.completed_at = now
    pipeline.error_message = None
    version.status = "submission_ready"
    version.processed_at = now
    version.updated_at = now
    document.updated_at = now
    if durable:
        session.commit()
    return pipeline


def retry_failed_step(
    *,
    session: Session,
    settings: Settings,
    project: Project,
    document: Document,
    version: DocumentVersion,
    pipeline: PipelineRun,
    step_name: str,
    staging_adapter: StagingIndexAdapter | None = None,
    ocr_adapter: OCRAdapter | None = None,
) -> PipelineRun:
    step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id, PipelineRunStep.step_name == step_name))
    if step is None:
        raise AppError("pipeline_step_not_found", "Pipeline step was not found", status_code=404)
    if step.status != "failed":
        raise AppError("pipeline_step_not_failed", "Only failed pipeline steps can be retried", status_code=409)
    if step.retry_count >= MAX_STEP_RETRIES:
        raise AppError("pipeline_retry_limit_exceeded", "Pipeline step retry limit has been reached", status_code=409, details={"max_retries": MAX_STEP_RETRIES})
    step.retry_count += 1
    step.error_message = None
    pipeline.status = "running"
    pipeline.error_message = None
    pipeline.completed_at = None
    version.status = "processing"
    _reset_from_step(session, version.id, _steps_for_run(session, pipeline.id), step_name)
    event = session.scalar(select(OutboxEvent).where(OutboxEvent.topic == "document.extraction.requested", OutboxEvent.aggregate_id == pipeline.id).limit(1))
    if event is None:
        event = OutboxEvent(id=uuid4(), topic="document.extraction.requested", aggregate_type="pipeline_run", aggregate_id=pipeline.id, project_id=project.id, project_generation=project.work_generation, payload={"pipeline_run_id": str(pipeline.id), "project_id": str(project.id), "project_generation": project.work_generation}, status="pending", attempts=0, available_at=datetime.now(UTC), created_at=datetime.now(UTC))
        session.add(event)
    else:
        event.status = "pending"
        event.available_at = datetime.now(UTC)
        event.processed_at = None
        event.task_id = None
        event.last_error = None
    pipeline.status = "queued"
    pipeline.current_step_name = step_name
    version.status = "queued"
    return pipeline


def latest_pipeline_for_version(session: Session, version_id: UUID) -> PipelineRun | None:
    return session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == version_id).order_by(desc(PipelineRun.created_at)).limit(1))


def ensure_no_active_pipeline(session: Session, version_id: UUID) -> None:
    active = session.scalar(
        select(PipelineRun)
        .where(PipelineRun.document_version_id == version_id, PipelineRun.status.in_(("queued", "running", "waiting_action")))
        .order_by(desc(PipelineRun.created_at))
        .limit(1)
    )
    if active is not None:
        raise AppError("pipeline_already_running", "A pipeline is already running for this document version", status_code=409)


def _steps_for_run(session: Session, run_id: UUID) -> dict[str, PipelineRunStep]:
    return {step.step_name: step for step in session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == run_id))}


def _reset_from_step(session: Session, version_id: UUID, steps: dict[str, PipelineRunStep], start_step: str) -> None:
    if start_step not in AUTO_EXTRACTION_STEPS:
        raise AppError("pipeline_step_not_retryable", "Only automatic extraction steps can be retried", status_code=409)
    reset = False
    for name in AUTO_EXTRACTION_STEPS:
        if name == start_step:
            reset = True
        if not reset:
            continue
        step = steps[name]
        step.status = "pending"
        step.progress_percent = 0
        step.started_at = None
        step.completed_at = None
        step.output_artifact_ref = None
        step.artifact_payload = None
        step.artifact_fingerprint = None
        step.claim_token = None
        step.claimed_at = None
        step.lease_expires_at = None
        if name != start_step:
            step.error_message = None
    if AUTO_EXTRACTION_STEPS.index(start_step) <= AUTO_EXTRACTION_STEPS.index("chunk_knowledge"):
        session.execute(delete(Chunk).where(Chunk.document_version_id == version_id))


def _execute_step(
    session: Session,
    settings: Settings,
    staging_adapter: StagingIndexAdapter,
    ocr_adapter: OCRAdapter,
    project: Project,
    document: Document,
    version: DocumentVersion,
    pipeline: PipelineRun,
    step_name: str,
    artifacts: dict[str, PipelineArtifact],
) -> PipelineArtifact | None:
    if step_name == "upload_received":
        return _artifact(version, step_name, {"source": version.original_snapshot_uri, "adapter_source": "database"})
    if step_name == "parse_document":
        parsed = _parse_document_payload(settings, version)
        return _artifact(version, step_name, {**parsed, "title": document.title})
    if step_name == "ocr_extract":
        text = str(artifacts["parse_document"].payload["text"])
        reliable_text = _has_reliable_text_layer(version)
        force_ocr = bool((version.chunk_strategy or {}).get("force_ocr"))
        model = session.get(AIModel, version.ocr_model_id) if version.ocr_model_id is not None else None
        if model is not None and model.deleted_at is not None:
            raise AppError("ocr_model_required", "An active OCR model is required", status_code=409)
        usage_step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id, PipelineRunStep.step_name == step_name))
        started = perf_counter()
        try:
            result = ocr_adapter.extract_text(model=model, version=version, parsed_text=text, force_ocr=force_ocr, reliable_text_layer=reliable_text)
        except AppError as exc:
            if model is not None:
                record_model_usage(
                    session,
                    model=model,
                    usage_purpose="ocr_extract",
                    source_channel="pipeline",
                    status="failed",
                    error_code=exc.code,
                    attempted=exc.code not in {"ocr_adapter_not_configured", "ocr_adapter_credential_required", "ocr_adapter_secret_ref_unresolved"},
                    latency_ms=max(0, int((perf_counter() - started) * 1000)),
                    project_id=project.id,
                    document_id=document.id,
                    document_version_id=version.id,
                    pipeline_run_id=pipeline.id,
                    pipeline_step_id=usage_step.id if usage_step is not None else None,
                    actor_user_id=pipeline.triggered_by,
                    metadata=_safe_usage_error_metadata(exc),
                )
            raise
        if model is not None and not result.skipped:
            usage = (result.metadata or {}).get("usage")
            record_model_usage(
                session,
                model=model,
                usage_purpose="ocr_extract",
                source_channel="pipeline",
                status="success",
                token_usage=usage if isinstance(usage, dict) else None,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                project_id=project.id,
                document_id=document.id,
                document_version_id=version.id,
                pipeline_run_id=pipeline.id,
                pipeline_step_id=usage_step.id if usage_step is not None else None,
                actor_user_id=pipeline.triggered_by,
            )
        return _artifact(
            version,
            step_name,
            {
                "skipped": result.skipped,
                "reason": result.reason,
                "text": result.text,
                "adapter_source": result.adapter_source,
                "ocr_model_id": str(version.ocr_model_id) if version.ocr_model_id else None,
                "ocr_config_version": version.ocr_config_version,
                "text_layer_status": "reliable" if reliable_text else "ocr_required",
                "execution_snapshot": result.metadata or {},
            },
        )
    if step_name == "split_paragraphs":
        markdown_source, adapter_source = _canonical_markdown_source(artifacts)
        config = _structure_chunking_config(settings, version)
        page_ranges = _page_ranges_from_artifacts(artifacts, markdown_source)
        parser = MarkdownStructureParser()
        structure = _apply_header_footer_policy(parser.parse(markdown_source, page_ranges=page_ranges), page_ranges=page_ranges, config=config)
        paragraphs = _split_paragraphs(markdown_source)
        layout = _document_layout_artifact(structure)
        version.chunk_strategy = {
            **(version.chunk_strategy or {}),
            "document_layout": layout,
            "structure_aware": True,
            "parser_version": parser.version,
            "chunker_version": CHUNKER_VERSION,
            "normalizer_version": NORMALIZER_VERSION,
            "tokenizer_version": UnicodeTokenCounter().version,
            "effective_chunk_config": config.snapshot(),
            "page_ranges": page_ranges,
            "document_structure": structure.as_metadata(),
        }
        return _artifact(version, step_name, {"paragraphs": paragraphs, "document_layout": layout, "document_structure": structure.as_metadata(), "adapter_source": f"markdown-structure-parser:{adapter_source}"})
    if step_name == "chunk_knowledge":
        markdown_source, _adapter_source = _canonical_markdown_source(artifacts)
        chunks = _create_structure_chunks(session, settings, project, document, version, markdown_source)
        return _artifact(version, step_name, {"chunk_count": len(chunks), "chunk_ids": [str(chunk.id) for chunk in chunks], "adapter_source": CHUNKER_VERSION, "processing_versions": _processing_versions(version)})
    if step_name == "generate_markdown":
        markdown, adapter_source = _canonical_markdown_source(artifacts)
        version.markdown_artifact_uri = _artifact_ref(version, step_name)
        return _artifact(version, step_name, {"markdown": markdown, "adapter_source": adapter_source})
    if step_name == "auto_tag":
        chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id, Chunk.status == "active").order_by(Chunk.chunk_index)))
        markdown = str((artifacts.get("generate_markdown") or _artifact(version, "generate_markdown", {"markdown": ""})).payload.get("markdown") or "")
        result = _apply_llm_tags(session=session, settings=settings, project=project, version=version, pipeline=pipeline, chunks=chunks, document_text=markdown)
        return _artifact(version, step_name, result)
    if step_name == "build_embeddings":
        chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id, Chunk.status == "active").order_by(Chunk.chunk_index)))
        result = _build_live_embeddings(session, project, version, chunks)
        return _artifact(version, step_name, result)
    if step_name == "build_staging_index":
        chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id, Chunk.status == "active").order_by(Chunk.chunk_index)))
        embedding_batch = load_canonical_embeddings(session, project=project, version=version, chunks=chunks)
        result = staging_adapter.write_chunks(project=project, document=document, version=version, chunks=chunks, vectors=embedding_batch.vectors, profile=embedding_batch.profile)
        embedding_batch.build.status = "staged"
        embedding_batch.build.index_name = result.index_name
        version.extraction_artifact_uri = f"opensearch://{result.index_name}"
        return _artifact(version, step_name, {"index_name": result.index_name, "document_ids": result.document_ids, "status": result.status, "adapter_source": result.adapter_source, "error": result.error})
    if step_name == "build_graph_preview":
        chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id, Chunk.status == "active").order_by(Chunk.chunk_index)))
        preview = _graph_preview_artifact(session, project, document, version, chunks)
        version.chunk_strategy = {**(version.chunk_strategy or {}), "graph_preview": preview}
        return _artifact(version, step_name, {**preview, "adapter_source": "internal-graph-preview-builder"})
    if step_name == "prepare_submission":
        return _artifact(version, step_name, {"status": "submission_ready", "adapter_source": "database"})
    return None


def _start_step(step: PipelineRunStep) -> None:
    step.status = "running"
    step.progress_percent = 10
    step.started_at = datetime.now(UTC)
    step.completed_at = None


def _claim_step(session: Session, pipeline_id: UUID, step_name: str, lease_seconds: int) -> tuple[PipelineRunStep, str]:
    now = datetime.now(UTC)
    step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline_id, PipelineRunStep.step_name == step_name).with_for_update())
    if step is None:
        raise AppError("pipeline_step_not_found", "Pipeline step was not found", status_code=404)
    if step.status == "completed":
        return step, "completed"
    if step.status == "running" and step.started_at is not None:
        if step.lease_expires_at is not None and step.lease_expires_at > now:
            return step, "busy"
        if step_name in EXTERNAL_SIDE_EFFECT_STEPS:
            return step, "ambiguous"
    _start_step(step)
    step.claim_token = uuid4()
    step.claimed_at = now
    step.lease_expires_at = now + timedelta(seconds=lease_seconds)
    return step, "claimed"


def _complete_step(step: PipelineRunStep, artifact: PipelineArtifact | None) -> None:
    step.status = "completed"
    step.progress_percent = 100
    step.completed_at = datetime.now(UTC)
    step.claim_token = None
    step.claimed_at = None
    step.lease_expires_at = None
    if artifact is not None:
        step.progress_message = f"{step.step_name.replace('_', ' ')} completed via {artifact.payload.get('adapter_source', 'adapter')}"
        step.artifact_payload = artifact.payload
        step.artifact_fingerprint = hashlib.sha256(json.dumps(artifact.payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _fail_step(step: PipelineRunStep, message: str) -> None:
    step.status = "failed"
    step.error_message = message
    step.completed_at = datetime.now(UTC)
    step.claim_token = None
    step.claimed_at = None
    step.lease_expires_at = None


def _artifact(version: DocumentVersion, step_name: str, payload: dict[str, object]) -> PipelineArtifact:
    return PipelineArtifact(ref=_artifact_ref(version, step_name), payload=payload)


def _build_live_embeddings(session: Session, project: Project, version: DocumentVersion, chunks: list[Chunk]) -> dict[str, object]:
    batch = embed_chunks(session, project=project, version=version, chunks=chunks, settings=get_settings())
    return {
        "adapter_source": batch.adapter_source,
        "embedding_model_id": str(batch.model.id),
        "embedding_profile_id": str(batch.profile.id),
        "model_name": model_name(batch.model),
        "chunk_count": len(chunks),
        "vector_dimension": batch.profile.vector_dimension,
        "usage": batch.usage,
        "embedding_build_id": str(batch.build.id),
        "content_fingerprint": batch.build.content_fingerprint,
    }


def _embedding_profile(session: Session, model: AIModel, version: DocumentVersion, dimension: int) -> EmbeddingProfile:
    config = model.config if isinstance(model.config, dict) else {}
    model_version = _model_name(model)
    distance_method = _string(config.get("distance_method") or "cosine") or "cosine"
    mapping_version = _int(config.get("mapping_version"), default=1)
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
    body: dict[str, Any] = {"model": _model_name(model), "input": texts}
    dimensions = _int(config.get("dimensions") or config.get("embedding_dimension"), default=0)
    if dimensions > 0:
        body["dimensions"] = dimensions
    request = urllib.request.Request(
        _openai_embeddings_url(_string(config.get("base_url") or model.endpoint or "https://api.openai.com/v1")),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **_embedding_auth_headers(model, settings)},
        method="POST",
    )
    context = _ssl_context(config)
    try:
        with urllib.request.urlopen(request, timeout=_timeout(config, default=60), context=context) as response:  # noqa: S310 - operator-configured model endpoint
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AppError("embedding_adapter_provider_rejected", "Embedding adapter provider rejected the request", status_code=502, details={"status_code": exc.code}) from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise AppError("embedding_adapter_unavailable", "Embedding adapter endpoint is unavailable", status_code=503) from exc


def _embedding_auth_headers(model: AIModel, settings: Settings) -> dict[str, str]:
    api_key = _resolve_model_api_key(model, settings)
    if not api_key:
        raise AppError("embedding_adapter_credential_required", "Embedding adapter API key is required", status_code=409)
    return {"Authorization": f"Bearer {api_key}"}


def _openai_embeddings_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    lowered = normalized.lower()
    if lowered.endswith("/embeddings"):
        return normalized
    if lowered.endswith("/responses"):
        normalized = normalized[: -len("/responses")]
    if lowered.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    return f"{normalized}/embeddings"


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


def _estimated_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _artifact_ref(version: DocumentVersion, step_name: str) -> str:
    return f"artifact://document_versions/{version.id}/{step_name}"


def _default_ocr_adapter(session: Session, version: DocumentVersion, settings: Settings | None = None) -> OCRAdapter:
    model = session.get(AIModel, version.ocr_model_id) if version.ocr_model_id is not None else None
    if model is not None and model.deleted_at is not None:
        model = None
    provider = (model.provider if model else "").lower().replace(" ", "_")
    if model is not None and provider == "tesseract":
        return TesseractOCRAdapter(settings)
    if model is not None and provider == "openai":
        return OpenAIOCRAdapter(settings)
    if model is not None and model.endpoint and provider in {"generic_http", "http", "paddleocr", "azure_ai_document_intelligence", "azure"}:
        return GenericHTTPOCRAdapter(settings)
    if model is not None and model.endpoint:
        return UnsupportedOCRAdapter()
    return LiveOnlyOCRAdapter()


def _require_tesseract_runtime(settings: Settings) -> None:
    commands = (
        shlex.split(settings.tesseract_command),
        shlex.split(settings.tesseract_pdf_command),
        shlex.split(settings.tesseract_sandbox_command),
    )
    if any(not command or shutil.which(command[0]) is None for command in commands):
        raise AppError(
            "ocr_tesseract_runtime_unavailable",
            "Tesseract sandbox runtime is unavailable",
            status_code=503,
        )


def _tesseract_inputs(settings: Settings, version: DocumentVersion) -> list[tuple[str, str, bytes]]:
    if (version.canonical_extension or "").lower() == ".docx":
        return _docx_ocr_inputs(settings, version)
    source = _load_source_object(settings, version)
    content_type = source.content_type or version.mime_type or _mime_type_for(version)
    return [
        (
            version.original_file_name or f"document{version.canonical_extension or ''}",
            content_type,
            source.body,
        )
    ]


def _tesseract_extension(file_name: str, content_type: str) -> str:
    by_type = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/tiff": ".tiff",
        "image/bmp": ".bmp",
        "image/webp": ".webp",
    }
    extension = by_type.get(content_type.lower())
    if extension is None:
        candidate = Path(file_name).suffix.lower()
        extension = candidate if candidate in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"} else None
    if extension is None:
        raise AppError("ocr_tesseract_input_unsupported", "Tesseract input type is unsupported", status_code=422)
    return extension


def _tesseract_languages(snapshot: dict[str, object]) -> str:
    values = snapshot.get("languages")
    languages = values if isinstance(values, list) else []
    aliases = {
        "en": "eng",
        "en_us": "eng",
        "en_gb": "eng",
        "zh": "chi_tra",
        "zh_tw": "chi_tra",
        "zh_hant": "chi_tra",
        "traditional_chinese": "chi_tra",
    }
    normalized = []
    for item in languages:
        value = str(item).strip().replace("-", "_")
        if value:
            normalized.append(aliases.get(value.lower(), value))
    normalized = normalized or ["eng"]
    if any(not re.fullmatch(r"[A-Za-z0-9_]+", item) for item in normalized):
        raise AppError("ocr_language_invalid", "Tesseract language configuration is invalid", status_code=422)
    return "+".join(dict.fromkeys(normalized))


def _run_ocr_sandbox(
    settings: Settings,
    root: Path,
    command: list[str],
    *,
    deadline: float,
    error_code: str,
) -> subprocess.CompletedProcess[bytes]:
    remaining = int(deadline - perf_counter())
    if remaining <= 0:
        raise AppError("ocr_tesseract_timeout", "Tesseract exceeded its time limit", status_code=503)
    arguments = [
        *shlex.split(settings.tesseract_sandbox_command),
        "--unshare-net",
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--bind",
        str(root),
        str(root),
        "--chdir",
        str(root),
        *command,
    ]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "ftp_proxy"}
    }
    environment.update({"HOME": str(root), "TMPDIR": str(root), "NO_PROXY": "*"})
    try:
        completed = subprocess.run(
            arguments,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=remaining,
            check=False,
            preexec_fn=lambda: _limit_tesseract_process(settings),
        )
    except FileNotFoundError as exc:
        raise AppError("ocr_tesseract_runtime_unavailable", "Tesseract sandbox runtime is unavailable", status_code=503) from exc
    except subprocess.TimeoutExpired as exc:
        raise AppError("ocr_tesseract_timeout", "Tesseract exceeded its time limit", status_code=503) from exc
    if completed.returncode != 0:
        raise AppError(error_code, "Tesseract could not process the document", status_code=422, details={"return_code": completed.returncode})
    if len(completed.stdout) > settings.max_upload_size_mb * 1024 * 1024 * 4:
        raise AppError("ocr_tesseract_output_limit", "Tesseract output exceeds the safe limit", status_code=422)
    return completed


def _limit_tesseract_process(settings: Settings) -> None:
    memory_bytes = settings.tesseract_max_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (settings.tesseract_timeout_seconds, settings.tesseract_timeout_seconds + 1),
    )
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (
            settings.max_upload_size_mb * 1024 * 1024 * 4,
            settings.max_upload_size_mb * 1024 * 1024 * 4,
        ),
    )
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    if hasattr(resource, "RLIMIT_CORE"):
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _tesseract_version(settings: Settings) -> str:
    command = shlex.split(settings.tesseract_command)
    try:
        completed = subprocess.run(
            [*command, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise AppError("ocr_tesseract_runtime_unavailable", "Tesseract runtime is unavailable", status_code=503) from exc
    first_line = completed.stdout.decode("utf-8", errors="replace").splitlines()
    if completed.returncode != 0 or not first_line:
        raise AppError("ocr_tesseract_runtime_unavailable", "Tesseract version evidence is unavailable", status_code=503)
    return first_line[0][:120]


def _ocr_snapshot(model: AIModel | None, version: DocumentVersion, force_ocr: bool) -> dict[str, object]:
    configured = dict((version.chunk_strategy or {}).get("ocr_snapshot") or {})
    config = model.config if model is not None and isinstance(model.config, dict) else {}
    timeout = configured.get("timeout_seconds", config.get("timeout_seconds", config.get("timeout", 30)))
    retries = configured.get("retry_count", config.get("retry_count", config.get("retries", 1)))
    languages = configured.get("languages", config.get("languages", config.get("language", [])))
    return {
        "model_id": str(version.ocr_model_id) if version.ocr_model_id else configured.get("model_id"),
        "config_version": version.ocr_config_version or configured.get("config_version"),
        "provider": model.provider if model is not None else configured.get("provider", "unknown"),
        "endpoint_configured": bool(model.endpoint if model is not None else configured.get("endpoint_configured")),
        "languages": languages if isinstance(languages, list) else [languages],
        "timeout_seconds": max(1, min(int(timeout or 30), 600)),
        "retry_count": max(0, min(int(retries or 0), 5)),
        "force_ocr": force_ocr,
        "force_ocr_confirmed": bool((version.chunk_strategy or {}).get("force_ocr_confirmed", force_ocr)),
    }


def _load_source_object(settings: Settings, version: DocumentVersion):
    from app.integrations.s3_storage import S3ObjectStorage

    if not version.storage_bucket or not version.storage_key:
        raise AppError("ocr_source_file_missing", "OCR source file is not available", status_code=409)
    storage = S3ObjectStorage(settings)
    return storage.get_object(bucket=version.storage_bucket, key=version.storage_key, max_bytes=settings.max_upload_size_mb * 1024 * 1024)


def _docx_ocr_inputs(settings: Settings, version: DocumentVersion) -> list[tuple[str, str, bytes]]:
    from app.integrations.s3_storage import S3ObjectStorage

    raw_manifest = (version.chunk_strategy or {}).get("office_media")
    if not isinstance(raw_manifest, list) or not raw_manifest:
        raise AppError("docx_ocr_media_missing", "DOCX does not contain validated image artifacts for OCR", status_code=422)
    if len(raw_manifest) > 512:
        raise AppError("docx_ocr_media_invalid", "DOCX OCR media manifest exceeds the safe limit", status_code=422)
    expected_prefix = f"projects/{version.project_id}/documents/{version.document_id}/versions/{version.id}/artifacts/media/"
    storage = S3ObjectStorage(settings)
    inputs: list[tuple[str, str, bytes]] = []
    total = 0
    for item in raw_manifest:
        if not isinstance(item, dict):
            raise AppError("docx_ocr_media_invalid", "DOCX OCR media manifest is invalid", status_code=422)
        bucket = item.get("storage_bucket")
        key = item.get("storage_key")
        content_type = item.get("content_type")
        if bucket != settings.s3_bucket or not isinstance(key, str) or not key.startswith(expected_prefix) or not isinstance(content_type, str) or not content_type.startswith("image/"):
            raise AppError("docx_ocr_media_invalid", "DOCX OCR media scope is invalid", status_code=422)
        remote = storage.get_object(bucket=bucket, key=key, max_bytes=settings.max_upload_size_mb * 1024 * 1024)
        total += len(remote.body)
        if total > settings.max_upload_size_mb * 1024 * 1024 * 2:
            raise AppError("docx_ocr_media_invalid", "DOCX OCR media exceeds the safe limit", status_code=422)
        inputs.append((Path(key).name, content_type, remote.body))
    return inputs


def _openai_ocr_payload(model: AIModel, version: DocumentVersion, inputs: list[tuple[str, str, bytes]], parsed_text: str) -> dict[str, Any]:
    config = model.config if isinstance(model.config, dict) else {}
    document_file_name = version.original_file_name or f"document{version.canonical_extension or ''}"
    system_prompt = (
        "You are NomoSmart's OCR extraction engine. Extract the uploaded document into Markdown only. "
        "Preserve the document's original reading order and visible structure as much as possible. "
        "Use Markdown headings, paragraphs, bullet or numbered lists, tables and code fences when the source structure supports them. "
        "Do not summarize, do not add commentary, and do not wrap the entire answer in a code block."
    )
    user_prompt = (
        f"File name: {document_file_name}\n"
        f"Input files: {len(inputs)}\n"
        "Return only Markdown text extracted from the document."
    )
    if parsed_text.strip():
        user_prompt += "\n\nParser text layer candidate. Use it only if it matches the visual document:\n" + parsed_text[:12000]
    input_content: list[dict[str, str]] = [{"type": "input_text", "text": user_prompt}]
    for file_name, content_type, source_bytes in inputs:
        data_uri = f"data:{content_type};base64,{b64encode(source_bytes).decode('ascii')}"
        if content_type.startswith("image/"):
            input_content.append({"type": "input_image", "image_url": data_uri})
        else:
            input_content.append({"type": "input_file", "filename": file_name, "file_data": data_uri})
    body: dict[str, Any] = {
        "model": _model_name(model),
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {
                "role": "user",
                "content": input_content,
            },
        ],
        "max_output_tokens": _int(config.get("max_output_tokens", config.get("max_tokens")), default=4096),
    }
    if config.get("temperature") is not None:
        body["temperature"] = _float(config.get("temperature"), default=0.0)
    return body


def _post_openai_ocr(model: AIModel, settings: Settings, body: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    config = model.config if isinstance(model.config, dict) else {}
    base_url = _string(config.get("base_url") or model.endpoint or "https://api.openai.com/v1").rstrip("/")
    if not base_url:
        raise AppError("ocr_adapter_not_configured", "OCR adapter endpoint is not configured", status_code=422)
    request = urllib.request.Request(
        _openai_responses_url(base_url),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **_openai_auth_headers(model, settings)},
        method="POST",
    )
    context = _ssl_context(config)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:  # noqa: S310 - operator-configured OpenAI-compatible endpoint
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AppError(
            "ocr_adapter_provider_rejected",
            "OCR adapter provider rejected the request",
            status_code=502,
            details=_safe_provider_error_details(exc),
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise AppError("ocr_adapter_unavailable", "OCR adapter endpoint is unavailable", status_code=503) from exc


def _safe_provider_error_details(exc: urllib.error.HTTPError) -> dict[str, object]:
    details: dict[str, object] = {"status_code": int(exc.code)}
    try:
        raw = exc.read(65537)
        if len(raw) > 65536:
            return details
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return details
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return details
    for field in ("type", "code", "param"):
        value = error.get(field)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            details[field] = str(value)[:160]
    return details


def _safe_usage_error_metadata(exc: AppError) -> dict[str, object]:
    provider_error: dict[str, object] = {}
    for field in ("status_code", "type", "code", "param"):
        value = exc.details.get(field)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            provider_error[field] = value if field == "status_code" else str(value)[:160]
    return {"provider_error": provider_error} if provider_error else {}


def _openai_auth_headers(model: AIModel, settings: Settings) -> dict[str, str]:
    api_key = _resolve_model_api_key(model, settings)
    if not api_key:
        raise AppError("ocr_adapter_credential_required", "OCR adapter API key is required", status_code=409)
    return {"Authorization": f"Bearer {api_key}"}


def _openai_responses_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    return normalized if normalized.endswith("/responses") else f"{normalized}/responses"


def _ssl_context(config: dict[str, object]) -> ssl.SSLContext | None:
    if not _verify_tls(config):
        return ssl._create_unverified_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        return None


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


def _openai_ocr_markdown(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                texts.append(content["text"])
    markdown = "\n\n".join(text.strip() for text in texts if text.strip()).strip()
    if not markdown:
        raise AppError("ocr_adapter_empty_result", "OCR adapter returned no text", status_code=502)
    return markdown


def _valid_markdown_ocr_text(markdown: str) -> bool:
    text = markdown.strip()
    if not text:
        return False
    if text[0] in "{[":
        try:
            json.loads(text)
        except json.JSONDecodeError:
            return True
        return False
    return True


def _model_name(model: AIModel) -> str:
    value = _string((model.config or {}).get("model_name") or model.name)
    if not value:
        raise AppError("ocr_model_name_required", "OCR Model model_name is required", status_code=422)
    return value


def _mime_type_for(version: DocumentVersion) -> str:
    extension = (version.canonical_extension or "").lower()
    if extension == ".pdf":
        return "application/pdf"
    if extension in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if extension == ".png":
        return "image/png"
    if extension == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(value: object, *, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _float(value: object, *, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _timeout(config: dict[str, object], *, default: int = 60) -> int:
    return max(1, min(_int(config.get("timeout_seconds") or config.get("timeout"), default=default), 300))


def _verify_tls(config: dict[str, object]) -> bool:
    value = config.get("verify_tls", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return True


def _parse_document_payload(settings: Settings, version: DocumentVersion) -> dict[str, object]:
    strategy = version.chunk_strategy or {}
    source_text = strategy.get("source_text") or strategy.get("parsed_text")
    if isinstance(source_text, str) and source_text.strip():
        return {"text": source_text.strip(), "canonical_markdown": source_text, "adapter_source": "configured-source-text"}
    extension = (version.canonical_extension or "").lower()
    if extension == ".doc":
        raise AppError("legacy_doc_reextraction_unsupported", "Legacy DOC files cannot be re-extracted; upload a DOCX replacement", status_code=422)
    if extension == ".docx":
        parsed = parse_office_document(settings, version)
        parser_metadata = dict(parsed.metadata)
        version.parser_version = str(parser_metadata.get("parser_version") or "pandoc:unknown")[:100]
        version.chunk_strategy = {
            **strategy,
            "text_layer_status": "reliable" if parsed.reliable_text_layer else "none",
            "office_parser": "pandoc-isolated-docx-gfm",
            "office_media": list(parsed.media),
            "office_parser_metadata": parser_metadata,
        }
        return {
            "text": parsed.markdown,
            "canonical_markdown": parsed.markdown,
            "media": list(parsed.media),
            "parser_metadata": parser_metadata,
            "adapter_source": "pandoc-isolated-docx-gfm",
        }
    if bool(strategy.get("force_ocr")) or ((version.canonical_extension or "").lower() == ".pdf" and not _has_reliable_text_layer(version)):
        return {"text": "", "adapter_source": "ocr-required-source"}
    raise AppError("parser_adapter_not_configured", "Parser adapter is not configured", status_code=503)


def _parse_text(settings: Settings, version: DocumentVersion) -> str:
    return str(_parse_document_payload(settings, version).get("text") or "")


def _has_reliable_text_layer(version: DocumentVersion) -> bool:
    strategy = version.chunk_strategy or {}
    if strategy.get("text_layer_status") == "reliable" or strategy.get("has_reliable_text_layer") is True:
        return True
    if strategy.get("text_layer_status") == "none" or strategy.get("has_reliable_text_layer") is False:
        return False
    return (version.canonical_extension or "").lower() in {".txt", ".md"}


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    return paragraphs or [text.strip()]


def _document_layout_artifact(paragraphs) -> dict[str, object]:
    if hasattr(paragraphs, "nodes") and hasattr(paragraphs, "parser_version"):
        return build_document_layout(paragraphs)
    markdown = "\n\n".join(str(value) for value in paragraphs)
    return build_document_layout(MarkdownStructureParser().parse(markdown))


def _split_layout_text(text: str, *, max_chars: int = 820) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        split_at = max(window.rfind("。"), window.rfind("."), window.rfind("\n"), window.rfind("；"), window.rfind(";"), window.rfind("，"), window.rfind(","))
        if split_at < max_chars // 2:
            split_at = max_chars
        parts.append(remaining[: split_at + 1].strip())
        remaining = remaining[split_at + 1 :].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _paginate_layout_blocks(blocks: list[dict[str, object]]) -> list[dict[str, object]]:
    return paginate_layout_blocks(blocks)


def _estimated_layout_block_height(block: dict[str, object]) -> int:
    return estimated_layout_block_height(block)


def _canonical_markdown_source(artifacts: dict[str, PipelineArtifact]) -> tuple[str, str]:
    generated = artifacts.get("generate_markdown")
    generated_markdown = generated.payload.get("markdown") if generated is not None else None
    if isinstance(generated_markdown, str):
        return generated_markdown, str(generated.payload.get("adapter_source") or "canonical-markdown-artifact")
    parse_payload = artifacts["parse_document"].payload
    ocr_payload = artifacts.get("ocr_extract").payload if artifacts.get("ocr_extract") is not None else {}
    canonical_markdown = parse_payload.get("canonical_markdown")
    if isinstance(canonical_markdown, str) and bool(ocr_payload.get("skipped", True)):
        return canonical_markdown, str(parse_payload.get("adapter_source") or "canonical-source-markdown")
    ocr_text = ocr_payload.get("text")
    if isinstance(ocr_text, str) and ocr_text.strip():
        return ocr_text, str(ocr_payload.get("adapter_source") or "ocr-markdown")
    parser_text = parse_payload.get("text")
    if isinstance(parser_text, str) and parser_text.strip():
        return parser_text, str(parse_payload.get("adapter_source") or "parser-text-markdown")
    return "", "internal-markdown-renderer"


def _create_chunks(
    session: Session,
    project: Project,
    document: Document,
    version: DocumentVersion,
    paragraphs: list[object],
    *,
    markdown_source: str | None = None,
) -> list[Chunk]:
    session.execute(delete(Chunk).where(Chunk.document_version_id == version.id))
    chunks: list[Chunk] = []
    now = datetime.now(UTC)
    canonical_source = markdown_source if markdown_source is not None else "\n\n".join(str(raw) for raw in paragraphs)
    search_offset = 0
    for index, raw in enumerate(paragraphs, start=1):
        content = str(raw)
        start_offset = canonical_source.find(content, search_offset)
        if start_offset < 0:
            raise AppError(
                "canonical_source_mapping_invalid",
                "Chunk content could not be mapped to canonical Markdown",
                status_code=500,
                details={"document_version_id": str(version.id), "paragraph": index},
            )
        end_offset = start_offset + len(content)
        search_offset = end_offset
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunk = Chunk(
            id=uuid4(),
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_index=index,
            title=f"{document.title} #{index}",
            content=content,
            markdown_content=f"### {document.title} #{index}\n\n{content}",
            display_markdown=f"### {document.title} #{index}\n\n{content}",
            content_type="text",
            content_hash=digest,
            start_offset=start_offset,
            end_offset=end_offset,
            source_mapping=[{
                "source": "parsed-text",
                "source_anchor": f"paragraph-{index}",
                "paragraph": index,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "offset_scope": "canonical_markdown",
                "offset_unit": "unicode_code_point",
                "markdown_start_offset": start_offset,
                "markdown_end_offset": end_offset,
                "anchor_start_offset": 0,
                "anchor_end_offset": len(content),
                "mapping_status": "resolved",
                "content_type": "text",
            }],
            embedding_model_id=version.embedding_model_id,
            token_count=max(1, len(content.split())),
            confidence_score=0.95,
            is_manual_edited=False,
            created_at=now,
            updated_at=now,
        )
        session.add(chunk)
        chunks.append(chunk)
    session.flush()
    return chunks


def _create_structure_chunks(
    session: Session,
    settings: Settings,
    project: Project,
    document: Document,
    version: DocumentVersion,
    markdown_source: str,
) -> list[Chunk]:
    processing_started = perf_counter()
    parser = MarkdownStructureParser()
    config = _structure_chunking_config(settings, version)
    page_ranges = _valid_page_ranges((version.chunk_strategy or {}).get("page_ranges"), markdown_source)
    structure = _apply_header_footer_policy(parser.parse(markdown_source, page_ranges=page_ranges), page_ranges=page_ranges, config=config)
    if not structure.nodes:
        raise AppError("markdown_structure_empty", "Canonical Markdown does not contain retrievable content", status_code=422)
    token_counter = UnicodeTokenCounter()
    drafts = StructureAwareChunker(config=config, token_counter=token_counter).chunk(
        structure,
        document_key=str(document.id),
        version_id=version.id,
    )
    if not drafts:
        raise AppError("chunk_content_required", "Document structure did not produce retrievable chunks", status_code=422)
    normalizer = RetrievalTextNormalizer(config=config, token_counter=token_counter)
    structure_metadata = structure.as_metadata()
    if config.remove_repeated_header_footer and len(page_ranges) < 3:
        warnings = list(structure_metadata.get("warnings") or [])
        warnings.append({"code": "page_boundaries_unavailable", "header_footer_removal": "skipped"})
        structure_metadata = {**structure_metadata, "warnings": warnings, "warning_count": len(warnings)}
    session.execute(delete(Chunk).where(Chunk.document_version_id == version.id))
    now = datetime.now(UTC)
    chunks: list[Chunk] = []
    for draft in drafts:
        retrieval_text = normalizer.normalize(draft, document_title=document.title)
        if not retrieval_text:
            raise AppError("retrieval_text_required", "Structure-aware chunk did not produce retrieval text", status_code=422)
        digest = hashlib.sha256(draft.display_text.encode("utf-8")).hexdigest()
        raw_digest = hashlib.sha256(draft.raw_markdown.encode("utf-8")).hexdigest()
        display_markdown_digest = hashlib.sha256(draft.display_markdown.encode("utf-8")).hexdigest()
        preview = " ".join(draft.display_text.split())
        title = preview if len(preview) <= 24 else f"{preview[:24].rstrip()}..."
        strategy = {
            **draft.metadata,
            "source": "structure_aware",
            "normalizer_version": normalizer.version,
            "previous_chunk_id": str(draft.previous_chunk_id) if draft.previous_chunk_id else None,
            "next_chunk_id": str(draft.next_chunk_id) if draft.next_chunk_id else None,
        }
        source_anchor_ranges = renderable_source_anchors(
            structure,
            start_offset=draft.start_offset,
            end_offset=draft.end_offset,
        )
        if not source_anchor_ranges:
            raise AppError("chunk_source_mapping_invalid", "Structure-aware chunk has no renderable source anchor", status_code=422)
        source_anchors = [str(value["source_anchor"]) for value in source_anchor_ranges]
        mapping = {
            "source": "canonical-markdown-structure",
            "source_anchor": source_anchors[0],
            "source_anchors": source_anchors,
            "source_anchor_ranges": source_anchor_ranges,
            "node_ids": list(draft.node_ids),
            "start_offset": draft.start_offset,
            "end_offset": draft.end_offset,
            "offset_scope": "canonical_markdown",
            "offset_unit": "unicode_code_point",
            "markdown_start_offset": draft.start_offset,
            "markdown_end_offset": draft.end_offset,
            "anchor_start_offset": source_anchor_ranges[0]["anchor_start_offset"],
            "anchor_end_offset": source_anchor_ranges[0]["anchor_end_offset"],
            "mapping_status": "resolved",
            "mapping_content": "markdown_fragment_v2",
            "markdown_fragment_sha256": raw_digest,
            "display_markdown_sha256": display_markdown_digest,
            "display_projection_version": draft.metadata.get("display_projection_version"),
            "content_type": draft.content_type,
            "heading_path": list(draft.heading_path),
            "page_start": draft.metadata.get("page_start"),
            "page_end": draft.metadata.get("page_end"),
        }
        chunk = Chunk(
            id=draft.id,
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_index=draft.sequence,
            title=title,
            content=draft.display_text,
            markdown_content=draft.raw_markdown,
            display_markdown=draft.display_markdown,
            retrieval_text=retrieval_text,
            embedding_content_hash=provisional_retrieval_hash(retrieval_text=retrieval_text, normalizer_version=normalizer.version, tokenizer_version=token_counter.version),
            content_type=draft.content_type,
            content_hash=digest,
            section_path=" > ".join(draft.heading_path) or None,
            heading_path=list(draft.heading_path) or None,
            heading_level=draft.heading_level,
            page_start=draft.metadata.get("page_start"),
            page_end=draft.metadata.get("page_end"),
            sequence=draft.sequence,
            stable_chunk_key=draft.stable_chunk_key,
            start_offset=draft.start_offset,
            end_offset=draft.end_offset,
            source_mapping=[mapping],
            chunk_strategy=strategy,
            embedding_model_id=version.embedding_model_id,
            token_count=token_counter.count(retrieval_text),
            confidence_score=0.95,
            is_manual_edited=False,
            created_at=now,
            updated_at=now,
        )
        session.add(chunk)
        chunks.append(chunk)
    version.chunk_size = config.target_chunk_tokens
    version.chunk_overlap = config.chunk_overlap_tokens
    version.chunk_strategy = {
        **(version.chunk_strategy or {}),
        "structure_aware": True,
        "parser_version": parser.version,
        "chunker_version": CHUNKER_VERSION,
        "normalizer_version": normalizer.version,
        "tokenizer_version": token_counter.version,
        "effective_chunk_config": config.snapshot(),
        "document_structure": structure_metadata,
    }
    session.flush()
    logger.info(
        "structure_aware_chunks_created",
        extra={
            "document_id": str(document.id),
            "document_version_id": str(version.id),
            "chunk_count": len(chunks),
            "node_count": len(structure.nodes),
            "heading_count": structure_metadata.get("heading_count", 0),
            "table_count": structure_metadata.get("table_count", 0),
            "warning_count": structure_metadata.get("warning_count", 0),
            "parser_version": parser.version,
            "chunker_version": CHUNKER_VERSION,
            "normalizer_version": normalizer.version,
            "tokenizer_version": token_counter.version,
            "processing_time_ms": max(0, int((perf_counter() - processing_started) * 1000)),
        },
    )
    return chunks


def _structure_chunking_config(settings: Settings, version: DocumentVersion) -> ChunkingConfig:
    strategy = version.chunk_strategy or {}
    configured = strategy.get("effective_chunk_config") if isinstance(strategy.get("effective_chunk_config"), dict) else strategy
    return ChunkingConfig(
        target_chunk_tokens=int(version.chunk_size or configured.get("target_chunk_tokens") or settings.target_chunk_tokens),
        max_chunk_tokens=int(configured.get("max_chunk_tokens") or settings.max_chunk_tokens),
        min_chunk_tokens=int(configured.get("min_chunk_tokens") or settings.min_chunk_tokens),
        chunk_overlap_tokens=int(version.chunk_overlap if version.chunk_overlap is not None else configured.get("chunk_overlap_tokens", settings.chunk_overlap_tokens)),
        heading_context_enabled=_config_bool(configured.get("heading_context_enabled"), settings.heading_context_enabled),
        max_heading_depth=int(configured.get("max_heading_depth") or settings.max_heading_depth),
        max_context_prefix_tokens=int(configured.get("max_context_prefix_tokens") or settings.max_context_prefix_tokens),
        document_title_context_enabled=_config_bool(configured.get("document_title_context_enabled"), settings.document_title_context_enabled),
        table_chunk_max_rows=int(configured.get("table_chunk_max_rows") or settings.table_chunk_max_rows),
        remove_repeated_header_footer=_config_bool(configured.get("remove_repeated_header_footer"), settings.remove_repeated_header_footer),
    )


def _config_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError("boolean chunk configuration must use true/false")


def _processing_versions(version: DocumentVersion) -> dict[str, object]:
    strategy = version.chunk_strategy or {}
    return {
        key: strategy.get(key)
        for key in ("parser_version", "chunker_version", "normalizer_version", "tokenizer_version", "effective_chunk_config")
        if strategy.get(key) is not None
    }


def _joined_page_ranges(pages: list[str]) -> list[dict[str, int]]:
    ranges: list[dict[str, int]] = []
    cursor = 0
    for page_number, page in enumerate(pages, start=1):
        start = cursor
        end = start + len(page)
        ranges.append({"page": page_number, "start_offset": start, "end_offset": end})
        cursor = end + 2
    return ranges


def _page_ranges_from_artifacts(artifacts: dict[str, PipelineArtifact], markdown_source: str) -> list[dict[str, int]]:
    ocr = artifacts.get("ocr_extract")
    snapshot = ocr.payload.get("execution_snapshot") if ocr is not None else None
    value = snapshot.get("page_ranges") if isinstance(snapshot, dict) else None
    return _valid_page_ranges(value, markdown_source)


def _valid_page_ranges(value: object, markdown_source: str) -> list[dict[str, int]]:
    if not isinstance(value, list):
        return []
    ranges: list[dict[str, int]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            return []
        start = item.get("start_offset")
        end = item.get("end_offset")
        page = item.get("page", index + 1)
        if isinstance(start, bool) or isinstance(end, bool) or isinstance(page, bool) or not isinstance(start, int) or not isinstance(end, int) or not isinstance(page, int) or not 0 <= start < end <= len(markdown_source):
            return []
        ranges.append({"page": int(page), "start_offset": start, "end_offset": end})
    if any(left["end_offset"] > right["start_offset"] for left, right in zip(ranges, ranges[1:])):
        return []
    return ranges


def _apply_header_footer_policy(structure, *, page_ranges: list[dict[str, int]], config: ChunkingConfig):
    if not config.remove_repeated_header_footer or len(page_ranges) < 3:
        return structure
    pages = [structure.raw_markdown[item["start_offset"] : item["end_offset"]] for item in page_ranges]
    detected = repeated_page_boilerplate(pages)
    return mark_repeated_boilerplate(structure, set(detected["headers"]) | set(detected["footers"]))


def _apply_llm_tags(
    *,
    session: Session,
    settings: Settings,
    project: Project,
    version: DocumentVersion,
    pipeline: PipelineRun,
    chunks: list[Chunk],
    document_text: str,
) -> dict[str, object]:
    model = _resolve_chat_tag_model(session, project)
    prompt = resolve_system_prompt(session, model=model, model_type="Chat")
    document_source = (document_text or "\n\n".join(chunk.markdown_content or chunk.content for chunk in chunks)).strip()
    if not document_source:
        raise AppError("tagging_text_required", "Text is required for auto tagging", status_code=422)

    version.llm_model_id = model.id
    _delete_rule_tag_links(session, version, chunks)
    actor_user_id = pipeline.triggered_by
    document_result = _generate_pipeline_tags(
        session=session,
        settings=settings,
        model=model,
        prompt=prompt,
        text=document_source,
        max_tags=8,
        allow_empty=False,
        usage_purpose="document_auto_tag",
        project=project,
        version=version,
        pipeline=pipeline,
    )
    document_tags = _result_tags(document_result)
    document_metadata = _tag_metadata(document_result, model=model, pipeline=pipeline, scope="document")
    for tag_text in document_tags:
        _attach_document_tag(session, project.id, version.id, tag_text, source="llm", actor_user_id=actor_user_id, metadata=document_metadata)

    chunk_results: list[dict[str, object]] = []
    chunk_tag_count = 0
    for chunk in chunks:
        chunk_text = (chunk.markdown_content or chunk.content or "").strip()
        chunk_result = _generate_pipeline_tags(
            session=session,
            settings=settings,
            model=model,
            prompt=prompt,
            text=chunk_text,
            max_tags=5,
            allow_empty=True,
            usage_purpose="chunk_auto_tag",
            project=project,
            version=version,
            pipeline=pipeline,
            chunk_id=chunk.id,
        )
        chunk_tags = _result_tags(chunk_result, allow_empty=True)
        chunk_metadata = _tag_metadata(chunk_result, model=model, pipeline=pipeline, scope="chunk", chunk_id=chunk.id)
        for tag_text in chunk_tags:
            _attach_chunk_tag(session, project.id, chunk.id, tag_text, source="llm", actor_user_id=actor_user_id, metadata=chunk_metadata)
        chunk_tag_count += len(chunk_tags)
        chunk_results.append({"chunk_id": str(chunk.id), "chunk_index": chunk.chunk_index, "tags": chunk_tags})

    return {
        "adapter_source": "live-chat-llm-tagger",
        "llm_model_id": str(model.id),
        "document_tags": document_tags,
        "chunk_tags": chunk_results,
        "document_tag_count": len(document_tags),
        "chunk_tag_count": chunk_tag_count,
    }


def _generate_pipeline_tags(
    *,
    session: Session,
    settings: Settings,
    model: AIModel,
    prompt,
    text: str,
    max_tags: int,
    allow_empty: bool,
    usage_purpose: str,
    project: Project,
    version: DocumentVersion,
    pipeline: PipelineRun,
    chunk_id: UUID | None = None,
) -> AIProviderResult:
    step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id, PipelineRunStep.step_name == "auto_tag"))
    started = perf_counter()
    try:
        result = generate_knowledge_tags(text=text, model=model, max_tags=max_tags, settings=settings, system_prompt=prompt, allow_empty=allow_empty)
    except AppError as exc:
        record_model_usage(
            session,
            model=model,
            usage_purpose=usage_purpose,
            source_channel="pipeline",
            status="failed",
            error_code=exc.code,
            latency_ms=max(0, int((perf_counter() - started) * 1000)),
            project_id=project.id,
            document_id=version.document_id,
            document_version_id=version.id,
            pipeline_run_id=pipeline.id,
            pipeline_step_id=step.id if step is not None else None,
            actor_user_id=pipeline.triggered_by,
            metadata={"chunk_id": str(chunk_id)} if chunk_id else {"scope": "document"},
        )
        raise
    record_model_usage(
        session,
        model=model,
        usage_purpose=usage_purpose,
        source_channel="pipeline",
        status="success",
        token_usage=result.token_usage,
        latency_ms=max(0, int((perf_counter() - started) * 1000)),
        project_id=project.id,
        document_id=version.document_id,
        document_version_id=version.id,
        pipeline_run_id=pipeline.id,
        pipeline_step_id=step.id if step is not None else None,
        actor_user_id=pipeline.triggered_by,
        metadata={"chunk_id": str(chunk_id)} if chunk_id else {"scope": "document"},
    )
    return result


def _delete_rule_tag_links(session: Session, version: DocumentVersion, chunks: list[Chunk]) -> None:
    session.execute(delete(DocumentVersionTag).where(DocumentVersionTag.document_version_id == version.id, DocumentVersionTag.source == "rule"))
    chunk_ids = [chunk.id for chunk in chunks]
    if chunk_ids:
        session.execute(delete(ChunkTag).where(ChunkTag.chunk_id.in_(chunk_ids), ChunkTag.source == "rule"))


def _resolve_chat_tag_model(session: Session, project: Project) -> AIModel:
    model = session.get(AIModel, project.llm_model_id) if project.llm_model_id else None
    if model is None or model.model_type != "Chat" or not model.is_active or model.deleted_at is not None:
        model = session.scalar(select(AIModel).where(AIModel.model_type == "Chat", AIModel.is_active.is_(True), AIModel.is_default.is_(True), AIModel.deleted_at.is_(None)).limit(1))
    if model is None:
        raise AppError("chat_model_required", "An active Chat LLM model is required for auto tagging", status_code=409)
    return model


def _normalize_tag_text(tag_text: str) -> str:
    normalized = re.sub(r"\s+", " ", tag_text).strip()
    if not normalized:
        raise AppError("tag_text_blank", "Tag text cannot be blank", status_code=422)
    return normalized[:80]


def _result_tags(result: AIProviderResult, *, allow_empty: bool = False) -> list[str]:
    try:
        parsed = json.loads(result.answer)
    except json.JSONDecodeError as exc:
        raise AppError("tagging_response_invalid", "Tagging response JSON is invalid", status_code=502) from exc
    if not isinstance(parsed, list):
        raise AppError("tagging_response_invalid", "Tagging response must be a JSON array", status_code=502)
    tags = [_normalize_tag_text(str(item)) for item in parsed if str(item).strip()]
    if not tags and not allow_empty:
        raise AppError("tagging_response_invalid", "Tagging response did not contain usable tags", status_code=502)
    return tags


def _tag_metadata(result: AIProviderResult, *, model: AIModel, pipeline: PipelineRun, scope: str, chunk_id: UUID | None = None) -> dict[str, object]:
    metadata: dict[str, object] = {
        "source": "llm",
        "tagging_scope": scope,
        "llm_model_id": str(model.id),
        "llm_model_name": model.name,
        "llm_provider": model.provider,
        "pipeline_run_id": str(pipeline.id),
        "request_id": str(pipeline.id),
        "system_prompt_source": result.system_prompt_source,
        "system_prompt_version_id": str(result.system_prompt_version_id) if result.system_prompt_version_id else None,
        "system_prompt_content_hash": result.system_prompt_content_hash,
        "system_prompt_layers": result.system_prompt_layers,
        "prompt_version": result.prompt_version,
        "token_usage": result.token_usage,
    }
    if chunk_id is not None:
        metadata["chunk_id"] = str(chunk_id)
    return metadata


def _get_or_create_tag(session: Session, project_id: UUID, tag_text: str) -> Tag:
    normalized = _normalize_tag_text(tag_text)
    tag = session.scalar(select(Tag).where(Tag.project_id == project_id, Tag.name == normalized))
    if tag is not None:
        return tag
    tag = Tag(id=uuid4(), project_id=project_id, name=normalized, created_at=datetime.now(UTC))
    session.add(tag)
    session.flush()
    return tag


def _attach_chunk_tag(session: Session, project_id: UUID, chunk_id: UUID, tag_text: str, *, source: str, actor_user_id: UUID | None, metadata: dict[str, object], confidence_score: float | None = None) -> None:
    tag = _get_or_create_tag(session, project_id, tag_text)
    link = session.get(ChunkTag, (chunk_id, tag.id))
    if link is None:
        session.add(ChunkTag(chunk_id=chunk_id, tag_id=tag.id, source=source, confidence_score=confidence_score, metadata_=metadata, created_by=actor_user_id, created_at=datetime.now(UTC)))
        return
    link.source = source
    link.confidence_score = confidence_score
    link.metadata_ = metadata
    link.created_by = actor_user_id


def _attach_document_tag(session: Session, project_id: UUID, version_id: UUID, tag_text: str, *, source: str, actor_user_id: UUID | None, metadata: dict[str, object], confidence_score: float | None = None) -> None:
    tag = _get_or_create_tag(session, project_id, tag_text)
    link = session.get(DocumentVersionTag, (version_id, tag.id))
    if link is None:
        session.add(DocumentVersionTag(document_version_id=version_id, tag_id=tag.id, source=source, confidence_score=confidence_score, metadata_=metadata, created_by=actor_user_id, created_at=datetime.now(UTC)))
        return
    link.source = source
    link.confidence_score = confidence_score
    link.metadata_ = metadata
    link.created_by = actor_user_id


def _graph_preview_artifact(session: Session, project: Project, document: Document, version: DocumentVersion, chunks: list[Chunk]) -> dict[str, object]:
    from app.domain.graph_projection import build_graph_projection, preview_artifact
    return preview_artifact(build_graph_projection(session, project, document, version, chunks))


def _step_message(step_name: str, ocr_name: str, force_ocr: bool) -> str:
    if step_name == "ocr_extract":
        return f"OCR model: {ocr_name}" + ("; force OCR enabled" if force_ocr else "")
    if step_name in REVIEW_AND_PUBLICATION_STEPS:
        return f"{step_name.replace('_', ' ')} is reserved for a later milestone"
    return step_name.replace("_", " ")


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.message
    if isinstance(exc, (TimeoutError, urllib.error.URLError, OSError)):
        return "Adapter endpoint is unavailable"
    return str(exc).splitlines()[0][:500] or exc.__class__.__name__
