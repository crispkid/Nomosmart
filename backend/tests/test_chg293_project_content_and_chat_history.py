"""CHG-293: direct policies and real disposable PostgreSQL history tests.

Live cases require CHG293_DATABASE_URL pointing to a disposable test service.
No production defaults or authentication dependency overrides. The two staging
positive cases explicitly require the approved live Embedding/index prerequisite;
history access itself is checked not to create additional Provider usage.
"""
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import ChatRecord, Project, User
from app.domain.project_access import archive_authority
from app.domain.chat_conversations import conversation_identities, require_conversation_identity


@pytest.mark.parametrize("roles,owner,grant,allowed", [
    ({"editor"}, False, True, False), ({"editor", "viewer"}, False, True, False),
    ({"editor"}, False, False, False), ({"owner", "editor"}, True, False, True),
    ({"viewer"}, False, True, True), ({"viewer"}, False, False, False),
    (set(), False, False, False),
])
def test_archive_editor_deny(roles, owner, grant, allowed):
    assert archive_authority(roles, is_owner=owner, can_execute=grant) is allowed


@pytest.fixture(scope="module")
def live_engine():
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from current_native_support import native_database
        with native_database() as engine:
            yield engine
        return
    url = os.environ.get("CHG293_DATABASE_URL")
    if not url:
        pytest.fail("CHG293_DATABASE_URL must identify a disposable PostgreSQL service")
    scope_file=os.environ.get("NOMOSMART_CHG315_TEST_SCOPE")
    if scope_file:
        # Current migrations contain public-schema tables. Reuse the genuinely
        # migrated empty template only inside this run's disposable cluster.
        scope_path=Path(scope_file)
        assert str(scope_path.parent).startswith('/private/tmp/nomosmart-chg315-')
        assert not scope_path.is_symlink() and scope_path.stat().st_uid == os.getuid()
        assert scope_path.stat().st_mode & 0o077 == 0
        scope=json.loads(scope_path.read_text())
        parsed=make_url(url)
        assert (parsed.host,parsed.port,parsed.username,parsed.password) == (scope['host'],scope['port'],scope['username'],scope['password'])
        assert parsed.query.get('sslmode') == 'verify-full' and parsed.query.get('sslrootcert') == scope['ca']
        def owned_cluster():
            inspected=subprocess.run(['docker','inspect',scope['container']],capture_output=True,text=True,check=True)
            labels=json.loads(inspected.stdout)[0]['Config']['Labels']
            assert labels.get('nomosmart.chg315.run_id') == scope['run_id']
        owned_cluster()
        root=Path(__file__).resolve().parents[2]
        contract=json.loads((root/'deploy/migrations/release-contract.json').read_text())
        targets=list(contract['targets'].values())
        for target in targets:
            assert hashlib.sha256((root/'sql/migrations'/target['file']).read_bytes()).hexdigest() == target['sha256']
        template=create_engine(parsed.set(database='chg315_fresh'))
        with template.connect() as connection:
            assert connection.scalar(text('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()')) is True
            assert connection.scalar(text('SELECT max(version::int) FROM public.flyway_schema_history WHERE success')) == int(contract['required_version'])
            applied=connection.execute(text('SELECT script,checksum FROM public.flyway_schema_history WHERE version=:version AND success'),
                {'version':contract['required_version']}).one()
            assert tuple(applied) in [(target['file'],target['checksum']) for target in targets]
            assert connection.scalar(text('SELECT count(*) FROM public.projects')) == 0
            assert connection.scalar(text('SELECT count(*) FROM public.ai_models')) == 0
        template.dispose()
        name='chg293_'+uuid4().hex
        admin=create_engine(parsed.set(database='postgres'),isolation_level='AUTOCOMMIT')
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE chg315_fresh'))
        engine=create_engine(parsed.set(database=name))
        marker=str(uuid4())
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE public.chg293_test_ownership (run_id uuid NOT NULL, marker uuid NOT NULL)'))
                connection.execute(text('INSERT INTO public.chg293_test_ownership VALUES (:run_id,:marker)'),{'run_id':scope['run_id'],'marker':marker})
            yield engine
        finally:
            owned_cluster()
            with engine.connect() as connection:
                assert tuple(connection.execute(text('SELECT run_id,marker FROM public.chg293_test_ownership')).one()) == (UUID(scope['run_id']),UUID(marker))
            engine.dispose()
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            admin.dispose()
        return
    schema = "chg293_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        # The verified service can already have pgcrypto in public. Keep tables
        # strictly in our schema, exposing only the genuine extension function.
        extension_schema = connection.scalar(text("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pgcrypto'"))
        if extension_schema:
            assert extension_schema == 'public'
            connection.execute(text(f'CREATE FUNCTION "{schema}".digest(bytea,text) RETURNS bytea LANGUAGE SQL IMMUTABLE STRICT AS $$ SELECT public.digest($1,$2) $$'))
    engine = create_engine(admin.url.update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for migration in sorted((Path(__file__).resolve().parents[2] / "sql/migrations").glob("V*.sql")):
                version = int(migration.name.split("__", 1)[0][1:])
                # Current application guards read the V050/V051 execution
                # tables even for a document with no running extraction.
                # Keep this fresh schema aligned with the tested application.
                if version > 51 or version == 42:
                    continue
                with connection.connection.cursor() as cursor:
                    cursor.execute(migration.read_text())
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def live_session(live_engine):
    with Session(live_engine, expire_on_commit=False) as session:
        yield session
        session.rollback()


def history(session, *, conversation_id=None, actor=None, project=None, scope="published", versions=None, deleted=False, document_version_id=None):
    actor = actor or User(keycloak_user_id=uuid4().hex, display_name="Same name")
    project = project or Project(name="CHG293 isolated history", status="active")
    session.add_all([actor, project])
    session.flush()
    now = datetime.now(UTC)
    row = ChatRecord(project_id=project.id, conversation_id=conversation_id or uuid4(),
        document_version_id=document_version_id,
        scope_mode=scope, selected_document_version_ids=[str(x) for x in (versions or [uuid4()])],
        question="Stored test history, not a generated answer", answer="Stored evidence",
        created_by=actor.id, asked_at=now, created_at=now, deleted_at=now if deleted else None)
    session.add(row)
    session.flush()
    return row, actor, project


def test_foreign_creator_cannot_reuse_existing_uuid(live_session):
    row, actor, project = history(live_session)
    other = User(keycloak_user_id=uuid4().hex, display_name=actor.display_name)
    live_session.add(other)
    live_session.flush()
    with pytest.raises(AppError) as denied:
        require_conversation_identity(live_session, project_id=project.id, conversation_id=row.conversation_id,
            user_id=other.id, scope_mode="published", requested_ids={uuid4()})
    assert denied.value.code == "conversation_read_only"


@pytest.mark.parametrize("deleted,scope", [(True, "published"), (False, None)])
def test_deleted_and_legacy_ids_are_not_new(live_session, deleted, scope):
    row, actor, project = history(live_session, deleted=deleted, scope=scope)
    with pytest.raises(AppError) as denied:
        require_conversation_identity(live_session, project_id=project.id, conversation_id=row.conversation_id,
            user_id=actor.id, scope_mode="published", requested_ids={uuid4()})
    assert denied.value.status_code == 404


def test_mixed_creators_are_not_guessed(live_session):
    row, actor, project = history(live_session)
    history(live_session, conversation_id=row.conversation_id, project=project, versions=row.selected_document_version_ids)
    identity = conversation_identities(live_session, [row.conversation_id])[row.conversation_id]
    assert not identity.valid
    with pytest.raises(AppError) as conflict:
        require_conversation_identity(live_session, project_id=project.id, conversation_id=row.conversation_id,
            user_id=actor.id, scope_mode="published", requested_ids={uuid4()})
    assert conflict.value.code == "conversation_identity_conflict"


def test_same_uuid_is_serialized_across_real_connections(live_engine):
    from app.domain.chat_conversations import lock_conversation
    cid = uuid4()
    with Session(live_engine, expire_on_commit=False) as first:
        lock_conversation(first, cid)
        def competing():
            with Session(live_engine) as second:
                with pytest.raises(AppError) as busy:
                    lock_conversation(second, cid)
                assert busy.value.code == "conversation_busy"
                lock_conversation(second, uuid4())  # unrelated requests are independent
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(competing).result(timeout=5)
        row, actor, project = history(first, conversation_id=cid)
        actor_id, project_id = actor.id, project.id
        first.commit()
    with Session(live_engine) as later:
        with pytest.raises(AppError) as denied:
            require_conversation_identity(later, project_id=project_id, conversation_id=cid,
                user_id=uuid4(), scope_mode="published", requested_ids={uuid4()})
        assert denied.value.code == "conversation_read_only"
        later.rollback()
        identity = require_conversation_identity(later, project_id=project_id, conversation_id=cid,
            user_id=actor_id, scope_mode="published", requested_ids={UUID(x) for x in row.selected_document_version_ids})
        assert identity.creator_id == actor_id


@pytest.mark.parametrize("fixed_scope", [[], ["not-a-uuid"], {"unexpected": "shape"}])
def test_malformed_stored_fixed_scope_fails_closed(live_session, fixed_scope):
    row, actor, project = history(live_session)
    row.selected_document_version_ids = fixed_scope
    live_session.flush()
    identity = conversation_identities(live_session, [row.conversation_id])[row.conversation_id]
    assert not identity.valid
    with pytest.raises(AppError) as denied:
        require_conversation_identity(live_session, project_id=project.id,
            conversation_id=row.conversation_id, user_id=actor.id,
            scope_mode="published", requested_ids=None)
    assert denied.value.code == "conversation_identity_conflict"


@pytest.fixture(scope="module")
def authenticated(request):
    """Real Keycloak tokens/JWKS, real FastAPI dependencies, disposable database."""
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_history_support import current_history_actors
        with current_history_actors() as value:
            yield value
        return
    live_engine = request.getfixturevalue('live_engine')
    import httpx
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.db.session import get_engine
    from app.main import create_app
    from app.security.auth import JWTValidator
    from app.db.models import Role, RolePermission, RoleUser

    base = os.environ.get("CHG293_KEYCLOAK_URL")
    if not base:
        pytest.fail("CHG293_KEYCLOAK_URL must identify a disposable Keycloak service")
    http = httpx.Client(base_url=base, timeout=20)
    def fresh_admin_headers():
        response = http.post("/realms/master/protocol/openid-connect/token", data={
            "client_id": "admin-cli", "grant_type": "password", "username": os.environ["CHG293_KEYCLOAK_ADMIN"],
            "password": os.environ["CHG293_KEYCLOAK_PASSWORD"]})
        response.raise_for_status()
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    admin_headers = fresh_admin_headers()
    realm, password = "chg293-" + uuid4().hex, uuid4().hex
    labels = ["owner", "editor", "viewer", "outsider"]
    response = http.post("/admin/realms", headers=admin_headers, json={"realm": realm, "enabled": True,
        "clients": [{"clientId": "chg293-test", "publicClient": True, "directAccessGrantsEnabled": True,
            "protocolMappers": [{"name": "aud", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
                "config": {"included.custom.audience": "chg293-test", "access.token.claim": "true"}}]}],
        "users": [{"username": label, "firstName": "Same", "lastName": "Name", "emailVerified": True,
                   "email": label + "@chg293.invalid", "enabled": True,
                   "credentials": [{"type": "password", "value": password, "temporary": False}]} for label in labels]})
    response.raise_for_status()
    env = {"APP_ENV": "test", "DATABASE_URL": live_engine.url.render_as_string(hide_password=False),
           "OIDC_ISSUER_URL": base + "/realms/" + realm, "OIDC_AUDIENCE": "chg293-test",
           # Model-bearing cases use the existing isolated stack's encryption
           # key, not a new key that cannot decrypt its approved model copies.
           "APP_ENCRYPTION_KEY": (os.environ["APP_ENCRYPTION_KEY"]
               if os.environ.get("CHG305_LIVE_STAGING_MODELS") == "1"
               else uuid4().hex + uuid4().hex), "LOG_LEVEL": "ERROR"}
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        settings = get_settings()
        validator = JWTValidator(settings)
        users, headers = {}, {}
        with Session(live_engine, expire_on_commit=False) as session:
            role = Role(name="CHG293 menu " + uuid4().hex, is_active=True)
            archive_role = Role(name="CHG293 execute " + uuid4().hex, is_active=True)
            session.add_all([role, archive_role]); session.flush()
            session.add_all([RolePermission(role_id=role.id, module_name="Menu", function_name="KnowledgeProjects", can_view=True),
                            RolePermission(role_id=archive_role.id, module_name="Project", function_name="ProjectArchive", can_execute=True)])
            for label in labels:
                token_response = http.post(f"/realms/{realm}/protocol/openid-connect/token", data={
                    "client_id": "chg293-test", "grant_type": "password", "username": label, "password": password})
                token_response.raise_for_status()
                token = token_response.json()["access_token"]
                principal = validator.validate(token)
                user = User(keycloak_user_id=principal.subject, display_name="Same name", is_active=True)
                session.add(user); session.flush()
                session.add(RoleUser(role_id=role.id, user_id=user.id, source="manual"))
                if label == "editor":
                    session.add(RoleUser(role_id=archive_role.id, user_id=user.id, source="manual"))
                users[label], headers[label] = user, {"Authorization": "Bearer " + token}
            session.commit()
        with TestClient(create_app(settings)) as client:
            yield client, users, headers
    finally:
        if get_engine.cache_info().currsize:
            get_engine().dispose()
        get_engine.cache_clear(); get_settings.cache_clear()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        # Browser acceptance can outlive Keycloak's short admin access-token TTL.
        # Authenticate normally again; never extend token lifetimes or skip cleanup.
        try:
            http.delete("/admin/realms/" + realm, headers=fresh_admin_headers()).raise_for_status()
        finally:
            http.close()


@pytest.fixture
def scoped_data(authenticated, request):
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_history_support import current_history_case
        with current_history_case(authenticated, request.node.nodeid, history) as value:
            yield value
        return
    live_engine = request.getfixturevalue('live_engine')
    from sqlalchemy import inspect
    from app.db.models import Chunk, Document, DocumentVersion, ProjectMember, ProjectOwner
    client, shared_users, headers = authenticated
    with Session(live_engine, expire_on_commit=False) as session:
        users = {label: session.get(User, inspect(actor).identity[0]) for label, actor in shared_users.items()}
        project = Project(name="CHG293 " + uuid4().hex, status="active", created_by=users["owner"].id)
        session.add(project); session.flush()
        session.add(ProjectOwner(project_id=project.id, user_id=users["owner"].id, created_at=datetime.now(UTC)))
        for label in ("owner", "editor", "viewer"):
            session.add(ProjectMember(project_id=project.id, user_id=users[label].id, project_role=label, created_at=datetime.now(UTC)))
        document = Document(project_id=project.id, document_code=uuid4().hex, title="CHG293 content", source_type="upload", status="inactive", created_by=users["owner"].id)
        session.add(document); session.flush()
        version = DocumentVersion(project_id=project.id, document_id=document.id, version_major=1,
                                  extraction_revision=1, version_label="v1.1", status="submission_ready")
        session.add(version); session.flush()
        session.add(Chunk(project_id=project.id, document_id=document.id, document_version_id=version.id,
                          chunk_index=1, title="Stored chunk", content="Stored isolated evidence", content_hash=uuid4().hex, status="active"))
        rows = {}
        for label in ("owner", "editor", "viewer"):
            row, _, _ = history(session, actor=users[label], project=project, scope="document_staging", versions=[version.id], document_version_id=version.id)
            rows[label] = row
        session.commit()
        yield client, users, headers, session, project, document, version, rows


def test_authenticated_shared_history_names_scope_and_paging(scoped_data):
    from live_staging_support import prepare_live_staging
    client, users, headers, session, project, document, version, rows = scoped_data
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_genuine_history_support import require_genuine_staging
        require_genuine_staging(session, project, document, version)
    else:
        prepare_live_staging(session, project, document, version)
    path = f"/api/v1/projects/{project.id}/chat/conversations"
    params = {"scope_mode": "document_staging", "document_version_id": str(version.id), "limit": 2}
    response = client.get(path, params=params, headers=headers["editor"])
    assert response.status_code == 200, response.text
    page = response.json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]
    following = client.get(path, params={**params, "cursor": page["next_cursor"]}, headers=headers["editor"])
    assert following.status_code == 200, following.text
    items = page["items"] + following.json()["items"]
    assert {item["id"] for item in items} == {str(row.conversation_id) for row in rows.values()}
    for item in items:
        own = item["created_by_user_id"] == str(users["editor"].id)
        assert item["created_by_display_name"] == "Same name"
        assert item["is_mine"] == own and item["can_continue"] == own
        assert item["can_evaluate"] == own and item["can_export"] == own and item["can_delete"] == own
        assert item["message_count"] == 1
        assert "email" not in item
    assert client.get(path, params={**params, "cursor": page["next_cursor"]}, headers=headers["viewer"]).status_code == 422
    assert client.get(path, params=params, headers=headers["outsider"]).status_code == 403
    assert client.get(path, params={"scope_mode": "published"}, headers=headers["editor"]).json()["items"] == []
    detail = client.get(path + "/" + str(rows["owner"].conversation_id), params={k: v for k, v in params.items() if k != "limit"}, headers=headers["editor"])
    assert detail.status_code == 200 and detail.json()["can_continue"] is False


def test_real_fixed_version_and_unused_only_guards(scoped_data):
    _, users, _, session, project, _, version, rows = scoped_data
    row = rows["owner"]
    with pytest.raises(AppError) as wrong_version:
        require_conversation_identity(session, project_id=project.id,
            conversation_id=row.conversation_id, user_id=users["owner"].id,
            scope_mode="document_staging", requested_ids={uuid4()})
    assert wrong_version.value.code == "conversation_not_found"
    with pytest.raises(AppError) as reused:
        require_conversation_identity(session, project_id=project.id,
            conversation_id=row.conversation_id, user_id=users["owner"].id,
            scope_mode="document_staging", requested_ids={version.id}, unused_only=True)
    assert reused.value.code == "conversation_identity_conflict"
    published, _, _ = history(session, actor=users["owner"], project=project,
        versions=[version.id], document_version_id=version.id)
    assert conversation_identities(session, [published.conversation_id])[published.conversation_id].valid
    published.selected_document_version_ids = [str(uuid4())]
    session.flush()
    assert not conversation_identities(session, [published.conversation_id])[published.conversation_id].valid


@pytest.mark.parametrize("actor", ["owner", "viewer"])
def test_authenticated_other_creator_mutations_denied_before_provider(scoped_data, actor):
    client, _, headers, session, project, _, version, rows = scoped_data
    row = rows["editor"]
    base = f"/api/v1/projects/{project.id}/chat"
    params = {"scope_mode": "document_staging", "document_version_id": str(version.id)}
    before = session.execute(text("SELECT count(*) FROM ai_model_usage_events")).scalar()
    response = client.post(base + "/query", headers=headers[actor], json={
        "question": "This must be rejected without Provider access", "scope_mode": "document_staging",
        "document_version_ids": [str(version.id)], "conversation_id": str(row.conversation_id)})
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "conversation_read_only"
    assert client.delete(base + "/conversations/" + str(row.conversation_id), params=params, headers=headers[actor]).status_code == 403
    assert client.get(base + "/conversations/" + str(row.conversation_id) + "/export.csv", params=params, headers=headers[actor]).status_code == 403
    assert client.post(base + "/records/" + str(row.id) + "/feedback", headers=headers[actor], json={"evaluation": "correct"}).status_code == 404
    session.refresh(row)
    assert row.deleted_at is None and row.evaluation == "not_evaluated"
    assert session.execute(text("SELECT count(*) FROM ai_model_usage_events")).scalar() == before


def test_editor_content_lifecycle_and_governance_are_separate(scoped_data):
    client, _, headers, session, project, document, _, _ = scoped_data
    base = f"/api/v1/projects/{project.id}"
    detail = client.get(base, headers=headers["editor"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["capabilities"]["can_manage_lifecycle"] is True
    assert detail.json()["capabilities"]["can_archive_project"] is False
    assert client.get(base, headers=headers["viewer"]).json()["capabilities"]["can_manage_lifecycle"] is False
    assert client.get(base + "/archive-impact", headers=headers["editor"]).status_code == 403
    assert client.post(base + "/archive-cleanup/retry", headers=headers["editor"]).status_code == 403
    lifecycle = base + f"/documents/{document.id}/lifecycle"
    payload = {"status": "deleted", "lock_version": document.lock_version, "impact_confirmed": True}
    assert client.patch(lifecycle, headers=headers["viewer"], json=payload).status_code == 403
    result = client.patch(lifecycle, headers=headers["editor"], json=payload)
    assert result.status_code == 200, result.text
    session.refresh(document)
    assert document.is_deleted and document.status == "deleted"
    assert client.put(base, headers=headers["editor"], json={"name": "Denied", "lock_version": project.lock_version}).status_code == 403


def test_creator_feedback_export_soft_delete_and_deleted_id_guard(scoped_data):
    client, _, headers, session, project, _, version, rows = scoped_data
    row = rows["editor"]
    base = f"/api/v1/projects/{project.id}/chat"
    path = base + "/conversations/" + str(row.conversation_id)
    params = {"scope_mode": "document_staging", "document_version_id": str(version.id)}
    assert client.post(base + f"/records/{row.id}/feedback", headers=headers["editor"], json={"evaluation": "correct"}).status_code == 200
    exported = client.get(path + "/export.csv", params=params, headers=headers["editor"])
    assert exported.status_code == 200 and str(row.id) in exported.text
    deleted = client.delete(path, params=params, headers=headers["editor"])
    assert deleted.status_code == 200, deleted.text
    session.refresh(row)
    assert row.deleted_at is not None and row.evaluation == "correct"
    assert client.get(path, params=params, headers=headers["owner"]).status_code == 404
    query = client.post(base + "/query", headers=headers["editor"], json={"question": "Deleted ID is not new",
        "scope_mode": "document_staging", "document_version_ids": [str(version.id)], "conversation_id": str(row.conversation_id)})
    assert query.status_code == 404 and query.json()["code"] == "conversation_not_found"


def test_published_history_is_shared_but_cannot_mix_surfaces(scoped_data):
    client, users, headers, session, project, _, version, rows = scoped_data
    published, _, _ = history(session, actor=users["owner"], project=project, versions=[version.id])
    session.commit()
    path = f"/api/v1/projects/{project.id}/chat/conversations"
    page = client.get(path, params={"scope_mode": "published"}, headers=headers["editor"])
    assert page.status_code == 200 and len(page.json()["items"]) == 1
    assert page.json()["items"][0]["id"] == str(published.conversation_id)
    assert page.json()["items"][0]["can_continue"] is False
    assert client.get(path + f"/{rows['owner'].conversation_id}", params={"scope_mode": "published"}, headers=headers["editor"]).status_code == 404
    query = client.post(f"/api/v1/projects/{project.id}/chat/query", headers=headers["editor"], json={
        "question": "Identity denied before missing manifest resolution", "scope_mode": "published", "conversation_id": str(published.conversation_id)})
    assert query.status_code == 403 and query.json()["code"] == "conversation_read_only"


def test_inactive_creator_remains_visible_but_disabled_reader_is_denied(scoped_data):
    client, users, headers, session, project, _, version, rows = scoped_data
    actor = session.get(User, users["owner"].id)
    actor.is_active = False
    original_name = actor.display_name
    actor.display_name = ""
    session.commit()
    path = f"/api/v1/projects/{project.id}/chat/conversations/{rows['owner'].conversation_id}"
    params = {"scope_mode": "document_staging", "document_version_id": str(version.id)}
    try:
        read = client.get(path, params=params, headers=headers["editor"])
        assert read.status_code == 200 and read.json()["created_by_display_name"] == ""
        assert read.json()["created_by_user_id"] == str(actor.id)
        assert client.get(path, params=params, headers=headers["owner"]).status_code == 403
    finally:
        actor.is_active = True
        actor.display_name = original_name
        session.commit()


def test_removed_reader_and_conflicting_history_fail_closed(scoped_data):
    from app.db.models import ProjectMember
    client, users, headers, session, project, _, version, rows = scoped_data
    path = f"/api/v1/projects/{project.id}/chat/conversations"
    params = {"scope_mode": "document_staging", "document_version_id": str(version.id)}
    membership = session.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == users["editor"].id))
    session.delete(membership); session.commit()
    assert client.get(path, params=params, headers=headers["editor"]).status_code == 403
    row = rows["owner"]
    history(session, actor=users["viewer"], project=project, conversation_id=row.conversation_id,
            scope="document_staging", versions=[version.id], document_version_id=version.id)
    session.commit()
    page = client.get(path, params=params, headers=headers["owner"])
    assert page.status_code == 200
    assert str(row.conversation_id) not in {item["id"] for item in page.json()["items"]}
    conflict = client.get(path + f"/{row.conversation_id}", params=params, headers=headers["owner"])
    assert conflict.status_code == 409 and conflict.json()["code"] == "conversation_identity_conflict"


def test_scope_unchanged_and_new_identity_allowance_are_provider_free(scoped_data):
    from app.api.routes.serving import _ensure_conversation_can_continue
    from live_staging_support import prepare_live_staging
    client, users, headers, session, project, document, version, rows = scoped_data
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_genuine_history_support import require_genuine_staging
        require_genuine_staging(session, project, document, version)
    else:
        prepare_live_staging(session, project, document, version)
    usage_before = session.scalar(text("SELECT count(*) FROM ai_model_usage_events"))
    _ensure_conversation_can_continue(session, project.id, rows["editor"].conversation_id, {version.id}, users["editor"].id, "document_staging")
    _ensure_conversation_can_continue(session, project.id, uuid4(), {version.id}, users["editor"].id, "document_staging")
    published, _, _ = history(session, actor=users["editor"], project=project, versions=[version.id])
    with pytest.raises(AppError) as scope_change:
        require_conversation_identity(session, project_id=project.id, conversation_id=published.conversation_id,
            user_id=users["editor"].id, scope_mode="published", requested_ids={uuid4()})
    assert scope_change.value.code == "conversation_scope_locked"
    with pytest.raises(AppError) as foreign_project:
        require_conversation_identity(session, project_id=uuid4(), conversation_id=published.conversation_id,
            user_id=users["editor"].id, scope_mode="published", requested_ids={version.id})
    assert foreign_project.value.status_code == 404
    assert session.scalar(text("SELECT count(*) FROM ai_model_usage_events")) == usage_before


def test_archive_write_denial_and_list_detail_capability_parity(scoped_data):
    client, _, headers, session, project, _, _, _ = scoped_data
    base = f"/api/v1/projects/{project.id}"
    payload = {"lock_version": project.lock_version, "confirmation_name": project.name}
    before = project.lock_version
    for response in (client.post(base + "/archive", headers=headers["editor"], json=payload),
                     client.request("DELETE", base, headers=headers["editor"], json=payload)):
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "project_editor_archive_forbidden"
    listing = client.get("/api/v1/projects", headers=headers["editor"]).json()
    items = listing["items"] if isinstance(listing, dict) else listing
    item = next(item for item in items if item["id"] == str(project.id))
    detail = client.get(base, headers=headers["editor"]).json()
    assert item["capabilities"] == detail["capabilities"]
    assert client.get(base, headers=headers["owner"]).json()["capabilities"]["can_archive_project"] is True
    session.refresh(project)
    assert project.status == "active" and project.lock_version == before


def test_editor_lifecycle_keeps_stale_and_activation_guards(scoped_data):
    client, _, headers, session, project, document, _, _ = scoped_data
    path = f"/api/v1/projects/{project.id}/documents/{document.id}/lifecycle"
    before = document.lock_version
    stale = client.patch(path, headers=headers["editor"], json={"status": "deleted", "lock_version": before + 1})
    assert stale.status_code == 409 and stale.json()["code"] == "stale_document"
    activation = client.patch(path, headers=headers["editor"], json={"status": "active", "lock_version": before})
    assert activation.status_code == 409 and activation.json()["code"] == "active_manifest_required"
    update = client.patch(path, headers=headers["editor"], json={"status": "inactive", "lock_version": before})
    assert update.status_code == 200, update.text
    session.refresh(document)
    assert document.status == "inactive" and not document.is_deleted and document.lock_version == before + 1


def test_editor_cannot_bypass_review_locked_chunk(scoped_data):
    from app.db.models import Chunk
    client, _, headers, session, project, document, version, _ = scoped_data
    version.status = "pending_review"
    chunk = session.scalar(select(Chunk).where(Chunk.document_version_id == version.id))
    original = chunk.content
    session.commit()
    path = f"/api/v1/projects/{project.id}/documents/{document.id}/versions/{version.id}/chunks/{chunk.id}"
    payload = {"lock_version": version.lock_version, "content": "Must not replace reviewed content", "source_mapping": [{"source_anchor": "test-block"}]}
    denied = client.patch(path, headers=headers["editor"], json=payload)
    assert denied.status_code == 409, denied.text
    assert client.patch(path, headers=headers["viewer"], json=payload).status_code == 403
    session.refresh(chunk)
    assert chunk.content == original


def test_shared_reads_do_not_modify_conversation_or_usage(scoped_data):
    client, _, headers, session, project, _, version, rows = scoped_data
    statement = text("SELECT md5(coalesce(jsonb_agg(to_jsonb(c) ORDER BY c.id)::text, '[]')) FROM chat_records c WHERE project_id=:id")
    before = session.scalar(statement, {"id": project.id})
    usage_before = session.scalar(text("SELECT count(*) FROM ai_model_usage_events"))
    params = {"scope_mode": "document_staging", "document_version_id": str(version.id)}
    path = f"/api/v1/projects/{project.id}/chat/conversations"
    assert client.get(path, headers=headers["viewer"], params=params).status_code == 200
    for row in rows.values():
        assert client.get(path + f"/{row.conversation_id}", headers=headers["viewer"], params=params).status_code == 200
    assert session.scalar(statement, {"id": project.id}) == before
    assert session.scalar(text("SELECT count(*) FROM ai_model_usage_events")) == usage_before


def test_archived_retry_policy_is_independent_from_active_content(scoped_data):
    from app.domain.project_access import project_capabilities
    client, users, _, session, project, _, _, _ = scoped_data
    project.status = "archived"
    project.archived_at = datetime.now(UTC)
    project.archived_by = users["owner"].id
    session.flush()
    project.archive_cleanup_status = "failed"
    for label in ("owner", "editor", "viewer"):
        caps = project_capabilities(session, project, user_id=users[label].id,
                                    visible_project_ids={project.id}, can_execute_archive=True)
        assert caps["can_manage_lifecycle"] is False
        assert caps["can_archive_project"] is False
        assert caps["can_retry_archive_cleanup"] is (label != "editor")


@pytest.fixture
def candidate_markdown(scoped_data):
    """Native source/CRUD input only; never generation, vectors or E2E evidence."""
    from app.db.models import Chunk, PipelineRun, PipelineRunStep
    from app.domain.markdown_artifacts import markdown_artifact_ref, resolve_manual_source_mapping

    _, users, _, session, project, document, version, _ = scoped_data
    raw = "# CHG293 stored candidate\n\nOwner-authored evidence.\n\n新增 **人工切片**，保留來源。"
    artifact_ref = markdown_artifact_ref(version.id)
    run = PipelineRun(project_id=project.id, document_id=document.id,
        document_version_id=version.id, run_type="knowledge_extraction", status="completed",
        triggered_by=users["owner"].id, created_at=datetime.now(UTC))
    session.add(run)
    session.flush()
    payload={"markdown":raw}
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    step = PipelineRunStep(run_id=run.id, step_name="generate_markdown", status="completed",
        output_artifact_ref=artifact_ref, artifact_payload=payload,artifact_fingerprint=fingerprint)
    session.add(step)
    version.markdown_artifact_uri = artifact_ref
    chunk = session.scalar(select(Chunk).where(Chunk.document_version_id == version.id))
    chunk.content = "Owner-authored evidence."
    chunk.markdown_content = chunk.content
    chunk.display_markdown = chunk.content
    start = raw.index(chunk.content)
    mapping=resolve_manual_source_mapping(content=chunk.content,markdown=raw,source_anchor='paragraph-2',
        start_offset=start,end_offset=start+len(chunk.content),offset_scope='canonical_markdown',offset_unit='unicode_code_point')
    assert mapping is not None
    chunk.source_mapping=[mapping]
    chunk.start_offset,chunk.end_offset=start,start+len(chunk.content)
    session.commit()
    manual_text = "新增 **人工切片**，保留來源。"
    manual_start = raw.index(manual_text)
    return {"scope": scoped_data, "raw": raw, "step": step, "chunk": chunk,
        "base": f"/api/v1/projects/{project.id}/documents/{document.id}/versions/{version.id}",
        "manual": {"content": manual_text, "view_mode": "markdown", "source_anchor": "paragraph-3",
            "start_offset": manual_start, "end_offset": manual_start + len(manual_text),
            "offset_scope": "canonical_markdown", "offset_unit": "unicode_code_point",
            "lock_version": version.lock_version}}


def content_fingerprints(session):
    # These fixed table names are test code, never request-supplied identifiers.
    tables = ("chunks", "tags", "chunk_tags", "document_version_tags", "document_versions",
              "pipeline_runs", "pipeline_run_steps", "outbox_events", "chat_records", "ai_model_usage_events",
              "document_content_states", "document_content_update_jobs")
    return {table: session.scalar(text(
        f"SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text)::text, '[]')) FROM {table} r"
    )) for table in tables}


def test_editor_manual_chunk_crud_preserves_raw_and_queues_real_outbox(candidate_markdown):
    from app.db.models import Chunk, OutboxEvent, DocumentContentState, DocumentContentUpdate, PipelineRun
    from app.domain.document_content_updates import CONTENT_UPDATE_TOPIC
    case = candidate_markdown
    model_count_before = case["scope"][3].scalar(text("SELECT count(*) FROM ai_models"))
    client, users, headers, session, project, document, version, _ = case["scope"]
    baseline = content_fingerprints(session)
    assert document.created_by == users["owner"].id
    created = client.post(case["base"] + "/chunks/manual", headers=headers["editor"], json=case["manual"])
    assert created.status_code == 200, created.text
    assert created.json()["chunk_artifact_status"] == "queued"
    assert created.json()["next_stage_allowed"] is False
    session.expire_all()
    manual = session.scalar(select(Chunk).where(Chunk.document_version_id == version.id,
        Chunk.change_type == "manual_create"))
    assert manual.edited_by == users["editor"].id
    assert manual.markdown_content == case["manual"]["content"]
    assert "**" in manual.display_markdown and "**" not in manual.retrieval_text
    assert "人工切片" in manual.retrieval_text
    assert manual.source_mapping[0]["markdown_start_offset"] == case["manual"]["start_offset"]

    manual_id=manual.id
    deleted=client.delete(case['base']+f'/chunks/{manual_id}',headers=headers['editor'],
        params={'lock_version':version.lock_version})
    assert deleted.status_code == 200 and deleted.json()['next_stage_allowed'] is False
    session.expire_all()
    assert session.get(Chunk,manual_id) is None
    events=list(session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == version.id,
        OutboxEvent.topic == 'chunk.artifacts.reconcile')))
    assert len(events) == 2 and {event.payload['revision'] for event in events} == {2,3}
    assert all(event.status == 'pending' and event.attempts == 0 for event in events)

    # Edit the original Owner-created content, not merely the Editor's new chunk.
    original = case["chunk"]
    original_id, original_text, original_lineage = original.id, original.content, original.lineage_id
    edited = client.patch(case["base"] + f"/chunks/{original_id}", headers=headers["editor"], json={
        "content": "Editor updated evidence.", "markdown_content": "Editor **updated** evidence.",
        "source_mapping": original.source_mapping, "lock_version": version.lock_version})
    assert edited.status_code == 200, edited.text
    session.expire_all()
    job=session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.document_version_id == version.id))
    assert job.status == 'queued' and job.actor_user_id == users['editor'].id
    assert job.pending_markdown == case['raw'].replace(original_text,'Editor **updated** evidence.')
    assert session.get(DocumentContentState,version.id).current_markdown == case['raw']
    assert session.get(PipelineRun,job.pipeline_run_id).status == 'queued'
    assert edited.json()['next_stage_allowed'] is False and version.status == 'processing'
    assert original.status == 'active' and original.content == original_text
    assert original.lineage_id == original_lineage and original.superseded_by_id is None
    assert session.scalar(select(Chunk).where(Chunk.parent_chunk_id == original_id)) is None
    event=session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id,OutboxEvent.topic == CONTENT_UPDATE_TOPIC))
    assert event.status == 'pending' and event.attempts == 0
    assert case["step"].artifact_payload == {"markdown": case["raw"]}
    after = content_fingerprints(session)
    for table in ("chat_records", "ai_model_usage_events"):
        assert after[table] == baseline[table]
    assert session.scalar(text("SELECT count(*) FROM ai_models")) == model_count_before


def test_editor_document_and_chunk_tag_crud_updates_postgresql_preview(candidate_markdown):
    from app.db.models import ChunkTag, DocumentVersionTag, Tag
    case = candidate_markdown
    client, users, headers, session, project, _, version, _ = case["scope"]
    baseline = content_fingerprints(session)
    paths = (case["base"] + "/tags", case["base"] + f"/chunks/{case['chunk'].id}/tags")
    for path in paths:
        result = client.post(path, headers=headers["owner"], json={"tag_text": "Owner shared label"})
        assert result.status_code == 200, result.text
    session.expire_all()
    tag = session.scalar(select(Tag).where(Tag.project_id == project.id, Tag.name == "Owner shared label"))
    assert session.get(ChunkTag, (case["chunk"].id, tag.id)).created_by == users["owner"].id
    original_revision = version.chunk_strategy["graph_tag_revision"]
    original_digest = version.chunk_strategy["graph_preview"]["source_digest"]
    for path in paths:
        removed = client.delete(path + f"/{tag.id}", headers=headers["editor"])
        assert removed.status_code == 200, removed.text
        # Existing UI replaces tag assignments via remove/add; no new rename API.
        added = client.post(path, headers=headers["editor"], json={"tag_text": "Editor replacement label"})
        assert added.status_code == 200, added.text
    session.expire_all()
    replacement = session.scalar(select(Tag).where(Tag.project_id == project.id, Tag.name == "Editor replacement label"))
    assert session.get(ChunkTag, (case["chunk"].id, tag.id)) is None
    assert session.get(DocumentVersionTag, (version.id, tag.id)) is None
    assert session.get(ChunkTag, (case["chunk"].id, replacement.id)).created_by == users["editor"].id
    assert session.get(DocumentVersionTag, (version.id, replacement.id)).created_by == users["editor"].id
    preview = version.chunk_strategy["graph_preview"]
    assert preview["source"] == "postgresql_staging_preview"
    assert preview["source_digest"] != original_digest
    assert preview["tag_revision"] == original_revision + 4
    assert {node["label"] for node in preview["nodes"] if node["type"] == "tag"} == {"Editor replacement label"}
    assert {edge["type"] for edge in preview["edges"] if edge["target"] == f"tag:{replacement.id}"} == {"VERSION_HAS_TAG", "CHUNK_HAS_TAG"}
    after = content_fingerprints(session)
    for table in ("pipeline_run_steps", "chunks", "chat_records", "outbox_events", "ai_model_usage_events"):
        assert after[table] == baseline[table]


def content_write_requests(case, lock_version):
    base, chunk_id = case["base"], case["chunk"].id
    missing_tag = uuid4()
    return [
        ("POST", base + "/chunks/manual", {"json": {**case["manual"], "lock_version": lock_version}}),
        ("PATCH", base + f"/chunks/{chunk_id}", {"json": {"content": "Must not change", "lock_version": lock_version,
            "source_mapping": [{"source_anchor": "paragraph-2"}]}}),
        ("DELETE", base + f"/chunks/{chunk_id}", {"params": {"lock_version": lock_version}}),
        ("POST", base + "/tags", {"json": {"tag_text": "Must not add"}}),
        ("POST", base + f"/chunks/{chunk_id}/tags", {"json": {"tag_text": "Must not add"}}),
        ("DELETE", base + f"/tags/{missing_tag}", {}),
        ("DELETE", base + f"/chunks/{chunk_id}/tags/{missing_tag}", {}),
    ]


@pytest.mark.parametrize("reason", ["viewer", "foreign", "removed", "disabled", "missing_menu", "archived"])
def test_content_write_denials_preserve_rows_and_outbox(candidate_markdown, reason):
    from sqlalchemy import delete
    from app.db.models import ProjectMember, RolePermission, RoleUser
    case = candidate_markdown
    client, users, headers, session, project, _, version, _ = case["scope"]
    actor_label = {"viewer": "viewer", "foreign": "outsider"}.get(reason, "editor")
    actor = session.get(User, users[actor_label].id)
    removed_roles = []
    if reason == "removed":
        session.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == actor.id))
    elif reason == "disabled":
        actor.is_active = False
    elif reason == "missing_menu":
        menu_roles = select(RolePermission.role_id).where(RolePermission.module_name == "Menu",
            RolePermission.function_name == "KnowledgeProjects", RolePermission.can_view.is_(True))
        rows = list(session.scalars(select(RoleUser).where(RoleUser.user_id == actor.id, RoleUser.role_id.in_(menu_roles))))
        removed_roles = [{column.name: getattr(row, column.name) for column in RoleUser.__table__.columns} for row in rows]
        for row in rows:
            session.delete(row)
    elif reason == "archived":
        project.status = "archived"
        project.archived_at = datetime.now(UTC)
        project.archived_by = users["owner"].id
    session.commit()
    before = content_fingerprints(session)
    try:
        for method, path, kwargs in content_write_requests(case, version.lock_version):
            denied = client.request(method, path, headers=headers[actor_label], **kwargs)
            expected_status = 409 if reason == "archived" else 403
            assert denied.status_code == expected_status, (reason, method, denied.status_code, denied.text)
            if reason in {"foreign", "removed"}:
                assert denied.json()["code"] == "project_scope_denied"
            elif reason == "archived":
                assert denied.json()["code"] == "project_archived"
        assert content_fingerprints(session) == before
    finally:
        # Module-level test actors are shared; restore only their altered fixture state.
        if reason == "disabled":
            actor.is_active = True
        for values in removed_roles:
            session.add(RoleUser(**values))
        session.commit()


@pytest.mark.parametrize("status,published", [("pending_manager_review", False), ("pending_owner_review", False), ("approved", False), ("active", True), ("inactive", True)])
def test_editor_content_writes_keep_review_and_published_locks(candidate_markdown, status, published):
    case = candidate_markdown
    client, _, headers, session, _, _, version, _ = case["scope"]
    version.status = status
    if published:
        version.published_at = datetime.now(UTC)
    session.commit()
    before = content_fingerprints(session)
    for method, path, kwargs in content_write_requests(case, version.lock_version):
        denied = client.request(method, path, headers=headers["editor"], **kwargs)
        assert denied.status_code == 409, (method, denied.status_code, denied.text)
    assert content_fingerprints(session) == before


@pytest.mark.parametrize("heading_path", [None, [], ["房貸", "違約金"]])
def test_nullable_heading_path_binding_honors_v046_constraint(scoped_data, heading_path):
    from app.db.models import Chunk
    _, _, _, session, _, _, version, _ = scoped_data
    chunk = session.scalar(select(Chunk).where(Chunk.document_version_id == version.id))
    chunk.heading_path = ["Before update"]
    session.flush()
    chunk.heading_path = heading_path
    session.flush()
    actual, is_sql_null = session.execute(text(
        "SELECT heading_path, heading_path IS NULL FROM chunks WHERE id=:id"), {"id": chunk.id}).one()
    assert actual == heading_path
    assert is_sql_null is (heading_path is None)


def test_json_null_heading_path_is_still_rejected_by_database(scoped_data):
    from sqlalchemy.exc import IntegrityError
    from app.db.models import Chunk
    _, _, _, session, _, _, version, _ = scoped_data
    chunk = session.scalar(select(Chunk).where(Chunk.document_version_id == version.id))
    with pytest.raises(IntegrityError) as invalid:
        with session.begin_nested():
            session.execute(text("UPDATE chunks SET heading_path='null'::jsonb WHERE id=:id"), {"id": chunk.id})
    assert invalid.value.orig.diag.constraint_name == "ck_chunks_heading_path_array"


def test_failed_replacement_rolls_back_superseded_state_and_outbox(candidate_markdown):
    case = candidate_markdown
    client, _, headers, session, _, _, version, _ = case["scope"]
    constraint = "chg293_test_abort_" + uuid4().hex
    # Real PostgreSQL failure after the first flush; only this random test schema
    # is affected. No monkeypatch, intercepted API or fake persistence adapter.
    session.execute(text(f"ALTER TABLE document_content_update_jobs ADD CONSTRAINT {constraint} CHECK (position('CHG293 rollback sentinel' in pending_markdown) = 0)"))
    session.commit()
    before = content_fingerprints(session)
    try:
        request_id = str(uuid4())
        response = client.patch(case["base"] + f"/chunks/{case['chunk'].id}",
            headers={**headers["editor"], 'X-Request-Id': request_id}, json={
                "content": "CHG293 rollback sentinel", "lock_version": version.lock_version,
                "source_mapping": case["chunk"].source_mapping})
        assert response.status_code == 500
        assert response.headers['content-type'].startswith('application/json')
        assert response.headers['X-Request-Id'] == request_id
        assert response.json() == {'code': 'unhandled_exception', 'message': 'Request failed',
                                   'details': {}, 'request_id': request_id}
        assert content_fingerprints(session) == before
        session.refresh(case["chunk"])
        assert case["chunk"].status == "active" and case["chunk"].superseded_by_id is None
        if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
            assert client.get('/api/v1/auth/me', headers=headers['editor']).status_code == 200
    finally:
        session.execute(text(f"ALTER TABLE document_content_update_jobs DROP CONSTRAINT {constraint}"))
        session.commit()


@pytest.mark.parametrize('fingerprint',[None,'0'*64])
def test_unverified_native_source_cannot_replace_chunk(candidate_markdown,fingerprint):
    case=candidate_markdown
    client,_,headers,session,_,_,version,_=case['scope']
    case['step'].artifact_fingerprint=fingerprint
    session.commit()
    before=content_fingerprints(session)
    response=client.patch(case['base']+f"/chunks/{case['chunk'].id}",headers=headers['editor'],json={
        'content':'Must remain unchanged','lock_version':version.lock_version,
        'source_mapping':case['chunk'].source_mapping})
    assert response.status_code == 409 and response.json()['code'] == 'content_edit_source_unavailable'
    session.expire_all()
    assert content_fingerprints(session) == before
    assert case['chunk'].status == 'active' and case['chunk'].superseded_by_id is None
