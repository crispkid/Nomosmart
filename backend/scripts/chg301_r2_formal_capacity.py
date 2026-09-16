"""Exact networkless 32 MiB VM probe using an already scanned local image.

Only the new labelled probe is deleted. No build, cluster, secret or application
access. Historical scan reuse is recorded, not represented as a fresh image scan.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from chg301_r2_formal_dependencies import approval_guard, source_guard
from chg301_r2_delivery import source_manifest
from chg301_r2_high_risk import raw_findings, time_guard, INSPECT
from chg301_r2_node_qualification import DOCKER, GiB, file_sha, write_new

OLD = Path("/private/tmp/chg301-r2-delivery-c0j_1wn6/manifest.json")
OLD_SHA = "c765eb1d0c49cc896b240a741181c464430649afd9b5460e11e2773a6ee3feb7"
IMAGE = "sha256:3fb90bfc19cf0548ad5bcd3d2db4b5915e6b0d37ed7c381c4dff8e36ae57cd8f"
LABEL = "nomosmart.chg301.formal.probe"


def main():
    approval_guard()
    if len(sys.argv) != 2:
        raise ValueError("one_exact_manifest_required")
    path = Path(sys.argv[1])
    root = path.parent
    if (len(sys.argv) != 2 or root.parent != Path("/private/tmp")
            or not root.name.startswith("chg301-r2-formal-") or path.name != "manifest.json"
            or path.is_symlink() or root.is_symlink()):
        raise ValueError("run_identity")
    manifest = json.loads(path.read_bytes())
    time_guard(manifest, datetime.now(UTC))
    source_guard(manifest["source"])
    if file_sha(OLD) != OLD_SHA:
        raise ValueError("historical_scan_identity")
    old = json.loads(OLD.read_bytes())
    scan = next(s for s in old["scans"] if s["name"] == "frontend")
    if scan["target"]["identity"]["id"] != IMAGE:
        raise ValueError("probe_image_identity")
    for report in scan["reports"].values():
        if file_sha(Path(report["path"])) != report["sha256"]:
            raise ValueError("scan_report_drift")
    findings = raw_findings(json.loads(Path(scan["reports"]["cves"]["path"]).read_bytes()))
    if any(f["severity"] in {"HIGH", "CRITICAL"} for f in findings.values()):
        raise ValueError("probe_security_gate")
    os.umask(0o077)
    work = Path(tempfile.mkdtemp(prefix="capacity-", dir=root))
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    evidence = {"started_at": datetime.now(UTC).isoformat(), "commands": [],
                "status": "BLOCKED", "image_id": IMAGE, "historical_scan_sha256": OLD_SHA,
                "scan_reused_not_fresh": True, "kubernetes_operations": 0, "provider_calls": 0}

    def command(args):
        result = subprocess.run([*DOCKER, *args], env=env, capture_output=True, timeout=30)
        index = len(evidence["commands"])
        write_new(work / f"{index:03}.stdout", result.stdout)
        write_new(work / f"{index:03}.stderr", result.stderr)
        evidence["commands"].append({"args": args, "exit_code": result.returncode})
        if result.returncode:
            raise ValueError(f"command_{index}_failed")
        return result.stdout.decode()

    def baseline():
        return [json.loads(command(["inspect", "--format", INSPECT, ident]))
                for ident in sorted(command(["ps", "-aq", "--no-trunc"]).split())]

    ident = None
    before = baseline()
    if before != manifest["baseline_before"]["containers"]:
        raise ValueError("container_baseline_drift")
    try:
        info = json.loads(command(["info", "--format", '{"cpu":{{.NCPU}},"memory":{{.MemTotal}}}']))
        actual_image = json.loads(command(["image", "inspect", "--format", '{"id":{{json .Id}},"arch":{{json .Architecture}}}', IMAGE]))
        if actual_image != {"id": IMAGE, "arch": "arm64"}:
            raise ValueError("local_image_drift")
        ident = command(["create", "--name", root.name + "-probe", "--label", LABEL + "=" + root.name,
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "32m", "--memory-swap", "32m", "--cpus", "0.1", "--pids-limit", "16",
            "--user", "10001:10001", "--entrypoint", "/bin/sh", IMAGE, "-c",
            "cat /proc/meminfo; head -n 1 /proc/stat; sleep 2; head -n 1 /proc/stat; df -Pk /"]).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", ident):
            raise ValueError("probe_id")
        write_new(work / "owned.json", {"id": ident, "label": LABEL, "run": root.name})
        output = command(["start", "--attach", ident])
        if command(["inspect", "--format", "{{.State.ExitCode}}", ident]).strip() != "0":
            raise ValueError("probe_failure")
        memory = {m[1]: int(m[2]) * 1024 for line in output.splitlines()
                  if (m := re.fullmatch(r"(MemTotal|MemAvailable):\s+(\d+) kB", line))}
        samples = [list(map(int, line.split()[1:])) for line in output.splitlines() if line.startswith("cpu ")]
        if len(samples) != 2 or set(memory) != {"MemTotal", "MemAvailable"}:
            raise ValueError("probe_incomplete")
        delta = [b-a for a, b in zip(*samples)]
        total = sum(delta[:8])
        if total <= 0:
            raise ValueError("cpu_sample")
        busy = info["cpu"] * (total-delta[3]-delta[4])/total
        disk = next(line.split() for line in output.splitlines() if line.startswith("overlay "))
        reserve = max(8 * GiB, .2 * info["memory"])
        evidence["capacity"] = {**memory, "busy_cpu": busy,
            "available_job_cpu": min(4, max(0, info["cpu"]-4-busy)),
            "available_job_memory": min(8 * GiB, max(0, memory["MemAvailable"]-reserve)),
            "disk_free": int(disk[3])*1024, "cpu_reserve": 4, "memory_reserve": reserve}
        evidence["status"] = "MEASURED_NOT_BUILD_OR_RUNTIME_ACCEPTANCE"
    finally:
        if ident:
            identity = json.loads(command(["inspect", "--format", '{"id":{{json .Id}},"labels":{{json .Config.Labels}}}', ident]))
            if identity["id"] != ident or identity["labels"].get(LABEL) != root.name or ident in {v["id"] for v in before}:
                raise ValueError("cleanup_identity")
            write_new(work / "cleanup-dry-run.json", {"container_id": ident, "only_owned_probe": True})
            command(["rm", ident])
            evidence["probe_removed"] = True
        evidence["baseline_unchanged"] = baseline() == before
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        write_new(work / "result.json", evidence)
        print(json.dumps({**{k: v for k, v in evidence.items() if k != "commands"},
                          "evidence": str(work / "result.json")}), flush=True)
    return 0 if evidence["baseline_unchanged"] and evidence["status"].startswith("MEASURED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
