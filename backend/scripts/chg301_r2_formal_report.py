"""Compact receipt of real local evidence; no runtime, network or PR operations."""
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from chg301_r2_formal_dependencies import ROOT, PLAN_SHA, source_guard
from chg301_r2_node_qualification import file_sha, write_new


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "/private/tmp/chg301-r2-formal-ytnv04nm/manifest.json":
        raise ValueError("exact_run_only")
    path = Path(sys.argv[1])
    root = path.parent
    run = json.loads(path.read_bytes())
    source = source_guard(run["source"])
    out = {"change": "CHG-301 R2", "requirements": ["CMPUPG-001", "CMPUPG-002", "CMPUPG-003", "CMPUPG-004"],
        "status": "PARTIAL_PR_BLOCKED", "generated_at": datetime.now(UTC).isoformat(),
        "plan_sha256": PLAN_SHA, "run_manifest": {"path": str(path), "sha256": file_sha(path)},
        "started_at": run["started_at"], "deadline": run["deadline"],
        "git_parent_ids": ["c261a494283835af57c0e0678afc7ee7e2c0dcc8", "5f1a0a2505dee9c85ee621bd2c8680b92d397a45"],
        "source_count": len(source), "source_changes": [{"path": p, "before": run["source"][p], "after": h}
            for p, h in source.items() if h != run["source"][p]],
        "sql_migrations_unchanged": all(h == run["source"][p] for p, h in source.items() if p.startswith("sql/migrations/")),
        "application_locks_unchanged": all(source[p] == run["source"][p] for p in
            ("frontend/package.json", "frontend/package-lock.json", "backend/pyproject.toml", "backend/uv.lock")),
        "scans": [], "builds": [], "test_reports": [], "other_receipts": [],
        "provider_calls": 0, "kubernetes_mutations": 0, "pr_writes": 0,
        "new_risk_acceptances": 0, "full_coverage_e2e_kubernetes": "DEFERRED_NOT_PASS",
        "manifest_counter_note": "static dispatcher runtime_mutations counter is not an aggregate of independent build/live wrappers; use the actual journals and cleanup receipts below",
        "remaining_blocks": ["official formal dependency High/Critical findings", "Backend builder linux-libc-dev/source-kernel applicability unresolved", "Redis multi-Sentinel failover failed with DNS/TILT and peer-auth evidence", "CLI resource/termination permission failure before container creation", "12 newly created/pulled images retained; cleanup not executed", "other platforms/final artifacts/necessary integrations not fully qualified"]}
    for scan in run["scans"]:
        reports = scan["reports"]
        for report in reports.values():
            if file_sha(Path(report["path"])) != report["sha256"]:
                raise ValueError("raw_report_drift")
        counts = dict(Counter(f["severity"] for f in scan["findings"].values()))
        if counts != scan["counts"]:
            raise ValueError("scan_count_mismatch")
        ledger = [{"advisory_id": key, "severity": f["severity"], "purls": f["purls"],
                   "location_count": len(f["locations"]), "raw_locations": "full SARIF report; no suppressed paths",
                   "state": "UNRESOLVED" if f["severity"] in {"HIGH", "CRITICAL"} else "DEFERRED_NONHIGH"}
                  for key, f in scan["findings"].items()]
        out["scans"].append({"name": scan["name"], "target": scan["target"], "reports": reports,
            "counts": counts, "status": scan["status"], "ledger": ledger})
    for candidate in sorted(root.glob("*/result.json")):
        record = json.loads(candidate.read_bytes())
        if "image_id" in record and "tag" in record:
            out["builds"].append({"path": str(candidate), "sha256": file_sha(candidate),
                **{k: record[k] for k in ("tag", "image_id", "exit_code", "elapsed_seconds", "resource_envelope") if k in record}})
    for xml in sorted((root / "analysis").glob("*.xml")):
        tree = ET.parse(xml).getroot()
        cases = tree.findall(".//testcase")
        failures = [c.attrib["name"] for c in cases if c.find("failure") is not None or c.find("error") is not None]
        out["test_reports"].append({"path": str(xml), "sha256": file_sha(xml), "tests": len(cases),
            "failed_or_error": len(failures), "skipped": len(tree.findall(".//skipped")), "failures": failures})
    for pattern in ("*-live-*/cleanup.json", "capacity-*/result.json", "analysis/*cleanup*.json",
                    "analysis/readonly-closeout.json", "analysis/app-cli-blocked.json", "analysis/*bandit-final*.json", "analysis/harness-final.json",
                    "analysis/source-hygiene-final.json", "analysis/uv-official-metadata.json",
                    "analysis/npm-11.19.1-material.json", "analysis/ubuntu-24.04.manifest.json"):
        for receipt in sorted(root.glob(pattern)):
            out["other_receipts"].append({"path": str(receipt), "sha256": file_sha(receipt)})
    out["readonly_closeout"] = json.loads((root / "analysis/readonly-closeout.json").read_bytes())
    out["live_lab_count"] = len(list(root.glob("*-live-*/journal.json")))
    out["probe_count"] = len(list(root.glob("capacity-*/result.json")))
    out["tools_sha256"] = {str(p.relative_to(ROOT)): file_sha(p) for p in sorted((ROOT / "backend/scripts").glob("chg301_r2_formal*.py"))}
    write_new(root / "analysis/final-evidence.json", out)
    print(json.dumps({"evidence": str(root / "analysis/final-evidence.json"),
        "sha256": file_sha(root / "analysis/final-evidence.json"), "status": out["status"],
        "scans": len(out["scans"]), "builds": len(out["builds"])}))


if __name__ == "__main__":
    main()
