"""Read-only snapshot after blocked CLI; never create/remove any Docker object."""
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys

from chg301_r2_formal_dependencies import approval_guard, source_guard
from chg301_r2_high_risk import INSPECT
from chg301_r2_node_qualification import DOCKER, write_new


def main():
    approval_guard()
    if len(sys.argv) != 2 or sys.argv[1] != "/private/tmp/chg301-r2-formal-ytnv04nm/manifest.json":
        raise ValueError("exact_run_only")
    path = Path(sys.argv[1])
    data = json.loads(path.read_bytes())
    original = data["baseline_before"]

    def read(args):
        return subprocess.run([*DOCKER, *args], capture_output=True, text=True,
                              timeout=30, check=True).stdout.strip()

    containers = [json.loads(read(["inspect", "--format", INSPECT, ident]))
                  for ident in sorted(read(["ps", "-aq", "--no-trunc"]).split())]
    images = sorted(read(["image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}"]).splitlines())
    networks = sorted(read(["network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}"]).splitlines())
    result = {"observed_at": datetime.now(UTC).isoformat(), "mutations": 0,
        "containers_unchanged": containers == original["containers"],
        "networks_unchanged": networks == original["networks"],
        "original_images_preserved": set(original["images"]).issubset(images),
        "protected_container_count": len(original["containers"]),
        "remaining_new_image_entries": sorted(set(images)-set(original["images"])),
        "source_after": source_guard(data["source"]),
        "cleanup_status": "BLOCKED_NOT_EXECUTED_AFTER_CLI_PERMISSION_FAILURE"}
    write_new(path.parent / "analysis/readonly-closeout.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in {"source_after", "remaining_new_image_entries"}}
                     | {"remaining_new_image_count": len(result["remaining_new_image_entries"])}), flush=True)


if __name__ == "__main__":
    main()
