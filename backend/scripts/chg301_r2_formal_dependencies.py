"""Current-plan static candidate qualification, reusing unchanged delivery checks.

This dispatcher has no build, runtime, cleanup or PR-write operation. Those need
separate capacity/safety-qualified exact commands. Historical run guards remain
unchanged; importing their pure helpers does not authorize their old runs.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from chg301_r2_delivery import Run as DeliveryRun, source_manifest
from chg301_r2_high_risk import time_guard
from chg301_r2_node_qualification import DOCKER, GiB, file_sha, write_new

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/CHG-301-R2-FORMAL-DEPENDENCY-REMEDIATION-PLAN.md"
PLAN_SHA = "1b272ee508bb9b5c0e9f2b2b0dc48734eb1f21f1f45e3b1fe5229a316e988cca"
PRE_SHA = "88548aaf15a24b7b3aac1f549b999f88ab8616c3c4d54de2847cb2c7558de8a4"
SECTION = "CHG-301 R2 Formal Installation Dependency Remediation"
APPROVAL = "核准 CHG-301 R2 正式安裝依賴修補實作計畫"
# Explicitly approved series only, not an arbitrary registry execution interface.
CANDIDATES = {
    "redis": "docker.io/library/redis:7.4.11-alpine",
    "nginx": "docker.io/library/nginx:1.30.5-alpine",
    "keycloak": "quay.io/keycloak/keycloak:26.7.3",
    "neo4j": "docker.io/library/neo4j:5.26.30-community",
    "migration": "docker.io/flyway/flyway:13.7.0-alpine",
    "postgresql": "docker.io/library/postgres:18.4-alpine",
    "rustfs": "docker.io/rustfs/rustfs:1.0.0-beta.10",
    "socat": "docker.io/alpine/socat:1.8.0.1",
    "opensearch": "docker.io/opensearchproject/opensearch:2.19.6",
    "cnpg-postgresql": "ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie",
    "cnpg-operator": "ghcr.io/cloudnative-pg/cloudnative-pg:1.30.0",
    "barman-plugin": "ghcr.io/cloudnative-pg/plugin-barman-cloud:v0.14.0",
    "barman-sidecar": "ghcr.io/cloudnative-pg/plugin-barman-cloud-sidecar:v0.14.0",
}
RUSTFS_REPAIRS = (
    ("FROM rustfs/rustfs:1.0.0-beta.10\n", "FROM rustfs/rustfs:1.0.0-beta.10@sha256:60f4f2f41ce95216f8cac676e69f9d90c0bfec458a3bc7fd7fb9b7c2452ac57a\n"),
    ("RUN apk add --no-cache su-exec\n", "\n".join((
        "RUN apk add --no-cache --upgrade " + chr(92),
        "    su-exec=0.3-r0 " + chr(92),
        "    curl=8.22.0-r0 libcurl=8.22.0-r0 " + chr(92),
        "    libssl3=3.5.8-r0 libcrypto3=3.5.8-r0", ""))),
)
FRONTEND_ANCHOR = "    openssl=3.5.8-r0 libssl3=3.5.8-r0 libcrypto3=3.5.8-r0\n"
FRONTEND_NPM_PATCH = "\n".join((
    "", "# CHG-301 R2: repair npm's own bundled dependencies, not application locks.",
    "ADD --checksum=sha256:9f58bff01604cb1b14008fef14dceb14d836a49225e45c6c2e37de3be3e707f0 https://registry.npmjs.org/npm/-/npm-11.19.1.tgz /tmp/npm-11.19.1.tgz",
    "RUN npm install --global --ignore-scripts --no-audit --no-fund /tmp/npm-11.19.1.tgz " + chr(92),
    "    && rm /tmp/npm-11.19.1.tgz " + chr(92), "    && npm cache clean --force", ""))
BACKEND_UV_PATCH = "\n".join((
    "  && printf '%s\\n' 'uv==0.11.33 --hash=sha256:36a98c68ba5c3bb59469414f54aaf00bd3134a647ca34509bc53d133ed8e0b5d --hash=sha256:71d00a28beb3924c593ba7ec248263679ae1f7c0f63a8cccc75e7d11ccb2adce --hash=sha256:9542178978b0b6f16a7ae99e55aca039f493a1edb373a15d7993eab80a28615a' " + chr(92),
    "    | /opt/uv/bin/pip install --no-cache-dir --require-hashes -r /dev/stdin " + chr(92), ""))
BACKEND_REPAIRS = tuple(("FROM ubuntu:24.04 AS " + stage + "\n",
    "FROM ubuntu:24.04@sha256:69cecf4bbf72d2d44a9eef1b71fb98c7fb973d78af11399deccef19beb008ad9 AS " + stage + "\n")
    for stage in ("builder", "runner")) + (("  && /opt/uv/bin/pip install --no-cache-dir uv==0.11.8 " + chr(92) + "\n", BACKEND_UV_PATCH),)
SOURCE_REPAIRS = {"deploy/rustfs/Dockerfile": RUSTFS_REPAIRS,
                  "backend/Dockerfile": BACKEND_REPAIRS,
                  "frontend/Dockerfile": ((FRONTEND_ANCHOR, FRONTEND_ANCHOR + FRONTEND_NPM_PATCH),)}


def source_guard(before):
    """Accept only the three approved dependency recipes' exact replacements.

    Reverse the replacements and hash the entire original file. This cannot
    conceal other edits, additions, removals or a changed Secret helper.
    """
    actual = source_manifest()
    if actual == before:
        return actual
    changed = {p for p in actual if actual[p] != before.get(p)}
    if set(actual) != set(before) or not changed.issubset(SOURCE_REPAIRS):
        raise ValueError("product_source_drift")
    for path in changed:
        original = (ROOT / path).read_text()
        for old, new in reversed(SOURCE_REPAIRS[path]):
            if original.count(new) != 1:
                raise ValueError("unapproved_recipe_change")
            original = original.replace(new, old, 1)
        if hashlib.sha256(original.encode()).hexdigest() != before[path]:
            raise ValueError("product_source_drift")
    return actual


def approval_guard():
    active = (ROOT / "DEVELOPMENT_PLAN.md").read_text().split("\n## ")[1]
    if (file_sha(PLAN) != PLAN_SHA or active.splitlines()[0] != SECTION
            or any(s not in active for s in (APPROVAL, PRE_SHA, "Gate 4 approval: APPROVED."))):
        raise ValueError("formal_dependency_current_approval_required")


def candidate_manifests(raw: bytes) -> dict[str, str]:
    """Require exact platform children, not a tag or assumed host architecture."""
    value = json.loads(raw)
    result = {}
    for arch in ("arm64", "amd64"):
        rows = [m for m in value.get("manifests", [])
                if m.get("platform", {}).get("os") == "linux"
                and m.get("platform", {}).get("architecture") == arch]
        if len(rows) == 1:
            result[arch] = rows[0]["digest"]
        elif len(rows) > 1:
            raise ValueError("ambiguous_platform")
    if "arm64" not in result:
        raise ValueError("arm64_platform_not_bound")
    return result


class Run(DeliveryRun):
    """Reuse static command allowlist; do not invoke the historical constructor."""

    def __init__(self, manifest: str | None):
        approval_guard()
        os.umask(0o077)
        if manifest is None:
            self.root = Path(tempfile.mkdtemp(prefix="chg301-r2-formal-", dir="/private/tmp"))
            now = datetime.now(UTC)
            self.data = {"plan_sha256": PLAN_SHA, "started_at": now.isoformat(),
                "deadline": (now + timedelta(hours=6)).isoformat(), "owner_uid": os.getuid(),
                "inode": self.root.stat().st_ino, "commands": [], "phases": [], "scans": [],
                "targets": [], "source": source_manifest(), "failures": [],
                "runtime_mutations": 0, "pr_writes": 0, "product_upgrades": []}
        else:
            path = Path(manifest)
            self.root = path.parent
            if (self.root.parent != Path("/private/tmp") or not self.root.name.startswith("chg301-r2-formal-")
                    or path.name != "manifest.json" or path.is_symlink() or self.root.is_symlink()):
                raise ValueError("run_path_identity")
            self.data = json.loads(path.read_bytes())
            if (self.data["inode"] != self.root.stat().st_ino or self.data["owner_uid"] != os.getuid()
                    or self.data["plan_sha256"] != PLAN_SHA or "closeout" in self.data["phases"]):
                raise ValueError("run_identity_or_closed")
        for name in ("raw", "analysis", "scanner-cache"):
            (self.root / name).mkdir(exist_ok=True, mode=0o700)
        self.env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        self.env.update(PYTHONDONTWRITEBYTECODE="1", DOCKER_SCOUT_CACHE_DIR=str(self.root / "scanner-cache"),
            DOCKER_CLI_HINTS="false", COMPOSE_DISABLE_ENV_FILE="1", COMPOSE_ENV_FILES="/dev/null")
        self.save()

    def guard(self):
        approval_guard()
        time_guard(self.data, datetime.now(UTC))
        source_guard(self.data["source"])
        if shutil.disk_usage(self.root).free < 100 * GiB:
            raise ValueError("disk_headroom")
        if os.cpu_count() - os.getloadavg()[0] < 4:
            raise ValueError("host_cpu_headroom")
        if sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()) > 40 * GiB:
            raise ValueError("run_disk_limit")

    def candidates(self, name: str):
        if any(t["name"] == name for t in self.data["targets"]):
            raise ValueError("candidate_already_recorded")
        reference = CANDIDATES[name]
        raw = self.command([*DOCKER, "buildx", "imagetools", "inspect", reference, "--raw"], timeout=120)
        platforms = candidate_manifests(raw)
        repo = reference.rsplit(":", 1)[0]
        self.data["targets"].append({"name": name, "declared": reference,
            "scan_reference": "registry://" + repo + "@" + platforms["arm64"],
            "manifest_digest": platforms["arm64"], "platform_children": platforms,
            "source_bound": False, "qualification": "OFFICIAL_BASE_CANDIDATE_NOT_ADOPTED"})
        write_new(self.root / "analysis" / (name + ".manifest.json"), raw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "candidate", "scan", "render", "closeout"))
    parser.add_argument("--manifest")
    parser.add_argument("--name", choices=tuple(CANDIDATES))
    args = parser.parse_args()
    if (args.action == "preflight") != (args.manifest is None):
        parser.error("fresh preflight only; other actions require the existing exact manifest")
    if args.action in {"candidate", "scan"} and args.name is None:
        parser.error("candidate name required")
    run = Run(args.manifest)
    try:
        if args.action == "candidate":
            run.candidates(args.name)
        elif args.action == "scan":
            run.scan(args.name)
        elif args.action == "render":
            run.inventory()
            run.render()
        else:
            getattr(run, args.action)()
        run.data["phases"].append(args.action + (":" + args.name if args.name else ""))
    except Exception as exc:
        run.data["failures"].append({"action": args.action, "name": args.name,
                                     "type": type(exc).__name__, "reason": str(exc)})
        raise
    finally:
        run.data["tool_sha256"] = file_sha(Path(__file__))
        run.save()
        print(json.dumps({"manifest": str(run.root / "manifest.json"), "phases": run.data["phases"]}), flush=True)


if __name__ == "__main__":
    main()
