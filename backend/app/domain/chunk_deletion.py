"""Candidate-only physical deletion, with retained history/accounting (CHG-295).

The caller owns authorization, the version lock and the transaction. This module
never commits, calls a Provider, or touches an external index. A failed inventory
must not become a best-effort cascade.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Text, cast, or_, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import (
    AIModelUsageEvent, ActiveVersionManifest, ApprovalEvidenceManifest,
    ApprovalRequest, ChatFeedbackEvent, ChatRecord, Chunk, ChunkTag,
    DocumentVersion, EmbeddingBuild, EmbeddingBuildVector, PipelineRun,
    PipelineRunStep, PublicApiRequestLog,
    Tag, ValidationRun, ValidationRunItem,
)
from app.services.audit import add_audit


REFERENCE_FKS = {
    ("chunks", "parent_chunk_id", "chunks"),
    ("chunks", "superseded_by_id", "chunks"),
    ("chunk_tags", "chunk_id", "chunks"),
    ("embedding_build_vectors", "chunk_id", "chunks"),
    ("ai_model_usage_events", "chat_record_id", "chat_records"),
    ("ai_model_usage_events", "validation_run_item_id", "validation_run_items"),
    ("validation_run_items", "chat_record_id", "chat_records"),
    ("validation_run_items", "parent_item_id", "validation_run_items"),
    ("chat_feedback_events", "chat_record_id", "chat_records"),
    ("chunk_tags", "tag_id", "tags"),
    ("document_version_tags", "tag_id", "tags"),
}


def reference_conflict() -> AppError:
    return AppError("chunk_delete_reference_conflict",
                    "Chunk deletion conflicts with retained evidence; reload and try again",
                    status_code=409)


def _require(condition: bool) -> None:
    if not condition:
        raise reference_conflict()


def _locked(session: Session, model, predicate):
    return list(session.scalars(select(model).where(predicate).order_by(model.id)
        .with_for_update().execution_options(populate_existing=True)))


def _mentions(column, ids):
    # Search known JSON evidence fields, not prompts or user content. UUIDs are
    # bound parameters. Unexpected shapes are rejected, not silently overlooked.
    return or_(*(cast(column, Text).contains(str(value)) for value in ids)) if ids else text("false")


def _same_scope(row, version: DocumentVersion) -> bool:
    return (row.project_id == version.project_id and row.document_version_id == version.id
            and getattr(row, "document_id", version.document_id) in (None, version.document_id))


def _only_version(values, version: DocumentVersion) -> bool:
    return isinstance(values, list) and bool(values) and {str(value) for value in values} == {str(version.id)}


def _citations_in_scope(values, version: DocumentVersion) -> bool:
    if not isinstance(values, list):
        return False
    return all(isinstance(value, dict)
        and value.get("document_id", str(version.document_id)) == str(version.document_id)
        and value.get("document_version_id", str(version.id)) == str(version.id)
        and value.get("project_id", str(version.project_id)) == str(version.project_id)
        for value in values)


def _check_fk_inventory(session: Session) -> None:
    # An unhandled future ON DELETE CASCADE must fail closed, not erase new data.
    rows = session.execute(text("""
        SELECT source.relname, attribute.attname, target.relname,
               source.relnamespace = target.relnamespace AS same_namespace,
               cardinality(constraint_row.conkey) = 1 AS single_column,
               target_attribute.attname AS target_column
        FROM pg_constraint constraint_row
        JOIN pg_class source ON source.oid = constraint_row.conrelid
        JOIN pg_class target ON target.oid = constraint_row.confrelid
        JOIN pg_namespace target_namespace ON target_namespace.oid = target.relnamespace
        JOIN pg_attribute attribute ON attribute.attrelid = source.oid
             AND attribute.attnum = ANY(constraint_row.conkey)
        JOIN pg_attribute target_attribute ON target_attribute.attrelid = target.oid
             AND target_attribute.attnum = ANY(constraint_row.confkey)
        WHERE constraint_row.contype = 'f'
          AND target_namespace.nspname = ANY(current_schemas(false))
          AND target.relname IN ('chunks', 'chat_records', 'validation_run_items',
                                 'embedding_build_vectors', 'chunk_tags', 'tags')
    """))
    _require(all(tuple(row[:3]) in REFERENCE_FKS and row.same_namespace
                 and row.single_column and row.target_column == "id" for row in rows))


@dataclass(frozen=True)
class DeletedCandidate:
    tag_ids: tuple[UUID, ...]
    chat_count: int
    validation_item_count: int
    vector_count: int


def delete_candidate_chunk(session: Session, version: DocumentVersion, chunk: Chunk,
                           *, actor_id: UUID, request_id: str | None) -> DeletedCandidate:
    """Inventory all affected evidence before changing any row; caller commits."""
    _require(_same_scope(chunk, version) and chunk.status == "active")
    _require(version.published_at is None)
    _check_fk_inventory(session)
    _require(session.scalar(select(ActiveVersionManifest.id).where(
        ActiveVersionManifest.document_version_id == version.id).limit(1)) is None)
    # Submitted/cancelled/rejected history must be edited via a new candidate.
    _require(session.scalar(select(ApprovalRequest.id).where(
        ApprovalRequest.document_version_id == version.id).limit(1)) is None)

    lineage = _locked(session, Chunk, or_(Chunk.parent_chunk_id == chunk.id, Chunk.superseded_by_id == chunk.id))
    _require(all(_same_scope(row, version) for row in lineage))
    assignments = list(session.scalars(select(ChunkTag).where(ChunkTag.chunk_id == chunk.id).with_for_update()))
    tag_ids = tuple(sorted({row.tag_id for row in assignments}, key=str))
    tags = _locked(session, Tag, Tag.id.in_(tag_ids))
    _require(len(tags) == len(tag_ids) and all(row.project_id == version.project_id for row in tags))
    vectors = _locked(session, EmbeddingBuildVector, EmbeddingBuildVector.chunk_id == chunk.id)
    builds = _locked(session, EmbeddingBuild, EmbeddingBuild.id.in_({row.embedding_build_id for row in vectors}))
    _require(all(_same_scope(row, version) and row.status != "published" for row in builds))
    _require(session.scalar(select(ActiveVersionManifest.id).where(
        ActiveVersionManifest.embedding_build_id.in_({row.id for row in builds})).limit(1)) is None)

    chats = _locked(session, ChatRecord, _mentions(ChatRecord.reference_docs, [chunk.id]))
    for row in chats:
        _require(_same_scope(row, version) and row.scope_mode == "document_staging"
                 and _only_version(row.selected_document_version_ids, version)
                 and _citations_in_scope(row.reference_docs, version)
                 and any(str(ref.get("chunk_id")) == str(chunk.id) for ref in row.reference_docs))
    chat_ids = {row.id for row in chats}
    items = _locked(session, ValidationRunItem, or_(
        _mentions(ValidationRunItem.reference_docs, [chunk.id]), ValidationRunItem.chat_record_id.in_(chat_ids)))
    item_ids = {row.id for row in items}
    children = _locked(session, ValidationRunItem, ValidationRunItem.parent_item_id.in_(item_ids))
    runs = _locked(session, ValidationRun, ValidationRun.id.in_({row.run_id for row in items + children}))
    run_map = {row.id: row for row in runs}
    for run in runs:
        _require(_same_scope(run, version) and run.run_scope == "document_staging"
                 and _only_version(run.selected_document_ids, version)
                 and run.approval_task_id is None
                 and run.status not in {"queued", "pending", "running"})
    for item in items + children:
        _require(item.run_id in run_map and _only_version(item.selected_document_ids, version)
                 and _citations_in_scope(item.reference_docs, version))
        if item.chat_record_id and item.chat_record_id not in chat_ids:
            related = session.get(ChatRecord, item.chat_record_id)
            _require(related is not None and _same_scope(related, version)
                     and related.scope_mode == "document_staging")

    usage = _locked(session, AIModelUsageEvent, or_(AIModelUsageEvent.chat_record_id.in_(chat_ids),
        AIModelUsageEvent.validation_run_item_id.in_(item_ids)))
    for row in usage:
        _require(_same_scope(row, version) and not row.public_api_request_log_id and not row.integration_client_id)
        if row.pipeline_run_id or row.pipeline_step_id:
            linked_step = session.get(PipelineRunStep, row.pipeline_step_id) if row.pipeline_step_id else None
            pipeline_ids = {value for value in (row.pipeline_run_id, linked_step.run_id if linked_step else None) if value}
            _require(not row.pipeline_step_id or linked_step is not None)
            _require(len(pipeline_ids) == 1)
            pipeline = session.get(PipelineRun, next(iter(pipeline_ids)))
            _require(pipeline is not None and _same_scope(pipeline, version))
        if row.validation_run_id:
            linked = session.get(ValidationRun, row.validation_run_id)
            _require(linked is not None and _same_scope(linked, version) and linked.run_scope == "document_staging")
        if row.chat_record_id and row.chat_record_id not in chat_ids:
            linked = session.get(ChatRecord, row.chat_record_id)
            _require(linked is not None and _same_scope(linked, version) and linked.scope_mode == "document_staging")
        if row.validation_run_item_id and row.validation_run_item_id not in item_ids:
            linked_item = session.get(ValidationRunItem, row.validation_run_item_id)
            linked_run = session.get(ValidationRun, linked_item.run_id) if linked_item else None
            _require(linked_run is not None and _same_scope(linked_run, version) and linked_run.run_scope == "document_staging")

    feedback = _locked(session, ChatFeedbackEvent, ChatFeedbackEvent.chat_record_id.in_(chat_ids))
    _require(all(row.project_id == version.project_id and row.source == "ui"
                 and row.public_response_id is None and row.integration_client_id is None for row in feedback))
    deleted_ids = {chunk.id, *chat_ids, *item_ids, *(row.id for row in vectors)}
    _require(session.scalar(select(ApprovalEvidenceManifest.id).where(or_(
        ApprovalEvidenceManifest.document_version_id == version.id,
        _mentions(ApprovalEvidenceManifest.manifest, deleted_ids | {row.id for row in builds}))).limit(1)) is None)
    _require(session.scalar(select(PublicApiRequestLog.id).where(or_(
        _mentions(PublicApiRequestLog.citations, [chunk.id]),
        _mentions(PublicApiRequestLog.selected_document_version_ids, [version.id]),
        _mentions(PublicApiRequestLog.metadata_, deleted_ids))).limit(1)) is None)

    def detach(row, field, deleted):
        old = getattr(row, field)
        if old not in deleted:
            return
        add_audit(session, actor_user_id=actor_id, action="knowledge.chunk.reference.detach",
            resource_type=row.__tablename__, resource_id=row.id, result="success", request_id=request_id,
            summary={"project_id": str(version.project_id), "document_id": str(version.document_id),
                     "document_version_id": str(version.id), "deleted_chunk_id": str(chunk.id),
                     "field": field, "target_id": str(old), "reason": "candidate_chunk_permanent_delete"})
        setattr(row, field, None)

    for row in lineage:
        detach(row, "parent_chunk_id", {chunk.id})
        detach(row, "superseded_by_id", {chunk.id})
    for row in usage:
        detach(row, "chat_record_id", chat_ids)
        detach(row, "validation_run_item_id", item_ids)
    for row in {item.id: item for item in items + children}.values():
        detach(row, "parent_item_id", item_ids)
    session.flush()
    for row in feedback + items:
        session.delete(row)
    session.flush()
    for row in chats + vectors + assignments:
        session.delete(row)
    session.flush()
    session.delete(chunk)
    session.flush()
    for run in runs:
        if not any(item.run_id == run.id for item in items):
            continue
        remaining = list(session.scalars(select(ValidationRunItem).where(
            ValidationRunItem.run_id == run.id, ValidationRunItem.is_current.is_(True))))
        run.total_count = len(remaining)
        run.completed_count = sum(item.status in {"passed", "needs_review", "completed", "skipped"} for item in remaining)
        run.failed_count = sum(item.status in {"failed", "error"} for item in remaining)
    session.flush()
    return DeletedCandidate(tag_ids, len(chats), len(items), len(vectors))
