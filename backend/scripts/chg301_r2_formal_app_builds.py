"""Source-bound unchanged app builds; explicit files, unique tags, no runtime."""
import json
from pathlib import Path
import subprocess
import sys

from chg301_r2_formal_dependencies import Run, ROOT
from chg301_r2_formal_rustfs import build_sources
from chg301_r2_node_qualification import write_new


def main():
    if len(sys.argv) != 4 or sys.argv[2] not in {"frontend", "backend"} or sys.argv[3] not in {"builder", "builder-r2", "runner", "runner-r2", "runner-r3", "builder-r2-scan-r1"}:
        raise ValueError("exact_manifest_frontend_or_backend_builder_or_runner_required")
    run = Run(sys.argv[1])
    component, operation = sys.argv[2:]
    if operation == "builder-r2-scan-r1":
        # One bounded retry after Scout's SARIF expansion hit the existing
        # aggregate 8GiB guard. Preserve the interrupted/empty original report;
        # lower Go's soft heap target, never increase or disable the hard guard.
        if component != "backend":
            raise ValueError("unexpected_scan_retry")
        work = run.root / "backend-builder-r2"
        build = json.loads((work / "result.json").read_bytes())
        name = component + "-" + operation
        if any(t["name"] == name for t in run.data["targets"]):
            raise ValueError("retry_already_attempted")
        run.env.update(GOMEMLIMIT="2GiB", GOGC="50", GOMAXPROCS="2")
        run.data["targets"].append({"name": name, "scan_reference": "local://" + build["image_id"],
            "identity": {"id": build["image_id"], "architecture": "arm64"}, "source_bound": True,
            "qualification": "EXACT_SOURCE_ARM64_BUILDER", "retry": 1,
            "scanner_limits": {"GOMEMLIMIT": "2GiB", "GOGC": "50", "GOMAXPROCS": "2"}})
        try:
            run.scan(name)
            write_new(work / "scan.json", dict(run.data["scans"][-1], image_id=build["image_id"]))
        finally:
            run.save()
        return
    target = operation.split("-")[0]
    if component == "backend":
        names = {"backend/" + n for n in ("Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock",
            "main.py", "migrate.py", "models.py", "connection.py")}
        names.update(str(p.relative_to(ROOT)) for p in (ROOT / "backend/app").rglob("*.py"))
    else:
        result = subprocess.run(["git", "ls-files", "-z", "--", "frontend"], cwd=ROOT,
            env=run.env, capture_output=True, check=True, timeout=30)
        names = set(result.stdout.decode().strip("\0").split("\0"))
        # Git's explicit allowlist excludes untracked/generated/operator data;
        # reject secret/env files rather than letting Docker decide to transmit.
        if any(Path(n).name.startswith(".env") and not n.endswith(".env.example") for n in names):
            raise ValueError("unexpected_tracked_environment")
        if any(set(Path(n).parts) & {"node_modules", ".next", ".next-dev", "coverage", "test-results"} for n in names):
            raise ValueError("generated_context_input")
    if any(not (ROOT / n).is_file() or (ROOT / n).is_symlink() or (ROOT / n).stat().st_size > 20*1024**2 for n in names):
        raise ValueError("source_missing_symlink_or_oversize")
    sources = {str(Path(n).relative_to(component)): n for n in sorted(names)}
    name = component + "-" + operation
    record = build_sources(run, run.root / name, sources,
                           "nomosmart/" + component + ":" + run.root.name + "-" + operation, target,
                           max_parallel_steps=1 if target == "builder" else 3 if component == "frontend" else 2)
    run.data["targets"].append({"name": name, "scan_reference": "local://" + record["image_id"],
        "identity": {"id": record["image_id"], "architecture": "arm64"}, "source_bound": True,
        "qualification": "EXACT_SOURCE_ARM64_" + target.upper()})
    try:
        run.scan(name)
        write_new(run.root / name / "scan.json", dict(run.data["scans"][-1], image_id=record["image_id"]))
    finally:
        run.save()


if __name__ == "__main__":
    main()
