"""Real pure-policy inputs: R2's human risk decision cannot expand silently.

No external adapters, monkeypatch, application imports or provider requests.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("chg301_r2_security", ROOT / "backend/scripts/chg301_r2_security.py")
SECURITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SECURITY)
APPROVAL = (ROOT / SECURITY.RISK_PATH).read_bytes()
LEDGER = json.loads(APPROVAL)
SOURCE = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in LEDGER["source_sha256"]}


def test_exact_approved_real_source_is_accepted_but_not_clean():
    findings = copy.deepcopy(LEDGER["findings"])
    result = SECURITY.assess_static_risk(findings, SOURCE, APPROVAL)
    assert result["status"] == "ACCEPTED_RISK"
    assert result["accepted_findings"] == findings
    assert len(result["accepted_findings"]) == 3
    assert result["unaccepted_high_critical"] == []
    assert findings == LEDGER["findings"]


@pytest.mark.parametrize("field,value", [
    ("filename", "backend/app/other.py"), ("line_number", 87),
    ("test_id", "B999"), ("issue_severity", "CRITICAL"),
    ("issue_confidence", "MEDIUM"),
])
def test_other_high_critical_identity_is_not_accepted(field, value):
    row = {**LEDGER["findings"][1], field: value}
    result = SECURITY.assess_static_risk([row], SOURCE, APPROVAL)
    assert result["status"] == "FAIL"
    assert result["unaccepted_high_critical"] == [row]


@pytest.mark.parametrize("approval", [b"", b"{}", APPROVAL + b" "])
def test_absent_or_changed_approval_does_not_inherit_risk(approval):
    result = SECURITY.assess_static_risk(LEDGER["findings"], SOURCE, approval)
    assert result["status"] == "FAIL"
    assert not result["accepted_findings"]


def test_changed_source_file_invalidates_acceptance(tmp_path):
    path = next(iter(SOURCE))
    changed = tmp_path / "changed.py"
    changed.write_bytes((ROOT / path).read_bytes() + b"\n# changed candidate\n")
    digest = hashlib.sha256(changed.read_bytes()).hexdigest()
    result = SECURITY.assess_static_risk(LEDGER["findings"], {path: digest}, APPROVAL)
    assert result["status"] == "FAIL"
    assert result["approval_id"] is None


def test_missing_source_cannot_pass():
    assert SECURITY.assess_static_risk(LEDGER["findings"], {}, APPROVAL)["status"] == "FAIL"


def test_accepted_and_new_issue_still_blocks():
    row = {**LEDGER["findings"][0], "filename": "new.py"}
    result = SECURITY.assess_static_risk([*LEDGER["findings"], row], SOURCE, APPROVAL)
    assert result["status"] == "FAIL"
    assert len(result["accepted_findings"]) == 3
    assert result["unaccepted_high_critical"] == [row]


def test_no_findings_is_clean_not_risk_acceptance():
    result = SECURITY.assess_static_risk([], SOURCE, APPROVAL)
    assert result["status"] == "PASS"
    assert not result["accepted_findings"]
