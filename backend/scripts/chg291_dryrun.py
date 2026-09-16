"""Source/image-bound hidden-Secret server dry run. Never a deployment gate PASS."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from chg291_integrated_preparation import guard, clean_env, put, PYTHON


def main(root):
    manifest=guard(root)
    template=Path('/private/tmp/chg293-build.5fYxc2/dryrun.py').read_text()
    body=template.replace("ROOT = Path('/Users/peter/Documents/GitHub/Nomosmart')",
                          f'ROOT = Path({str(root/"source")!r})')
    body=body.replace('0.1.0-chg293','0.1.0-chg299-v049')
    body=body.replace("value.replace('chg292','chg293')", "value.replace('chg292','chg299-v049')")
    old_ids={'backend':'sha256:7a367c11fc6a49825c57826714536832e81a27455130b652b7361d78bc2eec4d',
             'frontend':'sha256:500a02af6d9e318e944a23774bbb432d9cb77d2eb331882860ecf3b3eb712a80',
             'migrations':'sha256:bf9cb98e13bc396210a0a82bd785e602bde14ae4e240ca5f81fc9b9c0d4dafab'}
    for key,old in old_ids.items():
        candidate=json.loads((root/f'images/{key}-build.json').read_text())
        assert candidate['exitCode']==0
        body=body.replace(old,candidate['imageId'])
    body=body.replace("'nomosmart/migrations:0.1.0-chg288':'sha256:",
                      "'nomosmart/migrations:0.1.0-chg299-v049':'sha256:")
    body=body.replace("images['nomosmart/migrations:0.1.0-chg288']", "images['nomosmart/migrations:0.1.0-chg299-v049']")
    marker="    if key in {'nomosmart.io/deployment-release','DEPLOYMENT_BOOTSTRAP_RELEASE'}"
    assert marker in body
    body=body.replace(marker,"    if key=='image' and value=='nomosmart/migrations:0.1.0-chg288':\n        return 'nomosmart/migrations:0.1.0-chg299-v049'\n    if key=='schema_contract' and value=='forward-v047':\n        return 'forward-v049'\n"+marker)
    marker="        '--dry-run=server','--hide-secret','--timeout','15m']"
    assert marker in body
    body=body.replace(marker,"        '--set-string','image.migration.tag=0.1.0-chg299-v049',\n        '--set-string','compatibility.schemaContract=forward-v049',\n"+marker)
    script=root/'candidate-dryrun.py'
    with script.open('x') as stream:
        script.chmod(0o600);stream.write(body)
    outcome=subprocess.run([str(PYTHON),'-B',str(script)],env=clean_env(root),
                           capture_output=True,text=True,timeout=420)
    # The inspected template emits only summaries/diff paths, never values or
    # manifests. stderr is fingerprinted, not displayed or stored.
    summaries=[json.loads(line) for line in outcome.stdout.splitlines() if line.startswith('{')]
    result={'exitCode':outcome.returncode,'sourceSha256':manifest['sourceSha256'],
            'scriptSha256':hashlib.sha256(body.encode()).hexdigest(),'summaries':summaries,
            'stderrSha256':hashlib.sha256(outcome.stderr.encode()).hexdigest(),
            'deploymentAuthorized':False,'readinessOrderingGate':'BLOCKED separately'}
    guard(root)
    put(root/'results/candidate-dryrun.json',result)
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    main(parser.parse_args().root)
