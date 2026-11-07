"""Real HTTP default and permission checks for repaired acceptance contracts."""
from uuid import uuid4

from app.db.models import Role, RolePermission, RoleUser
import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_session_factory
from app.main import create_app
from owned_service_scope import verify_owned_services


@pytest.fixture
def scoped_data():
    # This test only needs real identities + SQL. It must not build an unrelated
    # generated corpus or inherit permission overrides from a workflow fixture.
    verify_owned_services(get_settings())
    path=Path(os.environ['NOMOSMART_TEST_IDENTITIES'])
    assert path==Path('/run/regression/identities.json') and not path.is_symlink()
    assert path.stat().st_uid==os.getuid() and path.stat().st_mode & 0o077==0
    identities=json.loads(path.read_bytes())
    with get_session_factory()() as session, TestClient(create_app()) as client:
        users={};headers={}
        for name in ('editor','outsider'):
            identity=identities[name]
            user=User(id=uuid4(),keycloak_user_id=identity['subject'],display_name='CHG341 '+name,
                      is_active=True,auth_source='keycloak')
            session.add(user);users[name]=user
            headers[name]={'Authorization':'Bearer '+identity['access_token']}
        session.commit()
        yield client,users,headers,session,None,None,None,None



def test_integration_client_http_defaults_and_permission_denial(scoped_data):
    client, users, headers, session, _, _, _, _ = scoped_data
    path = "/api/v1/integration-clients"
    assert client.get(path, headers=headers["editor"]).status_code == 403
    role = Role(name="CHG295 system menu " + uuid4().hex, is_active=True)
    session.add(role); session.flush()
    session.add(RolePermission(role_id=role.id, module_name="Menu", function_name="SystemManagement", can_view=True))
    assignment = RoleUser(role_id=role.id, user_id=users["editor"].id, source="manual")
    session.add(assignment); session.commit()
    try:
        response = client.get(path, headers=headers["editor"])
        assert response.status_code == 200, response.text
        assert response.json()["items"] == [] and response.json()["next_cursor"] is None
        assert client.get(path, headers=headers["editor"], params={"limit": 0}).status_code == 422
        assert client.get(path, headers=headers["editor"], params={"limit": 101}).status_code == 422
        assert client.get(path, headers=headers["editor"], params={"expiry": "invalid"}).status_code == 422
        assert client.get(path, headers=headers["outsider"]).status_code == 403
    finally:
        session.delete(assignment); session.commit()
    assert client.get(path, headers=headers["editor"]).status_code == 403
