"""Real current sessions, default list contract and permission union/revocation."""
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, text

from app.db.models import IntegrationClient, Role, RolePermission, RoleUser
from current_live_support import current_live as _common_current_live
import pytest


@pytest.fixture(scope="module")
def current_live(_common_current_live):
    from chg418_user_role_inputs import viewer_menu_input
    with viewer_menu_input(_common_current_live) as live:
        yield live


def test_current_integration_client_defaults_and_permission_union(current_live):
    live = current_live
    root = Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).parent
    path = root / ('integration-client-menu-' + uuid4().hex + '.json')
    actor = live.actor('project_viewer')
    outsider = live.actor('viewer')
    actor_id = UUID(live.context['actors']['project_viewer']['user_id'])
    role_id, permission_id = uuid4(), uuid4()
    proof = {'run_id': live.context['run_id'], 'role_id': str(role_id),
             'permission_id': str(permission_id), 'user_id': str(actor_id),
             'created_after': datetime.now(UTC).isoformat(), 'phase': 'BEFORE_INPUTS'}

    def save():
        path.write_text(json.dumps(proof, indent=2))
        path.chmod(0o600)

    def fingerprint(session, table):
        assert table in {'integration_clients', 'role_users', 'roles', 'role_permissions'}
        return session.scalar(text("SELECT md5(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')::text) FROM " + table + ' t'))

    save()
    created = False
    with live.database() as session:
        before = {name: fingerprint(session, name) for name in
                  ('integration_clients', 'role_users', 'roles', 'role_permissions')}
        expected = set(map(str, session.scalars(select(IntegrationClient.id))))
        assert len(expected) < 50, 'Current default page requires fewer than fifty owned clients'
        assert session.get(Role, role_id) is None and session.get(RolePermission, permission_id) is None
        assert actor.get('integration-clients').status_code == 403
        assert outsider.get('integration-clients').status_code == 403
        try:
            role = Role(id=role_id, name='chg370-integration-menu-' + role_id.hex,
                        is_active=True, is_system=False)
            session.add(role)
            session.flush()
            session.add(RolePermission(id=permission_id, role_id=role_id,
                module_name='Menu', function_name='SystemManagement', can_view=True))
            session.add(RoleUser(role_id=role_id, user_id=actor_id, source='manual'))
            session.commit()
            created = True
            proof['phase'] = 'REAL_MENU_GRANT_COMMITTED'
            save()
            result = actor.get('integration-clients')
            assert result.status_code == 200
            payload = result.json()
            assert {item['id'] for item in payload['items']} == expected
            assert payload['next_cursor'] is None and payload['has_more'] is False
            assert all('api_key' not in item for item in payload['items'])
            empty = actor.get('integration-clients', params={'name': 'chg370-absent-' + uuid4().hex})
            assert empty.status_code == 200 and empty.json()['items'] == []
            assert empty.json()['next_cursor'] is None and empty.json()['has_more'] is False
            for params in ({'limit': 0}, {'limit': 101}, {'expiry': 'invalid'}):
                assert actor.get('integration-clients', params=params).status_code == 422
            assert outsider.get('integration-clients').status_code == 403
            proof['phase'] = 'DEFAULTS_VALIDATION_AND_UNION_PASS'
            save()
        finally:
            session.rollback()
            if created:
                membership = session.get(RoleUser, (role_id, actor_id, 'manual'))
                permission = session.get(RolePermission, permission_id)
                role = session.get(Role, role_id)
                assert membership is not None and permission.role_id == role_id
                assert role.name == 'chg370-integration-menu-' + role_id.hex and not role.is_system
                session.delete(membership)
                session.delete(permission)
                session.flush()
                session.delete(role)
                session.commit()
            assert {name: fingerprint(session, name) for name in before} == before
            assert actor.get('integration-clients').status_code == 403
            assert actor.post('auth/logout').status_code == 204
            assert outsider.post('auth/logout').status_code == 204
            proof.update(cleanup_complete=True, all_four_original_tables_unchanged=True)
            save()
