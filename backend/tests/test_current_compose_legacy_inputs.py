"""Real cached-image private preparation; no original credential or service use."""
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import subprocess
from uuid import uuid4

import pytest

from current_live_support import load_current_context
from current_entrypoint_scope import load_entrypoint_scope


ROOT = Path(__file__).resolve().parents[2]


def _context():
    if os.environ.get("NOMOSMART_ENTRYPOINT_SCOPE"):
        context = load_entrypoint_scope()
        return context, Path(context["root"])
    return load_current_context(), Path(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"]).parent


@pytest.fixture(scope="module")
def private_preparation():
    context, root = _context()
    run = context["run_id"]
    name = context.get("resource_prefix", "nms370-") + "entrypoint-" + uuid4().hex[:12]
    directory = root / name
    directory.mkdir(mode=0o700)
    manifest = json.loads((ROOT / "docs/CHG-370-ORIGINAL-TARGET-MANIFEST.json").read_text())
    image = next(row["image_id"] for row in manifest["consumer_start_metadata"]
                 if row["service"] == "nomosmart-backend-1")
    assert image.startswith("sha256:") and len(image) == 71
    evidence = {"run_uuid": run, "image": image, "network": "none", "cases": [], "cleanup_complete": False}

    def save():
        p = directory / "receipt.json"
        p.write_text(json.dumps(evidence, indent=2))
        p.chmod(0o600)

    def ledger(kind, key, row):
        p = root / "owner.json"
        owner = json.loads(p.read_text())
        assert owner["run_uuid"] == run
        owner[kind][key] = row
        p.write_text(json.dumps(owner, indent=2))
        p.chmod(0o600)

    def docker(*args, data=None):
        environment = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
        return subprocess.run(["docker", "--context", "desktop-linux", *args], input=data,
                              capture_output=True, env=environment, timeout=40)

    for file in ("compose-secret-entrypoint.sh", "secret-env-entrypoint.sh"):
        source = ROOT / "deploy/docker" / file
        target = directory / file
        target.write_bytes(source.read_bytes())
        target.chmod(0o555)
    check = directory / "check.py"
    check.write_text("""import hashlib,json,os,pathlib,stat,sys
packet=json.load(sys.stdin)
assert os.getuid()==10001 and os.getgid()==10001
assert os.umask(0o027)==0o027
for name,expected in packet.items():
 p=pathlib.Path('/run/nomosmart/secrets')/name
 assert p.stat().st_uid==10001 and stat.S_IMODE(p.stat().st_mode)==0o400
 assert hashlib.sha256(p.read_bytes()).hexdigest()==expected
 assert p.parent.stat().st_uid==0 and stat.S_IMODE(p.parent.stat().st_mode)==0o710
 if name=='app_encryption_key': assert os.environ['APP_ENCRYPTION_KEY_FILE']==str(p)
 if name.startswith('keycloak_'):
  variable=name.upper()+'_FILE'
  if variable in os.environ: assert os.environ[variable]==str(p)
if 'KEYCLOAK_SYNC_CLIENT_SECRET' in os.environ:
 assert hashlib.sha256(os.environ['KEYCLOAK_SYNC_CLIENT_SECRET'].encode()).hexdigest()==packet['keycloak_sync_client_secret']
print('ACTUAL_UID10001_PRIVATE0400_INPUTS_VERIFIED')
""")
    check.chmod(0o444)
    volume = name + "-scratch"
    a = docker("volume", "create", "--label", "nomosmart.run=" + run, "--label", "nomosmart.operation=" + run, volume)
    assert a.returncode == 0
    ledger("volumes", volume, {"run_uuid": run, "purpose": "One isolated entrypoint scratch mount"})
    save()
    try:
        yield context, directory, name, volume, image, evidence, save, ledger, docker
    finally:
        a = docker("volume", "inspect", "--format", "{{json .Labels}}", volume)
        assert a.returncode == 0 and json.loads(a.stdout)["nomosmart.run"] == run
        a = docker("volume", "rm", volume)
        assert a.returncode == 0
        ledger("volumes", volume, {"run_uuid": run, "state": "REMOVED", "purpose": "Isolated entrypoint scratch mount"})
        evidence["cleanup_complete"] = True
        save()


@pytest.mark.parametrize("mode", ["current", "legacy-file", "legacy-export", "missing-reference"])
def test_actual_private_copy_for_current_and_retained_consumers(private_preparation, mode):
    context, directory, name, volume, image, evidence, save, ledger, docker = private_preparation
    root = _context()[1]
    names = ["app_encryption_key"]
    if mode in {"legacy-file", "legacy-export"}:
        names += ["keycloak_sync_client_secret", "keycloak_bootstrap_admin_password"]
    packet, files = {}, []
    args = ["create", "-i", "--pull=never", "--name", name + "-" + mode,
        "--label", "nomosmart.run=" + context["run_id"], "--label", "nomosmart.operation=" + context["run_id"], "--label", "nomosmart.test=entrypoint-compat",
        "--network", "none", "--user", "0:0", "--read-only", "--cap-drop", "ALL",
        "--memory", "256m", "--cpus", ".25", "--pids-limit", "64",
        "--tmpfs", "/run/nomosmart:rw,noexec,nosuid,nodev,size=2m,mode=0700",
        "--mount", "type=volume,src=" + volume + ",dst=/var/lib/nomosmart-upload",
        "-e", "APP_ENCRYPTION_KEY_FILE=/run/secrets/app_encryption_key"]
    for capability in ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID", "SYS_CHROOT"]:
        args += ["--cap-add", capability]
    for file in names:
        target = directory / (mode + "-" + file)
        value = secrets.token_urlsafe(40)
        target.write_text(value)
        target.chmod(0o600)
        packet[file] = sha256(value.encode()).hexdigest()
        files.append(target)
        args += ["--mount", "type=bind,src=" + str(target) + ",dst=/run/secrets/" + file + ",readonly"]
    for file in ("compose-secret-entrypoint.sh", "secret-env-entrypoint.sh"):
        args += ["--mount", "type=bind,src=" + str(directory / file) + ",dst=/opt/nomosmart/" + file + ",readonly"]
    for file in ("rustfs-ca.crt", "opensearch-ca.crt"):
        args += ["--mount", "type=bind,src=" + str(root / "tls/ca.pem") + ",dst=/etc/nomosmart/tls/" + file + ",readonly"]
    args += ["--mount", "type=bind,src=" + str(directory / "check.py") + ",dst=/check.py,readonly"]
    if mode == "legacy-file":
        for file in names[1:]:
            args += ["-e", file.upper() + "_FILE=/run/secrets/" + file]
    if mode == "legacy-export":
        args += ["-e", "NOMOSMART_SECRET_EXPORTS=KEYCLOAK_SYNC_CLIENT_SECRET:/run/secrets/keycloak_sync_client_secret"]
    if mode == "missing-reference":
        args += ["-e", "KEYCLOAK_SYNC_CLIENT_SECRET_FILE=/run/secrets/keycloak_sync_client_secret"]
    args += ["--entrypoint", "/bin/sh", image, "-c",
             "umask 0027; exec /opt/nomosmart/compose-secret-entrypoint.sh backend python /check.py"]
    cid = None
    try:
        a = docker(*args)
        assert a.returncode == 0, "owned private-preparation container creation failed"
        cid = a.stdout.decode().strip()
        ledger("containers", name + "-" + mode, {"id": cid, "purpose": "Real networkless private preparation " + mode})
        a = docker("start", "-ai", cid, data=json.dumps(packet).encode())
        expected = 66 if mode == "missing-reference" else 0
        evidence["cases"].append({"mode": mode, "container_id": cid, "raw_exit": a.returncode,
                                  "expected_exit": expected, "uid": 10001, "original_secret_reads": 0})
        save()
        assert a.returncode == expected, "actual private preparation returned unexpected exit"
        if expected == 0:
            assert b"ACTUAL_UID10001_PRIVATE0400_INPUTS_VERIFIED" in a.stdout
        for file in files:
            assert file.stat().st_mode & 0o777 == 0o600
            assert sha256(file.read_bytes()).hexdigest() == packet[file.name.removeprefix(mode + "-")]
    finally:
        if cid:
            a = docker("inspect", "--format", "{{json .Config.Labels}}", cid)
            assert a.returncode == 0 and json.loads(a.stdout)["nomosmart.run"] == context["run_id"]
            assert docker("rm", cid).returncode == 0
            ledger("containers", name + "-" + mode, {"id": cid, "state": "REMOVED", "purpose": mode})
        for file in files:
            file.unlink(missing_ok=True)
