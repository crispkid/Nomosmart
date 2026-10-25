"""Source-bound, coverage-only human exceptions. Runtime failures remain failures.

The eventual trusted release signature authenticates the operator's approval
attestation. A standalone receipt is not an independently signed human identity.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contract import FULL_GIT_SHA, SHA256, ReleaseContractError, _bounded_file, _load_json, sha256_file
from .contract_v3 import _reference

KIND = 'nomosmart-source-bound-coverage-acceptance'
SCHEMA_VERSION = 1
RELEASE_ID = '0.2.2'
FRONTEND_METRICS = ('lines', 'statements', 'functions', 'branches')
BACKEND_METRICS = ('lines', 'branches')
REQUIRED_CHECKS = frozenset({'frontend_minimum', 'backend_minimum', 'rag_required', 'report_stream'})
INPUT_NAMES = frozenset({'source_manifest', 'frontend_map', 'frontend_summary', 'backend_report', 'human_authorization', 'case_ledger', 'bug_ledger', 'original_results'})


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseContractError(message)


def _input(root: Path, references: dict, name: str) -> Any:
    reference = references[name]
    relative = _reference(reference, label=name)
    _require(relative.startswith('evidence/artifacts/'), 'acceptance input must be an inventoried evidence artifact')
    path = _bounded_file(root, relative)
    _require(sha256_file(path) == reference['sha256'], f'acceptance input hash differs: {name}')
    return _load_json(path, label=name)


def _count(value: Any) -> int:
    _require(type(value) is int and value >= 0, 'coverage counts must be nonnegative integers')
    return value


def _metric(covered: int, total: int) -> dict[str, Any]:
    _require(type(total) is int and total > 0 and 0 <= covered <= total, 'coverage denominator is empty or invalid')
    return {'covered': covered, 'total': total, 'percent': covered / total * 100}


def _frontend_name(path: str) -> str:
    _require(isinstance(path, str), 'coverage source path must be text')
    marker = '/frontend/src/'
    name = 'frontend/src/' + path.split(marker, 1)[1] if marker in path else path
    _require(name.startswith('frontend/src/') and '..' not in Path(name).parts, 'frontend coverage source path is outside application')
    return name


def _backend_name(path: str) -> str:
    _require(isinstance(path, str), 'coverage source path must be text')
    marker = '/backend/app/'
    name = 'backend/app/' + path.split(marker, 1)[1] if marker in path else path
    _require(name.startswith('backend/app/') and '..' not in Path(name).parts, 'backend coverage source path is outside application')
    return name


def _sources(root: Path, manifest: dict) -> tuple[dict, set[str], set[str]]:
    _require(isinstance(manifest, dict) and set(manifest) == {'files', 'frontend_omit', 'backend_omit'}, 'application source manifest fields differ')
    files = manifest['files']
    _require(isinstance(files, dict) and files, 'application source inventory is empty')
    _require(manifest['backend_omit'] == ['backend/app/db/models.py'], 'original backend omission rule changed')
    for name, digest in files.items():
        _require(isinstance(name, str) and name.startswith(('frontend/src/', 'backend/app/')), 'source inventory is outside application')
        _require(isinstance(digest, str) and bool(SHA256.fullmatch(digest)), 'source hash is invalid')
        _require(sha256_file(_bounded_file(root, name)) == digest, f'application source drift: {name}')
    actual = {
        str(path.relative_to(root))
        for top in ('frontend/src', 'backend/app')
        for path in (root / top).rglob('*')
        if path.is_file() and '__pycache__' not in path.parts and path.name != '.DS_Store'
    }
    _require(actual == set(files), 'complete application source inventory differs')
    frontend_omit = sorted(name for name in files if name.startswith('frontend/src/app/api/') and Path(name).suffix in ('.ts', '.tsx'))
    _require(manifest['frontend_omit'] == frontend_omit and len(frontend_omit) == 8, 'original frontend API route omission rule changed')
    frontend = {name for name in files if name.startswith('frontend/src/') and Path(name).suffix in ('.ts', '.tsx')} - set(frontend_omit)
    backend = {name for name in files if name.startswith('backend/app/') and name.endswith('.py')} - set(manifest['backend_omit'])
    _require(len(frontend) == 141 and len(backend) == 150, 'this release exception requires the original complete141/150 file denominators')
    return files, frontend, backend


def _frontend(data: dict, summary: dict, expected: set[str]) -> dict:
    _require(isinstance(data, dict) and data, 'frontend counter map is empty')
    names = [_frontend_name(name) for name in data]
    _require(set(names) == expected and len(names) == len(expected), 'frontend counter inventory is incomplete or duplicated')
    covered = dict.fromkeys(FRONTEND_METRICS, 0)
    total = dict.fromkeys(FRONTEND_METRICS, 0)
    for name, row in data.items():
        _require(_frontend_name(row['path']) == _frontend_name(name), 'frontend counter path differs')
        _require(set(row['s']) == set(row['statementMap']) and set(row['f']) == set(row['fnMap']) and set(row['b']) == set(row['branchMap']), 'frontend counter locations differ')
        line_hits: dict[int, int] = {}
        for identity, hits in row['s'].items():
            hits = _count(hits)
            line = row['statementMap'][identity]['start']['line']
            _require(type(line) is int and line > 0, 'statement source location is invalid')
            line_hits[line] = max(line_hits.get(line, 0), hits)
        for metric, values in [('lines', list(line_hits.values())), ('statements', list(row['s'].values())), ('functions', list(row['f'].values())), ('branches', [hit for hits in row['b'].values() for hit in hits])]:
            for value in values:
                _count(value)
            total[metric] += len(values)
            covered[metric] += sum(value > 0 for value in values)
    result = {name: _metric(covered[name], total[name]) for name in FRONTEND_METRICS}
    _require(isinstance(summary, dict) and 'total' in summary, 'frontend actual summary is absent')
    for metric, row in result.items():
        actual = summary['total'].get(metric, {})
        _require((actual.get('covered'), actual.get('total')) == (row['covered'], row['total']), 'frontend summary differs from its actual counters')
    return result


def _backend(data: dict, expected: set[str]) -> dict:
    _require(isinstance(data, dict) and isinstance(data.get('files'), dict), 'backend tool report is absent')
    names = [_backend_name(name) for name in data['files']]
    _require(set(names) == expected and len(names) == len(expected), 'backend counter inventory is incomplete or duplicated')
    sums = dict(covered_lines=0, num_statements=0, covered_branches=0, num_branches=0)
    for row in data['files'].values():
        s = row['summary']
        executed, missing = set(row['executed_lines']), set(row['missing_lines'])
        _require(not executed & missing, 'backend line counters overlap')
        _require(len(executed) == s['covered_lines'] and len(executed | missing) == s['num_statements'], 'backend line summary differs')
        executed_b, missing_b = {tuple(arc) for arc in row['executed_branches']}, {tuple(arc) for arc in row['missing_branches']}
        _require(not executed_b & missing_b, 'backend branch counters overlap')
        _require(len(executed_b) == s['covered_branches'] and len(executed_b | missing_b) == s['num_branches'], 'backend branch summary differs')
        for key in sums:
            sums[key] += _count(s[key])
    _require(all(data['totals'].get(key) == value for key, value in sums.items()), 'backend total summary differs from actual per-file counters')
    return {'lines': _metric(sums['covered_lines'], sums['num_statements']), 'branches': _metric(sums['covered_branches'], sums['num_branches'])}


def assess(root: Path, *, release_id: str, source_sha: str, inputs: dict) -> dict:
    """Evaluate actual files. It never runs models or turns runtime failures green."""
    _require(release_id == RELEASE_ID and bool(FULL_GIT_SHA.fullmatch(source_sha)), 'exception release/source identity is invalid')
    _require(isinstance(inputs, dict) and set(inputs) == INPUT_NAMES, 'acceptance input inventory differs')
    records = {name: _input(root, inputs, name) for name in INPUT_NAMES}
    files, fe_names, be_names = _sources(root, records['source_manifest'])
    approval = records['human_authorization']
    _require(isinstance(approval, dict) and approval.get('release_id') == release_id and approval.get('scope') == 'coverage-only', 'human approval has the wrong release/scope')
    _require(approval.get('approved') is True and all(isinstance(approval.get(key), str) and approval[key].strip() for key in ('by', 'statement', 'question_item_id', 'plan_sha256')), 'explicit human approval evidence is missing')
    _require(bool(SHA256.fullmatch(approval['plan_sha256'])), 'human approval plan hash is invalid')
    _require(approval.get('frontend_metrics') == list(FRONTEND_METRICS) and approval.get('backend_metrics') == list(BACKEND_METRICS) and approval.get('original_threshold') == 80, 'coverage waiver scope differs')
    manifest_hash = __import__('hashlib').sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    _require(approval.get('application_source_sha256') == manifest_hash, 'human approval is not bound to this application source')
    approval_refs = approval.get('approval_evidence')
    _require(isinstance(approval_refs, list) and len(approval_refs) == 2, 'approval and approved plan artifacts are required')
    proof_files = []
    for reference in approval_refs:
        relative = _reference(reference, label='human approval evidence')
        _require(relative.startswith('evidence/artifacts/'), 'human approval evidence path differs')
        path = _bounded_file(root, relative)
        _require(sha256_file(path) == reference['sha256'], 'human approval evidence hash differs')
        proof_files.append(path)
    approved = _load_json(proof_files[0], label='human approval evidence')
    gate = approved.get('gate4', {})
    _require(approved.get('plan_sha256') == approval['plan_sha256'] == sha256_file(proof_files[1]), 'human approved plan hash differs')
    _require(gate.get('status') == 'APPROVED' and gate.get('by') == approval['by'] and gate.get('question_item_id') == approval['question_item_id'] and gate.get('message'), 'human approval receipt is inconsistent')
    measurements = {'frontend': _frontend(records['frontend_map'], records['frontend_summary'], fe_names), 'backend': _backend(records['backend_report'], be_names)}
    cases = records['case_ledger']
    _require(isinstance(cases, dict) and cases.get('application_source_sha256') == manifest_hash, 'functional cases have no matching application source binding')
    checks = cases.get('checks')
    _require(isinstance(checks, list) and all(isinstance(row, dict) and isinstance(row.get('id'), str) for row in checks), 'functional case ledger is invalid')
    _require(len({row['id'] for row in checks}) == len(checks) and REQUIRED_CHECKS <= {row['id'] for row in checks}, 'required functional check inventory is incomplete or duplicated')
    for row in checks:
        _require(row.get('status') in {'passed', 'failed', 'blocked'} and isinstance(row.get('evidence'), list) and row['evidence'], 'functional check has no result/evidence')
        for reference in row['evidence']:
            relative = _reference(reference, label='functional evidence')
            _require(relative.startswith('evidence/artifacts/') and sha256_file(_bounded_file(root, relative)) == reference['sha256'], 'functional evidence hash differs')
    bugs = records['bug_ledger']
    _require(isinstance(bugs, dict) and isinstance(bugs.get('bugs'), list), 'bug ledger is missing')
    _require(bugs.get('application_source_sha256') == manifest_hash, 'bug ledger source differs')
    for bug in bugs['bugs']:
        _require(isinstance(bug, dict) and all(bug.get(key) for key in ('id', 'status', 'severity', 'root_cause', 'recommendation', 'evidence')), 'bug analysis is incomplete')
        _require(bug['status'] in {'confirmed', 'suspected', 'resolved'}, 'bug status is invalid')
        for reference in bug['evidence']:
            relative = _reference(reference, label='bug evidence')
            _require(relative.startswith('evidence/artifacts/') and sha256_file(_bounded_file(root, relative)) == reference['sha256'], 'bug evidence hash differs')
    originals = records['original_results'].get('commands')
    _require(isinstance(originals, list) and originals, 'original command results must be retained')
    for row in originals:
        _require(isinstance(row, dict) and type(row.get('exit_code')) is int and isinstance(row.get('command'), list) and row['command'] and row.get('evidence'), 'original command/exit evidence is absent')
        reference = row['evidence'];relative = _reference(reference, label='original result')
        _require(relative.startswith('evidence/artifacts/') and sha256_file(_bounded_file(root, relative)) == reference['sha256'], 'original result evidence differs')
    unresolved = [bug['id'] for bug in bugs['bugs'] if bug['status'] != 'resolved']
    functional = all(row['status'] == 'passed' for row in checks) and not unresolved
    coverage_met = all(row['percent'] >= 80 for side in measurements.values() for row in side.values())
    exception_accepted = not coverage_met  # Explicit, source-bound approval validated above.
    return {'release_id': release_id, 'source_sha': source_sha, 'application_source_sha256': manifest_hash, 'measurements': measurements,
            'functional_pass': functional, 'coverage_target_met': coverage_met, 'coverage_exception_accepted': exception_accepted,
            'exception_scope': 'coverage-only', 'unresolved_bug_ids': unresolved,
            'required_functional_checks': {row['id']: row['status'] for row in checks},
            'release_prerequisites_satisfied': functional and (coverage_met or exception_accepted),
            'release_eligible': False, 'remaining_release_gates': 'All other signed package gates remain mandatory; no package was assembled by this qualifier.'}


def create_receipt(root: Path, *, release_id: str, source_sha: str, inputs: dict) -> dict:
    result = assess(root, release_id=release_id, source_sha=source_sha, inputs=inputs)
    return {'schema_version': SCHEMA_VERSION, 'kind': KIND, 'release_id': release_id, 'source_sha': source_sha, 'inputs': inputs, 'assessment': result}


def verify_receipt(root: Path, reference: dict, *, release_id: str, source_sha: str) -> dict:
    relative = _reference(reference, label='coverage acceptance')
    path = _bounded_file(root, relative)
    _require(sha256_file(path) == reference['sha256'], 'coverage acceptance receipt hash differs')
    receipt = _load_json(path, label='coverage acceptance')
    _require(isinstance(receipt, dict) and set(receipt) == {'schema_version', 'kind', 'release_id', 'source_sha', 'inputs', 'assessment'}, 'coverage acceptance fields differ')
    _require(type(receipt['schema_version']) is int and receipt['schema_version'] == SCHEMA_VERSION and receipt['kind'] == KIND, 'coverage acceptance format differs')
    _require(receipt['release_id'] == release_id and receipt['source_sha'] == source_sha, 'coverage acceptance source/release differs')
    actual = assess(root, release_id=release_id, source_sha=source_sha, inputs=receipt['inputs'])
    _require(receipt['assessment'] == actual, 'coverage acceptance outcome was changed or is stale')
    return actual
