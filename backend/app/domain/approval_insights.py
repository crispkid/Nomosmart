"""CHG-495 UIRD-API-001/003/004: approval figures and version changes for the redesigned screens.

All functions read only; callers apply the existing access checks before calling them.
"""
from __future__ import annotations

import difflib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models import ApprovalTask, Chunk, ChunkReference, ChunkTag, Document, DocumentVersion, DocumentVersionTag, ReviewRecord, Tag
from app.domain.markdown_artifacts import resolve_markdown_artifact

# D495-09: the home card and the workbench flag a pending task once it has waited this long (design rule, not a setting).
PENDING_OVERDUE_HOURS = 48
DECISION_WINDOW = timedelta(days=7)
TEXT_CHANGE_LIMIT = 200
DECIDED = ("approved", "rejected")


def due_at(submitted_at: datetime) -> datetime:
    """CHG-497 DUE497-001: a pending task is due PENDING_OVERDUE_HOURS after it was submitted."""
    return submitted_at + timedelta(hours=PENDING_OVERDUE_HOURS)


def overdue_count(tasks, now: datetime | None = None) -> int:
    limit = (now or datetime.now(UTC)) - timedelta(hours=PENDING_OVERDUE_HOURS)
    return sum(1 for task in tasks if task.submitted_at is not None and task.submitted_at <= limit)


def my_recent_decisions(session: Session, user_id: UUID, now: datetime | None = None) -> tuple[int, float | None]:
    """Tasks the user decided in the last 7 days and their average wait (submitted -> decided)."""
    since = (now or datetime.now(UTC)) - DECISION_WINDOW
    wait = func.extract("epoch", ApprovalTask.completed_at - ApprovalTask.submitted_at)
    count, average = session.execute(
        select(func.count(ApprovalTask.id), func.avg(wait))
        .join(ReviewRecord, and_(ReviewRecord.document_version_id == ApprovalTask.document_version_id,
                                 ReviewRecord.review_stage == ApprovalTask.review_stage,
                                 ReviewRecord.created_at == ApprovalTask.completed_at,
                                 ReviewRecord.status == ApprovalTask.status))
        .where(ReviewRecord.reviewer_id == user_id, ApprovalTask.status.in_(DECIDED), ApprovalTask.completed_at >= since)
    ).one()
    return int(count or 0), (round(float(average), 3) if average is not None else None)


def decision_stats(session: Session, project_ids: set[UUID] | None, date_from: datetime, date_to: datetime) -> dict:
    """Decisions (both review stages) completed in the window, per ISO week (UTC, weeks start on Monday)."""
    conditions = [ApprovalTask.status.in_(DECIDED), ApprovalTask.completed_at >= date_from, ApprovalTask.completed_at <= date_to]
    if project_ids is not None:
        conditions.append(ApprovalTask.project_id.in_(project_ids))
    wait = func.extract("epoch", ApprovalTask.completed_at - ApprovalTask.submitted_at)
    approved, rejected, average = session.execute(
        select(func.count().filter(ApprovalTask.status == "approved"), func.count().filter(ApprovalTask.status == "rejected"),
               func.avg(wait)).where(*conditions)
    ).one()
    week = func.date_trunc("week", func.timezone("UTC", ApprovalTask.completed_at)).label("week")
    by_week = {
        row.week.replace(tzinfo=UTC): (int(row.approved or 0), int(row.rejected or 0))
        for row in session.execute(
            select(week, func.count().filter(ApprovalTask.status == "approved").label("approved"),
                   func.count().filter(ApprovalTask.status == "rejected").label("rejected"))
            .where(*conditions).group_by(week)
        )
    }
    start = _week_start(date_from)
    weekly = []
    while start <= date_to:
        approved_week, rejected_week = by_week.get(start, (0, 0))
        weekly.append({"week_start": start, "approved": approved_week, "rejected": rejected_week})
        start += timedelta(days=7)
    return {
        "completed_count": int(approved or 0) + int(rejected or 0),
        "approved_count": int(approved or 0),
        "rejected_count": int(rejected or 0),
        "average_wait_seconds": round(float(average), 3) if average is not None else None,
        "weekly": weekly,
    }


def _week_start(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    day = value - timedelta(days=value.weekday())
    return day.replace(hour=0, minute=0, second=0, microsecond=0)


def previous_published_version(session: Session, version: DocumentVersion) -> DocumentVersion | None:
    return session.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == version.document_id, DocumentVersion.project_id == version.project_id,
               DocumentVersion.id != version.id, DocumentVersion.published_at.is_not(None))
        .order_by(DocumentVersion.published_at.desc(), DocumentVersion.id.desc())
        .limit(1)
    )


def version_changes(session: Session, task: ApprovalTask) -> dict:
    version = session.get(DocumentVersion, task.document_version_id)
    previous = previous_published_version(session, version) if version is not None else None
    result: dict = {"approval_task_id": task.id, "document_version_id": task.document_version_id,
                    "first_submission": previous is None}
    if version is None or previous is None:
        return result
    result.update(previous_version_id=previous.id, previous_version_label=previous.version_label)
    new_text, old_text = _version_text(session, version), _version_text(session, previous)
    if new_text is not None and old_text is not None:
        changes, added, removed = _line_changes(old_text, new_text)
        result.update(text_status="unchanged" if not changes else "available", lines_added=added, lines_removed=removed,
                      text_changes=changes[:TEXT_CHANGE_LIMIT], text_changes_truncated=len(changes) > TEXT_CHANGE_LIMIT)
    result["tags"] = _name_changes(_tag_names(session, previous.id), _tag_names(session, version.id))
    result["references"] = _name_changes(_reference_names(session, previous.id), _reference_names(session, version.id))
    return result


def _version_text(session: Session, version: DocumentVersion) -> str | None:
    """The version's Markdown; without a Markdown artifact, its active chunks in order (D495-10)."""
    artifact = resolve_markdown_artifact(session, version)
    if artifact.status == "available" and artifact.text is not None:
        return artifact.text
    contents = list(session.scalars(
        select(Chunk.content).where(Chunk.document_version_id == version.id, Chunk.status == "active").order_by(Chunk.chunk_index)
    ))
    return "\n\n".join(contents) if contents else None


def _line_changes(old_text: str, new_text: str) -> tuple[list[dict], int, int]:
    changes: list[dict] = []
    added = removed = 0
    for line in difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("+"):
            added += 1
            changes.append({"op": "added", "text": line[1:]})
        elif line.startswith("-"):
            removed += 1
            changes.append({"op": "removed", "text": line[1:]})
    return changes, added, removed


def _tag_names(session: Session, version_id: UUID) -> set[str]:
    document_tags = select(Tag.name).join(DocumentVersionTag, DocumentVersionTag.tag_id == Tag.id).where(
        DocumentVersionTag.document_version_id == version_id)
    chunk_tags = select(Tag.name).join(ChunkTag, ChunkTag.tag_id == Tag.id).join(Chunk, Chunk.id == ChunkTag.chunk_id).where(
        Chunk.document_version_id == version_id, Chunk.status == "active")
    return set(session.scalars(document_tags.union(chunk_tags)))


def _reference_names(session: Session, version_id: UUID) -> set[str]:
    rows = session.execute(
        select(ChunkReference.normalized_name, Document.title)
        .outerjoin(Document, Document.id == ChunkReference.target_document_id)
        .where(ChunkReference.document_version_id == version_id, ChunkReference.is_deleted.is_(False))
    )
    return {title or name for name, title in rows}


def _name_changes(before: set[str], after: set[str]) -> dict:
    return {"added": sorted(after - before), "removed": sorted(before - after)}
