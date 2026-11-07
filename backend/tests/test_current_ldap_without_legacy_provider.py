"""Current real LDAP/API behavior while the exact retired IdP remains stopped."""
from contextlib import ExitStack
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from current_live_support import CurrentLive, load_current_context


def test_current_api_import_ldap_session_and_reads_do_not_require_legacy_provider():
    context = load_current_context()
    assert context['auth_mode'] == 'ldap'
    root = Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).parent
    path = root / 'ldap-without-legacy-provider.json'
    assert not path.exists()
    retired = context.get('retired_identity_provider')
    assert retired and set(retired) == {'container_id', 'owner_run_uuid'}, 'retired_provider_readonly_metadata_required'
    cid = retired['container_id']
    assert len(cid) == 64 and all(value in '0123456789abcdef' for value in cid)
    template = '{{json .Id}}\n{{json .Config.Labels}}\n{{json .State.Running}}'

    def observe_stopped():
        result = subprocess.run(['docker', 'inspect', '--format', template, cid],
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0
        actual, labels, running = map(json.loads, result.stdout.splitlines())
        assert actual == cid and labels['nomosmart.run'] == retired['owner_run_uuid']
        assert running is False, 'Retired IdP must already be stopped; no restart or repair is authorized'

    observe_stopped()
    proof = {'run_uuid': context['run_id'], 'container_id': cid,
             'phase': 'RETIRED_PROVIDER_OBSERVED_STOPPED',
             'original_container_or_credential_operations': 0, 'provider_start_stop_commands': 0}

    def save():
        path.write_text(json.dumps(proof, indent=2))
        path.chmod(0o600)

    save()
    try:
        tests = str(Path(__file__).resolve().parent)
        code = ('import sys; sys.path.insert(0, ' + repr(tests) + '); '
                'import test_live_backend_api_behavior as m; '
                'assert m.CURRENT_CONTEXT is not None; '
                'assert m.SERVICE_TOKEN is None and m.SERVICE_CLAIMS is None; '
                'print("CURRENT_IMPORT_WITHOUT_LEGACY_GRANT")')
        imported = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True,
                                  cwd=Path(__file__).resolve().parents[1], timeout=30)
        proof.update(child_import_exit=imported.returncode, child_import_stderr_bytes=len(imported.stderr))
        save()
        assert imported.returncode == 0, 'current API import required the unavailable legacy provider'
        assert b'CURRENT_IMPORT_WITHOUT_LEGACY_GRANT' in imported.stdout
        with ExitStack() as stack:
            live = CurrentLive(context, stack)
            client = live.actor('owner')
            try:
                me = client.get('auth/me')
                assert me.status_code == 200 and me.json()['mode'] == 'ldap'
                users = client.get('users')
                assert users.status_code == 200 and isinstance(users.json(), list)
                assert context['actors']['owner']['user_id'] in {row['id'] for row in users.json()}
                proof.update(phase='REAL_LDAP_AND_PROTECTED_API_PASS_WITH_LEGACY_DOWN',
                             real_ldap_session=True, actual_protected_read=True, eager_legacy_token=None)
                save()
            finally:
                assert client.post('auth/logout').status_code == 204
    finally:
        observe_stopped()
        proof.update(retired_provider_remains_stopped=True, completed_at_utc=datetime.now(UTC).isoformat())
        save()
