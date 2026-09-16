"""Approved application-only run. Small manifest, immutable per-command receipts."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from chg301_r2_application_guard import GiB, digest, execute, write_new
from chg301_r2_delivery import source_manifest
from chg301_r2_high_risk import INSPECT

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/CHG-301-R2-APPLICATION-SECURITY-PLAN.md"
PLAN_SHA = "7150b1486e366b8fe81e47bdf81792038739410bf8505c639e22b9079412a6e0"
DOCKER = ["docker", "--context", "desktop-linux"]
OLD = Path("/private/tmp/chg301-r2-formal-ytnv04nm")
PROBE = "sha256:dcb458bcb1b84eb32b7ff27285cac4a64c8865fef9c413a4d000972dbe57197c"
LABEL = "nomosmart.chg301.application"


def approval():
    active = (ROOT/"DEVELOPMENT_PLAN.md").read_text().split("\n## ")[1]
    if (digest(PLAN) != PLAN_SHA or not active.startswith("CHG-301 R2 Backend Frontend Application Security\n")
            or "Gate 4 approval: APPROVED." not in active
            or "核准 CHG-301 R2 Backend／Frontend 高風險修補與驗證計畫" not in active):
        raise ValueError("application_current_approval_required")


def compact_sarif(path):
    # Full raw SARIF remains immutable; do not duplicate massive file locations.
    if path.stat().st_size > 512*1024**2:
        raise ValueError("sarif_requires_streaming_review")
    report = json.loads(path.read_bytes())
    findings = {}
    for run in report["runs"]:
        rules = run["tool"]["driver"]["rules"]
        for result in run["results"]:
            rule = rules[result["ruleIndex"]]
            severity = rule["properties"]["cvssV3_severity"]
            if rule["id"] != result["ruleId"] or severity not in {"HIGH", "CRITICAL", "MEDIUM", "LOW", "UNSPECIFIED"}:
                raise ValueError("scanner_contract")
            entry = findings.setdefault(rule["id"], {"severity": severity, "purls": set(), "instances": 0})
            if entry["severity"] != severity:
                raise ValueError("conflicting_severity")
            entry["purls"].update(rule["properties"].get("purls", []))
            entry["instances"] += 1
    return {key: {**entry, "purls": sorted(entry["purls"])} for key, entry in findings.items()}


class Run:
    def __init__(self, path=None):
        approval()
        os.umask(0o077)
        if path:
            path = Path(path)
            self.root = path.parent
            if (self.root.parent != Path("/private/tmp") or not self.root.name.startswith("chg301-r2-application-")
                    or path.name != "manifest.json" or path.is_symlink() or self.root.is_symlink()):
                raise ValueError("run_path")
            self.data = json.loads(path.read_bytes())
            if self.data["owner"] != os.getuid() or self.data["inode"] != self.root.stat().st_ino:
                raise ValueError("run_owner")
        else:
            self.root = Path(tempfile.mkdtemp(prefix="chg301-r2-application-", dir="/private/tmp"))
            now = datetime.now(UTC)
            self.data = {"started_at": now.isoformat(), "deadline": (now+timedelta(hours=6)).isoformat(),
                         "owner": os.getuid(), "inode": self.root.stat().st_ino,
                         "plan_sha256": PLAN_SHA, "source_before": source_manifest(),
                         "commands": [], "artifacts": {}, "status": "IN_PROGRESS",
                         "peripherals": "DEFERRED_PERIPHERAL_BY_USER", "provider_calls": 0, "deployment_writes": 0}
        self.env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        self.env.update(PYTHONDONTWRITEBYTECODE="1", DOCKER_CLI_HINTS="false",
                        DOCKER_SCOUT_CACHE_DIR=str(self.root/"scanner-cache"),
                        GOMEMLIMIT="2GiB", GOGC="50", GOMAXPROCS="2",
                        COMPOSE_DISABLE_ENV_FILE="1", COMPOSE_ENV_FILES="/dev/null")
        (self.root/"commands").mkdir(exist_ok=True, mode=0o700)
        self.save()

    def save(self):
        draft = self.root/"manifest.next.json"
        write_new(draft, self.data)
        draft.replace(self.root/"manifest.json")

    def guard(self):
        approval()
        if self.data.get("permission_stop"):
            raise PermissionError("prior_owned_process_permission_failure_requires_direction")
        now = datetime.now(UTC)
        start, end = (datetime.fromisoformat(self.data[k]) for k in ("started_at", "deadline"))
        if self.data["plan_sha256"] != PLAN_SHA or end-start != timedelta(hours=6) or not start <= now < end-timedelta(minutes=10):
            raise ValueError("run_window_or_identity")
        if source_manifest() != self.data.get("source_accepted", self.data["source_before"]):
            raise ValueError("source_drift")
        if shutil.disk_usage(self.root).free < 100*GiB:
            raise ValueError("host_disk_headroom")
        if os.cpu_count()-os.getloadavg()[0] < 4:
            raise ValueError("host_cpu_headroom")

    def command(self, args, timeout=120, allowed=(0,), extra_env=None):
        self.guard()
        # Only fixed call sites in this module or approved test driver dispatch.
        work = self.root/"commands"/f"{len(self.data['commands']):04}"
        self.data["commands"].append({"path": str(work/"result.json"), "status": "STARTED"})
        self.save()
        try:
            record = execute(args, work, env={**self.env, **(extra_env or {})}, cwd=ROOT,
                             timeout=min(timeout, (datetime.fromisoformat(self.data["deadline"])-datetime.now(UTC)).total_seconds()-600),
                             guard=self.guard)
        finally:
            if (work/"result.json").exists():
                self.data["commands"][-1].update(sha256=digest(work/"result.json"), status="RECORDED")
                diagnostic = json.loads((work/"result.json").read_bytes())
                if "PermissionError" in diagnostic.get("termination_error", ""):
                    self.data["permission_stop"] = str(work/"result.json")
            self.save()
        if record["exit_code"] not in allowed:
            raise ValueError(f"command_{work.name}_exit_{record['exit_code']}")
        return work

    def output(self, args, **kwargs):
        work = self.command(args, **kwargs)
        if (work/"stdout").stat().st_size > 4*1024**2:
            raise ValueError("large_output_requires_file_processing")
        return (work/"stdout").read_text().strip()

    def baseline(self):
        ids = sorted(self.output([*DOCKER, "ps", "-aq", "--no-trunc"]).split())
        containers = [json.loads(self.output([*DOCKER, "inspect", "--format", INSPECT, i])) for i in ids]
        return {"containers": containers,
                "networks": sorted(self.output([*DOCKER, "network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"]).splitlines()),
                "images": sorted(self.output([*DOCKER, "image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"]).splitlines())}

    def init(self):
        self.data["baseline_before"] = self.baseline()
        self.data["git"] = {ref: self.output(["git", "rev-parse", ref]) for ref in ("HEAD", "MERGE_HEAD")}
        for name, args in (("host-memory", ["memory_pressure"]), ("host-size", ["sysctl", "-n", "hw.memsize"]),
                           ("disk", ["df", "-Pk", str(self.root)])):
            self.data[name] = str(self.command(args)/"result.json")
        paths = sorted(p for p in Path("/private/tmp").glob("chg301*") if p.is_dir() and not p.is_symlink())
        usage = self.output(["du", "-sk", *map(str, paths)], timeout=120)
        total = sum(int(line.split()[0])*1024 for line in usage.splitlines())
        self.data["history_bytes"] = total
        if total > 80*GiB:
            raise ValueError("history_disk_limit")
        self.save()
        print(json.dumps({"manifest": str(self.root/"manifest.json"), "containers": len(self.data["baseline_before"]["containers"]), "history_bytes": total}), flush=True)

    def capacity(self):
        # Check current available host memory, not merely installed RAM.
        pressure = self.output(["memory_pressure"])
        total_host = int(self.output(["sysctl", "-n", "hw.memsize"]))
        percent = re.search(r"System-wide memory free percentage: (\d+)%", pressure)
        if not percent or total_host*int(percent[1])/100 < 8*GiB+max(8*GiB,.2*total_host):
            raise ValueError("host_memory_headroom")
        paths = sorted(p for p in Path("/private/tmp").glob("chg301*") if p.is_dir() and not p.is_symlink())
        usage = self.output(["du", "-sk", *map(str, paths)], timeout=120)
        if sum(int(line.split()[0])*1024 for line in usage.splitlines()) > 80*GiB:
            raise ValueError("history_disk_limit")
        if sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()) > 40*GiB:
            raise ValueError("run_disk_limit")
        scan = json.loads((OLD/"frontend-runner-r3/scan.json").read_bytes())
        if scan["image_id"] != PROBE:
            raise ValueError("probe_binding")
        for r in scan["reports"].values():
            if digest(Path(r["path"])) != r["sha256"]:
                raise ValueError("probe_report_drift")
        findings = compact_sarif(Path(scan["reports"]["cves"]["path"]))
        if any(v["severity"] in {"HIGH", "CRITICAL"} for v in findings.values()):
            raise ValueError("probe_security_gate")
        info = json.loads(self.output([*DOCKER, "info", "--format", '{"cpu":{{.NCPU}},"memory":{{.MemTotal}}}']))
        ident = self.output([*DOCKER, "create", "--pull=never", "--label", LABEL+"="+self.root.name,
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "10001:10001", "--cpus", "0.1", "--memory", "32m", "--memory-swap", "32m", "--pids-limit", "16",
            "--entrypoint", "/bin/sh", PROBE, "-c", "cat /proc/meminfo; head -n 1 /proc/stat; sleep 2; head -n 1 /proc/stat; df -Pk /"])
        work = Path(tempfile.mkdtemp(prefix="capacity-", dir=self.root))
        write_new(work/"owned.json", {"id": ident, "image_id": PROBE, "label": LABEL, "run": self.root.name})
        try:
            out = self.output([*DOCKER, "start", "--attach", ident])
            if self.output([*DOCKER, "inspect", "--format", "{{.State.ExitCode}}", ident]) != "0":
                raise ValueError("capacity_probe_exit")
            memory = {m[1]: int(m[2])*1024 for line in out.splitlines() if (m := re.fullmatch(r"(MemTotal|MemAvailable):\s+(\d+) kB", line))}
            samples = [list(map(int, line.split()[1:])) for line in out.splitlines() if line.startswith("cpu ")]
            delta = [b-a for a, b in zip(*samples)]
            total = sum(delta[:8])
            busy = info["cpu"]*(total-delta[3]-delta[4])/total
            disk = next(line.split() for line in out.splitlines() if line.startswith("overlay "))
            result = {"memory_available": memory["MemAvailable"], "cpu_busy": busy,
                      "job_cpu": min(4, max(0, info["cpu"]-4-busy)),
                      "job_memory": min(8*GiB, max(0, memory["MemAvailable"]-max(8*GiB,.2*info["memory"]))),
                      "disk_free": int(disk[3])*1024}
            write_new(work/"result.json", result)
        finally:
            self.remove_container(ident, PROBE, work)
        return result

    def remove_container(self, ident, image, work):
        actual = json.loads(self.output([*DOCKER, "inspect", "--format", '{"id":{{json .Id}},"image":{{json .Image}},"labels":{{json .Config.Labels}},"running":{{.State.Running}}}', ident]))
        if (actual["id"] != ident or actual["image"] != image or actual["labels"].get(LABEL) != self.root.name
                or actual["running"] or ident in {v["id"] for v in self.data["baseline_before"]["containers"]}):
            raise ValueError("cleanup_identity_not_proven")
        write_new(work/"cleanup-dry-run.json", actual)
        self.command([*DOCKER, "rm", ident])
        write_new(work/"cleanup.json", {"removed": ident})

    def build(self, component, stage, arch, *, compiler_free=False, attempt=1):
        if component not in {"backend", "frontend"} or arch not in {"arm64", "amd64"}:
            raise ValueError("application_platform_scope")
        stages = {"backend": {"builder", "runner"}, "frontend": {"base", "deps", "builder", "prod-deps", "runner"}}
        if stage not in stages[component] or compiler_free and component != "backend":
            raise ValueError("stage_scope")
        name = f"{component}-{stage}-{arch}" + ("-qualification" if compiler_free else "")
        if attempt not in (1, 2, 3):
            raise ValueError("maximum_two_retries")
        if attempt > 1:
            name += f"-attempt{attempt}"
        work = self.root/name
        work.mkdir(mode=0o700)
        context = work/"context"
        context.mkdir(mode=0o700)
        if component == "backend":
            names = {"backend/"+n for n in ("Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock", "main.py", "migrate.py", "models.py", "connection.py")}
            names.update(str(p.relative_to(ROOT)) for p in (ROOT/"backend/app").rglob("*.py"))
        else:
            names = set(self.output(["git", "ls-files", "--", "frontend"]).splitlines())
        mapping = {}
        for src in sorted(names):
            path = ROOT/src
            if (path.is_symlink() or not path.is_file() or path.stat().st_size > 20*1024**2
                    or set(path.parts) & {"node_modules", ".next", ".next-dev", "coverage", "test-results"}
                    or path.name.startswith(".env") and not path.name.endswith(".example")):
                raise ValueError("context_input_denied")
            dest = Path(src).relative_to(component)
            (context/dest).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Context remains inside the private0700 run; preserve source modes
            # sent to Docker instead of accidentally turning public code to0600.
            parent = dest.parent
            while parent != Path("."):
                (context/parent).chmod((ROOT/component/parent).stat().st_mode & 0o777)
                parent = parent.parent
            shutil.copy2(path, context/dest)
            mapping[str(dest)] = {"source": src, "sha256": digest(path), "mode": path.stat().st_mode & 0o777}
        if compiler_free:
            recipe = context/"Dockerfile"
            text = recipe.read_text()
            for line in ("    build-essential \\\n", "    libpq-dev \\\n"):
                if text.count(line) != 1:
                    raise ValueError("qualification_recipe_contract")
                text = text.replace(line, "")
            # Generated isolated build context; repository recipe stays intact until proven.
            recipe.write_text(text)
        write_new(work/"context.json", {"sources": mapping, "recipe_sha256": digest(context/"Dockerfile"), "compiler_free_qualification": compiler_free})
        parallel = 3 if component == "frontend" and stage == "runner" else 2 if stage == "runner" else 1
        capacity = self.capacity()
        if capacity["job_cpu"] < parallel or capacity["job_memory"] < parallel*2*GiB or capacity["disk_free"] < 100*GiB:
            raise ValueError("vm_capacity_insufficient")
        now = self.baseline()
        if now["containers"] != self.data["baseline_before"]["containers"] or now["networks"] != self.data["baseline_before"]["networks"]:
            raise ValueError("protected_resource_drift")
        tag = f"nomosmart/{component}:{self.root.name}-{stage}-{arch}"+("-q" if compiler_free else "")+f"-a{attempt}"
        check = self.command([*DOCKER, "image", "inspect", "--format", "{{.Id}}", tag], allowed=(0,1))
        if json.loads((check/"result.json").read_bytes())["exit_code"] == 0:
            raise ValueError("tag_exists")
        args = [*DOCKER, "buildx", "build", "--builder", "desktop-linux", "--platform", "linux/"+arch,
                "--resource", "memory=2g", "--resource", "cpu-quota=100000", "--resource", "cpu-period=100000",
                "--provenance=false", "--load", "--progress=plain", "--no-cache", "--target", stage,
                "--tag", tag, "--label", LABEL+"="+self.root.name,
                "--iidfile", str(work/"image-id.txt"), "--metadata-file", str(work/"metadata.json"), str(context)]
        write_new(work/"intent.json", {"tag": tag, "args": args, "capacity": capacity,
                                      "maximum_parallel_steps": parallel, "aggregate_cpu": parallel, "aggregate_memory": parallel*2*GiB})
        command = self.command(args, timeout=1800)
        ident = (work/"image-id.txt").read_text().strip()
        self.data["artifacts"][name] = {"component": component, "stage": stage, "platform": "linux/"+arch,
              "id": ident, "tag": tag, "work": str(work), "build_command": str(command/"result.json"), "qualification": compiler_free}
        write_new(work/"result.json", self.data["artifacts"][name])
        self.save()
        print(json.dumps(self.data["artifacts"][name]), flush=True)

    def scan(self, name):
        artifact = self.data["artifacts"][name]
        capacity = self.capacity()
        if capacity["job_cpu"] < 2 or capacity["job_memory"] < 2*GiB:
            raise ValueError("scan_resource_headroom")
        work = Path(artifact["work"])
        reports = {}
        for mode, fmt in (("cves", "sarif"), ("sbom", "spdx")):
            path = work/(fmt+".json")
            if path.exists():
                raise ValueError("existing_report_preserved")
            self.command([*DOCKER, "scout", mode, "--platform", artifact["platform"], "--format", fmt,
                          "--output", str(path), "local://"+artifact["id"]], timeout=1200)
            reports[mode] = {"path": str(path), "sha256": digest(path)}
        findings = compact_sarif(work/"sarif.json")
        result = {"image_id": artifact["id"], "reports": reports,
                  "counts": dict(Counter(v["severity"] for v in findings.values())), "findings": findings}
        write_new(work/"scan.json", result)
        artifact["scan"] = {"path": str(work/"scan.json"), "sha256": digest(work/"scan.json"), "counts": result["counts"]}
        self.save()
        print(json.dumps({"name": name, "counts": result["counts"]}), flush=True)

    def smoke(self, name):
        artifact = self.data["artifacts"][name]
        scan = json.loads(Path(artifact["scan"]["path"]).read_bytes())
        if digest(Path(artifact["scan"]["path"])) != artifact["scan"]["sha256"] or scan["image_id"] != artifact["id"]:
            raise ValueError("cli_scan_binding")
        for report in scan["reports"].values():
            if digest(Path(report["path"])) != report["sha256"]:
                raise ValueError("cli_scan_drift")
        if any(v["severity"] in {"HIGH", "CRITICAL"} for v in scan["findings"].values()):
            raise ValueError("cli_security_gate")
        work = Path(artifact["work"])/"cli"
        work.mkdir(mode=0o700)
        capacity = self.capacity()
        if capacity["job_cpu"] < 1 or capacity["job_memory"] < GiB:
            raise ValueError("cli_capacity")
        if artifact["component"] == "backend":
            script = "python3 --version; /opt/venv/bin/python -c 'import fastapi,ssl,uvicorn,psycopg2,cryptography,sqlalchemy,ldap_filter,celery,neo4j,paramiko,markdown_it,pydantic_settings,jwt; print(fastapi.__version__); print(ssl.OPENSSL_VERSION); print(psycopg2.__version__)'; /opt/venv/bin/uvicorn --version"
            if artifact["stage"] == "builder":
                script += "; /opt/uv/bin/uv --version; /opt/uv/bin/uv pip check --python /opt/venv/bin/python --offline; ! command -v cc; ! command -v gcc; ! command -v pg_config; test ! -d /usr/include/linux"
            else:
                script += "; pandoc --version; tesseract --version; pdftotext -v; test ! -e /opt/uv/bin/uv"
        else:
            script = "node --version; node -e \"console.log(require('crypto').createHash('sha256').update('CHG301').digest('hex'))\""
            if artifact["stage"] in {"builder", "runner", "deps", "prod-deps"}:
                script += "; node node_modules/next/dist/bin/next --version"
            if artifact["stage"] == "runner":
                script += "; test ! -e /usr/local/bin/npm"
            else:
                script += "; npm --version"
        ident = self.output([*DOCKER, "create", "--pull=never", "--platform", artifact["platform"],
            "--label", LABEL+"="+self.root.name, "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "10001:10001", "--cpus", "1", "--memory", "1g",
            "--memory-swap", "1g", "--pids-limit", "64", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
            "--env", "HOME=/tmp", "--entrypoint", "/bin/sh", artifact["id"], "-ec", script])
        write_new(work/"owned.json", {"id": ident, "image_id": artifact["id"], "label": LABEL, "run": self.root.name})
        result = {"image_id": artifact["id"], "platform": artifact["platform"], "container_id": ident, "status": "BLOCKED"}
        try:
            command = self.command([*DOCKER, "start", "--attach", ident], timeout=120, allowed=(0,1))
            code = int(self.output([*DOCKER, "inspect", "--format", "{{.State.ExitCode}}", ident]))
            result.update(exit_code=code, command=str(command/"result.json"), status="PASS" if code == 0 else "FAIL")
        finally:
            self.remove_container(ident, artifact["id"], work)
            result["removed"] = True
            after = self.baseline()
            result["baseline_unchanged"] = all(after[k] == self.data["baseline_before"][k] for k in ("containers", "networks"))
            write_new(work/"result.json", result)
        artifact["cli"] = {"path": str(work/"result.json"), "sha256": digest(work/"result.json"), "status": result["status"]}
        self.save()
        print(json.dumps(result), flush=True)
        if result["status"] != "PASS" or not result["baseline_unchanged"]:
            raise ValueError("cli_failed")

    def adopt(self):
        approval()
        before = self.data["source_before"]
        now = source_manifest()
        if {p for p in now if now[p] != before[p]} != {"backend/Dockerfile"} or set(now) != set(before):
            raise ValueError("only_qualified_backend_recipe_may_change")
        old_recipe = (OLD/"backend-runner-r2/context/Dockerfile").read_bytes()
        if digest(OLD/"backend-runner-r2/context/Dockerfile") != before["backend/Dockerfile"]:
            raise ValueError("prechange_source_identity")
        expected = old_recipe.replace(b"    build-essential \\\n", b"").replace(b"    libpq-dev \\\n", b"")
        if (ROOT/"backend/Dockerfile").read_bytes() != expected:
            raise ValueError("unexpected_recipe_edit")
        for arch in ("arm64", "amd64"):
            rows = [a for a in self.data["artifacts"].values() if a["qualification"] and a["platform"] == "linux/"+arch and a.get("cli", {}).get("status") == "PASS"]
            if not rows or any(digest(Path(a["work"])/"context/Dockerfile") != now["backend/Dockerfile"] for a in rows):
                raise ValueError("clean_install_scan_cli_evidence_required")
        self.data["source_accepted"] = now
        write_new(self.root/"source-adoption.json", {"before": before["backend/Dockerfile"], "after": now["backend/Dockerfile"], "only_removed": ["build-essential", "libpq-dev"]})
        self.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("init", "capacity", "build", "scan", "smoke", "baseline", "adopt"))
    parser.add_argument("--manifest")
    parser.add_argument("--component")
    parser.add_argument("--stage")
    parser.add_argument("--arch")
    parser.add_argument("--compiler-free", action="store_true")
    parser.add_argument("--name")
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()
    if (args.operation == "init") != (args.manifest is None):
        raise ValueError("new_or_existing_run_required")
    run = Run(args.manifest)
    if args.operation == "init":
        run.init()
    elif args.operation == "capacity":
        print(json.dumps(run.capacity()))
    elif args.operation == "build":
        run.build(args.component, args.stage, args.arch, compiler_free=args.compiler_free, attempt=args.attempt)
    elif args.operation == "scan":
        run.scan(args.name)
    elif args.operation == "smoke":
        run.smoke(args.name)
    elif args.operation == "adopt":
        run.adopt()
    else:
        print(json.dumps(run.baseline()))


if __name__ == "__main__":
    main()
