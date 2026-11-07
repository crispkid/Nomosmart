"""Current protocol equivalents for missing/disabled/no-menu identities."""
from pathlib import Path
import os
from uuid import uuid4

import httpx

from current_live_support import current_live  # noqa: F401
from scripts.current_e2e_governance_fixture import read_private


def task_path(live):
    if live.context.get('change_id')=='CHG-414':
        from chg418_retained_auth_task import read_task_path
        return read_task_path(live)
    root = Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).parent
    browser = read_private(root / 'browser-work/context.json')
    assert browser['run_id'] == live.context['run_id']
    return 'approvals/' + browser['approval_task_id']


def anonymous(live):
    c = live.context
    return httpx.Client(base_url=c['backend_url'] + c['api_prefix'] + '/',
        verify=c['ca_file'], timeout=15, trust_env=False, headers={'Origin': c['origin']})


def test_current_unknown_task_missing_session_and_no_menu_identity(current_live):
    live = current_live
    path = task_path(live)
    owner = live.actor('owner')
    try:
        assert owner.get('approvals/' + str(uuid4())).status_code == 404
        with anonymous(live) as client:
            missing = client.get(path)
            assert missing.status_code == 401 and missing.json()['code'] == 'authentication_required'
            person = live.context['actors']['denial']
            assert client.post('auth/login', json={key: person[key] for key in ('username', 'password')}).status_code == 200
            try:
                denied = client.get(path)
                assert denied.status_code == 403 and denied.json()['code'] == 'application_access_denied'
                assert client.get('auth/me').status_code == 403
            finally:
                state = client.get('auth/session')
                assert state.status_code == 200 and state.json()['authenticated']
                assert client.post('auth/logout', headers={'X-CSRF-Token': state.json()['csrf_token']}).status_code == 204
    finally:
        assert owner.post('auth/logout').status_code == 204


def test_current_disabled_directory_user_cannot_login_and_old_session_is_revoked(current_live):
    live = current_live
    victim = live.actor('system_viewer')
    operator = live.actor('system_editor')
    person = live.context['actors']['system_viewer']
    path = 'users/' + person['user_id'] + '/status'
    try:
        assert operator.patch(path, json={'is_active': False}).status_code == 200
        revoked = victim.get('auth/me')
        assert revoked.status_code == 401 and revoked.json()['code'] == 'session_expired'
        with anonymous(live) as client:
            response = client.post('auth/login', json={key: person[key] for key in ('username', 'password')})
            assert response.status_code == 403 and response.json()['code'] == 'user_disabled'
    finally:
        assert operator.patch(path, json={'is_active': True}).status_code == 200
        assert operator.post('auth/logout').status_code == 204
