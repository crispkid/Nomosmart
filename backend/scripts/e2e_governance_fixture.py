from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from base64 import b64encode
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_ROOT)
sys.path.insert(0, str(BACKEND_ROOT))

from neo4j import GraphDatabase
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings, neo4j_driver_options
from app.db.models import (
    AIModel,
    ApprovalTask,
    Chunk,
    Document,
    DocumentVersion,
    EmbeddingBuild,
    EmbeddingBuildVector,
    EmbeddingProfile,
    GraphSyncJob,
    PipelineRun,
    PipelineRunStep,
    Project,
    ProjectMember,
    ProjectOwner,
    Role,
    RolePermission,
    RoleUser,
    User,
)
from app.db.session import get_engine
from app.domain.embeddings import _content_fingerprint, estimated_tokens
from scripts.cleanup_test_data import _collect_scope, _delete_scope


PREFIX = "codex-live-governance-"
PIPELINE_STEPS = (
    "manager_review",
    "owner_review",
    "publish",
    "production_index",
    "graph_sync",
)
EDITOR_GRANTS = (
    ("Menu", "KnowledgeProjects", True, True, False, False),
    ("Project", "ProjectList", True, True, True, False),
    ("Document", "DocumentImport", True, True, True, False),
    ("Document", "DocumentReview", True, True, True, False),
    ("Document", "DocumentVersion", True, True, True, False),
    ("Knowledge", "ChunkEditing", True, True, True, False),
    ("Knowledge", "KnowledgeExtraction", True, True, True, False),
    ("Knowledge", "KnowledgeGraph", True, False, False, False),
    ("Knowledge", "TagManagement", True, True, True, False),
    ("Chat", "ChatVerification", True, False, False, False),
    ("Notification", "NotificationCenter", True, False, True, False),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision isolated live governance E2E data.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    setup = subparsers.add_parser("setup")
    setup.add_argument("--peter-email", required=True)
    setup.add_argument("--john-email", required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--project-id", type=UUID, required=True)
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--project-id", type=UUID, required=True)

    args = parser.parse_args()
    if args.command == "setup":
        result = provision(args.peter_email, args.john_email)
    elif args.command == "inspect":
        result = inspect_fixture(args.project_id)
    else:
        result = cleanup_fixture(args.project_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def provision(peter_email: str, john_email: str) -> dict[str, object]:
    now = datetime.now(UTC)
    suffix = uuid4().hex[:10]
    with Session(get_engine(), expire_on_commit=False) as session:
        peter = _active_user(session, peter_email)
        john = _active_user(session, john_email)
        if john.manager_user_id != peter.id:
            raise RuntimeError("John must report to Peter before governance E2E can run")

        model = AIModel(
            name=f"{PREFIX}embedding-{suffix}",
            model_type="Embedding",
            provider="custom",
            endpoint=None,
            is_active=True,
            is_default=False,
            config={"model_name": f"{PREFIX}embedding-{suffix}", "mapping_version": 1},
            config_version=1,
        )
        session.add(model)
        session.flush()
        profile = EmbeddingProfile(
            model_id=model.id,
            model_version=model.config["model_name"],
            vector_dimension=4,
            distance_method="cosine",
            chunk_strategy={"mode": "live-governance-e2e"},
            mapping_version=1,
        )
        session.add(profile)
        session.flush()

        project = Project(
            name=f"{PREFIX}project-{suffix}",
            description="Disposable live governance acceptance project",
            status="active",
            embedding_model_id=model.id,
            created_by=peter.id,
            lock_version=1,
        )
        session.add(project)
        session.flush()
        editor_role = Role(
            name=f"{PREFIX}role-{project.id}",
            description="Disposable live governance acceptance role",
            is_active=True,
            is_system=False,
            lock_version=1,
        )
        session.add(editor_role)
        session.flush()
        session.add(RoleUser(role_id=editor_role.id, user_id=john.id, source="manual"))
        session.add_all(
            [
                RolePermission(
                    role_id=editor_role.id,
                    module_name=module_name,
                    function_name=function_name,
                    can_view=can_view,
                    can_create=can_create,
                    can_edit=can_edit,
                    can_delete=can_delete,
                )
                for module_name, function_name, can_view, can_create, can_edit, can_delete in EDITOR_GRANTS
            ]
        )
        session.add_all(
            [
                ProjectOwner(project_id=project.id, user_id=peter.id, created_at=now),
                ProjectMember(project_id=project.id, user_id=peter.id, project_role="owner", created_at=now),
                ProjectMember(project_id=project.id, user_id=john.id, project_role="editor", created_at=now),
            ]
        )

        document = Document(
            project_id=project.id,
            document_code=f"{PREFIX}{suffix}",
            title=f"{PREFIX}document-{suffix}",
            source_type="file_upload",
            status="inactive",
            created_by=john.id,
            lock_version=1,
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            project_id=project.id,
            document_id=document.id,
            version_major=1,
            extraction_revision=0,
            version_label="v1.0",
            status="submission_ready",
            original_file_name=f"{PREFIX}{suffix}.md",
            canonical_extension="md",
            mime_type="text/markdown",
            file_size=128,
            chunk_strategy={"mode": "live-governance-e2e"},
            embedding_model_id=model.id,
            embedding_profile_id=profile.id,
            lock_version=1,
            processed_at=now,
        )
        session.add(version)
        session.flush()

        content = "NomoSmart live governance acceptance evidence for manager and owner review."
        chunk = Chunk(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_index=1,
            title=f"{PREFIX}chunk-{suffix}",
            content=content,
            markdown_content=content,
            content_type="text",
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_mapping=[{"page": 1, "anchor": "governance-evidence"}],
            chunk_strategy={"mode": "live-governance-e2e"},
            embedding_model_id=model.id,
            token_count=estimated_tokens(content),
            confidence_score=1,
            status="active",
        )
        session.add(chunk)
        session.flush()

        vector = [0.25, 0.5, 0.75, 1.0]
        vector_checksum = hashlib.sha256(json.dumps(vector, separators=(",", ":")).encode("utf-8")).hexdigest()
        chunk.embedding_vector_ref = f"embedding://profiles/{profile.id}/versions/{version.id}/chunks/{chunk.id}#{vector_checksum}"
        build = EmbeddingBuild(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            embedding_profile_id=profile.id,
            build_revision=1,
            status="completed",
            chunk_count=1,
            checksum=vector_checksum,
            content_fingerprint=_content_fingerprint(model, [chunk], [content]),
            model_id=model.id,
            vector_dimension=4,
            token_count=chunk.token_count,
            usage={"source": "controlled-e2e-fixture"},
            completed_at=now,
        )
        session.add(build)
        session.flush()
        session.add(
            EmbeddingBuildVector(
                embedding_build_id=build.id,
                chunk_id=chunk.id,
                chunk_index=1,
                vector=vector,
                vector_checksum=vector_checksum,
                token_count=chunk.token_count,
                created_at=now,
            )
        )

        pipeline = PipelineRun(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            run_type="document_extraction",
            status="submission_ready",
            progress_percent=100,
            current_step_name="manager_review",
            current_waiting_role="editor",
            triggered_by=john.id,
            started_at=now,
            created_at=now,
        )
        session.add(pipeline)
        session.flush()
        session.add_all(
            [
                PipelineRunStep(
                    run_id=pipeline.id,
                    step_name=step,
                    status="pending",
                    progress_percent=0,
                    retry_count=0,
                )
                for step in PIPELINE_STEPS
            ]
        )
        session.commit()
        return {
            "project_id": str(project.id),
            "document_id": str(document.id),
            "version_id": str(version.id),
            "document_title": document.title,
            "submit_path": f"/project/{project.id}/knowledge/{document.id}/submit-review",
            "knowledge_path": f"/project/{project.id}/knowledge/{document.id}",
            "project_path": f"/project/{project.id}/import",
        }


def inspect_fixture(project_id: UUID) -> dict[str, object]:
    settings = get_settings()
    with Session(get_engine()) as session:
        project = session.get(Project, project_id)
        if project is None or not project.name.startswith(PREFIX):
            raise RuntimeError("Refusing to inspect a project outside the live E2E prefix")
        version = session.scalar(select(DocumentVersion).where(DocumentVersion.project_id == project_id))
        build = session.scalar(select(EmbeddingBuild).where(EmbeddingBuild.project_id == project_id))
        graph_job = session.scalar(select(GraphSyncJob).where(GraphSyncJob.project_id == project_id).order_by(GraphSyncJob.created_at.desc()))
        tasks = list(session.scalars(select(ApprovalTask).where(ApprovalTask.project_id == project_id).order_by(ApprovalTask.created_at)))
        if version is None:
            raise RuntimeError("Fixture document version is missing")
        index_name = build.index_name if build else None
        opensearch_documents = _opensearch_document_count(settings, index_name, project_id) if index_name else 0
        neo4j_nodes = _neo4j_node_count(settings, project_id)
        return {
            "version_status": version.status,
            "published_at": version.published_at.isoformat() if version.published_at else None,
            "index_name": index_name,
            "opensearch_documents": opensearch_documents,
            "graph_job_status": graph_job.status if graph_job else None,
            "neo4j_nodes": neo4j_nodes,
            "tasks": [
                {"id": str(task.id), "review_stage": task.review_stage, "status": task.status}
                for task in tasks
            ],
        }


def cleanup_fixture(project_id: UUID) -> dict[str, object]:
    settings = get_settings()
    with Session(get_engine(), expire_on_commit=False) as session:
        project = session.get(Project, project_id)
        if project is None:
            return {"deleted": False, "reason": "already_missing"}
        if not project.name.startswith(PREFIX):
            raise RuntimeError("Refusing to delete a project outside the live E2E prefix")
        builds = list(session.scalars(select(EmbeddingBuild).where(EmbeddingBuild.project_id == project_id)))
        profile_ids = {build.embedding_profile_id for build in builds}
        index_names = {build.index_name for build in builds if build.index_name}
        for index_name in index_names:
            if not any(str(profile_id)[:8] in index_name for profile_id in profile_ids):
                raise RuntimeError("Refusing to delete an OpenSearch index not tied to the E2E embedding profile")
            _delete_opensearch_index(settings, index_name)
        _delete_neo4j_project(settings, project_id)
        scope = _collect_scope(session, prefixes=(PREFIX,), cutoff=None)
        deleted = _delete_scope(session, scope)
        session.commit()
        return {"deleted": True, "rows": deleted, "indices": sorted(index_names)}


def _active_user(session: Session, email: str) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        raise RuntimeError(f"Active synchronized user not found: {email}")
    return user


def _opensearch_request(settings, method: str, path: str, body: dict[str, object] | None = None):
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{settings.opensearch_url.rstrip('/')}/{path.lstrip('/')}",
        data=payload,
        method=method,
        headers={"content-type": "application/json"},
    )
    username = settings.opensearch_username.get_secret_value()
    password = settings.opensearch_password.get_secret_value()
    if username or password:
        request.add_header("authorization", f"Basic {b64encode(f'{username}:{password}'.encode()).decode()}")
    context = None if settings.opensearch_verify_tls else ssl._create_unverified_context()  # noqa: SLF001
    with urllib.request.urlopen(request, timeout=10, context=context) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8")) if response.length != 0 else {}


def _opensearch_document_count(settings, index_name: str, project_id: UUID) -> int:
    payload = _opensearch_request(settings, "POST", f"{index_name}/_count", {"query": {"term": {"project_id": str(project_id)}}})
    return int(payload.get("count", 0))


def _delete_opensearch_index(settings, index_name: str) -> None:
    try:
        _opensearch_request(settings, "DELETE", index_name)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise


def _neo4j_node_count(settings, project_id: UUID) -> int:
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username.get_secret_value(), settings.neo4j_password.get_secret_value()),
        **neo4j_driver_options(settings),
    )
    try:
        with driver.session(database=settings.neo4j_database) as session:
            record = session.run("MATCH (p:Project {id: $id}) OPTIONAL MATCH (p)-[*0..3]-(n) RETURN count(DISTINCT n) AS count", id=str(project_id)).single()
            return int(record["count"] if record else 0)
    finally:
        driver.close()


def _delete_neo4j_project(settings, project_id: UUID) -> None:
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username.get_secret_value(), settings.neo4j_password.get_secret_value()),
        **neo4j_driver_options(settings),
    )
    try:
        with driver.session(database=settings.neo4j_database) as session:
            session.run(
                "MATCH (p:Project {id: $id}) OPTIONAL MATCH (p)-[*0..3]-(n) "
                "WITH p, collect(DISTINCT n) AS related WITH [p] + related AS nodes "
                "UNWIND nodes AS node DETACH DELETE node",
                id=str(project_id),
            ).consume()
    finally:
        driver.close()


if __name__ == "__main__":
    raise SystemExit(main())
