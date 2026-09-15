"""Source-bound pytest process isolation; no test selection/expectation changes."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from chg291_integrated_preparation import guard, clean_env, put, PYTHON


def main(root, label, tests):
    manifest = guard(root)
    assert re.fullmatch('[a-z0-9-]+',label)
    state=json.loads((root/'private-state.json').read_text())
    assert state['label']==root.name and not state.get('cleaned')
    env=clean_env(root)
    env.update(json.loads((root/'environment-api.json').read_text()))
    assert '127.0.0.1:15834/nomosmart' in env['DATABASE_URL']
    assert env['OIDC_ISSUER_URL']=='https://127.0.0.1:18834/realms/'+root.name+'-api'
    assert not env.get('CHG298_MODEL_BINDING')
    env.update(CHG295_ISOLATED_REALM=root.name+'-api', CHG296_ISOLATED='1',
               CHG297_ISOLATED='1', CHG298_ISOLATED='1', CHG299_ISOLATED='1',
               CHG295_BUG_DATABASE_URL=env['DATABASE_URL'])
    for key, value in {'DB':env['DATABASE_URL'],'NEO4J':env['NEO4J_URI'],
                       'OPENSEARCH':env['OPENSEARCH_URL'],'S3':env['S3_ENDPOINT_URL'],
                       'S3_KEY':env['S3_ACCESS_KEY_ID'],'S3_SECRET':env['S3_SECRET_ACCESS_KEY']}.items():
        env['CHG295_CLEANUP_'+key]=value
    if tests != ['tests']:
        for name in tests:
            assert re.fullmatch(r'tests/test_[a-z0-9_]+\.py',name)
            assert (root/'source/backend'/name).is_file()
    log=root/(label+'.log'); xml=root/(label+'.xml'); cov=root/(label+'-coverage.json')
    assert not any(p.exists() for p in (log,xml,cov))
    env['COVERAGE_FILE']=str(root/(label+'.coverage'))
    command=[str(PYTHON),'-B','-m','pytest','-o','addopts=','-p','no:cacheprovider',
             '--tb=short','-q',*tests,'--junitxml='+str(xml),'--cov=app',
             '--cov-report=json:'+str(cov),'--cov-report=term','--cov-fail-under=80']
    started=time.time()
    with log.open('x') as stream:
        log.chmod(0o600)
        outcome=subprocess.run(command,cwd=root/'source/backend',env=env,
                               stdout=stream,stderr=subprocess.STDOUT,timeout=900)
    result={'command':command,'exitCode':outcome.returncode,
            'elapsedSeconds':round(time.time()-started,2),'sourceSha256':manifest['sourceSha256']}
    if xml.exists():
        result['suites']=[node.attrib for node in ET.parse(xml).iter('testsuite')]
    if cov.exists():
        result['coverageTotals']=json.loads(cov.read_text())['totals']
    put(root/(label+'-result.json'),result)
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--label',required=True)
    parser.add_argument('tests',nargs='+')
    args=parser.parse_args()
    main(args.root,args.label,args.tests)
