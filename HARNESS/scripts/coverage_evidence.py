#!/usr/bin/env python3
"""Record and verify source-bound full-suite coverage evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUITES: dict[str, dict[str, Any]] = {
    "frontend": {
        "paths": (
            "frontend/src",
            "frontend/tests",
            "frontend/package.json",
            "frontend/package-lock.json",
            "frontend/vitest.config.ts",
            "frontend/eslint.config.mjs",
        ),
        "tests": ("frontend/tests",),
        "report": "frontend/coverage/coverage-summary.json",
        "command": "npm run test:coverage",
    },
    "backend": {
        "paths": (
            "backend/app",
            "backend/tests",
            "backend/pyproject.toml",
            "backend/uv.lock",
        ),
        "tests": ("backend/tests",),
        "report": "backend/coverage.json",
        "command": "python -m pytest --continue-on-collection-errors",
        "group_command": "python scripts/run_test_groups.py",
    },
}


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_git(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        fail(result.stderr.decode("utf-8", errors="replace").strip() or "git command failed")
    return result.stdout


def commit_identity(root: Path) -> str:
    return run_git(root, "rev-parse", "HEAD").decode().strip()


def dirty_fingerprint(root: Path, paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(run_git(root, "diff", "--binary", "HEAD", "--", *paths))
    untracked = run_git(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *paths,
    ).decode().splitlines()
    for relative in sorted(untracked):
        path = root / relative
        if not path.is_file():
            continue
        digest.update(b"\0untracked\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_manifest(root: Path, test_roots: tuple[str, ...]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for relative_root in test_roots:
        base = root / relative_root
        if not base.is_dir():
            fail(f"Missing full-suite test directory: {relative_root}")
        for path in sorted(candidate for candidate in base.rglob("*") if candidate.is_file()):
            relative = path.relative_to(root).as_posix()
            if path.suffix not in {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
                continue
            entries.append({"path": relative, "sha256": sha256_file(path)})
    if not entries:
        fail("Full-suite manifest is empty.")
    return entries


def parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(f"Coverage evidence has an invalid {field}: {value}")
    if parsed.tzinfo is None:
        fail(f"Coverage evidence {field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def evidence_path(root: Path, suite: str) -> Path:
    return root / "test-results" / "coverage-evidence" / f"{suite}.json"


def current_state(root: Path, suite: str) -> dict[str, Any]:
    contract = SUITES[suite]
    return {
        "commit": commit_identity(root),
        "dirty_diff_sha256": dirty_fingerprint(root, contract["paths"]),
        "suite_manifest": test_manifest(root, contract["tests"]),
    }


def validate_execution_command(root: Path, suite: str, command: str) -> dict[str, str] | None:
    contract = SUITES[suite]
    if command == contract["command"]:
        return None
    if suite == "backend" and command == contract.get("group_command"):
        configured = os.environ.get("NOMOSMART_TEST_GROUP_PLAN")
        if not configured:
            fail("Grouped full-suite evidence requires its private execution plan.")
        plan_path = Path(configured)
        if plan_path.is_symlink() or not plan_path.is_file() or plan_path.stat().st_uid != os.getuid() or plan_path.stat().st_mode & 0o077:
            fail("Grouped execution plan must be an owned private regular file.")
        plan = json.loads(plan_path.read_bytes())
        if plan.get("root") != str(root / "backend") or plan.get("version") != 1:
            fail("Grouped execution belongs to another source checkout.")
        result = Path(plan["output"]) / "result.json"
        validate_group_result(root, result)
        return {"kind": "grouped", "path": str(result), "sha256": sha256_file(result)}
    fail(f"{suite} evidence command must be the canonical full-suite command {contract['command']!r}.")


def validate_group_result(root: Path, result: Path) -> None:
    if not result.is_absolute() or result.is_symlink() or not result.is_file() or result.stat().st_uid != os.getuid() or result.stat().st_mode & 0o077:
        fail("Grouped result must be an owned private regular file.")
    outcome = json.loads(result.read_bytes())
    actual_modules = {p.relative_to(root / "backend").as_posix() for p in (root / "backend/tests").glob("test_*.py")}
    groups = outcome.get("groups", [])
    modules = [name for g in groups for name in g.get("modules", [])]
    if not outcome.get("passed") or not outcome.get("functional_pass") or outcome.get("coverage_exit") != [0, 0]:
        fail("Grouped full suite did not pass all functional and coverage checks.")
    if set(modules) != actual_modules or len(modules) != len(actual_modules):
        fail("Grouped evidence does not cover every module exactly once.")
    for g in groups:
        counts = g.get("counts", {})
        if g.get('selection',{}).get('blocked') or g.get('selection',{}).get('unmatched_allow'):
            fail("Deselected or unknown cases cannot produce a full-suite PASS receipt.")
        if g.get("status") != "EXECUTED" or g.get("exit") != 0 or any(counts.get(k, 1) != 0 for k in ("failure", "error", "skipped")):
            fail("Blocked, failed, or skipped groups cannot produce a PASS receipt.")
    source = outcome.get("source", {})
    actual_source = {p.relative_to(root / "backend").as_posix(): sha256_file(p)
                     for base in ("app", "tests") for p in (root / "backend" / base).rglob("*.py")}
    if source != actual_source:
        fail("Grouped evidence source manifest is stale or incomplete.")
    if sha256_file(result.parent / "coverage.json") != sha256_file(root / "backend/coverage.json"):
        fail("Grouped coverage is not the actual combined report.")


def validate_current_group_result(root: Path, result: Path) -> dict:
    """Current schema is opt-in; missing historical facts never become PASS."""
    sys.path.insert(0, str(root / 'backend'))
    from scripts.current_acceptance import (AcceptanceError, NONCURRENT, canonical_case,
        classify, coverage_metrics, group_outcome, incomplete_reasons, load_policy, satisfied_current_equivalents)
    try:
        if (not result.is_absolute() or result.is_symlink() or not result.is_file()
                or result.stat().st_uid != os.getuid() or result.stat().st_mode & 0o077):
            fail('Current result must be a private owned regular file.')
        value = json.loads(result.read_text())
        if value.get('schema_version') == 4 and value.get('profile') == 'current-native-settlement':
            return validate_native_settlement_result(root, result, value)
        policy_path = Path(os.environ['NOMOSMART_CURRENT_ACCEPTANCE_POLICY'])
        policy = load_policy(root, policy_path)
        if (value.get('schema_version') != 2 or value.get('profile') != 'current-acceptance'
                or value.get('acceptance_policy') != str(policy_path)
                or value.get('acceptance_policy_sha256') != sha256_file(policy_path)
                or value.get('source') != policy['source']):
            fail('Current result does not match the approved current source/profile.')
        if (not value.get('current_acceptance_pass') or not value.get('functional_current_pass')
                or value.get('legacy_full_suite_pass') is not False or value.get('release_pass') is not False
                or value.get('coverage_exit') != [0, 0] or incomplete_reasons(policy)
                or value.get('missing_current_definitions') or value.get('duplicate_runtime_cases')):
            fail('Current cases, current safety intents, package prerequisites or coverage are incomplete.')
        actual_modules = {p.relative_to(root / 'backend').as_posix() for p in (root / 'backend/tests').glob('test_*.py')}
        modules, selected = set(), set()
        groups = value.get('groups', [])
        if not groups or len({row['name'] for row in groups}) != len(groups):
            fail('Current groups must be complete and uniquely named.')
        for row in groups:
            modules.update(row['modules'])
            if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', row['name']):
                fail('Invalid current group directory.')
            directory = result.parent / row['name']
            declared = {case: item for case, item in policy['cases'].items()
                        if case.split('::')[0].removeprefix('backend/') in row['modules']}
            if row.get('status') == 'NOT_EXECUTED_NONCURRENT_ONLY':
                if not declared or any(item['disposition'] not in NONCURRENT for item in declared.values()) or row.get('count_as_pass') is not False:
                    fail('Current required cases cannot be excluded as a whole module.')
                continue
            if row.get('status') != 'EXECUTED':
                fail('A required current group has not executed.')
            selection_path = directory / 'selection.json'
            if sha256_file(selection_path) != row.get('selection_sha256'):
                fail('Current real collection record changed.')
            selection = json.loads(selection_path.read_text())
            if selection != row.get('selection') or selection.get('blocked') or selection.get('unmatched_allow'):
                fail('Current collection is missing or has blocked cases.')
            for node in selection['selected']:
                if classify(policy, node) != 'REQUIRED_CURRENT' or node in selected:
                    fail('Unknown, noncurrent or repeated runtime case in a current PASS result.')
                selected.add(node)
            for item in selection['noncurrent']:
                if classify(policy, item['nodeid']) not in NONCURRENT or item.get('count_as_pass') is not False:
                    fail('Invalid noncurrent accounting.')
            for item in selection.get('current_equivalents', []):
                original = canonical_case(item['nodeid'])
                approved = policy.get('current_equivalents', {}).get(original)
                if (not approved or item.get('replacement') != approved['replacement']
                        or item.get('count_as_original_pass') is not False):
                    fail('Unverified current requirement replacement.')
            actual = group_outcome(row['raw_exit'], directory / 'junit.xml', directory / 'coverage.json', directory / 'private.log')
            from scripts.current_qualified_reuse import exact_junit_selection
            exact_junit_selection((directory/'junit.xml').read_bytes(), selection['selected'], require_pass=True)
            if actual != row.get('outcome') or not actual['functional_pass']:
                fail('Current result differs from its real JUnit, log or counter.')
        expected = {case for case, item in policy['cases'].items() if item['disposition'] == 'REQUIRED_CURRENT'}
        selected_definitions = {canonical_case(case) for case in selected}
        equivalents = satisfied_current_equivalents(policy, selected_definitions)
        if (modules != actual_modules or selected_definitions | set(equivalents) != expected
                or value.get('current_equivalents_satisfied') != equivalents):
            fail('Current result does not cover every required source definition.')
        from scripts.current_acceptance import current_runtime_evidence, current_runtime_gate_passes
        runtime_evidence = current_runtime_evidence(root, policy, selected)
        if (not current_runtime_gate_passes(runtime_evidence)
                or runtime_evidence != value.get('runtime_evidence')):
            fail('Current runtime parameters or current intent evidence are incomplete or changed.')
        authority = policy.get('execution_authority')
        if authority is not None:
            from scripts.current_acceptance import approved_continuation414
            if authority != approved_continuation414(root):
                fail('Exact414 authority changed; no current coverage acceptance.')
        metrics = coverage_metrics(result.parent / 'coverage.json')
        if not metrics['each80_pass'] or metrics != value.get('coverage'):
            fail('Current full application coverage does not satisfy both original80% gates.')
        report = json.loads((result.parent / 'coverage.json').read_text())
        expected_files = {name for name in policy['source'] if name.startswith('backend/app/') and name.endswith('.py') and name != 'backend/app/db/models.py'}
        observed = set()
        for name in report['files']:
            path = Path(name)
            if path.is_absolute():
                name = path.relative_to(root).as_posix()
            elif name.startswith('app/'):
                name = 'backend/' + name
            observed.add(name)
        if observed != expected_files:
            fail('Current coverage omitted or added application source files.')
        if sha256_file(result.parent / 'coverage.json') != sha256_file(root / 'backend/coverage.json'):
            fail('Canonical current report is not the actual combined report.')
        return value
    except (AcceptanceError, OSError, ValueError, KeyError) as error:
        fail('Current acceptance validation refused: ' + type(error).__name__)


def validate_native_settlement_result(root, result, value):
    """Independently requalify every witness; result/catalog PASS flags are inert."""
    import tempfile
    from scripts.current_qualified_reuse import bound_file
    from scripts.current_test_groups import native_settlement_state
    from scripts.current_acceptance import require
    plan = json.loads(bound_file(value['plan_reference']))
    require(Path(plan['output']) == result.parent, 'native_settlement_actual_output_binding')
    require(plan['acceptance_policy'] == os.environ['NOMOSMART_CURRENT_ACCEPTANCE_POLICY'], 'native_settlement_canonical_policy')
    with tempfile.TemporaryDirectory(prefix='canonical-settlement-', dir=result.parent) as directory:
        actual = native_settlement_state(root, plan, Path(directory))
    recorded = dict(value); recorded.pop('plan_reference', None)
    require(actual == recorded, 'native_settlement_result_changed_or_not_recomputed')
    require(actual['current_acceptance_pass'] is True and actual['coverage_gate_pass'] is True
            and actual['functional_current_pass'] is True and not actual['blockers'],
            'native_settlement_still_incomplete')
    report = result.parent/'coverage.json'
    native_report = json.loads(report.read_bytes())
    normalized_files = {Path(name).relative_to(root).as_posix() if Path(name).is_absolute() else 'backend/'+name if name.startswith('app/') else name:row for name,row in native_report['files'].items()}
    require(normalized_files == actual['coverage']['files'] and native_report['totals'] == actual['coverage']['totals'],
            'native_settlement_report_not_original_counter_combination')
    require(sha256_file(report) == sha256_file(root/'backend/coverage.json'), 'native_settlement_canonical_report_changed')
    return value


def record_current_backend(root: Path, command: str, started_at_value: str) -> None:
    if command != SUITES['backend']['group_command']:
        fail('Current acceptance requires its canonical explicit grouped command.')
    configured = os.environ.get('NOMOSMART_TEST_GROUP_PLAN')
    if not configured:
        fail('Current acceptance group plan is required.')
    plan_path = Path(configured)
    if plan_path.is_symlink() or not plan_path.is_file() or plan_path.stat().st_mode & 0o077 or plan_path.stat().st_uid != os.getuid():
        fail('Current acceptance group plan must be private and owned.')
    plan = json.loads(plan_path.read_text())
    if ((plan.get('version'),plan.get('profile')) not in {(2,'current-acceptance'),(4,'current-native-settlement')} or plan.get('root') != str(root / 'backend')):
        fail('Current acceptance plan version/root mismatch.')
    result = Path(plan['output']) / 'result.json'
    validate_current_group_result(root, result)
    started = parse_time(started_at_value, 'started_at')
    ended = datetime.now(timezone.utc)
    report = root / SUITES['backend']['report']
    timestamp = datetime.fromtimestamp(report.stat().st_mtime, timezone.utc)
    if not started <= timestamp <= ended:
        fail('Current report was not generated within its execution window.')
    state = current_state(root, 'backend')
    value = {'schema_version': 2, 'suite': 'backend', 'profile': 'current-acceptance', 'command': command,
             'source': {key: state[key] for key in ('commit', 'dirty_diff_sha256')},
             'suite_manifest': state['suite_manifest'], 'started_at': started.isoformat(), 'ended_at': ended.isoformat(),
             'execution': {'path': str(result), 'sha256': sha256_file(result)},
             'report': {'path': SUITES['backend']['report'], 'sha256': sha256_file(report)},
             'legacy_full_suite_pass': False, 'release_pass': False}
    target = evidence_path(root, 'backend').with_name('backend-current.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2) + '\n')
    print('ok: recorded current acceptance separately; historical/full release status unchanged')


def verify_current_backend(root: Path) -> None:
    target = evidence_path(root, 'backend').with_name('backend-current.json')
    if not target.is_file():
        fail('Missing current backend complete evidence; required current cases are not yet qualified.')
    value = json.loads(target.read_text())
    if value.get('schema_version') != 2 or value.get('profile') != 'current-acceptance' or value.get('command') != SUITES['backend']['group_command']:
        fail('Current backend evidence identity is invalid.')
    execution = value.get('execution', {})
    result = Path(execution.get('path', ''))
    if sha256_file(result) != execution.get('sha256'):
        fail('Current execution result changed after recording.')
    validate_current_group_result(root, result)
    state = current_state(root, 'backend')
    if value.get('source') != {key: state[key] for key in ('commit', 'dirty_diff_sha256')} or value.get('suite_manifest') != state['suite_manifest']:
        fail('Current complete evidence source changed.')
    report = root / SUITES['backend']['report']
    if value.get('report') != {'path': SUITES['backend']['report'], 'sha256': sha256_file(report)}:
        fail('Current complete report changed.')
    print('ok: complete current backend evidence verified; legacy/release not granted')


def record(root: Path, suite: str, command: str, started_at_value: str) -> None:
    if suite == 'backend' and os.environ.get('NOMOSMART_CURRENT_ACCEPTANCE_POLICY'):
        record_current_backend(root, command, started_at_value)
        return
    contract = SUITES[suite]
    execution = validate_execution_command(root, suite, command)
    started_at = parse_time(started_at_value, "started_at")
    ended_at = datetime.now(timezone.utc)
    if ended_at < started_at:
        fail("Coverage evidence end time precedes its start time.")

    report = root / contract["report"]
    if not report.is_file():
        fail(f"Missing {suite} coverage report: {contract['report']}")
    report_time = datetime.fromtimestamp(report.stat().st_mtime, timezone.utc)
    if report_time < started_at:
        fail(f"{suite} coverage report predates the full-suite run.")
    if report_time > ended_at.replace(microsecond=999999):
        fail(f"{suite} coverage report timestamp is after the evidence end time.")

    state = current_state(root, suite)
    payload = {
        "schema_version": 1,
        "suite": suite,
        "source": {
            "commit": state["commit"],
            "dirty_diff_sha256": state["dirty_diff_sha256"],
        },
        "command": command,
        "execution": execution,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "ended_at": ended_at.isoformat().replace("+00:00", "Z"),
        "suite_manifest": state["suite_manifest"],
        "report": {
            "path": contract["report"],
            "sha256": sha256_file(report),
        },
    }
    output = evidence_path(root, suite)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(f"ok: recorded source-bound {suite} coverage evidence at {output.relative_to(root)}")


def verify(root: Path, suite: str) -> None:
    if suite == 'backend' and os.environ.get('NOMOSMART_CURRENT_ACCEPTANCE_POLICY'):
        verify_current_backend(root)
        return
    contract = SUITES[suite]
    path = evidence_path(root, suite)
    if not path.is_file():
        fail(f"Missing {suite} coverage evidence. Run the complete {suite} suite first.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        fail(f"Invalid {suite} coverage evidence: {exc}")
    if payload.get("schema_version") != 1 or payload.get("suite") != suite:
        fail(f"{suite} coverage evidence has an unsupported schema or suite identity.")
    if suite == "backend" and payload.get("command") == contract.get("group_command"):
        execution = payload.get("execution") or {}
        if execution.get("kind") != "grouped" or not execution.get("path"):
            fail("Grouped evidence is missing its actual execution result.")
        result = Path(execution["path"])
        validate_group_result(root, result)
        if sha256_file(result) != execution.get("sha256"):
            fail("Grouped execution result changed after recording.")
    elif payload.get("command") != contract["command"]:
        fail(f"{suite} coverage evidence was not produced by the canonical full-suite command.")

    started_at = parse_time(str(payload.get("started_at", "")), "started_at")
    ended_at = parse_time(str(payload.get("ended_at", "")), "ended_at")
    if ended_at < started_at:
        fail(f"{suite} coverage evidence has inverted timestamps.")

    state = current_state(root, suite)
    source = payload.get("source") or {}
    if source.get("commit") != state["commit"]:
        fail(f"{suite} coverage evidence belongs to a stale commit.")
    if source.get("dirty_diff_sha256") != state["dirty_diff_sha256"]:
        fail(
            f"{suite} coverage evidence does not match the current tracked/untracked "
            "source and test diff."
        )
    if payload.get("suite_manifest") != state["suite_manifest"]:
        fail(f"{suite} coverage evidence suite manifest is stale or incomplete.")

    report_meta = payload.get("report") or {}
    if report_meta.get("path") != contract["report"]:
        fail(f"{suite} coverage evidence references an unexpected report path.")
    report = root / contract["report"]
    if not report.is_file():
        fail(f"Missing {suite} coverage report: {contract['report']}")
    if report_meta.get("sha256") != sha256_file(report):
        fail(f"{suite} coverage report hash does not match its evidence record.")
    report_time = datetime.fromtimestamp(report.stat().st_mtime, timezone.utc)
    if report_time < started_at or report_time > ended_at.replace(microsecond=999999):
        fail(f"{suite} coverage report timestamp is outside the recorded full-suite run.")
    print(f"ok: {suite} coverage evidence matches commit, diff, suite manifest and report hash")


def verify_measurement(root: Path) -> None:
    from release_quality import main as quality_main
    raise SystemExit(quality_main(["coverage", "--root", str(root)]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("record", "verify", "measurement"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--suite", choices=tuple(SUITES))
    parser.add_argument("--command")
    parser.add_argument("--started-at")
    arguments = parser.parse_args()
    root = Path(arguments.root).resolve()
    if arguments.action == "measurement":
        verify_measurement(root)
    if not arguments.suite:
        fail("record/verify requires --suite.")
    if arguments.action == "record":
        if not arguments.command or not arguments.started_at:
            fail("record requires --command and --started-at.")
        record(root, arguments.suite, arguments.command, arguments.started_at)
    else:
        verify(root, arguments.suite)


if __name__ == "__main__":
    main()
