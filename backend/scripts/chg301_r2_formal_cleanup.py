"""Remove only this approved run's verified new image IDs; no prune or force."""
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys

from chg301_r2_formal_dependencies import Run, source_guard
from chg301_r2_node_qualification import DOCKER, write_new

BUILDS = ("rustfs-build", "rustfs-final", "frontend-runner", "frontend-runner-r2",
          "frontend-runner-r3", "frontend-builder", "frontend-builder-r2",
          "backend-runner", "backend-runner-r2", "backend-builder", "backend-builder-r2")


def main():
    if len(sys.argv) != 2:
        raise ValueError("exact_current_manifest_required")
    run = Run(sys.argv[1])
    run.guard()
    current = run.baseline()
    original = run.data["baseline_before"]
    if current["containers"] != original["containers"] or current["networks"] != original["networks"]:
        raise ValueError("protected_container_or_network_drift")
    if not set(original["images"]).issubset(current["images"]):
        raise ValueError("preexisting_image_drift")
    original_ids = {s.rsplit(" ", 1)[1] for s in original["images"]}
    current_ids = {s.rsplit(" ", 1)[1] for s in current["images"]}
    record = {"started_at": datetime.now(UTC).isoformat(), "commands": [], "removed": []}

    def command(args):
        result = subprocess.run([*DOCKER, *args], env=run.env, capture_output=True, text=True, timeout=60)
        record["commands"].append({"args": args, "exit_code": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode:
            raise ValueError("cleanup_command_failed")
        return result.stdout.strip()

    def inspect(ident):
        return json.loads(command(["image", "inspect", "--format",
            '{"id":{{json .Id}},"labels":{{json .Config.Labels}},"tags":{{json .RepoTags}},"digests":{{json .RepoDigests}}}', ident]))

    plan = []
    for name in BUILDS:
        build = json.loads((run.root / name / "result.json").read_bytes())
        actual = inspect(build["image_id"])
        if (actual["id"] in original_ids or actual["id"] != build["image_id"]
                or actual["labels"].get("nomosmart.chg301.formal") != run.root.name
                or actual["tags"] != [build["tag"]]):
            raise ValueError("owned_image_identity")
        expected_repo = build["tag"].rsplit(":", 1)[0]
        if any(d != expected_repo + "@" + build["image_id"] for d in actual["digests"]):
            raise ValueError("unexpected_image_digest_reference")
        plan.append({"name": name, **actual})
    redis = next(s for s in run.data["scans"] if s["name"] == "redis")
    reference = redis["target"]["scan_reference"].removeprefix("registry://")
    actual = inspect(reference)
    short = reference.removeprefix("docker.io/library/")
    if (actual["id"] in original_ids or actual["tags"]
            or actual["digests"] != [short]):
        raise ValueError("new_pulled_redis_identity")
    journals = [json.loads(p.read_bytes()) for p in run.root.glob("redis-live-*/journal.json")]
    if not journals or not any(j["image_id"] == actual["id"] and j["image"] == reference for j in journals):
        raise ValueError("redis_pull_receipt_missing")
    plan.append({"name": "redis-exact-pulled-child", **actual})
    planned_ids = {p["id"] for p in plan}
    if len(plan) != len(planned_ids) or current_ids-original_ids != planned_ids:
        raise ValueError("unaccounted_image_delta")
    for container in original["containers"]:
        if command(["inspect", "--format", "{{.Image}}", container["id"]]) in planned_ids:
            raise ValueError("image_used_by_protected_container")
    write_new(run.root / "analysis/image-cleanup-dry-run.json", {"images": plan,
        "preserve_images": len(original["images"]), "no_force_or_prune": True})
    try:
        for item in plan:
            run.guard()
            if inspect(item["id"]) != {k: v for k, v in item.items() if k != "name"}:
                raise ValueError("image_changed_since_cleanup_plan")
            command(["image", "rm", "--no-prune", item["id"]])
            record["removed"].append({"name": item["name"], "id": item["id"]})
    finally:
        after = run.baseline()
        record["baseline_unchanged"] = after == original
        record["finished_at"] = datetime.now(UTC).isoformat()
        write_new(run.root / "analysis/image-cleanup.json", record)
        run.data["baseline_after"] = after
        run.data["baseline_unchanged"] = record["baseline_unchanged"]
        run.data["source_after"] = source_guard(run.data["source"])
        run.save()
        print(json.dumps({"removed_images": len(record["removed"]),
                          "baseline_unchanged": record["baseline_unchanged"]}), flush=True)
    if not record["baseline_unchanged"]:
        raise ValueError("docker_baseline_not_restored")


if __name__ == "__main__":
    main()
