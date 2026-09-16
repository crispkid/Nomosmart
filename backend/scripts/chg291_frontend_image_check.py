"""Rebind existing real isolated image assertions to this approved candidate."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from chg291_integrated_preparation import guard, clean_env, put, NODE


def main(root):
    manifest=guard(root)
    state=json.loads((root/'private-state.json').read_text())
    assert state.get('cleaned'), 'Complete large lab cleanup before smoke containers'
    candidate=json.loads((root/'images/frontend-build.json').read_text())
    assert candidate['exitCode']==0
    env=clean_env(root)
    env['NOMOSMART_IMAGE_SMOKE_SCOPE']='CHG-291-INTEGRATED'
    source=root/'source/frontend/scripts'
    helper=(source/'chg294-image-smoke.mjs').read_text()
    wrapper=(source/'chg294-image-verify.mjs').read_text()
    # No expected runtime version/hash/native/browser assertion is changed.
    helper=helper.replace('CHG-294-R2','CHG-291-INTEGRATED').replace('CHG-294 R2 final image','CHG-291 integrated candidate')
    wrapper=wrapper.replace('CHG-294-R2','CHG-291-INTEGRATED').replace('chg294-r2-verify-','chg291-integrated-smoke-')
    wrapper=wrapper.replace('sha256:2c65c3eab7f7601612297a6c1ec11f8445ac0b2c174c18f4076cf98c2a70eb9d',candidate['imageId'])
    wrapper=wrapper.replace('nomosmart/frontend:0.1.0-chg294-r2',candidate['tag'])
    # Historical alternate candidate is not the target of this new run. Its
    # image ID remains in baseline verification below, without running it.
    wrapper=wrapper.replace('  assert.equal(inspect("image", "nomosmart/frontend:0.1.0-chg294").Id, oldImage);\n','')
    wrapper=wrapper.replace('"--network", internalNetwork ? network : "none",',
                            '"--memory", "512m", "--cpus", "1", "--network", internalNetwork ? network : "none",')
    folder=root/'images/frontend-smoke'
    folder.mkdir(mode=0o700)
    for name,body in [('chg294-image-smoke.mjs',helper),('verify.mjs',wrapper)]:
        with (folder/name).open('x') as stream:
            (folder/name).chmod(0o600); stream.write(body)
    docker=['docker','--context','desktop-linux']
    before=set(subprocess.check_output(docker+['ps','-aq','--no-trunc'],env=env).decode().split())
    images=set(subprocess.check_output(docker+['image','ls','-aq','--no-trunc'],env=env).decode().split())
    log=folder/'output.log'
    with log.open('x') as stream:
        log.chmod(0o600)
        outcome=subprocess.run([str(NODE/'node'),str(folder/'verify.mjs')],env=env,
                               stdout=stream,stderr=subprocess.STDOUT,timeout=360)
    after=set(subprocess.check_output(docker+['ps','-aq','--no-trunc'],env=env).decode().split())
    remaining_images=set(subprocess.check_output(docker+['image','ls','-aq','--no-trunc'],env=env).decode().split())
    result={'exitCode':outcome.returncode,'imageId':candidate['imageId'],
            'sourceSha256':manifest['sourceSha256'],
            'helperSha256':hashlib.sha256(helper.encode()).hexdigest(),
            'wrapperSha256':hashlib.sha256(wrapper.encode()).hexdigest(),
            'logSha256':hashlib.sha256(log.read_bytes()).hexdigest(),
            'containerIdSetUnchanged':before==after,'existingImagesPreserved':images<=remaining_images}
    put(folder/'result.json',result)
    print(json.dumps(result))
    assert before==after and images<=remaining_images, 'Baseline drift; no broad cleanup'

    # Reuse the earlier liveness/contract assertions with current source hashes.
    # This is explicitly not DB readiness or full end-to-end acceptance.
    backend=json.loads((root/'images/backend-build.json').read_text())
    program=Path('/private/tmp/chg293-build.5fYxc2/backend-smoke.py').read_text()
    begin=program.index('expected = ')+len('expected = ')
    end=program.index('\nfor name, checksum',begin)
    old_hashes=ast.literal_eval(program[begin:end])
    new_hashes={name:manifest['files']['backend/'+name] for name in old_hashes}
    program=program[:begin]+repr(new_hashes)+program[end:]
    run=root.name+'-backend-smoke'
    args=docker+['container','create','--interactive','--pull=never','--name',run,
        '--label','nomosmart.acceptance='+run,'--network','none','--read-only',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=64m','--user','10001:10001',
        '--cap-drop=ALL','--security-opt','no-new-privileges','--memory','512m','--cpus','1',
        '-e','APP_ENV=test','-e','PYTHONDONTWRITEBYTECODE=1','-e','APP_ENCRYPTION_KEY',
        '--entrypoint','python',backend['imageId'],'-']
    smoke_env={**env,'APP_ENCRYPTION_KEY':state['app_key']}
    cid=subprocess.check_output(args,env=smoke_env,text=True).strip()
    def inspect():
        return json.loads(subprocess.check_output(docker+['inspect',cid],env=env,text=True))[0]
    try:
        config=inspect()
        assert config['Image']==backend['imageId']
        assert config['Config']['Labels']['nomosmart.acceptance']==run
        assert config['HostConfig']['NetworkMode']=='none' and config['HostConfig']['ReadonlyRootfs']
        assert not config['Mounts'] and not config['HostConfig']['PortBindings']
        output=subprocess.run(docker+['container','start','--attach','--interactive',cid],
            input=program,env=env,capture_output=True,text=True,timeout=90)
        evidence={'exitCode':output.returncode,'imageId':backend['imageId'],
                  'programSha256':hashlib.sha256(program.encode()).hexdigest(),
                  'stderrSha256':hashlib.sha256(output.stderr.encode()).hexdigest(),
                  'result':json.loads(output.stdout) if output.returncode==0 else None}
        put(root/'images/backend-smoke.json',evidence)
        print(json.dumps(evidence))
    finally:
        assert inspect()['Config']['Labels']['nomosmart.acceptance']==run
        subprocess.run(docker+['rm','-f',cid],env=env,check=True,capture_output=True)
    assert before==set(subprocess.check_output(docker+['ps','-aq','--no-trunc'],env=env).decode().split())


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    main(parser.parse_args().root)
