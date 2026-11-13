"""Assemble one explicitly unqualified test package from real retained materials."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import tempfile

from .contract import canonical_json, sha256_file
from .contract_test_candidate import IDENTITY, decode, reject, source, verify_test_candidate
from .local_verified import copy_protocol_runtime
from .public_sources import PublicSourceInventory, _read, relative_path


def _local(path: str) -> Path:
    value = Path(path)
    if not value.is_absolute() or value.resolve() != value or value.is_symlink() or not value.is_file():
        reject('material_path')
    return value


def _json(path: str):
    value = _local(path)
    body, _ = _read(value.parent, relative_path(value.name))
    return decode(body)


def _write(destination: Path, relative: str, body: bytes):
    relative_path(relative)
    path = destination / relative
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open('xb') as handle:
        path.chmod(0o600)
        handle.write(body)
    return {'path': relative, 'sha256': hashlib.sha256(body).hexdigest()}


def _blob(archive, digest):
    import re
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        reject('oci_blob_name')
    name = 'blobs/sha256/' + digest.split(':')[1]
    members = [m for m in archive.getmembers() if m.name == name]
    if len(members) != 1 or not members[0].isfile() or not 0 < members[0].size <= 4 * 1024 * 1024:
        reject('oci_metadata_member')
    stream = archive.extractfile(members[0])
    if stream is None:
        reject('oci_metadata_missing')
    with stream:
        body = stream.read(4 * 1024 * 1024 + 1)
    if hashlib.sha256(body).hexdigest() != digest.split(':')[1]:
        reject('oci_metadata_hash')
    decode(body)
    return body


def _image_materials(repo, intake, staging):
    from .cli import _git
    platforms = _json(intake['platforms_file'])
    if not isinstance(platforms, list) or len(platforms) != 4:
        reject('material_platform_inventory')
    components = intake['components']
    if not isinstance(components, dict) or set(components) != {'backend', 'frontend'}:
        reject('material_components')
    result = []
    build_sources = {}
    for name in sorted(components):
        component_rows = [r for r in platforms if r['component'] == name]
        if len(component_rows) != 2:
            reject('component_platform_count')
        build_source = component_rows[0]['source']
        source(build_source)
        if any(r['source'] != build_source for r in component_rows):
            reject('component_build_source_disagreement')
        build_sources[name] = build_source
        material = components[name]
        if set(material) != {'build_inputs_file', 'multi_archive_file', 'blob_verification_file'}:
            reject('material_component_fields')
        inputs = _json(material['build_inputs_file'])
        proof = _json(material['blob_verification_file'])
        expected_fields = {'source', 'files', 'complete_public_git_context', 'source_context_sha256',
                           'git_archive_sha256', 'no_private_or_local_test_inputs'}
        if (not isinstance(inputs, dict) or set(inputs) != expected_fields
                or inputs['source'] != build_source or inputs['complete_public_git_context'] is not True
                or inputs['no_private_or_local_test_inputs'] is not True
                or proof.get('source') != build_source or proof.get('complete_referenced_graph_verified') is not True):
            reject('material_provenance')
        context_sha = hashlib.sha256(json.dumps(inputs['files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if context_sha != inputs['source_context_sha256']:
            reject('build_context_digest')
        tracked = {p[len(name) + 1:] for p in _git(repo, 'ls-files', '-z', name).split('\0') if p}
        if tracked != set(inputs['files']):
            reject('build_input_inventory_drift')
        # Every actual old build input must still match, not just a selected app subset.
        frozen = PublicSourceInventory.freeze(repo / name, list(inputs['files']))
        if {p: {'sha256': r['sha256'], 'executable': r['executable']} for p, r in frozen.files.items()} != inputs['files']:
            reject('build_input_drift')
        multi = _local(material['multi_archive_file'])
        if sha256_file(multi) != proof['archive_sha256']:
            reject('multi_archive_hash')
        prefix = 'test-evidence/images/' + name + '/'
        inputs_ref = _write(staging, prefix + 'build-inputs.json', canonical_json(inputs))
        proof_ref = _write(staging, prefix + 'blob-verification.json', canonical_json(proof))
        with tarfile.open(multi, mode='r:') as archive:
            index_body = _blob(archive, proof['index_digest'])
            index = decode(index_body)
            index_ref = _write(staging, prefix + 'index.json', index_body)
            rows = [r for r in platforms if r['component'] == name]
            if {r['platform'] for r in rows} != {'linux/amd64', 'linux/arm64'} or len(rows) != 2:
                reject('component_platforms')
            for row in sorted(rows, key=lambda r: r['platform']):
                if (row['source'] != build_source or row['source_context_sha256'] != context_sha
                        or row['multi_platform_index_digest'] != proof['index_digest']
                        or sha256_file(_local(row['archive'])) != row['archive_sha256']):
                    reject('platform_material_identity')
                descriptor = [d for d in index['manifests'] if d['digest'] == row['manifest_digest']]
                if len(descriptor) != 1:
                    reject('platform_index_membership')
                body = _blob(archive, row['manifest_digest'])
                image = decode(body)
                config_body = _blob(archive, row['config_digest'])
                arch = row['platform'].split('/')[1]
                manifest_ref = _write(staging, prefix + arch + '-manifest.json', body)
                config_ref = _write(staging, prefix + arch + '-config.json', config_body)
                # Reuse the original complete per-blob proof bound to the unchanged archive.
                for d in [descriptor[0], image['config'], *image['layers']]:
                    blob = proof['verified_blob_files'].get('blobs/sha256/' + d['digest'].split(':')[1])
                    if blob != {'sha256': d['digest'].split(':')[1], 'bytes': d['size']}:
                        reject('original_blob_proof_incomplete')
                result.append({'component': name, 'platform': row['platform'],
                    'reference': row['tag'].rsplit(':', 1)[0] + '@' + row['manifest_digest'],
                    'index_digest': proof['index_digest'], 'manifest_digest': row['manifest_digest'],
                    'config_digest': row['config_digest'], 'archive_sha256': row['archive_sha256'],
                    'multi_archive_sha256': proof['archive_sha256'], 'source_context_sha256': context_sha,
                    'index': index_ref, 'manifest': manifest_ref, 'config': config_ref,
                    'build_inputs': inputs_ref, 'blob_verification': proof_ref})
        for path in frozen.files:
            frozen.read(path)
    return build_sources, result


def assemble_test_candidate(*, repo: Path, commit: str, candidate_id: str,
                            release_id: str, materials: Path, output_dir: Path):
    from .cli import (_chart_digest, _chart_version, _deterministic_archive, _git,
                      source_hygiene, source_identity)
    if (not re.fullmatch(r'\d+\.\d+\.\d+', release_id)
            or not re.fullmatch(re.escape(release_id) + r'-test-[a-z0-9-]{1,80}', candidate_id)):
        reject('candidate_output_identity')
    repo = repo.resolve()
    identity = source_identity(repo, commit)
    source_hygiene(repo)
    materials = _local(str(materials))
    if materials.stat().st_uid != os.getuid() or materials.stat().st_mode & 0o077 or materials.parent.stat().st_mode & 0o077:
        reject('private_material_intake_required')
    intake = _json(str(materials))
    if set(intake) != {'version', 'platforms_file', 'components', 'observations', 'pending_requirements'} or intake['version'] != 1:
        reject('material_intake')
    output = output_dir.absolute()
    if (output.resolve() != output or not output.is_dir() or output.is_symlink()
            or output == repo or repo in output.parents or output.stat().st_mode & 0o077
            or output.stat().st_uid != os.getuid()):
        reject('private_output_directory_required')
    final = output / ('nomosmart-' + candidate_id)
    archive_path = output / (final.name + '.tar.gz')
    if any(p.exists() or p.is_symlink() for p in (final, archive_path, archive_path.with_suffix('.gz.next'))):
        reject('output_exists')
    with tempfile.TemporaryDirectory(prefix='test-candidate-', dir=output) as temporary:
        os.chmod(temporary, 0o700)
        staging = Path(temporary) / final.name
        runtime = copy_protocol_runtime(repo, staging)
        build_source, images = _image_materials(repo, intake, staging)
        observations = []
        for row in intake['observations']:
            if not isinstance(row, dict) or set(row) != {'id', 'source', 'command', 'actual_exit', 'raw'}:
                reject('material_observation_fields')
            refs = []
            for record in row['raw']:
                if set(record) != {'name', 'file', 'sha256'}:
                    reject('material_observation_raw')
                body, _ = _read(_local(record['file']).parent, relative_path(Path(record['file']).name))
                if hashlib.sha256(body).hexdigest() != record['sha256']:
                    reject('material_observation_hash')
                # Public, structured receipts only; never bundle opaque/private diagnostic logs.
                decode(body)
                refs.append(_write(staging, 'test-evidence/observations/' + record['name'], body))
            observations.append({**{k: row[k] for k in ('id', 'source', 'command', 'actual_exit')}, 'raw': refs})
        chart = staging / 'deploy/helm/nomosmart'
        def reference(name):
            return {'path': name, 'sha256': sha256_file(staging / name)}
        files = PublicSourceInventory.freeze(staging, [p.relative_to(staging).as_posix()
                    for p in staging.rglob('*') if p.is_file()]).files
        manifest = {**IDENTITY, 'candidate_id': candidate_id, 'release_id': release_id,
            'created_at': _git(repo, 'show', '-s', '--format=%cI', commit), 'source': identity,
            'image_build_source': build_source, 'compatibility': {'api': 'v1',
                'chart_version': _chart_version(chart), 'chart_sha256': _chart_digest(chart)},
            'images': images, 'observations': observations, 'pending_requirements': intake['pending_requirements'],
            'runtime_files': reference('deploy/release/runtime-files.protocol.json'),
            'migration_contract': reference('deploy/migrations/release-contract.json'),
            'files': [{'path': name, **details} for name, details in sorted(files.items())]}
        _write(staging, 'release-manifest.json', canonical_json(manifest))
        lines = [f"{row['sha256']}  {row['path']}" for row in manifest['files']]
        lines.append(f"{sha256_file(staging / 'release-manifest.json')}  release-manifest.json")
        _write(staging, 'SHA256SUMS', ('\n'.join(sorted(lines)) + '\n').encode())
        result = verify_test_candidate(staging)
        if source_identity(repo, commit) != identity:
            reject('source_changed_during_assembly')
        for name in runtime.files:
            runtime.read(name)
        source_hygiene(repo)
        shutil.move(str(staging), final)
    _deterministic_archive(final, archive_path, int(_git(repo, 'show', '-s', '--format=%ct', commit)))
    archive_path.chmod(0o600)
    return {**result, 'package_dir': str(final), 'archive': str(archive_path),
            'archive_sha256': sha256_file(archive_path)}
