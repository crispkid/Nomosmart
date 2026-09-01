from __future__ import annotations

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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings, neo4j_driver_options
from app.core.encryption import EnvelopeCipher
from app.db.models import (
    AIModel,
    ApprovalRequest,
    Chunk,
    Document,
    DocumentVersion,
    EmbeddingProfile,
    PipelineRun,
    PipelineRunStep,
    Project,
    User,
)
from app.db.session import get_engine
from app.domain.review_publish import (
    LiveNeo4jGraphSyncAdapter,
    LiveOpenSearchPublishedAdapter,
    publish_version,
)

SUPPORTED_LIVE_EMBEDDING_PROVIDERS = {"openai", "vllm", "custom"}


class LiveAcceptanceBlocked(RuntimeError):
    """Raised when live acceptance prerequisites are intentionally unavailable."""


def main() -> int:
    run_id = uuid4()
    settings = None
    original_prefix = None
    index_name: str | None = None
    graph_ids: dict[str, UUID] = {}

    try:
        _assert_env_file_ready()
        settings = get_settings()
        original_prefix = settings.opensearch_index_prefix
        settings.opensearch_index_prefix = f"{original_prefix}-m7-{str(run_id)[:8]}"
        print("milestone7-live: checking PostgreSQL and required schema", flush=True)
        engine = get_engine()
        with Session(engine, expire_on_commit=False) as session:
            session.execute(text("select 1"))
            _assert_required_tables(session)

            print("milestone7-live: publishing controlled fixture through live adapters", flush=True)
            fixture = _seed_publish_fixture(session, run_id, settings=settings)
            graph_ids = {
                "project_id": fixture["project"].id,
                "document_id": fixture["document"].id,
                "version_id": fixture["version"].id,
            }

            manifest, index_result, graph_job = publish_version(
                session=session,
                actor_user_id=fixture["actor"].id,
                document=fixture["document"],
                version=fixture["version"],
                lock_version=1,
                request_id=f"milestone7-live-{run_id}",
                search_adapter=LiveOpenSearchPublishedAdapter(settings),
                graph_adapter=LiveNeo4jGraphSyncAdapter(settings),
            )
            index_name = index_result.index_name

            session.flush()
            assert manifest.index_ready is True
            assert manifest.document_version_id == fixture["version"].id
            assert graph_job.status == "completed"
            assert fixture["version"].status == "active"
            assert fixture["pipeline"].status == "completed"

            _verify_opensearch_documents(settings, index_name, index_result.document_ids)
            _verify_neo4j_graph(settings, fixture["version"].id)

            print(
                json.dumps(
                    {
                        "status": "passed",
                        "run_id": str(run_id),
                        "opensearch_index": index_name,
                        "opensearch_documents": len(index_result.document_ids),
                        "graph_sync_job_id": str(graph_job.id),
                        "manifest_generation": manifest.publication_generation,
                    },
                    sort_keys=True,
                )
            )
            session.rollback()
        return 0
    except LiveAcceptanceBlocked as exc:
        print(f"milestone7-live: blocked: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - command must expose any live acceptance failure
        print(f"milestone7-live: failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if settings is not None and index_name:
            _delete_opensearch_index(settings, index_name)
        if settings is not None and graph_ids:
            _delete_neo4j_fixture(settings, graph_ids)


def _assert_required_tables(session: Session) -> None:
    required = {
        "active_version_manifests",
        "approval_requests",
        "chunks",
        "document_versions",
        "documents",
        "embedding_builds",
        "graph_sync_jobs",
        "pipeline_run_steps",
        "pipeline_runs",
    }
    rows = session.execute(
        text(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'public'
              and table_name = any(:tables)
            """
        ),
        {"tables": list(required)},
    )
    found = {row[0] for row in rows}
    missing = sorted(required - found)
    if missing:
        raise RuntimeError(f"missing required Milestone 7 tables: {', '.join(missing)}")


def _seed_publish_fixture(session: Session, run_id: UUID, *, settings: Settings | None = None) -> dict[str, object]:
    now = datetime.now(UTC)
    actor = User(
        keycloak_user_id=f"milestone7-live-{run_id}",
        display_name="Milestone 7 Live Acceptance",
        auth_source="keycloak",
        is_active=True,
    )
    session.add(actor)
    session.flush()

    model, profile = _resolve_live_embedding_model(session, run_id, settings or get_settings())
    project = Project(
        name=f"Milestone 7 Live {str(run_id)[:8]}",
        description="Temporary live acceptance fixture",
        status="active",
        embedding_model_id=model.id,
        created_by=actor.id,
    )
    if profile is not None:
        session.add(profile)
    session.add(project)
    session.flush()

    document = Document(
        project_id=project.id,
        document_code=f"M7-{str(run_id)[:8]}",
        title="Milestone 7 Live Acceptance Document",
        source_type="file_upload",
        status="inactive",
        is_deleted=False,
        created_by=actor.id,
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
        status="approved",
        chunk_strategy={"mode": "acceptance"},
        embedding_model_id=model.id,
        embedding_profile_id=profile.id if profile is not None else None,
        extraction_artifact_uri=f"opensearch://nomosmart-m7-staging-{str(run_id)[:8]}",
        lock_version=1,
        processed_at=now,
    )
    session.add(version)
    session.flush()

    chunks = [
        Chunk(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_index=1,
            title="Acceptance chunk A",
            content="Milestone 7 live acceptance alpha content.",
            markdown_content="Milestone 7 live acceptance alpha content.",
            content_type="text",
            content_hash="alpha",
            source_mapping=[{"page": 1}],
            embedding_model_id=model.id,
        ),
        Chunk(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_index=2,
            title="Acceptance chunk B",
            content="Milestone 7 live acceptance beta content.",
            markdown_content="Milestone 7 live acceptance beta content.",
            content_type="text",
            content_hash="beta",
            source_mapping=[{"page": 1}],
            embedding_model_id=model.id,
        ),
    ]
    session.add_all(chunks)

    pipeline = PipelineRun(
        project_id=project.id,
        document_id=document.id,
        document_version_id=version.id,
        run_type="document_extraction",
        status="waiting_action",
        progress_percent=100,
        current_step_name="publish",
        current_waiting_role="publisher",
        triggered_by=actor.id,
        created_at=now,
    )
    session.add(pipeline)
    session.flush()
    session.add_all(
        [
            PipelineRunStep(run_id=pipeline.id, step_name="publish", status="waiting_action", progress_percent=0, retry_count=0),
            PipelineRunStep(run_id=pipeline.id, step_name="production_index", status="pending", progress_percent=0, retry_count=0),
            PipelineRunStep(run_id=pipeline.id, step_name="graph_sync", status="pending", progress_percent=0, retry_count=0),
        ]
    )
    session.add(
        ApprovalRequest(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            submitter_id=actor.id,
            owner_user_id=actor.id,
            status="approved",
            submitted_at=now,
            approved_at=now,
            created_at=now,
        )
    )
    session.flush()
    return {"actor": actor, "project": project, "document": document, "version": version, "pipeline": pipeline}


def _resolve_live_embedding_model(session: Session, run_id: UUID, settings: Settings) -> tuple[AIModel, EmbeddingProfile | None]:
    configured = _embedding_model_from_env(session, run_id, settings)
    if configured is not None:
        return configured

    existing = _existing_supported_embedding_model(session)
    if existing is not None:
        model, profile = existing
        print(f"milestone7-live: reusing Embedding model {model.name} ({model.provider})", flush=True)
        return model, profile

    raise LiveAcceptanceBlocked(
        "No supported live Embedding model is configured. Set MILESTONE_LIVE_EMBEDDING_PROVIDER, "
        "MILESTONE_LIVE_EMBEDDING_MODEL, MILESTONE_LIVE_EMBEDDING_API_KEY and, for non-OpenAI providers, "
        "MILESTONE_LIVE_EMBEDDING_ENDPOINT; or configure an active OpenAI/vLLM/custom Embedding model with an encrypted API key."
    )


def _embedding_model_from_env(session: Session, run_id: UUID, settings: Settings) -> tuple[AIModel, EmbeddingProfile | None] | None:
    provided = {
        key: _env(key)
        for key in (
            "MILESTONE_LIVE_EMBEDDING_PROVIDER",
            "MILESTONE_LIVE_EMBEDDING_MODEL",
            "MILESTONE_LIVE_EMBEDDING_ENDPOINT",
            "MILESTONE_LIVE_EMBEDDING_API_KEY",
            "MILESTONE_LIVE_EMBEDDING_DIMENSION",
            "MILESTONE_LIVE_EMBEDDING_DIMENSIONS",
        )
    }
    if not any(provided.values()):
        return None

    provider = _required_env(provided, "MILESTONE_LIVE_EMBEDDING_PROVIDER").lower()
    if provider not in SUPPORTED_LIVE_EMBEDDING_PROVIDERS:
        raise LiveAcceptanceBlocked(f"MILESTONE_LIVE_EMBEDDING_PROVIDER must be one of {sorted(SUPPORTED_LIVE_EMBEDDING_PROVIDERS)}, got {provider!r}")
    model_name = _required_env(provided, "MILESTONE_LIVE_EMBEDDING_MODEL")
    api_key = _required_env(provided, "MILESTONE_LIVE_EMBEDDING_API_KEY")
    endpoint = provided["MILESTONE_LIVE_EMBEDDING_ENDPOINT"] or ("https://api.openai.com/v1" if provider == "openai" else None)
    if not endpoint:
        raise LiveAcceptanceBlocked("MILESTONE_LIVE_EMBEDDING_ENDPOINT is required for vLLM/custom live Embedding providers")

    dimension = _positive_int(provided["MILESTONE_LIVE_EMBEDDING_DIMENSIONS"] or provided["MILESTONE_LIVE_EMBEDDING_DIMENSION"])
    model_id = uuid4()
    config: dict[str, object] = {
        "source": "milestone7-live-env",
        "model_name": model_name,
        "distance_method": "cosine",
        "mapping_version": 1,
    }
    if dimension is not None:
        config["dimensions"] = dimension
    cipher = EnvelopeCipher(settings.encryption_key_bytes)
    model = AIModel(
        id=model_id,
        name=f"Milestone 7 Embedding {str(run_id)[:8]}",
        model_type="Embedding",
        provider=provider,
        endpoint=endpoint,
        api_key_encrypted=cipher.encrypt(api_key, context=f"ai-model:{model_id}"),
        is_active=True,
        is_default=False,
        config=config,
    )
    session.add(model)
    session.flush()
    profile = None
    if dimension is not None:
        profile = EmbeddingProfile(
            model_id=model.id,
            model_version=model_name,
            vector_dimension=dimension,
            distance_method="cosine",
            chunk_strategy={"mode": "acceptance"},
            mapping_version=1,
        )
    print(f"milestone7-live: using env Embedding provider {provider} at {endpoint}", flush=True)
    return model, profile


def _existing_supported_embedding_model(session: Session) -> tuple[AIModel, EmbeddingProfile | None] | None:
    models = list(
        session.scalars(
            select(AIModel)
            .where(AIModel.model_type == "Embedding", AIModel.is_active.is_(True))
            .order_by(AIModel.is_default.desc(), AIModel.updated_at.desc())
        )
    )
    for model in models:
        provider = (model.provider or "").strip().lower()
        if provider not in SUPPORTED_LIVE_EMBEDDING_PROVIDERS:
            continue
        if not model.api_key_encrypted:
            continue
        if provider != "openai" and not (model.endpoint or "").strip():
            continue
        profile = session.scalar(
            select(EmbeddingProfile)
            .where(EmbeddingProfile.model_id == model.id)
            .order_by(EmbeddingProfile.updated_at.desc())
            .limit(1)
        )
        return model, profile
    return None


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _required_env(values: dict[str, str | None], name: str) -> str:
    value = values.get(name)
    if not value:
        raise LiveAcceptanceBlocked(f"{name} is required when configuring a live Embedding provider through environment variables")
    return value


def _positive_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise LiveAcceptanceBlocked("MILESTONE_LIVE_EMBEDDING_DIMENSION(S) must be a positive integer") from exc
    if parsed <= 0:
        raise LiveAcceptanceBlocked("MILESTONE_LIVE_EMBEDDING_DIMENSION(S) must be a positive integer")
    return parsed


def _verify_opensearch_documents(settings, index_name: str, document_ids: list[str]) -> None:
    _opensearch_request(settings, "POST", f"/{index_name}/_refresh", b"")
    for document_id in document_ids:
        payload = _opensearch_request(settings, "GET", f"/{index_name}/_doc/{document_id}", None)
        source = payload.get("_source", {})
        if payload.get("found") is not True or source.get("index_scope") != "published":
            raise RuntimeError(f"published OpenSearch document not verified: {document_id}")


def _delete_opensearch_index(settings, index_name: str) -> None:
    try:
        _opensearch_request(settings, "DELETE", f"/{index_name}", b"", allow_missing=True)
    except Exception as exc:  # noqa: BLE001 - cleanup best effort
        print(f"milestone7-live: cleanup warning: could not delete OpenSearch index {index_name}: {exc}", file=sys.stderr)


def _opensearch_request(settings, method: str, path: str, body: bytes | None, *, allow_missing: bool = False) -> dict:
    base = settings.opensearch_url.rstrip("/")
    context = None if settings.opensearch_verify_tls else ssl._create_unverified_context()  # noqa: SLF001
    request = urllib.request.Request(f"{base}{path}", data=body, method=method)
    request.add_header("content-type", "application/json")
    username = settings.opensearch_username.get_secret_value()
    password = settings.opensearch_password.get_secret_value()
    if username or password:
        token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request.add_header("authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:  # noqa: S310
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        if allow_missing and exc.code == 404:
            return {}
        raise


def _verify_neo4j_graph(settings, version_id: UUID) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username.get_secret_value(), settings.neo4j_password.get_secret_value()),
        **neo4j_driver_options(settings),
    )
    try:
        with driver.session(database=settings.neo4j_database) as session:
            count = session.execute_read(
                lambda tx: tx.run(
                    """
                    MATCH (v:DocumentVersion {id: $version_id})-[:VERSION_HAS_CHUNK]->(c:Chunk)
                    RETURN count(c) AS chunk_count
                    """,
                    version_id=str(version_id),
                ).single()["chunk_count"]
            )
        if count < 2:
            raise RuntimeError(f"Neo4j graph sync did not write expected chunks for {version_id}")
    finally:
        driver.close()


def _delete_neo4j_fixture(settings, graph_ids: dict[str, UUID]) -> None:
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username.get_secret_value(), settings.neo4j_password.get_secret_value()),
            **neo4j_driver_options(settings),
        )
        try:
            with driver.session(database=settings.neo4j_database) as session:
                session.execute_write(
                    lambda tx: tx.run(
                        """
                        MATCH (p:Project {id: $project_id})
                        OPTIONAL MATCH (d:Document {id: $document_id})
                        OPTIONAL MATCH (v:DocumentVersion {id: $version_id})
                        OPTIONAL MATCH (v)-[:VERSION_HAS_CHUNK]->(c:Chunk)
                        DETACH DELETE c, v, d, p
                        """,
                        project_id=str(graph_ids["project_id"]),
                        document_id=str(graph_ids["document_id"]),
                        version_id=str(graph_ids["version_id"]),
                    )
                )
        finally:
            driver.close()
    except Exception as exc:  # noqa: BLE001 - cleanup best effort
        print(f"milestone7-live: cleanup warning: could not delete Neo4j fixture: {exc}", file=sys.stderr)

def _assert_env_file_ready() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    example_path = env_path.with_name(".env.example")
    if not env_path.exists():
        raise RuntimeError(f"missing {env_path}; copy {example_path} and fill operator-owned Development secrets before running live acceptance")
    content = env_path.read_text(encoding="utf-8")
    placeholders = ["<password>", "<secret>", "<64-character-hex-key>"]
    found = [placeholder for placeholder in placeholders if placeholder in content]
    if found:
        raise RuntimeError(f"{env_path} still contains placeholder values from .env.example: {', '.join(found)}")


if __name__ == "__main__":
    raise SystemExit(main())
