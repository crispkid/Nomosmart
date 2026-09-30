from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AIModel,
    ChatRecord,
    Chunk,
    ChunkTag,
    Document,
    DocumentVersion,
    DocumentVersionTag,
    PipelineRun,
    PipelineRunStep,
    Project,
    ProjectOwner,
    Tag,
    User,
    ValidationRun,
    ValidationRunItem,
)
from app.domain.chunk_artifacts import chunk_artifact_state
from app.domain.embeddings import load_staging_embeddings
from app.domain.chat_citations import citation_persistence_payload
from app.domain.extraction_pipeline import AUTO_EXTRACTION_STEPS


@dataclass(frozen=True)
class SubmissionEvidenceProjection:
    evidence_revision: str
    generated_at: datetime
    next_stage_allowed: bool
    block_reasons: list[str]
    manifest: dict[str, Any]
    summary: dict[str, Any]


def build_submission_evidence(
    session: Session,
    *,
    project: Project,
    document: Document,
    version: DocumentVersion,
) -> SubmissionEvidenceProjection:
    generated_at = datetime.now(UTC)
    pipeline = session.scalar(
        select(PipelineRun)
        .where(
            PipelineRun.project_id == project.id,
            PipelineRun.document_id == document.id,
            PipelineRun.document_version_id == version.id,
        )
        .order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc())
        .limit(1)
    )
    steps = (
        list(
            session.scalars(
                select(PipelineRunStep)
                .where(PipelineRunStep.run_id == pipeline.id)
                .order_by(PipelineRunStep.id)
            )
        )
        if pipeline is not None
        else []
    )
    chunks = list(
        session.scalars(
            select(Chunk)
            .where(Chunk.document_version_id == version.id, Chunk.status == "active")
            .order_by(Chunk.chunk_index, Chunk.id)
        )
    )
    artifact_status, artifacts_ready, _ = chunk_artifact_state(version, len(chunks), session=session)
    embedding = load_staging_embeddings(session, project=project, version=version, chunks=chunks).build if artifacts_ready else None
    graph_preview = dict((version.chunk_strategy or {}).get("graph_preview") or {})
    chat_records = list(
        session.scalars(
            select(ChatRecord)
            .where(
                ChatRecord.document_version_id == version.id,
                ChatRecord.scope_mode == "document_staging",
                ChatRecord.deleted_at.is_(None),
            )
            .order_by(ChatRecord.asked_at, ChatRecord.id)
        )
    )
    validation_runs = list(
        session.scalars(
            select(ValidationRun)
            .where(
                ValidationRun.project_id == project.id,
                ValidationRun.document_version_id == version.id,
                ValidationRun.run_scope == "document_staging",
            )
            .order_by(ValidationRun.created_at, ValidationRun.id)
        )
    )
    validation_items = (
        list(
            session.scalars(
                select(ValidationRunItem)
                .where(ValidationRunItem.run_id.in_([run.id for run in validation_runs]))
                .order_by(ValidationRunItem.created_at, ValidationRunItem.id)
            )
        )
        if validation_runs
        else []
    )
    submitter = session.get(User, document.created_by) if document.created_by else None
    manager = session.get(User, submitter.manager_user_id) if submitter and submitter.manager_user_id else None
    owners = list(
        session.scalars(
            select(User)
            .join(ProjectOwner, ProjectOwner.user_id == User.id)
            .where(ProjectOwner.project_id == project.id, User.is_active.is_(True))
            .order_by(User.display_name, User.id)
        )
    )
    model_ids = {value for value in (version.llm_model_id, version.ocr_model_id, version.embedding_model_id) if value}
    models = {
        str(model.id): {
            "id": str(model.id),
            "name": model.name,
            "type": model.model_type,
            "provider": model.provider,
            "config_version": model.config_version,
        }
        for model in session.scalars(select(AIModel).where(AIModel.id.in_(model_ids)))
    } if model_ids else {}
    tag_ids = set(
        session.scalars(
            select(ChunkTag.tag_id).where(ChunkTag.chunk_id.in_([chunk.id for chunk in chunks]))
        )
    ) if chunks else set()
    tag_ids.update(
        session.scalars(
            select(DocumentVersionTag.tag_id).where(DocumentVersionTag.document_version_id == version.id)
        )
    )
    tag_count = len(tag_ids)
    chunk_tags: dict[UUID, list[dict[str, Any]]] = {}
    if chunks:
        for link, tag in session.execute(
            select(ChunkTag, Tag)
            .join(Tag, Tag.id == ChunkTag.tag_id)
            .where(ChunkTag.chunk_id.in_([chunk.id for chunk in chunks]))
            .order_by(Tag.name, Tag.id)
        ):
            chunk_tags.setdefault(link.chunk_id, []).append(
                {
                    "tag_id": str(tag.id),
                    "name": tag.name,
                    "source": link.source,
                    "confidence": float(link.confidence_score) if link.confidence_score is not None else None,
                }
            )
    block_reasons: list[str] = []
    if project.status != "active":
        block_reasons.append("project_archived")
    if document.is_deleted:
        block_reasons.append("document_deleted")
    if version.status != "submission_ready":
        block_reasons.append("version_not_submission_ready")
    if pipeline is None:
        block_reasons.append("pipeline_missing")
    elif pipeline.status != "submission_ready":
        block_reasons.append("pipeline_not_submission_ready")
    step_status = {step.step_name: step.status for step in steps}
    if pipeline is not None and any(step_status.get(name) != "completed" for name in AUTO_EXTRACTION_STEPS):
        block_reasons.append("pipeline_steps_incomplete")
    if not artifacts_ready:
        block_reasons.append("chunk_artifacts_not_ready")
    if not chunks:
        block_reasons.append("chunks_required")
    if any(not chunk.source_mapping for chunk in chunks):
        block_reasons.append("source_traceability_missing")
    if embedding is None or not artifacts_ready:
        block_reasons.append("staging_index_not_ready")
    if graph_preview.get("status") != "available":
        block_reasons.append("graph_preview_not_ready")
    if any(run.status in {"queued", "running"} for run in validation_runs):
        block_reasons.append("validation_running")
    if any(run.status in {"failed", "partial_failed"} for run in validation_runs):
        block_reasons.append("validation_failed")

    manifest = {
        "schema": "nomosmart.approval-evidence.v1",
        "project": {"id": str(project.id), "generation": project.work_generation, "name": project.name},
        "document": {
            "id": str(document.id),
            "title": document.title,
            "source_type": document.source_type,
            "created_by": str(document.created_by) if document.created_by else None,
            "lock_version": document.lock_version,
        },
        "version": {
            "id": str(version.id),
            "label": version.version_label,
            "status": version.status,
            "lock_version": version.lock_version,
            "content_sha256": version.content_sha256,
            "source_document_id": str(version.source_document_id) if version.source_document_id else None,
            "source_version_id": str(version.source_version_id) if version.source_version_id else None,
            "source_snapshot_created_at": version.source_snapshot_created_at.isoformat() if version.source_snapshot_created_at else None,
            "artifact_refs": {
                "original": version.original_snapshot_uri or version.storage_key,
                "markdown": version.markdown_artifact_uri,
                "extraction": version.extraction_artifact_uri,
            },
        },
        "pipeline": {
            "id": str(pipeline.id) if pipeline else None,
            "status": pipeline.status if pipeline else None,
            "steps": [
                {
                    "id": str(step.id),
                    "name": step.step_name,
                    "status": step.status,
                    "fingerprint": step.artifact_fingerprint,
                    "output_ref": step.output_artifact_ref,
                }
                for step in steps
            ],
        },
        "models": models,
        "chunks": [
            {
                "id": str(chunk.id),
                "lineage_id": str(chunk.lineage_id),
                "parent_chunk_id": str(chunk.parent_chunk_id) if chunk.parent_chunk_id else None,
                "revision": chunk.revision,
                "change_type": chunk.change_type,
                "index": chunk.chunk_index,
                "type": chunk.content_type,
                "title": chunk.title,
                "content": chunk.content,
                "markdown_content": chunk.markdown_content,
                "display_markdown": chunk.display_markdown,
                "content_hash": chunk.content_hash,
                "source_mapping": chunk.source_mapping,
                "confidence": float(chunk.confidence_score) if chunk.confidence_score is not None else None,
                "token_count": chunk.token_count,
                "tags": chunk_tags.get(chunk.id, []),
            }
            for chunk in chunks
        ],
        "graph": {
            "status": graph_preview.get("status"),
            "source": graph_preview.get("source"),
            "node_count": int(graph_preview.get("node_count") or 0),
            "edge_count": int(graph_preview.get("edge_count") or 0),
            "chunk_count": int(graph_preview.get("chunk_count") or 0),
        },
        "conversations": [
            {
                "record_id": str(record.id),
                "conversation_id": str(record.conversation_id),
                "surface": record.scope_mode,
                "document_version_id": str(record.document_version_id) if record.document_version_id else None,
                "conversation_title": record.conversation_title,
                "selected_document_version_ids": record.selected_document_version_ids,
                "question": record.question,
                "answer": record.answer,
                "citations": [citation_persistence_payload(citation) for citation in record.reference_docs or []],
                "evaluation": record.evaluation,
                "revision_suggestion": record.revision_suggestion,
                "created_by": str(record.created_by),
                "asked_at": record.asked_at.isoformat(),
                "answered_at": record.answered_at.isoformat() if record.answered_at else None,
                "content_hash": _hash(
                    {
                        "question": record.question,
                        "answer": record.answer,
                        "citations": [citation_persistence_payload(citation) for citation in record.reference_docs or []],
                        "evaluation": record.evaluation,
                        "revision_suggestion": record.revision_suggestion,
                    }
                ),
            }
            for record in chat_records
        ],
        "validation": {
            "runs": [
                {
                    "id": str(run.id),
                    "status": run.status,
                    "total": run.total_count,
                    "completed": run.completed_count,
                    "failed": run.failed_count,
                    "execution_manifest_hash": run.execution_manifest_hash,
                    "execution_manifest_version": (run.execution_manifest or {}).get(
                        "manifest_version"
                    ),
                    "max_attempts": run.max_attempts,
                }
                for run in validation_runs
            ],
            "items": [
                {
                    "id": str(item.id),
                    "parent_item_id": str(item.parent_item_id) if item.parent_item_id else None,
                    "attempt": item.attempt,
                    "is_current": item.is_current,
                    "input_item_id": str(item.input_item_id),
                    "input_ordinal": item.input_ordinal,
                    "input_content_hash": item.input_content_hash,
                    "run_id": str(item.run_id),
                    "status": item.status,
                    "chat_record_id": str(item.chat_record_id) if item.chat_record_id else None,
                    "question": item.question,
                    "expected_answer": item.expected_answer,
                    "expected_keywords": item.expected_keywords,
                    "selected_document_ids": item.selected_document_ids,
                    "category": item.category,
                    "priority": item.priority,
                    "answer": item.answer,
                    "citations": [citation_persistence_payload(citation) for citation in item.reference_docs or []],
                    "score": float(item.score) if item.score is not None else None,
                    "evaluation_reason": item.evaluation_reason,
                    "error_message": item.error_message,
                    "error_code": item.error_code,
                    "latency_ms": item.latency_ms,
                    "token_usage": item.token_usage,
                    "content_hash": _hash(
                        {
                            "question": item.question,
                            "answer": item.answer,
                            "citations": [citation_persistence_payload(citation) for citation in item.reference_docs or []],
                            "score": float(item.score) if item.score is not None else None,
                            "reason": item.evaluation_reason,
                        }
                    ),
                }
                for item in validation_items
            ],
        },
        "actors": {
            "submitter": _actor(submitter),
            "manager": _actor(manager),
            "owners": [_actor(owner) for owner in owners],
        },
        "artifact_status": artifact_status,
        "block_reasons": sorted(set(block_reasons)),
    }
    evidence_revision = _hash(manifest)
    confidence_values = [float(chunk.confidence_score) for chunk in chunks if chunk.confidence_score is not None]
    summary = {
        "creator": _actor(submitter),
        "manager": _actor(manager),
        "owners": [_actor(owner) for owner in owners],
        "models": models,
        "artifact_status": artifact_status,
        "content_type_counts": {
            kind: sum(1 for chunk in chunks if (chunk.content_type or "text").lower() == kind)
            for kind in ("text", "image", "table", "chart")
        },
        "chunk_count": len(chunks),
        "tag_count": tag_count,
        "average_confidence": round(sum(confidence_values) / len(confidence_values), 5) if confidence_values else None,
        "graph": manifest["graph"],
        "conversation_record_ids": [str(record.id) for record in chat_records],
        "validation_run_ids": [str(run.id) for run in validation_runs],
    }
    return SubmissionEvidenceProjection(
        evidence_revision=evidence_revision,
        generated_at=generated_at,
        next_stage_allowed=not block_reasons,
        block_reasons=sorted(set(block_reasons)),
        manifest=manifest,
        summary=summary,
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _actor(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "user_id": str(user.id),
        "given_name": user.given_name,
        "family_name": user.family_name,
        "display_name": user.display_name,
        "email": user.email,
        "department": user.department,
        "title": user.title,
    }
