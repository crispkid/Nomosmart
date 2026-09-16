"""Bounded candidate image checks in the approved disposable lab, never live DB."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote
from uuid import uuid4

from chg291_integrated_preparation import guard, clean_env, put


def main(root):
    manifest = guard(root)
    state = json.loads((root/'private-state.json').read_text())
    assert state['label'] == root.name and not state.get('cleaned')
    env = clean_env(root)
    docker = ['docker', '--context', 'desktop-linux']
    def command(args, *, input=None, extra=None):
        outcome = subprocess.run(docker+args, env={**env, **(extra or {})}, input=input,
                                 text=True, capture_output=True, timeout=90)
        assert outcome.returncode == 0, 'Candidate operation failed; no automatic retry'
        return outcome.stdout
    for name, cid in state['containers'].items():
        info = json.loads(command(['inspect', cid]))[0]
        assert info['Config']['Labels']['nomosmart.acceptance'] == root.name
        assert info['HostConfig']['NetworkMode'] == root.name
    images = {name: json.loads((root/f'images/{name}-build.json').read_text())['imageId']
              for name in ('backend', 'migrations')}
    assert len(state['containers']) == 7
    network = json.loads(command(['network', 'inspect', state['network']]))[0]
    assert network['Internal'] and set(network['Containers']) == set(state['containers'].values())
    import psycopg2
    connection = psycopg2.connect(host='127.0.0.1', port=15834, user='postgres',
                                 password=state['password'], dbname='acceptance')
    connection.autocommit = True
    db = 'gate_' + uuid4().hex
    with connection.cursor() as cursor:
        cursor.execute('CREATE DATABASE '+db)
    connection.close()
    name = root.name+'-gate-migration'
    log = command(['run','--rm','--pull=never','--name',name,
        '--label','nomosmart.acceptance='+root.name,'--network',root.name,
        '--memory','512m','--cpus','1','--cap-drop=ALL','--security-opt','no-new-privileges',
        '-e','FLYWAY_PASSWORD',images['migrations'],
        '-url=jdbc:postgresql://'+root.name+'-postgres:5432/'+db,'-user=postgres',
        '-target=48','migrate'], extra={'FLYWAY_PASSWORD':state['password']})
    log_path = root/'results/migration-gate-v048.log'
    with log_path.open('x') as stream:
        log_path.chmod(0o600); stream.write(log)
    program = '''import json,os,sys
from dataclasses import asdict
from sqlalchemy import create_engine,text
from app.core.config import Settings
from app.deployment.bootstrap import _database_check
settings=Settings(_env_file=None)
engine=create_engine(settings.database_url.get_secret_value())
with engine.connect() as c:
    latest=c.scalar(text("SELECT max(version::integer) FROM flyway_schema_history WHERE success"))
    has49=c.scalar(text("SELECT count(*) FROM flyway_schema_history WHERE version::integer=49 AND success"))
assert latest==48 and has49==0
check=_database_check(settings)
print(json.dumps({'uid':os.getuid(),'python':sys.version.split()[0],
 'flywayVersion':latest,'successfulV049Rows':has49,'databaseReadinessResult':asdict(check),
 'finding':'V048 accepted without V049; migration ordering is not enforced by this check'}))
'''
    raw = command(['run','--rm','--interactive','--pull=never','--name',root.name+'-gate-backend',
        '--label','nomosmart.acceptance='+root.name,'--network',root.name,
        '--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=64m',
        '--memory','512m','--cpus','1','--cap-drop=ALL','--security-opt','no-new-privileges',
        '-e','DATABASE_URL','-e','APP_ENV=test','-e','APP_ENCRYPTION_KEY','-e','PYTHONDONTWRITEBYTECODE=1',
        '--entrypoint','python',images['backend'],'-'], input=program,
        extra={'DATABASE_URL':'postgresql+psycopg2://postgres:'+quote(state['password'])+'@'+root.name+'-postgres:5432/'+db,
               'APP_ENCRYPTION_KEY':state['app_key']})
    result = json.loads(raw)
    assert result['uid'] != 0 and result['successfulV049Rows'] == 0
    result.update(sourceSha256=manifest['sourceSha256'], images=images,
                  isolatedDatabase=db, providerCalls=0, currentEnvironmentWrites=0,
                  migrationLogSha256=hashlib.sha256(log.encode()).hexdigest(),
                  releaseGate='BLOCKED: real V048 readiness acceptance reproduced')
    put(root/'results/migration-order-probe.json',result)
    print(json.dumps(result))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    main(parser.parse_args().root)
