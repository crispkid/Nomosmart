"""Sequential approved application matrix; stop on failure, never auto-retry."""
import json
import sys
from chg301_r2_application_run import Run


def main():
    if len(sys.argv) != 2:
        raise ValueError("exact_application_manifest_required")
    run = Run(sys.argv[1])
    matrix = [("backend", "runner", "amd64")]
    matrix += [("frontend", stage, arch) for arch in ("arm64", "amd64")
               for stage in ("base", "deps", "builder", "prod-deps", "runner")]
    for component, stage, arch in matrix:
        name = f"{component}-{stage}-{arch}"
        if name in run.data["artifacts"]:
            raise ValueError("matrix_does_not_replay_existing_artifacts")
        print(json.dumps({"starting": name}), flush=True)
        run.build(component, stage, arch)
        run.scan(name)
        run.smoke(name)


if __name__ == "__main__":
    main()
