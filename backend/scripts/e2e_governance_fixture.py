"""Receipt-only governance E2E tooling. Never loads current app configuration.

The old completed-build/fixed-vector provisioner was not ingestion evidence.
Input preparation is available without a Provider. Full governance setup remains
blocked until genuine generation and creation-receipt integration are approved.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from neo4j import GraphDatabase
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import ApprovalTask, DocumentVersion, GraphSyncJob
from app.domain.markdown_structure import MarkdownStructureParser
from app.integrations.s3_storage import S3ClientConfig
from scripts.e2e_run_resources import CleanupConflict, RunJournal, SqlResources, cleanup_run, require
from scripts.e2e_external_resources import GraphResources, IndexResources, ObjectResources


def env(name):
    value = os.environ.get(name)
    require(bool(value), "missing_" + name.lower())
    return value


@contextmanager
def configured_services(kinds):
    # Explicit operator assertion is additional to immutable backend bindings;
    # never infer isolation from a hostname, prefix or current .env file.
    require(env("E2E_ISOLATION") == "fresh-disposable", "disposable_isolation_required")
    require(env("E2E_WRITERS_QUIESCED") == "1", "exclusive_disposable_writers_required")
    with ExitStack() as stack:
        services = {}
        if "sql" in kinds:
            engine = create_engine(env("E2E_DATABASE_URL"), pool_pre_ping=True)
            stack.callback(engine.dispose); services["sql"] = SqlResources(engine)
        if "graph" in kinds:
            driver = GraphDatabase.driver(env("E2E_NEO4J_URI"), auth=(env("E2E_NEO4J_USER"), env("E2E_NEO4J_PASSWORD"))
                if os.environ.get("E2E_NEO4J_AUTH") != "disabled" else None)
            stack.callback(driver.close); services["graph"] = GraphResources(driver, env("E2E_NEO4J_DATABASE"))
        if "index" in kinds:
            auth = (env("E2E_OPENSEARCH_USER"), env("E2E_OPENSEARCH_PASSWORD")) if os.environ.get("E2E_OPENSEARCH_USER") else None
            index = IndexResources(env("E2E_OPENSEARCH_URL"), auth=auth)
            stack.callback(index.http.close); services["index"] = index
        if "object" in kinds:
            objects = ObjectResources(S3ClientConfig(env("E2E_S3_URL"), env("E2E_S3_REGION"), env("E2E_S3_KEY"),
                env("E2E_S3_SECRET"), True), env("E2E_S3_BUCKET"))
            stack.callback(objects.http.close); services["object"] = objects
        yield services


def exact_project(run, project_id):
    projects = [e for e in run.data["resources"] if e["kind"] == "sql" and e["identity"].get("table") == "projects"]
    require(len(projects) == 1 and projects[0]["identity"].get("pk") == {"id": str(project_id)}, "project_not_in_receipt")


def inspect_fixture(run, project_id, services):
    exact_project(run, project_id)
    sql_entries = [e for e in run.data["resources"] if e["kind"] == "sql"]
    # Reading by project never registers workflow-generated rows as owned.
    with services["sql"].prepare(sql_entries):
        with Session(services["sql"].engine) as session:
            versions = list(session.scalars(select(DocumentVersion).where(DocumentVersion.project_id == project_id)))
            require(len(versions) == 1, "single_owned_version_required")
            version = versions[0]
            tasks = list(session.scalars(select(ApprovalTask).where(ApprovalTask.project_id == project_id)))
            job = session.scalar(select(GraphSyncJob).where(GraphSyncJob.project_id == project_id).order_by(GraphSyncJob.created_at.desc()))
            return {"version_status": version.status, "published_at": version.published_at.isoformat() if version.published_at else None,
                "graph_job_status": job.status if job else None,
                "tasks": [{"id": str(t.id), "review_stage": t.review_stage, "status": t.status} for t in tasks]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "setup", "inspect", "cleanup", "prepare-input"))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--project-id", type=UUID)
    parser.add_argument("--peter-email")
    parser.add_argument("--john-email")
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            require(env("E2E_ISOLATION") == "fresh-disposable", "disposable_isolation_required")
            # Exists before setup access/writes. Real creation subsequently binds
            # service identities; this command does not discover/adopt resources.
            with RunJournal(args.manifest, create=True) as run:
                result = {"status": "initialized", "run_id": run.data["run_id"]}
        else:
            with RunJournal(args.manifest) as run:
                if args.project_id is not None: exact_project(run, args.project_id)
                if args.command == "setup":
                    result = {"status": "blocked", "code": "E2E_BLOCKED", "reason": "genuine_generation_and_workflow_receipts_required",
                        "run_id": run.data["run_id"]}
                elif args.command == "prepare-input":
                    require(args.markdown is not None and args.markdown.is_file(), "markdown_input_required")
                    raw = args.markdown.read_text()
                    structure = MarkdownStructureParser().parse(raw)
                    result = {"status": "input_prepared_only", "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                        **structure.as_metadata(), "generation_evidence": False}
                else:
                    kinds = {e["kind"] for e in run.data["resources"]}
                    with configured_services(kinds) as services:
                        if args.command == "cleanup": result = cleanup_run(run, services)
                        else:
                            require(args.project_id is not None and "sql" in services, "project_id_required")
                            result = inspect_fixture(run, args.project_id, services)
        print(json.dumps(result, sort_keys=True))
        return 2 if result.get("status") == "blocked" else 0
    except Exception as exc:
        # No URL, secret, document body, traceback or service response in reports.
        print(json.dumps({"status": "failed", "code": exc.code if isinstance(exc, CleanupConflict) else "e2e_helper_failure"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
