"""Real disposable PostgreSQL/Neo4j tests; no fake service or provider adapters.

Set CHG292_DATABASE_URL and NEO4J_URI to isolated services. Never point this suite
at a current application database. Each run uses a random PostgreSQL schema and
deletes only the explicit graph identities it created.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import subprocess
import unittest
from uuid import uuid4
import urllib.request
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (ActiveVersionManifest, AIModel, Chunk, ChunkTag, Document, DocumentVersion,
    DocumentVersionTag, EmbeddingProfile, GraphSyncJob, NotificationEvent, OutboxEvent, Project, ProjectOwner, Role, RolePermission, RoleUser, Tag, User)
from app.domain.graph_projection import build_graph_projection, digest, graph_difference, preview_artifact
from app.domain.graph_reconciliation import Neo4jProjectionStore, locked_projection, synchronize_graph


class TagGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("CHG292_DATABASE_URL") or not os.environ.get("NEO4J_URI"):
            raise RuntimeError("CHG292_DATABASE_URL and NEO4J_URI must identify disposable real services")
        cls.schema = "chg292_" + uuid4().hex
        cls.admin = create_engine(os.environ["CHG292_DATABASE_URL"])
        with cls.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(os.environ["CHG292_DATABASE_URL"], connect_args={"options": f"-csearch_path={cls.schema}"})
        cls.addClassCleanup(cls.cleanup_database)
        # Use the repository's real schema/migrations, not ORM-generated DDL
        # (its historical duplicate index names are unrelated to this change).
        migrations = Path(os.environ["CHG292_MIGRATIONS_PATH"])
        with cls.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for migration in sorted(migrations.glob("V*.sql")):
                if int(migration.name.split("__", 1)[0][1:]) > int(os.environ.get("CHG292_MAX_MIGRATION", "48")):
                    continue
                if migration.name.startswith("V042__"):
                    continue  # CloudNativePG role/database grants, not table DDL.
                with connection.connection.cursor() as cursor:
                    cursor.execute(migration.read_text())
        cls.settings = Settings(_env_file=None, app_env="test", neo4j_uri=os.environ["NEO4J_URI"],
            neo4j_username="", neo4j_password="", database_url=os.environ["CHG292_DATABASE_URL"],
            opensearch_url=os.environ["CHG292_OPENSEARCH_URL"], opensearch_username="", opensearch_password="",
            opensearch_index_prefix=cls.schema.replace("_", "-"))
        cls.store = Neo4jProjectionStore(cls.settings)
        cls.created_ids: set[str] = set()

    @classmethod
    def tearDownClass(cls):
        with cls.store.connection() as graph:
            graph.run("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=sorted(cls.created_ids)).consume()

    @classmethod
    def cleanup_database(cls):
        cls.engine.dispose()
        with cls.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))
        cls.admin.dispose()

    def setUp(self):
        self.session = Session(self.engine, expire_on_commit=False, autoflush=False)
        self.project = Project(name="CHG292 isolated", status="active")
        self.session.add(self.project)
        self.session.flush()
        self.document = Document(project_id=self.project.id, document_code=uuid4().hex, title="Graph evidence", source_type="upload", status="active")
        self.session.add(self.document)
        self.session.flush()
        self.version = DocumentVersion(project_id=self.project.id, document_id=self.document.id,
            version_major=1, extraction_revision=1, version_label="v1.1", status="active", published_at=datetime.now(UTC))
        self.session.add(self.version)
        self.session.flush()
        self.chunks = [Chunk(project_id=self.project.id, document_id=self.document.id, document_version_id=self.version.id,
            chunk_index=i, title=f"Chunk {i}", content="Do not copy this body into the graph", content_hash=digest(i),
            markdown_content="**Original**", display_markdown="**Original**", retrieval_text="Original") for i in (1, 2)]
        self.tag = Tag(project_id=self.project.id, name="Same canonical tag", created_at=datetime.now(UTC))
        self.session.add_all([*self.chunks, self.tag])
        self.session.flush()
        self.session.add(DocumentVersionTag(document_version_id=self.version.id, tag_id=self.tag.id,
            source="manual", created_at=datetime.now(UTC)))
        self.session.add(ChunkTag(chunk_id=self.chunks[0].id, tag_id=self.tag.id, source="llm",
            confidence_score=.8, metadata_={"model_id": "test-model-reference", "api_key": "NEVER-PROJECT", "prompt": "NEVER-PROJECT"},
            created_at=datetime.now(UTC)))
        self.session.commit()
        self.created_ids.update(str(x.id) for x in [self.project, self.document, self.version, self.tag, *self.chunks])

    def tearDown(self):
        self.session.close()

    def embedding_build(self, version, chunks):
        """Preloaded isolated numeric data tests indexing, NOT Provider quality."""
        from app.domain.embeddings import _content_fingerprint, _persist_embedding_build, embedding_content_hash
        model = self.session.get(AIModel, self.project.embedding_model_id) if self.project.embedding_model_id else None
        if model is None:
            model = AIModel(name=uuid4().hex, model_type="Embedding", provider="custom", config={"dimensions": 3})
            self.session.add(model); self.session.flush()
            self.project.embedding_model_id = model.id
        profile = self.session.scalar(select(EmbeddingProfile).where(EmbeddingProfile.model_id == model.id))
        if profile is None:
            profile = EmbeddingProfile(model_id=model.id, model_version=model.name, vector_dimension=3,
                distance_method="cosine", chunk_strategy={}, mapping_version=2)
            self.session.add(profile); self.session.flush()
        version.embedding_profile_id = profile.id; version.embedding_model_id = model.id
        for chunk in chunks:
            chunk.chunk_strategy = {"parser_version": "test-parse", "chunker_version": "test-chunk",
                "normalizer_version": "test-normalize", "tokenizer_version": "test-token"}
            chunk.embedding_model_id = model.id
            chunk.embedding_content_hash = embedding_content_hash(retrieval_text=chunk.retrieval_text,
                embedding_model=str(model.id), embedding_model_version=model.name, embedding_dimension=3,
                normalizer_version="test-normalize", tokenizer_version="test-token")
        texts = [chunk.retrieval_text for chunk in chunks]
        return _persist_embedding_build(self.session, model, profile, version, chunks, texts,
            [[float(i + 1), .25, .75] for i in range(len(chunks))], _content_fingerprint(model, chunks, texts), {})

    def owner(self):
        user = User(keycloak_user_id=uuid4().hex, display_name="Isolated graph owner")
        self.session.add(user); self.session.flush()
        self.session.add(ProjectOwner(project_id=self.project.id, user_id=user.id, created_at=datetime.now(UTC)))
        self.session.commit()
        return user

    def publish(self, version, chunks, owner):
        from app.domain.review_publish import LiveNeo4jGraphSyncAdapter, LiveOpenSearchPublishedAdapter, publish_version
        build = self.embedding_build(version, chunks)
        self.session.commit()
        self.addCleanup(self.delete_index, build.embedding_profile_id)
        result = publish_version(session=self.session, actor_user_id=owner.id, document=self.document,
            version=version, lock_version=version.lock_version, request_id=None,
            search_adapter=LiveOpenSearchPublishedAdapter(self.settings), graph_adapter=LiveNeo4jGraphSyncAdapter(self.settings))
        self.session.commit()
        return result

    def delete_index(self, profile_id):
        from app.domain.review_publish import published_index_name
        url = f"{self.settings.opensearch_url}/{published_index_name(self.settings.opensearch_index_prefix, profile_id)}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=10):
                pass
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise

    def authenticated_client(self):
        """Real Keycloak password grant/JWKS and real app dependencies; no overrides."""
        from fastapi.testclient import TestClient
        from app.core.config import get_settings
        from app.db.session import get_engine
        from app.security.auth import JWTValidator
        base = os.environ["CHG292_KEYCLOAK_URL"].rstrip("/")
        def request(path, data=None, token=None, method="POST", form=False):
            headers = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode() if data is not None else None
            with urllib.request.urlopen(urllib.request.Request(base + path, data=body, headers=headers, method=method), timeout=20) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        admin = request("/realms/master/protocol/openid-connect/token", form=True,
            data={"grant_type": "password", "client_id": "admin-cli", "username": os.environ["CHG292_KEYCLOAK_ADMIN"],
                  "password": os.environ["CHG292_KEYCLOAK_PASSWORD"]})["access_token"]
        realm, password = "chg292-" + uuid4().hex, uuid4().hex
        request("/admin/realms", token=admin, data={"realm": realm, "enabled": True,
            "clients": [{"clientId": "graph-test", "publicClient": True, "directAccessGrantsEnabled": True,
                "protocolMappers": [{"name": "aud", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
                    "config": {"included.custom.audience": "graph-test", "access.token.claim": "true"}}]}],
            "users": [{"username": "graph-user", "enabled": True, "emailVerified": True, "email": "graph@example.invalid",
                "firstName": "Graph", "lastName": "Test", "credentials": [{"type": "password", "value": password, "temporary": False}]}]})
        self.addCleanup(request, "/admin/realms/" + realm, token=admin, method="DELETE")
        issuer = base + "/realms/" + realm
        token = request(f"/realms/{realm}/protocol/openid-connect/token", form=True,
            data={"grant_type": "password", "client_id": "graph-test", "username": "graph-user", "password": password})["access_token"]
        db_url = self.admin.url.update_query_dict({"options": f"-csearch_path={self.schema}"}).render_as_string(hide_password=False)
        previous_env = {key: os.environ.get(key) for key in ("DATABASE_URL", "OIDC_ISSUER_URL", "OIDC_AUDIENCE")}
        os.environ.update(DATABASE_URL=db_url, OIDC_ISSUER_URL=issuer, OIDC_AUDIENCE="graph-test")
        def reset_settings():
            get_engine().dispose(); get_engine.cache_clear(); get_settings.cache_clear()
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.addCleanup(reset_settings)
        get_engine.cache_clear(); get_settings.cache_clear()
        settings = self.settings.model_copy(update={"oidc_issuer_url": issuer, "oidc_audience": "graph-test", "log_level": "ERROR"})
        principal = JWTValidator(settings).validate(token)
        user = User(keycloak_user_id=principal.subject, display_name="Authenticated isolated owner")
        role = Role(name="chg292-" + uuid4().hex)
        self.session.add_all([user, role]); self.session.flush()
        self.session.add_all([ProjectOwner(project_id=self.project.id, user_id=user.id, created_at=datetime.now(UTC)),
            RoleUser(role_id=role.id, user_id=user.id, source="manual"),
            RolePermission(role_id=role.id, module_name="Menu", function_name="KnowledgeProjects", can_view=True)])
        self.session.commit()
        from app.main import create_app
        client = TestClient(create_app(settings), headers={"Authorization": "Bearer " + token})
        self.addCleanup(client.close)
        return client, user

    def projection(self):
        return build_graph_projection(self.session, self.project, self.document, self.version)

    def sync(self):
        result = synchronize_graph(self.session, self.settings, self.project.id, self.document.id, self.version.id)
        self.session.commit()
        return result

    def query(self, statement, **params):
        with self.store.connection() as graph:
            return [dict(row) for row in graph.run(statement, **params)]

    def test_shared_identity_provenance_and_preview(self):
        projection = self.projection()
        self.assertEqual(len(projection.graph["nodes"]), 6)
        self.assertEqual(len(projection.graph["edges"]), 6)
        encoded = json.dumps(projection.graph)
        self.assertNotIn("NEVER-PROJECT", encoded)
        self.assertNotIn(self.chunks[0].content, encoded)
        assignments = [e for e in projection.graph["edges"] if e["type"].endswith("HAS_TAG")]
        self.assertEqual({e["properties"]["source"] for e in assignments}, {"manual", "llm"})
        preview = preview_artifact(projection)
        self.assertEqual([n["id"] for n in preview["nodes"] if n["type"] == "tag"], [f"tag:{self.tag.id}"])
        self.assertEqual(preview["edge_count"], 6)

    def test_publish_adapter_and_idempotent_readback(self):
        from app.domain.review_publish import LiveNeo4jGraphSyncAdapter
        result = LiveNeo4jGraphSyncAdapter(self.settings).sync_active_version(session=self.session,
            project_id=self.project.id, document=self.document, version=self.version, chunks=self.chunks)
        self.session.commit()
        self.assertEqual((result.node_count, result.edge_count), (6, 6))
        first = self.store.read(self.projection())
        self.assertTrue(first.matches(self.projection()))
        self.assertEqual(first.target_digest, self.sync().target_digest)

    def test_empty_tags_do_not_copy_document_tags(self):
        self.session.delete(self.session.get(ChunkTag, (self.chunks[0].id, self.tag.id)))
        self.session.commit()
        result = self.sync()
        self.assertEqual(sum(e["type"] == "CHUNK_HAS_TAG" for e in result.graph["edges"]), 0)
        self.session.delete(self.session.get(DocumentVersionTag, (self.version.id, self.tag.id)))
        self.session.commit()
        result = self.sync()
        self.assertEqual(sum(n["type"] == "Tag" for n in result.graph["nodes"]), 0)

    def test_same_name_cross_project_not_merged(self):
        self.sync()
        other = Project(name="Another isolated Project", status="active")
        self.session.add(other); self.session.flush()
        other_tag = Tag(project_id=other.id, name=self.tag.name, created_at=datetime.now(UTC))
        self.session.add(other_tag); self.session.commit()
        self.assertNotEqual(other_tag.id, self.tag.id)
        self.session.add(ChunkTag(chunk_id=self.chunks[1].id, tag_id=other_tag.id, source="manual", created_at=datetime.now(UTC)))
        self.session.commit()
        with self.assertRaises(AppError) as error:
            self.projection()
        self.assertEqual(error.exception.code, "graph_scope_mismatch")

    def test_obsolete_edge_only_shared_tag_and_unknown_edge_preserved(self):
        self.sync()
        self.query("MATCH (a:Chunk {id:$a}), (b:Chunk {id:$b}), (t:Tag {id:$t}) "
            "MERGE (a)-[:UNRELATED_TEST_EDGE]->(b) MERGE (b)-[:CHUNK_HAS_TAG]->(t)",
            a=str(self.chunks[0].id), b=str(self.chunks[1].id), t=str(self.tag.id))
        before = self.store.read(self.projection())
        self.assertFalse(before.matches(self.projection()))
        self.sync()
        rows = self.query("MATCH (a:Chunk {id:$a})-[r:UNRELATED_TEST_EDGE]->() RETURN count(r) AS n", a=str(self.chunks[0].id))
        self.assertEqual(rows[0]["n"], 1)
        self.assertTrue(self.store.read(self.projection()).matches(self.projection()))

    def test_target_drift_rolls_back_without_mutation(self):
        self.sync()
        before = self.store.read(self.projection())
        self.query("MATCH (:Chunk {id:$id})-[r:CHUNK_HAS_TAG]->() DELETE r", id=str(self.chunks[0].id))
        drifted = self.store.read(self.projection())
        with self.assertRaises(AppError) as error:
            self.store.reconcile(self.projection(), target_digest=before.target_digest)
        self.assertEqual(error.exception.code, "graph_target_changed")
        self.assertEqual(self.store.read(self.projection()).target_digest, drifted.target_digest)

    def test_real_transaction_rolls_back_structure_conflict(self):
        self.sync()
        extra = str(uuid4()); self.created_ids.add(extra)
        self.query("MATCH (v:DocumentVersion {id:$id}) CREATE (c:Chunk {id:$extra}) MERGE (v)-[:VERSION_HAS_CHUNK]->(c)", id=str(self.version.id), extra=extra)
        before = self.store.read(self.projection())
        with self.assertRaises(AppError):
            self.store.reconcile(self.projection())
        self.assertEqual(before.target_digest, self.store.read(self.projection()).target_digest)

    def test_missing_edge_formal_read_fails_not_postgres_enriched(self):
        from app.api.routes.serving import _project_graph_without_chunk_content
        self.sync()
        graph = _project_graph_without_chunk_content(self.session, self.project, {self.version.id}, 120)
        self.assertEqual(len([n for n in graph.nodes if n.type == "Tag"]), 1)
        self.query("MATCH (:Chunk {id:$id})-[r:CHUNK_HAS_TAG]->() DELETE r", id=str(self.chunks[0].id))
        with self.assertRaises(AppError) as error:
            _project_graph_without_chunk_content(self.session, self.project, {self.version.id}, 120)
        self.assertEqual(error.exception.code, "graph_projection_not_ready")

    def test_candidate_preview_refresh_and_published_guard(self):
        from app.api.routes.documents import _ensure_tag_mutable, _refresh_tag_preview
        from app.api.routes.serving import _project_graph_without_chunk_content
        with self.assertRaises(AppError) as error:
            _ensure_tag_mutable(self.session, self.project, self.version, "test")
        self.assertEqual(error.exception.code, "published_tag_revision_required")
        # Directly seed a separate candidate state in disposable test data.
        self.version.published_at = None; self.version.status = "submission_ready"
        self.session.commit()
        _ensure_tag_mutable(self.session, self.project, self.version, "test")
        _refresh_tag_preview(self.session, self.project, self.document, self.version)
        self.session.commit()
        self.assertEqual(self.version.chunk_strategy["graph_preview"]["tag_revision"], 1)
        graph = _project_graph_without_chunk_content(self.session, self.project, {self.version.id}, 120, allow_preview=True)
        self.assertEqual(len(graph.nodes), 6)
        self.assertEqual(len(self.store.read(self.projection()).graph["nodes"]), 0)
        self.version.status = "approved"; self.session.commit()
        with self.assertRaises(AppError) as error:
            _ensure_tag_mutable(self.session, self.project, self.version, "test")
        self.assertEqual(error.exception.code, "document_version_review_locked")

    def test_durable_worker_binding_success_and_stale_failure(self):
        from app.domain.graph_sync_jobs import enqueue_graph_sync, execute_graph_sync_job
        kwargs = dict(project_id=self.project.id, document_id=self.document.id, document_version_id=self.version.id,
            trigger_type="manual_retry", requested_by_user_id=None, request_id=None)
        job = enqueue_graph_sync(self.session, **kwargs); self.session.commit()
        execute_graph_sync_job(self.session, settings=self.settings, job_id=job.id)
        self.session.refresh(job)
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.edge_count, 6)
        stale = enqueue_graph_sync(self.session, **kwargs); self.session.commit()
        self.version.lock_version += 1; self.session.commit()
        execute_graph_sync_job(self.session, settings=self.settings, job_id=stale.id)
        self.session.refresh(stale)
        self.assertEqual(stale.status, "failed")
        self.assertEqual(stale.error_code, "graph_source_changed")

    def test_concurrent_real_sessions_same_scope(self):
        self.session.commit()
        def run():
            with Session(self.engine, autoflush=False) as session:
                result = synchronize_graph(session, self.settings, self.project.id, self.document.id, self.version.id)
                session.commit()
                return result.target_digest
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: run(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertTrue(self.store.read(self.projection()).matches(self.projection()))

    def test_graph_only_compare_apply_noop_and_bindings(self):
        from scripts.chg292_graph_tag_reconcile import reconcile_scope
        self.sync()
        self.query("MATCH (:Chunk {id:$id})-[r:CHUNK_HAS_TAG]->() DELETE r", id=str(self.chunks[0].id))
        scope = dict(project_id=self.project.id, document_id=self.document.id, version_id=self.version.id)
        source = self.projection().source_digest
        report = reconcile_scope(self.session, self.settings, **scope)
        self.assertNotIn(self.tag.name, json.dumps(report))
        with self.assertRaises(AppError):
            reconcile_scope(self.session, self.settings, **scope, apply=True)
        options = dict(apply=True, expected_source=report["source_digest"], expected_target=report["target_digest"],
            expected_environment=report["environment_digest"], reason="isolated verification")
        applied = reconcile_scope(self.session, self.settings, **scope, **options); self.session.commit()
        self.assertTrue(applied["ready"])
        self.assertEqual(source, self.projection().source_digest)
        report = reconcile_scope(self.session, self.settings, **scope)
        options["expected_target"] = report["target_digest"]
        self.assertFalse(reconcile_scope(self.session, self.settings, **scope, **options)["changed"])
        self.assertEqual(len(list(self.session.scalars(select(GraphSyncJob).where(GraphSyncJob.document_version_id == self.version.id)))), 1)

    def test_operator_cli_compares_readonly_and_applies_only_bound_scope(self):
        self.sync()
        self.query("MATCH (:Chunk {id:$id})-[r:CHUNK_HAS_TAG]->() DELETE r", id=str(self.chunks[0].id))
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/chg292_graph_tag_reconcile.py"),
            "--environment", "test", "--project-id", str(self.project.id), "--document-id", str(self.document.id),
            "--version-id", str(self.version.id)]
        env = {**os.environ, "DATABASE_URL": self.admin.url.update_query_dict({"options": f"-csearch_path={self.schema}"}).render_as_string(hide_password=False)}
        before = self.store.read(self.projection()).target_digest
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ready"])
        self.assertNotIn(self.tag.name, result.stdout)
        self.assertEqual(before, self.store.read(self.projection()).target_digest)
        denied = subprocess.run([*command, "--apply"], env=env, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(denied.returncode, 2)
        apply = subprocess.run([*command, "--apply", "--expected-source", report["source_digest"],
            "--expected-target", report["target_digest"], "--expected-environment", report["environment_digest"],
            "--reason", "isolated CLI acceptance"], env=env, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(apply.returncode, 0, apply.stderr)
        self.assertTrue(json.loads(apply.stdout)["ready"])
        self.assertTrue(self.store.read(self.projection()).matches(self.projection()))

    def test_snapshot_refreshes_stale_identity_map(self):
        old = self.projection().binding()
        self.session.commit()
        with Session(self.engine) as other:
            changed = other.get(DocumentVersion, self.version.id)
            changed.lock_version += 1
            other.commit()
        with self.assertRaises(AppError) as error:
            locked_projection(self.session, self.project.id, self.document.id, self.version.id, expected_binding=old)
        self.assertEqual(error.exception.code, "graph_source_changed")

    def test_duplicate_ids_and_foreign_ownership_fail_closed(self):
        self.sync()
        self.query("MATCH (t:Tag {id:$id}) CREATE (:Tag {id:$id, project_id:t.project_id, name:t.name})", id=str(self.tag.id))
        with self.assertRaises(AppError) as error:
            self.store.reconcile(self.projection())
        self.assertEqual(error.exception.code, "graph_identity_conflict")

    def test_unknown_relation_owner_is_not_deleted(self):
        self.sync()
        self.query("MATCH (:Chunk {id:$id})-[r:CHUNK_HAS_TAG]->() SET r.projection_owner='another-feature'", id=str(self.chunks[0].id))
        with self.assertRaises(AppError):
            self.store.reconcile(self.projection())
        rows = self.query("MATCH (:Chunk {id:$id})-[r:CHUNK_HAS_TAG]->() RETURN r.projection_owner AS owner", id=str(self.chunks[0].id))
        self.assertEqual(rows[0]["owner"], "another-feature")

    def test_legacy_unknown_tag_ownership_stops(self):
        self.sync()
        extra = str(uuid4()); self.created_ids.add(extra)
        self.query("MATCH (c:Chunk {id:$id}) CREATE (t:Tag {id:$extra}) MERGE (c)-[:CHUNK_HAS_TAG]->(t)", id=str(self.chunks[0].id), extra=extra)
        with self.assertRaises(AppError):
            self.store.reconcile(self.projection())

    def test_missing_structure_is_not_recreated_by_tag_only_repair(self):
        before = self.store.read(self.projection())
        with self.assertRaises(AppError) as error:
            self.store.reconcile(self.projection(), tags_only=True, target_digest=before.target_digest)
        self.assertEqual(error.exception.code, "graph_structure_repair_required")
        self.assertEqual(before.target_digest, self.store.read(self.projection()).target_digest)

    def test_real_constraint_failure_rolls_back_partial_graph_then_retry_recovers(self):
        from app.domain.graph_sync_jobs import enqueue_graph_sync, execute_graph_sync_job
        # A real, disposable Neo4j constraint produces a server-side failure
        # after preceding MERGEs; never substitute a fake driver response.
        constraint = "chg292_" + uuid4().hex
        self.query(f"CREATE CONSTRAINT {constraint} FOR (c:Chunk) REQUIRE (c.project_id, c.title) IS UNIQUE")
        self.chunks[1].title = self.chunks[0].title; self.session.commit()
        kwargs = dict(project_id=self.project.id, document_id=self.document.id, document_version_id=self.version.id,
            trigger_type="manual_retry", requested_by_user_id=None, request_id=None)
        try:
            job = enqueue_graph_sync(self.session, **kwargs); self.session.commit()
            execute_graph_sync_job(self.session, settings=self.settings, job_id=job.id)
            self.session.refresh(job)
            self.assertEqual(job.status, "failed")
            self.assertEqual(job.error_code, "graph_projection_not_ready")
            self.assertEqual(len(self.store.read(self.projection()).graph["nodes"]), 0)
        finally:
            self.query(f"DROP CONSTRAINT {constraint}")
        retry = enqueue_graph_sync(self.session, **kwargs, parent_job_id=job.id); self.session.commit()
        execute_graph_sync_job(self.session, settings=self.settings, job_id=retry.id)
        self.session.refresh(retry)
        self.assertEqual(retry.status, "completed")
        self.assertTrue(self.store.read(self.projection()).matches(self.projection()))

    def test_project_generation_and_disabled_document_cancel_or_fail(self):
        from app.domain.graph_sync_jobs import enqueue_graph_sync, execute_graph_sync_job
        def enqueue():
            job = enqueue_graph_sync(self.session, project_id=self.project.id, document_id=self.document.id,
                document_version_id=self.version.id, trigger_type="manual_retry", requested_by_user_id=None, request_id=None)
            self.session.commit()
            return job
        stale = enqueue()
        self.project.work_generation += 1; self.session.commit()
        execute_graph_sync_job(self.session, settings=self.settings, job_id=stale.id)
        self.session.refresh(stale)
        self.assertEqual(stale.status, "cancelled")
        disabled = enqueue()
        self.document.status = "inactive"; self.session.commit()
        execute_graph_sync_job(self.session, settings=self.settings, job_id=disabled.id)
        self.session.refresh(disabled)
        self.assertEqual(disabled.error_code, "graph_scope_inactive")
        self.assertEqual(len(self.store.read(self.projection()).graph["nodes"]), 0)

    def test_crash_after_graph_commit_retry_is_idempotent(self):
        from app.domain.graph_sync_jobs import enqueue_graph_sync, execute_graph_sync_job
        job = enqueue_graph_sync(self.session, project_id=self.project.id, document_id=self.document.id,
            document_version_id=self.version.id, trigger_type="manual_retry", requested_by_user_id=None, request_id=None)
        self.session.commit()
        external_commit = synchronize_graph(self.session, self.settings, self.project.id, self.document.id, self.version.id)
        self.session.rollback()  # Real cross-store commit gap, no fake adapter.
        execute_graph_sync_job(self.session, settings=self.settings, job_id=job.id)
        self.session.refresh(job)
        self.assertEqual(job.status, "completed")
        self.assertEqual(external_commit.target_digest, self.store.read(self.projection()).target_digest)

    def test_real_publish_switch_history_and_readiness(self):
        from app.api.routes.serving import _active_version_ids, _project_graph_without_chunk_content
        from app.domain.review_publish import switch_active_version
        from app.domain.graph_sync_jobs import execute_graph_sync_job
        owner = self.owner()
        self.version.status = "approved"; self.version.published_at = None
        self.session.commit()
        manifest, _index, job = self.publish(self.version, self.chunks, owner)
        self.assertEqual(job.status, "completed")
        self.assertTrue(self.store.read(self.projection()).matches(self.projection()))
        v2 = DocumentVersion(project_id=self.project.id, document_id=self.document.id,
            version_major=2, extraction_revision=1, version_label="v2.1", status="approved")
        self.session.add(v2); self.session.flush()
        c2 = Chunk(project_id=self.project.id, document_id=self.document.id, document_version_id=v2.id,
            chunk_index=1, content="Historical evidence", content_hash=digest("history"), retrieval_text="Historical evidence")
        self.session.add(c2); self.session.flush()
        self.session.add(ChunkTag(chunk_id=c2.id, tag_id=self.tag.id, source="manual", created_at=datetime.now(UTC)))
        self.session.commit()
        self.created_ids.update((str(v2.id), str(c2.id)))
        self.publish(v2, [c2], owner)
        old_graph = _project_graph_without_chunk_content(self.session, self.project, {self.version.id}, 120)
        self.assertIn(str(self.chunks[0].id), {n.id for n in old_graph.nodes})
        self.assertEqual(_active_version_ids(self.session, self.project.id), {v2.id})
        self.session.refresh(self.version)
        switched, switched_job = switch_active_version(session=self.session, actor_user_id=owner.id,
            document=self.document, version=self.version, lock_version=self.version.lock_version,
            impact_confirmed=True, audit_reason="isolated acceptance", request_id=None)
        self.session.commit()
        execute_graph_sync_job(self.session, settings=self.settings, job_id=switched_job.id)
        self.assertEqual(switched.document_version_id, self.version.id)
        self.assertTrue(self.store.read(self.projection()).matches(self.projection()))
        newer = build_graph_projection(self.session, self.project, self.document, v2)
        self.assertTrue(self.store.read(newer).matches(newer))

    def test_real_publish_failure_rolls_back_but_retains_failed_job(self):
        owner = self.owner()
        self.version.status = "approved"; self.version.published_at = None
        self.session.commit()
        # Real corrupt ownership causes a real Neo4j transaction refusal.
        self.query("CREATE (:Tag {id:$id, project_id:$foreign})", id=str(self.tag.id), foreign=str(uuid4()))
        with self.assertRaises(AppError):
            self.publish(self.version, self.chunks, owner)
        self.session.refresh(self.version)
        self.assertEqual(self.version.status, "approved")
        self.assertIsNone(self.version.published_at)
        self.assertIsNone(self.session.scalar(select(ActiveVersionManifest).where(ActiveVersionManifest.document_id == self.document.id)))
        job = self.session.scalar(select(GraphSyncJob).where(GraphSyncJob.document_version_id == self.version.id))
        self.assertEqual(job.status, "failed")
        notice = self.session.scalar(select(NotificationEvent).where(NotificationEvent.business_key == f"graph:{self.version.id}"))
        self.assertEqual(notice.event_type, "graph_sync.failed")

    def test_graph_only_repair_preserves_nonempty_vectors_index_and_manifest(self):
        from scripts.chg292_graph_tag_reconcile import reconcile_scope
        from app.domain.review_publish import published_index_name
        owner = self.owner()
        self.version.status = "approved"; self.version.published_at = None; self.session.commit()
        self.publish(self.version, self.chunks, owner)
        index_url = self.settings.opensearch_url + "/" + published_index_name(self.settings.opensearch_index_prefix, self.version.embedding_profile_id)
        with urllib.request.urlopen(urllib.request.Request(index_url + "/_refresh", method="POST"), timeout=10):
            pass
        tables = ("projects", "documents", "document_versions", "tags", "chunk_tags", "document_version_tags",
            "embedding_profiles", "embedding_builds", "embedding_build_vectors", "active_version_manifests", "ai_models", "ai_model_usage_events")
        def snapshots():
            sql = {name: self.session.scalar(text(f"SELECT md5(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text, '[]')) FROM {name} t")) for name in tables}
            with urllib.request.urlopen(index_url + "/_search?size=1000", timeout=10) as response:
                hits = json.load(response)["hits"]["hits"]
            self.assertEqual(len(hits), 2)
            return sql, digest(sorted([{k: hit[k] for k in ("_id", "_source")} for hit in hits], key=lambda hit: hit["_id"]))
        before = snapshots()
        self.query("MATCH (:Chunk {id:$id})-[r:CHUNK_HAS_TAG]->() DELETE r", id=str(self.chunks[0].id))
        scope = dict(project_id=self.project.id, document_id=self.document.id, version_id=self.version.id)
        report = reconcile_scope(self.session, self.settings, **scope)
        reconcile_scope(self.session, self.settings, **scope, apply=True, expected_source=report["source_digest"],
            expected_target=report["target_digest"], expected_environment=report["environment_digest"], reason="isolated verification")
        self.session.commit()
        self.assertEqual(before, snapshots())

    def test_authenticated_graph_status_scope_and_published_mutations(self):
        client, owner = self.authenticated_client()
        self.version.status = "approved"; self.version.published_at = None; self.session.commit()
        self.publish(self.version, self.chunks, owner)
        base = f"/api/v1/projects/{self.project.id}"
        detail = f"{base}/documents/{self.document.id}/versions/{self.version.id}"
        response = client.get(detail + "/graph")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn("**Original**", json.dumps(data))
        self.assertEqual(client.get(base + "/serving-status").json()["graph_ready_count"], 1)
        path_url = base + f"/graph/paths?source_id={self.chunks[0].id}&target_id=tag:{self.tag.id}"
        self.assertEqual(client.get(path_url).status_code, 200)
        forbidden = client.get(f"/api/v1/projects/{uuid4()}/graph")
        self.assertEqual(forbidden.status_code, 403)
        source = self.projection().source_digest
        for path in ("/tags", f"/chunks/{self.chunks[0].id}/tags"):
            rejected = client.post(detail + path, json={"tag_text": "Should not exist"})
            self.assertEqual(rejected.status_code, 409, rejected.text)
            automatic = client.post(detail + path + "/auto", json={"max_tags": 5})
            self.assertEqual(automatic.status_code, 409, automatic.text)
        self.assertEqual(self.projection().source_digest, source)
        self.query("MATCH (:Chunk {id:$id})-[r:CHUNK_HAS_TAG]->() DELETE r", id=str(self.chunks[0].id))
        for path in (detail + "/graph", base + "/graph", base + f"/graph/neighbors?node_id={self.chunks[0].id}", path_url):
            not_ready = client.get(path)
            self.assertEqual(not_ready.status_code, 503, not_ready.text)
        status = client.get(base + "/serving-status").json()
        self.assertEqual(status["graph_ready_count"], 0)
        self.assertEqual(status["ready_index_count"], 1)
        self.document.status = "inactive"; self.session.commit()
        self.assertEqual(client.get(base + "/graph").json()["nodes"], [])
        self.project.status = "archived"; self.project.archived_at = datetime.now(UTC); self.project.archived_by = owner.id
        self.session.commit()
        self.assertEqual(client.get(base + "/graph").status_code, 409)

    def test_claimed_terminal_and_unbound_work_fail_safely(self):
        from app.domain.graph_sync_jobs import enqueue_graph_sync, execute_graph_sync_job, GRAPH_SYNC_TOPIC
        execute_graph_sync_job(self.session, settings=self.settings, job_id=uuid4())
        job = enqueue_graph_sync(self.session, project_id=self.project.id, document_id=self.document.id,
            document_version_id=self.version.id, trigger_type="manual_retry", requested_by_user_id=None, request_id=None)
        self.session.commit()
        for state in ("running", "failed", "completed"):
            job.status = state; job.claim_token = uuid4(); job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
            self.session.commit()
            execute_graph_sync_job(self.session, settings=self.settings, job_id=job.id)
            self.session.refresh(job)
            self.assertEqual(job.status, state)
        job.status = "queued"; job.claim_token = None; job.lease_expires_at = None
        event = self.session.scalar(select(OutboxEvent).where(OutboxEvent.topic == GRAPH_SYNC_TOPIC, OutboxEvent.aggregate_id == job.id))
        event.payload = {"job_id": str(job.id)}
        self.session.commit()
        execute_graph_sync_job(self.session, settings=self.settings, job_id=job.id)
        self.session.refresh(job)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error_code, "graph_work_binding_required")
        self.assertEqual(len(self.store.read(self.projection()).graph["nodes"]), 0)

    def test_authenticated_candidate_tag_edit_refreshes_preview_only(self):
        client, owner = self.authenticated_client()
        self.version.status = "submission_ready"; self.version.published_at = None; self.session.commit()
        path = f"/api/v1/projects/{self.project.id}/documents/{self.document.id}/versions/{self.version.id}"
        before_version = self.version.lock_version
        response = client.post(path + "/tags", json={"tag_text": "New candidate tag"})
        self.assertEqual(response.status_code, 200, response.text)
        self.session.refresh(self.version)
        self.assertEqual(self.version.chunk_strategy["graph_tag_revision"], 1)
        self.assertEqual(before_version, self.version.lock_version)
        tag = self.session.scalar(select(Tag).where(Tag.project_id == self.project.id, Tag.name == "New candidate tag"))
        preview = client.get(path + "/graph").json()
        self.assertIn(f"tag:{tag.id}", {node["id"] for node in preview["nodes"]})
        response = client.delete(path + f"/tags/{tag.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.session.refresh(self.version)
        self.assertEqual(self.version.chunk_strategy["graph_tag_revision"], 2)
        self.assertEqual(len(self.store.read(self.projection()).graph["nodes"]), 0)
        self.version.status = "approved"; self.session.commit()
        self.assertEqual(client.post(path + "/tags", json={"tag_text": "Rejected"}).status_code, 409)
        owner.is_active = False; self.session.commit()
        self.assertEqual(client.get(path + "/graph").status_code, 403)


if __name__ == "__main__":
    unittest.main()
