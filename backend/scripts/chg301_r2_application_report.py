"""Compact final evidence and fail-closed application-only PR eligibility."""
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from chg301_r2_application_run import Run, ROOT
from chg301_r2_application_guard import digest, write_new


def main():
    if len(sys.argv) != 2:
        raise ValueError("exact_manifest_required")
    run = Run(sys.argv[1])
    run.guard()
    expected = {(c, s, "linux/"+a) for c, stages in
                (("backend", ("builder", "runner")), ("frontend", ("base", "deps", "builder", "prod-deps", "runner")))
                for s in stages for a in ("arm64", "amd64")}
    entries, passed, blockers = [], set(), []
    for name, item in run.data["artifacts"].items():
        entry = {"name": name, **item}
        key = (item["component"], item["stage"], item["platform"])
        eligible = item.get("cli", {}).get("status") == "PASS"
        if eligible:
            scan_path = Path(item["scan"]["path"])
            scan = json.loads(scan_path.read_bytes())
            if digest(scan_path) != item["scan"]["sha256"] or scan["image_id"] != item["id"]:
                raise ValueError("final_scan_binding")
            if any(v["severity"] in {"HIGH", "CRITICAL"} for v in scan["findings"].values()):
                blockers.append(name+":unresolved_high")
            for report in scan["reports"].values():
                if digest(Path(report["path"])) != report["sha256"]:
                    raise ValueError("final_raw_changed")
            entry["reports"] = scan["reports"]
            entry["counts"] = scan["counts"]
            if key in passed:
                raise ValueError("ambiguous_qualified_artifact")
            passed.add(key)
        entry["eligible_current_artifact"] = eligible
        entries.append(entry)
    if expected != passed:
        blockers.append("missing_platform_stage")
    audit_path = Path(run.data["source_audit"]["path"])
    if digest(audit_path) != run.data["source_audit"]["sha256"]:
        raise ValueError("audit_changed")
    audit = json.loads(audit_path.read_bytes())
    if any(digest(ROOT/p) != sha for p, sha in audit["tool_sast"]["source_sha256"].items()):
        raise ValueError("tool_changed_after_audit")
    if audit["backend_sast"]["assessment"]["status"] not in {"PASS", "ACCEPTED_RISK"} or audit["tool_sast"]["high_count"]:
        blockers.append("unaccepted_source_high")
    test_rows = []
    verification = Path(run.data["verification"])
    for name in ("regression.xml", "deployment-contract.xml"):
        path = verification/name
        report = ET.parse(path).getroot()
        row = {"path": str(path), "sha256": digest(path), "tests": len(report.findall(".//testcase")),
               "failures": len(report.findall(".//failure"))+len(report.findall(".//error")), "skipped": len(report.findall(".//skipped"))}
        test_rows.append(row)
        if not row["tests"] or row["failures"] or row["skipped"]:
            blockers.append(name+":tests_incomplete")
    frontend = json.loads((verification/"frontend/result.json").read_bytes())
    if frontend["exit_code"]:
        blockers.append("frontend_lint_contracts")
    cleanup = json.loads((run.root/"cleanup/result.json").read_bytes())
    if not cleanup["baseline_restored"] or len(cleanup["removed"]) != 12+len(entries):
        blockers.append("cleanup_incomplete")
    commands = [json.loads(Path(c["path"]).read_bytes()) for c in run.data["commands"]]
    peak = max(c["peak_rss_bytes"] for c in commands)
    if peak > 8*1024**3 or any(c.get("termination_error") for c in commands):
        blockers.append("resource_or_termination_error")
    result = {"change": "CHG-301 R2 CMPAPP-001..004", "generated_at": datetime.now(UTC).isoformat(),
        "status": "APPLICATION_CHECKPOINT_ELIGIBLE_FOR_PR" if not blockers else "BLOCKED", "blockers": blockers,
        "manifest": {"path": str(run.root/"manifest.json"), "sha256": digest(run.root/"manifest.json")},
        "plan_sha256": run.data["plan_sha256"], "started_at": run.data["started_at"], "deadline": run.data["deadline"],
        "artifacts": entries, "qualified_platform_stage_count": len(passed),
        "source_changes": {p: {"before": sha, "after": run.data["source_accepted"][p]} for p, sha in run.data["source_before"].items() if sha != run.data["source_accepted"][p]},
        "source_sha256": run.data["source_accepted"], "source_audit": audit, "tests": test_rows,
        "frontend_verification": frontend, "cleanup": {"path": str(run.root/"cleanup/result.json"),
             "sha256": digest(run.root/"cleanup/result.json"), "removed_images": len(cleanup["removed"]), "baseline_restored": cleanup["baseline_restored"]},
        "resources": {"peak_process_tree_rss_bytes": peak, "command_count": len(commands), "manifest_bytes": (run.root/"manifest.json").stat().st_size},
        "tools_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT/"backend/scripts").glob("chg301_r2_application_*.py"))},
        "peripheral_status": "DEFERRED_PERIPHERAL_BY_USER", "coverage_e2e_kubernetes": "DEFERRED_NOT_RELEASE_PASS",
        "new_risk_acceptances": 0, "deployment_writes": 0, "provider_calls": 0,
        "pr_write_status": "NOT_YET_UPDATED_REQUIRES_FRESH_REMOTE_AND_SOURCE_HYGIENE_CHECK"}
    output = ROOT/"docs/CHG-301-R2-APPLICATION-SECURITY-EVIDENCE.json"
    write_new(output, result)
    print(json.dumps({"status": result["status"], "blockers": blockers, "qualified": len(passed), "tests": test_rows,
                      "removed_images": len(cleanup["removed"]), "peak_rss_bytes": peak}), flush=True)
    if blockers:
        raise ValueError("application_pr_gate_not_met")


if __name__ == "__main__":
    main()
