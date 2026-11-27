"""CHG-495 UIRD-API-002: project overview figures for the project list, its status chips and the project header.

Derived status (D495-08): an archived project is `deactivated`; otherwise `processing` while any document
version has an unfinished pipeline run, `published` when at least one document is published, else `draft`.
Chunk count counts the active chunks of currently published versions of live documents.
"""
from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, DocumentVersion, PipelineRun, Project, ProjectOwner, User

ACTIVE_PIPELINE_STATUSES = ("queued", "running", "waiting_action")
DERIVED_STATUSES = ("processing", "published", "draft", "deactivated")


def _processing_exists():
    return (
        select(PipelineRun.id)
        .where(PipelineRun.project_id == Project.id, PipelineRun.status.in_(ACTIVE_PIPELINE_STATUSES),
               PipelineRun.document_version_id.is_not(None))
        .correlate(Project)
        .exists()
    )


def published_document_count_expression():
    return (
        select(func.count(Document.id))
        .where(Document.project_id == Project.id, Document.status == "active", Document.is_deleted.is_(False))
        .correlate(Project)
        .scalar_subquery()
    )


def chunk_count_expression():
    return (
        select(func.count(Chunk.id))
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.project_id == Project.id, Chunk.status == "active", DocumentVersion.status == "active",
               DocumentVersion.published_at.is_not(None), Document.is_deleted.is_(False))
        .correlate(Project)
        .scalar_subquery()
    )


def derived_status_expression():
    published_exists = (
        select(Document.id)
        .where(Document.project_id == Project.id, Document.status == "active", Document.is_deleted.is_(False))
        .correlate(Project)
        .exists()
    )
    return case(
        (Project.status == "archived", "deactivated"),
        (_processing_exists(), "processing"),
        (published_exists, "published"),
        else_="draft",
    )


def owner_name_matches(pattern: str):
    """Owner display name search for the project list (M11), escaped LIKE pattern."""
    return (
        select(ProjectOwner.project_id)
        .join(User, User.id == ProjectOwner.user_id)
        .where(ProjectOwner.project_id == Project.id, User.display_name.ilike(pattern, escape="\\"))
        .correlate(Project)
        .exists()
    )


def project_owners(session: Session, project_ids: Iterable[UUID]) -> dict[UUID, list[dict]]:
    ids = list(project_ids)
    owners: dict[UUID, list[dict]] = {project_id: [] for project_id in ids}
    if not ids:
        return owners
    rows = session.execute(
        select(ProjectOwner.project_id, User.id, User.display_name)
        .join(User, User.id == ProjectOwner.user_id)
        .where(ProjectOwner.project_id.in_(ids))
        .order_by(ProjectOwner.project_id, func.lower(User.display_name), User.id)
    )
    for project_id, user_id, display_name in rows:
        owners[project_id].append({"user_id": user_id, "display_name": display_name})
    return owners


def project_overview(session: Session, project_id: UUID) -> dict:
    """Owners, published documents, chunks and derived status of one project."""
    row = session.execute(
        select(published_document_count_expression(), chunk_count_expression(), derived_status_expression())
        .select_from(Project).where(Project.id == project_id)
    ).one()
    return {
        "owners": project_owners(session, [project_id])[project_id],
        "published_document_count": int(row[0] or 0),
        "chunk_count": int(row[1] or 0),
        "derived_status": row[2],
    }


def status_counts(session: Session, visible_project_ids: Iterable[UUID]) -> dict[str, int]:
    ids = list(visible_project_ids)
    counts = {status: 0 for status in DERIVED_STATUSES}
    published_total = 0
    if ids:
        derived = derived_status_expression().label("derived")
        for status, count in session.execute(
            select(derived, func.count()).select_from(Project).where(Project.id.in_(ids)).group_by(derived)
        ):
            counts[status] = int(count)
        published_total = int(session.scalar(
            select(func.count(Document.id)).join(Project, Project.id == Document.project_id)
            .where(Document.project_id.in_(ids), Project.status == "active", Document.status == "active",
                   Document.is_deleted.is_(False))
        ) or 0)
    return {"total": sum(counts.values()), **counts, "published_document_total": published_total}
