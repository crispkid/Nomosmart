"""Real retained reports/catalogs and pure refusal policies; no external doubles."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
import chg301_r2_high_risk as high

RUN = Path(os.environ["CHG301_R2_HIGH_EVIDENCE"]).resolve(strict=True)
RECORD = json.loads((RUN / "manifest.json").read_bytes())
EVIDENCE = json.loads(high.NODE_EVIDENCE.read_bytes())


def historical_approval_section():
    sections = (ROOT / "DEVELOPMENT_PLAN.md").read_text().split("\n## ")
    actual = next(s for s in sections[1:] if s.splitlines()[0] == high.SECTION)
    return "# Historical approval evidence\n\n## " + actual


def test_actual_approved_plan_and_original_source_binding():
    high.approval_guard(high.PLAN.read_bytes(), historical_approval_section())
    assert RECORD["plan_sha256"] == high.PLAN_SHA
    assert high.file_sha(high.NODE_EVIDENCE) == RECORD["input_evidence_sha256"]
    assert RECORD["pr_before"]["headRefOid"] == high.GIT_BASE[0]
    assert RECORD["main_before"] == high.GIT_BASE[1]


def test_retired_high_runner_rejects_current_delivery_approval():
    with pytest.raises(ValueError):
        high.approval_guard(high.PLAN.read_bytes(), (ROOT / "DEVELOPMENT_PLAN.md").read_text())


@pytest.mark.parametrize("case", ["hash", "historical", "pending", "phrase"])
def test_current_scope_approval_cannot_be_reused_or_forged(case):
    plan = high.PLAN.read_bytes()
    active = historical_approval_section()
    if case == "hash":
        plan += b" "
    elif case == "historical":
        active = "# Unapproved\n\n## A different plan\n\n" + active
    elif case == "pending":
        active = active.replace("Gate 4 approval: APPROVED.", "Gate 4 approval: PENDING.", 1)
    else:
        active = active.replace(high.APPROVAL, "missing", 1)
    with pytest.raises(ValueError):
        high.approval_guard(plan, active)


def test_new_window_is_bounded_and_does_not_reset():
    start = datetime.fromisoformat(RECORD["started_at"])
    high.time_guard(RECORD, start)
    with pytest.raises(ValueError, match="exhausted"):
        high.time_guard(RECORD, start + timedelta(hours=5, minutes=50))
    with pytest.raises(ValueError, match="identity"):
        high.time_guard({**RECORD, "deadline": (start + timedelta(hours=7)).isoformat()}, start)


@pytest.mark.parametrize("args", [
    [*high.DOCKER, "run", "--privileged", "anything"],
    [*high.DOCKER, "build", "."], [*high.DOCKER, "system", "prune", "-af"],
    ["git", "-C", str(ROOT), "push", "--force"],
    ["git", "-C", str(ROOT), "reset", "--hard"],
    ["gh", "pr", "merge", "1"], ["gh", "pr", "edit", "1"],
    ["kubectl", "delete", "pod", "example"],
    ["curl", "https://example.invalid"], ["sh", "-c", "true"],
    [*high.DOCKER, "inspect", "--format", "{{json .Config.Env}}", "a" * 64],
])
def test_readonly_dispatch_cannot_start_mutation(args):
    assert not high.command_allowed(args)


def test_actual_executed_commands_are_allowlisted_and_nonmutating():
    assert RECORD["commands"]
    for command in RECORD["commands"]:
        assert high.command_allowed(command["args"])
    assert RECORD["docker_mutations"] == RECORD["provider_calls"] == RECORD["pr_writes"] == 0


def test_actual_raw_highs_and_unknowns_are_not_silently_deferred():
    rows = high.high_ledger(EVIDENCE)
    pending = [row for row in rows if row["severity"] in high.HIGH]
    assert len(pending) == 221
    assert all(row["state"] == "UNRESOLVED" for row in pending)
    assert len({row["id"] for row in pending if row["scope"] != "supplemental"}) == 83
    assert sum(row["scope"] == "node-original59" and row["prior_assessment"] == "INDETERMINATE" for row in pending) == 25
    assert all(row["state"] == "DEFERRED_BY_SCOPE" for row in rows if row["severity"] not in high.HIGH)


@pytest.mark.parametrize("family", list(high.RELEASES))
def test_actual_official_catalogs_are_bound_and_not_security_pass(family):
    path = RUN / "raw" / f"{family}-releases.json"
    entry = next(row for row in RECORD["downloads"] if row["path"] == str(path.relative_to(RUN)))
    assert high.file_sha(path) == entry["sha256"]
    result = high.compatible_releases(family, json.loads(path.read_bytes()))
    assert 1 <= len(result["selected"]) <= 3
    assert all(row["version"].startswith(high.RELEASES[family][1] + ".") for row in result["selected"])
    assert result["not_image_security_pass"] is True


@pytest.mark.parametrize("family", list(high.RELEASES))
def test_catalog_without_bound_baseline_cannot_be_clean(family):
    with pytest.raises(ValueError, match="baseline_not_in"):
        high.compatible_releases(family, [])


@pytest.mark.parametrize("status", ["UNRESOLVED", "INDETERMINATE", "PROPOSED_NOT_AFFECTED", "DEFERRED_BY_SCOPE", "ACCEPTED_WITHOUT_VALIDATION"])
def test_pure_pr_policy_rejects_unresolved_or_relabelled_high(status):
    rows = high.high_ledger(EVIDENCE)
    row = next(row for row in rows if row["severity"] in high.HIGH)
    # Policy inputs, not scanner output or a fabricated successful external test.
    with pytest.raises(ValueError, match="unresolved_high"):
        high.pr_guard([{**row, "state": status}], "PASS", "PASS", True, high.GIT_BASE[0], high.GIT_BASE[0])


def test_incomplete_evidence_cannot_pass_even_when_no_rows():
    with pytest.raises(ValueError, match="incomplete_security"):
        high.pr_guard([], "PASS", "PASS", True, high.GIT_BASE[0], high.GIT_BASE[0])


def test_actual_candidate_findings_prevent_pr_write():
    with pytest.raises(ValueError, match="unresolved_high"):
        high.pr_guard(high.high_ledger(EVIDENCE), "NOT_RUN", "NOT_RUN", True,
                      RECORD["pr_before"]["headRefOid"], high.GIT_BASE[0])


def test_actual_nested_raw_metadata_not_only_summary():
    image = EVIDENCE["additionalFindings"][0]
    path = Path(EVIDENCE["run"]["root"]) / "analysis" / (image["name"] + ".sarif.json")
    assert high.file_sha(path) == image["sarif_sha256"]
    rows = high.raw_findings(json.loads(path.read_bytes()))
    assert sum(row["severity"] in high.HIGH for row in rows.values()) == 47
    assert all(row["instances"] > 0 and row["purls"] for row in rows.values())


def test_actual_raw_cannot_change_rule_identity():
    image = EVIDENCE["additionalFindings"][0]
    path = Path(EVIDENCE["run"]["root"]) / "analysis" / (image["name"] + ".sarif.json")
    changed = json.loads(path.read_bytes())
    changed["runs"][0]["results"][0]["ruleId"] = "not-the-original-id"
    with pytest.raises(ValueError, match="raw_rule_identity"):
        high.raw_findings(changed)
