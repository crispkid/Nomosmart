"""App-only local SAST plus exact same-source public dependency audit reuse."""
from collections import Counter
import json
from pathlib import Path
import sys

from chg301_r2_application_run import Run, ROOT
from chg301_r2_application_guard import digest, write_new
from chg301_r2_security import assess_static_risk, RISK_PATH


def main():
    if len(sys.argv) not in (2,3) or len(sys.argv) == 3 and sys.argv[2] not in {"2", "3"}:
        raise ValueError("exact_application_manifest_required")
    run = Run(sys.argv[1])
    work = run.root/("app-audit" if len(sys.argv) == 2 else "app-audit-attempt"+sys.argv[2])
    work.mkdir(mode=0o700)
    prior = Path("/private/tmp/chg301-r2-security-gu0ylzpx/result.json")
    if digest(prior) != "e917b6bc35ce1960070251df0f6c18b02126bc85cef5376419596d535299aaf3":
        raise ValueError("dependency_receipt_drift")
    old = json.loads(prior.read_bytes())
    selected = {name: sha for name, sha in old["source_sha256"].items()
                if name.startswith("backend/app/") or name in {"backend/uv.lock", "backend/pyproject.toml", "frontend/package.json", "frontend/package-lock.json", RISK_PATH}}
    if any(digest(ROOT/name) != sha for name, sha in selected.items()):
        raise ValueError("dependency_audit_source_drift")
    reports = {name: {"path": str(prior.parent/(name+".json")), "sha256": digest(prior.parent/(name+".json"))}
               for name in ("npm-production", "npm-full", "pip-production", "pip-full")}
    dependency = {"mode": "HISTORICAL_SAME_SOURCE_REUSE_NOT_NEW_ONLINE_AUDIT", "path": str(prior),
                  "sha256": digest(prior), "finished_at": old["finished_at"], "source_sha256": selected,
                  "checks": {name: old["checks"][name] for name in reports}, "reports": reports}
    if any(v["status"] != "PASS" for v in dependency["checks"].values()):
        raise ValueError("dependency_findings_need_review")
    scanner = "/private/tmp/chg301-r2-security-0utu1kq_/scanner-venv/bin/bandit"
    path = work/"bandit.json"
    run.command([scanner, "-r", "backend/app", "--ignore-nosec", "-f", "json", "-o", str(path)], allowed=(0,1))
    report = json.loads(path.read_bytes())
    if report["errors"] or report["metrics"]["_totals"]["loc"] == 0:
        raise ValueError("sast_incomplete")
    assessment = assess_static_risk(report["results"], selected, (ROOT/RISK_PATH).read_bytes())
    tools_report = work/"tool-bandit.json"
    tool_names = sorted(str(p.relative_to(ROOT)) for p in (ROOT/"backend/scripts").glob("chg301_r2_application_*.py"))
    run.command([scanner, *tool_names, "--ignore-nosec", "-f", "json", "-o", str(tools_report)], allowed=(0,1))
    tools = json.loads(tools_report.read_bytes())
    tools_high = [f for f in tools["results"] if f["issue_severity"] in {"HIGH", "CRITICAL"}]
    result = {"dependency_audit": dependency, "backend_sast": {"path": str(path), "sha256": digest(path),
        "assessment": assessment, "counts": dict(Counter(f["issue_severity"] for f in report["results"]))},
        "tool_sast": {"path": str(tools_report), "sha256": digest(tools_report), "high_count": len(tools_high),
                      "source_sha256": {p: digest(ROOT/p) for p in tool_names}},
        "not_full_frontend_security_or_runtime_acceptance": True}
    write_new(work/"result.json", result)
    run.data["source_audit"] = {"path": str(work/"result.json"), "sha256": digest(work/"result.json")}
    run.save()
    print(json.dumps({"dependencies": "SAME_SOURCE_4_PASS", "sast": assessment["status"], "accepted_high": len(assessment["accepted_findings"]), "tool_high": len(tools_high)}), flush=True)
    if assessment["status"] == "FAIL" or tools_high or tools["errors"]:
        raise ValueError("unaccepted_source_high")


if __name__ == "__main__":
    main()
