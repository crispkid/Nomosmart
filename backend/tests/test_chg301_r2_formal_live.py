"""Real run-owned Redis and RustFS contracts; no deployed services or Provider.

Explicit evidence opt-in, static safety gate, fresh VM capacity, constrained
nonroot containers, internal-only network, generated test credentials and CA.
"""
from datetime import UTC, datetime, timedelta
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
from chg301_r2_formal_dependencies import approval_guard
from chg301_r2_high_risk import raw_findings, time_guard, INSPECT
from chg301_r2_node_qualification import DOCKER, file_sha

LABEL = "nomosmart.chg301.formal.live"
RUN = Path(os.environ["CHG301_R2_FORMAL_EVIDENCE"]).resolve(strict=True)


class Lab:
    def __init__(self, component):
        approval_guard()
        manifest = json.loads((RUN / "manifest.json").read_bytes())
        time_guard(manifest, datetime.now(UTC))
        assert RUN.parent == Path("/private/tmp") and RUN.name.startswith("chg301-r2-formal-")
        self.root = Path(tempfile.mkdtemp(prefix=component + "-live-", dir=RUN))
        self.name, self.component = self.root.name, component
        self.env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.commands, self.containers, self.secret_values, self.generated_files = [], [], [], []
        self.network = None
        self.started = time.monotonic()
        self.before = self.baseline()
        assert self.before == manifest["baseline_before"]["containers"]
        if component == "redis":
            scan = next(s for s in manifest["scans"] if s["name"] == "redis")
            self.image = scan["target"]["scan_reference"].removeprefix("registry://")
        else:
            stage = os.environ.get("CHG301_R2_RUSTFS_STAGE", "rustfs-build")
            assert stage in {"rustfs-build", "rustfs-final"}
            scan = json.loads((RUN / stage / "scan.json").read_bytes())
            self.image = scan["image_id"]
        for report in scan["reports"].values():
            assert file_sha(Path(report["path"])) == report["sha256"]
        findings = raw_findings(json.loads(Path(scan["reports"]["cves"]["path"]).read_bytes()))
        assert not any(f["severity"] in {"HIGH", "CRITICAL"} for f in findings.values())
        self.scan = scan
        p = subprocess.run([sys.executable, str(ROOT / "backend/scripts/chg301_r2_formal_capacity.py"),
                            str(RUN / "manifest.json")], env=self.env, capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr[-1500:]
        self.capacity = json.loads(p.stdout.splitlines()[-1])
        cap = self.capacity["capacity"]
        assert cap["available_job_cpu"] >= 2 and cap["available_job_memory"] >= 2 * 1024**3
        assert cap["disk_free"] >= 100 * 1024**3
        # A digest pull only, never running a floating tag or overwriting a tag.
        if component == "redis":
            self.docker("pull", "--platform", "linux/arm64", self.image, timeout=180)
        self.image_id = json.loads(self.docker("image", "inspect", "--format", "{{json .Id}}", self.image).stdout)
        self.network = self.docker("network", "create", "--internal", "--label", LABEL + "=" + self.name, self.name).stdout.strip()
        self.password = secrets.token_hex(24)
        self.secret_values.append(self.password)
        self.secret = self.file("password", self.password)
        self.save()

    def save(self):
        record = {"component": self.component, "image": self.image, "image_id": self.image_id,
            "scan": self.scan, "capacity": self.capacity, "network": self.network,
            "containers": self.containers, "commands": self.commands,
            "source_sha256": {p: file_sha(ROOT / p) for p in [
                "docker-compose.yml", "deploy/helm/nomosmart/templates/redis.yaml",
                "deploy/docker/secret-env-entrypoint.sh", "deploy/rustfs/Dockerfile"]}}
        (self.root / "journal.json").write_text(json.dumps(record, indent=2))
        (self.root / "journal.json").chmod(0o600)

    def docker(self, *args, check=True, timeout=30):
        assert time.monotonic() - self.started < 1200 or args[0] in {"inspect", "rm", "network", "ps"}
        result = subprocess.run([*DOCKER, *args], env=self.env, capture_output=True, text=True, timeout=timeout)
        for value in self.secret_values:
            result.stdout = result.stdout.replace(value, "[REDACTED]")
            result.stderr = result.stderr.replace(value, "[REDACTED]")
        self.commands.append({"args": list(args), "exit_code": result.returncode,
                              "stdout": result.stdout, "stderr": result.stderr})
        if check:
            assert result.returncode == 0, (result.stdout + result.stderr)[-1500:]
        return result

    def baseline(self):
        return [json.loads(self.docker("inspect", "--format", INSPECT, i).stdout)
                for i in sorted(self.docker("ps", "-aq", "--no-trunc").stdout.split())]

    def file(self, name, content):
        path = self.root / name
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        path.chmod(0o400)  # Never make even disposable credentials world-readable.
        self.generated_files.append(path)
        return path

    def certificates(self, hosts):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CHG301 disposable test CA")])
        now = datetime.now(UTC)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in hosts] +
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256()))
        return self.file("tls.crt", cert.public_bytes(serialization.Encoding.PEM)), self.file(
            "tls.key", key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))

    def create(self, script, *, mounts=(), env=(), aliases=(), entry="/bin/sh", args=None):
        assert len(self.containers) < 4
        uid = 999 if self.component == "redis" else 10001
        command = ["create", "--pull=never", "--label", LABEL + "=" + self.name,
            "--network", self.network, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", f"{uid}:{uid}", "--cpus", "0.5", "--memory", "512m", "--memory-swap", "512m",
            "--pids-limit", "128", "--log-opt", "max-size=2m", "--log-opt", "max-file=1",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
            "--tmpfs", "/data:rw,nosuid,nodev,size=128m,mode=1777",
            "--tmpfs", f"/logs:rw,noexec,nosuid,nodev,size=32m,mode=0700,uid={uid},gid={uid}",
            "--tmpfs", f"/run/secrets:rw,noexec,nosuid,nodev,size=1m,mode=0700,uid={uid},gid={uid}",
            "--tmpfs", f"/tls:rw,noexec,nosuid,nodev,size=1m,mode=0700,uid={uid},gid={uid}"]
        for alias in aliases:
            command += ["--network-alias", alias]
        for name, value in env:
            assert value not in self.secret_values
            command += ["-e", name + "=" + value]
        for path, dest in mounts:
            assert path.parent == self.root and path.is_file() and not path.is_symlink()
            assert Path(dest).parent in {Path('/tls'), Path('/run/secrets')}
        # Provision generated secrets over stdin into private tmpfs as the same
        # nonroot service UID. No host credential mount or root preparation.
        gate = 'i=0; until [ -f /tmp/chg301-ready ]; do i=$((i+1)); [ "$i" -lt 300 ]; sleep 0.1; done; exec "$@"'
        command += ["--entrypoint", "/bin/sh", self.image_id, "-ec", gate, "sh", entry,
                    *(args if args is not None else ["-ec", script])]
        ident = self.docker(*command).stdout.strip()
        assert ident and ident not in {v["id"] for v in self.before}
        self.containers.append(ident)
        self.save()
        self.docker("start", ident)
        for path, dest in mounts:
            result = subprocess.run([*DOCKER, "exec", "-i", ident, "/bin/sh", "-ec",
                'umask 077; cat > "$1"; chmod 0400 "$1"', "sh", dest],
                input=path.read_bytes(), capture_output=True, env=self.env, timeout=15)
            self.commands.append({"operation": "private_tmpfs_generated_file", "container": ident,
                                  "destination": dest, "exit_code": result.returncode, "mode": "0400"})
            assert result.returncode == 0, "private generated file preparation failed"
        self.docker("exec", ident, "touch", "/tmp/chg301-ready")
        return ident

    def wait_for(self, action, predicate, seconds=35):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = action()
            if predicate(value):
                return value
            time.sleep(.5)
        self.save()
        pytest.fail("real isolated service readiness/contract timeout")

    def close(self):
        cleanup = []
        try:
            for ident in reversed(self.containers):
                # Capture real process errors before removing the disposable
                # service. docker() redacts generated secret values.
                self.docker("logs", "--tail", "80", ident, check=False)
                row = json.loads(self.docker("inspect", "--format", '{"id":{{json .Id}},"labels":{{json .Config.Labels}}}', ident).stdout)
                assert row["id"] == ident and row["labels"].get(LABEL) == self.name
                cleanup.append({"kind": "container", "id": ident})
            if self.network:
                row = json.loads(self.docker("network", "inspect", "--format", '{"id":{{json .Id}},"labels":{{json .Labels}}}', self.network).stdout)
                assert row["id"] == self.network and row["labels"].get(LABEL) == self.name
                cleanup.append({"kind": "network", "id": self.network})
            (self.root / "cleanup-dry-run.json").write_text(json.dumps(cleanup, indent=2))
            for item in cleanup:
                self.docker(*(["rm", "-f", item["id"]] if item["kind"] == "container" else ["network", "rm", item["id"]]))
            files = []
            for path in self.generated_files:
                assert path.parent == self.root and path.is_file() and not path.is_symlink()
                files.append({"path": str(path), "sha256": file_sha(path), "mode": oct(path.stat().st_mode & 0o777)})
            (self.root / "private-files-cleanup-dry-run.json").write_text(json.dumps(files, indent=2))
            for path in self.generated_files:
                path.unlink()
            assert self.baseline() == self.before
            (self.root / "cleanup.json").write_text(json.dumps({"removed": cleanup, "private_files_removed": files,
                                                               "baseline_unchanged": True}))
        finally:
            self.save()


@pytest.fixture
def redis_lab():
    lab = Lab("redis")
    try:
        yield lab
    finally:
        lab.close()


def cli(lab, ident, *args, tls=False, auth=True, port=6379):
    prefix = 'export REDISCLI_AUTH="$(cat /run/secrets/redis_password)"; ' if auth else ""
    options = ["--tls", "--cacert", "/tls/ca.crt"] if tls else []
    p = lab.docker("exec", ident, "/bin/sh", "-ec", prefix + 'exec redis-cli --raw "$@"', "sh",
        *options, "--user", "nomosmart", "-p", str(port), *args, check=False)
    return p.stdout.strip() + p.stderr.strip()


def test_redis_actual_compose_secret_acl_and_queue(redis_lab):
    lab = redis_lab
    command = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["redis"]["command"][0]
    command = command.replace("${REDIS_USERNAME:-nomosmart}", "nomosmart").replace("$$", "$")
    missing = lab.create(command)
    assert lab.docker("wait", missing).stdout.strip() != "0"
    ident = lab.create(command, mounts=[(lab.secret, "/run/secrets/redis_password")])
    lab.wait_for(lambda: cli(lab, ident, "PING"), lambda v: v == "PONG")
    assert "NOAUTH" in cli(lab, ident, "PING", auth=False)
    assert "NOPERM" in cli(lab, ident, "CONFIG", "GET", "*")
    assert "NOPERM" in cli(lab, ident, "ACL", "LIST")
    assert cli(lab, ident, "SET", "formal:value", "unchanged") == "OK"
    assert cli(lab, ident, "GET", "formal:value") == "unchanged"
    assert cli(lab, ident, "LPUSH", "formal:queue", "one") == "1"
    assert cli(lab, ident, "BRPOP", "formal:queue", "1") == "formal:queue\none"
    assert cli(lab, ident, "DEL", "formal:value") == "1"


def test_redis_actual_helm_tls_replication_and_sentinel_failover(redis_lab):
    lab = redis_lab
    env = {**lab.env, "KUBECONFIG": str(lab.root / "no-kube"), "HELM_PLUGINS": str(lab.root / "no-plugins")}
    p = subprocess.run(["helm", "template", "formal", str(ROOT / "deploy/helm/nomosmart"), "-n", "formal",
        "--set", "redis.cluster.enabled=true,redis.cluster.replicas=2"], capture_output=True, text=True, check=True, env=env, timeout=30)
    (lab.root / "render.yaml").write_text(p.stdout)
    docs = list(yaml.safe_load_all(p.stdout))
    data = next(d for d in docs if d and d["kind"] == "StatefulSet" and d["metadata"]["name"].endswith("-redis"))
    sentinel = next(d for d in docs if d and d["kind"] == "Deployment" and d["metadata"]["name"].endswith("-redis-sentinel"))
    name = data["metadata"]["name"]
    aliases = [f"{name}-{i}.{name}-headless.formal.svc.cluster.local" for i in range(2)]
    cert, key = lab.certificates([*aliases, "localhost"])
    mounts = [(lab.secret, "/run/secrets/redis_password"), (cert, "/tls/tls.crt"),
              (cert, "/tls/ca.crt"), (key, "/tls/tls.key")]
    prefix = 'export REDIS_USERNAME=nomosmart REDIS_REPLICATION_USERNAME=nomosmart REDIS_SENTINEL_USERNAME=nomosmart; export REDIS_PASSWORD="$(cat /run/secrets/redis_password)"; export REDIS_REPLICATION_PASSWORD="$REDIS_PASSWORD" REDIS_SENTINEL_PASSWORD="$REDIS_PASSWORD"; '
    script = data["spec"]["template"]["spec"]["containers"][0]["args"][0]
    primary = lab.create(prefix + script, mounts=mounts, aliases=[aliases[0]], env=[("POD_NAME", name + "-0")])
    replica = lab.create(prefix + script, mounts=mounts, aliases=[aliases[1]], env=[("POD_NAME", name + "-1")])
    lab.wait_for(lambda: cli(lab, primary, "PING", tls=True), lambda v: v == "PONG")
    lab.wait_for(lambda: cli(lab, replica, "INFO", "replication", tls=True), lambda v: "master_link_status:up" in v)
    assert "PONG" not in cli(lab, primary, "PING")
    assert "NOAUTH" in cli(lab, primary, "PING", tls=True, auth=False)
    assert cli(lab, primary, "SET", "formal:replication", "real", tls=True) == "OK"
    lab.wait_for(lambda: cli(lab, replica, "GET", "formal:replication", tls=True), lambda v: v == "real")
    sent_script = sentinel["spec"]["template"]["spec"]["containers"][0]["args"][0]
    sent = lab.create(prefix + sent_script, mounts=mounts)
    sent2 = lab.create(prefix + sent_script, mounts=mounts)
    lab.wait_for(lambda: cli(lab, sent, "SENTINEL", "get-master-addr-by-name", "nomosmart", tls=True, port=26379),
                 lambda v: v == aliases[0] + "\n6379")
    for monitor in (sent, sent2):
        lab.wait_for(lambda: cli(lab, monitor, "SENTINEL", "replicas", "nomosmart", tls=True, port=26379),
                     lambda v: aliases[1] in v and "master-link-status\nok" in v)
    lab.docker("stop", "-t", "5", primary)
    lab.wait_for(lambda: cli(lab, sent, "SENTINEL", "get-master-addr-by-name", "nomosmart", tls=True, port=26379),
                 lambda v: v == aliases[1] + "\n6379", seconds=75)
    assert cli(lab, replica, "SET", "formal:after-failover", "real", tls=True) == "OK"
    assert cli(lab, replica, "GET", "formal:replication", tls=True) == "real"


def test_rustfs_nonroot_final_image_secret_tls_and_s3():
    lab = Lab("rustfs")
    try:
        cert, key = lab.certificates(["rustfs", "localhost"])
        access = lab.file("access", "chg301testaccess")
        mounts = [(access, "/run/secrets/s3_access_key_id"), (lab.secret, "/run/secrets/rustfs_secret_access_key"),
            (cert, "/tls/rustfs_cert.pem"), (cert, "/tls/rustfs_ca.pem"), (key, "/tls/rustfs_key.pem")]
        env = [("RUSTFS_TLS_PATH", "/tls"), ("RUSTFS_ADDRESS", ":9000"),
            ("RUSTFS_CONSOLE_ENABLE", "false"),
            ("NOMOSMART_SECRET_EXPORTS", "RUSTFS_ACCESS_KEY:/run/secrets/s3_access_key_id,RUSTFS_SECRET_KEY:/run/secrets/rustfs_secret_access_key")]
        missing = lab.create("", env=env, entry="/opt/nomosmart/secret-env-entrypoint.sh",
                             args=["/entrypoint.sh", "rustfs", "/data"])
        assert lab.docker("wait", missing).stdout.strip() == "66"
        ident = lab.create("", mounts=mounts, env=env, aliases=["rustfs"], entry="/opt/nomosmart/secret-env-entrypoint.sh",
                           args=["/entrypoint.sh", "rustfs", "/data"])
        curl = ["--cacert", "/tls/rustfs_ca.pem", "--resolve", "rustfs:9000:127.0.0.1", "--max-time", "5", "-fsS"]
        lab.wait_for(lambda: lab.docker("exec", ident, "curl", *curl, "https://rustfs:9000/health", check=False).returncode,
                     lambda v: v == 0, seconds=60)
        assert lab.docker("exec", ident, "id", "-u").stdout.strip() == "10001"
        unsigned = lab.docker("exec", ident, "curl", *curl, "https://rustfs:9000/", check=False)
        assert unsigned.returncode == 22 and "403" in unsigned.stderr
        wrong_host = lab.docker("exec", ident, "curl", "--cacert", "/tls/rustfs_ca.pem", "--max-time", "5",
            "--resolve", "wrong-host:9000:127.0.0.1", "-fsS", "https://wrong-host:9000/health", check=False)
        assert wrong_host.returncode == 60
        def request(method, path, payload=None):
            args = [*curl, "--aws-sigv4", "aws:amz:us-east-1:s3", "-X", method]
            if payload is not None:
                args += ["--data-binary", payload]
            args += ["https://rustfs:9000/" + path]
            return lab.docker("exec", ident, "/bin/sh", "-ec",
                'access="$(cat /run/secrets/s3_access_key_id)"; secret="$(cat /run/secrets/rustfs_secret_access_key)"; exec curl --user "$access:$secret" "$@"', "sh", *args).stdout
        request("PUT", "formal-test-bucket")
        request("PUT", "formal-test-bucket/item", "retained-original-business-text")
        assert request("GET", "formal-test-bucket/item") == "retained-original-business-text"
        request("DELETE", "formal-test-bucket/item")
        request("DELETE", "formal-test-bucket")
    finally:
        lab.close()
