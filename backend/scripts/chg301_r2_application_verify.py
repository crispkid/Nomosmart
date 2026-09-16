"""Narrow approved regression entry point; no live services or Provider access."""
import json
from pathlib import Path
import sys

from chg301_r2_application_run import Run, ROOT, DOCKER, LABEL
from chg301_r2_application_guard import write_new

PYTHON = "/private/tmp/chg301-r2-pytest-layr63SP/venv/bin/python"


def main():
    if len(sys.argv) not in (2,3) or len(sys.argv) == 3 and sys.argv[2] not in {"2", "3"}:
        raise ValueError("exact_application_manifest_required")
    run = Run(sys.argv[1])
    work = run.root/("verification" if len(sys.argv) == 2 else "verification-attempt"+sys.argv[2])
    work.mkdir(mode=0o700)
    # A test cannot hash its own not-yet-finished command receipt. Bind the
    # completed evidence snapshot before starting the verification subprocess.
    write_new(work/"input-manifest.json", run.data)
    env = {
        "CHG301_R2_CANDIDATE_EVIDENCE": "/private/tmp/chg301-r2-traefik-vtkgc8jt",
        "CHG301_R2_REPAIR_EVIDENCE": "/private/tmp/chg301-r2-repair-8tn60fwz",
        "CHG301_R2_SMOKE_EVIDENCE": "/private/tmp/chg301-r2-smoke-fw9s9y9n",
        "CHG301_R2_NODE_EVIDENCE": "/private/tmp/chg301-r2-node-scan-mpgg_ipl",
        "CHG301_R2_TWO_LIBRARY_EVIDENCE": "/private/tmp/chg301-r2-two-lib-say0hh9k",
        "CHG301_R2_NODE_QUAL_EVIDENCE": "/private/tmp/chg301-r2-node-qual-_py7trju",
        "CHG301_R2_HIGH_EVIDENCE": "/private/tmp/chg301-r2-high-w4fccj_d",
        "CHG301_R2_DELIVERY_EVIDENCE": "/private/tmp/chg301-r2-delivery-c0j_1wn6",
        "CHG301_R2_FORMAL_EVIDENCE": "/private/tmp/chg301-r2-formal-ytnv04nm",
        "CHG301_R2_APPLICATION_EVIDENCE": str(run.root),
        "CHG301_R2_APPLICATION_MANIFEST": str(work/"input-manifest.json"),
        "PYTHONPATH": str(ROOT/"backend"), "KUBECONFIG": str(run.root/"no-kube"),
        "HELM_PLUGINS": str(run.root/"no-plugins"), "HELM_CONFIG_HOME": str(run.root/"helm-config"),
        "HELM_CACHE_HOME": str(run.root/"helm-cache")}
    files = ["backend/tests/test_chg301_r2_"+name+".py" for name in (
        "ingress", "node_qualification", "high_risk", "delivery", "formal_artifacts",
        "application_guard", "application_artifacts", "security_policy")]
    args = [PYTHON, "-m", "pytest", "--noconftest", "-p", "no:cacheprovider", "-c", "/dev/null"]
    run.command([*args, *files, "-q", "--junitxml="+str(work/"regression.xml")], timeout=1200, allowed=(0,1), extra_env=env)
    run.command([*args, "backend/tests/test_chg229_full_stack_deployment.py", "-q", "--junitxml="+str(work/"deployment-contract.xml")], timeout=1200, allowed=(0,1), extra_env=env)
    for command in ("spec:doctor", "spec:trace", "plan:doctor", "plan:approved", "test:plan", "backend:syntax", "helm:lint", "deploy:config-policy"):
        run.command([str(ROOT/"HARNESS/harness.sh"), command], timeout=1200, extra_env=env)
    run.command([*DOCKER, "compose", "--profile", "*", "config", "--no-env-resolution", "--quiet"], extra_env={"COMPOSE_FILE": str(ROOT/"docker-compose.yml")})
    artifact = run.data["artifacts"]["frontend-builder-arm64"]
    if artifact.get("cli", {}).get("status") != "PASS" or artifact["scan"]["counts"].get("HIGH", 0) or artifact["scan"]["counts"].get("CRITICAL", 0):
        raise ValueError("frontend_verification_safety_gate")
    capacity = run.capacity()
    if capacity["job_cpu"] < 1 or capacity["job_memory"] < 2*1024**3:
        raise ValueError("frontend_lint_capacity")
    cli = work/"frontend"
    cli.mkdir(mode=0o700)
    ident = run.output([*DOCKER, "create", "--pull=never", "--label", LABEL+"="+run.root.name,
        "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "10001:10001", "--cpus", "1", "--memory", "2g", "--memory-swap", "2g", "--pids-limit", "64",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777", "--env", "HOME=/tmp",
        "--entrypoint", "/bin/sh", artifact["id"], "-ec",
        "node --test tests/chg294SecurityDependencies.test.mjs; npm run lint"])
    write_new(cli/"owned.json", {"id": ident, "image_id": artifact["id"], "run": run.root.name, "label": LABEL})
    try:
        command = run.command([*DOCKER, "start", "--attach", ident], timeout=1200, allowed=(0,1,2))
        result = {"exit_code": int(run.output([*DOCKER, "inspect", "--format", "{{.State.ExitCode}}", ident])), "command": str(command/"result.json"), "image_id": artifact["id"]}
        write_new(cli/"result.json", result)
        print(json.dumps({"frontend_lint_contracts_exit": result["exit_code"]}), flush=True)
    finally:
        run.remove_container(ident, artifact["id"], cli)
    run.data["verification"] = str(work)
    run.save()


if __name__ == "__main__":
    main()
