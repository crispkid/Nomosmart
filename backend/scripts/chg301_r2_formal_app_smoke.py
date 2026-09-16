"""Exact source-bound CLI checks, networkless/nonroot; no application startup."""
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from chg301_r2_formal_dependencies import Run, ROOT, source_guard
from chg301_r2_high_risk import raw_findings
from chg301_r2_node_qualification import DOCKER, GiB, file_sha, write_new


def main():
    if len(sys.argv) != 2:
        raise ValueError("exact_current_manifest_required")
    run = Run(sys.argv[1])
    run.guard()
    work = run.root / "app-cli"
    work.mkdir(mode=0o700)
    before = run.baseline()
    if before["containers"] != run.data["baseline_before"]["containers"]:
        raise ValueError("protected_container_drift")
    probe = subprocess.run([sys.executable, str(ROOT / "backend/scripts/chg301_r2_formal_capacity.py"),
        str(run.root / "manifest.json")], env=run.env, capture_output=True, text=True, timeout=120, check=True)
    capacity = json.loads(probe.stdout.splitlines()[-1])
    if capacity["capacity"]["available_job_cpu"] < 1 or capacity["capacity"]["available_job_memory"] < GiB:
        raise ValueError("insufficient_capacity")
    record = {"started_at": datetime.now(UTC).isoformat(), "capacity": capacity,
              "source": source_guard(run.data["source"]), "cases": [], "commands": []}
    specs = (
        ("frontend-runner-r3", "test ! -e /usr/local/bin/npm; node --version; node node_modules/next/dist/bin/next --version; node -e \"console.log(require('crypto').createHash('sha256').update('CHG301').digest('hex'))\""),
        ("frontend-builder-r2", "npm --version; node --version; node node_modules/next/dist/bin/next --version"),
        ("backend-runner-r2", "python3 --version; /opt/venv/bin/python -c 'import fastapi,ssl; print(fastapi.__version__); print(ssl.OPENSSL_VERSION)'; /opt/venv/bin/uvicorn --version; test ! -e /opt/uv/bin/uv"),
    )
    started = time.monotonic()

    def command(args):
        if time.monotonic()-started > 600 and args[0] not in {"inspect", "rm", "ps"}:
            raise ValueError("cli_time_limit")
        result = subprocess.run([*DOCKER, *args], env=run.env, capture_output=True, text=True, timeout=30)
        record["commands"].append({"args": args, "exit_code": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode:
            raise ValueError("cli_command_failed")
        return result.stdout.strip()

    try:
        for name, script in specs:
            run.guard()
            build = json.loads((run.root / name / "result.json").read_bytes())
            scan = json.loads((run.root / name / "scan.json").read_bytes())
            if scan["image_id"] != build["image_id"]:
                raise ValueError("scan_build_mismatch")
            for report in scan["reports"].values():
                if file_sha(Path(report["path"])) != report["sha256"]:
                    raise ValueError("scan_changed")
            findings = raw_findings(json.loads(Path(scan["reports"]["cves"]["path"]).read_bytes()))
            if any(f["severity"] in {"HIGH", "CRITICAL"} for f in findings.values()):
                raise ValueError("cli_security_gate")
            context = json.loads((run.root / name / "context.json").read_bytes())
            if any(file_sha(ROOT / src) != context["sha256"][dest] for dest, src in context["sources"].items()):
                raise ValueError("cli_source_drift")
            label = "nomosmart.chg301.formal.cli"
            ident = command(["create", "--pull=never", "--label", label + "=" + run.root.name,
                "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", "10001:10001", "--cpus", "1", "--memory", "1g", "--memory-swap", "1g",
                "--pids-limit", "64", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
                "--env", "HOME=/tmp", "--entrypoint", "/bin/sh", build["image_id"], "-ec", script])
            item = {"name": name, "image_id": build["image_id"], "container_id": ident}
            record["cases"].append(item)
            try:
                item["stdout"] = command(["start", "--attach", ident])
                item["exit_code"] = int(command(["inspect", "--format", "{{.State.ExitCode}}", ident]))
                if item["exit_code"]:
                    raise ValueError("cli_failure")
                if name == "frontend-builder-r2" and item["stdout"].splitlines()[0] != "11.19.1":
                    raise ValueError("npm_version_mismatch")
            finally:
                identity = json.loads(command(["inspect", "--format", '{"id":{{json .Id}},"image":{{json .Image}},"labels":{{json .Config.Labels}}}', ident]))
                if (identity["id"] != ident or identity["image"] != build["image_id"]
                        or identity["labels"].get(label) != run.root.name
                        or ident in {c["id"] for c in before["containers"]}):
                    raise ValueError("cleanup_identity")
                write_new(work / (name + "-cleanup-dry-run.json"), identity)
                command(["rm", ident])
                item["removed"] = True
    finally:
        record["baseline_unchanged"] = run.baseline() == before
        record["finished_at"] = datetime.now(UTC).isoformat()
        write_new(work / "result.json", record)
        print(json.dumps({"cases": [{k: v for k, v in c.items() if k != "stdout"} for c in record["cases"]],
                          "baseline_unchanged": record["baseline_unchanged"]}), flush=True)
    if not record["baseline_unchanged"]:
        raise ValueError("docker_baseline_drift")


if __name__ == "__main__":
    main()
