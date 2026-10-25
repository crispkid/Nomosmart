"""Explicit v0.2.2 coverage-only exception; all functional and trust gates remain."""
from pathlib import Path
from typing import Any

from .acceptance import RELEASE_ID, verify_receipt
from .contract import ReleaseContractError, _bounded_file, _load_json
from .contract_v3 import verify_payload as verify_common_payload
from .contract_v4 import REQUIRED_GATES, _validate_manifest, qualification

SCHEMA_VERSION = 5
PACKAGE_TYPE = 'nomosmart-local-coverage-exception-release'
PURPOSE = 'local-coverage-exception-release'
COVERAGE_GATES = frozenset({'frontend_coverage', 'backend_coverage'})


def validate_manifest(payload: dict[str, Any]) -> None:
    _validate_manifest(payload, coverage_exception=True)
    if payload['release_id'] != RELEASE_ID:
        raise ReleaseContractError('coverage exception is authorized only for 0.2.2')


def verify_acceptance(root: Path, payload: dict[str, Any]) -> dict:
    assessment = verify_receipt(root, payload['coverage_acceptance'], release_id=payload['release_id'], source_sha=payload['source']['git_sha'])
    if not assessment['release_prerequisites_satisfied']:
        raise ReleaseContractError('coverage acceptance cannot waive functional failures or unresolved bugs')
    if not assessment['coverage_exception_accepted']:
        raise ReleaseContractError('use the strict release format when coverage meets its targets')
    return assessment


def verify_payload(root: Path, payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    validate_manifest(payload)
    verify_acceptance(root, payload)  # Fail before signing or installation.
    receipt = _load_json(_bounded_file(root, payload['coverage_acceptance']['path']), label='coverage acceptance')
    inventory = {row['path']: row['sha256'] for row in payload['files']}
    required = [payload['coverage_acceptance'], *receipt['inputs'].values()]
    for reference in required:
        if inventory.get(reference['path']) != reference['sha256']:
            raise ReleaseContractError('acceptance receipt/input is outside checksum inventory')
    for name in REQUIRED_GATES:
        report = _load_json(_bounded_file(root, payload['gates'][name]['path']), label=name)
        if not report.get('artifacts'):
            raise ReleaseContractError(f'mandatory gate requires underlying evidence: {name}')
        if name in COVERAGE_GATES and (report.get('coverage_acceptance') != payload['coverage_acceptance'] or any(ref not in report['artifacts'] for ref in required)):
            raise ReleaseContractError('coverage gate must bind its receipt and actual underlying inputs')
    return verify_common_payload(root, payload, _coverage_exception=True)
