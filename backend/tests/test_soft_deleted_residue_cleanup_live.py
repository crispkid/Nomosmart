"""Real native storage/identity inputs, not generated model/ready evidence.

The coordinator configures this module in memory. No test double is used and
unconfigured services are reported unavailable, never converted to a pass.
"""
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import select as io_select
import subprocess
import sys
import time
import unittest
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models as m
from app.domain import soft_deleted_residue_cleanup as cleanup
from app.domain.content_update_cleanup import delete_retired_index
from app.domain.extraction_pipeline import staging_index_name
from app.security.session_auth import digest as session_digest
from scripts.soft_deleted_residue_cleanup import authenticate, command

CONFIG = None


def configure(value):
    global CONFIG
    CONFIG = value


class SoftDeletedResidueLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if CONFIG is None:
            raise unittest.SkipTest("BLOCKED: approved real maintenance service context is required")
        cls.config = CONFIG

    def setUp(self):
        self.db = Session(self.config["engine"], expire_on_commit=False)
        self.settings = self.config["settings"]
        self.doc = self.db.get(m.Document, self.config["document_id"])
        self.version = self.db.get(m.DocumentVersion, self.config["version_id"])
        self.project = self.db.get(m.Project, self.doc.project_id)
        self.scope = cleanup.Scope(self.project.id, self.doc.id, self.version.id,
            self.doc.lock_version, self.version.lock_version, self.project.work_generation, 1, cleanup.digest("native input"))
        self.context = authenticate(self.db, self.settings, self.config["identities"]["editor"]["session_cookie"])
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)

    def _native_rows(self):
        now = datetime.now(UTC)
        old = m.Chunk(project_id=self.project.id, document_id=self.doc.id, document_version_id=self.version.id,
            chunk_index=1, content="obsolete native storage input", status="superseded", content_hash=cleanup.digest("old"))
        current = m.Chunk(project_id=self.project.id, document_id=self.doc.id, document_version_id=self.version.id,
            chunk_index=1, content="retained native storage input", status="active", content_hash=cleanup.digest("new"))
        tag = m.Tag(project_id=self.project.id, name="native shared input " + uuid4().hex, created_at=now)
        model = m.AIModel(name="native storage input " + uuid4().hex, model_type="Embedding", provider="stored-vector-input", is_active=False)
        self.db.add_all((old, current, tag, model)); self.db.flush()
        current.parent_chunk_id = old.id
        profile = m.EmbeddingProfile(model_id=model.id, model_version="native-storage", vector_dimension=2,
            distance_method="cosine", mapping_version=1, chunk_strategy={"native_storage_input": True})
        self.db.add(profile); self.db.flush()
        builds = [m.EmbeddingBuild(project_id=self.project.id, document_id=self.doc.id, document_version_id=self.version.id,
            embedding_profile_id=profile.id, vector_dimension=2, status="failed", build_revision=i,
            content_fingerprint=cleanup.digest(i), chunk_count=1) for i in (1, 2)]
        self.db.add_all(builds); self.db.flush()
        vectors = [m.EmbeddingBuildVector(embedding_build_id=b.id, chunk_id=c.id, chunk_index=1,
            vector=[0.2, 0.3], vector_checksum=hashlib.sha256(b'[0.2,0.3]').hexdigest(), token_count=1, created_at=now)
            for b, c in zip(builds, (old, current), strict=True)]
        self.db.add_all(vectors)
        self.db.add_all([m.ChunkTag(chunk_id=c.id, tag_id=tag.id, source="manual", metadata_={"native_storage_input": True},
            created_by=self.context.user_id, created_at=now) for c in (old, current)])
        pipeline = m.PipelineRun(project_id=self.project.id, document_id=self.doc.id, document_version_id=self.version.id,
            project_generation=self.project.work_generation, run_type="document_extraction", status="failed", created_at=now)
        other = m.PipelineRun(project_id=self.project.id, document_id=self.doc.id, document_version_id=self.version.id,
            project_generation=self.project.work_generation, run_type="document_extraction", status="failed", created_at=now)
        self.db.add_all((pipeline, other)); self.db.flush()
        step = m.PipelineRunStep(run_id=pipeline.id, step_name="auto_tag", status="failed",
            artifact_payload={"tagged_chunks": [{"chunk_id": str(old.id)}]}, artifact_fingerprint=cleanup.digest("native input"))
        self.db.add(step); self.db.flush()
        return old, current, tag, builds, vectors, step, other

    def test_01_actual_oidc_and_effective_permissions(self):
        # Keep the historical case ID; credentials are actual LDAP/OIDC server
        # sessions, not cookies renamed as external bearer tokens.
        for name in ("editor", "owner"):
            context = authenticate(self.db, self.settings, self.config["identities"][name]["session_cookie"])
            cleanup.authorize(self.db, self.scope, context)
        for name in ("viewer", "outsider", "disabled"):
            with self.subTest(name=name), self.assertRaises(AppError):
                context = authenticate(self.db, self.settings, self.config["identities"][name]["session_cookie"])
                cleanup.authorize(self.db, self.scope, context)
        with self.assertRaises(AppError):
            authenticate(self.db, self.settings, "invalid-session-cookie")
        with self.assertRaises(AppError):
            authenticate(self.db, self.settings, None)
        with self.assertRaises(AppError) as error:
            authenticate(self.db, self.settings, self.config["expired_cookie"])
        self.assertEqual(error.exception.code, "session_expired")

        cookie = self.config["identities"]["editor"]["session_cookie"]
        for payload in (None, {}, {"session_cookie": ""}, {"session_cookie": 42},
                {"session_cookie": "x" * 201}, {"access_token": "external-bearer"},
                {"session_cookie": cookie, "access_token": "external-bearer"}):
            with self.subTest(input_shape=type(payload).__name__), self.assertRaises(AppError) as error:
                command("inspect", payload)
            self.assertEqual(error.exception.code, "authentication_required")
        for supplied, expected in ((cookie, "soft_residue_invalid_scope"),
                ("invalid-session-cookie", "session_expired")):
            child = subprocess.run([sys.executable, "-B", "-m", "scripts.soft_deleted_residue_cleanup", "inspect"],
                input=json.dumps({"session_cookie": supplied, "scope": {}}),
                capture_output=True, text=True, timeout=20)
            result = json.loads(child.stdout)
            self.assertEqual(child.returncode, 1)
            self.assertEqual(result["code"], expected)
            self.assertTrue(supplied not in child.stdout and supplied not in child.stderr, "private credential was disclosed")

        row = self.db.scalar(select(m.AuthSession).where(m.AuthSession.secret_digest == session_digest(cookie)))
        before_activity = row.last_activity_at
        for change, expected in (("config_revision", "session_revoked"),
                ("locally_disabled", "user_disabled"), ("directory_enabled", "user_disabled"),
                ("project_membership", "soft_residue_permission_denied"), ("role_grants", "application_access_denied")):
            nested = self.db.begin_nested()
            try:
                if change == "config_revision":
                    self.db.execute(update(m.AuthSession).where(m.AuthSession.id == row.id).values(config_revision=row.config_revision + 1000))
                elif change in {"locally_disabled", "directory_enabled"}:
                    self.db.execute(update(m.User).where(m.User.id == self.context.user_id)
                        .values(**{change: change == "locally_disabled"}))
                elif change == "project_membership":
                    self.db.execute(delete(m.ProjectMember).where(m.ProjectMember.project_id == self.project.id,
                        m.ProjectMember.user_id == self.context.user_id))
                else:
                    self.db.execute(delete(m.RoleUser).where(m.RoleUser.user_id == self.context.user_id))
                with self.assertRaises(AppError) as error:
                    cleanup.authorize(self.db, self.scope, self.context)
                self.assertEqual(error.exception.code, expected)
            finally:
                nested.rollback()
        cleanup.authorize(self.db, self.scope, self.context)
        self.assertEqual(self.db.get(m.AuthSession, row.id).last_activity_at, before_activity)
        revoked_cookie = self.config["revocable_cookie"]
        revoked_context = authenticate(self.db, self.settings, revoked_cookie)
        self.config["logout_revocable"]()
        with self.assertRaises(AppError) as error:
            cleanup.authorize(self.db, self.scope, revoked_context)
        self.assertEqual(error.exception.code, "session_expired")
        with self.assertRaises(AppError):
            authenticate(self.db, self.settings, revoked_cookie)

    def test_02_parent_scope_restore_and_locks_are_checked(self):
        cleanup.locked_scope(self.db, self.scope, self.context)
        self.doc.is_deleted = False; self.db.flush()
        with self.assertRaises(AppError) as error:
            cleanup.locked_scope(self.db, self.scope, self.context)
        self.assertEqual(error.exception.code, "soft_residue_stale")

    def test_03_actual_chat_reference_protects_old_identity(self):
        old, *_ = self._native_rows()
        cleanup.reference_inventory(self.db, self.scope, [old.id])
        self.db.add(m.ChatRecord(project_id=self.project.id, conversation_id=uuid4(), question="synthetic reference input",
            reference_docs=[{"chunk_id": str(old.id)}], created_by=self.context.user_id,
            asked_at=datetime.now(UTC), created_at=datetime.now(UTC)))
        self.db.flush()
        with self.assertRaises(AppError) as error:
            cleanup.reference_inventory(self.db, self.scope, [old.id])
        self.assertEqual(error.exception.code, "soft_residue_history_reference")

    def test_04_unknown_json_and_actual_new_fk_fail_closed(self):
        self.db.add(m.ChatRecord(project_id=self.project.id, conversation_id=uuid4(), question="synthetic malformed reference input",
            reference_docs=[42], created_by=self.context.user_id, asked_at=datetime.now(UTC), created_at=datetime.now(UTC)))
        self.db.flush()
        with self.assertRaises(AppError) as error:
            cleanup.reference_inventory(self.db, self.scope, [])
        self.assertEqual(error.exception.code, "soft_residue_unknown_reference")
        self.db.execute(text("CREATE TABLE chg347_unknown_reference(id uuid PRIMARY KEY, chunk_id uuid REFERENCES chunks(id) ON DELETE CASCADE)"))
        with self.assertRaises(AppError) as error:
            cleanup.check_chunk_fks(self.db)
        self.assertEqual(error.exception.code, "soft_residue_unknown_reference")

    def test_05_native_storage_retirement_preserves_latest_and_shared_rows(self):
        old, current, tag, builds, vectors, step, other = self._native_rows()
        retained = cleanup.digest(cleanup.row_value(current))
        selected_vector = cleanup.digest(cleanup.row_value(vectors[1]))
        items = cleanup.database_items(self.db, self.scope, other.id)
        cleanup.reference_inventory(self.db, self.scope, cleanup.identity_tokens(items))
        receipt = cleanup.retire_database_items(self.db, self.scope, items, run_id=uuid4(), revision=1)
        self.assertEqual(receipt["vectors"], 1)
        self.assertEqual(receipt["links"], 1)
        self.assertEqual(receipt["protected_lineage_ids"], [str(old.id)])
        self.assertEqual(cleanup.digest(cleanup.row_value(current)), retained)
        self.assertEqual(cleanup.digest(cleanup.row_value(vectors[1])), selected_vector)
        self.assertEqual(self.db.get(m.Chunk, old.id).content, "")
        self.assertIsNone(self.db.get(m.EmbeddingBuildVector, vectors[0].id))
        self.assertIsNotNone(self.db.get(m.Tag, tag.id))
        self.assertIsNotNone(self.db.get(m.ChunkTag, (current.id, tag.id)))
        self.assertEqual(self.db.get(m.EmbeddingBuild, builds[0].id).status, "invalidated")
        self.assertEqual(builds[1].status, "failed")
        self.assertTrue(step.artifact_payload["payload_retired"])
        self.assertNotIn("tagged_chunks", step.artifact_payload)

    def test_06_changed_storage_input_is_rejected_before_delete(self):
        old, _, _, _, vectors, _, other = self._native_rows()
        items = cleanup.database_items(self.db, self.scope, other.id)
        vectors[0].vector = [0.4, 0.5]; self.db.flush()
        with self.assertRaises(AppError) as error:
            cleanup.retire_database_items(self.db, self.scope, items, run_id=uuid4(), revision=1)
        self.assertEqual(error.exception.code, "soft_residue_stale")
        self.assertNotEqual(old.content, "")
        self.assertIsNotNone(self.db.get(m.EmbeddingBuildVector, vectors[0].id))

    def test_07_real_opensearch_exclusive_index_and_selected_protection(self):
        base = staging_index_name(self.settings.opensearch_index_prefix, self.project.id, self.version.id)
        selected = base + "-edit-" + uuid4().hex
        self.version.extraction_artifact_uri = "opensearch://" + selected
        with httpx.Client(base_url=self.settings.opensearch_url, verify=self.settings.opensearch_httpx_verify,
                auth=(self.settings.opensearch_username.get_secret_value(), self.settings.opensearch_password.get_secret_value()),
                trust_env=False, timeout=15) as client:
            for name in (base, selected):
                self.config["record_resource"]("index", name)
                response = client.put("/" + name, json={"settings": {"number_of_shards": 1, "number_of_replicas": 0},
                    "mappings": {"properties": {k: {"type": "keyword"} for k in ("project_id", "document_id", "document_version_id")}}})
                self.assertEqual(response.status_code, 200)
                self.addCleanup(lambda n=name: self.config["delete_index"](n))
                source = {"project_id": str(self.project.id), "document_id": str(self.doc.id), "document_version_id": str(self.version.id)}
                self.assertEqual(client.put("/" + name + "/_doc/native", params={"refresh": "true"}, json=source).status_code, 201)
            self.db.flush()
            with self.assertRaises(AppError):
                delete_retired_index(self.db, self.settings, self.project, self.doc, self.version, selected, selected)
            self.assertTrue(delete_retired_index(self.db, self.settings, self.project, self.doc, self.version, base, selected))
            self.assertEqual(client.get("/" + base).status_code, 404)
            self.assertEqual(client.get("/" + selected).status_code, 200)

    def test_08_real_neo4j_unknown_candidate_is_protected(self):
        from app.core.config import create_neo4j_driver
        cleanup.require_empty_candidate_graph(self.settings, self.version.id)
        identity = str(uuid4())
        self.config["record_resource"]("graph_node", identity)
        with create_neo4j_driver(self.settings) as driver, driver.session(database=self.settings.neo4j_database) as graph:
            graph.run("CREATE (:Chunk {id:$id, document_version_id:$v, maintenance_run_id:$owner})",
                id=identity, v=str(self.version.id), owner=self.config["run_id"]).consume()
            try:
                with self.assertRaises(AppError) as error:
                    cleanup.require_empty_candidate_graph(self.settings, self.version.id)
                self.assertEqual(error.exception.code, "soft_residue_graph_reference")
            finally:
                graph.run("MATCH(n:Chunk {id:$id, maintenance_run_id:$owner}) DELETE n",
                    id=identity, owner=self.config["run_id"]).consume()

    def test_09_incomplete_retained_source_cannot_be_marked_ready(self):
        before = dict(self.version.chunk_strategy)
        with self.assertRaises(AppError):
            cleanup.inspect_cleanup(self.db, self.settings, self.scope, self.context)
        self.assertEqual(self.version.chunk_strategy, before)
        self.assertNotIn(cleanup.KEY, self.version.chunk_strategy)

    def test_10_real_parent_lock_blocks_concurrent_restore(self):
        cleanup.locked_scope(self.db, self.scope, self.context)
        with Session(self.config["engine"]) as writer:
            writer.execute(text("SET LOCAL lock_timeout='200ms'"))
            from sqlalchemy.exc import OperationalError
            with self.assertRaises(OperationalError) as error:
                writer.execute(text("UPDATE documents SET is_deleted=false WHERE id=:id"), {"id": self.doc.id})
            self.assertEqual(error.exception.orig.pgcode, "55P03")

    def test_11_real_s3_source_hash_is_unchanged_by_storage_retirement(self):
        from app.integrations.s3_storage import S3ObjectStorage
        storage = S3ObjectStorage(self.settings)
        key = self.settings.s3_object_prefix + "native-input/" + self.config["run_id"] + "/" + uuid4().hex + ".txt"
        body = b"native source input; not model output"
        self.config["record_resource"]("object", key)
        storage.put_object(bucket=self.settings.s3_bucket, key=key, body=body, content_type="text/plain")
        self.addCleanup(lambda: storage.delete_object(bucket=self.settings.s3_bucket, key=key))
        old, _, _, _, _, _, other = self._native_rows()
        items = cleanup.database_items(self.db, self.scope, other.id)
        cleanup.retire_database_items(self.db, self.scope, items, run_id=uuid4(), revision=1)
        actual = storage.get_object(bucket=self.settings.s3_bucket, key=key).body
        self.assertEqual(hashlib.sha256(actual).hexdigest(), hashlib.sha256(body).hexdigest())

    def test_12_real_network_disconnect_cannot_be_reported_as_absent(self):
        base = staging_index_name(self.settings.opensearch_index_prefix, self.project.id, self.version.id)
        selected = base + "-edit-" + uuid4().hex
        client = httpx.Client(base_url=self.settings.opensearch_url, verify=self.settings.opensearch_httpx_verify,
            auth=(self.settings.opensearch_username.get_secret_value(), self.settings.opensearch_password.get_secret_value()), trust_env=False, timeout=10)
        self.addCleanup(client.close)
        self.config["record_resource"]("index", base)
        self.assertEqual(client.put("/" + base, json={"settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"properties": {k: {"type": "keyword"} for k in ("project_id", "document_id", "document_version_id")}}}).status_code, 200)
        self.addCleanup(lambda: self.config["delete_index"](base))
        source = {"project_id": str(self.project.id), "document_id": str(self.doc.id), "document_version_id": str(self.version.id)}
        self.assertEqual(client.put("/" + base + "/_doc/native", params={"refresh": "true"}, json=source).status_code, 201)
        root = Path(self.config["fault_root"])
        (root / "fault-request.json").write_text(json.dumps({"run_id": self.config["run_id"], "service": "opensearch"}))
        stop = time.monotonic() + 90
        while not (root / "fault-active").exists():
            self.assertLess(time.monotonic(), stop, "real fault controller unavailable"); time.sleep(.1)
        try:
            with self.assertRaises(AppError):
                delete_retired_index(self.db, self.settings, self.project, self.doc, self.version, base, selected)
        finally:
            (root / "fault-observed").touch()
            stop = time.monotonic() + 90
            while not (root / "fault-restored").exists():
                self.assertLess(time.monotonic(), stop, "real fault restoration unavailable"); time.sleep(.1)
        client.close()
        # A new transport avoids reusing a TCP connection from before the fault.
        with httpx.Client(base_url=self.settings.opensearch_url, verify=self.settings.opensearch_httpx_verify,
                auth=(self.settings.opensearch_username.get_secret_value(), self.settings.opensearch_password.get_secret_value()),
                trust_env=False, timeout=10) as reader:
            response = reader.get("/" + base + "/_doc/native")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["_source"], source)

    def test_13_native_checkpoint_survives_real_process_termination(self):
        # This is a native metadata storage input, not a valid planned/ready run.
        original = dict(self.version.chunk_strategy)
        run_id = str(uuid4())
        source = """import json,sys,time
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from app.db.models import DocumentVersion
from app.domain.soft_deleted_residue_cleanup import _save
from uuid import UUID
p=json.load(sys.stdin)
with Session(create_engine(p['database_url'],hide_parameters=True)) as db:
 v=db.scalar(select(DocumentVersion).where(DocumentVersion.id==UUID(p['version_id'])).with_for_update())
 _save(db,v,{'run_id':p['run_id'],'state':'partial_unknown','native_storage_input':True})
 db.commit()
 print('committed',flush=True)
 time.sleep(60)
"""
        process = subprocess.Popen([sys.executable, "-B", "-c", source], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            process.stdin.write(json.dumps({"database_url": self.config["engine"].url.render_as_string(hide_password=False),
                "version_id": str(self.version.id), "run_id": run_id})); process.stdin.close()
            self.assertTrue(io_select.select([process.stdout], [], [], 15)[0], "native checkpoint process did not signal within 15 seconds")
            self.assertEqual(process.stdout.readline().strip(), "committed")
            process.terminate(); process.wait(timeout=10)
            with Session(self.config["engine"]) as reader:
                version = reader.get(m.DocumentVersion, self.version.id)
                self.assertEqual(version.chunk_strategy[cleanup.KEY]["state"], "partial_unknown")
                self.assertEqual(version.chunk_strategy[cleanup.KEY]["run_id"], run_id)
                self.assertNotEqual(version.chunk_strategy[cleanup.KEY]["state"], "completed")
        finally:
            if process.poll() is None:
                process.terminate(); process.wait(timeout=10)
            process.stdout.close()
            with Session(self.config["engine"]) as writer:
                version = writer.get(m.DocumentVersion, self.version.id); version.chunk_strategy = original; writer.commit()


if __name__ == "__main__":
    unittest.main()
