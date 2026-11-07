"""Project-scoped numbering, held in the caller's document transaction."""
from uuid import UUID

from sqlalchemy import Numeric, case, cast, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Document, Project


def allocate_document_code(session: Session, project_id: UUID) -> str:
    # Acquire before autoflush; a previous allocation in this transaction may
    # still be pending. Never commit here: the new row must keep the same lock.
    with session.no_autoflush:
        status = session.scalar(
            select(Project.status).where(Project.id == project_id).with_for_update()
        )
    if status is None:
        raise AppError("project_not_found", "Project was not found", status_code=404)
    if status != "active":
        raise AppError("project_archived", "Archived projects cannot accept imports", status_code=409)
    session.flush()
    # Numeric (not int64 or lexicographic) also supports existing long codes.
    # CASE prevents casting legacy nonnumeric codes, regardless of query order.
    number = case(
        (Document.document_code.op("~")(r"^DOC-[0-9]+$"),
         cast(func.substr(Document.document_code, 5), Numeric)),
        else_=None,
    )
    highest = session.scalar(
        select(func.max(number)).where(Document.project_id == project_id)
    )
    return f"DOC-{int(highest or 0) + 1:06d}"
