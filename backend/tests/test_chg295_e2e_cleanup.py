"""Real disposable services only. No Provider or generated-success evidence.

Requires explicit CHG295_CLEANUP_* service credentials; never loads app .env.
All entities left for comparison belong to the fresh outer test stack, not MAAS.
"""
from contextlib import ExitStack
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import time
from uuid import uuid4

import pytest
from neo4j import GraphDatabase
from sqlalchemy import create_engine, delete, select, text, update
from sqlalchemy.orm import Session

from app.db.models import AIModel, Document, DocumentVersion, Project, ProjectMember, Role, RoleUser, User
from app.integrations.s3_storage import S3ClientConfig
from scripts.e2e_run_resources import CleanupConflict, RunJournal, SqlResources, cleanup_run
from scripts.e2e_external_resources import GraphResources, IndexResources, ObjectResources


@pytest.fixture(scope="module")
def stores():
    required = ("DB", "NEO4J", "OPENSEARCH", "S3", "S3_KEY", "S3_SECRET")
    values = {k: os.environ.get("CHG295_CLEANUP_" + k) for k in required}
    if not all(values.values()):
        pytest.fail("BLOCKED: fresh CHG295_CLEANUP_* services required; no current-service fallback")
    engine = create_engine(values["DB"], pool_pre_ping=True)
    driver = GraphDatabase.driver(values["NEO4J"], auth=None)
    index = IndexResources(values["OPENSEARCH"])
    objects = ObjectResources(S3ClientConfig(values["S3"], "us-east-1", values["S3_KEY"], values["S3_SECRET"], True),
        "chg295-" + uuid4().hex)
    assert objects.request("PUT").is_success
    assert objects.request("PUT", query={"versioning": ""},
        body=b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Enabled</Status></VersioningConfiguration>').is_success
    result = {"sql": SqlResources(engine), "graph": GraphResources(driver), "index": index, "object": objects}
    for service in result.values(): assert service.binding()
    yield result
    objects.http.close(); index.http.close(); driver.close(); engine.dispose()


def journal(tmp_path, stores, name="a", kinds=None):
    folder = tmp_path / name
    folder.mkdir(mode=0o700)
    return RunJournal(folder / "run.json", create=True,
        bindings={k: v.binding() for k, v in stores.items() if kinds is None or k in kinds})


def add_project(sql, run):
    project = Project(id=uuid4(), name="codex-live-governance-same-prefix", status="active")
    sql.create(run, [project])
    return project.id


def retained_user(sql):
    ident = uuid4()
    with Session(sql.engine) as session:
        session.add(User(id=ident, keycloak_user_id=str(ident), display_name="Retained test user"))
        session.commit()
    return ident


def exists(sql, model, ident):
    with Session(sql.engine) as session: return session.get(model, ident) is not None


def test_same_prefix_all_stores_and_idempotence(tmp_path, stores):
    with journal(tmp_path, stores, "a") as a, journal(tmp_path, stores, "b") as b:
        values = []
        for run in (a, b):
            pid = add_project(stores["sql"], run)
            node = stores["graph"].create_node(run, "Project", {"id": str(pid), "name": "same-prefix"})
            idx = stores["index"].create(run)
            stores["index"].create_document(run, idx, {"input": "controlled storage input, not generation evidence"})
            obj = stores["object"].create(run, b"owned test input")
            values.append((pid, node, idx, obj))
        snapshot = json.dumps(b.data, sort_keys=True)
        assert cleanup_run(a, stores)["status"] == "cleanup_complete"
        assert not exists(stores["sql"], Project, values[0][0])
        assert exists(stores["sql"], Project, values[1][0])
        assert stores["index"].check(values[1][2])
        assert stores["object"].check(values[1][3])
        with stores["graph"].prepare([values[1][1]]) as batch: assert batch.nodes
        assert json.dumps(b.data, sort_keys=True) == snapshot
        assert cleanup_run(a, stores)["status"] == "cleanup_complete"
        assert cleanup_run(b, stores)["status"] == "cleanup_complete"


def test_sql_owned_composite_keys_keep_shared_user(tmp_path, stores):
    sql = stores["sql"]; user = retained_user(sql)
    with journal(tmp_path, stores) as run:
        pid = add_project(sql, run); rid = uuid4()
        sql.create(run, [Role(id=rid, name="owned-" + str(rid)),
            RoleUser(role_id=rid, user_id=user, source="manual"),
            ProjectMember(project_id=pid, user_id=user, project_role="editor", created_at=datetime.now(UTC))])
        cleanup_run(run, stores)
        assert exists(sql, User, user) and not exists(sql, Role, rid)


@pytest.mark.parametrize("dependency", ["restrict", "cascade", "set_null"])
def test_sql_foreign_inbound_is_rejected_before_other_store_delete(tmp_path, stores, dependency):
    sql = stores["sql"]
    with journal(tmp_path, stores) as run:
        pid = add_project(sql, run)
        node = stores["graph"].create_node(run, "Project")
        # Disposable-only actual FK tables cover all deletion actions; unknown
        # referencing rows must refuse even when database CASCADE could remove them.
        name = "e2e_fk_" + uuid4().hex
        action = {"restrict": "RESTRICT", "cascade": "CASCADE", "set_null": "SET NULL"}[dependency]
        with sql.engine.begin() as c:
            c.execute(text(f'CREATE TABLE "{name}" (id uuid PRIMARY KEY, project_id uuid REFERENCES projects(id) ON DELETE {action})'))
            child = uuid4()
            c.execute(text(f'INSERT INTO "{name}" VALUES (:id, :pid)'), {"id": child, "pid": pid})
        try:
            with pytest.raises(CleanupConflict, match="sql_unowned_dependency"): cleanup_run(run, stores)
            assert exists(sql, Project, pid)
            with stores["graph"].prepare([node]) as batch: assert batch.nodes
            with sql.engine.connect() as c: assert c.scalar(text(f'SELECT project_id FROM "{name}" WHERE id=:id'), {"id": child}) == pid
        finally:
            with sql.engine.begin() as c: c.execute(text(f'DROP TABLE "{name}"'))
        assert cleanup_run(run, stores)["status"] == "cleanup_complete"


def test_sql_scope_change_refuses(tmp_path, stores):
    sql = stores["sql"]
    with journal(tmp_path, stores) as run, journal(tmp_path, stores, "b") as b:
        a_id, b_id = add_project(sql, run), add_project(sql, b)
        did = uuid4()
        sql.create(run, [Document(id=did, project_id=a_id, document_code=str(did), title="input", source_type="file_upload")])
        with sql.engine.begin() as c: c.execute(update(Document).where(Document.id == did).values(project_id=b_id))
        with pytest.raises(CleanupConflict, match="sql_ownership_changed"): cleanup_run(run, stores)
        assert exists(sql, Document, did)
        with sql.engine.begin() as c: c.execute(update(Document).where(Document.id == did).values(project_id=a_id))
        cleanup_run(run, stores); cleanup_run(b, stores)


def test_sql_created_at_replacement_is_not_adopted(tmp_path, stores):
    sql = stores["sql"]
    with journal(tmp_path, stores) as run:
        pid = add_project(sql, run)
        with sql.engine.begin() as c:
            c.execute(delete(Project).where(Project.id == pid))
            c.execute(Project.__table__.insert().values(id=pid, name="replacement", status="active"))
        with pytest.raises(CleanupConflict, match="sql_ownership_changed"): cleanup_run(run, stores)
        assert exists(sql, Project, pid)


def test_shared_tag_owned_edge_and_unknown_late_edge(tmp_path, stores):
    graph = stores["graph"]
    with journal(tmp_path, stores) as run:
        node = graph.create_node(run, "Chunk")
        shared_id = str(uuid4())
        with graph.driver.session() as s:
            shared = s.run("CREATE (n:Tag {id:$id}) RETURN elementId(n) AS e", id=shared_id).single()["e"]
        edge = graph.create_edge(run, node["proof"]["element"], shared, "CHUNK_HAS_TAG")
        with graph.prepare([node, edge]) as batch:
            with graph.driver.session() as s:
                late = s.run("MATCH (n),(t) WHERE elementId(n)=$a AND elementId(t)=$b CREATE (n)-[r:LATE_TEST_EDGE]->(t) RETURN elementId(r) AS e",
                    a=node["proof"]["element"], b=shared).single()["e"]
            with pytest.raises(CleanupConflict, match="graph_unowned_relationship"): batch.delete()
        with pytest.raises(CleanupConflict, match="graph_unowned_relationship"): cleanup_run(run, stores)
        with graph.driver.session() as s:
            s.run("MATCH ()-[r]->() WHERE elementId(r)=$id DELETE r", id=late).consume()
        cleanup_run(run, stores)
        with graph.driver.session() as s:
            assert s.run("MATCH (n:Tag {id:$id}) RETURN count(n) AS c", id=shared_id).single()["c"] == 1


@pytest.mark.parametrize("conflict", ["alias", "foreign_document", "uuid", "marker"])
def test_index_conflicts_preserve_whole_index(tmp_path, stores, conflict):
    index = stores["index"]
    with journal(tmp_path, stores) as run:
        entry = index.create(run); name = entry["identity"]["name"]
        proof = json.loads(json.dumps(entry["proof"]))
        if conflict == "alias": index.request("PUT", f"/{name}/_alias/owned-test-{uuid4().hex}")
        elif conflict == "foreign_document": index.request("PUT", f"/{name}/_doc/foreign?refresh=true", {"value": "unowned"})
        elif conflict == "uuid": entry["proof"]["uuid"] = "not-this-index"
        else: index.request("PUT", f"/{name}/_mapping", {"_meta": {"different": "owner"}})
        with pytest.raises(CleanupConflict): cleanup_run(run, stores)
        assert index.request("GET", "/" + name)
        # Restore only this negative test's own mutation; then use the original receipt.
        entry["proof"] = proof
        current = index.request("GET", "/" + name)[name]
        for alias in current.get("aliases", {}): index.request("DELETE", f"/{name}/_alias/{alias}")
        if conflict == "foreign_document": index.request("DELETE", f"/{name}/_doc/foreign?refresh=true")
        if conflict == "marker": index.request("PUT", f"/{name}/_mapping", {"_meta": proof["marker"]})
        cleanup_run(run, stores)


def test_object_old_version_only_and_sibling_retained(tmp_path, stores):
    objects = stores["object"]
    with journal(tmp_path, stores) as run, journal(tmp_path, stores, "b") as b:
        a = objects.create(run, b"old version")
        sibling = objects.create(b, b"sibling")
        replacement = objects.request("PUT", a["identity"]["key"], body=b"replacement, not owned by a")
        assert replacement.is_success
        replacement_version = replacement.headers["x-amz-version-id"]
        cleanup_run(run, stores)
        assert objects.request("GET", a["identity"]["key"], query={"versionId": replacement_version}).content == b"replacement, not owned by a"
        assert objects.check(sibling)
        cleanup_run(b, stores)


def test_object_wrong_etag_refuses(tmp_path, stores):
    objects = stores["object"]
    with journal(tmp_path, stores) as run:
        a = objects.create(run, b"input"); original = a["proof"]["etag"]
        a["proof"]["etag"] = '"wrong"'
        with pytest.raises(CleanupConflict, match="object_ownership_changed"): cleanup_run(run, stores)
        a["proof"]["etag"] = original
        assert objects.check(a)
        cleanup_run(run, stores)


def test_missing_sql_root_does_not_skip_external(tmp_path, stores):
    with journal(tmp_path, stores) as run:
        pid = add_project(stores["sql"], run)
        stores["graph"].create_node(run, "Project")
        stores["index"].create(run); stores["object"].create(run, b"input")
        with stores["sql"].engine.begin() as c: c.execute(delete(Project).where(Project.id == pid))
        assert cleanup_run(run, stores)["resources"] == 4
        assert all(e["state"] == "deleted" for e in run.data["resources"])


def test_foreign_binding_refuses_and_records_error(tmp_path, stores):
    with journal(tmp_path, stores) as run:
        pid = add_project(stores["sql"], run)
        run.data["bindings"]["sql"]["system_id"] = "foreign"
        with pytest.raises(CleanupConflict, match="cleanup_target_changed"): cleanup_run(run, stores)
        assert exists(stores["sql"], Project, pid)
        assert run.data["state"] == "cleanup_failed"
        assert run.data["errors"] == [{"code": "cleanup_target_changed"}]
        run.data["bindings"]["sql"] = stores["sql"].binding()
        cleanup_run(run, stores)


def test_private_receipt_and_duplicate_identity(tmp_path):
    with journal(tmp_path, {}) as run:
        run.intent("sql", {"table": "projects", "pk": {"id": str(uuid4())}})
        identity = run.data["resources"][0]["identity"]
        with pytest.raises(CleanupConflict, match="receipt_duplicate_identity"): run.intent("sql", identity)
    assert (tmp_path / "a" / "run.json").stat().st_mode & 0o077 == 0


def test_receipt_symlink_and_invalid_schema(tmp_path):
    with journal(tmp_path, {}) as run: path = run.path
    link = path.parent / "symlink.json"; link.symlink_to(path)
    with pytest.raises(OSError): RunJournal(link)
    path.write_text("[]")
    with pytest.raises(CleanupConflict, match="receipt_invalid_schema"): RunJournal(path)


def test_receipt_exclusive_lock(tmp_path):
    with journal(tmp_path, {}) as run:
        with pytest.raises(BlockingIOError): RunJournal(run.path)


def test_real_sql_connection_loss_after_graph_commit_is_resumable(tmp_path, stores):
    # Kill only the exact transaction owned by this test after the graph receipt
    # is committed. The genuine database disconnect is not an injected adapter.
    name = "chg295-fault-" + uuid4().hex
    engine = create_engine(os.environ["CHG295_CLEANUP_DB"], connect_args={"application_name": name})
    local = {**stores, "sql": SqlResources(engine)}
    try:
        with journal(tmp_path, local) as run:
            pid = add_project(local["sql"], run)
            stores["graph"].create_node(run, "Project")
            idx = stores["index"].create(run)
            stores["index"].create_document(run, idx, {"input": "retains time for concurrent real fault"})
            def disconnect_owned_transaction():
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    saved = json.loads(run.path.read_text())
                    if any(e["kind"] == "graph" and e["state"] == "deleted" for e in saved["resources"]):
                        with stores["sql"].engine.begin() as c:
                            pids = c.scalars(text("SELECT pid FROM pg_stat_activity WHERE application_name=:name AND xact_start IS NOT NULL"), {"name": name}).all()
                            assert len(pids) == 1
                            assert c.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pids[0]})
                            return
                    time.sleep(0.005)
                pytest.fail("Did not observe graph commit before fault deadline")
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(disconnect_owned_transaction)
                with pytest.raises(CleanupConflict, match="cleanup_service_failure"): cleanup_run(run, local)
                future.result(timeout=25)
            assert run.data["state"] == "cleanup_partial"
            assert exists(stores["sql"], Project, pid)
            assert next(e for e in run.data["resources"] if e["kind"] == "graph")["state"] == "deleted"
            # Drop the dead connection; reconnect to the same immutable DB binding.
            engine.dispose()
            assert cleanup_run(run, local)["status"] == "cleanup_complete"
            assert cleanup_run(run, local)["status"] == "cleanup_complete"
    finally:
        engine.dispose()


def test_sql_nullable_cycle_only_within_owned_rows(tmp_path, stores):
    sql = stores["sql"]
    with journal(tmp_path, stores) as run:
        pid = add_project(sql, run); did, v1, v2 = uuid4(), uuid4(), uuid4()
        sql.create(run, [Document(id=did, project_id=pid, document_code=str(did), title="input", source_type="file_upload"),
            DocumentVersion(id=v1, project_id=pid, document_id=did, version_major=1, extraction_revision=0, version_label="v1.0", status="uploaded"),
            DocumentVersion(id=v2, project_id=pid, document_id=did, version_major=2, extraction_revision=0, version_label="v2.0", status="uploaded")])
        with sql.engine.begin() as c:
            c.execute(update(DocumentVersion).where(DocumentVersion.id == v1).values(source_version_id=v2))
            c.execute(update(DocumentVersion).where(DocumentVersion.id == v2).values(source_version_id=v1))
        cleanup_run(run, stores)
        assert not exists(sql, DocumentVersion, v1) and not exists(sql, DocumentVersion, v2)


def test_shared_model_and_role_unchanged(tmp_path, stores):
    sql = stores["sql"]; rid, mid, user = uuid4(), uuid4(), retained_user(sql)
    with Session(sql.engine) as session:
        session.add_all([Role(id=rid, name="retained-" + str(rid)),
            AIModel(id=mid, name="retained-" + str(mid), model_type="Embedding", provider="storage-input-only", is_active=False)])
        session.commit()
    with journal(tmp_path, stores) as run:
        project = Project(id=uuid4(), name="owned", embedding_model_id=mid)
        sql.create(run, [project, RoleUser(role_id=rid, user_id=user, source="manual")])
        cleanup_run(run, stores)
        assert exists(sql, AIModel, mid) and exists(sql, Role, rid) and exists(sql, User, user)


def test_actual_custom_trigger_requires_review(tmp_path, stores):
    sql = stores["sql"]; function = "e2e_trigger_" + uuid4().hex
    with journal(tmp_path, stores) as run:
        pid = add_project(sql, run)
        with sql.engine.begin() as c:
            c.execute(text(f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END $$"))
            c.execute(text(f"CREATE TRIGGER {function} BEFORE DELETE ON projects FOR EACH ROW EXECUTE FUNCTION {function}()"))
        try:
            with pytest.raises(CleanupConflict, match="sql_custom_trigger_requires_review"): cleanup_run(run, stores)
            assert exists(sql, Project, pid)
        finally:
            with sql.engine.begin() as c:
                c.execute(text(f"DROP TRIGGER {function} ON projects"))
                c.execute(text(f"DROP FUNCTION {function}()"))
        cleanup_run(run, stores)


def test_no_adoption_on_duplicate_graph_create(tmp_path, stores):
    graph = stores["graph"]
    with journal(tmp_path, stores) as a, journal(tmp_path, stores, "b") as b:
        node = graph.create_node(b, "Project")
        with pytest.raises(CleanupConflict, match="graph_resource_exists"):
            graph.create_node(a, "Project", {"id": node["identity"]["id"]})
        with pytest.raises(CleanupConflict, match="graph_ownership_changed"): cleanup_run(a, stores)
        with graph.prepare([node]) as batch: assert batch.nodes
        cleanup_run(b, stores)
        # An unconfirmed intent that is actually absent is safe to finish.
        cleanup_run(a, stores)


def test_object_unconfirmed_version_refuses(tmp_path, stores):
    with journal(tmp_path, stores) as run:
        run.intent("object", {"bucket": stores["object"].bucket, "key": "e2e/" + run.data["run_id"] + "/" + uuid4().hex})
        with pytest.raises(CleanupConflict, match="object_receipt_unconfirmed"): cleanup_run(run, stores)
        assert run.data["state"] == "cleanup_failed"


def test_owned_manifest_project_match_and_unowned_identity_rejection(tmp_path, stores):
    from scripts.e2e_governance_fixture import exact_project
    with journal(tmp_path, stores) as run:
        pid = add_project(stores["sql"], run)
        exact_project(run, pid)
        with pytest.raises(CleanupConflict, match="project_not_in_receipt"): exact_project(run, uuid4())
        cleanup_run(run, stores)


def test_actual_same_name_index_replacement_is_retained(tmp_path, stores):
    index = stores["index"]
    with journal(tmp_path, stores) as run:
        entry = index.create(run); name = entry["identity"]["name"]
        index.request("DELETE", "/" + name)
        index.request("PUT", "/" + name, {"settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"_meta": entry["proof"]["marker"]}})
        replacement_uuid = index.request("GET", "/" + name)[name]["settings"]["index"]["uuid"]
        assert replacement_uuid != entry["proof"]["uuid"]
        with pytest.raises(CleanupConflict, match="index_ownership_changed"): cleanup_run(run, stores)
        assert index.request("GET", "/" + name)[name]["settings"]["index"]["uuid"] == replacement_uuid


def test_foreign_run_cannot_add_document_to_other_owned_index(tmp_path, stores):
    index = stores["index"]
    with journal(tmp_path, stores) as a, journal(tmp_path, stores, "b") as b:
        entry = index.create(b)
        with pytest.raises(CleanupConflict, match="index_not_in_run_receipt"):
            index.create_document(a, entry, {"unowned": True})
        assert index.check(entry)
        cleanup_run(a, stores); cleanup_run(b, stores)
