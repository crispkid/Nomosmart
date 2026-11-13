"""Signed local acceptance with full gates and protocol authentication contract 2."""
from __future__ import annotations
from datetime import datetime
import math
from pathlib import Path
import re
from typing import Any

from .contract import CONTROL_FILES, FULL_GIT_SHA, SHA256, ReleaseContractError, _bounded_file, _load_json, _normalize_fingerprint
from .contract_v3 import REQUIRED_GATES as BUILD_GATES, _reference, verify_payload as verify_common_payload
from .publication import validate_application_images

SCHEMA_VERSION = 4
PACKAGE_TYPE = 'nomosmart-local-verified-release'
PURPOSE = 'local-verified-release'
REQUIRED_GATES = BUILD_GATES | frozenset({
    'frontend_full_suite', 'backend_full_suite', 'installer_full_suite', 'release_full_suite',
    'e2e', 'frontend_coverage', 'backend_coverage', 'compose', 'local_helm',
    'application_static_security', 'upgrade_restore',
})
DEFERRED_GATES = frozenset({'production_multi_host_capacity', 'production_fault_domains_and_ha', 'production_network_isolation_qualification'})
EXCLUDED_GATES = frozenset({'production_backup'})
FILE_REFERENCES = ('external_dependencies', 'external_advisory', 'migration_contract')


def _reject(message):
    raise ReleaseContractError(message)


def validate_manifest(payload: dict[str, Any]) -> None:
    _validate_manifest(payload)


def _validate_manifest(payload: dict[str, Any], *, schema_version=SCHEMA_VERSION,
        package_type=PACKAGE_TYPE, purpose=PURPOSE, required_gates=REQUIRED_GATES,
        file_references=FILE_REFERENCES) -> None:
    fields = {'schema_version','package_type','purpose','release_id','auth_contract_revision',
        'production_ready','production_platform_qualified','created_at','source','compatibility',
        'application_images','signing','gates','files','deferred_validation','excluded_validation',*file_references}
    if (not isinstance(payload,dict) or set(payload)!=fields
            or type(payload.get('schema_version')) is not int or payload['schema_version']!=schema_version
            or payload.get('package_type')!=package_type or payload.get('purpose')!=purpose
            or type(payload.get('auth_contract_revision')) is not int or payload['auth_contract_revision']!=2
            or payload.get('production_ready') is not False or payload.get('production_platform_qualified') is not False
            or not isinstance(payload.get('release_id'),str) or not re.fullmatch(r'\d+\.\d+\.\d+',payload['release_id'])):
        _reject('local verified release identity is invalid')
    try:
        created = datetime.fromisoformat(payload['created_at'].replace('Z','+00:00'))
        if created.tzinfo is None: raise ValueError()
    except (TypeError,ValueError,AttributeError):
        _reject('release creation timestamp is invalid')
    source=payload['source']
    if (not isinstance(source,dict) or set(source)!={'git_sha','tree_sha256','clean','detached'}
            or not FULL_GIT_SHA.fullmatch(str(source.get('git_sha','')))
            or not SHA256.fullmatch(str(source.get('tree_sha256','')))
            or source.get('clean') is not True or source.get('detached') is not True):
        _reject('local release source must be clean, detached and content-bound')
    signing=payload['signing']
    if not isinstance(signing,dict) or set(signing)!={'type','fingerprint'} or signing['type']!='openpgp-detached':
        _reject('local release requires OpenPGP detached signing')
    _normalize_fingerprint(str(signing['fingerprint']))
    compatibility=payload['compatibility']
    if (not isinstance(compatibility,dict) or set(compatibility)!={'application','api','chart_version','chart_sha256'}
            or compatibility['application']!=payload['release_id'] or compatibility['chart_version']!=payload['release_id']
            or compatibility['api']!='v1' or not SHA256.fullmatch(str(compatibility['chart_sha256']))):
        _reject('local release compatibility identity is invalid')
    validate_application_images(payload['application_images'],version=payload['release_id'])
    inventory={}
    if not isinstance(payload['files'],list) or not payload['files']:
        _reject('local release file inventory is empty')
    for row in payload['files']:
        if not isinstance(row,dict) or set(row)!={'path','sha256','size'} or type(row['size']) is not int or row['size']<0:
            _reject('local release inventory entry is invalid')
        path=_reference({'path':row['path'],'sha256':row['sha256']},label='local payload')
        if path in inventory or path in CONTROL_FILES:_reject('local release inventory is duplicate or reserved')
        inventory[path]=row['sha256']
    def inventoried(reference,label):
        path=_reference(reference,label=label)
        if inventory.get(path)!=reference['sha256']:_reject('local release reference is outside its inventory: '+label)
        return path
    for name in file_references:inventoried(payload[name],name)
    if payload['external_dependencies']['path']!='deploy/release/external-dependencies.protocol.lock.json':
        _reject('local release must use the protocol dependency lock')
    if payload['migration_contract']['path']!='deploy/migrations/release-contract.json':
        _reject('local migration contract location differs')
    gates=payload['gates']
    if not isinstance(gates,dict) or set(gates)!=required_gates:_reject('local required gate inventory differs')
    gate_paths=set()
    for name,row in gates.items():
        if (not isinstance(row,dict) or set(row)!={'status','source_sha','path','evidence_sha256'}
                or row['status']!='passed' or row['source_sha']!=source['git_sha']):
            _reject('local gate did not pass for this source: '+name)
        path=inventoried({'path':row['path'],'sha256':row['evidence_sha256']},name)
        if path in gate_paths:_reject('local gate evidence is not unique')
        gate_paths.add(path)
    for field,names,status in [('deferred_validation',DEFERRED_GATES,'deferred_by_user'),('excluded_validation',EXCLUDED_GATES,'excluded_by_user')]:
        values=payload[field]
        if not isinstance(values,dict) or set(values)!=names:_reject('local deferred/excluded inventory differs')
        for name,row in values.items():
            if (not isinstance(row,dict) or set(row)!={'status','reason','approval'} or row['status']!=status
                    or not isinstance(row['reason'],str) or not row['reason'].strip()):
                _reject('local deferred/excluded state is invalid: '+name)
            inventoried(row['approval'],name+' approval')


def _metric(covered,total,*,label):
    from .quality_reports import _metric as metric
    return metric(covered,total,label=label,require_target=True)


def verify_coverage(report: dict[str,Any],side: str) -> None:
    from .quality_reports import verify_coverage as validate
    validate(report,side,require_target=True)


def verify_full_suite(value: dict[str,Any], source_sha: str) -> None:
    # A missing live prerequisite commonly appears as a tool-level skip. It
    # cannot be relabelled as a successful full run by an outer wrapper.
    if (not isinstance(value,dict) or value.get('scope')!='full'
            or value.get('source_sha')!=source_sha
            or type(value.get('tests')) is not int or value['tests']<=0
            or type(value.get('passed')) is not int or value['passed']!=value['tests']
            or any(type(value.get(k)) is not int or value[k]!=0
                   for k in ('exit_code','failed','errors','blocked','skipped'))):
        _reject('full suite did not complete successfully')


def verify_payload(root: Path,payload: dict[str,Any]):
    images,platforms=verify_common_payload(root,payload,protocol_contract=True)
    inventory={row['path']:row['sha256'] for row in payload['files']}
    def report(reference,label):
        from .contract import sha256_file
        path=_reference(reference,label=label)
        actual=_bounded_file(root,path)
        if inventory.get(path)!=reference['sha256'] or sha256_file(actual)!=reference['sha256']:
            _reject('local evidence content differs: '+label)
        return _load_json(actual,label=label)
    for field in ('deferred_validation','excluded_validation'):
        for name,row in payload[field].items():
            approval=report(row['approval'],name+' approval')
            if (not isinstance(approval,dict) or not isinstance(approval.get('approver'),str) or not approval['approver'].strip()
                    or not isinstance(approval.get('quote'),str) or not approval['quote'].strip()
                    or not isinstance(approval.get('change_id'),str) or not approval['change_id'].startswith('CHG-')
                    or not isinstance(approval.get('decisions'),dict) or approval['decisions'].get(name)!=row['status']):
                _reject('local scope approval does not match the declared decision: '+name)
    for name in REQUIRED_GATES:
        row=payload['gates'][name]
        gate=report({'path':row['path'],'sha256':row['evidence_sha256']},name)
        artifacts=gate['artifacts']
        if not artifacts:_reject('local gate requires underlying evidence: '+name)
        if name in {'frontend_coverage','backend_coverage'}:
            matches=[r for r in artifacts if r['path'].endswith('coverage-summary.json' if name.startswith('frontend') else 'backend-coverage.json')]
            if len(matches)!=1:_reject('coverage tool artifact is missing or ambiguous: '+name)
            verify_coverage(report(matches[0],name+' counters'),name.split('_')[0])
        elif name.endswith('_full_suite'):
            matches=[r for r in artifacts if r['path'].endswith('full-suite-summary.json')]
            if len(matches)!=1:_reject('full suite tool summary is missing or ambiguous: '+name)
            value=report(matches[0],name+' full suite')
            verify_full_suite(value,payload['source']['git_sha'])
        elif name=='e2e':
            matches=[r for r in artifacts if r['path'].endswith('e2e-summary.json')]
            if len(matches)!=1:_reject('full E2E tool summary is missing or ambiguous')
            value=report(matches[0],'full E2E')
            if (value.get('scope')!='full' or value.get('source_sha')!=payload['source']['git_sha']
                    or not isinstance(value.get('checks'),list) or not value['checks']
                    or any(not isinstance(c,dict) or c.get('status')!='passed' for c in value['checks'])):
                _reject('full E2E did not complete successfully')
    return images,platforms
