"""CHG-301 R2 nonsecret baseline and bounded, networkless VM-capacity probe.

Never connects to Kubernetes, reads operator configuration, builds/pulls images,
or changes existing resources. Only the exact new probe container is removed.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ("docker", "--context", "desktop-linux")
IMAGE = "sha256:02419de7eddf55aa5bcf49efb74e88fa8d931b4d77c07eff8a6b2144472b6952"
LABEL = "nomosmart.chg301.r2.probe"


def command(args, *, timeout=30):
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("command failed: " + args[0] + ":" + str(result.returncode))
    return result.stdout


def docker(*args):
    return command([*DOCKER, *args])


def put(path, value):
    # Exact newly created private evidence path; never operator configuration.
    with path.open("x") as stream:
        path.chmod(0o600)
        json.dump(value, stream, indent=2)


def baseline():
    ids = sorted(docker("ps", "-aq", "--no-trunc").split())
    states = []
    for ident in ids:
        # Do not request or print Config.Env or mounted Secret contents.
        row = json.loads(docker("inspect", "--format",
            '{"id":{{json .Id}},"status":{{json .State.Status}},'
            '"started_at":{{json .State.StartedAt}},"restart_count":{{.RestartCount}}}', ident))
        states.append(row)
    return states


def main():
    assert os.environ.get("CHG301_R2_ISOLATED") == "1", "explicit R2 opt-in required"
    root = Path(tempfile.mkdtemp(prefix="chg301-r2-preflight-", dir="/private/tmp"))
    root.chmod(0o700)
    run = root.name
    evidence = {"scope": "CHG-301 R2 capacity only", "started_at": datetime.now(UTC).isoformat(),
                "probe_image_id": IMAGE, "provider_calls": 0, "kubernetes_operations": 0,
                "status": "FAIL", "probe_container_id": None}
    before = None
    ident = None
    try:
        evidence["tool_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        evidence["git"] = command(["git", "rev-parse", "HEAD", "MERGE_HEAD"]).split()
        evidence["docker"] = json.loads(docker("info", "--format",
            '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}},"version":{{json .ServerVersion}}}'))
        before = baseline()
        evidence["baseline"] = before
        info = json.loads(docker("image", "inspect", "--format",
            '{"id":{{json .Id}},"architecture":{{json .Architecture}}}', IMAGE))
        assert info["id"] == IMAGE and info["architecture"] == "arm64"
        assert not docker("ps", "-aq", "--filter", "name=^/" + run + "$").strip()
        # /proc exposes VM capacity, including containerd workloads not shown in
        # docker stats. No mount, network, host namespace or daemon socket.
        script = "cat /proc/meminfo; head -n 1 /proc/stat; sleep 2; head -n 1 /proc/stat; df -Pk /"
        ident = docker("create", "--name", run, "--label", LABEL + "=" + run,
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt",
            "no-new-privileges", "--memory", "32m", "--memory-swap", "32m", "--cpus", "0.1",
            "--pids-limit", "16", "--user", "10001:10001", "--entrypoint", "/bin/sh",
            IMAGE, "-c", script).strip()
        assert re.fullmatch(r"[0-9a-f]{64}", ident)
        evidence["probe_container_id"] = ident
        put(root / "owned.json", {"run": run, "container_id": ident, "image_id": IMAGE})
        text = docker("start", "--attach", ident)
        assert docker("inspect", "--format", "{{.State.ExitCode}}", ident).strip() == "0"
        memory = {m.group(1): int(m.group(2)) * 1024 for line in text.splitlines()
                  if (m := re.fullmatch(r"(MemTotal|MemAvailable):\s+(\d+) kB", line))}
        samples = [list(map(int, line.split()[1:])) for line in text.splitlines() if line.startswith("cpu ")]
        assert len(samples) == 2 and set(memory) == {"MemTotal", "MemAvailable"}
        delta = [b-a for a, b in zip(*samples)]
        # guest/guest_nice are already included in user/nice; do not double count.
        total = sum(delta[:8]); idle = delta[3] + delta[4]
        assert total > 0 and 0 <= idle <= total
        busy = evidence["docker"]["cpus"] * (total-idle) / total
        df = next(line.split() for line in text.splitlines() if line.startswith("overlay "))
        available = int(df[3]) * 1024
        reserve_memory = max(8 * 1024**3, evidence["docker"]["memory_bytes"] * .20)
        evidence["capacity"] = {"vm_memory_bytes": memory["MemTotal"],
            "vm_memory_available_bytes": memory["MemAvailable"], "vm_sample_busy_cores": busy,
            "vm_filesystem_available_bytes": available, "sample_seconds": 2,
            "required_reserve_cores": 4, "required_reserve_memory_bytes": reserve_memory,
            "remaining_test_cpu_ceiling": max(0, evidence["docker"]["cpus"]-4-busy),
            "remaining_test_memory_ceiling_bytes": max(0, memory["MemAvailable"]-reserve_memory),
            "disk_100gib_precondition": available >= 100 * 1024**3}
        evidence["status"] = "MEASURED_NOT_CLUSTER_APPROVAL"
    except Exception as exc:
        evidence["error_type"] = type(exc).__name__
    finally:
        if ident:
            actual = json.loads(docker("inspect", "--format",
                '{"id":{{json .Id}},"labels":{{json .Config.Labels}}}', ident))
            assert actual["id"] == ident and actual["labels"].get(LABEL) == run
            assert before is not None and ident not in {r["id"] for r in before}
            docker("rm", "-f", ident)
            evidence["probe_removed"] = True
        if before is not None:
            after = baseline()
            evidence["baseline_unchanged"] = before == after
            if before != after:
                evidence["status"] = "BASELINE_DRIFT"
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        put(root / "result.json", evidence)
        print(json.dumps({"status": evidence["status"], "capacity": evidence.get("capacity"),
                          "evidence": str(root / "result.json")}, indent=2))
    return 0 if evidence["status"] == "MEASURED_NOT_CLUSTER_APPROVAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
