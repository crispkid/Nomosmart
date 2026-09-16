"""CHG-293: direct policies and real disposable PostgreSQL history tests.

Live cases require CHG293_DATABASE_URL pointing to a disposable test service.
No production defaults, Provider calls or authentication dependency overrides.
"""
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
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
    url = os.environ.get("CHG293_DATABASE_URL")
    if not url:
        pytest.fail("CHG293_DATABASE_URL must identify a disposable PostgreSQL service")
    schema = "chg293_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(admin.url.update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for migration in sorted((Path(__file__).resolve().parents[2] / "sql/migrations").glob("V*.sql")):
                version = int(migration.name.split("__", 1)[0][1:])
                if version > 48 or version == 42:
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
def authenticated(live_engine):
    """Real Keycloak tokens/JWKS, real FastAPI dependencies, disposable database."""
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
           "APP_ENCRYPTION_KEY": uuid4().hex + uuid4().hex, "LOG_LEVEL": "ERROR"}
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
def scoped_data(authenticated, live_engine):
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
    client, users, headers, session, project, _, version, rows = scoped_data
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
    client, users, headers, session, project, _, version, rows = scoped_data
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
    """An already-stored candidate artifact; this does not simulate OCR execution."""
    from app.db.models import Chunk, PipelineRun, PipelineRunStep
    from app.domain.markdown_artifacts import markdown_artifact_ref

    _, users, _, session, project, document, version, _ = scoped_data
    raw = "# CHG293 stored candidate\n\nOwner-authored evidence.\n\n新增 **人工切片**，保留來源。"
    artifact_ref = markdown_artifact_ref(version.id)
    run = PipelineRun(project_id=project.id, document_id=document.id,
        document_version_id=version.id, run_type="knowledge_extraction", status="completed",
        triggered_by=users["owner"].id, created_at=datetime.now(UTC))
    session.add(run)
    session.flush()
    step = PipelineRunStep(run_id=run.id, step_name="generate_markdown", status="completed",
        output_artifact_ref=artifact_ref, artifact_payload={"markdown": raw})
    session.add(step)
    version.markdown_artifact_uri = artifact_ref
    chunk = session.scalar(select(Chunk).where(Chunk.document_version_id == version.id))
    chunk.content = "Owner-authored evidence."
    chunk.markdown_content = chunk.content
    chunk.display_markdown = chunk.content
    start = raw.index(chunk.content)
    chunk.source_mapping = [{"source_anchor": "paragraph-2", "view_mode": "markdown",
        "offset_scope": "canonical_markdown", "offset_unit": "unicode_code_point",
        "start_offset": start, "end_offset": start + len(chunk.content)}]
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
              "pipeline_runs", "pipeline_run_steps", "outbox_events", "chat_records", "ai_model_usage_events")
    return {table: session.scalar(text(
        f"SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text)::text, '[]')) FROM {table} r"
    )) for table in tables}


def test_editor_manual_chunk_crud_preserves_raw_and_queues_real_outbox(candidate_markdown):
    from app.db.models import Chunk, OutboxEvent
    case = candidate_markdown
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

    # Edit the original Owner-created content, not merely the Editor's new chunk.
    original = case["chunk"]
    original_id, original_text, original_lineage = original.id, original.content, original.lineage_id
    edited = client.patch(case["base"] + f"/chunks/{original_id}", headers=headers["editor"], json={
        "content": "Editor updated evidence.", "markdown_content": "Editor **updated** evidence.",
        "source_mapping": original.source_mapping, "lock_version": version.lock_version})
    assert edited.status_code == 200, edited.text
    session.expire_all()
    replacement = session.scalar(select(Chunk).where(Chunk.parent_chunk_id == original_id))
    assert original.status == "superseded" and original.content == original_text
    assert original.superseded_by_id == replacement.id
    assert replacement.edited_by == users["editor"].id and replacement.revision == 1
    assert replacement.lineage_id == original_lineage
    assert replacement.markdown_content == "Editor **updated** evidence."
    assert "**" not in replacement.retrieval_text
    assert replacement.embedding_content_hash != manual.embedding_content_hash

    replacement_id = replacement.id
    predecessor_index = original.chunk_index
    deleted = client.delete(case["base"] + f"/chunks/{replacement_id}",
        headers=headers["editor"], params={"lock_version": version.lock_version})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["chunk_artifact_status"] == "queued"
    assert deleted.json()["next_stage_allowed"] is False
    session.expire_all()
    assert session.get(Chunk, replacement_id) is None
    assert original.status == "superseded" and original.content == original_text
    assert original.superseded_by_id is None and original.chunk_index == predecessor_index
    assert manual.status == "active"
    events = list(session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == version.id,
        OutboxEvent.topic == "chunk.artifacts.reconcile")))
    assert len(events) == 3
    assert all(event.status == "pending" and event.attempts == 0 for event in events)
    assert {event.payload["revision"] for event in events} == {2, 3, 4}
    assert version.chunk_strategy["chunk_artifacts"]["requested_by"] == str(users["editor"].id)
    assert case["step"].artifact_payload == {"markdown": case["raw"]}
    after = content_fingerprints(session)
    for table in ("pipeline_runs", "pipeline_run_steps", "chat_records", "ai_model_usage_events"):
        assert after[table] == baseline[table]
    assert session.scalar(text("SELECT count(*) FROM ai_models")) == 0


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
    from sqlalchemy.exc import IntegrityError
    case = candidate_markdown
    client, _, headers, session, _, _, version, _ = case["scope"]
    constraint = "chg293_test_abort_" + uuid4().hex
    # Real PostgreSQL failure after the first flush; only this random test schema
    # is affected. No monkeypatch, intercepted API or fake persistence adapter.
    session.execute(text(f"ALTER TABLE chunks ADD CONSTRAINT {constraint} CHECK (content <> 'CHG293 rollback sentinel')"))
    session.commit()
    before = content_fingerprints(session)
    try:
        with pytest.raises(IntegrityError) as aborted:
            client.patch(case["base"] + f"/chunks/{case['chunk'].id}", headers=headers["editor"], json={
                "content": "CHG293 rollback sentinel", "lock_version": version.lock_version,
                "source_mapping": case["chunk"].source_mapping})
        assert aborted.value.orig.diag.constraint_name == constraint
        assert content_fingerprints(session) == before
        session.refresh(case["chunk"])
        assert case["chunk"].status == "active" and case["chunk"].superseded_by_id is None
    finally:
        session.execute(text(f"ALTER TABLE chunks DROP CONSTRAINT {constraint}"))
        session.commit()
