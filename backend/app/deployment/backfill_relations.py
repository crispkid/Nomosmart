"""CHG-446 SUPER446-007: add supersede relations to chunks extracted before CHG-446.

Usage (inside the backend container, shell access required): python -m app.deployment.backfill_relations
Safe to repeat: chunks that already have a supersede row for the same name are skipped; reference rows are never
changed. Afterwards unresolved rows are resolved where possible and published reference edges are synchronized.
Prints counts only."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import DocumentVersion, Project
from app.db.session import get_session_factory
from app.domain.chunk_references import backfill_supersedes, resolve_pending_references


def main() -> None:
    factory = get_session_factory()
    totals = {"versions": 0, "added": 0, "resolved": 0, "graph_projects": 0}
    with factory() as session:
        projects = list(session.scalars(select(Project.id).where(Project.status == "active")))
        for project_id in projects:
            versions = session.scalars(select(DocumentVersion).where(DocumentVersion.project_id == project_id,
                DocumentVersion.status.in_(("active", "submission_ready", "awaiting_confirmation", "pending_manager_review",
                                            "pending_owner_review", "approved")))).all()
            added = sum(backfill_supersedes(session, version) for version in versions)
            totals["versions"] += len(versions)
            totals["added"] += added
            totals["resolved"] += resolve_pending_references(session, project_id)
            session.commit()
            if added:
                from app.domain.graph_references import sync_reference_edges
                sync_reference_edges(session, get_settings(), project_id)
                totals["graph_projects"] += 1
    print(json.dumps(totals))


if __name__ == "__main__":
    main()
