"""Explicitly scoped graph-only compare/apply. Default operation is read-only."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Document, DocumentVersion, GraphSyncJob, Project
from app.domain.graph_projection import build_graph_projection, digest
from app.domain.graph_reconciliation import Neo4jProjectionStore, locked_projection, synchronize_graph
from app.services.audit import add_audit


def environment_digest(settings) -> str:
    url = make_url(settings.database_url.get_secret_value())
    return digest({"environment": settings.app_env, "database": {"driver": url.drivername,
        "host": url.host, "port": url.port, "database": url.database,
        "options": url.query.get("options")},
        "neo4j_uri": settings.neo4j_uri, "neo4j_database": settings.neo4j_database})


def reconcile_scope(session, settings, *, project_id, document_id, version_id, apply=False,
                    expected_source=None, expected_target=None, expected_environment=None, reason=None) -> dict:
    environment = environment_digest(settings)
    if apply:
        if not all((expected_source, expected_target, expected_environment, reason)) or expected_environment != environment:
            raise AppError("graph_repair_binding_required", "Apply requires matching environment/source/target bindings and a reason", status_code=409)
        projection = locked_projection(session, project_id, document_id, version_id)
        if projection.source_digest != expected_source:
            raise AppError("graph_source_changed", "Graph source changed since comparison", status_code=409)
    else:
        project, document, version = session.get(Project, project_id), session.get(Document, document_id), session.get(DocumentVersion, version_id)
        if project is None or document is None or version is None or project.status != "active" or document.is_deleted or document.status != "active" or version.published_at is None:
            raise AppError("graph_scope_inactive", "A published active document scope is required", status_code=409)
        projection = build_graph_projection(session, project, document, version)
    store = Neo4jProjectionStore(settings)
    before = store.read(projection)
    report = {"mode": "compare", "environment": settings.app_env, "environment_digest": environment, **before.report(projection)}
    if not apply:
        return report
    if before.target_digest != expected_target:
        raise AppError("graph_target_changed", "Graph changed since comparison", status_code=409)
    if before.matches(projection):
        return {**report, "mode": "apply", "changed": False}
    after = synchronize_graph(session, settings, project_id, document_id, version_id,
        expected_binding=projection.binding(), target_digest=expected_target, tags_only=True)
    now = datetime.now(UTC)
    job = GraphSyncJob(project_id=project_id, document_id=document_id, document_version_id=version_id,
        project_generation=projection.project_generation, trigger_type="manual_tag_repair", status="completed",
        node_count=len(after.graph["nodes"]), edge_count=len(after.graph["edges"]), created_at=now, completed_at=now)
    session.add(job)
    session.flush()
    add_audit(session, actor_user_id=None, action="graph.tags.repair", resource_type="graph_sync_job", resource_id=job.id,
        result="success", request_id=None, summary={"source_digest": projection.source_digest,
        "before_digest": before.target_digest, "after_digest": after.target_digest, "reason": str(reason)[:500]})
    return {**after.report(projection), "mode": "apply", "changed": True, "environment_digest": environment}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=("development", "test", "production"))
    for name in ("project", "document", "version"):
        parser.add_argument(f"--{name}-id", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-source")
    parser.add_argument("--expected-target")
    parser.add_argument("--expected-environment")
    parser.add_argument("--reason")
    args = parser.parse_args()
    settings = get_settings()
    if settings.app_env != args.environment:
        print(json.dumps({"error": "graph_environment_mismatch"}))
        return 2
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with Session(engine) as session:
            if not args.apply:
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            report = reconcile_scope(session, settings, project_id=args.project_id, document_id=args.document_id,
                version_id=args.version_id, apply=args.apply, expected_source=args.expected_source,
                expected_target=args.expected_target, expected_environment=args.expected_environment, reason=args.reason)
            if args.apply:
                session.commit()
            else:
                session.rollback()
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0
    except AppError as exc:
        print(json.dumps({"error": exc.code}))
        return 2
    except Exception:
        # Never print DSNs, driver errors, parameters or source content.
        print(json.dumps({"error": "graph_reconciliation_failed"}))
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
