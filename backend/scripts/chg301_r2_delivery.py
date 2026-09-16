"""Bounded delivery-artifact inventory/scanning; no build/runtime/Git write dispatch.

Reuse existing SARIF and process-policy helpers, not retired execution authority.
Source/image findings are evidence only, never permission to upgrade dependencies.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import certifi
import yaml

from chg301_r2_high_risk import INSPECT, PR_FIELDS, raw_findings, time_guard
from chg301_r2_ingress import GIT_BASE
from chg301_r2_node_qualification import DOCKER, GiB, NoRedirect, file_sha, process_usage, write_new

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/CHG-301-R2-DELIVERY-SECURITY-PLAN.md"
PLAN_SHA = "3db7c0c206f3303f8458aaad7a64c23f7b67d54036daececdf86ce381e52eadc"
PRE_SHA = "f73b28d6a30d4fc7581a91804b89e11f40065dc240b4d2d997a8358e2f43d1f0"
SECTION = "CHG-301 R2 Delivery And Installation Dependency Security"
APPROVAL = "核准 CHG-301 R2 交付程式與正式安裝依賴安全修訂計畫"
PYTHON = Path("/private/tmp/chg301-r2-pytest-layr63SP/venv/bin/python")
BANDIT = Path("/private/tmp/chg301-r2-security-0utu1kq_/scanner-venv/bin/bandit")
PLATFORM = "linux/arm64"
LOCAL_CANDIDATES = {
    "backend": "nomosmart/backend:0.1.0-chg300",
    "frontend": "nomosmart/frontend:0.1.0-chg299-v049",
    "migration": "nomosmart/migrations:chg301-test",
    "postgresql": "nomosmart/postgresql:chg301-test",
    "rustfs": "nomosmart/rustfs:chg301-test",
    "keycloak": "nomosmart/keycloak:26.0.8",
    "opensearch-helm": "nomosmart/opensearch:2.19.6-repository-s3",
}
CODE_ROOTS = ("backend/app", "frontend/src", "deploy/installer", "deploy/package",
              "deploy/release", "deploy/helm/nomosmart", "deploy/docker", "sql/migrations")
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".sh", ".yaml", ".yml", ".json", ".sql", ".toml", ".template"}


def approval_guard() -> None:
    active = (ROOT / "DEVELOPMENT_PLAN.md").read_text().split("\n## ")[1]
    if (file_sha(PLAN) != PLAN_SHA or active.splitlines()[0] != SECTION
            or any(s not in active for s in (APPROVAL, PRE_SHA, "Gate 4 approval: APPROVED."))):
        raise ValueError("delivery_current_approval_required")


def source_manifest() -> dict[str, str]:
    names = {"docker-compose.yml", "backend/Dockerfile", "frontend/Dockerfile",
             "backend/pyproject.toml", "backend/uv.lock", "frontend/package.json", "frontend/package-lock.json"}
    names.update(str(p.relative_to(ROOT)) for p in (ROOT / "deploy").glob("*/Dockerfile*"))
    for directory in CODE_ROOTS:
        for path in (ROOT / directory).rglob("*"):
            if set(path.parts) & {"generated", "node_modules", ".next", "__pycache__", ".venv", "venv", "tests", "evidence", "state"}:
                continue
            if path.is_file() and (path.suffix in SUFFIXES or not path.suffix):
                if path.name.startswith(".") or path.name.endswith(".env"):
                    continue
                names.add(str(path.relative_to(ROOT)))
    result = {}
    for name in sorted(names):
        path = ROOT / name
        if path.is_symlink() or ROOT not in path.resolve().parents:
            raise ValueError("source_path_identity")
        result[name] = file_sha(path)
    return result


def classify(uses: list[str]) -> str:
    known = {"delivery", "install", "build", "external", "unused-test"}
    if not uses or any(use not in known for use in uses):
        return "UNRESOLVED"
    if set(uses) & {"delivery", "install", "build"}:
        return "IN_SCOPE"
    if set(uses) == {"unused-test"}:
        return "DEFERRED_TEST_INFRA"
    return "EXTERNAL_PREREQUISITE" if set(uses) == {"external"} else "UNRESOLVED"


def delivery_gate(artifacts: list[dict]) -> None:
    if not artifacts or not any(classify(a["uses"]) == "IN_SCOPE" for a in artifacts):
        raise ValueError("missing_delivery_inventory")
    for row in artifacts:
        state = classify(row["uses"])
        if state == "UNRESOLVED":
            raise ValueError("unknown_artifact_use")
        if state == "DEFERRED_TEST_INFRA":
            if row.get("enabled") is not False:
                raise ValueError("deferred_infra_enabled_or_unknown")
            continue
        if state == "EXTERNAL_PREREQUISITE":
            if not row.get("owner") or not row.get("prerequisites"):
                raise ValueError("external_contract_missing")
            continue
        if not row.get("source_bound") or not row.get("complete_scan"):
            raise ValueError("delivery_evidence_incomplete")
        if any(f["severity"] in {"HIGH", "CRITICAL"} and f["state"] != "FIXED" for f in row["findings"]):
            raise ValueError("delivery_high_requires_resolution")


class Run:
    def __init__(self, manifest: str | None):
        approval_guard()
        os.umask(0o077)
        if manifest is None:
            self.root = Path(tempfile.mkdtemp(prefix="chg301-r2-delivery-", dir="/private/tmp"))
            now = datetime.now(UTC)
            self.data = {"plan_sha256": PLAN_SHA, "started_at": now.isoformat(),
                         "deadline": (now + timedelta(hours=6)).isoformat(), "owner_uid": os.getuid(),
                         "inode": self.root.stat().st_ino, "commands": [], "phases": [], "scans": [],
                         "source": source_manifest(), "failures": [], "runtime_mutations": 0, "pr_writes": 0}
        else:
            self.root = Path(manifest).parent
            if (self.root.parent != Path("/private/tmp") or not self.root.name.startswith("chg301-r2-delivery-")
                    or Path(manifest).name != "manifest.json" or self.root.is_symlink() or Path(manifest).is_symlink()):
                raise ValueError("run_path_identity")
            self.data = json.loads(Path(manifest).read_bytes())
            if (self.data["inode"] != self.root.stat().st_ino or self.data["owner_uid"] != os.getuid()
                    or self.data["plan_sha256"] != PLAN_SHA):
                raise ValueError("run_identity")
        for name in ("raw", "analysis", "scanner-cache"):
            (self.root / name).mkdir(exist_ok=True, mode=0o700)
        self.env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        self.env.update(PYTHONDONTWRITEBYTECODE="1", DOCKER_SCOUT_CACHE_DIR=str(self.root / "scanner-cache"),
                        DOCKER_CLI_HINTS="false", COMPOSE_DISABLE_ENV_FILE="1", COMPOSE_ENV_FILES="/dev/null")
        self.save()

    def save(self):
        path = self.root / "manifest-next.json"
        write_new(path, self.data)
        path.replace(self.root / "manifest.json")

    def guard(self):
        approval_guard()
        time_guard(self.data, datetime.now(UTC))
        if source_manifest() != self.data["source"]:
            raise ValueError("product_source_drift")
        if shutil.disk_usage(self.root).free < 100 * GiB:
            raise ValueError("disk_headroom")
        if os.cpu_count() - os.getloadavg()[0] < 4:
            raise ValueError("host_cpu_headroom")
        if sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()) > 40 * GiB:
            raise ValueError("run_disk_limit")

    def command(self, args: list[str], timeout=120, allowed=(0,), env_extra=None):
        self.guard()
        # Only this module's explicit static commands may use the dispatcher.
        if args[:3] == DOCKER:
            if args[3] not in {"ps", "inspect", "image", "network", "info", "scout", "buildx", "compose"}:
                raise ValueError("docker_mutation_forbidden")
            if args[3] in {"image", "network"} and args[4] not in {"ls", "inspect"}:
                raise ValueError("docker_mutation_forbidden")
            if args[3] == "buildx" and args[4:6] != ["imagetools", "inspect"]:
                raise ValueError("docker_build_forbidden")
            if args[3] == "scout" and args[4] not in {"version", "cves", "sbom"}:
                raise ValueError("scout_mutation_forbidden")
            if args[3] == "compose" and args[4:6] != ["--profile", "*"]:
                raise ValueError("compose_runtime_forbidden")
            if args[3] == "compose" and args[6:] != ["config", "--no-env-resolution", "--quiet"]:
                raise ValueError("compose_runtime_forbidden")
        elif args[0] not in {"git", "gh", "memory_pressure", "sysctl", "du", "helm", str(PYTHON), str(BANDIT)}:
            raise ValueError("unknown_tool")
        if args[0] == "git" and args[1] not in {"rev-parse", "diff", "ls-files", "branch"}:
            raise ValueError("git_write_forbidden")
        if args[0] == "gh" and not (args[1:4] == ["pr", "view", "1"] or args[1:3] == ["api", "repos/crispkid/Nomosmart/commits/main"]):
            raise ValueError("github_write_forbidden")
        if args[0] == "helm" and args[1] not in {"template", "version"}:
            raise ValueError("helm_write_forbidden")
        env = {**self.env, **(env_extra or {})}
        if args[0] == "helm":
            env.update(KUBECONFIG=str(self.root / "no-kube"), HELM_PLUGINS=str(self.root / "no-plugins"),
                       HELM_CONFIG_HOME=str(self.root / "helm-config"), HELM_CACHE_HOME=str(self.root / "helm-cache"))
        index = len(self.data["commands"])
        out, err = (self.root / "raw" / f"{index:03}.{suffix}" for suffix in ("stdout", "stderr"))
        entry = {"args": args, "started_at": datetime.now(UTC).isoformat()}
        self.data["commands"].append(entry)
        self.save()
        with out.open("xb") as o, err.open("xb") as e:
            proc = subprocess.Popen(args, cwd=ROOT, env=env, stdout=o, stderr=e, start_new_session=True)
            until = time.monotonic() + min(timeout, (datetime.fromisoformat(self.data["deadline"]) - datetime.now(UTC)).total_seconds() - 600)
            try:
                while proc.poll() is None:
                    if process_usage(os.getpid())["rss_bytes"] > 8 * GiB or time.monotonic() >= until:
                        raise ValueError("host_process_resource_or_time_limit")
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
            except BaseException:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                entry["interrupted"] = True
                self.save()
                raise
        entry.update(exit_code=proc.returncode, stdout_sha256=file_sha(out), stderr_sha256=file_sha(err),
                     finished_at=datetime.now(UTC).isoformat())
        self.save()
        if proc.returncode not in allowed:
            raise ValueError(f"command_{index}_exit_{proc.returncode}")
        return out.read_bytes()

    def baseline(self):
        ids = self.command([*DOCKER, "ps", "-aq", "--no-trunc"]).decode().split()
        return {"containers": [json.loads(self.command([*DOCKER, "inspect", "--format", INSPECT, i])) for i in sorted(ids)],
                "images": sorted(self.command([*DOCKER, "image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"]).decode().splitlines()),
                "networks": sorted(self.command([*DOCKER, "network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"]).decode().splitlines())}

    def preflight(self):
        if "preflight" in self.data["phases"]:
            raise ValueError("preflight_cannot_reset")
        if self.command(["git", "rev-parse", "HEAD", "MERGE_HEAD"]).decode().split() != GIT_BASE:
            raise ValueError("git_parent_drift")
        if self.command(["git", "ls-files", "--unmerged"]).strip():
            raise ValueError("git_conflict")
        self.data["baseline_before"] = self.baseline()
        self.data["pr_before"] = json.loads(self.command(["gh", "pr", "view", "1", "--repo", "crispkid/Nomosmart", "--json", PR_FIELDS]))
        self.data["main_before"] = self.command(["gh", "api", "repos/crispkid/Nomosmart/commits/main", "--jq", ".sha"]).decode().strip()
        if self.data["pr_before"]["headRefOid"] != GIT_BASE[0] or self.data["main_before"] != GIT_BASE[1]:
            raise ValueError("remote_drift")
        pressure = self.command(["memory_pressure", "-Q"]).decode()
        total = int(self.command(["sysctl", "-n", "hw.memsize"]).strip())
        free = int(re.search(r"memory free percentage: (\d+)%", pressure)[1])
        if free < 20 or total * free / 100 < 16 * GiB:
            raise ValueError("host_memory_headroom")
        self.data["host"] = {"pressure": pressure, "total_ram": total, "cpus": os.cpu_count(), "load": list(os.getloadavg())}
        self.data["vm_totals"] = json.loads(self.command([*DOCKER, "info", "--format", '{"cpu":{{.NCPU}},"memory":{{.MemTotal}}}']))
        self.data["vm_build_gate"] = "AVAILABLE_MEMORY_AND_ENFORCED_LIMITS_NOT_VERIFIED"
        self.data["scout_version"] = self.command([*DOCKER, "scout", "version"]).decode()
        self.data["tools"] = {name: {"path": shutil.which(name), "sha256": file_sha(Path(shutil.which(name)).resolve())}
                              for name in ("docker", "helm", "gh")}

    def inventory(self):
        rows = []
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        for name, service in compose["services"].items():
            image = service.get("image", "")
            image = re.sub(r"\$\{[A-Z_]+:-([^}]+)}", r"\1", image)
            rows.append({"use": "compose", "name": name, "image": image,
                         "profiles": service.get("profiles", []), "build": service.get("build"),
                         "source": "docker-compose.yml", "classification": "IN_SCOPE_INSTALL"})
        for path in sorted((ROOT / "deploy/helm/nomosmart").glob("values*.yaml")):
            def walk(value, parts):
                if isinstance(value, dict):
                    if "repository" in value and "tag" in value:
                        rows.append({"use": "helm-values", "name": ".".join(parts),
                                     "image": value["repository"] + ":" + str(value["tag"]),
                                     "digest_override": value.get("digest"), "source": str(path.relative_to(ROOT)),
                                     "classification": "IN_SCOPE_INSTALL"})
                    for key, child in value.items():
                        walk(child, [*parts, key])
            walk(yaml.safe_load(path.read_text()), [])
        for filename in ("cloudnativepg.py", "barman_cloud.py"):
            path = ROOT / "deploy/installer/nomosmart_installer" / filename
            for node in ast.parse(path.read_text()).body:
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in {"OPERATOR_IMAGE", "PLUGIN_IMAGE", "SIDECAR_IMAGE", "MANIFEST_URL", "MANIFEST_SHA256"}:
                    rows.append({"use": "installer", "name": node.target.id, "value": ast.literal_eval(node.value),
                                 "source": str(path.relative_to(ROOT)), "classification": "IN_SCOPE_INSTALL"})
        for path in [ROOT / "backend/Dockerfile", ROOT / "frontend/Dockerfile", *sorted((ROOT / "deploy").glob("*/Dockerfile"))]:
            for line in path.read_text().splitlines():
                if line.startswith(("FROM ", "ARG ")):
                    rows.append({"use": "build-input", "declaration": line, "source": str(path.relative_to(ROOT)),
                                 "classification": "BUILD_INPUT"})
        write_new(self.root / "analysis/declared-uses.json", rows)
        self.data["declared_uses"] = rows
        self.data["closure_status"] = "PARTIAL_RENDER_AND_DYNAMIC_PATH_REVIEW_REQUIRED"

    def render(self):
        """Offline checked-in examples only; never read live values or operator env."""
        sys.path.insert(0, str(ROOT / "deploy/installer"))
        from nomosmart_installer.config import load_config
        records = []

        def images(value, path, result):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"image", "imageName"} and isinstance(child, str):
                        result.append({"path": ".".join([*path, key]), "image": child})
                    else:
                        images(child, [*path, key], result)
            elif isinstance(value, list):
                for number, child in enumerate(value):
                    images(child, [*path, str(number)], result)

        def render_one(name, args):
            raw = self.command(["helm", "template", "delivery-inventory", "deploy/helm/nomosmart", *args])
            path = self.root / "analysis" / (name + ".yaml")
            write_new(path, raw)
            for doc in yaml.safe_load_all(raw):
                if not doc:
                    continue
                found = []
                images(doc, [], found)
                for image in found:
                    records.append({"case": name, "kind": doc["kind"], "name": doc["metadata"]["name"],
                                    **image, "render_sha256": file_sha(path)})

        render_one("chart-default", [])
        for example in sorted((ROOT / "deploy/installer").glob("nomosmart-install*.example.toml")):
            config = load_config(example)
            for stage in ("foundation", "application", "operational"):
                name = example.stem + "-" + stage
                values = config.generated_helm_values(stage)
                path = self.root / "analysis" / (name + ".json")
                write_new(path, values)
                args = [item for source in config.application.values for item in ("-f", str(source))]
                render_one(name, [*args, "-f", str(path)])
            if config.deployment_profile == "bundled":
                render_one(example.stem + "-finalize", [*args, "-f", str(path), "--set",
                    "installer.deploymentStage=application,bootstrap.deploymentPhase=onboarding,bootstrap.finalize.enabled=true,bootstrap.evidenceRelease=delivery-prior"])
        self.command([*DOCKER, "compose", "--profile", "*", "config", "--no-env-resolution", "--quiet"],
                     env_extra={"COMPOSE_FILE": str(ROOT / "docker-compose.yml")})
        write_new(self.root / "analysis/rendered-images.json", records)
        self.data["rendered_images"] = records
        self.data["closure_status"] = "RENDERED_EXAMPLES_DYNAMIC_MANIFEST_AND_FINAL_ARTIFACT_BINDING_PENDING"

    def targets(self):
        targets = []
        for name, tag in LOCAL_CANDIDATES.items():
            try:
                image = json.loads(self.command([*DOCKER, "image", "inspect", "--format", '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}},"digests":{{json .RepoDigests}}}', tag]))
                targets.append({"name": name, "declared": tag, "scan_reference": "local://" + image["id"],
                                "identity": image, "source_bound": False,
                                "qualification": "EXISTING_CANDIDATE_SOURCE_BINDING_PENDING"})
            except ValueError as exc:
                self.data["failures"].append({"target": name, "error": str(exc)})
        remote = {"nginx": "docker.io/library/nginx:1.27.5-alpine", "redis": "docker.io/library/redis:7.4.2-alpine",
                  "neo4j": "docker.io/library/neo4j:5.26.4-community", "opensearch-compose": "docker.io/opensearchproject/opensearch:2.19.1",
                  "socat": "docker.io/alpine/socat:1.8.0.1"}
        for row in self.data["declared_uses"]:
            if row["use"] == "installer" and row["name"] in {"OPERATOR_IMAGE", "PLUGIN_IMAGE", "SIDECAR_IMAGE"}:
                remote[row["name"].lower()] = row["value"]
            if row["use"] == "helm-values" and row["name"] == "postgresql.cluster.image":
                remote["cnpg-postgresql"] = row["image"]
        for name, ref in remote.items():
            try:
                raw = self.command([*DOCKER, "buildx", "imagetools", "inspect", ref, "--raw"])
                index = json.loads(raw)
                choices = [m for m in index.get("manifests", []) if m.get("platform", {}).get("os") == "linux" and m.get("platform", {}).get("architecture") == "arm64"]
                if len(choices) == 1:
                    digest = choices[0]["digest"]
                elif "config" in index and "layers" in index:
                    import hashlib
                    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
                else:
                    raise ValueError("arm64_manifest_missing_or_ambiguous")
                repo = ref.split("@")[0].rsplit(":", 1)[0] if ":" in ref.split("@")[0].split("/")[-1] else ref.split("@")[0]
                targets.append({"name": name, "declared": ref, "scan_reference": "registry://" + repo + "@" + digest,
                                "manifest_digest": digest, "source_bound": True, "qualification": "DECLARED_THIRD_PARTY_ARM64"})
            except ValueError as exc:
                self.data["failures"].append({"target": name, "error": str(exc)})
        self.data["targets"] = targets
        write_new(self.root / "analysis/scan-targets.json", targets)

    def scan(self, name):
        # Host-only static inspection: do not pretend VM totals prove VM free RAM.
        pressure = self.command(["memory_pressure", "-Q"]).decode()
        total = int(self.command(["sysctl", "-n", "hw.memsize"]).strip())
        free = int(re.search(r"memory free percentage: (\d+)%", pressure)[1])
        if free < 20 or total * free / 100 < 16 * GiB:
            raise ValueError("host_memory_headroom")
        historical = sorted(str(p) for p in Path("/private/tmp").glob("chg301-*")
                            if p.is_dir() and not p.is_symlink())
        disk = self.command(["du", "-sk", *historical], timeout=120)
        historical_bytes = sum(int(line.split()[0]) * 1024 for line in disk.decode().splitlines())
        self.data["historical_artifact_bytes"] = historical_bytes
        if historical_bytes > 80 * GiB:
            raise ValueError("historical_disk_limit")
        target = next(t for t in self.data["targets"] if t["name"] == name)
        reports = {}
        for mode, fmt in (("cves", "sarif"), ("sbom", "spdx")):
            path = self.root / "analysis" / f"{name}.{fmt}.json"
            if path.exists():
                raise ValueError("existing_scan_not_overwritten")
            self.command([*DOCKER, "scout", mode, "--platform", PLATFORM, "--format", fmt,
                          "--output", str(path), target["scan_reference"]], timeout=1200)
            reports[mode] = {"path": str(path), "sha256": file_sha(path)}
        findings = raw_findings(json.loads(Path(reports["cves"]["path"]).read_bytes()))
        summary = {"name": name, "target": target, "reports": reports, "findings": findings,
                   "counts": dict(Counter(f["severity"] for f in findings.values())),
                   "status": "FINDINGS_REQUIRE_REVIEW" if any(f["severity"] in {"HIGH", "CRITICAL"} for f in findings.values()) else "NO_RAW_HIGH_CRITICAL",
                   "not_source_or_release_acceptance": True}
        self.data["scans"].append(summary)
        print(json.dumps({"scan": name, "counts": summary["counts"], "status": summary["status"]}), flush=True)

    def closeout(self):
        self.data["baseline_after"] = self.baseline()
        self.data["baseline_unchanged"] = self.data["baseline_before"] == self.data["baseline_after"]
        self.data["source_unchanged"] = self.data["source"] == source_manifest()
        if not self.data["baseline_unchanged"]:
            raise ValueError("docker_baseline_drift")

    def audit(self):
        raw = self.command([str(PYTHON), "backend/scripts/chg301_r2_security.py"], timeout=1200,
                           allowed=(0, 1), env_extra={"CHG301_R2_ISOLATED": "1"})
        summary = json.loads(raw.decode().splitlines()[-1])
        path = Path(summary["evidence"])
        if path.parent.parent != Path("/private/tmp") or not path.parent.name.startswith("chg301-r2-security-"):
            raise ValueError("audit_evidence_identity")
        self.data["source_audit"] = {**summary, "sha256": file_sha(path),
                                     "tool_sha256": file_sha(ROOT / "backend/scripts/chg301_r2_security.py")}
        print(json.dumps(summary), flush=True)

    def local_audit(self):
        """No registry/audit service call: local AST and exact historical hash check."""
        import chg301_r2_security as security
        prior = Path("/private/tmp/chg301-r2-security-0utu1kq_/result.json")
        if file_sha(prior) != "bd648f6c323e238b84faf886e1c29a1f09bb2c3278d224275825899f7485786a":
            raise ValueError("historical_audit_identity")
        old = json.loads(prior.read_bytes())
        now = {name: file_sha(ROOT / name) for name in security.sources()}
        if old["source_sha256"] != now:
            raise ValueError("historical_audit_source_mismatch")
        report = self.root / "analysis/local-bandit.json"
        if report.exists():
            raise ValueError("existing_scan_not_overwritten")
        version = self.command([str(BANDIT), "--version"]).decode().strip()
        self.command([str(BANDIT), "-r", *security.CODE_DIRS, "--ignore-nosec", "-f", "json", "-o", str(report)],
                     timeout=1200, allowed=(0, 1))
        data = json.loads(report.read_bytes())
        if data.get("errors") or not data["metrics"]["_totals"]["loc"]:
            raise ValueError("incomplete_local_bandit")
        assessment = security.assess_static_risk(data["results"], now, (ROOT / security.RISK_PATH).read_bytes())
        self.data["local_audit"] = {"historical_path": str(prior), "historical_sha256": file_sha(prior),
            "historical_finished_at": old["finished_at"], "same_source_files": len(now),
            "historical_dependency_checks": {k: v for k, v in old["checks"].items() if k != "bandit"},
            "fresh_online_audit": "BLOCKED_PERMISSION_DEPENDENCY_METADATA_EGRESS_REQUIRES_EXPLICIT_CONSENT",
            "bandit_version": version, "bandit_path": str(report), "bandit_sha256": file_sha(report),
            "bandit_counts": dict(Counter(f["issue_severity"] for f in data["results"])),
            "assessment": assessment, "not_release_acceptance": True}
        print(json.dumps({"local_audit": assessment["status"], "same_source_files": len(now),
                          "fresh_online_audit": "BLOCKED_PERMISSION"}), flush=True)

    def manifests(self):
        """Download only the two public, hash-pinned installer manifests; no apply."""
        self.guard()
        sys.path.insert(0, str(ROOT / "deploy/installer"))
        from nomosmart_installer import cloudnativepg as cnpg, barman_cloud as barman
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=certifi.where())))
        entries = []
        for name, module in (("cnpg", cnpg), ("barman", barman)):
            url = module.MANIFEST_URL
            for attempt in range(2):
                parts = urllib.parse.urlsplit(url)
                if parts.scheme != "https" or parts.hostname not in {
                    "raw.githubusercontent.com", "github.com", "release-assets.githubusercontent.com"}:
                    raise ValueError("manifest_download_destination")
                try:
                    with opener.open(urllib.request.Request(url), timeout=60) as response:
                        payload = response.read(2 * 1024 * 1024 + 1)
                    break
                except urllib.error.HTTPError as exc:
                    if attempt or exc.code not in {301, 302, 303, 307, 308}:
                        raise
                    url = exc.headers["Location"]
            if len(payload) > 2 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != module.MANIFEST_SHA256:
                raise ValueError("official_manifest_digest")
            rendered = (payload.decode().replace(cnpg.UPSTREAM_IMAGE, cnpg.OPERATOR_IMAGE)
                        if name == "cnpg" else barman.BarmanCloud._pin_manifest(payload))
            if hashlib.sha256(rendered.encode()).hexdigest() != module.RENDERED_MANIFEST_SHA256:
                raise ValueError("pinned_manifest_digest")
            write_new(self.root / "analysis" / f"{name}-upstream.yaml", payload)
            write_new(self.root / "analysis" / f"{name}-pinned.yaml", rendered.encode())
            entries.append({"name": name, "url": module.MANIFEST_URL, "sha256": module.MANIFEST_SHA256,
                            "rendered_sha256": module.RENDERED_MANIFEST_SHA256,
                            "image": cnpg.OPERATOR_IMAGE if name == "cnpg" else barman.PLUGIN_IMAGE,
                            "sidecar": barman.SIDECAR_IMAGE if name == "barman" else None})
        self.data["official_manifests"] = entries
        self.data["closure_status"] = "DECLARATIONS_AND_EXAMPLE_ROUTES_CHECKED_FINAL_ARTIFACTS_AND_BUILD_INPUTS_PENDING"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("preflight", "inventory", "render", "targets", "scan", "audit", "local_audit", "manifests", "closeout"))
    parser.add_argument("--manifest")
    parser.add_argument("--name")
    args = parser.parse_args()
    if not args.manifest and args.phase != "preflight":
        parser.error("existing manifest required")
    run = Run(args.manifest)
    print(json.dumps({"root": str(run.root), "phase": args.phase}), flush=True)
    try:
        if args.phase == "scan":
            run.scan(args.name)
        else:
            getattr(run, args.phase)()
        run.data["phases"].append(args.phase + (":" + args.name if args.name else ""))
    except Exception as exc:
        run.data["failures"].append({"phase": args.phase, "error": str(exc), "type": type(exc).__name__})
        raise
    finally:
        run.save()


if __name__ == "__main__":
    main()
