"""CHG-300 approved isolated tests; reuse guarded real-service V049 lab.

No image build/pull, live credentials, Kubernetes, Provider or current-data access.
Installed Flyway 13.0 is a source-level test vehicle, not new-image acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

from chg291_v049_rehearsal import ROOT, Rehearsal


def own_sources():
    paths = [Path(__file__), ROOT / "backend/tests/test_chg300_migration_gate.py"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def prepare_gate_databases(lab):
    for label, version in (("m300_ready", 49), ("m300_v048", 48)):
        lab.migrate(lab.database(label), version)
    lab.database("m300_empty")
    baseline = lab.database("m300_baseline")
    lab.docker("exec", lab.state["services"]["flyway"], "/flyway/flyway",
               "-url=jdbc:postgresql://pg:5432/" + baseline, "-baselineVersion=49", "baseline")
    # Baseline-only deliberately does not run V042's app-role grants. Make its
    # genuine history readable so the negative case tests BASELINE vs SQL, not ACL.
    lab.psql(baseline, "GRANT SELECT ON public.flyway_schema_history TO nomosmart")
    failed = lab.database("m300_failed")
    lab.migrate(failed, 48)
    # Deliberate self-created ownerless project: genuine V049 failure, not a
    # manually inserted Flyway failure/success record.
    lab.psql(failed, "INSERT INTO projects(id,name,status) VALUES (gen_random_uuid(),'CHG300 synthetic ownerless','active')")
    assert lab.migrate(failed, check=False).returncode != 0
    target = lab.database("m300_target_only")
    # Copy only genuine isolated history into a new empty rejection DB.
    exported = lab.docker("exec", lab.state["services"]["pg"], "pg_dump", "-U", "postgres",
                          "-d", "v49_m300_ready", "-t", "public.flyway_schema_history")
    lab.psql(target, exported.stdout.decode())
    checksum = lab.query("v49_m300_ready", "SELECT checksum FROM public.flyway_schema_history WHERE version='049' AND success")
    assert type(checksum) is int
    lab.state["m300_checksum"] = checksum
    lab.state["secrets"]["m300_reader"] = secrets.token_hex(24)
    lab.save()
    password = lab.state["secrets"]["m300_reader"]
    lab.psql("v49_m300_ready", f"""CREATE ROLE v49_m300_reader LOGIN PASSWORD '{password}';
        ALTER ROLE v49_m300_reader SET default_transaction_read_only=on;
        GRANT CONNECT ON DATABASE v49_m300_ready TO v49_m300_reader;
        GRANT USAGE ON SCHEMA public TO v49_m300_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO v49_m300_reader;""")
    lab.state["m300_before"] = lab.snapshot("v49_m300_ready")
    lab.save()


def gate_tests(lab, *, image_manifest=None):
    packages = ROOT / "backend/.venv/lib/python3.12/site-packages"
    mounts = [(str(ROOT / "backend/app"), "/current/app", True),
              (str(ROOT / "backend/tests/test_chg300_migration_gate.py"), "/verify/test_gate.py", True)]
    if image_manifest is not None:
        mounts = [(str(ROOT / "backend/tests/test_chg300_migration_gate.py"), "/verify/test_gate.py", True),
                  (str(image_manifest), "/verify/image-manifest.json", True)]
    for package in ("pytest", "_pytest", "pluggy", "iniconfig", "packaging", "pygments", "pytest_cov", "coverage"):
        mounts.append((str(packages / package), "/test-deps/" + package, True))
    mounts.append((str(packages / "py.py"), "/test-deps/py.py", True))
    password = lab.state["secrets"]["NOMOSMART_DB_PASSWORD"]
    env = {"APP_ENV": "test", "M300_ISOLATED": "1", "M300_CHECKSUM": str(lab.state["m300_checksum"]),
           "M300_URL": f"postgresql+psycopg2://nomosmart:{password}@pg:5432/v49_m300_ready",
           "M300_READONLY_URL": f"postgresql+psycopg2://v49_m300_reader:{lab.state['secrets']['m300_reader']}@pg:5432/v49_m300_ready",
           "APP_ENCRYPTION_KEY": lab.state["secrets"]["app"], "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": "/current:/app:/test-deps", "PYTHONSAFEPATH": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
           "COVERAGE_CORE": "pytrace", "COVERAGE_FILE": "/tmp/.coverage-chg300"}
    if image_manifest is not None:
        env.update(M300_EXECUTION_MODE="image", PYTHONPATH="/app:/test-deps")
    pytest_args = [
        "-m", "pytest", "-c", "/dev/null", "--rootdir=/verify", "-p", "no:cacheprovider", "--tb=short", "-q",
        "/verify/test_gate.py", "--junitxml=/tmp/gate.xml", "-p", "pytest_cov.plugin", "--cov=app.deployment.migration_gate",
        "--cov-branch", "--cov-report=json:/tmp/gate-coverage.json", "--cov-report=term", "--cov-fail-under=80"]
    if image_manifest is not None:
        # Keep tmpfs mounted until genuine pytest artifacts have been copied.
        ident = lab.create("m300-gate", "backend", env=env, mounts=mounts,
            entrypoint="/bin/sh", command=["-c", "exec sleep 3600"])
        result = lab.docker("exec", ident, "python", *pytest_args, timeout=180, check=False)
        code = result.returncode
    else:
        ident = lab.create("m300-gate", "backend", env=env, mounts=mounts, entrypoint="python", command=pytest_args)
        code = int(lab.docker("wait", ident, timeout=180).stdout.decode().strip())
        result = lab.docker("logs", ident)
    output = result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
    for secret in lab.state["secrets"].values():
        output = output.replace(secret, "[REDACTED]")
    lab.state["operations"].append({"operation": "CHG300 image-internal gate pytest" if image_manifest is not None else "CHG300 source gate pytest (not new-image acceptance)",
        "image": lab.state["images"]["backend"], "returncode": code, "output": output})
    lab.save()
    print(output[-5000:], flush=True)
    for name in ("gate.xml", "gate-coverage.json"):
        if image_manifest is not None:
            # Docker archive/cp may not expose tmpfs; read the real file from the
            # still-running container namespace, preserving its exact bytes.
            content = lab.docker("exec", ident, "cat", "/tmp/" + name).stdout
            assert 0 < len(content) < 5_000_000
            target = lab.path.parent / name
            with target.open("xb") as stream:
                target.chmod(0o600); stream.write(content)
        else:
            lab.docker("cp", ident + ":/tmp/" + name, str(lab.path.parent / name), check=False)
    lab.remove_container(ident)
    assert lab.snapshot("v49_m300_ready") == lab.state["m300_before"], "Read-only gate changed database"
    return code


def main():
    directory = Path(tempfile.mkdtemp(prefix="chg300-isolated-", dir="/private/tmp"))
    directory.chmod(0o700)
    path = directory / "private-state.json"
    state = {"run": "v49-" + secrets.token_hex(6), "containers": [], "volumes": [], "databases": [],
        "services": {}, "allowed_mounts": [], "operations": [], "dumps": [], "chg300_sources": own_sources(),
        "secrets": {"pg": secrets.token_hex(24), "kc": secrets.token_hex(24), "app": secrets.token_hex(32)}}
    path.write_text(json.dumps(state)); path.chmod(0o600)
    lab = Rehearsal(path)
    print("CHG300 isolated directory:", directory, flush=True)
    codes = []
    try:
        lab.setup()
        prepare_gate_databases(lab)
        codes.append(gate_tests(lab))
        assert own_sources() == state["chg300_sources"], "CHG300 tooling drift"
        # Retain actual V049/Owner/rollback matrix, using the unchanged runner
        # contract and real PostgreSQL + Keycloak. No current data copied.
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
        env.update(V49_STATE=str(path), PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        result = subprocess.run([sys.executable, "-m", "pytest", "-c", "/dev/null", "--rootdir=" + str(ROOT),
            "-p", "no:cacheprovider", "--tb=short", "-q", str(ROOT / "backend/tests/test_chg291_v049_live_rehearsal.py"),
            "--junitxml=" + str(directory / "retained-v049.xml")], env=env, timeout=900)
        codes.append(result.returncode)
    finally:
        lab = Rehearsal(path)
        cleanup_ok = False
        try:
            if "baseline" in lab.state:
                lab.cleanup()
            cleanup_ok = True
        finally:
            safe = {k: v for k, v in lab.state.items() if k not in {"secrets", "allowed_mounts"}}
            safe.update(test_returncodes=codes, cleanup_ok=cleanup_ok,
                        new_image_build=False, provider_calls=0, deployment=False)
            (directory / "evidence.json").write_text(json.dumps(safe, indent=2))
            if cleanup_ok:
                path.unlink()
            print("CHG300 evidence:", directory / "evidence.json", flush=True)
    return 0 if codes == [0, 0] else 1


if __name__ == "__main__":
    raise SystemExit(main())
