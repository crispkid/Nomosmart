"""Actual owned files and receipt rejection; no business-success substitution."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/scripts'))
from run_test_groups import private_json
from backend_regression_profile import profile


def test_private_environment_rejects_public_file_and_symlink(tmp_path):
    path=tmp_path/'input.json';path.write_text('{"purpose":"native-file-control"}');path.chmod(0o600)
    assert private_json(path)['purpose']=='native-file-control'
    path.chmod(0o644)
    with pytest.raises(AssertionError):private_json(path)
    path.chmod(0o600);link=tmp_path/'link.json';link.symlink_to(path)
    with pytest.raises(AssertionError):private_json(link)


def test_reviewed_assignment_keeps_every_current_module_once():
    actual={str(p.relative_to(ROOT/'backend')) for p in (ROOT/'backend/tests').glob('test_*.py')}
    rows=profile(ROOT)
    assert {row['module'] for row in rows}==actual and len(rows)==len(actual)
    for row in rows:
        assert row['reason']
        if row['cohort']=='blocked':assert row['runtime_cases']=='unknown_not_collected'


def test_deselected_receipt_cannot_be_misrepresented_as_full_pass(tmp_path):
    spec=importlib.util.spec_from_file_location('coverage_receipt_control',ROOT/'HARNESS/scripts/coverage_evidence.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    actual=[str(p.relative_to(ROOT/'backend')) for p in (ROOT/'backend/tests').glob('test_*.py')]
    # Corrupted input to the receipt validator. This never produces a business
    # or coverage PASS receipt; its observable requirement is actual rejection.
    receipt=dict(passed=True,functional_pass=True,coverage_exit=[0,0],groups=[dict(modules=actual,status='EXECUTED',exit=0,
        counts=dict(failure=0,error=0,skipped=0),selection=dict(blocked=[dict(nodeid='native-control',reason='POLICY_BLOCKED')]))])
    path=tmp_path/'result.json';path.write_text(json.dumps(receipt));path.chmod(0o600)
    with pytest.raises(SystemExit) as rejection:module.validate_group_result(ROOT,path)
    assert rejection.value.code==1
