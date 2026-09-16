"""Registry-only scan of the official kind0.32 default ARM64 node candidate.

No pull/create/run, cluster access, application settings, or image changes.
Only public image metadata/PURLs are sent through the configured Scout tool.
"""
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile

from chg301_r2_ingress import (
    ACCEPTANCE_PATH, ACCEPTED_BUILD, BATCH_DEADLINE, DOCKER, GIT_BASE, ROOT,
    applicability_guard, assess_sarif, digest, save, source_snapshot,
)

NODE = "docker.io/kindest/node:v1.36.1"
NODE_INDEX = "sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5"
OFFICIAL_SOURCE = "https://github.com/kubernetes-sigs/kind/releases/tag/v0.32.0"


def node_identity(value):
    rows = [v for v in value.get("manifests", []) if v.get("platform") == {"architecture": "arm64", "os": "linux"}]
    if value.get("digest") != NODE_INDEX or len(rows) != 1:
        raise ValueError("official_node_identity")
    return rows[0]["digest"]


def main():
    if os.environ.get("CHG301_R2_ISOLATED") != "1":
        raise SystemExit("explicit isolated opt-in required")
    applicability_guard(ACCEPTANCE_PATH.read_bytes(), (ROOT / "DEVELOPMENT_PLAN.md").read_text(),
                        (ACCEPTED_BUILD / "all-severity.sarif.json").read_bytes(), datetime.now(UTC))
    os.umask(0o077)
    work = Path(tempfile.mkdtemp(prefix="chg301-r2-node-scan-", dir="/private/tmp"))
    result = {"scope": "Original R2 registry-only node candidate", "status": "BLOCKED_ERROR",
              "official_source": OFFICIAL_SOURCE, "image": NODE, "index_digest": NODE_INDEX,
              "started_at": datetime.now(UTC).isoformat(), "commands": [], "container_executions": 0,
              "kubernetes_operations": 0, "provider_calls": 0, "pr_operations": 0,
              "accepted_findings": [], "database_version": "Not exposed by Scout; query timestamp recorded"}
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}

    def command(args, timeout=120):
        remaining = (datetime.fromisoformat(BATCH_DEADLINE) - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise ValueError("original_batch_deadline_exceeded")
        started = datetime.now(UTC).isoformat()
        proc = subprocess.run(args, cwd=work, env=env, capture_output=True, timeout=min(timeout, remaining))
        ordinal = len(result["commands"])
        save(work / f"{ordinal:02d}.stdout", proc.stdout)
        save(work / f"{ordinal:02d}.stderr", proc.stderr)
        result["commands"].append({"argv": args, "exit_code": proc.returncode, "started_at": started,
                                   "finished_at": datetime.now(UTC).isoformat()})
        if proc.returncode:
            raise RuntimeError("candidate_tool_failed")
        return proc.stdout

    def inventory():
        ids = command([*DOCKER, "ps", "-aq", "--no-trunc"]).decode().split()
        return {"containers": [json.loads(command([*DOCKER, "inspect", "--format",
            '{"id":{{json .Id}},"status":{{json .State.Status}},"started_at":{{json .State.StartedAt}},"restart_count":{{.RestartCount}}}', v])) for v in sorted(ids)],
            "networks": sorted(command([*DOCKER, "network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"]).decode().splitlines()),
            "images": sorted(command([*DOCKER, "image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"]).decode().splitlines())}

    before, source = None, source_snapshot()
    try:
        parents = command(["git", "-C", str(ROOT), "rev-parse", "HEAD", "MERGE_HEAD"]).decode().split()
        if parents != GIT_BASE:
            raise ValueError("source_parent_drift")
        result["git_parents"] = parents
        result["kind_version"] = command(["kind", "version"]).decode().strip()
        if not result["kind_version"].startswith("kind v0.32.0 "):
            raise ValueError("kind_version_drift")
        before = inventory()
        save(work / "baseline-before.json", before)
        save(work / "source-manifest.json", source)
        value = json.loads(command([*DOCKER, "buildx", "imagetools", "inspect", NODE, "--format", "{{json .Manifest}}"] ))
        arm64 = node_identity(value)
        save(work / "image-index.json", value)
        result["arm64_digest"] = arm64
        command([*DOCKER, "scout", "version"])
        ref = "registry://" + NODE + "@" + NODE_INDEX
        print(json.dumps({"phase": "node_registry_scan", "evidence": str(work), "arm64": arm64}), flush=True)
        command([*DOCKER, "scout", "cves", "--platform", "linux/arm64", "--format", "sarif",
                 "--output", str(work / "all-severity.sarif.json"), ref], 1200)
        command([*DOCKER, "scout", "sbom", "--platform", "linux/arm64", "--format", "spdx",
                 "--output", str(work / "sbom.spdx.json"), ref], 1200)
        sbom = json.loads((work / "sbom.spdx.json").read_bytes())
        image_refs = [r.get("referenceLocator", "") for p in sbom.get("packages", []) for r in p.get("externalRefs", [])]
        if not any(p.startswith("pkg:oci/") and arm64 in p for p in image_refs):
            raise ValueError("node_sbom_image_binding")
        result["sbom_packages_including_image"] = len(sbom["packages"])
        result["assessment"] = assess_sarif(json.loads((work / "all-severity.sarif.json").read_bytes()))
        result["status"] = result["assessment"]["status"]
        if node_identity(json.loads(command([*DOCKER, "buildx", "imagetools", "inspect", NODE,
                                            "--format", "{{json .Manifest}}"]))) != arm64:
            raise ValueError("node_tag_drift")
    except Exception as exc:
        result.update(status="BLOCKED_ERROR", error_type=type(exc).__name__)
        if isinstance(exc, ValueError):
            result["error_code"] = str(exc)
    finally:
        try:
            after = inventory()
            save(work / "baseline-after.json", after)
            result["protected_baseline_unchanged"] = before is not None and before == after
            result["source_unchanged"] = source == source_snapshot()
            if not result["protected_baseline_unchanged"] or not result["source_unchanged"]:
                result["status"] = "BLOCKED_BASELINE_DRIFT"
        except Exception as exc:
            result.update(status="BLOCKED_BASELINE_CHECK", baseline_error=type(exc).__name__)
        result["finished_at"] = datetime.now(UTC).isoformat()
        result["runner_sha256"] = digest(Path(__file__).read_bytes())
        result["artifacts"] = {p.name: digest(p.read_bytes()) for p in work.iterdir() if p.is_file()}
        save(work / "result.json", result)
        print(json.dumps({"status": result["status"], "severity_counts": result.get("assessment", {}).get("severity_counts"),
                          "error_type": result.get("error_type"), "error_code": result.get("error_code"),
                          "evidence": str(work / "result.json")}, indent=2))
    return 0 if result["status"] == "CANDIDATE_SCAN_ONLY_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
