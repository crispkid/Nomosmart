"""High-only checkpoint: immutable inventory and bounded read-only preflight.

This entry point deliberately cannot build, start containers or write GitHub.
Those operations must not be reachable until their material/security gates pass.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.request

import certifi

from chg301_r2_ingress import GIT_BASE, source_snapshot
from chg301_r2_node_qualification import (
    DOCKER, GiB, NoRedirect, file_sha, sha, validate_url, write_new,
)

ROOT = Path(__file__).resolve().parents[2]
SECTION = "CHG-301 R2 High-risk Remediation And Review PR Checkpoint"
PLAN = ROOT / "docs/CHG-301-R2-HIGH-PR-PLAN.md"
PLAN_SHA = "da3865a87a30f55e61aa78f74b1a6a3d12a7634af2139f7676a28c706bbe1fca"
PREAPPROVAL_SHA = "ef830bcb3007261cb61b4cea5fcb0e96a607c16c2912065c54c248f6b4c34dbb"
APPROVAL = "核准 CHG-301 R2 高風險修正、必要回歸與 PR 更新計畫"
NODE_EVIDENCE = ROOT / "docs/CHG-301-R2-NODE-QUALIFICATION-EVIDENCE.json"
HIGH = {"HIGH", "CRITICAL"}
INSPECT = '{"id":{{json .Id}},"status":{{json .State.Status}},"started_at":{{json .State.StartedAt}},"restart_count":{{.RestartCount}}}'
PR_FIELDS = "number,title,state,url,headRefOid,headRefName,baseRefName,isDraft,mergeStateStatus,statusCheckRollup"
RELEASES = {
    "kind": ("kubernetes-sigs/kind", "1.36", "1.36.4"),
    "cilium": ("cilium/cilium", "1.20", "1.20.1"),
    "traefik": ("traefik/traefik", "3.7", "3.7.13"),
}
REGISTRY_RECHECKS = {
    "node": ("docker.io/kindest/node:v1.36.4", "sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"),
    "cilium": ("quay.io/cilium/cilium:v1.20.1", "sha256:ae9ea21f7427fe24bc6ea7247eb552157a1b0a431744045d3f641545ca71d11b"),
    "operator": ("quay.io/cilium/operator-generic:v1.20.1", "sha256:6c3885fc7b629099fdbe2a5c87869c86feb825fa18fae299eac0f61918d16ecf"),
}


def approval_guard(plan: bytes, active: str) -> None:
    if sha(plan) != PLAN_SHA:
        raise ValueError("approved_plan_hash")
    sections = active.split("\n## ")
    if len(sections) < 2 or sections[1].splitlines()[0] != SECTION:
        raise ValueError("historical_plan_not_active")
    if any(value not in sections[1] for value in (
        "Gate 4 approval: APPROVED.", APPROVAL, PREAPPROVAL_SHA,
    )):
        raise ValueError("explicit_current_approval_required")


def time_guard(record: dict, now: datetime) -> None:
    started = datetime.fromisoformat(record["started_at"])
    deadline = datetime.fromisoformat(record["deadline"])
    if deadline - started != timedelta(hours=6) or now < started:
        raise ValueError("run_time_identity")
    if now >= deadline - timedelta(minutes=10):
        raise ValueError("run_time_exhausted")


def command_allowed(args: list[str]) -> bool:
    """No mutable Docker/Git/GitHub or arbitrary process dispatch."""
    if args[:3] == DOCKER:
        tail = args[3:]
        return tail in [
            ["ps", "-aq", "--no-trunc"],
            ["network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"],
            ["image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"],
            ["info", "--format", '{"cpu":{{.NCPU}},"memory":{{.MemTotal}}}'],
            ["stats", "--no-stream", "--format", "{{.ID}} {{.CPUPerc}} {{.MemUsage}}"],
        ] or (len(tail) == 4 and tail[:3] == ["buildx", "imagetools", "inspect"]
              and tail[3] in {v[0] for v in REGISTRY_RECHECKS.values()}) or (len(tail) == 4 and tail[:3] == ["inspect", "--format", INSPECT]
              and re.fullmatch(r"[0-9a-f]{64}", tail[3]) is not None)
    if args[:3] == ["git", "-C", str(ROOT)]:
        return args[3:] in [
            ["rev-parse", "HEAD", "MERGE_HEAD"], ["branch", "--show-current"],
            ["ls-files", "--unmerged"], ["diff", "--name-status"],
            ["diff", "--cached", "--name-status"],
        ]
    return args in [
        ["gh", "pr", "view", "1", "--repo", "crispkid/Nomosmart", "--json", PR_FIELDS],
        ["gh", "api", "repos/crispkid/Nomosmart/commits/main", "--jq", ".sha"],
        ["memory_pressure", "-Q"],
        ["kubectl", "--context", "docker-desktop", "top", "nodes", "--no-headers", "--request-timeout=10s"],
    ]


def high_ledger(evidence: dict) -> list[dict]:
    """Retain severity AND applicability; never turn unknown-high into deferred."""
    rows = []
    for entry in evidence["nodeFindings"]:
        severity = entry["raw_severity"]
        rows.append({
            "image": evidence["identities"]["node"]["arm64"], "id": entry["id"],
            "severity": severity, "prior_assessment": entry["assessment"],
            "state": "UNRESOLVED" if severity in HIGH else "DEFERRED_BY_SCOPE",
            "purls": entry["purls"], "scope": "node-original59",
        })
    for image in evidence["additionalFindings"]:
        for entry in image["findings"]:
            rows.append({
                "image": image["manifest_digest"], "id": entry["id"],
                "severity": entry["severity"], "prior_assessment": "INDETERMINATE",
                "state": "UNRESOLVED" if entry["severity"] in HIGH else "DEFERRED_BY_SCOPE",
                "sarif_sha256": image["sarif_sha256"], "scope": "additional",
            })
    rows.append({"image": evidence["identities"]["node"]["arm64"],
                 "id": "GHSA-p7v4-vr35-mj6f", "severity": "CRITICAL",
                 "state": "UNRESOLVED", "scope": "supplemental",
                 "prior_assessment": "EFFECTIVE_CONFIGURATION_UNVERIFIED"})
    if len({(r["image"], r["id"]) for r in rows}) != len(rows):
        raise ValueError("duplicate_image_finding")
    return rows


def raw_findings(report: dict) -> dict:
    """Keep every real scanner ID/package/location without its prose or snippets."""
    findings = {}
    for run in report["runs"]:
        rules = run["tool"]["driver"]["rules"]
        for result in run["results"]:
            rule = rules[result["ruleIndex"]]
            if rule["id"] != result["ruleId"]:
                raise ValueError("raw_rule_identity")
            severity = rule["properties"]["cvssV3_severity"]
            if severity not in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNSPECIFIED"}:
                raise ValueError("raw_severity_unknown")
            entry = findings.setdefault(rule["id"], {"severity": severity, "purls": set(), "locations": set(), "instances": 0})
            if entry["severity"] != severity:
                raise ValueError("raw_severity_conflict")
            entry["purls"].update(rule["properties"].get("purls", []))
            entry["locations"].update(loc["physicalLocation"]["artifactLocation"]["uri"] for loc in result.get("locations", []))
            entry["instances"] += 1
    return {key: {**value, "purls": sorted(value["purls"]), "locations": sorted(value["locations"])}
            for key, value in findings.items()}


def compatible_releases(family: str, releases: list[dict]) -> dict:
    _, series, baseline = RELEASES[family]
    candidates = {}
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        pattern = (r"kindest/node:v(" + re.escape(series) + r"\.\d+)@sha256:([0-9a-f]{64})"
                   if family == "kind" else r"^v(" + re.escape(series) + r"\.\d+)$")
        matches = re.findall(pattern, release.get("body", "") if family == "kind" else release["tag_name"])
        for match in matches:
            version = match[0] if family == "kind" else match
            candidates[version] = {"version": version, "release": release["html_url"],
                                   "published_at": release["published_at"],
                                   "index_digest": "sha256:" + match[1] if family == "kind" else None}
    if baseline not in candidates:
        raise ValueError("baseline_not_in_official_release_catalog")
    newer = sorted((v for v in candidates if tuple(map(int, v.split("."))) > tuple(map(int, baseline.split(".")))),
                   key=lambda v: tuple(map(int, v.split("."))), reverse=True)
    selected = [candidates[baseline], *(candidates[v] for v in newer[:2])]
    return {"family": family, "series": series, "selected": selected,
            "newer_candidates": len(newer),
            "status": "NO_NEWER_COMPATIBLE_RELEASE_IN_CATALOG" if not newer else "MATERIAL_BINDING_REQUIRED",
            "not_image_security_pass": True}


def pr_guard(rows: list[dict], regressions: str, cleanup: str, evidence_complete: bool,
             current_head: str, expected_head: str) -> None:
    if not rows or not evidence_complete:
        raise ValueError("pr_incomplete_security_evidence")
    # No implicit acceptance API: exact accepted records must be validated separately.
    if any(row["severity"] in HIGH and row["state"] != "FIXED" for row in rows):
        raise ValueError("pr_unresolved_high")
    if regressions != "PASS" or cleanup != "PASS":
        raise ValueError("pr_required_regression_cleanup")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head) or current_head != expected_head:
        raise ValueError("pr_remote_drift")


class Run:
    def __init__(self, manifest: str | None):
        approval_guard(PLAN.read_bytes(), (ROOT / "DEVELOPMENT_PLAN.md").read_text())
        os.umask(0o077)
        if manifest is None:
            self.work = Path(tempfile.mkdtemp(prefix="chg301-r2-high-", dir="/private/tmp"))
            now = datetime.now(UTC)
            self.record = {"scope": SECTION, "plan_sha256": PLAN_SHA, "preapproval_sha256": PREAPPROVAL_SHA,
                           "started_at": now.isoformat(), "deadline": (now + timedelta(hours=6)).isoformat(),
                           "root_inode": self.work.stat().st_ino, "owner_uid": os.getuid(),
                           "commands": [], "downloads": [], "phases": [], "failures": [],
                           "docker_mutations": 0, "pr_writes": 0, "provider_calls": 0}
            self.manifest = self.work / "manifest.json"
        else:
            self.manifest = Path(manifest)
            self.work = self.manifest.parent
            if (self.work.parent != Path("/private/tmp") or not self.work.name.startswith("chg301-r2-high-")
                    or self.manifest.name != "manifest.json" or self.work.is_symlink() or self.manifest.is_symlink()):
                raise ValueError("run_path_identity")
            self.record = json.loads(self.manifest.read_bytes())
            if (self.record["root_inode"] != self.work.stat().st_ino or self.record["owner_uid"] != os.getuid()
                    or self.record["plan_sha256"] != PLAN_SHA):
                raise ValueError("run_owner_scope_identity")
        for folder in ("raw", "analysis"):
            (self.work / folder).mkdir(exist_ok=True, mode=0o700)
        self.env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
        self.checkpoint()

    def checkpoint(self):
        path = self.work / "manifest-next.json"
        write_new(path, self.record)
        path.replace(self.manifest)

    def guard(self):
        approval_guard(PLAN.read_bytes(), (ROOT / "DEVELOPMENT_PLAN.md").read_text())
        time_guard(self.record, datetime.now(UTC))
        if shutil.disk_usage(self.work).free < 100 * GiB:
            raise ValueError("disk_headroom")
        if sum(p.stat().st_size for p in self.work.rglob("*") if p.is_file() and not p.is_symlink()) > 40 * GiB:
            raise ValueError("run_disk_limit")

    def command(self, args):
        self.guard()
        if not command_allowed(args):
            raise ValueError("command_scope")
        proc = subprocess.run(args, capture_output=True, env=self.env, timeout=60, check=False)
        n = len(self.record["commands"])
        write_new(self.work / "raw" / f"command-{n:03}.stdout", proc.stdout)
        write_new(self.work / "raw" / f"command-{n:03}.stderr", proc.stderr)
        self.record["commands"].append({"args": args, "exit_code": proc.returncode,
                                         "stdout_sha256": sha(proc.stdout), "stderr_sha256": sha(proc.stderr)})
        self.checkpoint()
        if proc.returncode:
            raise ValueError(f"command_failed_{n}")
        return proc.stdout

    def baseline(self):
        ids = sorted(self.command([*DOCKER, "ps", "-aq", "--no-trunc"]).decode().split())
        return {"containers": [json.loads(self.command([*DOCKER, "inspect", "--format", INSPECT, i])) for i in ids],
                "images": sorted(self.command([*DOCKER, "image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"]).decode().splitlines()),
                "networks": sorted(self.command([*DOCKER, "network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"]).decode().splitlines())}

    def preflight(self):
        if "preflight" in self.record["phases"]:
            raise ValueError("preflight_cannot_reset")
        if self.command(["git", "-C", str(ROOT), "rev-parse", "HEAD", "MERGE_HEAD"]).decode().split() != GIT_BASE:
            raise ValueError("git_parent_drift")
        if self.command(["git", "-C", str(ROOT), "ls-files", "--unmerged"]).strip():
            raise ValueError("git_unmerged_entries")
        self.record["source_before"] = source_snapshot()
        prior = json.loads(NODE_EVIDENCE.read_bytes())
        if self.record["source_before"] != prior["source"]:
            raise ValueError("source_drift_before_repair")
        self.record["baseline_before"] = self.baseline()
        if self.record["baseline_before"] != prior["protection"]["after"]:
            raise ValueError("docker_baseline_drift")
        self.record["vm_capacity"] = json.loads(self.command([*DOCKER, "info", "--format", '{"cpu":{{.NCPU}},"memory":{{.MemTotal}}}']))
        self.record["docker_stats"] = self.command([*DOCKER, "stats", "--no-stream", "--format", "{{.ID}} {{.CPUPerc}} {{.MemUsage}}"]).decode()
        self.record["host_memory"] = self.command(["memory_pressure", "-Q"]).decode()
        self.record["host_free_bytes"] = shutil.disk_usage(self.work).free
        self.record["host_cpu"] = {"count": os.cpu_count(), "load": list(os.getloadavg())}
        self.record["heavy_work_gate"] = "UNVERIFIED_VM_AVAILABLE_MEMORY_AND_JOB_LIMIT_ENFORCEMENT"
        self.record["pr_before"] = json.loads(self.command(["gh", "pr", "view", "1", "--repo", "crispkid/Nomosmart", "--json", PR_FIELDS]))
        self.record["main_before"] = self.command(["gh", "api", "repos/crispkid/Nomosmart/commits/main", "--jq", ".sha"]).decode().strip()
        if (self.record["pr_before"]["headRefOid"] != GIT_BASE[0] or self.record["main_before"] != GIT_BASE[1]
                or self.record["pr_before"]["state"] != "OPEN" or self.record["pr_before"]["headRefName"] != "fix/compose-method1-installer"):
            raise ValueError("remote_baseline_drift")
        self.record["input_evidence_sha256"] = file_sha(NODE_EVIDENCE)
        self.record["phases"].append("preflight")
        self.checkpoint()

    def ledger(self):
        self.guard()
        if "preflight" not in self.record["phases"] or file_sha(NODE_EVIDENCE) != self.record["input_evidence_sha256"]:
            raise ValueError("ledger_preflight_binding")
        evidence = json.loads(NODE_EVIDENCE.read_bytes())
        for image in evidence["additionalFindings"]:
            for suffix, key in (("sarif", "sarif_sha256"), ("spdx", "spdx_sha256")):
                path = Path(evidence["run"]["root"]) / "analysis" / (image["name"] + "." + suffix + ".json")
                if path.is_symlink() or file_sha(path) != image[key]:
                    raise ValueError("retained_raw_drift")
        rows = high_ledger(evidence)
        write_new(self.work / "analysis/high-ledger.json", rows)
        self.record["ledger_summary"] = {"rows": len(rows), "states": dict(Counter(r["state"] for r in rows)),
                                          "raw_high_unique_ids": len({r["id"] for r in rows if r["severity"] in HIGH and r["scope"] != "supplemental"})}
        self.record["phases"].append("ledger")
        self.checkpoint()

    def catalogs(self):
        self.guard()
        if "preflight" not in self.record["phases"]:
            raise ValueError("catalog_preflight_required")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                    urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
        results = []
        for family, (repo, _, _) in RELEASES.items():
            url = f"https://api.github.com/repos/{repo}/releases?per_page=30"
            validate_url(url, {"api.github.com"})
            path = self.work / "raw" / f"{family}-releases.json"
            if path.exists():
                raise ValueError("catalog_no_overwrite")
            with opener.open(urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"}), timeout=30) as response:
                if response.status != 200:
                    raise ValueError("catalog_status")
                data = response.read(4 * 1024**2 + 1)
                if len(data) > 4 * 1024**2:
                    raise ValueError("catalog_size")
            write_new(path, data)
            rows = json.loads(data)
            result = compatible_releases(family, rows)
            result.update({"url": url, "raw_sha256": sha(data), "observed_at": datetime.now(UTC).isoformat(),
                           "catalog_release_count": len(rows), "scope_limit": "Latest 30 official release records; no unpublished registry artifacts inferred."})
            results.append(result)
            self.record["downloads"].append({"url": url, "path": str(path.relative_to(self.work)), "sha256": sha(data), "bytes": len(data)})
            self.checkpoint()
        write_new(self.work / "analysis/official-candidates.json", results)
        self.record["phases"].append("catalogs")
        self.checkpoint()

    def evidence(self):
        self.guard()
        prior = json.loads(NODE_EVIDENCE.read_bytes())
        rows = high_ledger(prior)
        research = json.loads((ROOT / "docs/CHG-301-R2-NODE-REMEDIATION-RESEARCH-EVIDENCE.json").read_bytes())
        sources = [{"image": prior["identities"]["node"]["arm64"],
                    "path": Path(research["artifacts"]["root"]) / "all-severity.sarif.json",
                    "hash": research["artifacts"]["all-severity.sarif.json"]}]
        for image in prior["additionalFindings"]:
            sources.append({"image": image["manifest_digest"],
                            "path": Path(prior["run"]["root"]) / "analysis" / (image["name"] + ".sarif.json"),
                            "hash": image["sarif_sha256"]})
        by_identity = {(row["image"], row["id"]): row for row in rows}
        for source in sources:
            if source["path"].is_symlink() or file_sha(source["path"]) != source["hash"]:
                raise ValueError("raw_source_digest")
            for identifier, details in raw_findings(json.loads(source["path"].read_bytes())).items():
                row = by_identity.get((source["image"], identifier))
                if row is None:
                    if details["severity"] in HIGH:
                        raise ValueError("missing_previously_tracked_high")
                    row = {"image": source["image"], "id": identifier, "severity": details["severity"],
                           "scope": "node-additional-nonhigh", "state": "DEFERRED_BY_SCOPE",
                           "prior_assessment": "NOT_ASSESSED_BY_HIGH_ONLY_SCOPE"}
                    rows.append(row)
                if row["severity"] != details["severity"]:
                    raise ValueError("summary_raw_severity_drift")
                row.update(details)
                row["sarif_sha256"] = source["hash"]
        write_new(self.work / "analysis/high-ledger-complete-raw.json", rows)
        app = json.loads((ROOT / "docs/CHG-301-R2-SECURITY-AMENDMENT-EVIDENCE.json").read_bytes())
        changed = [name for name, digest in app["security"]["source_sha256"].items()
                   if file_sha(ROOT / name) != digest]
        if changed:
            raise ValueError("prior_app_security_source_drift")
        old_result = Path(app["local_evidence"]["security_result"])
        if file_sha(old_result) != app["security"]["result_sha256"]:
            raise ValueError("prior_app_security_result_drift")
        self.record["app_security_reuse"] = {
            "source_files_unchanged": len(app["security"]["source_sha256"]),
            "result_sha256": file_sha(old_result), "scan_time": app["security"]["finished_at"],
            "checks": {k: {"status": v["status"], "findings": len(v["findings"])} for k, v in app["security"]["checks"].items()},
            "fresh_scan": False, "candidate_app_image_scan_complete": False,
        }
        self.record["complete_ledger_summary"] = {
            "rows": len(rows), "states": dict(Counter(row["state"] for row in rows)),
            "raw_high_unique_ids": len({row["id"] for row in rows if row["severity"] in HIGH and row["scope"] != "supplemental"}),
            "supplemental_critical": 1, "new_fixes": 0,
        }
        self.record["phases"].append("evidence")
        self.checkpoint()

    def recheck(self):
        self.guard()
        results = []
        for name, (reference, expected) in REGISTRY_RECHECKS.items():
            raw = self.command([*DOCKER, "buildx", "imagetools", "inspect", reference])
            match = re.search(r"^Digest:\s+(sha256:[0-9a-f]{64})\s*$", raw.decode(), re.M)
            if not match or match[1] != expected:
                raise ValueError("official_tag_digest_drift")
            results.append({"name": name, "reference": reference, "digest": expected,
                            "stdout_sha256": sha(raw), "time": datetime.now(UTC).isoformat()})
        self.record["registry_rechecks"] = results
        self.record["phases"].append("recheck")
        self.checkpoint()

    def capacity(self):
        # Read-only metrics, never installing a metrics server to make a gate pass.
        n = len(self.record["commands"])
        try:
            self.command(["kubectl", "--context", "docker-desktop", "top", "nodes", "--no-headers", "--request-timeout=10s"])
        except ValueError as exc:
            if str(exc) != f"command_failed_{n}":
                raise
            self.record["vm_metrics"] = {"status": "UNAVAILABLE", "command_index": n}
        else:
            self.record["vm_metrics"] = {"status": "RECORDED_NOT_YET_BUDGET_QUALIFIED", "command_index": n}
        self.record["phases"].append("capacity")
        self.checkpoint()

    def closeout(self):
        self.guard()
        after = self.baseline()
        self.record["baseline_after"] = after
        if after != self.record["baseline_before"]:
            raise ValueError("baseline_drift_at_closeout")
        self.record["source_after"] = source_snapshot()
        self.record["source_changes"] = [k for k, v in self.record["source_before"].items()
                                          if self.record["source_after"].get(k) != v]
        if set(self.record["source_changes"]) - {"backend/tests/test_chg301_r2_ingress.py"}:
            raise ValueError("unapproved_source_drift")
        self.record["phases"].append("closeout")
        self.checkpoint()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "ledger", "catalogs", "evidence", "recheck", "capacity", "closeout"))
    parser.add_argument("--manifest")
    args = parser.parse_args()
    run = Run(args.manifest)
    print("manifest=" + str(run.manifest), flush=True)
    try:
        getattr(run, args.phase)()
    except Exception as exc:
        run.record["failures"].append({"phase": args.phase, "type": type(exc).__name__, "message": str(exc),
                                       "time": datetime.now(UTC).isoformat()})
        run.checkpoint()
        raise
    print(json.dumps({"phase": args.phase, "status": "RECORDED", "does_not_prove_remediation": True}))


if __name__ == "__main__":
    main()
