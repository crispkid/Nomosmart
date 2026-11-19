"""CHG-442 REF442-003/004: review and correct the textual references found in a document version's chunks.

Same permission and state rules as tag edits: project Owner or Editor, and only while the version is not in
review or published. Removing a reference is a soft delete so rule extraction does not bring it back.
These are not `DocumentReference` (cross-project linked documents, routes/references.py).
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.documents import (_ensure_tag_mutable, _get_active_chunk, _get_scoped_project, _refresh_tag_preview,
                                      _require_tag_edit_permission, _scoped_document_version)
from app.api.schemas import (ChunkReferenceCreatePayload, ChunkReferenceItem, ChunkReferenceListResponse,
                             ChunkReferenceSummary, ChunkReferenceUpdatePayload)
from app.core.errors import AppError
from app.db.session import get_db
from app.db.models import ChunkReference
from app.domain.chunk_references import reference_key, reference_summary, require_target_document, version_reference_rows
from app.security.context import IdentityContext, get_identity_context
from app.security.project_roles import PROJECT_EDITOR_ROLES, has_project_role
from app.services.audit import add_audit

router = APIRouter(prefix="/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunk-references", tags=["chunk-references"])


def _editable(session: Session, project, version, context: IdentityContext) -> bool:
    if project.id not in set(context.visible_project_ids) or not has_project_role(session, project.id, context.user_id, PROJECT_EDITOR_ROLES):
        return False
    return not (version.published_at is not None or version.status in {"active", "inactive", "pending_manager_review",
                                                                        "pending_owner_review", "approved", "publishing"})


def _response(session: Session, project, version, context: IdentityContext) -> ChunkReferenceListResponse:
    items = [ChunkReferenceItem(id=row.id, chunk_id=row.chunk_id, chunk_index=index, raw_text=row.raw_text, start_offset=row.start_offset,
                                end_offset=row.end_offset, normalized_name=row.normalized_name, status=row.status,
                                target_document_id=row.target_document_id, target_title=title, source=row.source,
                                relation_type=row.relation_type, is_deleted=row.is_deleted, lock_version=row.lock_version)
             for row, index, title in version_reference_rows(session, version.id)]
    return ChunkReferenceListResponse(document_version_id=version.id, editable=_editable(session, project, version, context), items=items,
                                      summary=ChunkReferenceSummary(**reference_summary(session, version.id)))


def _mutation_scope(session: Session, project_id: UUID, document_id: UUID, version_id: UUID, context: IdentityContext, action: str):
    project = _get_scoped_project(session, project_id, context)
    _require_tag_edit_permission(session, project.id, context)
    document, version = _scoped_document_version(session, project.id, document_id, version_id)
    _ensure_tag_mutable(session, project, version, action)
    return project, document, version


def _scoped_row(session: Session, version_id: UUID, reference_id: UUID, lock_version: int) -> ChunkReference:
    row = session.scalar(select(ChunkReference).where(ChunkReference.id == reference_id, ChunkReference.document_version_id == version_id,
                                                      ChunkReference.is_deleted.is_(False)).with_for_update())
    if row is None:
        raise AppError("chunk_reference_not_found", "Reference was not found", status_code=404)
    if row.lock_version != lock_version:
        raise AppError("chunk_reference_stale", "Reference was changed by another request", status_code=409)
    return row


@router.get("", response_model=ChunkReferenceListResponse)
def list_chunk_references(project_id: UUID, document_id: UUID, version_id: UUID, context: IdentityContext = Depends(get_identity_context),
                          session: Session = Depends(get_db)) -> ChunkReferenceListResponse:
    project = _get_scoped_project(session, project_id, context)
    _document, version = _scoped_document_version(session, project.id, document_id, version_id)
    return _response(session, project, version, context)


@router.post("", response_model=ChunkReferenceListResponse, status_code=201)
def create_chunk_reference(project_id: UUID, document_id: UUID, version_id: UUID, payload: ChunkReferenceCreatePayload, request: Request,
                           context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ChunkReferenceListResponse:
    project, document, version = _mutation_scope(session, project_id, document_id, version_id, context, "knowledge.chunk_reference.create")
    chunk = _get_active_chunk(session, project.id, document.id, version.id, payload.chunk_id)
    if payload.external and payload.target_document_id is not None:
        raise AppError("chunk_reference_invalid", "Choose a document or mark the reference as external, not both", status_code=422)
    target = require_target_document(session, project.id, document.id, payload.target_document_id) if payload.target_document_id else None
    raw = payload.raw_text.strip()
    key = reference_key(raw)
    if not raw or not key:
        raise AppError("chunk_reference_invalid", "Reference text is empty", status_code=422)
    now = datetime.now(UTC)
    row = ChunkReference(id=uuid4(), project_id=project.id, document_id=document.id, document_version_id=version.id, chunk_id=chunk.id,
                         raw_text=raw, normalized_name=key, status="resolved" if target else "external" if payload.external else "unresolved",
                         target_document_id=target.id if target else None, source="manual", relation_type=payload.relation_type,
                         is_deleted=False, created_by=context.user_id,
                         updated_by=context.user_id, lock_version=1, created_at=now, updated_at=now)
    session.add(row)
    _refresh_tag_preview(session, project, document, version)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.chunk_reference.create", resource_type="chunk", resource_id=chunk.id,
              result="success", request_id=request.state.request_id,
              summary={"reference_id": str(row.id), "status": row.status, "relation_type": row.relation_type,
                       "target_document_id": str(row.target_document_id) if target else None})
    session.commit()
    return _response(session, project, version, context)


@router.patch("/{reference_id}", response_model=ChunkReferenceListResponse)
def update_chunk_reference(project_id: UUID, document_id: UUID, version_id: UUID, reference_id: UUID, payload: ChunkReferenceUpdatePayload,
                           request: Request, context: IdentityContext = Depends(get_identity_context),
                           session: Session = Depends(get_db)) -> ChunkReferenceListResponse:
    project, document, version = _mutation_scope(session, project_id, document_id, version_id, context, "knowledge.chunk_reference.update")
    row = _scoped_row(session, version.id, reference_id, payload.lock_version)
    before = {"status": row.status, "target_document_id": str(row.target_document_id) if row.target_document_id else None}
    if payload.action == "assign":
        if payload.target_document_id is None:
            raise AppError("chunk_reference_invalid", "A target document is required", status_code=422)
        row.target_document_id = require_target_document(session, project.id, document.id, payload.target_document_id).id
        row.status = "resolved"
    else:
        row.status, row.target_document_id = ("external" if payload.action == "external" else "unresolved"), None
    row.updated_by, row.updated_at = context.user_id, datetime.now(UTC)
    row.lock_version += 1
    _refresh_tag_preview(session, project, document, version)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.chunk_reference.update", resource_type="chunk", resource_id=row.chunk_id,
              result="success", request_id=request.state.request_id,
              summary={"reference_id": str(row.id), "before": before, "after": {"status": row.status,
                       "target_document_id": str(row.target_document_id) if row.target_document_id else None}})
    session.commit()
    return _response(session, project, version, context)


@router.delete("/{reference_id}", response_model=ChunkReferenceListResponse)
def remove_chunk_reference(project_id: UUID, document_id: UUID, version_id: UUID, reference_id: UUID, lock_version: int, request: Request,
                           context: IdentityContext = Depends(get_identity_context), session: Session = Depends(get_db)) -> ChunkReferenceListResponse:
    project, document, version = _mutation_scope(session, project_id, document_id, version_id, context, "knowledge.chunk_reference.delete")
    row = _scoped_row(session, version.id, reference_id, lock_version)
    row.is_deleted, row.updated_by, row.updated_at = True, context.user_id, datetime.now(UTC)
    row.lock_version += 1
    _refresh_tag_preview(session, project, document, version)
    add_audit(session, actor_user_id=context.user_id, action="knowledge.chunk_reference.delete", resource_type="chunk", resource_id=row.chunk_id,
              result="success", request_id=request.state.request_id, summary={"reference_id": str(row.id), "raw_text": row.raw_text})
    session.commit()
    return _response(session, project, version, context)
