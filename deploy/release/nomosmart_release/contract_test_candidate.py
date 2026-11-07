"""Integrity-only protocol test material. Never a qualified or signed release."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import stat
import zlib

from .contract import FULL_GIT_SHA, SHA256, ReleaseContractError
from .contract_v4 import REQUIRED_GATES, DEFERRED_GATES, EXCLUDED_GATES
from .public_sources import PublicSourceInventory, SourceBoundaryError, _read, relative_path

IDENTITY = {
    'schema_version': 5, 'package_type': 'nomosmart-protocol-test-candidate',
    'purpose': 'protocol-installation-test', 'auth_contract_revision': 2,
    'test_only': True, 'verification_state': 'unverified', 'release_qualified': False,
    'production_ready': False, 'production_platform_qualified': False,
    'authenticity': 'not_verified',
}
PENDING = REQUIRED_GATES | DEFERRED_GATES | EXCLUDED_GATES | frozenset({
    'current_acceptance', 'license_obligations', 'trusted_signing',
})
PENDING_STATES = frozenset({'not_qualified', 'failed', 'blocked', 'not_run',
                           'deferred_by_user', 'excluded_by_user'})
CONTROLS = frozenset({'release-manifest.json', 'SHA256SUMS'})


def reject(code):
    raise ReleaseContractError('test_candidate_' + code)


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            reject('duplicate_json_key')
        result[key] = value
    return result


def decode(body: bytes):
    try:
        return json.loads(body, object_pairs_hook=_pairs,
                          parse_constant=lambda _: reject('nonfinite_json'))
    except (ValueError, UnicodeError, TypeError):
        reject('invalid_json')


def read(root: Path, name: str) -> bytes:
    try:
        body, _ = _read(root, relative_path(name))
        return body
    except SourceBoundaryError:
        reject('unsafe_or_missing_file')


def source(value):
    if (not isinstance(value, dict) or set(value) != {'git_sha', 'tree_sha256', 'clean', 'detached'}
            or not FULL_GIT_SHA.fullmatch(str(value['git_sha']))
            or not SHA256.fullmatch(str(value['tree_sha256']))
            or value['clean'] is not True or value['detached'] is not True):
        reject('source_identity')


def _reference(value, inventory):
    if (not isinstance(value, dict) or set(value) != {'path', 'sha256'}
            or value.get('path') not in inventory
            or inventory[value['path']]['sha256'] != value['sha256']):
        reject('reference_outside_inventory')
    return value['path']


def _validate_migration_contract(root, manifest):
    migration = decode(read(root, manifest['migration_contract']['path']))
    if (not isinstance(migration, dict) or migration.get('release_version') != manifest['release_id']
            or migration.get('required_version') not in {'054', '055', '056'}
            or set(migration.get('targets', {})) != ({'SQL', 'SQL_BASELINE'} if migration.get('required_version') == '054' else {'SQL'})):
        reject('migration_auth_contract')
    for kind, row in migration['targets'].items():
        prefix = 'V' if kind == 'SQL' else 'B'
        if (not isinstance(row, dict) or type(row.get('checksum')) is not int
                or not -(2**31) <= row['checksum'] < 2**31
                or not isinstance(row.get('file'), str)
                or not re.fullmatch(prefix + re.escape(migration['required_version']) + r'__[a-z0-9_]+\.sql', row['file'])):
            reject('migration_payload')
        body = read(root, 'sql/migrations/' + row['file'])
        crc = zlib.crc32(''.join(body.decode('utf-8-sig').splitlines()).encode('utf-8'))
        checksum = crc if crc < 2**31 else crc - 2**32
        if hashlib.sha256(body).hexdigest() != row.get('sha256') or checksum != row['checksum']:
            reject('migration_payload')
    return migration


def validate_manifest(manifest):
    fields = set(IDENTITY) | {'candidate_id', 'release_id', 'created_at', 'source',
        'image_build_source', 'compatibility', 'images', 'pending_requirements',
        'observations', 'files', 'runtime_files', 'migration_contract'}
    if (not isinstance(manifest, dict) or set(manifest) != fields
            or any(type(manifest.get(k)) is not type(v) or manifest[k] != v
                   for k, v in IDENTITY.items())
            or not re.fullmatch(r'\d+\.\d+\.\d+', str(manifest['release_id']))
            or not re.fullmatch(re.escape(str(manifest['release_id'])) + r'-test-[a-z0-9-]{1,80}',
                                str(manifest['candidate_id']))):
        reject('identity')
    try:
        if datetime.fromisoformat(manifest['created_at'].replace('Z', '+00:00')).tzinfo is None:
            reject('timestamp')
    except (ValueError, AttributeError, TypeError):
        reject('timestamp')
    source(manifest['source'])
    if not isinstance(manifest['image_build_source'], dict) or set(manifest['image_build_source']) != {'frontend', 'backend'}:
        reject('component_build_source_inventory')
    for component_source in manifest['image_build_source'].values():
        source(component_source)
    compatibility = manifest['compatibility']
    if (not isinstance(compatibility, dict)
            or set(compatibility) != {'api', 'chart_version', 'chart_sha256'}
            or compatibility['api'] != 'v1'
            or compatibility['chart_version'] != manifest['release_id']
            or not SHA256.fullmatch(str(compatibility['chart_sha256']))):
        reject('compatibility')
    pending = manifest['pending_requirements']
    if not isinstance(pending, dict) or set(pending) != PENDING:
        reject('pending_inventory')
    for name, row in pending.items():
        if (not isinstance(row, dict) or set(row) != {'status', 'reason'}
                or row['status'] not in PENDING_STATES
                or not isinstance(row['reason'], str) or not row['reason'].strip()):
            reject('pending_state')
        if row['status'] == 'deferred_by_user' and name not in DEFERRED_GATES:
            reject('unauthorized_deferral')
        if row['status'] == 'excluded_by_user' and name not in EXCLUDED_GATES:
            reject('unauthorized_exclusion')
    inventory = {}
    if not isinstance(manifest['files'], list) or not manifest['files']:
        reject('empty_inventory')
    for row in manifest['files']:
        if (not isinstance(row, dict) or set(row) != {'path', 'sha256', 'size', 'executable'}
                or not SHA256.fullmatch(str(row['sha256'])) or type(row['size']) is not int
                or not 0 <= row['size'] <= 64 * 1024 * 1024 or type(row['executable']) is not bool):
            reject('file_record')
        try:
            relative_path(row['path'])
        except SourceBoundaryError:
            reject('file_path')
        if row['path'] in inventory or row['path'] in CONTROLS:
            reject('duplicate_or_control_file')
        inventory[row['path']] = row
    if _reference(manifest['runtime_files'], inventory) != 'deploy/release/runtime-files.protocol.json':
        reject('runtime_list_location')
    if _reference(manifest['migration_contract'], inventory) != 'deploy/migrations/release-contract.json':
        reject('migration_location')
    images = manifest['images']
    if not isinstance(images, list) or len(images) != 4:
        reject('image_inventory')
    found = set()
    for row in images:
        fields = {'component', 'platform', 'reference', 'index_digest', 'manifest_digest',
            'config_digest', 'archive_sha256', 'multi_archive_sha256', 'source_context_sha256',
            'index', 'manifest', 'config', 'build_inputs', 'blob_verification'}
        if not isinstance(row, dict) or set(row) != fields:
            reject('image_record')
        pair = (row['component'], row['platform'])
        if pair in found or pair[0] not in {'frontend', 'backend'} or pair[1] not in {'linux/amd64', 'linux/arm64'}:
            reject('image_platform')
        found.add(pair)
        if (not isinstance(row['reference'], str)
                or not re.fullmatch(r'[^@\s]+@sha256:[0-9a-f]{64}', row['reference'])
                or not row['reference'].endswith('@' + row['manifest_digest'])):
            reject('image_reference')
        for key in ('index_digest', 'manifest_digest', 'config_digest'):
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', str(row[key])):
                reject('image_digest')
        for key in ('archive_sha256', 'multi_archive_sha256', 'source_context_sha256'):
            if not SHA256.fullmatch(str(row[key])):
                reject('image_archive_or_context')
        for key in ('index', 'manifest', 'config', 'build_inputs', 'blob_verification'):
            _reference(row[key], inventory)
    observations = manifest['observations']
    if not isinstance(observations, list) or not observations:
        reject('observations_missing')
    ids = set()
    for row in observations:
        if (not isinstance(row, dict) or set(row) != {'id', 'source', 'command', 'actual_exit', 'raw'}
                or not re.fullmatch(r'[a-z0-9-]{1,100}', str(row['id'])) or row['id'] in ids
                or type(row['actual_exit']) is not int or not 0 <= row['actual_exit'] <= 255
                or not isinstance(row['command'], list) or not row['command']
                or any(not isinstance(arg, str) for arg in row['command'])
                or not isinstance(row['raw'], list) or not row['raw']):
            reject('observation_record')
        ids.add(row['id'])
        source(row['source'])
        for ref in row['raw']:
            _reference(ref, inventory)
    return inventory


def verify_test_candidate(root: Path):
    """Local directory only; archive extraction is never implicit."""
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or root.resolve() != root or root.stat().st_mode & 0o7022):
        reject('root')
    manifest = decode(read(root, 'release-manifest.json'))
    inventory = validate_manifest(manifest)
    actual = set()
    for path in root.rglob('*'):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)) or mode & 0o7022:
            reject('unsafe_payload_mode_or_type')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(inventory) | CONTROLS:
        reject('unlisted_or_missing_payload')
    try:
        frozen = PublicSourceInventory.freeze(root, list(inventory))
    except SourceBoundaryError:
        reject('payload_boundary')
    if frozen.files != {name: {k: row[k] for k in ('sha256', 'size', 'executable')}
                        for name, row in inventory.items()}:
        reject('payload_content_or_mode')
    expected = [f"{row['sha256']}  {name}" for name, row in inventory.items()]
    expected.append(f"{hashlib.sha256(read(root, 'release-manifest.json')).hexdigest()}  release-manifest.json")
    if read(root, 'SHA256SUMS') != ('\n'.join(sorted(expected)) + '\n').encode():
        reject('checksums')
    runtime = decode(read(root, manifest['runtime_files']['path']))
    if (set(runtime) != {'version', 'auth_contract_revision', 'files'} or runtime['version'] != 1
            or runtime['auth_contract_revision'] != 2 or not isinstance(runtime['files'], list)
            or len(runtime['files']) != len(set(runtime['files']))
            or any(name not in inventory for name in runtime['files'])
            or any(name not in runtime['files'] and not name.startswith('test-evidence/') for name in inventory)):
        reject('runtime_payload_inventory')
    from .cli import _chart_digest, _chart_version, PROHIBITED_CONTENT
    chart = root / 'deploy/helm/nomosmart'
    if (_chart_digest(chart) != manifest['compatibility']['chart_sha256']
            or _chart_version(chart) != manifest['release_id']):
        reject('chart_drift')
    for name in inventory:
        if any(pattern.search(read(root, name)) for pattern in PROHIBITED_CONTENT):
            reject('credential_material')
    _validate_migration_contract(root, manifest)
    from .dependencies import validate_protocol_dependencies
    dependencies = validate_protocol_dependencies(
        decode(read(root, 'deploy/release/external-dependencies.protocol.lock.json')),
        version=manifest['release_id'])
    for observation in manifest['observations']:
        # Original native execution receipts retain their real nonzero exits.
        for ref in observation['raw']:
            receipt = decode(read(root, ref['path']))
            if (not isinstance(receipt, dict) or set(receipt) != {'args', 'exit', 'stdout_sha256', 'stderr_sha256'}
                    or receipt['exit'] != observation['actual_exit']
                    or observation['command'] != ['docker', *receipt['args']]
                    or any(not SHA256.fullmatch(str(receipt[key])) for key in ('stdout_sha256', 'stderr_sha256'))):
                reject('observation_native_exit_or_command')
    for row in manifest['images']:
        def value(key):
            return decode(read(root, row[key]['path']))
        for key in ('index', 'manifest', 'config'):
            if hashlib.sha256(read(root, row[key]['path'])).hexdigest() != row[key + '_digest'].split(':')[1]:
                reject('oci_bytes_digest')
        index, image, config = value('index'), value('manifest'), value('config')
        descriptors = index.get('manifests', [])
        os_name, arch = row['platform'].split('/')
        if (sum(d.get('digest') == row['manifest_digest'] and d.get('platform', {}).get('architecture') == arch
                and d.get('platform', {}).get('os') == os_name for d in descriptors) != 1
                or image.get('config', {}).get('digest') != row['config_digest']
                or config.get('architecture') != arch or config.get('os') != os_name):
            reject('oci_graph')
        labels = config.get('config', {}).get('Labels', {})
        image_source = manifest['image_build_source'][row['component']]
        if (labels.get('org.opencontainers.image.revision') != image_source['git_sha']
                or labels.get('org.opencontainers.image.version') != manifest['release_id']
                or labels.get('io.nomosmart.source-digest') != 'sha256:' + row['source_context_sha256']):
            reject('image_source_labels')
        inputs, proof = value('build_inputs'), value('blob_verification')
        if (inputs.get('source') != image_source
                or not isinstance(inputs.get('files'), dict) or not inputs['files']
                or proof.get('source') != image_source
                or proof.get('archive_sha256') != row['multi_archive_sha256']
                or proof.get('index_digest') != row['index_digest']):
            reject('build_provenance')
        if (inputs.get('complete_public_git_context') is not True
                or inputs.get('no_private_or_local_test_inputs') is not True
                or hashlib.sha256(json.dumps(inputs['files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest() != row['source_context_sha256']
                or inputs.get('source_context_sha256') != row['source_context_sha256']
                or proof.get('complete_referenced_graph_verified') is not True):
            reject('build_input_context')
        descriptor = next(d for d in descriptors if d['digest'] == row['manifest_digest'])
        for d in [descriptor, image['config'], *image['layers']]:
            blob = proof.get('verified_blob_files', {}).get('blobs/sha256/' + d['digest'].split(':')[1])
            if blob != {'sha256': d['digest'].split(':')[1], 'bytes': d['size']}:
                reject('blob_proof_graph')
    return {**IDENTITY, 'status': 'integrity_verified', 'candidate_id': manifest['candidate_id'],
            'manifest_sha256': hashlib.sha256(read(root, 'release-manifest.json')).hexdigest(),
            'chart_sha256': manifest['compatibility']['chart_sha256'],
            'source': manifest['source'], 'image_build_source': manifest['image_build_source'],
            'migration_reference': dependencies['images']['migration']['reference'],
            'pending_requirements': sorted(manifest['pending_requirements']),
            'image_digests': {r['component'] + ':' + r['platform']: r['reference'] for r in manifest['images']}}
