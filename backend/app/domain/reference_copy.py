"""Target-owned copy evidence. Never calls Providers or copies vectors."""
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import NoReturn
from uuid import uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Chunk, Document, DocumentVersion, EmbeddingProfile, PipelineRun, PipelineRunStep
from app.domain.chunk_representations import chunking_config_from_snapshot
from app.domain.document_layout import build_document_layout
from app.domain.embeddings import resolve_index_retrieval_text
from app.domain.markdown_artifacts import markdown_artifact_ref, normalize_source_mappings, resolve_markdown_artifact
from app.domain.markdown_structure import MarkdownStructureParser
from app.domain.retrieval_text import RetrievalTextNormalizer, provisional_retrieval_hash
from app.domain.structure_chunking import ChunkDraft
from app.domain.tokenization import UnicodeTokenCounter


def _invalid() -> NoReturn:
    raise AppError("source_version_no_extractable_text", "Source version copy evidence is unavailable or invalid", status_code=409)


def copy_chunks(session: Session, *, source: DocumentVersion, target: DocumentVersion) -> list[Chunk]:
    artifact = resolve_markdown_artifact(session, source, require_fingerprint=True)
    if artifact.status != "available" or not artifact.text:
        _invalid()
    markdown = artifact.text
    source_document = session.get(Document, source.document_id)
    target_document = session.get(Document, target.document_id)
    profile = session.get(EmbeddingProfile, source.embedding_profile_id) if source.embedding_profile_id else None
    chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == source.id,
        Chunk.project_id == source.project_id, Chunk.document_id == source.document_id,
        Chunk.status == "active").order_by(Chunk.chunk_index, Chunk.id)))
    if not source_document or not target_document or not profile or not chunks:
        _invalid()
    if (source_document.project_id != source.project_id
            or target_document.project_id != target.project_id
            or profile.model_id != source.embedding_model_id
            or (target.chunk_strategy or {}).get("source_text") != markdown):
        _invalid()
    copied = []
    ids = {chunk.id: uuid5(target.id, str(chunk.id)) for chunk in chunks}
    counter = UnicodeTokenCounter()
    now = datetime.now(UTC)
    # Validate every source before writing target chunks. Caller owns the item transaction.
    for index, chunk in enumerate(chunks, 1):
        source_retrieval = resolve_index_retrieval_text(chunk, profile=profile)
        metadata = deepcopy(chunk.chunk_strategy or {})
        config = chunking_config_from_snapshot(metadata.get("config") or metadata.get("effective_chunk_config"))
        normalizer = RetrievalTextNormalizer(config=config, token_counter=counter)
        start, end = chunk.start_offset, chunk.end_offset
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(markdown)
                or markdown[start:end] != chunk.markdown_content or not chunk.display_markdown
                or sha256(chunk.content.encode()).hexdigest() != chunk.content_hash):
            _invalid()
        mappings = normalize_source_mappings(chunk.content, chunk.source_mapping, markdown)
        if not mappings or any(item.get("mapping_status") != "resolved" for item in mappings):
            _invalid()
        if any(item.get("mapping_content") != "markdown_fragment_v2"
               or item.get("markdown_start_offset") != start
               or item.get("markdown_end_offset") != end for item in mappings):
            _invalid()
        display_digest = sha256(chunk.display_markdown.encode()).hexdigest()
        if any(item.get("display_markdown_sha256", display_digest) != display_digest for item in mappings):
            _invalid()
        draft = ChunkDraft(id=ids[chunk.id], stable_chunk_key="", sequence=index,
            display_text=chunk.content, display_markdown=chunk.display_markdown,
            raw_markdown=chunk.markdown_content, heading_path=tuple(chunk.heading_path or ()),
            heading_level=chunk.heading_level, content_type=chunk.content_type,
            start_offset=start, end_offset=end, node_ids=(), token_count=0)
        # A stored hash alone cannot prove content and contextual prefix still agree.
        if (metadata.get("normalizer_version") != normalizer.version
                or metadata.get("tokenizer_version") != counter.version
                or normalizer.normalize(draft, document_title=source_document.title) != source_retrieval):
            _invalid()
        retrieval = normalizer.normalize(draft, document_title=target_document.title)
        stable_key = sha256(json.dumps({"document_id": str(target.document_id), "source_chunk_id": str(chunk.id),
            "raw_hash": sha256(draft.raw_markdown.encode()).hexdigest(), "retrieval_text": retrieval,
            "sequence": index}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        metadata = {key: value for key, value in metadata.items() if not key.startswith("embedding_")}
        metadata.update(source="copied", structure_aware=True,
            copied_from_chunk_id=str(chunk.id), copied_from_version_id=str(source.id),
            copied_from_project_id=str(source.project_id), copied_from_document_id=str(source.document_id),
            previous_chunk_id=str(ids[chunks[index - 2].id]) if index > 1 else None,
            next_chunk_id=str(ids[chunks[index].id]) if index < len(chunks) else None)
        copied.append(Chunk(id=draft.id, project_id=target.project_id, document_id=target.document_id,
            document_version_id=target.id, chunk_index=index, title=chunk.title, content=chunk.content,
            markdown_content=chunk.markdown_content, display_markdown=chunk.display_markdown,
            retrieval_text=retrieval, embedding_content_hash=provisional_retrieval_hash(retrieval_text=retrieval,
                normalizer_version=normalizer.version, tokenizer_version=counter.version),
            content_type=chunk.content_type, content_hash=chunk.content_hash, section_path=chunk.section_path,
            heading_path=deepcopy(chunk.heading_path), heading_level=chunk.heading_level,
            page_start=chunk.page_start, page_end=chunk.page_end, sequence=index, stable_chunk_key=stable_key,
            start_offset=start, end_offset=end, source_mapping=mappings, chunk_strategy=metadata,
            embedding_model_id=target.embedding_model_id, token_count=counter.count(retrieval),
            confidence_score=chunk.confidence_score, status="active", is_manual_edited=False,
            created_at=now, updated_at=now))
    source_strategy = source.chunk_strategy or {}
    inherited = {key: deepcopy(source_strategy[key]) for key in (
        "page_ranges", "parser_version", "chunker_version", "normalizer_version", "tokenizer_version",
        "effective_chunk_config", "document_structure", "document_layout") if key in source_strategy}
    if "document_layout" not in inherited:
        inherited["document_layout"] = build_document_layout(MarkdownStructureParser().parse(markdown))
    target.chunk_strategy = {**(target.chunk_strategy or {}), **inherited, "structure_aware": True}
    target.chunk_size, target.chunk_overlap = source.chunk_size, source.chunk_overlap
    target.markdown_artifact_uri = markdown_artifact_ref(target.id)
    session.add_all(copied)
    session.flush()
    # Insert all targets first: a parent can occur later in the source ordering.
    # Historical/non-active parents are provenance, not target live relationships.
    for original, clone in zip(chunks, copied):
        clone.parent_chunk_id = ids.get(original.parent_chunk_id)
    session.flush()
    return copied


def complete_copied_steps(session: Session, *, source: DocumentVersion, target: DocumentVersion,
                          pipeline: PipelineRun, chunks: list[Chunk]) -> None:
    """Only called after target chunks/tags persist; all refs are target-owned."""
    from app.domain.extraction_pipeline import AUTO_EXTRACTION_STEPS

    strategy = target.chunk_strategy or {}
    markdown = strategy["source_text"]
    payloads = {
        "upload_received": {"source_sha256": target.content_sha256},
        "parse_document": {"text": markdown, "page_ranges": strategy.get("page_ranges", [])},
        "ocr_extract": {"markdown": markdown, "reused_source_ocr": True},
        "generate_markdown": {"markdown": markdown},
        "split_paragraphs": {"document_layout": strategy["document_layout"],
            "document_structure": strategy.get("document_structure", {})},
        "chunk_knowledge": {"chunk_count": len(chunks), "chunk_ids": [str(chunk.id) for chunk in chunks]},
        "auto_tag": {"reused_source_tags": True, "source": "copied"},
    }
    names = AUTO_EXTRACTION_STEPS[:AUTO_EXTRACTION_STEPS.index("build_embeddings")]
    steps = list(session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id,
        PipelineRunStep.step_name.in_(names))))
    if len(steps) != len(names) or target.markdown_artifact_uri != markdown_artifact_ref(target.id):
        _invalid()
    for step in steps:
        payload = {**payloads[step.step_name], "adapter_source": "canonical-project-copy",
            "copied_from_version_id": str(source.id), "target_version_id": str(target.id)}
        step.artifact_payload = payload
        step.artifact_fingerprint = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        step.output_artifact_ref = f"artifact://document_versions/{target.id}/{step.step_name}"
        step.status, step.progress_percent = "completed", 100
        step.completed_at = datetime.now(UTC)
        step.progress_message = "Canonical source artifacts copied into target version"
    session.flush()
