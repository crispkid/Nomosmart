"""Exact new-run and explicitly approved twelve historical image cleanup."""
import json
from pathlib import Path
import sys

from chg301_r2_application_run import Run, ROOT, OLD, LABEL, DOCKER
from chg301_r2_application_guard import digest, write_new


def exact_pulled_reference(image, image_id):
    reference = "redis@"+image_id
    return (image["id"] == image_id and image["tags"] in ([], [reference])
            and image["digests"] == [reference])


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in {"dry-run", "apply"}:
        raise ValueError("exact_application_manifest_and_mode_required")
    run = Run(sys.argv[1])
    work = run.root/"cleanup"
    work.mkdir(mode=0o700, exist_ok=True)
    prior_path = ROOT/"docs/CHG-301-R2-FORMAL-DEPENDENCY-EVIDENCE.json"
    if digest(prior_path) != "810c580bfdecd3b356bba283e763ce89e1d4db1e328ecc17fe9cd38abfb9840b":
        raise ValueError("historical_cleanup_scope_drift")
    prior = json.loads(prior_path.read_bytes())
    if digest(OLD/"manifest.json") != prior["run_manifest"]["sha256"]:
        raise ValueError("historical_manifest_drift")
    original = json.loads(run.output(["jq", ".baseline_before", str(OLD/"manifest.json")]))
    current = run.baseline()
    if any(current[k] != original[k] or current[k] != run.data["baseline_before"][k] for k in ("containers", "networks")):
        raise ValueError("protected_resource_drift")
    if not set(original["images"]) <= set(current["images"]):
        raise ValueError("original_images_changed")
    protected_ids = {line.rsplit(" ", 1)[1] for line in original["images"]}

    def inspect(ident):
        return json.loads(run.output([*DOCKER, "image", "inspect", "--format",
            '{"id":{{json .Id}},"tags":{{json .RepoTags}},"digests":{{json .RepoDigests}},"labels":{{json (index .Config "Labels")}}}', ident]))

    expected = [{"id": b["image_id"], "tag": b["tag"], "label": "nomosmart.chg301.formal", "owner": OLD.name} for b in prior["builds"]]
    if len(expected) != 11:
        raise ValueError("historical_build_scope")
    expected += [{"id": a["id"], "tag": a["tag"], "label": LABEL, "owner": run.root.name} for a in run.data["artifacts"].values()]
    planned = []
    for item in expected:
        actual = inspect(item["id"])
        if (actual["id"] in protected_ids or actual["id"] != item["id"] or actual["tags"] != [item["tag"]]
                or actual["labels"].get(item["label"]) != item["owner"]
                or any(d != item["tag"].rsplit(":",1)[0]+"@"+item["id"] for d in actual["digests"])):
            raise ValueError("owned_image_identity")
        planned.append(actual)
    redis_id = "sha256:f8d15882ba108587477ce13c00ab0551933a84138427b7cc9abadfbe45ffd973"
    if "redis:<none> "+redis_id not in prior["readonly_closeout"]["remaining_new_image_entries"]:
        raise ValueError("redis_outside_twelve")
    redis = inspect(redis_id)
    # Docker's containerd store can expose the exact digest reference in both
    # fields. This is the approved pull reference, not an additional mutable tag.
    if redis["id"] in protected_ids or not exact_pulled_reference(redis, redis_id):
        raise ValueError("pulled_image_has_new_references")
    receipts = [json.loads(p.read_bytes()) for p in OLD.glob("redis-live-*/journal.json")]
    if not any(r["image_id"] == redis_id and r["image"] == "docker.io/library/redis@"+redis_id for r in receipts):
        raise ValueError("exact_pull_receipt_missing")
    planned.append(redis)
    ids = {p["id"] for p in planned}
    if len(ids) != len(planned) or {line.rsplit(" ",1)[1] for line in current["images"]}-protected_ids != ids:
        raise ValueError("unexpected_image_delta_not_deleted")
    for c in current["containers"]:
        if run.output([*DOCKER, "inspect", "--format", "{{.Image}}", c["id"]]) in ids:
            raise ValueError("image_in_use")
    plan = {"images": planned, "protected": original, "no_force_or_prune": True}
    if sys.argv[2] == "dry-run":
        write_new(work/"dry-run.json", plan)
        print(json.dumps({"exact_images": len(planned), "mode": "DRY_RUN_ONLY"}), flush=True)
        return
    if json.loads((work/"dry-run.json").read_bytes()) != plan:
        raise ValueError("cleanup_plan_drift")
    result = {"removed": []}
    try:
        for image in planned:
            if inspect(image["id"]) != image:
                raise ValueError("cleanup_identity_changed")
            # Recheck current consumers immediately before each exact deletion.
            consumers = run.output([*DOCKER, "ps", "-aq", "--no-trunc"]).split()
            for ident in consumers:
                if run.output([*DOCKER, "inspect", "--format", "{{.Image}}", ident]) == image["id"]:
                    raise ValueError("image_now_in_use")
            run.command([*DOCKER, "image", "rm", "--no-prune", image["id"]])
            result["removed"].append(image["id"])
    finally:
        after = run.baseline()
        result["baseline_restored"] = after == original
        result["after"] = after
        write_new(work/"result.json", result)
        print(json.dumps({"removed": len(result["removed"]), "baseline_restored": result["baseline_restored"]}), flush=True)
    if not result["baseline_restored"]:
        raise ValueError("protected_baseline_not_restored")


if __name__ == "__main__":
    main()
