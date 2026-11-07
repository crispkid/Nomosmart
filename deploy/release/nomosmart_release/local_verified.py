"""Assemble v4 only from existing complete evidence and an authorized signing key."""
from __future__ import annotations
from pathlib import Path
import re
import shutil
import tempfile

from .contract import _bounded_file, _load_json, sha256_file, verify_release_package
from .contract_v4 import (DEFERRED_GATES, EXCLUDED_GATES, PACKAGE_TYPE, PURPOSE,
    REQUIRED_GATES, SCHEMA_VERSION, validate_manifest, verify_payload)
from .publication import validate_application_images
from .validation import collect_evidence
from .public_sources import PublicSourceInventory, SourceBoundaryError


def copy_protocol_runtime(repo: Path, destination: Path) -> PublicSourceInventory:
    """The reviewed file list is versioned; directory discovery grants nothing."""
    from .cli import ReleaseBuildError, _git
    list_path = _bounded_file(repo, 'deploy/release/runtime-files.protocol.json')
    approved = _load_json(list_path, label='protocol runtime file list')
    if (not isinstance(approved, dict) or set(approved) != {'version', 'auth_contract_revision', 'files'}
            or approved['version'] != 1 or approved['auth_contract_revision'] != 2
            or not isinstance(approved['files'], list)):
        raise ReleaseBuildError('protocol runtime file list is invalid')
    tracked = set(_git(repo, 'ls-files', '-z').split('\0'))
    if any(not isinstance(name, str) or name not in tracked for name in approved['files']):
        raise ReleaseBuildError('protocol runtime file is not part of the committed source')
    try:
        inventory = PublicSourceInventory.freeze(repo, approved['files'])
        inventory.copy_to(destination)
    except SourceBoundaryError as error:
        raise ReleaseBuildError(str(error)) from None
    return inventory


def assemble_local_verified_release(*, repo: Path, commit: str, release_id: str,
    image_inventory: Path, evidence_dir: Path, output_dir: Path,
    signing_fingerprint: str, public_key: Path, gpg_binary='gpg', gpg_home: Path | None=None):
    return _assemble_local_release(repo=repo,commit=commit,release_id=release_id,
        image_inventory=image_inventory,evidence_dir=evidence_dir,output_dir=output_dir,
        signing_fingerprint=signing_fingerprint,public_key=public_key,gpg_binary=gpg_binary,gpg_home=gpg_home)


def _assemble_local_release(*, repo: Path, commit: str, release_id: str, image_inventory: Path,
    evidence_dir: Path, output_dir: Path, signing_fingerprint: str, public_key: Path,
    gpg_binary='gpg',gpg_home: Path | None=None,reviewed=False):
    from . import contract_v4 as contract
    if reviewed:
        from . import contract_v5 as contract
    required_gates=contract.REQUIRED_GATES
    quality_references=getattr(contract,'QUALITY_REFERENCES',())
    from .cli import (PROHIBITED_CONTENT, ReleaseBuildError, _chart_digest, _chart_version,
        _deterministic_archive, _git, _payload_inventory, _safe_copy,
        _sign_attestation, _write_json, source_hygiene, source_identity)
    if not re.fullmatch(r'\d+\.\d+\.\d+',release_id):
        raise ReleaseBuildError('local release ID must be a semantic version')
    repo=repo.resolve();source=source_identity(repo,commit);source_hygiene(repo)
    images=validate_application_images(_load_json(image_inventory,label='application images'),version=release_id)
    if evidence_dir.is_symlink() or not evidence_dir.is_dir():
        raise ReleaseBuildError('local release evidence must be a regular directory')
    evidence_dir=evidence_dir.resolve()
    gates,paths=collect_evidence(evidence_dir,commit,required_gates=required_gates)
    # A genuine prior human scope receipt, never generated passed gates.
    approval_path=_bounded_file(evidence_dir,'platform-scope-approval.json')
    approval=_load_json(approval_path,label='local platform scope approval')
    decisions={**{name:'deferred_by_user' for name in DEFERRED_GATES},**{name:'excluded_by_user' for name in EXCLUDED_GATES}}
    if approval.get('decisions')!=decisions:
        raise ReleaseBuildError('local platform scope approval differs from required decisions')
    paths.add('platform-scope-approval.json')
    quality_refs={}
    if reviewed:
        # References are supplied explicitly; no promotion of existing unverified candidates.
        index=_load_json(_bounded_file(evidence_dir,'quality-index.json'),label='reviewed quality index')
        if not isinstance(index,dict) or set(index)!=set(quality_references):
            raise ReleaseBuildError('reviewed release quality references are missing')
        from .quality_reports import read_reference
        from .contract_v3 import _reference
        def origin(ref):
            path=_reference(ref,label='reviewed quality input')
            if path == 'deploy/release/quality-policy.json':return _bounded_file(repo,path)
            if not path.startswith('evidence/artifacts/'):
                raise ReleaseBuildError('reviewed quality evidence must use package-relative evidence/artifacts references')
            return _bounded_file(evidence_dir,path.removeprefix('evidence/'))
        visited=set()
        def close(ref):
            path=_reference(ref,label='quality input')
            if path in visited:return
            if len(visited)>=10000:raise ReleaseBuildError('quality reference closure is too large')
            visited.add(path);actual=origin(ref)
            if sha256_file(actual)!=ref['sha256']:raise ReleaseBuildError('quality input digest differs')
            if path.startswith('evidence/'):paths.add(path.removeprefix('evidence/'))
            if not path.endswith('.json'):return
            pending=[_load_json(actual,label='quality input')]
            while pending:
                value=pending.pop()
                if isinstance(value,dict):
                    if set(value)=={'path','sha256'}:close(value)
                    else:pending.extend(value.values())
                elif isinstance(value,list):pending.extend(value)
        for key,reference in index.items():
            close(reference)
            quality_refs[key]=reference
        if index['quality_policy']['path']!='deploy/release/quality-policy.json':
            raise ReleaseBuildError('reviewed policy must use its committed location')
    output=output_dir.resolve()
    if output==repo or repo in output.parents:raise ReleaseBuildError('release output must be outside source')
    output.mkdir(parents=True,exist_ok=True)
    final=output/f'nomosmart-{release_id}';archive=output/f'nomosmart-{release_id}.tar.gz'
    if any(p.exists() or p.is_symlink() for p in (final,archive,archive.with_suffix(archive.suffix+'.next'))):
        raise ReleaseBuildError('local release output already exists')
    with tempfile.TemporaryDirectory(prefix='nomosmart-local-verified-',dir=output) as temporary:
        staging=Path(temporary)/final.name
        runtime_inventory=copy_protocol_runtime(repo,staging)
        for relative in sorted(paths):
            origin=_bounded_file(evidence_dir,relative)
            if any(pattern.search(origin.read_bytes()) for pattern in PROHIBITED_CONTENT):
                raise ReleaseBuildError('local release evidence contains credential material')
            _safe_copy(origin,staging/'evidence'/relative)
        chart=staging/'deploy/helm/nomosmart'
        approval_ref={'path':'evidence/platform-scope-approval.json','sha256':sha256_file(staging/'evidence/platform-scope-approval.json')}
        manifest={'schema_version':contract.SCHEMA_VERSION,'package_type':contract.PACKAGE_TYPE,'purpose':contract.PURPOSE,
            'release_id':release_id,'auth_contract_revision':2,'production_ready':False,'production_platform_qualified':False,
            'created_at':_git(repo,'show','-s','--format=%cI',commit),'source':source,
            'signing':{'type':'openpgp-detached','fingerprint':signing_fingerprint.upper()},
            'compatibility':{'application':release_id,'api':'v1','chart_version':_chart_version(chart),'chart_sha256':_chart_digest(chart)},
            'application_images':images,'gates':gates,
            'deferred_validation':{name:{'status':'deferred_by_user','reason':'User accepted local platform acceptance only.','approval':dict(approval_ref)} for name in sorted(DEFERRED_GATES)},
            'excluded_validation':{name:{'status':'excluded_by_user','reason':'Production backup is outside this local platform release scope. Isolated restore qualification is still required.','approval':dict(approval_ref)} for name in sorted(EXCLUDED_GATES)},
            'files':_payload_inventory(staging),**quality_refs}
        for name,relative in {'external_dependencies':'deploy/release/external-dependencies.protocol.lock.json',
                'external_advisory':'evidence/external-advisory.json','migration_contract':'deploy/migrations/release-contract.json'}.items():
            manifest[name]={'path':relative,'sha256':sha256_file(staging/relative)}
        contract.validate_manifest(manifest)
        # Verify actual counters and every reference before any key operation.
        contract.verify_payload(staging,manifest)
        _write_json(staging/'release-manifest.json',manifest)
        sums=[f"{r['sha256']}  {r['path']}" for r in manifest['files']]
        sums.append(f"{sha256_file(staging/'release-manifest.json')}  release-manifest.json")
        (staging/'SHA256SUMS').write_text('\n'.join(sorted(sums))+'\n',encoding='utf-8')
        _write_json(staging/'RELEASE-ATTESTATION.json',{'manifest_sha256':sha256_file(staging/'release-manifest.json'),'checksums_sha256':sha256_file(staging/'SHA256SUMS')})
        _sign_attestation(staging,signing_fingerprint=signing_fingerprint,public_key=public_key,gpg_binary=gpg_binary,gpg_home=gpg_home)
        result=verify_release_package(staging,purpose=contract.PURPOSE,trusted_fingerprint=signing_fingerprint,
            expected_chart_sha256=_chart_digest(chart),gpg_binary=gpg_binary)
        if source_identity(repo,commit)!=source:raise ReleaseBuildError('source changed during local release assembly')
        for name in runtime_inventory.files:runtime_inventory.read(name)
        source_hygiene(repo);shutil.move(str(staging),final)
    _deterministic_archive(final,archive,int(_git(repo,'show','-s','--format=%ct',commit)))
    return {**result,'status':'created','package_dir':str(final),'archive':str(archive),'archive_sha256':sha256_file(archive)}
