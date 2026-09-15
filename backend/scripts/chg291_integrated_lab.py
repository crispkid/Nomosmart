"""Adapt the inspected prior real-service lab to a new private approved run.

Copies only known .py tooling templates, never prior state/env/credentials/data.
Actual start/prepare/test/cleanup remain explicit CLI steps. No Provider path.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from chg291_integrated_preparation import guard, clean_env, put, PYTHON

TEMPLATE = Path('/private/tmp/chg299-live.IP4kuZ')


def materialize(root, refresh=False):
    guard(root)
    assert not (root / 'private-state.json').exists(), 'Never rewrite running lab tooling'
    previous = json.loads((root / 'lab-tooling.json').read_text()) if refresh else {}
    if not refresh:
        assert not (root / 'stack.py').exists()
    for name, record in previous.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == record['generatedSha256']
    source = root / 'source'
    records = {}
    for name in ('stack.py', 'prepare.py', 'prepare_api.py', 'transport.py',
                 'run_focused.py', 'run_capture.py', 'cleanup_verified.py'):
        path = TEMPLATE / name
        original = path.read_text()
        body = original.replace('/tmp/chg299-live.IP4kuZ', str(root))
        body = body.replace('chg299-live-ip4kuz', root.name).replace('chg299-api-ip4kuz', root.name + '-api')
        body = body.replace("REPO = Path('/Users/peter/Documents/GitHub/Nomosmart')", f'REPO = Path({str(source)!r})')
        if name == 'stack.py':
            body = body.replace('sha256:9b18b78397054fce88a9552e9d5a3ad5bb7fd258c5b3cc1c5028e46373d6ea8f',
                                'sha256:d44dceab9181bb118b01c269135d2443aa4d519e55916017c26a7fc3db6b6a7a')
            before = '        fullenv = dict(os.environ, **env)'
            assert before in body
            body = body.replace(before, '''        if name == 'postgres':
            env.update(NOMOSMART_DB='nomosmart', NOMOSMART_DB_USER='nomosmart',
                NOMOSMART_MIGRATION_USER='nomosmart_migrator', KEYCLOAK_DB='isolated_identity',
                KEYCLOAK_DB_USER='isolated_identity')
            state['secret_files'] = []
            for key in ('NOMOSMART_DB_PASSWORD', 'NOMOSMART_MIGRATION_PASSWORD', 'KEYCLOAK_DB_PASSWORD'):
                secret_file = ROOT / (key.lower() + '.secret')
                secret_file.write_text(secrets.token_hex(24)); secret_file.chmod(0o600)
                args += ['-v', str(secret_file)+':/run/secrets/'+key+':ro']
                env[key+'_FILE'] = '/run/secrets/'+key
                state['secret_files'].append(str(secret_file))
            save(state)
        fullenv = dict(os.environ, **env)''')
        elif name == 'prepare.py':
            body = body.replace("['nomosmart', 'acceptance_chg292', 'acceptance_chg293', 'acceptance_chg295']",
                                "['acceptance_chg292', 'acceptance_chg293', 'acceptance_chg295']")
            body = body.replace("    cursor.execute('CREATE ROLE nomosmart NOLOGIN')\n", '')
            # Use the exact new candidate's packaged migrations, not a mounted
            # host SQL directory or a historical migration image.
            candidate = json.loads((root/'images/migrations-build.json').read_text())
            image_id = candidate['imageId']
            body = body.replace('sha256:f3c8433401abf859ef9022584c8e6111684363ec490f737e749e9a4705ea32d0', image_id)
            body = body.replace("    '-v',str(REPO/'sql/migrations')+':/flyway/sql:ro', image,", '    image,')
            start = body.index('result=command(')
            end = body.index("prefix='postgresql", start)
            call = body[start:end].replace("'-target=48'", "'-target='+str(target_version)")
            body = body[:start] + 'for target_version in (48, 49):\n' + ''.join('    '+line+'\n' for line in call.splitlines()) + body[end:]
            body = body.replace('FLYWAY48_AND_ENVIRONMENT_READY', 'FLYWAY49_AND_ENVIRONMENT_READY')
        elif name == 'prepare_api.py':
            body = body.replace("CHG292_MAX_MIGRATION='48'", "CHG292_MAX_MIGRATION='49'")
            body = body.replace("NOMOSMART_TEST_MAX_MIGRATION='48'", "NOMOSMART_TEST_MAX_MIGRATION='49'")
        body = body.replace('CHG299', 'CHG291 integrated') if name in ('stack.py', 'prepare.py', 'prepare_api.py') else body
        if name == 'prepare_api.py':
            body = body.replace('Flyway V048 database', 'Flyway V049 database')
        # Do not mechanically rename CHG299_ISOLATED, an existing safety contract.
        target = root / name
        with target.open('w' if refresh else 'x') as stream:
            target.chmod(0o600)
            stream.write(body)
        records[name] = {'templateSha256': hashlib.sha256(original.encode()).hexdigest(),
                         'generatedSha256': hashlib.sha256(body.encode()).hexdigest()}
    if refresh:
        with (root/'lab-tooling.json').open('w') as stream:
            json.dump(records, stream, indent=2)
    else:
        put(root / 'lab-tooling.json', records)
    print('NEW_LAB_TOOLING_READY; no prior credentials/state copied')


def run(root, action, extra):
    guard(root)
    records = json.loads((root / 'lab-tooling.json').read_text())
    for name, record in records.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest() == record['generatedSha256']
    env = clean_env(root)
    if action == 'start':
        command = [str(PYTHON), '-B', str(root/'stack.py'), 'start']
    elif action == 'transport':
        command = [str(PYTHON), '-B', str(root/'transport.py')]
    elif action in ('prepare', 'prepare-api', 'cleanup'):
        name = {'prepare': 'prepare.py', 'prepare-api': 'prepare_api.py', 'cleanup': 'cleanup_verified.py'}[action]
        command = [str(PYTHON), '-B', str(root/name)]
    elif action == 'test':
        assert len(extra) >= 2
        command = [str(PYTHON), '-B', str(root/'run_capture.py'), *extra]
    else:
        raise ValueError('Unsupported action')
    os.chdir(root)
    os.execve(command[0], command, env)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('materialize', 'refresh', 'start', 'transport', 'prepare', 'prepare-api', 'test', 'cleanup'))
    parser.add_argument('--root', required=True, type=Path)
    args, extra = parser.parse_known_args()
    if args.action in ('materialize', 'refresh'):
        assert not extra
        materialize(args.root, refresh=args.action == 'refresh')
    else:
        run(args.root, args.action, extra)
