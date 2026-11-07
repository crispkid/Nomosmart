"""CHG-310 API regression against owned PostgreSQL, Keycloak and FastAPI.

CHG310_LIVE_CONTEXT points to a private receipt from an isolated test run.
Missing prerequisites fail; no stub identity, database or HTTP response is used.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db.models import ApprovalTask, DocumentReference, DocumentReferenceEvent, DocumentVersion, Project, ProjectOwner, Role, RolePermission, RoleUser, User


class PrivateContext(dict):
    def __repr__(self):
        return "<private owned CHG-310 context>"


@pytest.fixture(scope="module")
def live(request):
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from current_authorization_support import current_approval_read_scope
        with current_approval_read_scope(request) as current:
            yield current
        return
    path = Path(os.environ["CHG310_LIVE_CONTEXT"])
    assert path.is_absolute() and not path.is_symlink()
    assert path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o077 == 0
    context = PrivateContext(json.loads(path.read_text()))
    UUID(context["run_id"])
    assert context["backend_url"].startswith("http://127.0.0.1:")
    assert context["issuer"].endswith("/chg310-" + context["run_id"].replace("-", ""))
    engine = create_engine(context["database_url"], hide_parameters=True)
    with engine.connect() as connection:
        assert str(connection.scalar(text("SELECT run_id FROM chg310_ownership"))) == context["run_id"]
    with httpx.Client(base_url=context["backend_url"] + "/api/v1", timeout=15, trust_env=False) as client:
        yield context, engine, client
    engine.dispose()


def headers(context, actor):
    if context.get('current_prepared_session_headers') is not None:
        assert context.get('current_negative_scope') == 'real-post-login-user-and-role-rejection'
        assert actor in {'owner', 'disabled', 'zero'}
        return context['current_prepared_session_headers'][actor]
    if context.get("current_live") is not None:
        return context["current_live"].session_headers(context["actor_aliases"][actor])
    response = httpx.post(context["issuer"] + "/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": context["client_id"], **{
            key: context["actors"][actor][key] for key in ("username", "password")
        },
    }, timeout=15, trust_env=False)
    assert response.status_code == 200, "real isolated OIDC grant failed"
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.mark.parametrize("actor", ["viewer", "editor", "cross", "management", "expired"])
def test_unrelated_members_cannot_read_evidence(live, actor):
    context, _, client = live
    auth = headers(context, actor)
    rows = client.get("/approval-requests", headers=auth)
    assert rows.status_code == 200
    payload = rows.json()
    assert isinstance(payload, list)
    assert context["request_id"] not in {row["id"] for row in payload}
    for route in ("/approval-requests/" + context["request_id"], "/approvals/" + context["task_id"]):
        response = client.get(route, headers=auth)
        assert response.status_code == 403
        assert response.json()["code"] == "approval_read_denied"
        assert "chunks" not in response.json() and "evidence_manifest" not in response.json()


@pytest.mark.parametrize("actor", ["submitter", "assignee", "manager", "delegate", "past", "owner", "auditor"])
def test_authorized_actors_and_read_only_auditor(live, actor):
    context, _, client = live
    auth = headers(context, actor)
    assert client.get("/approval-requests/" + context["request_id"], headers=auth).status_code == 200
    response = client.get("/approvals/" + context["task_id"], headers=auth)
    assert response.status_code == 200
    expected_read_only = context.get("expected_read_only", {}).get(actor, actor != "assignee")
    assert response.json()["read_only"] == expected_read_only
    assert response.json()["document"]["capabilities"]["can_publish"] is False
    if actor == "submitter":
        rows = client.get("/approval-requests", headers=auth)
        assert rows.status_code == 200
        expected = context.get("expected_submitter_request_ids", [context["request_id"]])
        assert {row["id"] for row in rows.json()} == set(expected)


def test_admin_audit_never_authorizes_decisions(live):
    context, engine, client = live
    auth = headers(context, "auditor")
    if context.get("current_live") is not None:
        with Session(engine) as session:
            task = session.get(ApprovalTask, UUID(context["task_id"]))
            baseline = task.status, task.lock_version
    for action in ("approve", "reject"):
        response = client.post(f"/approvals/{context['task_id']}/{action}", headers=auth, json={"lock_version": 1, "comment": "denied audit-only action"})
        assert response.status_code == 403
    assert client.post(f"/document-versions/{context['version_id']}/publish", headers=auth, json={"lock_version": 1, "impact_confirmed": True}).status_code == 403
    with Session(engine) as session:
        task = session.get(ApprovalTask, UUID(context["task_id"]))
        expected = baseline if context.get("current_live") is not None else ("pending", 1)
        assert (task.status, task.lock_version) == expected


@pytest.mark.parametrize("field", ["is_active", "is_system"])
def test_audit_role_must_be_current_and_protected(live, field):
    context, engine, client = live
    auth = headers(context, "auditor")
    with Session(engine) as session:
        role = session.get(Role, UUID(context["admin_role_id"]))
        previous = getattr(role, field)
        setattr(role, field, False)
        session.commit()
    try:
        assert client.get("/approvals/" + context["task_id"], headers=auth).status_code == 403
    finally:
        with Session(engine) as session:
            setattr(session.get(Role, UUID(context["admin_role_id"])), field, previous)
            session.commit()


def test_owner_and_delegate_revocation(live):
    context, engine, client = live
    auth = headers(context, "delegate")
    with Session(engine) as session:
        delegation_manager = context["users"].get("delegation_manager", context["users"]["submitter"])
        submitter = session.get(User, UUID(delegation_manager))
        old_end = submitter.manager_delegate_end_at
        submitter.manager_delegate_end_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    try:
        assert client.get("/approvals/" + context["task_id"], headers=auth).status_code == 403
    finally:
        with Session(engine) as session:
            session.get(User, UUID(delegation_manager)).manager_delegate_end_at = old_end
            session.commit()
    with Session(engine) as session:
        session.delete(session.get(ProjectOwner, (UUID(context["project_id"]), UUID(context["users"]["owner"]))))
        session.commit()
    try:
        assert client.get("/approvals/" + context["task_id"], headers=headers(context, "owner")).status_code == 403
    finally:
        with Session(engine) as session:
            session.add(ProjectOwner(project_id=UUID(context["project_id"]), user_id=UUID(context["users"]["owner"]), created_at=datetime.now(UTC)))
            session.commit()


def test_reference_operations_require_menu_view(live):
    context, engine, client = live
    auth = headers(context, "reference")
    operations = [
        ("POST", f"/document-references/{context['reference_id']}/detach"),
        ("POST", f"/document-references/{context['reference_id']}/sync"),
        ("GET", "/document-reference-events"),
        ("GET", f"/document-reference-events/impacted-projects?source_document_id={context['source_document_id']}"),
        ("POST", f"/document-reference-events/{context['event_id']}/resolve"),
    ]
    for method, route in operations:
        response = client.request(method, route, headers=auth)
        assert response.status_code == 403 and response.json()["code"] == "permission_denied"
    with Session(engine) as session:
        assert session.get(DocumentReference, UUID(context["reference_id"])).status == "active"
        assert session.get(DocumentReferenceEvent, UUID(context["event_id"])).resolved_at is None
        role = Role(name="chg310-union-" + uuid4().hex, is_active=True)
        session.add(role)
        session.flush()
        membership = RoleUser(role_id=role.id, user_id=UUID(context["users"]["reference"]), source="manual")
        session.add(membership)
        grant = RolePermission(role_id=role.id, module_name="Menu", function_name="KnowledgeProjects", can_view=True)
        session.add(grant)
        session.commit()
        grant_id = grant.id
        role_id = role.id
    try:
        assert client.get("/document-reference-events", headers=auth).status_code == 200
        assert client.get(operations[3][1], headers=auth).status_code == 200
        assert client.post(operations[1][1], headers=auth).status_code == 202
        assert client.post(operations[4][1], headers=auth).status_code == 200
        assert client.post(operations[0][1], headers=auth).status_code == 200
    finally:
        with Session(engine) as session:
            session.get(DocumentReference, UUID(context["reference_id"])).status = "active"
            event = session.get(DocumentReferenceEvent, UUID(context["event_id"]))
            event.is_read, event.resolved_at = False, None
            session.delete(session.get(RolePermission, grant_id))
            session.delete(session.get(RoleUser, (role_id, UUID(context["users"]["reference"]), "manual")))
            session.flush()
            session.delete(session.get(Role, role_id))
            session.commit()


def test_viewer_writes_and_archived_reads_denied(live):
    context, engine, client = live
    response = client.post(f"/document-references/{context['reference_id']}/detach", headers=headers(context, "viewer"))
    assert response.status_code == 403
    with Session(engine) as session:
        project = session.get(Project, UUID(context["project_id"]))
        project.status = "archived"
        project.archived_at = datetime.now(UTC)
        project.archived_by = UUID(context["users"]["owner"])
        session.commit()
    try:
        for actor in ("owner", "auditor"):
            assert client.get("/approvals/" + context["task_id"], headers=headers(context, actor)).status_code == 409
        assert client.post(f"/document-references/{context['reference_id']}/sync", headers=headers(context, "owner")).status_code == 409
    finally:
        with Session(engine) as session:
            project = session.get(Project, UUID(context["project_id"]))
            project.status, project.archived_at, project.archived_by = "active", None, None
            session.commit()


def test_not_found_and_identity_rejections(live):
    context, _, client = live
    assert client.get("/approvals/" + str(uuid4()), headers=headers(context, "owner")).status_code == 404
    assert client.get("/approvals/" + context["task_id"]).status_code == 401
    for actor, code in (("disabled", "user_disabled"), ("zero", "application_access_denied")):
        response = client.get("/approvals/" + context["task_id"], headers=headers(context, actor))
        assert response.status_code == 403 and response.json()["code"] == code


def test_malformed_token_rejected(live):
    context, _, client = live
    response = client.get("/approvals/" + context["task_id"], headers={"Authorization": "Bearer not-a-jwt"})
    expected = "authentication_required" if context.get("current_live") is not None else "invalid_token"
    assert response.status_code == 401 and response.json()["code"] == expected


def test_real_oidc_token_expiry(live):
    context, _, client = live
    container = json.loads(subprocess.check_output(["docker", "inspect", context["names"]["kc"]], text=True))[0]
    assert container["Id"] in context["containers"]
    assert container["Config"]["Labels"]["io.nomosmart.chg310"] == context["run_id"]
    private_env = dict(value.split("=", 1) for value in container["Config"]["Env"])
    base, realm = context["issuer"].rsplit("/realms/", 1)
    with httpx.Client(timeout=15, trust_env=False) as oidc:
        response = oidc.post(base + "/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli",
            "username": private_env["KC_BOOTSTRAP_ADMIN_USERNAME"],
            "password": private_env["KC_BOOTSTRAP_ADMIN_PASSWORD"],
        })
        assert response.status_code == 200, "owned realm admin grant failed"
        admin = {"Authorization": "Bearer " + response.json()["access_token"]}
        endpoint = base + "/admin/realms/" + realm
        response = oidc.get(endpoint, headers=admin)
        assert response.status_code == 200
        configuration = response.json()
        try:
            assert oidc.put(endpoint, headers=admin, json={**configuration, "accessTokenLifespan": 3}).status_code == 204
            auth = headers(context, "owner")
        finally:
            assert oidc.put(endpoint, headers=admin, json=configuration).status_code == 204
    # Read the issuer's real expiration claim solely to wait for wall-clock expiry.
    claims = jwt.decode(auth["Authorization"].removeprefix("Bearer "), options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 3
    assert client.get("/approvals/" + context["task_id"], headers=auth).status_code == 200
    time.sleep(max(0, claims["exp"] - time.time()) + 1)
    response = client.get("/approvals/" + context["task_id"], headers=auth)
    assert response.status_code == 401 and response.json()["code"] == "token_expired"


def test_completed_approval_owner_can_publish_but_auditor_cannot(live):
    context, engine, client = live
    with Session(engine) as session:
        version = session.get(DocumentVersion, UUID(context["version_id"]))
        task = session.get(ApprovalTask, UUID(context["task_id"]))
        original = (version.status, task.status, task.completed_at)
        if context.get('current_live') is not None:
            assert context['current_approved_input'] is True
            assert version.status==task.status=='approved' and task.completed_at is not None
        else:
            version.status, task.status, task.completed_at = "approved", "approved", datetime.now(UTC)
            session.commit()
    try:
        for actor, allowed in (("owner", True), ("auditor", False)):
            response = client.get("/approvals/" + context["task_id"], headers=headers(context, actor))
            assert response.status_code == 200
            assert response.json()["read_only"] is True
            assert response.json()["read_only_reason"] == "task_completed"
            assert response.json()["document"]["capabilities"]["can_publish"] is allowed
    finally:
        if context.get('current_live') is None:
            with Session(engine) as session:
                version = session.get(DocumentVersion, UUID(context["version_id"]))
                task = session.get(ApprovalTask, UUID(context["task_id"]))
                version.status, task.status, task.completed_at = original
                session.commit()


def test_audit_membership_removal_applies_next_request(live):
    context, engine, client = live
    source = context["admin_role_membership_source"] if context.get("current_live") is not None else "manual"
    key = (UUID(context["admin_role_id"]), UUID(context["users"]["auditor"]), source)
    auth = headers(context, "auditor")
    with Session(engine) as session:
        session.delete(session.get(RoleUser, key))
        session.commit()
    try:
        assert client.get("/approvals/" + context["task_id"], headers=auth).status_code == 403
    finally:
        with Session(engine) as session:
            session.add(RoleUser(role_id=key[0], user_id=key[1], source=key[2]))
            session.commit()


def test_audit_view_revocation_applies_next_request(live):
    context, engine, client = live
    auth = headers(context, "auditor")
    with Session(engine) as session:
        grant = session.scalar(select(RolePermission).where(RolePermission.role_id == UUID(context["admin_role_id"]), RolePermission.module_name == "Menu", RolePermission.function_name == "SystemManagement"))
        grant_id, previous = grant.id, grant.can_view
        grant.can_view = False
        session.commit()
    try:
        assert client.get("/approvals/" + context["task_id"], headers=auth).status_code == 403
    finally:
        with Session(engine) as session:
            session.get(RolePermission, grant_id).can_view = previous
            session.commit()
