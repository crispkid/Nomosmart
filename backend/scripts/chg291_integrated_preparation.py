"""Approved integrated-release preparation; no live-data or deployment entrypoint.

Create a private source-bound copy, then run explicit checks in that copy.
Existing credentials, environment files and generated artifacts are excluded.
Outputs are evidence, never a fabricated release approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

REPO = Path(__file__).resolve().parents[2]
NODE = Path('/tmp/chg294-r2.5S694K/node-v24.21.0-darwin-arm64/bin')
PYTHON = REPO / 'backend/.venv/bin/python'
EXCLUDED = {'.git', 'node_modules', '.next', '.venv', 'venv', '__pycache__',
            '.pytest_cache', 'coverage', 'test-results', 'output', '.codex', '.agents'}
SQL_SHA = 'b8d256be49ff99c2c157ec8f95bf96f5ac2846aae450637f895747bb298f9f96'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path, value):
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def allowed(name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or any(p in EXCLUDED for p in path.parts):
        return False
    if path.name.startswith('.env') and not path.name.endswith(('.example', '.template')):
        return False
    if path.name.endswith(('.env', '.key', '.pem', '.p12', '.pfx', '.pyc', '.log')):
        return False
    return True


def clean_env(root):
    env = {key: os.environ[key] for key in ('HOME', 'TMPDIR', 'LANG', 'TERM') if key in os.environ}
    env.update(PATH=f'{NODE}:{PYTHON.parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
               PYTHONDONTWRITEBYTECODE='1', NEXT_TELEMETRY_DISABLED='1', CI='1',
               E2E_PYTHON=str(PYTHON), NOMOSMART_HARNESS_ROOT_DIR=str(root / 'source'))
    return env


def snapshot():
    root = Path(tempfile.mkdtemp(prefix='chg291-release-', dir='/private/tmp'))
    root.chmod(0o700)
    source = root / 'source'
    source.mkdir(mode=0o700)
    names = set(subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=REPO
    ).decode().split('\0')) - {''}
    names.update(str(p.relative_to(REPO)) for p in (REPO / 'HARNESS').rglob('*') if p.is_file())
    names.update(('SPECIFICATION.md', 'SPEC_CHANGELOG.md', 'DEVELOPMENT_PLAN.md',
                  'TEST_PLAN.md', 'TRACEABILITY.md', 'API_COMPATIBILITY.md', 'AGENTS.md'))
    hashes = {}
    for name in sorted(names):
        if not allowed(name):
            continue
        path = REPO / name
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(REPO):
            raise RuntimeError(f'Unsafe source type: {name}')
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha(path)
        shutil.copy2(path, target)
        if sha(path) != before or sha(target) != before:
            raise RuntimeError(f'Source changed during snapshot: {name}')
        hashes[name] = before
    assert hashes['sql/migrations/V049__exclusive_project_member_role.sql'] == SQL_SHA
    assert not (source / 'backend/.env').exists()
    assert not (source / 'frontend/.env.local').exists()
    manifest = {'scope': 'CHG-291 integrated preparation A-C; no deployment or Provider',
                'createdAt': time.time(), 'root': str(root), 'files': hashes,
                'gitHead': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO).decode().strip(),
                'sourceSha256': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}
    put(root / 'source-manifest.json', manifest)
    (root / 'results').mkdir(mode=0o700)
    print(json.dumps({'root': str(root), 'files': len(hashes), 'sourceSha256': manifest['sourceSha256']}))


def guard(root):
    root = root.resolve(strict=True)
    assert re.fullmatch(r'/private/tmp/chg291-release-[a-z0-9_]+', str(root))
    assert root.stat().st_mode & 0o077 == 0
    manifest = json.loads((root / 'source-manifest.json').read_text())
    assert manifest['root'] == str(root)
    for name, expected in manifest['files'].items():
        path = root / 'source' / name
        assert not path.is_symlink() and sha(path) == expected, f'Snapshot drift: {name}'
    assert not any((root / 'source' / p).exists() for p in ('backend/.env', 'frontend/.env', 'frontend/.env.local'))
    return manifest


def check(root, name):
    manifest = guard(root)
    source = root / 'source'
    commands = {
        'install': ([str(NODE / 'npm'), 'ci', '--no-audit', '--no-fund'], source / 'frontend', 1200),
        'frontend': (['bash', str(source / 'HARNESS/harness.sh'), 'test:frontend'], source, 1200),
        'components': ([str(NODE / 'npm'), 'exec', '--', 'vitest', 'run', '--coverage'], source / 'frontend', 600),
        'lint': (['bash', str(source / 'HARNESS/harness.sh'), 'frontend:lint'], source, 300),
        'build-frontend': (['bash', str(source / 'HARNESS/harness.sh'), 'frontend:build'], source, 1200),
        'syntax': (['bash', str(source / 'HARNESS/harness.sh'), 'backend:syntax'], source, 300),
        'helm-lint': (['bash', str(source / 'HARNESS/harness.sh'), 'helm:lint'], source, 180),
        'config-policy': (['bash', str(source / 'HARNESS/harness.sh'), 'deploy:config-policy'], source, 180),
        'compose': (['docker', 'compose', 'config', '--no-env-resolution', '--quiet'], source, 180),
        'static-security': (['uvx', '--offline', 'bandit', '-r', 'backend/app',
                             'deploy/installer/nomosmart_installer', 'deploy/release/nomosmart_release',
                             '-lll', '-iii'], source, 300),
    }
    command, cwd, timeout = commands[name.removesuffix('-retry')]
    result_path = root / 'results' / (name + '.json')
    log = root / 'results' / (name + '.log')
    assert not result_path.exists() and not log.exists(), 'Do not overwrite prior evidence'
    env = clean_env(root)
    version = subprocess.check_output([str(NODE / 'node'), '--version'], env=env).decode().strip()
    assert version == 'v24.21.0', 'Reviewed Node version required'
    started = time.time()
    with log.open('x') as stream:
        log.chmod(0o600)
        try:
            outcome = subprocess.run(command, cwd=cwd, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=timeout)
            code = outcome.returncode
        except subprocess.TimeoutExpired:
            code = 124
    guard(root)
    result = {'check': name, 'command': command, 'exitCode': code,
              'elapsedSeconds': round(time.time() - started, 2), 'sourceSha256': manifest['sourceSha256'],
              'log': str(log), 'logSha256': sha(log), 'node': version}
    put(result_path, result)
    print(json.dumps(result))


def images(root):
    manifest = guard(root)
    env = clean_env(root)
    docker = ['docker', '--context', 'desktop-linux']
    artifacts = root / 'images'
    artifacts.mkdir(mode=0o700)
    tags = {key: f'nomosmart/{key}:0.1.0-chg299-v049' for key in ('backend', 'frontend', 'migrations')}
    for tag in tags.values():
        probe = subprocess.run([*docker, 'image', 'inspect', tag], env=env, capture_output=True)
        assert probe.returncode != 0 and b'No such image' in probe.stderr, 'Do not overwrite image or ignore daemon failure'
    before = subprocess.check_output([*docker, 'image', 'ls', '-q', '--no-trunc'], env=env).decode().split()
    put(artifacts / 'baseline.json', {'images': sorted(set(before)), 'sourceSha256': manifest['sourceSha256']})
    for name, tag in tags.items():
        guard(root)
        source = root / 'source'
        context = source if name == 'migrations' else source / name
        dockerfile = source / 'deploy/migrations/Dockerfile' if name == 'migrations' else context / 'Dockerfile'
        assert dockerfile.is_file() and (context / '.dockerignore').is_file()
        log = artifacts / f'{name}-build.log'
        iidfile = artifacts / f'{name}.iid'
        command = [*docker, 'build', '--platform', 'linux/arm64', '--progress=plain',
                   '--iidfile', str(iidfile), '-f', str(dockerfile), '-t', tag, str(context)]
        started = time.time()
        print(json.dumps({'phase': 'build', 'image': name, 'tag': tag}), flush=True)
        with log.open('x') as stream:
            log.chmod(0o600)
            try:
                outcome = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
                code = outcome.returncode
            except subprocess.TimeoutExpired:
                code = 124
        result = {'command': command, 'exitCode': code, 'elapsedSeconds': round(time.time()-started, 2),
                  'logSha256': sha(log), 'sourceSha256': manifest['sourceSha256'], 'tag': tag}
        if code == 0:
            iid = iidfile.read_text().strip()
            info = json.loads(subprocess.check_output([*docker, 'image', 'inspect', tag], env=env))[0]
            assert re.fullmatch(r'sha256:[a-f0-9]{64}', iid) and info['Id'] == iid
            assert info['Architecture'] == 'arm64' and info['Os'] == 'linux'
            result.update(imageId=iid, architecture=info['Architecture'], user=info['Config']['User'])
        put(artifacts / f'{name}-build.json', result)
        print(json.dumps(result), flush=True)
        guard(root)
        if code != 0:
            raise SystemExit('Candidate build failed; inspect safe log before continuing')
    after = set(subprocess.check_output([*docker, 'image', 'ls', '-q', '--no-trunc'], env=env).decode().split())
    assert set(before) <= after, 'Existing image baseline changed'


def scans(root):
    guard(root)
    env = clean_env(root)
    directory = root / 'images'
    docker = ['docker', '--context', 'desktop-linux']
    for name in ('backend', 'frontend', 'migrations'):
        build = json.loads((directory / f'{name}-build.json').read_text())
        assert build['exitCode'] == 0
        image = build['imageId']
        info = json.loads(subprocess.check_output([*docker, 'image', 'inspect', build['tag']], env=env))[0]
        assert info['Id'] == image
        for label, options, extension in (
            ('high-critical', ['cves', '--exit-code', '--only-severity', 'critical,high', '--format', 'sarif'], 'sarif'),
            ('all-severity', ['cves', '--format', 'sarif'], 'sarif'),
            ('sbom', ['sbom', '--format', 'spdx'], 'json'),
        ):
            output = directory / f'{name}-{label}.{extension}'
            log = directory / f'{name}-{label}.log'
            assert not output.exists()
            command = [*docker, 'scout', *options, '--output', str(output), 'local://' + image]
            with log.open('x') as stream:
                log.chmod(0o600)
                outcome = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
            result = {'imageId': image, 'command': command, 'exitCode': outcome.returncode, 'logSha256': sha(log)}
            if output.exists():
                result['artifactSha256'] = sha(output)
            put(directory / f'{name}-{label}-result.json', result)
            print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'check', 'images', 'scans'))
    parser.add_argument('--root', type=Path)
    parser.add_argument('--name')
    args = parser.parse_args()
    if args.action == 'snapshot':
        snapshot()
    elif args.action == 'check':
        assert args.root and args.name
        check(args.root, args.name)
    else:
        assert args.root
        (images if args.action == 'images' else scans)(args.root)
