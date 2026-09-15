"""Real HTTP default and permission checks for repaired acceptance contracts."""
from uuid import uuid4

from app.db.models import Role, RolePermission, RoleUser
from test_chg293_project_content_and_chat_history import authenticated, live_engine, scoped_data


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
