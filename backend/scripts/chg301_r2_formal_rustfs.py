"""Build the one approved source-bound RustFS recipe in a minimal owned context."""
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from chg301_r2_formal_dependencies import Run, ROOT, source_guard
from chg301_r2_node_qualification import DOCKER, GiB, file_sha, process_usage, write_new


def build_sources(run, work, sources, tag, target=None, max_parallel_steps=1):
    """Shared resource checks; callers provide explicit product allowlists."""
    run.guard()
    work.mkdir(mode=0o700)  # Never overwrite an earlier attempt.
    context = work / "context"
    context.mkdir(mode=0o700)
    for dest, source in sources.items():
        if Path(dest).is_absolute() or ".." in Path(dest).parts or (ROOT / source).is_symlink():
            raise ValueError("context_path_identity")
        (context / dest).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(ROOT / source, context / dest)
    hashes = {p: file_sha(context / p) for p in sources}
    write_new(work / "context.json", {"sources": sources, "sha256": hashes})
    capacity = subprocess.run([sys.executable, str(ROOT / "backend/scripts/chg301_r2_formal_capacity.py"),
        str(run.root / "manifest.json")], env=run.env, capture_output=True, text=True, timeout=120)
    if capacity.returncode:
        raise ValueError("capacity_probe_failed")
    cap = json.loads(capacity.stdout.splitlines()[-1])
    # Buildx resource limits are PER STEP, not a shared build budget. The
    # source-bound Dockerfile DAG permits 3 independent frontend RUN branches,
    # 2 backend branches, and only 1 for RustFS. Reserve for their sum.
    per_cpu, per_mem = (2, 4) if target is None else (1, 2)
    if max_parallel_steps not in {1, 2, 3}:
        raise ValueError("unknown_build_parallelism")
    required_cpu, required_mem = per_cpu * max_parallel_steps, per_mem * max_parallel_steps * GiB
    if required_cpu > 4 or required_mem > 8*GiB:
        raise ValueError("build_aggregate_limit")
    if cap["capacity"]["available_job_cpu"] < required_cpu or cap["capacity"]["available_job_memory"] < required_mem:
        raise ValueError("vm_capacity_insufficient")
    if run.baseline()["containers"] != run.data["baseline_before"]["containers"]:
        raise ValueError("protected_container_drift")
    if subprocess.run([*DOCKER, "image", "inspect", tag], env=run.env, capture_output=True, timeout=30).returncode == 0:
        raise ValueError("tag_already_exists")
    args = [*DOCKER, "buildx", "build", "--builder", "desktop-linux", "--platform", "linux/arm64",
        "--resource", f"memory={per_mem}g", "--resource", f"cpu-quota={per_cpu*100000}", "--resource", "cpu-period=100000",
        "--provenance=false", "--load", "--progress=plain", "--tag", tag,
        "--label", "nomosmart.chg301.formal=" + run.root.name,
        "--iidfile", str(work / "image-id.txt"), "--metadata-file", str(work / "metadata.json")]
    if target:
        args += ["--target", target]
    if target != "builder":
        args += ["--no-cache"]
    args.append(str(context))
    record = {"args": args, "capacity": cap, "context_sha256": hashes,
              "builder_export_cache_reused": target == "builder",
              "resource_envelope": {"per_step_cpu": per_cpu, "per_step_memory_gib": per_mem,
                  "maximum_parallel_run_steps": max_parallel_steps, "aggregate_cpu": required_cpu,
                  "aggregate_memory_bytes": required_mem},
              "source_sha256": source_guard(run.data["source"]), "tag": tag,
              "started_at": datetime.now(UTC).isoformat()}
    write_new(work / "owned-intent.json", record)
    started = time.monotonic()
    with (work / "stdout").open("xb") as out, (work / "stderr").open("xb") as err:
        proc = subprocess.Popen(args, env=run.env, cwd=ROOT, stdout=out, stderr=err, start_new_session=True)
        try:
            while proc.poll() is None:
                run.guard()
                if any(file_sha(ROOT / sources[p]) != h or file_sha(context / p) != h for p, h in hashes.items()):
                    raise ValueError("build_context_source_drift")
                if time.monotonic()-started >= 1800 or process_usage(os.getpid())["rss_bytes"] > 8*GiB:
                    raise ValueError("build_time_or_memory_limit")
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
            raise
    record.update(exit_code=proc.returncode, elapsed_seconds=round(time.monotonic()-started, 2),
                  stderr_sha256=file_sha(work / "stderr"), finished_at=datetime.now(UTC).isoformat())
    if proc.returncode == 0:
        record["image_id"] = (work / "image-id.txt").read_text().strip()
    write_new(work / "result.json", record)
    print(json.dumps({k: record[k] for k in ("tag", "exit_code", "elapsed_seconds", "image_id") if k in record}), flush=True)
    if proc.returncode:
        raise ValueError("final_source_build_failed")
    return record


def main():
    if len(sys.argv) != 2:
        raise ValueError("exact_existing_manifest_required")
    run = Run(sys.argv[1])
    sources = {"Dockerfile": "deploy/rustfs/Dockerfile",
               "docker/secret-env-entrypoint.sh": "deploy/docker/secret-env-entrypoint.sh",
               "docker/compose-secret-entrypoint.sh": "deploy/docker/compose-secret-entrypoint.sh"}
    build_sources(run, run.root / "rustfs-final", sources, "nomosmart/rustfs:" + run.root.name + "-final")


if __name__ == "__main__":
    main()
