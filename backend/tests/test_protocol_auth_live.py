"""PROTAUTH focused tests against owned real PostgreSQL, HTTPS API and LDAP.

Set NOMOSMART_CURRENT_LIVE_CONTEXT for a current run; CHG363_STATE_FILE is historical only. No dependency replacement or synthetic response
is permitted. Missing live prerequisites are BLOCKED, never a passing substitute.
"""
import json
import os
import sys
from pathlib import Path
import ssl
from uuid import UUID

import httpx
import pytest

current_context_file = os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT")
if current_context_file:
    # Current authority is validated before any historical path is considered.
    if '--collect-only' not in sys.argv and os.environ.get('NOMOSMART_CHG414_API_PROFILE') != 'host-direct' and os.environ.get('NOMOSMART_CHG414_LINUX_PROFILE') == '/tmp/nms414-919553ec-native-protocol/profile.json':
        from current_linux_protocol414 import load_collection, load_native_directory_context
        current_context = load_collection()
    else:
        from current_live_support import load_current_context, load_current_collection_context
        current_context = load_current_collection_context()
    state = None
    root = Path(current_context_file).parent
else:
    current_context = None
    state_file = os.environ.get("CHG363_STATE_FILE")
    if not state_file:
        pytest.skip("BLOCKED: a current owned live context is required", allow_module_level=True)
    root = Path(state_file).resolve().parent
    state = json.loads(Path(state_file).read_text())
    if state.get("owner") != "CHG-363" or state.get("project") != "nomosmart-chg363":
        raise RuntimeError("Refusing an unowned test environment")
    os.environ.update(DATABASE_URL=state["database_url"], APP_ENCRYPTION_KEY=state["app_encryption_key"], AUTH_ENCRYPTION_KEY_ID="chg363-v1", AUTH_ENDPOINT_ALLOWED_HOSTS="localhost", AUTH_TRUST_ROOT=str(root / "tls"), FRONTEND_APP_ORIGIN="https://localhost:18463")
    os.chdir(root)
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import AuthConnectionSecret, AuthLoginFlow, IdentitySetting, User
from app.db.session import get_session_factory
from app.integrations.ldap_directory import LdapDirectory
from app.security.auth_configuration import configuration, current_setting, read_secret, unseal
from sqlalchemy import select

if current_context is not None:
    # Collection sees real non-secret metadata only. No account material,
    # database engine or client TLS context is constructed until runtime.
    engine = factory = context = origin = base = None
else:
    engine = None
    factory = get_session_factory()
    context = ssl.create_default_context(cafile=str(root / "tls/ca.pem"))
    origin = "https://localhost:18463"
    base = os.environ.get("CHG363_API_BASE", origin + "/api/backend")


def account(alias):
    if os.environ.get('NOMOSMART_CHG414_API_PROFILE') != 'host-direct' and os.environ.get('NOMOSMART_CHG414_LINUX_PROFILE') == '/tmp/nms414-919553ec-native-protocol/profile.json':
        raise RuntimeError('native_directory_profile_has_no_interactive_accounts')
    if current_context is not None:
        # Password is a lazy reference, intentionally absent from dict.items().
        # Materialize only this request payload in memory; never persist it.
        actor = state['accounts'][alias]
        return {'username': actor['username'], 'password': actor['password']}
    return {'username': alias, 'password': state['ldap_user_password']}


@pytest.fixture(scope='module', autouse=True)
def close_current_database():
    global current_context, state, engine, factory, context, origin, base
    if current_context is not None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        if os.environ.get('NOMOSMART_CHG414_API_PROFILE') != 'host-direct' and os.environ.get('NOMOSMART_CHG414_LINUX_PROFILE') == '/tmp/nms414-919553ec-native-protocol/profile.json':
            actual_context = load_native_directory_context()
            assert actual_context['native_metadata_only'] is True
            assert actual_context['runtime_profile'] == 'existing-api-v1'
            assert actual_context['runtime_purpose'] == 'native-directory-only'
            assert actual_context['real_SQL_TLS_identity_verified'] is True
            assert actual_context['application_session_established'] is False
        else:
            actual_context = load_current_context()
            assert actual_context.get('native_metadata_only') is not True, 'normal_runtime_context_required'
        current_context = actual_context
        state = current_context['protocol_tests']
        engine = create_engine(current_context['database_url'], hide_parameters=True)
        factory = sessionmaker(bind=engine)
        context = ssl.create_default_context(cafile=current_context['ca_file'])
        origin = current_context['origin']
        base = current_context['backend_url'].rstrip('/') + current_context.get('api_prefix','/api/v1')
    try:
        yield
    finally:
        if engine is not None:
            engine.dispose()


@pytest.fixture
def browser(request):
    if os.environ.get('NOMOSMART_CHG414_API_PROFILE') != 'host-direct' and os.environ.get('NOMOSMART_CHG414_LINUX_PROFILE') == '/tmp/nms414-919553ec-native-protocol/profile.json':
        raise RuntimeError('native_directory_profile_has_no_browser_or_login')
    with httpx.Client(base_url=base, verify=context, trust_env=False, headers={"Origin": origin}, timeout=20) as client:
        try:
            yield client
        finally:
            if current_context is not None and current_context.get('change_id') == 'CHG-414':
                assert current_context.get('operation_uuid') == '919553ec-fbfe-48de-a134-9832e4914652', 'current414_cleanup_scope_required'
                receipt = {'case_id': request.node.nodeid, 'session_http_status': None, 'logout_http_status': None}
                try:
                    observed = client.get('/auth/session')
                    receipt['session_http_status'] = observed.status_code
                    assert observed.status_code == 200, 'current414_cleanup_session_state_unavailable'
                    state_now = observed.json()
                    if state_now.get('authenticated') is True:
                        token = state_now.get('csrf_token')
                        assert isinstance(token, str) and token, 'current414_cleanup_csrf_unavailable'
                        logged_out = client.post('/auth/logout', headers={'X-CSRF-Token': token})
                        receipt['logout_http_status'] = logged_out.status_code
                        assert logged_out.status_code == 204, 'current414_cleanup_logout_unconfirmed'
                finally:
                    # Status-only receipt; no state body, cookie, token, headers,
                    # credential values, or request content is ever serialized.
                    import time
                    directory = root / 'protocol-session-cleanup'
                    directory.mkdir(mode=0o700, exist_ok=True)
                    assert directory.resolve() == directory and not directory.is_symlink()
                    assert directory.stat().st_uid == os.getuid() and directory.stat().st_mode & 0o077 == 0
                    path = directory / (str(os.getpid()) + '-' + str(time.time_ns()) + '.json')
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, 'w') as output:
                        json.dump(receipt, output, sort_keys=True)


def sign_in(client, username="user01"):
    response = client.post("/auth/login", json=account(username))
    assert response.status_code == 200, response.json().get("code")
    response = client.get("/auth/session")
    assert response.status_code == 200 and response.json()["authenticated"]
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def test_ldap_contract_cookie_and_no_bearer_shortcut(browser):
    public = browser.get("/auth/config").json()
    assert public["mode"] == "ldap" and public["idle_timeout_seconds"] == 1800 and public["absolute_timeout_seconds"] is None
    assert browser.get("/auth/me", headers={"Authorization": "Bearer retired-external-token"}).status_code == 401
    assert browser.post("/auth/oidc/start", json={"return_to": "/"}).status_code == 409
    sign_in(browser)
    cookie = next(c for c in browser.cookies.jar if c.name == "__Host-nomosmart_session")
    assert cookie.secure and cookie.path == "/" and "HttpOnly" in cookie._rest and cookie.expires is None
    profile = browser.get("/auth/me")
    assert profile.status_code == 200 and profile.json()["mode"] == "ldap"
    assert str(UUID(profile.json()["user_id"])) == profile.json()["user_id"]
    assert profile.json()["groups"] and profile.json()["permissions"]


@pytest.mark.parametrize("username,password", [("user01", "wrong-password"), ("user01", ""), ("*)(uid=*)", "wrong-password")])
def test_rejected_credentials_never_create_a_session(browser, username, password):
    response = browser.post("/auth/login", json={"username": account(username)["username"] if username in {"user01", "user02", "user03"} else username, "password": password})
    assert response.status_code in {401, 422}
    assert not browser.cookies.get("__Host-nomosmart_session")
    assert not browser.get("/auth/session").json()["authenticated"]


def test_origin_csrf_activity_and_local_logout(browser):
    assert browser.post("/auth/login", headers={"Origin": "https://untrusted.example.invalid"}, json=account("user01")).status_code == 403
    sign_in(browser)
    assert browser.post("/auth/activity", headers={"X-CSRF-Token": ""}).status_code == 403
    assert browser.post("/auth/activity", headers={"Origin": "https://untrusted.example.invalid"}).status_code == 403
    assert browser.post("/auth/activity").status_code == 200
    assert browser.post("/auth/logout").status_code == 204
    assert browser.get("/auth/me").status_code == 401


def test_synchronized_user_without_positive_permission_is_denied(browser):
    sign_in(browser, "user02")
    response = browser.get("/auth/me")
    assert response.status_code == 403 and response.json()["code"] == "application_access_denied"
    assert browser.get("/auth/session").json()["csrf_token"]
    assert browser.post("/auth/logout").status_code == 204


def test_real_paged_directory_and_context_bound_encryption():
    settings = get_settings()
    with factory() as session:
        current = current_setting(session)
        cfg = configuration(current)
        secret = read_secret(session, settings, current, "ldap_bind_password")
        directory = LdapDirectory(settings, cfg.directory.model_copy(update={"page_size": 1}), secret)
        result = directory.snapshot("people_and_groups")
        assert len(result.people) == state.get('expected_people', 3) and len(result.groups) == state.get('expected_groups', 2)
        assert sum(len(ids) for ids in result.user_group_ids.values()) == state.get('expected_memberships', 2)
        encrypted = session.scalar(select(AuthConnectionSecret).where(AuthConnectionSecret.setting_id == current.id, AuthConnectionSecret.purpose == "ldap_bind_password"))
        assert secret not in encrypted.envelope and encrypted.key_id == settings.auth_encryption_key_id
        with pytest.raises(AppError, match="could not be verified"):
            unseal(settings, encrypted.key_id, encrypted.envelope, context="wrong-purpose")


def test_fresh_auth_and_daily_schedule_revision(browser):
    sign_in(browser)
    before = browser.get("/system/identity-settings")
    assert before.status_code == 200
    row = before.json()
    assert not row["editable"]
    assert state["ldap_service_password"] not in before.text and "envelope" not in before.text
    body = {"configuration": row["configuration"], "expected_revision": row["revision"]}
    assert browser.post("/system/identity-settings/validate", json=body).status_code == 423
    rejected = browser.post("/system/identity-settings/reauth/start", json={"username": account("user01")["username"], "password": "wrong-password"})
    assert rejected.status_code == 401
    assert browser.get("/auth/me").status_code == 200
    assert browser.post("/system/identity-settings/reauth/start", json=account("user01")).status_code == 200
    row = browser.get("/system/identity-settings").json()
    assert row["editable"]
    cfg = row["configuration"]
    # A legal daily time; this is configuration validation, not fake scheduler time.
    cfg["sync_schedule"] = "17 3 * * *" if cfg["sync_schedule"] != "17 3 * * *" else "0 2 * * *"
    candidate = browser.post("/system/identity-settings/validate", json={"configuration": cfg, "expected_revision": row["revision"]})
    assert candidate.status_code == 200, candidate.json().get("code")
    receipt = candidate.json()
    assert not receipt["candidate_login_required"]
    activated = browser.put("/system/identity-settings", json={"candidate_id": receipt["candidate_id"], "expected_revision": row["revision"]})
    assert activated.status_code == 200 and not activated.json()["reauthentication_required"]
    assert browser.get("/auth/me").status_code == 200
    after = browser.get("/system/identity-settings").json()
    assert after["configuration"]["sync_schedule"] == cfg["sync_schedule"] and not after["editable"]
    assert after["revision"] > row["revision"]


def test_incomplete_real_directory_run_retains_committed_snapshot():
    from datetime import UTC, datetime
    from uuid import uuid4
    from sqlalchemy import func
    from app.db.models import ExternalGroup, IdentitySyncRun, Notification, RoleUser
    from app.security.auth_configuration import stage_configuration
    from app.services.directory_sync_worker import execute_directory_sync
    settings = get_settings()
    with factory.begin() as session:
        current = current_setting(session)
        cfg = configuration(current)
        limited = cfg.model_copy(update={"directory": cfg.directory.model_copy(update={"page_size": 1, "maximum_entries": 1})})
        candidate = stage_configuration(session, settings, limited, {}, None, previous=current)
        run_id, lease = uuid4(), uuid4()
        session.add(IdentitySyncRun(id=run_id, source="ldap", configuration_revision=candidate.revision, status="queued", phase="queued", trigger_type="manual", requested_scope="people_and_groups", queued_at=datetime.now(UTC), lease_token=lease, users_created=0, users_updated=0, users_disabled=0, groups_created=0, groups_updated=0, role_memberships_updated=0, attempt=0))
        before = {"users": session.scalar(select(func.count()).select_from(User)), "groups": session.scalar(select(func.count()).select_from(ExternalGroup)), "roles": session.scalar(select(func.count()).select_from(RoleUser))}
    execute_directory_sync(settings, factory, run_id, lease)
    with factory() as session:
        run = session.get(IdentitySyncRun, run_id)
        assert run.status == "failed" and run.error_code == "directory_limit_exceeded"
        after = {"users": session.scalar(select(func.count()).select_from(User)), "groups": session.scalar(select(func.count()).select_from(ExternalGroup)), "roles": session.scalar(select(func.count()).select_from(RoleUser))}
        assert after == before
        assert session.scalar(select(Notification.id).where(Notification.business_key == "directory-sync:" + str(run_id)))


def test_live_worker_sync_preserves_local_disable_and_manual_role_union(browser):
    import time
    from uuid import uuid4
    from sqlalchemy import delete
    from app.db.models import Role, RolePermission, RoleUser
    sign_in(browser)
    people = browser.get('/users').json()
    user = next(row for row in people if row['employee_id'] == state.get('union_employee_id', 'Z36303'))
    with factory.begin() as session:
        role_ids = [uuid4(), uuid4()]
        for index, role_id in enumerate(role_ids):
            session.add(Role(id=role_id, name='chg363-union-' + str(role_id), is_active=True))
            session.flush()
            session.add(RoleUser(role_id=role_id, user_id=UUID(user['id']), source='manual'))
            session.add(RolePermission(role_id=role_id, module_name='Menu', function_name='SystemManagement', can_view=True, can_edit=index == 1))
    try:
        with httpx.Client(base_url=base, verify=context, trust_env=False, headers={'Origin':origin}, timeout=20) as person:
            sign_in(person, 'user03')
            profile=person.get('/auth/me')
            assert profile.status_code == 200
            assert any(p['function_name']=='SystemManagement' and p['can_view'] and p['can_edit'] for p in profile.json()['permissions'])
            disabled=browser.patch('/users/'+user['id']+'/status',json={'is_active':False})
            assert disabled.status_code==200 and not disabled.json()['is_active']
            assert person.get('/auth/me').status_code in {401,403}
            queued=browser.post('/identity-sync/run')
            assert queued.status_code==202, queued.json().get('code')
            run_id=queued.json()['id'];deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                run=browser.get('/identity-sync/runs/'+run_id).json()
                if run['status'] in {'succeeded','failed'}:break
                time.sleep(1)
            assert run['status']=='succeeded',run.get('error_code')
            assert not browser.get('/users/'+user['id']).json()['is_active']
            assert browser.patch('/users/'+user['id']+'/status',json={'is_active':True}).status_code==200
            # Re-enabling does not revive the revoked cookie.
            assert person.get('/auth/me').status_code==401
            sign_in(person,'user03')
            assert person.get('/auth/me').status_code==200
        with factory() as session:
            assert len(session.scalars(select(RoleUser).where(RoleUser.user_id==UUID(user['id']),RoleUser.role_id.in_(role_ids),RoleUser.source=='manual')).all())==2
    finally:
        browser.patch('/users/'+user['id']+'/status',json={'is_active':True})
        with factory.begin() as session:
            session.execute(delete(RoleUser).where(RoleUser.role_id.in_(role_ids)))
            session.execute(delete(RolePermission).where(RolePermission.role_id.in_(role_ids)))
            session.execute(delete(Role).where(Role.id.in_(role_ids)))


def test_postgresql_fences_legacy_directory_producers():
    from datetime import UTC, datetime
    from uuid import uuid4
    from sqlalchemy.exc import IntegrityError
    from app.db.models import IdentitySyncRun
    with factory.begin() as session:
        with pytest.raises(IntegrityError,match='identity_sync_auth_contract_mismatch'):
            with session.begin_nested():
                session.add(IdentitySyncRun(id=uuid4(),source='keycloak',status='queued',phase='queued',trigger_type='manual',requested_scope='people_and_groups',queued_at=datetime.now(UTC),lease_token=uuid4(),users_created=0,users_updated=0,users_disabled=0,groups_created=0,groups_updated=0,role_memberships_updated=0,attempt=0))
                session.flush()


def test_explicit_oidc_binding_is_idempotent_and_conflict_checked(browser):
    from uuid import uuid4
    from sqlalchemy import delete
    sign_in(browser)
    assert browser.post('/system/identity-settings/reauth/start',json=account('user01')).status_code==200
    row=browser.get('/system/identity-settings').json();cfg=row['configuration']
    if not cfg['oidc']:
        pytest.skip('BLOCKED: current real OIDC provider and validated configuration are required for explicit bindings')
    people=browser.get('/users').json();first=next(p for p in people if p['employee_id']==state.get('union_employee_id','Z36303'));second=next(p for p in people if p['employee_id']==state.get('denial_employee_id','Z36302'))
    with factory() as session:
        object_ids={str(p.id):p.directory_object_id for p in session.scalars(select(User)).all()}
    subject='chg363-explicit-'+uuid4().hex
    body={'source_id':cfg['directory']['source_id'],'issuer':cfg['oidc']['issuer'],'subject':subject,'user_id':first['id'],'directory_object_id':object_ids[first['id']],'expected_revision':row['revision']}
    try:
        result=browser.post('/system/identity-settings/identity-bindings',json=body)
        assert result.status_code==200
        repeated=browser.post('/system/identity-settings/identity-bindings',json=body)
        assert repeated.status_code==200 and repeated.json()==result.json()
        body.update(user_id=second['id'],directory_object_id=object_ids[second['id']])
        assert browser.post('/system/identity-settings/identity-bindings',json=body).status_code==409
        body['directory_object_id']='unrelated-stable-object'
        assert browser.post('/system/identity-settings/identity-bindings',json=body).status_code==422
    finally:
        from app.db.models import AuthenticationIdentity
        with factory.begin() as session:
            session.execute(delete(AuthenticationIdentity).where(AuthenticationIdentity.subject==subject))
