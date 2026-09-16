"""Real Flyway/SQL/restore and real OIDC/API V049 rehearsal, two explicit modes.

Host tests require the guarded runner's private journal. Container API tests
use only fresh test credentials and the explicitly isolated service aliases.
No mocks, auth overrides, Provider, inherited .env or ORM schema creation.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import UUID, uuid4

import pytest

API = os.environ.get("V49_API") == "1"

if not API:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from chg291_v049_rehearsal import Rehearsal, SQL, SQL_SHA, digest

    @pytest.fixture(scope="module")
    def lab():
        assert "V49_STATE" in os.environ, "Use approved isolated runner"
        r = Rehearsal(os.environ["V49_STATE"])
        r.guard()
        base = r.database("base")
        r.migrate(base, 48)
        r.base_dump = r.backup(base)
        return r

    def new_db(lab, label):
        db = lab.database(label)
        lab.restore(db, lab.base_dump)
        return db

    def seed(lab, db, roles=("editor", "viewer"), *, owner_side="both", archived=False):
        owner, member, project = (str(uuid4()) for _ in range(3))
        statements = [f"INSERT INTO users(id,keycloak_user_id,display_name) VALUES ('{owner}','{uuid4()}','Synthetic Owner'),('{member}','{uuid4()}','Synthetic Member')",
            f"INSERT INTO projects(id,name,status) VALUES ('{project}','Synthetic V049 project','active')"]
        if owner_side in {"both", "governance"}:
            statements.append(f"INSERT INTO project_owners(project_id,user_id) VALUES ('{project}','{owner}')")
        if owner_side in {"both", "membership"}:
            statements.append(f"INSERT INTO project_members(project_id,user_id,project_role) VALUES ('{project}','{owner}','owner')")
        for role in roles:
            assert role in {"owner", "editor", "viewer"}
            statements.append(f"INSERT INTO project_members(project_id,user_id,project_role) VALUES ('{project}','{member}','{role}')")
        if "owner" in roles:
            statements.append(f"INSERT INTO project_owners(project_id,user_id) VALUES ('{project}','{member}')")
        if archived:
            statements.append(f"UPDATE projects SET status='archived',archived_at=now(),archived_by='{owner}' WHERE id='{project}'")
        lab.psql(db, "BEGIN;" + ";".join(statements) + ";COMMIT;")
        return owner, member, project

    def members(lab, db):
        return lab.query(db, "SELECT json_agg(x ORDER BY project_id,user_id,project_role) FROM (SELECT project_id,user_id,project_role,created_at FROM project_members) x")

    def assert_parity(lab, db):
        assert lab.query(db, """SELECT count(*) FROM (
            (SELECT project_id,user_id FROM project_owners EXCEPT SELECT project_id,user_id FROM project_members WHERE project_role='owner')
            UNION ALL (SELECT project_id,user_id FROM project_members WHERE project_role='owner' EXCEPT SELECT project_id,user_id FROM project_owners)) x""") == 0

    def record(lab, case, **values):
        lab.state["operations"].append({"case": case, **values})
        lab.save()

    def test_01_isolation_and_original_v048(lab):
        lab.guard("v49_base")
        assert lab.query("v49_base", "SELECT max(version::integer) FROM flyway_schema_history WHERE success") == 48
        assert lab.query("v49_base", "SELECT count(*) FROM pg_constraint WHERE conname='uq_project_members_project_user'") == 0
        with pytest.raises(AssertionError):
            lab.guard("nomosmart")
        assert lab.state["images"]["backend"].startswith("sha256:")
        record(lab, "V49-R01", postgres_version=lab.psql("v49_base", "SHOW server_version").stdout.decode().strip(), sql_sha256=SQL_SHA)

    def test_02_exact_change_and_actual_restore(lab):
        db = new_db(lab, "exact")
        owner, member, project = seed(lab, db)
        before = lab.snapshot(db)
        before_rows = members(lab, db)
        dump = lab.backup(db)
        restored = lab.database("restore_before")
        lab.restore(restored, dump)
        assert lab.snapshot(restored) == before
        lab.migrate(db)
        after = lab.snapshot(db)
        expected = [x for x in before_rows if not (x["user_id"] == member and x["project_role"] == "viewer")]
        assert members(lab, db) == expected
        assert before["project_owners"] == after["project_owners"]
        exceptions = {"project_members", "audit_logs", "flyway_schema_history", "_constraints", "_acl"}
        assert {k:v for k,v in before.items() if k not in exceptions} == {k:v for k,v in after.items() if k not in exceptions}
        assert after["audit_logs"]["count"] == before["audit_logs"]["count"] + 1
        assert after["flyway_schema_history"]["count"] == before["flyway_schema_history"]["count"] + 1
        new_constraints = [x for x in after["_constraints"] if x not in before["_constraints"]]
        assert len(new_constraints) == 1 and new_constraints[0]["conname"] == "uq_project_members_project_user"
        assert [x for x in after["_acl"] if x not in before["_acl"]] == [
            {"relname": "uq_project_members_project_user", "relkind": "i", "owner": "v49_migrator", "relacl": None}]
        assert_parity(lab, db)
        lab.migrate(db)
        assert lab.snapshot(db) == after
        again = lab.database("restore_after_upgrade")
        lab.restore(again, dump)
        assert lab.snapshot(again) == before and len(members(lab, again)) == 3
        record(lab, "V49-R02/R05/R06/R09", before_digest=digest(before), after_digest=digest(after),
               restored_digest=digest(lab.snapshot(again)), removed_membership_count=1, owner_unchanged=True,
               unrelated_data_unchanged=True, source_tables=len([k for k in before if not k.startswith('_')]))

    @pytest.mark.parametrize("roles,side,archived,expected", [
        (("owner","editor","viewer"), "both", False, "owner"),
        (("editor","viewer"), "governance", False, "editor"),
        (("viewer",), "membership", False, "viewer"),
        (("editor","viewer"), "both", True, "editor"),
    ])
    def test_03_role_owner_and_archived_matrix(lab, roles, side, archived, expected):
        db = new_db(lab, "matrix_" + uuid4().hex[:8])
        owner, member, project = seed(lab, db, roles, owner_side=side, archived=archived)
        lab.migrate(db)
        assert_parity(lab, db)
        assert lab.query(db, f"SELECT json_agg(project_role) FROM project_members WHERE user_id='{member}'") == [expected]
        assert lab.query(db, f"SELECT json_agg(project_role) FROM project_members WHERE user_id='{owner}'") == ["owner"]
        after = lab.snapshot(db)
        result = lab.psql(db, f"INSERT INTO project_members(project_id,user_id,project_role) VALUES ('{project}','{member}','{'viewer' if expected != 'viewer' else 'editor'}')", check=False)
        assert result.returncode != 0 and b"uq_project_members_project_user" in result.stderr
        assert lab.snapshot(db) == after
        lab.migrate(db)
        assert lab.snapshot(db) == after
        record(lab, "V49-R03/R05", roles=roles, owner_side=side, archived=archived, retained=expected)

    def test_04_ownerless_failure_no_partial_changes(lab):
        db = new_db(lab, "ownerless")
        seed(lab, db, owner_side="none")
        before = lab.snapshot(db)
        result = lab.migrate(db, check=False)
        assert result.returncode != 0 and b"project_without_owner" in result.stderr + result.stdout
        after = lab.snapshot(db)
        # PostgreSQL transactional Flyway migration must not leave partial SQL or success history.
        assert after == before
        record(lab, "V49-R04", unchanged_digest=digest(after), flyway_failure_history_rows=
               lab.query(db, "SELECT count(*) FROM flyway_schema_history WHERE NOT success"))

    def test_05_lock_timeout_is_atomic(lab):
        db = new_db(lab, "locked")
        seed(lab, db)
        before = lab.snapshot(db)
        # Real concurrent PG connection holds the same writer lock; no sleep-only simulation.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lab.docker, "exec", "-i", lab.state["services"]["pg"], "psql", "-X", "-U", "postgres", "-d", db,
                         "-v", "ON_ERROR_STOP=1", "-Atq", data=b"BEGIN; LOCK TABLE projects IN ROW EXCLUSIVE MODE; SELECT pg_sleep(12); ROLLBACK;")
            for _ in range(40):
                locked = lab.query(db, "SELECT count(*) FROM pg_locks WHERE relation='projects'::regclass AND mode='RowExclusiveLock' AND granted")
                if locked:
                    break
                time.sleep(0.1)
            assert locked
            result = lab.migrate(db, check=False, timeout_lock=True)
            assert result.returncode != 0 and b"lock timeout" in result.stderr + result.stdout
            future.result(timeout=20)
        assert lab.snapshot(db) == before
        record(lab, "V49-R08", timeout_rollback_digest=digest(before))

    def test_06_sql_idempotence_separate_from_flyway(lab):
        db = new_db(lab, "sql_rerun")
        seed(lab, db)
        lab.migrate(db)
        before = lab.snapshot(db)
        lab.psql(db, SQL.read_text())
        assert lab.snapshot(db) == before

    @pytest.mark.parametrize("source,version", [("deployed",48),("deployed",49),("current",48),("current",49)])
    def test_07_authentic_api_compatibility(lab, source, version):
        db = new_db(lab, f"api_{source}_{version}")
        if version == 49:
            lab.migrate(db)
        lab.api(db, source, f"{source}-{version}")
        if source == "current" and version == 49:
            # Do not revert schema/data when trying the old application artifact.
            lab.api(db, "deployed", "rollback-49")
        record(lab, "V49-R07/R09", source=source, schema_version=version)

else:
    import httpx
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import Session
    from app.core.config import get_settings
    from app.db.models import Project, ProjectMember, ProjectOwner, Role, RolePermission, RoleUser, User
    from app.db.session import get_engine
    from app.main import create_app
    from app.security.auth import JWTValidator

    @pytest.fixture(scope="module")
    def auth():
        import app
        expected_root = "/current/app" if os.environ["V49_API_SOURCE"] == "current" else "/app/app"
        assert str(Path(app.__file__).resolve()).startswith(expected_root + "/"), "Wrong application source loaded"
        from urllib.parse import urlparse
        assert os.environ.get("V49_RUN", "").startswith("v49-")
        assert urlparse(os.environ["DATABASE_URL"]).hostname == "pg"
        assert urlparse(os.environ["DATABASE_URL"]).path == "/" + os.environ["V49_DB"]
        assert os.environ["V49_KC_URL"] == "http://kc:8080"
        http = httpx.Client(base_url=os.environ["V49_KC_URL"], timeout=15, trust_env=False)
        for _ in range(70):
            try:
                if http.get("/realms/master/.well-known/openid-configuration").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            pytest.fail("real isolated Keycloak unavailable")
        def admin_headers():
            r = http.post("/realms/master/protocol/openid-connect/token", data={"client_id":"admin-cli", "grant_type":"password",
                          "username":"v49-admin", "password":os.environ["V49_KC_PASSWORD"]})
            r.raise_for_status()
            return {"Authorization":"Bearer " + r.json()["access_token"]}
        realm = "v49-" + uuid4().hex
        password = uuid4().hex
        labels = ("owner", "member", "second", "viewer", "outsider")
        r = http.post("/admin/realms", headers=admin_headers(), json={"realm":realm, "enabled":True,
            "clients":[{"clientId":"v49-test", "publicClient":True, "directAccessGrantsEnabled":True,
                "protocolMappers":[{"name":"aud", "protocol":"openid-connect", "protocolMapper":"oidc-audience-mapper",
                                    "config":{"included.custom.audience":"v49-test", "access.token.claim":"true"}}]}],
            "users":[{"username":label, "firstName":"Synthetic", "lastName":label,
                      "email":label + "@v049.invalid", "emailVerified":True,"enabled":True,
                      "credentials":[{"type":"password","value":password,"temporary":False}]} for label in labels]})
        r.raise_for_status()
        os.environ.update({"OIDC_ISSUER_URL":"http://kc:8080/realms/" + realm, "OIDC_AUDIENCE":"v49-test"})
        get_settings.cache_clear(); get_engine.cache_clear()
        settings = get_settings()
        engine = create_engine(settings.database_url.get_secret_value())
        validator = JWTValidator(settings)
        identities, headers = {}, {}
        try:
            with Session(engine) as session:
                role = Role(name="V049 menu " + uuid4().hex)
                session.add(role); session.flush()
                session.add(RolePermission(role_id=role.id,module_name="Menu",function_name="KnowledgeProjects",can_view=True))
                for label in labels:
                    response = http.post(f"/realms/{realm}/protocol/openid-connect/token", data={"client_id":"v49-test",
                              "grant_type":"password", "username":label,"password":password})
                    response.raise_for_status()
                    token = response.json()["access_token"]
                    principal = validator.validate(token)
                    user = User(keycloak_user_id=principal.subject,display_name="Synthetic " + label)
                    session.add(user);session.flush()
                    session.add(RoleUser(role_id=role.id,user_id=user.id,source="manual"))
                    identities[label] = user.id
                    headers[label] = {"Authorization":"Bearer " + token}
                session.commit()
            with TestClient(create_app(settings), raise_server_exceptions=False) as client:
                yield engine, client, identities, headers
        finally:
            http.delete("/admin/realms/"+realm,headers=admin_headers()).raise_for_status()
            http.close();engine.dispose()
            if get_engine.cache_info().currsize:
                get_engine().dispose()
            get_engine.cache_clear();get_settings.cache_clear()

    @pytest.fixture
    def project(auth):
        engine, client, users, headers = auth
        with Session(engine) as session:
            p = Project(name="V049 API " + uuid4().hex,status="active")
            session.add(p);session.flush()
            for label,role in (("owner","owner"),("member","editor"),("viewer","viewer")):
                session.add(ProjectMember(project_id=p.id,user_id=users[label],project_role=role,created_at=datetime.now(UTC)))
            session.add(ProjectOwner(project_id=p.id,user_id=users["owner"],created_at=datetime.now(UTC)))
            ident = p.id
            session.commit()
        return ident

    def state(auth, project):
        engine, _, _, _ = auth
        with engine.connect() as c:
            return {"lock":c.scalar(text("SELECT lock_version FROM projects WHERE id=:id"),{"id":project}),
                "members":c.execute(text("SELECT user_id,project_role,created_at FROM project_members WHERE project_id=:id ORDER BY user_id,project_role"),{"id":project}).all(),
                "owners":c.execute(text("SELECT user_id,created_at FROM project_owners WHERE project_id=:id ORDER BY user_id"),{"id":project}).all(),
                "audits":c.execute(text("SELECT action,result,summary FROM audit_logs WHERE resource_id=:id ORDER BY id"),{"id":project}).all()}

    def put(auth, project, label, roles, lock=1, actor="owner"):
        _, client, users, headers = auth
        return client.put(f"/api/v1/projects/{project}/members/{users[label]}",headers=headers[actor],json={"roles":roles,"lock_version":lock})

    def test_api_single_replace_and_owner_parity(auth, project):
        _, client, users, headers = auth
        before = state(auth,project)
        r = put(auth,project,"member",["viewer"])
        assert r.status_code == 200, r.text
        assert next(x for x in r.json() if x["user_id"] == str(users["member"]))["roles"] == ["viewer"]
        after = state(auth,project)
        assert after["lock"] == before["lock"]+1 and len(after["audits"]) == len(before["audits"])+1
        assert after["owners"] == before["owners"]
        assert put(auth,project,"member",["owner"],lock=2).status_code == 200
        assert put(auth,project,"member",["editor"],lock=3).status_code == 200
        final = state(auth,project)
        assert final["owners"] == before["owners"] and final["lock"] == 4
        for _,result,summary in final["audits"]:
            assert result == "success" and len(summary["roles"]) == 1
        loaded = client.get(f"/api/v1/projects/{project}/members",headers=headers["owner"])
        assert loaded.status_code == 200 and all(len(row["roles"]) == 1 for row in loaded.json())

    def test_api_legacy_read_keeps_storage_unchanged(auth, project):
        engine,client,users,headers=auth
        with engine.begin() as c:
            constrained=c.scalar(text("SELECT count(*) FROM pg_constraint WHERE conname='uq_project_members_project_user'"))
            if not constrained:
                c.execute(text("INSERT INTO project_members(project_id,user_id,project_role) VALUES (:p,:u,'viewer')"),
                          {"p":project,"u":users["member"]})
        before=state(auth,project)
        loaded=client.get(f"/api/v1/projects/{project}/members",headers=headers["owner"])
        assert loaded.status_code==200
        assert next(row for row in loaded.json() if row["user_id"]==str(users["member"]))["roles"]==["editor"]
        assert all(len(row["roles"])==1 for row in loaded.json())
        assert state(auth,project)==before  # projection must never backfill old rows
        assert len(before["members"]) == (3 if constrained else 4)

    def test_real_sql_role_policies_and_scope(auth,project):
        from app.core.errors import AppError
        from app.security.project_roles import project_roles, has_project_role, require_project_role
        engine,_,users,_=auth
        with Session(engine) as session:
            for label,expected in (("owner",{"owner"}),("member",{"editor"}),("viewer",{"viewer"}),("outsider",set())):
                assert project_roles(session,project,users[label])==expected
                assert has_project_role(session,project,users[label],frozenset({"owner"})) == (label=="owner")
            require_project_role(session,project,users["owner"],{project},frozenset({"owner"}))
            with pytest.raises(AppError) as denied:
                require_project_role(session,project,users["viewer"],{project},frozenset({"owner"}))
            assert denied.value.status_code==403
            with pytest.raises(AppError):
                require_project_role(session,project,users["outsider"],set(),frozenset({"owner"}))

    @pytest.mark.parametrize("roles",[[],["editor","viewer"],["viewer","viewer"],["unknown"]])
    def test_api_invalid_cardinality_atomic(auth,project,roles):
        before=state(auth,project)
        assert put(auth,project,"member",roles).status_code == 422
        assert state(auth,project) == before

    def test_api_stale_and_denied_actor(auth,project):
        before=state(auth,project)
        assert put(auth,project,"member",["viewer"],lock=999).status_code == 409
        assert state(auth,project) == before
        for actor in ("member","viewer","outsider"):
            assert put(auth,project,"member",["owner"],actor=actor).status_code in (403,404)
            assert state(auth,project) == before

    def test_api_only_and_self_owner_protected(auth,project):
        _,client,users,headers=auth
        for second in (False,True):
            if second:
                assert put(auth,project,"second",["owner"]).status_code == 200
            before=state(auth,project)
            assert put(auth,project,"owner",["viewer"],lock=before["lock"]).status_code == 409
            assert state(auth,project) == before
            removed=client.delete(f"/api/v1/projects/{project}/members/{users['owner']}",headers=headers["owner"],params={"lock_version":before["lock"]})
            assert removed.status_code == 409
            assert state(auth,project) == before

    def test_api_concurrent_changes_one_success(auth,project):
        before=state(auth,project)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(put,auth,project,"member",[role]) for role in ("viewer","owner")]
            responses=[f.result(timeout=20) for f in futures]
        assert sorted(r.status_code for r in responses) == [200,409], [r.text for r in responses]
        after=state(auth,project)
        assert after["lock"] == before["lock"]+1 and len(after["audits"]) == len(before["audits"])+1
        _,_,users,_=auth
        member_roles=[role for uid,role,_ in after["members"] if uid==users["member"]]
        assert len(member_roles)==1
        assert (users["member"] in [uid for uid,_ in after["owners"]]) == (member_roles==["owner"])
