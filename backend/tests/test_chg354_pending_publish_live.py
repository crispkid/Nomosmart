"""Three read-contract groups against real disposable TLS/OIDC/PostgreSQL.

Controlled approved fields are query inputs, never approval/publish evidence.
No Provider, business decision or successful publication is invoked here.
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
from uuid import uuid4

import httpx
import pytest


@pytest.fixture(scope='module')
def live():
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from current_pending_publish_support import live_current
        with live_current() as value:
            yield value
        return
    descriptor = os.environ.get('CHG354_AUTH_PACKET_FD')
    if descriptor is None:
        pytest.skip('BLOCKED: current approved CHG-354 anonymous OIDC context required')
    with os.fdopen(int(descriptor)) as stream:
        packet = json.load(stream)
    root = Path(packet['original_root'])
    status = json.loads((root / 'docs/CHG-354-PLAN-STATUS.json').read_text())
    state = json.loads((root / '.operator/chg354/runtime/run.json').read_text())
    assert status['gate_4']['status'] == 'APPROVED'
    assert hashlib.sha256((root / status['plan']['path']).read_bytes()).hexdigest() == status['plan']['sha256']
    assert state['authority_run_id'] == status['run_id'] and state['run_id'] == packet['run_id'] and not state.get('cleanup')
    assert datetime.now().timestamp() < state['runtime_deadline']
    assert packet['origin'] == state['origin'] == 'https://localhost:38443'
    assert packet['ca_file'] == str(Path(state['source']) / 'deploy/docker/generated/current/tls/active/edge-ca.crt')
    with httpx.Client(base_url=packet['origin'] + '/api/backend', verify=ssl.create_default_context(cafile=packet['ca_file']), trust_env=False, timeout=30) as client:
        yield packet, client, state


def read(live, params=None, actor='owner', path='/approvals/pending-publish/page', status=200):
    packet, client, _ = live
    headers = (packet['session_headers'][actor]if actor else{})if packet.get('auth_contract_revision')==2 else({'Authorization':'Bearer '+packet['tokens'][actor]}if actor else{})
    response = client.get(path, params=params, headers=headers)
    assert response.status_code == status, f'HTTP {response.status_code}; expected {status}'
    return response.json()


def sql(live, statement):
    state = live[2]
    if "actual_live" in state:
        from current_pending_publish_support import sql_current
        return sql_current(state,statement)
    result = subprocess.run(['docker', '--context', 'desktop-linux', 'exec', '-i', state['project'] + '-postgresql-1',
                             'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'nomosmart'],
                            input=statement, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, 'Owned SQL control transaction failed'
    return result.stdout.strip()


def test_cross_100_unique_rows_totals_and_legacy_contract(live):
    seed = live[0]['seed']
    ids, rows, pages = [], [], 0
    params = {}
    while True:
        page = read(live, params)
        pages += 1
        assert page['total'] == 135 and len(page['items']) <= 20
        assert page['has_more'] == bool(page['next_cursor'])
        rows.extend(page['items'])
        ids.extend(item['document_version_id'] for item in page['items'])
        if not page['has_more']:
            break
        assert pages < 8
        params['cursor'] = page['next_cursor']
    assert pages == 7 and ids == seed['expected_owner_ids'] and len(set(ids)) == 135
    by_id = {row['document_version_id']: row for row in rows}
    for item in seed['records'][:135]:
        assert by_id[item['version_id']]['approval_request_id'] == item['request_id']
        assert by_id[item['version_id']]['approval_task_id'] == item['task_id']
    missing = by_id[seed['records'][134]['version_id']]
    assert missing['approval_request_id'] is None and missing['submitter_name'] is None
    legacy = read(live, path='/approvals/pending-publish')
    assert isinstance(legacy, list) and len(legacy) == 100
    assert all({'document_version_id', 'lock_version', 'approved_at'} <= row.keys() for row in legacy)


def test_authorized_counts_cursor_scope_and_safe_validation(live):
    seed = live[0]['seed']
    viewer = read(live, actor='viewer')
    assert viewer == {'items': [], 'total': 0, 'has_more': False, 'next_cursor': None}
    outsider = read(live, actor='outsider')
    assert outsider['total'] == 2
    assert {row['document_version_id'] for row in outsider['items']} == {r['version_id'] for r in seed['records'][135:137]}
    read(live, actor=None, status=401)
    first = read(live, {'limit': 1})
    cursor = first['next_cursor']
    assert cursor
    for actor in ('viewer', 'outsider'):
        assert read(live, {'cursor': cursor}, actor, status=422)['code'] == 'cursor_scope_mismatch'
    changed = ('A' if cursor[0] != 'A' else 'B') + cursor[1:]
    assert read(live, {'cursor': changed}, status=422)['code'] == 'cursor_invalid'
    other = read(live, {'limit': 1}, path='/approvals/history')
    assert other['next_cursor']
    assert read(live, {'cursor': other['next_cursor']}, status=422)['code'] == 'cursor_invalid'
    for params in ({'limit': 0}, {'limit': 101}, [('limit', '1'), ('limit', '2')], [('cursor', cursor), ('cursor', cursor)]):
        read(live, params, status=422)
    project, owner = seed['projects'][0], seed['actors']['owner']
    try:
        sql(live, f"DELETE FROM project_owners WHERE project_id='{project}' AND user_id='{owner}';")
        assert read(live, {'cursor': cursor}, status=422)['code'] == 'cursor_scope_mismatch'
        assert read(live)['total'] == 0
    finally:
        sql(live, f"INSERT INTO project_owners(project_id,user_id,created_at) VALUES('{project}','{owner}',now()) ON CONFLICT DO NOTHING;")


def test_keyset_survives_removal_new_front_row_and_empty_tail(live):
    seed = live[0]['seed']
    first = read(live)
    cursor = first['next_cursor']
    removed = first['items'][0]['document_version_id']
    request_id = str(uuid4())
    added = seed['records'][138]
    project = seed['projects'][0]
    try:
        sql(live, f"UPDATE document_versions SET status='draft' WHERE id='{removed}';")
        second = read(live, {'cursor': cursor})
        assert second['total'] == 134
        assert [r['document_version_id'] for r in second['items']] == seed['expected_owner_ids'][20:40]
        sql(live, f"""BEGIN;
UPDATE document_versions SET status='approved' WHERE id='{added['version_id']}';
INSERT INTO approval_requests(id,project_id,document_id,document_version_id,submitter_id,status,submitted_at,approved_at,created_at)
VALUES('{request_id}','{project}','{added['document_id']}','{added['version_id']}','{seed['actors']['viewer']}','approved',now(),now(),now());
COMMIT;""")
        refreshed = read(live)
        assert refreshed['total'] == 135 and refreshed['items'][0]['document_version_id'] == added['version_id']
        sql(live, f"UPDATE document_versions SET status='draft' WHERE project_id='{project}';")
        assert read(live, {'cursor': cursor}) == {'items': [], 'total': 0, 'has_more': False, 'next_cursor': None}
    finally:
        sql(live, f"""BEGIN;
DELETE FROM approval_requests WHERE id='{request_id}';
UPDATE document_versions SET status='approved' WHERE project_id='{project}' AND id<>'{added['version_id']}';
UPDATE document_versions SET status='draft' WHERE id='{added['version_id']}';
COMMIT;""")
    assert read(live)['total'] == 135
