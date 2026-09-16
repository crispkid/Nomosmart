"""CHG-301 real isolated Docker/process tests. Never reads deployed configuration.

Opt in with CHG301_ISOLATED=1 after approval. All resources are journalled and
label-checked before exact cleanup. No mock process, provider, host port or socket.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
LABEL = "nomosmart.chg301.test"
SHARED = "/opt/nomosmart/secret-env-entrypoint.sh"
PREPARE = "/opt/nomosmart/compose-secret-entrypoint.sh"
TAGS = {"migration": "nomosmart/migrations:chg301-test",
        "postgresql": "nomosmart/postgresql:chg301-test",
        "rustfs": "nomosmart/rustfs:chg301-test",
        "backend": "nomosmart/backend:0.1.0-chg300",
        "keycloak": "nomosmart/keycloak:26.0.8"}


class Lab:
    def __init__(self):
        assert os.environ.get("CHG301_ISOLATED") == "1", "explicit isolated-test opt in required"
        self.root = Path(tempfile.mkdtemp(prefix="chg301-", dir="/private/tmp"))
        self.root.chmod(0o700)
        self.run = "chg301-" + secrets.token_hex(6)
        self.started = time.monotonic()
        self.cleaning = False
        self.containers, self.volumes, self.files = [], [], []
        self.secret_values = []
        self.results = []
        self.baseline = self.docker("ps", "-aq", "--no-trunc").stdout.split()
        self.images = {k: self.inspect("image", v)["Id"] for k, v in TAGS.items()}
        info = json.loads(self.docker("info", "--format", "{{json .}}").stdout)
        assert info["NCPU"] >= 4 and info["MemTotal"] >= 8 * 1024**3
        self.network = self.docker("network", "create", "--internal", "--label", f"{LABEL}={self.run}", self.run).stdout.strip()
        self.save()

    def docker(self, *args, check=True, data=None, timeout=120):
        assert self.cleaning or time.monotonic() - self.started < 90 * 60, "isolated batch budget exhausted"
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
        result = subprocess.run(["docker", "--context", "desktop-linux", *args], input=data,
                                capture_output=True, text=True, timeout=min(timeout, 1200), env=env)
        for value in self.secret_values:
            result.stdout = result.stdout.replace(value, "[REDACTED]")
            result.stderr = result.stderr.replace(value, "[REDACTED]")
            if len(value) > 24:
                for fragment in (value[:12], value[-12:]):
                    result.stdout = result.stdout.replace(fragment, "[REDACTED]")
                    result.stderr = result.stderr.replace(fragment, "[REDACTED]")
        if check:
            assert result.returncode == 0, f"docker {args[0]}: {result.stderr[-1800:]}"
        return result

    def inspect(self, kind, ident):
        return json.loads(self.docker(kind, "inspect", ident).stdout)[0]

    def save(self):
        evidence = {"run": self.run, "network": self.network, "containers": self.containers,
                    "volumes": self.volumes, "images": self.images, "results": self.results,
                    "baseline_container_ids": self.baseline}
        evidence["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ROOT / "deploy/docker/secret-env-entrypoint.sh", ROOT / "deploy/docker/compose-secret-entrypoint.sh",
                      ROOT / "docker-compose.yml", Path(__file__), ROOT / "deploy/package/nomosmart_package.py"]}
        p = self.root / "journal.json"
        p.write_text(json.dumps(evidence, indent=2)); p.chmod(0o600)

    def file(self, name, value=None, mode=0o600):
        p = self.root / name
        if value is None:
            value = "Chg301!" + secrets.token_urlsafe(32)
            self.secret_values.append(value)
        p.write_text(value); p.chmod(mode)
        self.files.append(p)
        return p

    def create(self, image, command, *, entry=PREPARE, uid="0:0", env=None,
               mounts=(), extra=(), tmpfs=True, memory="512m"):
        args = ["create", "--pull=never", "--label", f"{LABEL}={self.run}",
                "--network", self.network, "--cpus=1", f"--memory={memory}",
                f"--memory-swap={memory}", "--pids-limit=256", "--user", uid,
                "--log-opt", "max-size=2m", "--log-opt", "max-file=1"]
        if tmpfs:
            args += ["--tmpfs", "/run/nomosmart:rw,noexec,nosuid,nodev,size=16m,mode=0700"]
        for k, v in (env or {}).items():
            args += ["-e", f"{k}={v}"]  # Tests pass file paths/config, not credentials.
        for source, target in mounts:
            source = Path(source)
            assert source.is_relative_to(self.root) or source in {
                ROOT / "deploy/docker/secret-env-entrypoint.sh",
                ROOT / "deploy/docker/compose-secret-entrypoint.sh"}
            args += ["--mount", f"type=bind,source={source},target={target},readonly"]
        if entry:
            args += ["--entrypoint", entry]
        args += list(extra) + [self.images[image], *command]
        ident = self.docker(*args).stdout.strip()
        self.containers.append(ident)
        info = self.inspect("container", ident)
        assert not info["HostConfig"]["Privileged"] and not info["HostConfig"]["PortBindings"]
        for mount in info["Mounts"]:
            if mount["Type"] == "volume":
                # Docker image-declared fresh anonymous volumes are owned only by
                # this just-created container; their exact IDs are retained.
                assert not self.docker("ps", "-aq", "--filter", f"volume={mount['Name']}").stdout.strip().replace(ident[:12], "")
                self.volumes.append(mount["Name"])
        self.save()
        self.docker("start", ident)
        return ident

    def finished(self, ident, expected=0):
        code = int(self.docker("wait", ident, timeout=1200).stdout.strip())
        logs = self.docker("logs", ident, check=False)
        self.results.append({"container": ident, "exit": code, "expected": expected})
        self.save()
        assert code == expected, (code, (logs.stdout + logs.stderr)[-2200:])
        return logs.stdout + logs.stderr

    def remove(self, ident):
        info = self.inspect("container", ident)
        assert info["Config"]["Labels"].get(LABEL) == self.run and ident not in self.baseline
        self.docker("rm", "-f", ident)

    def cleanup(self):
        # Expiring a test budget must never disable exact owned cleanup.
        self.cleaning = True
        for ident in reversed(self.containers):
            if self.docker("container", "inspect", ident, check=False).returncode == 0:
                self.remove(ident)
        for volume in self.volumes:
            assert not self.docker("ps", "-aq", "--filter", f"volume={volume}").stdout.strip()
            self.docker("volume", "rm", volume)
        net = self.inspect("network", self.network)
        assert net["Labels"].get(LABEL) == self.run and not net.get("Containers")
        self.docker("network", "rm", self.network)
        current = self.docker("ps", "-aq", "--no-trunc").stdout.split()
        assert set(current) == set(self.baseline), "container inventory drift"
        for p in reversed(self.files):
            assert p.parent == self.root and p.name != "journal.json"
            p.unlink(missing_ok=True)
        self.results.append({"cleanup": "exact owned containers/volumes/network/private files removed"})
        self.save()
        print(f"CHG301 redacted evidence: {self.root / 'journal.json'}")


@pytest.fixture(scope="module")
def lab():
    lab = Lab()
    try:
        yield lab
    finally:
        lab.cleanup()


def test_real_private_copy_uid_mode_umask_and_repeat_prepare(lab):
    secret = lab.file("copy.secret")
    before = hashlib.sha256(secret.read_bytes()).hexdigest()
    body = """set -eu
test "$(id -u)" = 10001
test "$(umask)" = 0027
test "$(stat -c %a /run/nomosmart/secrets/database_migration_password)" = 400
test "$(stat -c %u /run/nomosmart/secrets/database_migration_password)" = 10001
test "$(stat -c %a /run/nomosmart/secrets)" = 710
test "$(stat -c %u /run/nomosmart/secrets)" = 0
test -n "$FLYWAY_PASSWORD"
test ! -w /run/nomosmart/secrets
sha256sum /run/nomosmart/secrets/database_migration_password
"""
    # Invoke the actual wrapper twice inside the same tmpfs to exercise reuse.
    script = lab.file("copy-check.sh", body, 0o644)
    command = ["-c", f'umask 0027; {PREPARE} migration sh /test.sh && exec {PREPARE} migration sh /test.sh']
    ident = lab.create("migration", command, entry="/bin/sh",
        env={"NOMOSMART_SECRET_EXPORTS": "FLYWAY_PASSWORD:/run/secrets/database_migration_password"},
        mounts=[(secret, "/run/secrets/database_migration_password"), (script, "/test.sh")])
    output = lab.finished(ident)
    assert output.count(before) == 2
    assert secret.stat().st_mode & 0o777 == 0o600 and hashlib.sha256(secret.read_bytes()).hexdigest() == before
    lab.remove(ident)


def test_candidate_images_contain_exact_entrypoints_and_sql(lab):
    expected = [hashlib.sha256((ROOT / "deploy/docker" / name).read_bytes()).hexdigest()
                for name in ("secret-env-entrypoint.sh", "compose-secret-entrypoint.sh")]
    for image in ("migration", "postgresql", "rustfs"):
        ident = lab.create(image, ["-c", f"sha256sum {SHARED} {PREPARE}"], entry="/bin/sh", tmpfs=False)
        assert [line.split()[0] for line in lab.finished(ident).splitlines()] == expected
        lab.remove(ident)
    ident = lab.create("migration", ["-c", "sha256sum /flyway/sql/*.sql"], entry="/bin/sh", tmpfs=False)
    actual = {Path(line.split()[1]).name: line.split()[0] for line in lab.finished(ident).splitlines()}
    assert actual == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "sql/migrations").glob("*.sql")}
    lab.remove(ident)


def test_existing_backend_application_matches_current_main(lab):
    paths = ["app/core/config.py", "app/deployment/bootstrap.py", "app/deployment/migration_gate.py",
             "app/worker.py", "app/db/session.py"]
    ident = lab.create("backend", ["-c", "sha256sum " + " ".join("/app/" + p for p in paths)],
                       entry="/bin/sh", uid="10001:10001", tmpfs=False)
    assert [line.split()[0] for line in lab.finished(ident).splitlines()] == [
        hashlib.sha256((ROOT / "backend" / p).read_bytes()).hexdigest() for p in paths]
    lab.remove(ident)


@pytest.mark.parametrize("case,code", [("empty", 66), ("symlink", 66), ("missing", 66),
    ("traversal", 64), ("outside", 64), ("legacy", 64), ("no_tmpfs", 64),
    ("not_root", 64), ("profile", 64), ("bad_mapping", 64)])
def test_real_preparation_rejects_unsafe_inputs(lab, case, code):
    secret = lab.file("reject-" + case, "" if case == "empty" else None)
    env = {"NOMOSMART_SECRET_EXPORTS": "FLYWAY_PASSWORD:/run/secrets/database_migration_password"}
    command = ["migration", "/bin/sh", "-c", "exit 0"]
    if case == "symlink":
        # Create a real symlink *inside* an isolated container, not a fake reader.
        command = ["-c", f"mkdir /run/secrets; ln -s /input /run/secrets/database_migration_password; exec {PREPARE} migration sh -c 'exit 0'"]
        mounts = [(secret, "/input")]
    else:
        mounts = [(secret, "/run/secrets/database_migration_password")]
    if case == "missing": env["NOMOSMART_SECRET_EXPORTS"] = "FLYWAY_PASSWORD:/run/secrets/absent"
    if case == "traversal": env["DATABASE_URL_FILE"] = "/run/secrets/../input"
    if case == "outside": env["DATABASE_URL_FILE"] = "/etc/passwd"
    if case == "legacy": env["NOMOSMART_RUN_AS"] = "0:0"
    if case == "profile": command[0] = "arbitrary"
    if case == "bad_mapping": env["NOMOSMART_SECRET_EXPORTS"] = "1BAD:/run/secrets/database_migration_password"
    ident = lab.create("migration", command, env=env, mounts=mounts,
        entry="/bin/sh" if case == "symlink" else PREPARE,
        uid="10001:10001" if case == "not_root" else "0:0", tmpfs=case != "no_tmpfs")
    lab.finished(ident, code)
    lab.remove(ident)


def test_real_shared_entrypoint_works_nonroot_without_preparation(lab):
    ident = lab.create("migration", ["flyway", "-v"], entry=SHARED, uid="10001:10001",
        extra=["--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only", "--tmpfs", "/tmp:size=64m"], tmpfs=False)
    assert "13.6.0" in lab.finished(ident)
    lab.remove(ident)


def test_real_original_pr_nonroot_regression(lab):
    original = subprocess.run(["git", "show", "c261a494283835af57c0e0678afc7ee7e2c0dcc8:deploy/docker/secret-env-entrypoint.sh"],
                              cwd=ROOT, capture_output=True, text=True, check=True).stdout
    script = lab.file("original-pr-entrypoint.sh", original, 0o555)
    ident = lab.create("migration", ["flyway", "-v"], entry="/original.sh", uid="10001:10001",
        env={"NOMOSMART_RUN_AS": "10001:10001"}, mounts=[(script, "/original.sh")],
        extra=["--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only"], tmpfs=False)
    assert "privilege drop requires root" in lab.finished(ident, 64)
    lab.remove(ident)


def test_real_rustfs_tls_nonroot_startup_and_signal(lab):
    key = lab.file("rustfs-test.key", "")
    cert = lab.file("rustfs-test.crt", "")
    result = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=rustfs",
        "-addext", "subjectAltName=DNS:rustfs"], capture_output=True, timeout=30)
    assert result.returncode == 0
    key.chmod(0o600); cert.chmod(0o600)
    access = lab.file("rustfs-test-access")
    password = lab.file("rustfs-test-password")
    ident = lab.create("rustfs", ["rustfs", "/entrypoint.sh", "rustfs", "/data"],
        env={"NOMOSMART_SECRET_EXPORTS": "RUSTFS_ACCESS_KEY:/run/secrets/s3_access_key_id,RUSTFS_SECRET_KEY:/run/secrets/rustfs_secret_access_key"},
        mounts=[(access, "/run/secrets/s3_access_key_id"), (password, "/run/secrets/rustfs_secret_access_key"),
                (key, "/opt/rustfs-tls/rustfs_key.pem"), (cert, "/opt/rustfs-tls/rustfs_cert.pem"),
                (cert, "/opt/rustfs-tls/rustfs_ca.pem")],
        extra=["--network-alias", "rustfs", "--mount", "type=volume,target=/data"], memory="1g")
    for _ in range(45):
        p = lab.docker("exec", ident, "curl", "--noproxy", "*", "--max-time", "3",
            "--cacert", "/opt/rustfs-tls/rustfs_ca.pem", "--resolve", "rustfs:9000:127.0.0.1",
            "-fsS", "https://rustfs:9000/health", check=False)
        if not p.returncode:
            break
        if not lab.inspect("container", ident)["State"]["Running"]:
            break
        time.sleep(1)
    else:
        raise AssertionError("isolated RustFS health timeout")
    logs = lab.docker("logs", ident, check=False)
    assert p.returncode == 0, (logs.stdout + logs.stderr)[-2000:]
    lab.docker("exec", ident, "sh", "-c", "test $(awk '/^Uid:/{print $2}' /proc/1/status) = 10001")
    lab.docker("stop", "-t", "15", ident)
    assert lab.inspect("container", ident)["State"]["ExitCode"] != 137, "SIGTERM was not handled before forced kill"
    lab.remove(ident)


def test_real_backend_settings_resolves_private_files_and_preserves_exit(lab):
    value = secrets.token_hex(32)
    lab.secret_values.append(value)
    secret = lab.file("backend.secret", value)
    ca = lab.file("backend-ca.pem", "isolated byte-preservation test CA, no network operation\n")
    check = lab.file("backend-check.py", """import os, pathlib, stat
from app.core.config import Settings
assert os.getuid() == 10001
s = Settings(_env_file=None)
assert s.compose_secret_mount_root == '/run/nomosmart/secrets'
assert s.app_encryption_key.get_secret_value() == pathlib.Path(os.environ['APP_ENCRYPTION_KEY_FILE']).read_text()
assert os.environ['S3_CA_CERT_PATH'] == '/run/nomosmart/tls/rustfs-ca.crt'
assert stat.S_IMODE(pathlib.Path(os.environ['S3_CA_CERT_PATH']).stat().st_mode) == 0o400
raise SystemExit(23)
""", 0o644)
    mounts = [(secret, "/run/secrets/app_encryption_key"), (ca, "/etc/nomosmart/tls/rustfs-ca.crt"),
              (ca, "/etc/nomosmart/tls/opensearch-ca.crt"), (check, "/test.py"),
              (ROOT / "deploy/docker/secret-env-entrypoint.sh", SHARED),
              (ROOT / "deploy/docker/compose-secret-entrypoint.sh", PREPARE)]
    ident = lab.create("backend", ["backend", "python", "/test.py"], mounts=mounts,
        env={"APP_ENV": "test", "PYTHONPATH": "/app", "APP_ENCRYPTION_KEY_FILE": "/run/secrets/app_encryption_key",
             "COMPOSE_SECRET_MOUNT_ROOT": "/run/secrets", "S3_CA_CERT_PATH": "/etc/nomosmart/tls/rustfs-ca.crt"})
    lab.finished(ident, 23)
    lab.remove(ident)


def test_existing_keycloak_compose_0600_startup_contract(lab):
    """Read-only-command prerequisite: no realm or external connection is made."""
    password = lab.file("keycloak-startup-test.secret")
    info = lab.inspect("image", lab.images["keycloak"])
    ident = lab.create("keycloak", ["--version"], entry=None,
        uid=info["Config"].get("User", "1000"), tmpfs=False,
        env={"NOMOSMART_SECRET_EXPORTS": "KC_BOOTSTRAP_ADMIN_PASSWORD:/run/secrets/keycloak_bootstrap_admin_password"},
        mounts=[(password, "/run/secrets/keycloak_bootstrap_admin_password"),
                (ROOT / "deploy/docker/secret-env-entrypoint.sh", SHARED)])
    lab.finished(ident)
    lab.remove(ident)


def test_real_postgres_restart_and_nonroot_flyway_v049(lab):
    mappings = {"POSTGRES_PASSWORD_FILE": "postgres_admin_password",
                "NOMOSMART_DB_PASSWORD_FILE": "postgres_app_password",
                "NOMOSMART_MIGRATION_PASSWORD_FILE": "postgres_migration_password",
                "KEYCLOAK_DB_PASSWORD_FILE": "keycloak_db_password"}
    paths = {name: lab.file(name) for name in mappings.values()}
    env = {k: "/run/secrets/" + v for k, v in mappings.items()}
    env.update(POSTGRES_DB="postgres", POSTGRES_USER="postgres", NOMOSMART_DB="nomosmart",
               NOMOSMART_DB_USER="nomosmart", NOMOSMART_MIGRATION_USER="migrator",
               KEYCLOAK_DB="identity_test", KEYCLOAK_DB_USER="identity_test")
    ident = lab.create("postgresql", ["postgresql", "docker-entrypoint.sh", "postgres"],
        env=env, mounts=[(p, "/run/secrets/" + name) for name, p in paths.items()],
        extra=["--network-alias", "postgresql"], memory="1g")
    def query(sql):
        return lab.docker("exec", "-i", ident, "psql", "-X", "-U", "postgres", "-d", "nomosmart",
                          "-v", "ON_ERROR_STOP=1", "-Atq", data=sql).stdout.strip()
    def ready():
        for _ in range(90):
            p = lab.docker("exec", ident, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False)
            if not p.returncode:
                return
            time.sleep(1)
        logs = lab.docker("logs", ident, check=False)
        raise AssertionError("isolated PostgreSQL not ready: " + (logs.stdout + logs.stderr)[-1800:])
    ready()
    assert query("SELECT current_user") == "postgres"
    assert lab.docker("exec", ident, "sh", "-c", "test $(awk '/^Uid:/{print $2}' /proc/1/status) = $(id -u postgres)").returncode == 0
    url = "postgresql+psycopg2://nomosmart:" + paths["postgres_app_password"].read_text() + "@postgresql:5432/nomosmart"
    database = lab.file("isolated-database-url", url)
    ca = lab.file("gate-ca.pem", "isolated test CA; database gate fails before TLS dependencies\n")
    backend_mounts = [(database, "/run/secrets/database_url"),
        (ca, "/etc/nomosmart/tls/rustfs-ca.crt"), (ca, "/etc/nomosmart/tls/opensearch-ca.crt"),
        (ROOT / "deploy/docker/secret-env-entrypoint.sh", SHARED),
        (ROOT / "deploy/docker/compose-secret-entrypoint.sh", PREPARE)]
    gate_env = {"APP_ENV": "test", "DATABASE_URL_FILE": "/run/secrets/database_url",
                "MIGRATION_REQUIRED_VERSION": "049", "MIGRATION_REQUIRED_CHECKSUM": "-1579162252",
                "DEPLOYMENT_BOOTSTRAP_RELEASE": lab.run}
    def bootstrap_reject(code, **changes):
        container = lab.create("backend", ["backend", "python", "-m", "app.deployment.bootstrap",
            "--mode", "check", "--wait-seconds", "0"], env=gate_env | changes, mounts=backend_mounts)
        assert code in lab.finished(container, 1)
        lab.remove(container)
    bootstrap_reject("database_migration_history_missing")
    migration = lab.create("migration", ["migration", "flyway", "-url=jdbc:postgresql://postgresql:5432/nomosmart",
        "-user=migrator", "-connectRetries=5", "-validateMigrationNaming=true", "migrate"],
        env={"NOMOSMART_SECRET_EXPORTS": "FLYWAY_PASSWORD:/run/secrets/database_migration_password"},
        mounts=[(paths["postgres_migration_password"], "/run/secrets/database_migration_password")], memory="1g")
    lab.finished(migration)
    assert query("SELECT version || ':' || checksum || ':' || success FROM flyway_schema_history ORDER BY installed_rank DESC LIMIT 1") == "049:-1579162252:true"
    bootstrap_reject("database_migration_checksum_mismatch", MIGRATION_REQUIRED_CHECKSUM="1")
    bootstrap_reject("database_migration_target_missing", MIGRATION_REQUIRED_VERSION="050")
    check = lab.file("gate-check.py", """from app.core.config import Settings
from app.deployment.migration_gate import verify_migration_database
from app.deployment.bootstrap import _bootstrap_evidence_check, BootstrapFailure
s = Settings(_env_file=None)
verify_migration_database(s)
try:
    _bootstrap_evidence_check(s)
except BootstrapFailure as exc:
    assert exc.code == 'deployment_evidence_missing'
else:
    raise AssertionError('missing real bootstrap evidence was accepted')
""", 0o644)
    container = lab.create("backend", ["backend", "python", "/gate-check.py"],
        env=gate_env | {"PYTHONPATH": "/app"}, mounts=backend_mounts + [(check, "/gate-check.py")])
    lab.finished(container)
    lab.remove(container)
    query("CREATE TABLE chg301_restart (value text); INSERT INTO chg301_restart VALUES ('preserved');")
    lab.docker("restart", ident, timeout=120)
    ready()
    assert query("SELECT value FROM chg301_restart") == "preserved"
    assert query("SELECT count(*) FROM flyway_schema_history WHERE success") == "49"
    lab.remove(migration)
    lab.remove(ident)
