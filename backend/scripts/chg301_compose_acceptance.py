"""Approved CHG-301 real Compose acceptance, isolated from the deployed system.

No external env, existing package, kubeconfig, host ports, Provider or Docker
socket mount. Data is bounded tmpfs; exact IDs/labels are checked at cleanup.
"""
from __future__ import annotations

import copy
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time

import yaml

ROOT = Path(__file__).resolve().parents[2]
LABEL = "nomosmart.chg301.compose-test"
APP_IMAGE = "nomosmart/backend:0.1.0-chg300"
IMAGES = {
    "backend": APP_IMAGE, "celery-worker": APP_IMAGE, "celery-beat": APP_IMAGE,
    "deployment-bootstrap": APP_IMAGE,
    "migration": "nomosmart/migrations:chg301-test",
    "postgresql": "nomosmart/postgresql:chg301-test",
    "rustfs": "nomosmart/rustfs:chg301-test",
    # Docker Desktop's preloaded copy is addressed by version+digest, not a
    # standalone tag; this is the same checked-in version, not a substitute.
    "redis": "redis:7.4.2-alpine@sha256:02419de7eddf55aa5bcf49efb74e88fa8d931b4d77c07eff8a6b2144472b6952",
    "neo4j": "neo4j:5.26.4-community",
    "keycloak": "nomosmart/keycloak:26.0.8",
    "opensearch": "opensearchproject/opensearch:2.19.1",
}
# Sum: 10.75GiB memory / 7 CPU. Data tmpfs maxima 6.75GiB in total.
LIMITS = {"postgresql": (1024, 0.5), "redis": (256, 0.25),
          "opensearch": (2048, 1.5), "neo4j": (1536, 1),
          "rustfs": (1024, 0.5), "keycloak": (1536, 1),
          "migration": (1024, 0.5), "deployment-bootstrap": (768, 0.5),
          "backend": (512, 0.5), "celery-worker": (768, 0.5), "celery-beat": (512, 0.25)}
DATA_TMPFS = {
    # Upstream creates/chmods PGDATA itself, then drops to postgres. The mount
    # parent must remain traversable, like the real image/volume parent.
    "postgres_data": "/var/lib/postgresql:rw,nosuid,nodev,size=2g,mode=0755",
    "redis_data": "/data:rw,nosuid,nodev,size=128m,mode=0755",
    "opensearch_data": "/usr/share/opensearch/data:rw,nosuid,nodev,size=2g,uid=1000,gid=1000,mode=0750",
    "neo4j_data": "/data:rw,nosuid,nodev,size=1g,mode=0755",
    "neo4j_logs": "/logs:rw,nosuid,nodev,size=128m,mode=0755",
    "rustfs_data": "/data:rw,nosuid,nodev,size=1g,uid=10001,gid=10001,mode=0700",
    "keycloak_data": "/opt/keycloak/data:rw,nosuid,nodev,size=512m,uid=1000,gid=0,mode=0700",
}
ALLOWED_REPO_BINDS = {
    ROOT / "deploy/docker/secret-env-entrypoint.sh",
    ROOT / "deploy/docker/compose-secret-entrypoint.sh",
    ROOT / "deploy/docker/ssh_known_hosts.example",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Acceptance:
    def __init__(self, scenario="startup"):
        assert os.environ.get("CHG301_ISOLATED") == "1", "explicit test opt-in required"
        self.root = Path(tempfile.mkdtemp(prefix="chg301-compose-", dir="/private/tmp"))
        self.root.chmod(0o700)
        self.run = "chg301-" + secrets.token_hex(6)
        self.scenario = scenario
        self.started = time.monotonic()
        self.cleaning = False
        self.secret_values = []
        self.containers, self.volumes, self.networks = {}, [], []
        self.stages, self.results = [], {}
        self.env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
        self.env.update(COMPOSE_DISABLE_ENV_FILE="1", COMPOSE_ENV_FILES="/dev/null")
        self.source = {str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__),
            ROOT / "docker-compose.yml", ROOT / "deploy/package/nomosmart_package.py",
            *sorted(ALLOWED_REPO_BINDS)]}
        self.compose_file = self.root / "compose.yaml"
        self.env_file = self.root / "test.env"
        self.baseline = self.docker("ps", "-aq", "--no-trunc").stdout.split()
        self.images = {}
        self.write_journal()

    def redact(self, value):
        for secret in sorted(self.secret_values, key=len, reverse=True):
            if len(secret) >= 8:
                value = value.replace(secret, "[REDACTED]")
                if len(secret) > 24:
                    value = value.replace(secret[:12], "[REDACTED]").replace(secret[-12:], "[REDACTED]")
        return value

    def process(self, command, *, timeout=120, check=True, data=None):
        if not self.cleaning:
            assert time.monotonic() - self.started < 90 * 60, "batch limit exceeded"
        result = subprocess.run(command, cwd=self.root, env=self.env, input=data,
            capture_output=True, text=True, timeout=min(timeout, 1200))
        # Preserve exact internal JSON identities. Redact only at the logging /
        # artifact boundary; a factory password may equal a service's name.
        if check and result.returncode:
            raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode}): {self.redact(result.stdout + result.stderr)[-2400:]}")
        return result

    def docker(self, *args, **kwargs):
        return self.process(["docker", "--context", "desktop-linux", *args], **kwargs)

    def compose(self, *args, **kwargs):
        return self.docker("compose", "--env-file", str(self.env_file), "-p", self.run,
                           "-f", str(self.compose_file), *args, **kwargs)

    def inspect(self, kind, ident):
        return json.loads(self.docker(kind, "inspect", ident).stdout)[0]

    def stage(self, name):
        self.stages.append({"stage": name, "elapsed_seconds": round(time.monotonic() - self.started, 2)})
        self.write_journal()
        print(name, flush=True)

    def write_journal(self):
        payload = {"run": self.run, "scenario": self.scenario, "baseline_container_ids": self.baseline,
            "containers": self.containers, "volumes": self.volumes, "networks": self.networks,
            "source_sha256": self.source, "images": self.images,
            "stages": self.stages, "results": self.results}
        p = self.root / "journal.json"
        p.write_text(json.dumps(payload, indent=2)); p.chmod(0o600)

    def package(self):
        self.stage("Generate fresh isolated package and verify second-init byte identity")
        output = self.root / "package"
        command = [sys.executable, str(ROOT / "deploy/package/nomosmart_package.py"),
            "init", "--target", "compose", "--output-dir", str(output),
            "--profile", "factory_acceptance", "--app-env", "development", "--no-display"]
        self.process(command, timeout=120)
        self.current = output / "current"
        self.package_files = {str(p.relative_to(self.current)): sha(p)
            for p in self.current.rglob("*") if p.is_file()}
        for p in self.current.iterdir():
            if p.is_file() and p.name != "manifest.json":
                self.secret_values.append(p.read_text())
                assert p.stat().st_mode & 0o777 == 0o600
        self.process(command, timeout=120)
        assert self.package_files == {str(p.relative_to(self.current)): sha(p)
            for p in self.current.rglob("*") if p.is_file()}
        admin = (self.current / "opensearch_admin_password").read_text()
        service = (self.current / "opensearch_service_password").read_text()
        assert admin != service and len(admin) == len(service) == 64
        self.results["package_second_init_unchanged"] = True

    def prepare(self):
        self.stage("Validate existing exact image prerequisites and isolated resource budget")
        info = json.loads(self.docker("info", "--format", "{{json .}}").stdout)
        assert info["NCPU"] >= 8 and info["MemTotal"] >= 16 * 1024**3
        assert sum(m for m, _ in LIMITS.values()) < 16384 and sum(c for _, c in LIMITS.values()) < 8
        for name, tag in IMAGES.items():
            self.images[name] = self.inspect("image", tag)["Id"]
        self.package()
        network = self.docker("network", "create", "--internal", "--label", f"{LABEL}={self.run}", self.run).stdout.strip()
        self.networks.append(network); self.write_journal()
        raw = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        services = {}
        tls = self.current / "tls/active"
        config = {"MIGRATION_REQUIRED_VERSION": "049", "MIGRATION_REQUIRED_CHECKSUM": "-1579162252",
            "DEPLOYMENT_PHASE": "factory_acceptance", "DEPLOYMENT_BOOTSTRAP_RELEASE": self.run,
            "DEPLOYMENT_BOOTSTRAP_WAIT_SECONDS": "120", "APP_ENV": "development",
            "CELERY_WORKER_CONCURRENCY": "1", "NEO4J_HEAP_INITIAL_SIZE": "256m",
            "NEO4J_HEAP_MAX_SIZE": "512m", "OPENSEARCH_JAVA_OPTS": "-Xms512m -Xmx512m"}
        # A custom package output deliberately does not write the operator env.
        # Supply real local test custody/log references, not production alerts.
        config.update(BREAK_GLASS_RUNBOOK_URI=(ROOT / "docs/CHG-301-PR1-INTEGRATION-PLAN.md").as_uri(),
                      BREAK_GLASS_ALERTING_EVIDENCE=f"factory-terminal-acceptance:{self.run}:redacted-journal")
        if self.scenario == "bootstrap-failure":
            config["MIGRATION_REQUIRED_CHECKSUM"] = "1"  # Real DB contract must reject.
            config["DEPLOYMENT_BOOTSTRAP_WAIT_SECONDS"] = "0"
        for service in ("rustfs", "opensearch"):
            config.update({f"{service.upper()}_TLS_CERT_FILE": str(tls / f"{service}.crt"),
                f"{service.upper()}_TLS_KEY_FILE": str(tls / f"{service}.key"),
                f"{service.upper()}_TLS_CA_FILE": str(tls / f"{service}-ca.crt")})
        self.env_file.write_text("\n".join(f"{k}={v}" for k, v in config.items()) + "\n"); self.env_file.chmod(0o600)
        for name in IMAGES:
            service = copy.deepcopy(raw["services"][name])
            for key in ("profiles", "build", "env_file", "ports"):
                service.pop(key, None)
            service.update(image=self.images[name], pull_policy="never", restart="no",
                labels={LABEL: self.run}, networks=["application"],
                mem_limit=f"{LIMITS[name][0]}m", memswap_limit=f"{LIMITS[name][0]}m",
                cpus=LIMITS[name][1], pids_limit=512,
                logging={"driver": "json-file", "options": {"max-size": "2m", "max-file": "1"}})
            mounts = []
            for value in service.get("volumes", []):
                # Interpolated TLS mounts contain ':-'; their destination is after '}'.
                source = value.split("}", 1)[0] + "}" if value.startswith("${") else value.split(":", 1)[0]
                if source in DATA_TMPFS:
                    service.setdefault("tmpfs", []).append(DATA_TMPFS[source])
                elif source.startswith("./"):
                    path = (ROOT / source).resolve()
                    assert path in ALLOWED_REPO_BINDS
                    mounts.append(str(path) + value[len(source):])
                elif source.startswith("${SFTP_KNOWN_HOSTS_FILE"):
                    mounts.append(str(ROOT / "deploy/docker/ssh_known_hosts.example") + value[len(source):])
                else:
                    assert source.startswith("${RUSTFS_TLS_") or source.startswith("${OPENSEARCH_TLS_")
                    mounts.append(value)
            # Check the current shared helper even with an unchanged Keycloak image.
            if name == "keycloak":
                mounts.append(str(ROOT / "deploy/docker/secret-env-entrypoint.sh") + ":/opt/nomosmart/secret-env-entrypoint.sh:ro")
            service["volumes"] = mounts
            if "healthcheck" in service:
                service["healthcheck"].update(interval="5s", timeout="10s", retries=36)
            services[name] = service
        model = {"services": services, "networks": {"application": {"external": True, "name": self.run}},
                 "secrets": {name: {"file": str(self.current / name)} for name in raw["secrets"]}}
        if self.scenario == "migration-failure":
            # Real Flyway/PostgreSQL authentication fails; no fake migration Job
            # or hand-written history. The original package remains untouched.
            password = secrets.token_urlsafe(48)
            self.secret_values.append(password)
            bad = self.root / "negative-migration-password"
            bad.write_text(password); bad.chmod(0o600)
            model["secrets"]["database_migration_password"]["file"] = str(bad)
            services["migration"]["command"] = ["-connectRetries=0" if c.startswith("-connectRetries=") else c
                                                  for c in services["migration"]["command"]]
        self.compose_file.write_text(yaml.safe_dump(model, sort_keys=False)); self.compose_file.chmod(0o600)
        rendered = json.loads(self.compose("config", "--no-env-resolution", "--format", "json").stdout)
        for name, service in rendered["services"].items():
            assert not service.get("ports") and not service.get("build") and not service.get("env_file")
            assert service["image"] == self.images[name]
            for mount in service.get("volumes", []):
                assert mount["type"] == "bind" and mount["read_only"]
                path = Path(mount["source"])
                assert path.is_relative_to(self.root) or path in ALLOWED_REPO_BINDS
            assert set(service.get("depends_on", {})) <= set(IMAGES)
        self.results["render_sha256"] = hashlib.sha256(json.dumps(rendered, sort_keys=True).encode()).hexdigest()
        self.results["limits"] = {"memory_mib": sum(m for m, _ in LIMITS.values()),
                                  "cpus": sum(c for _, c in LIMITS.values()), "data_tmpfs_max_mib": 6912}
        self.write_journal()

    def discover(self):
        ids = self.docker("ps", "-aq", "--no-trunc", "--filter", f"label={LABEL}={self.run}").stdout.split()
        for ident in ids:
            assert ident not in self.baseline
            info = self.inspect("container", ident)
            labels = info["Config"]["Labels"]
            assert labels[LABEL] == self.run and labels["com.docker.compose.project"] == self.run
            service = labels["com.docker.compose.service"]
            assert service in IMAGES and info["Image"] == self.images[service]
            assert not info["HostConfig"]["PortBindings"] and not info["HostConfig"]["Privileged"]
            self.containers[service] = ident
            for mount in info["Mounts"]:
                if mount["Type"] == "volume":
                    # All declared data volumes should have been replaced by capped tmpfs.
                    if mount["Name"] not in self.volumes:
                        self.volumes.append(mount["Name"])
                    if not self.cleaning:
                        raise RuntimeError("unexpected anonymous volume outside tmpfs budget")
        self.write_journal()

    def record_status(self):
        status = {}
        for name, ident in self.containers.items():
            info = self.inspect("container", ident)
            status[name] = {"status": info["State"]["Status"], "exit": info["State"]["ExitCode"],
                "health": info["State"].get("Health", {}).get("Status"),
                "oom": info["State"]["OOMKilled"]}
            logs = self.docker("logs", "--tail", "180", ident, check=False)
            p = self.root / f"{name}.log"
            p.write_text(self.redact(logs.stdout + logs.stderr)); p.chmod(0o600)
        self.results["status"] = status
        self.write_journal()
        return status

    def execute(self):
        self.prepare()
        self.stage("Create only run-owned Compose containers; no build/pull/recreate")
        try:
            result = self.compose("create", "--no-build", "--pull", "never", check=False, timeout=120)
        finally:
            self.discover()
        assert result.returncode == 0, result.stderr[-2000:]
        self.stage("Start actual migration/bootstrap/Worker/Beat/Backend dependency chain")
        try:
            result = self.compose("up", "-d", "--no-build", "--pull", "never", "--no-recreate", check=False, timeout=600)
        finally:
            self.discover(); self.record_status()
        if self.scenario != "startup":
            assert result.returncode != 0, "real dependency failure did not reject Compose up"
            state = self.results["status"]
            failed = "migration" if self.scenario == "migration-failure" else "deployment-bootstrap"
            assert state[failed]["status"] == "exited" and state[failed]["exit"] != 0
            assert all(state[n]["status"] == "created" for n in ("backend", "celery-worker", "celery-beat"))
            if failed == "migration":
                assert state["deployment-bootstrap"]["status"] == "created"
                assert "password authentication failed" in (self.root / "migration.log").read_text()
            else:
                assert state["migration"]["status"] == "exited" and state["migration"]["exit"] == 0
                assert "migration_checksum_mismatch" in (self.root / "deployment-bootstrap.log").read_text()
            assert self.package_files == {str(p.relative_to(self.current)): sha(p)
                for p in self.current.rglob("*") if p.is_file()}
            self.results["negative_acceptance"] = "PASS"
            self.stage(f"Verified real {self.scenario}; downstream consumers never started")
            return
        assert result.returncode == 0, result.stderr[-2000:]
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = self.record_status()
            if any(s["oom"] or (s["status"] == "exited" and s["exit"]) for s in state.values()):
                raise RuntimeError("real service exited unsuccessfully; see redacted service logs")
            if all(state[n]["health"] == "healthy" for n in IMAGES if n not in ("migration", "deployment-bootstrap")):
                break
            time.sleep(5)
        else:
            raise RuntimeError("real stack readiness deadline exceeded")
        state = self.record_status()
        assert all(state[n]["status"] == "exited" and state[n]["exit"] == 0 for n in ("migration", "deployment-bootstrap"))
        self.stage("Verify actual Backend readiness and OpenSearch version/admin/service authentication")
        backend = self.containers["backend"]
        ready = json.loads(self.docker("exec", backend, "curl", "-fsS", "http://127.0.0.1:8000/api/v1/ready").stdout)
        assert ready["status"] == "ready"
        self.results["backend_readiness"] = ready
        for name, username, filename in (("opensearch", "admin", "opensearch_admin_password"),
                                         ("backend", "nomosmart", "opensearch_service_password")):
            # No password enters argv or an output artifact.
            script = ("printf 'user = \"" + username + ":%s\"\\n' \"$(cat /run/secrets/" + filename + ")\" | "
                "curl --config - --noproxy '*' --cacert " +
                ("/usr/share/opensearch/config/tls/opensearch_ca.pem" if name == "opensearch" else "/etc/nomosmart/tls/opensearch-ca.crt") +
                " -fsS https://opensearch:9200/")
            response = json.loads(self.docker("exec", self.containers[name], "sh", "-c", script).stdout)
            assert response["version"]["number"] == "2.19.1"
        self.results["opensearch_admin_and_service_auth"] = True
        self.stage("Repeat Compose up without replacement and verify package unchanged")
        before = dict(self.containers)
        self.compose("up", "-d", "--no-build", "--no-recreate", "--pull", "never", timeout=300)
        self.discover()
        assert self.containers == before
        assert self.package_files == {str(p.relative_to(self.current)): sha(p)
            for p in self.current.rglob("*") if p.is_file()}
        self.results["repeated_up_same_container_ids"] = True
        self.results["positive_acceptance"] = "PASS"
        self.write_journal()

    def cleanup(self):
        self.cleaning = True
        self.stage("Cleanup exact run-owned resources; leave redacted evidence only")
        # Discover even after interrupted or partially failed Compose creation.
        if self.images and self.compose_file.exists():
            self.discover()
        for name, ident in reversed(list(self.containers.items())):
            info = self.inspect("container", ident)
            assert info["Config"]["Labels"].get(LABEL) == self.run and ident not in self.baseline
            self.docker("rm", "-f", ident)
        for volume in self.volumes:
            assert not self.docker("ps", "-aq", "--filter", f"volume={volume}").stdout.strip()
            self.docker("volume", "rm", volume)
        for ident in self.networks:
            info = self.inspect("network", ident)
            assert info["Labels"].get(LABEL) == self.run and not info.get("Containers")
            self.docker("network", "rm", ident)
        assert set(self.docker("ps", "-aq", "--no-trunc").stdout.split()) == set(self.baseline)
        package = self.root / "package"
        if package.exists():
            # Only our freshly generated private package; reject symlink traversal.
            for p in sorted(package.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                assert p.is_relative_to(package) and not p.is_symlink()
                if p.is_file(): p.unlink()
                elif p.is_dir(): p.rmdir()
            package.rmdir()
        bad = self.root / "negative-migration-password"
        if bad.exists():
            assert bad.is_file() and not bad.is_symlink()
            bad.unlink()
        self.results["exact_cleanup"] = "PASS"
        self.write_journal()


def cleanup_journal(path):
    """Recover only this runner's exact temporary resources after interruption."""
    assert os.environ.get("CHG301_ISOLATED") == "1"
    path = Path(path)
    assert path.name == "journal.json" and path.parent.parent == Path("/private/tmp")
    assert path.parent.name.startswith("chg301-compose-") and not path.is_symlink() and not path.parent.is_symlink()
    assert path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o777 == 0o600
    state = json.loads(path.read_text())
    assert re.fullmatch(r"chg301-[a-f0-9]{12}", state["run"])
    lab = Acceptance.__new__(Acceptance)
    lab.root, lab.run = path.parent, state["run"]
    lab.scenario = state.get("scenario", "startup")
    lab.started, lab.cleaning = time.monotonic(), True
    lab.secret_values = []
    lab.env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    lab.env.update(COMPOSE_DISABLE_ENV_FILE="1", COMPOSE_ENV_FILES="/dev/null")
    lab.compose_file, lab.env_file = lab.root / "compose.yaml", lab.root / "test.env"
    lab.baseline = state["baseline_container_ids"]
    lab.source, lab.images = state["source_sha256"], state["images"]
    lab.containers, lab.volumes, lab.networks = state["containers"], state["volumes"], state["networks"]
    lab.stages, lab.results = state["stages"], state["results"]
    lab.cleanup()
    print(f"Recovered exact cleanup: {path}")
    return 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--cleanup-journal":
        return cleanup_journal(sys.argv[2])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("startup", "migration-failure", "bootstrap-failure"), default="startup")
    args = parser.parse_args()
    lab = Acceptance(args.scenario)
    code = 0
    try:
        lab.execute()
    except Exception as exc:
        code = 1
        lab.results["error"] = lab.redact(str(exc))
        lab.results["positive_acceptance" if lab.scenario == "startup" else "negative_acceptance"] = "FAIL"
        lab.write_journal()
        print(lab.results["error"], flush=True)
    finally:
        lab.cleanup()
        print(f"Redacted evidence: {lab.root / 'journal.json'}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
