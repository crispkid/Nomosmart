#!/usr/bin/env python3
"""Host-only Docker workflow. No shell evaluation, credential display or reset."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy/package"))
import nomosmart_package as package


class WorkflowError(RuntimeError):
    def __init__(self, code: int, reason: str, recovery: str):
        self.code, self.reason, self.recovery = code, reason, recovery
        super().__init__(reason)


def private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise WorkflowError(2, "INCOMPLETE_CONFIG", f"Restore the matching regular file: {path}")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise WorkflowError(2, "PRIVATE_FILE_PERMISSIONS", f"Restrict access to {path} (chmod 600).")


def read_env(path: Path) -> dict[str, str]:
    """Read literal deployment selectors; Compose resolves the full typed model."""
    private_file(path)
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)", line.strip())
        if not match or match[1] in values:
            raise WorkflowError(2, "INVALID_ENV", "Use unique KEY=value entries in nomosmart.env.")
        value = match[2].strip()
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise WorkflowError(2, "INVALID_ENV", "Close quoted values in nomosmart.env.")
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[match[1]] = value
    return values


def port(value: str | int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise WorkflowError(2, "INVALID_PORT", "Configure integer HTTP/HTTPS ports from 1 to 65535.") from None
    if str(result) != str(value) or not 1 <= result <= 65535:
        raise WorkflowError(2, "INVALID_PORT", "Configure integer HTTP/HTTPS ports from 1 to 65535.")
    return result


def selectors(values: dict[str, str]) -> dict:
    host = values.get("NOMOSMART_PUBLIC_HOST", package.DEFAULT_PUBLIC_HOST)
    try:
        if package._validate_public_host(host) != host:
            raise ValueError()
        project = values.get("COMPOSE_PROJECT_NAME", "nomosmart")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
            raise ValueError()
        address = values.get("EDGE_HOST_IP", "127.0.0.1")
        ipaddress.IPv4Address(address)
    except (ValueError, package.PackageError):
        raise WorkflowError(2, "INVALID_DEPLOYMENT_SELECTORS", "Use a valid lowercase hostname/project and IPv4 bind address.") from None
    http, https = port(values.get("EDGE_HTTP_PORT", "80")), port(values.get("EDGE_HTTPS_PORT", "443"))
    if http == https:
        raise WorkflowError(2, "INVALID_PORT", "HTTP and HTTPS ports must be distinct.")
    origin = f"https://{host}" + (f":{https}" if https != 443 else "")
    for key in ("NOMOSMART_PUBLIC_ORIGIN", "FRONTEND_APP_ORIGIN", "NEXT_PUBLIC_APP_ORIGIN"):
        if key in values and values[key] != origin:
            raise WorkflowError(2, "ORIGIN_MISMATCH", f"Align {key} with the configured hostname and HTTPS port.")
    return {"host": host, "project": project, "address": address, "http": http, "https": https, "origin": origin}


def safe_log(line: str, secret_values: list[str]) -> str:
    """Only operational fields survive; free-form text/content is not echoed."""
    for secret in secret_values:
        if secret:
            line = line.replace(secret, "[REDACTED]")
    try:
        record = json.loads(line)
    except ValueError:
        level = re.search(r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b", line)
        return json.dumps({"level": level[1] if level else "UNKNOWN", "message": "unstructured log content suppressed"})
    if not isinstance(record, dict):
        return json.dumps({"message": "unstructured log content suppressed"})
    allowed = {"timestamp", "level", "status_code", "latency_ms"}
    result = {}
    for key in allowed:
        value = record.get(key)
        if key in {"status_code", "latency_ms"} and isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
        elif key == "level" and value in {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL", "FATAL"}:
            result[key] = value
        elif key == "timestamp" and isinstance(value, str) and re.fullmatch(r"[0-9TZ:+. -]{1,40}", value):
            result[key] = value
    result["message"] = "operational fields only; free-form content suppressed"
    return json.dumps(result, ensure_ascii=False)


class Workflow:
    def __init__(self, root: Path = ROOT, timeout: int = 1800):
        self.root = root.resolve()
        self.env_file = self.root / "deploy/docker/nomosmart.env"
        self.current = self.root / "deploy/docker/generated/current"
        self.state_dir = self.root / "deploy/docker/.nomosmart-workflow"
        self.state_path = self.state_dir / "state.json"
        self.deadline = time.monotonic() + timeout
        self.stage = "DISCOVER"
        self.settings: dict = {}
        self.model: dict = {}
        self.manifest: dict = {}
        self.secret_values: list[str] = []
        self.state: dict = {}
        self.mutating = False
        self.child: subprocess.Popen | None = None
        # Explicit env-file must be the authority, including over ambient keys
        # that Compose can interpolate. Keep Docker connection/proxy settings.
        self.child_env = os.environ.copy()
        compose = (self.root / "docker-compose.yml").read_text()
        for key in set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", compose)) | {k for k in self.child_env if k.startswith("COMPOSE_")}:
            self.child_env.pop(key, None)
        self.child_env["PYTHONDONTWRITEBYTECODE"] = "1"

    def remaining(self, limit: float | None = None) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise WorkflowError(5, "TIMEOUT", "Correct the reported stage/dependency and rerun up, or choose a longer --timeout.")
        return min(left, limit) if limit else left

    def progress(self, stage: str) -> None:
        self.stage = stage
        print(json.dumps({"stage": stage}), flush=True)

    def stop_child(self) -> None:
        child = self.child
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            except ProcessLookupError:
                pass
        self.child = None

    def process(self, command: list[str], *, limit: float | None = 30, check: bool = True) -> tuple[int, str]:
        with tempfile.TemporaryFile() as output:
            try:
                self.child = subprocess.Popen(command, cwd=self.root, env=self.child_env,
                                              stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError:
                raise WorkflowError(2, "TOOL_UNAVAILABLE", f"Install/check the required tool: {Path(command[0]).name}") from None
            deadline = time.monotonic() + self.remaining(limit)
            announced = time.monotonic()
            try:
                while self.child.poll() is None:
                    if time.monotonic() >= deadline:
                        self.stop_child()
                        raise WorkflowError(5, "TIMEOUT", "Correct the reported stage/dependency and rerun up, or choose a longer --timeout.")
                    if time.monotonic() - announced >= 20:
                        print(json.dumps({"stage": self.stage, "status": "working"}), flush=True)
                        announced = time.monotonic()
                    time.sleep(0.15)
                code = self.child.returncode
                self.child = None
                output.seek(0)
                data = output.read(8 * 1024 * 1024).decode("utf-8", errors="replace")
            except BaseException:
                self.stop_child()
                raise
        if check and code:
            raise WorkflowError(4, "COMMAND_FAILED", "Check Docker connectivity, registry access and the current stage with status/logs; preserved resources may be resumed.")
        return code, data

    def docker(self, *arguments: str, **options) -> tuple[int, str]:
        return self.process(["docker", *arguments], **options)

    def compose(self, *arguments: str, **options) -> tuple[int, str]:
        return self.docker("compose", "--project-directory", str(self.root), "-f", str(self.root / "docker-compose.yml"),
                           "--env-file", str(self.env_file), "-p", self.settings["project"], *arguments, **options)

    def json_command(self, *arguments: str) -> object:
        _, data = self.docker(*arguments)
        try:
            return json.loads(data)
        except ValueError:
            raise WorkflowError(4, "INVALID_DOCKER_RESPONSE", "Check the Docker daemon and compatible Compose plugin.") from None

    @contextmanager
    def lock(self):
        if self.state_dir.is_symlink() or self.state_dir.parent.is_symlink():
            raise WorkflowError(2, "UNSAFE_STATE_PATH", "Use a regular deployment state directory.")
        self.state_dir.mkdir(mode=0o700, exist_ok=True)
        if self.state_dir.stat().st_uid != os.getuid():
            raise WorkflowError(3, "STATE_OWNERSHIP", "Use the deployment owner's account.")
        os.chmod(self.state_dir, 0o700)
        fd = os.open(self.state_dir / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkflowError(3, "BUSY", "Wait for the other up/down process to finish.") from None
            self.mutating = True
            yield
        finally:
            self.mutating = False
            os.close(fd)

    def load(self) -> None:
        values = read_env(self.env_file)
        self.settings = selectors(values)
        private_file(self.current / "manifest.json")
        try:
            self.manifest = package._safe_manifest(self.current / "manifest.json")
        except package.PackageError:
            raise WorkflowError(2, "INCOMPLETE_CONFIG", "Restore the matching generation manifest; do not regenerate existing secrets.") from None
        if self.manifest.get("target") != "compose" or self.manifest.get("app_env") != values.get("APP_ENV"):
            raise WorkflowError(2, "GENERATION_MISMATCH", "Restore environment and generation from the same installation.")
        secret_entries = self.manifest.get("secrets")
        if not isinstance(secret_entries, dict) or not secret_entries:
            raise WorkflowError(2, "INCOMPLETE_CONFIG", "Restore the complete generation manifest.")
        for name, entry in secret_entries.items():
            if not re.fullmatch(r"[a-z0-9_]+", name) or not isinstance(entry, dict) or entry.get("file") != name:
                raise WorkflowError(2, "INVALID_MANIFEST", "Restore a supported Compose generation manifest.")
            path = self.current / name
            private_file(path)
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                raise WorkflowError(2, "SECRET_MISMATCH", "Restore the matching secret files; rotate only through the explicit package workflow.")
            if name not in {"s3_access_key_id", "keycloak_bootstrap_admin_username", "database_migration_user", "flyway_jdbc_url"}:
                self.secret_values.append(data.decode().strip())
        if self.state_path.exists() or self.state_path.is_symlink():
            private_file(self.state_path)
            try:
                self.state = json.loads(self.state_path.read_text())
            except ValueError:
                raise WorkflowError(2, "INVALID_STATE", "Restore the private workflow metadata; preserve configuration and data.") from None
            expected = {"version": 1, "root": str(self.root), "env_file": str(self.env_file),
                        "project": self.settings["project"], "generation": self.manifest.get("generation_id")}
            if not isinstance(self.state, dict) or any(self.state.get(k) != v for k, v in expected.items()):
                raise WorkflowError(3, "BINDING_MISMATCH", "Use the bound directory/configuration; investigate explicit moves or rotations before starting.")
        _, data = self.compose("config", "--format", "json")
        try:
            self.model = json.loads(data)
        except ValueError:
            raise WorkflowError(2, "INVALID_COMPOSE", "Correct Compose configuration without dumping private environment values.") from None
        self.validate_model()

    def validate_model(self) -> None:
        services = self.model.get("services", {})
        required = {"migration", "deployment-bootstrap", "backend", "frontend", "edge", "celery-worker", "celery-beat"}
        if not required <= services.keys() or self.model.get("name") != self.settings["project"]:
            raise WorkflowError(2, "INCOMPLETE_SERVICE_SET", "Use the supplied Compose file with explicit installation profiles.")
        origin, issuer = self.settings["origin"], self.settings["origin"] + "/identity/realms/nomosmart"
        checks = {"frontend": {"FRONTEND_APP_ORIGIN": origin, "NEXT_PUBLIC_APP_ORIGIN": origin,
                               "FRONTEND_OIDC_ISSUER_URL": issuer, "NEXT_PUBLIC_OIDC_ISSUER_URL": issuer},
                  "backend": {"FRONTEND_APP_ORIGIN": origin, "OIDC_ISSUER_URL": issuer},
                  "edge": {"NOMOSMART_PUBLIC_ORIGIN": origin, "EDGE_HTTPS_PORT": str(self.settings["https"])}}
        if "keycloak" in services:
            checks["keycloak"] = {"KC_HOSTNAME": origin + "/identity"}
        for service, expected in checks.items():
            env = services[service].get("environment", {})
            if any(str(env.get(k)) != v for k, v in expected.items()):
                raise WorkflowError(2, "ORIGIN_MISMATCH", f"Align the public origin/issuer configuration for {service}.")
        cors = services["backend"].get("environment", {}).get("CORS_ALLOWED_ORIGINS", "")
        if origin not in [s.strip() for s in cors.split(",")]:
            raise WorkflowError(2, "ORIGIN_MISMATCH", "Include the exact public origin in CORS_ALLOWED_ORIGINS.")
        for entry in self.model.get("secrets", {}).values():
            path = Path(entry.get("file", ""))
            if path.parent != self.current or path.name not in self.manifest["secrets"]:
                raise WorkflowError(2, "SECRET_MOUNT_MISMATCH", "Use the verified generated/current secret mounts.")
        for service in services.values():
            for mount in service.get("volumes", []):
                if mount.get("type") == "bind" and not Path(mount["source"]).is_file():
                    # The only supported directory bind is the reviewed theme/SQL.
                    path = Path(mount["source"])
                    if not path.is_dir() or not path.is_relative_to(self.root):
                        raise WorkflowError(2, "MISSING_MOUNT", "Restore the required Compose bind file/directory before startup.")
        edge = services["edge"]
        mounts = {m["target"]: Path(m["source"]) for m in edge.get("volumes", []) if m.get("type") == "bind"}
        ca = self.current / "tls/active/edge-ca.crt"
        try:
            package._validate_edge_certificate_set(mounts["/etc/nginx/tls/tls.crt"].parent,
                                                   public_host=self.settings["host"], source="operator")
            ssl.create_default_context(cafile=str(ca))
        except (KeyError, OSError, ssl.SSLError, package.PackageError):
            raise WorkflowError(2, "INVALID_TLS", "Restore matching edge certificate/key/CA covering the public hostname; do not disable verification.") from None

    def inventory(self) -> dict[str, dict]:
        _, ids = self.docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + self.settings["project"])
        result = {}
        desktop = sys.platform == "darwin" and self.json_command("info", "--format", "{{json .}}").get("OperatingSystem") == "Docker Desktop"
        if ids.strip():
            for item in self.json_command("inspect", *ids.split()):
                labels = item.get("Config", {}).get("Labels", {})
                service = labels.get("com.docker.compose.service")
                config_files = labels.get("com.docker.compose.project.config_files", "").split(",")
                working = labels.get("com.docker.compose.project.working_dir", "")
                if service not in self.model["services"] or len(config_files) != 1 or Path(config_files[0]).resolve() != self.root / "docker-compose.yml" or Path(working).resolve() != self.root:
                    raise WorkflowError(3, "FOREIGN_PROJECT", "Choose another project name/directory; matching names alone do not establish ownership.")
                expected = self.model["services"][service]
                mounts = {m["Destination"]: m for m in item.get("Mounts", [])}
                declared = list(expected.get("volumes", []))
                declared += [{"type": "bind", "source": self.model["secrets"][s["source"]]["file"],
                              "target": (s.get("target", s["source"]) if s.get("target", "").startswith("/") else "/run/secrets/" + s.get("target", s["source"])), "read_only": True}
                             for s in expected.get("secrets", [])]
                for mount in declared:
                    actual = mounts.get(mount["target"], {})
                    if mount["type"] == "bind":
                        source = actual.get("Source", "/")
                        if desktop and source.startswith("/host_mnt/"):
                            source = source[len("/host_mnt"):]
                        if Path(source).resolve() != Path(mount["source"]).resolve() or actual.get("RW") != (not mount.get("read_only", False)):
                            raise WorkflowError(3, "MOUNT_DRIFT", f"Investigate the existing {service} mount ownership before up/down.")
                    elif mount["type"] == "volume":
                        wanted = self.model["volumes"][mount["source"]]["name"]
                        if actual.get("Name") != wanted:
                            raise WorkflowError(3, "VOLUME_DRIFT", f"Investigate the existing {service} data volume before up/down.")
                if service in result or labels.get("com.docker.compose.oneoff", "false").lower() == "true":
                    raise WorkflowError(3, "AMBIGUOUS_PROJECT", "Resolve one-off/duplicate containers before managing this installation.")
                result[service] = item
        for resource, inspect_cmd in (("volumes", ["volume", "inspect"]), ("networks", ["network", "inspect"])):
            for key, expected in self.model.get(resource, {}).items():
                if expected.get("external"):
                    continue
                code, data = self.docker(*inspect_cmd, expected["name"], check=False)
                if code:
                    continue
                try:
                    labels = json.loads(data)[0].get("Labels") or {}
                except (ValueError, IndexError):
                    raise WorkflowError(3, "INVALID_RESOURCE", "Investigate the existing Compose resource.") from None
                singular = "volume" if resource == "volumes" else "network"
                if labels.get("com.docker.compose.project") != self.settings["project"] or labels.get("com.docker.compose." + singular) != key:
                    raise WorkflowError(3, "FOREIGN_RESOURCE", "Choose another project or investigate existing named resources; they will not be changed.")
        return result

    def preflight(self, resources: dict[str, dict]) -> dict:
        host = self.settings["host"]
        try:
            addresses = {row[4][0] for row in socket.getaddrinfo(host, None, socket.AF_INET)}
        except OSError:
            raise WorkflowError(2, "DNS_UNAVAILABLE", f"Resolve {host} to the configured host; for local use add one 127.0.0.1 /etc/hosts entry or use --public-host localhost on fresh install.") from None
        if ipaddress.ip_address(self.settings["address"]).is_loopback and "127.0.0.1" not in addresses:
            raise WorkflowError(2, "DNS_MISMATCH", f"Resolve {host} to 127.0.0.1 for this loopback deployment.")
        edge = resources.get("edge", {})
        bound = edge.get("NetworkSettings", {}).get("Ports", {}) if edge.get("State", {}).get("Running") else {}
        for target, published in ((80, self.settings["http"]), (443, self.settings["https"])):
            own = any(p["HostIp"] == self.settings["address"] and int(p["HostPort"]) == published for p in (bound.get(f"{target}/tcp") or []))
            if own:
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    listener.bind((self.settings["address"], published))
            except PermissionError:
                if published >= 1024:
                    raise WorkflowError(2, "PORT_PROBE_PERMISSION", "Allow local port inspection for the configured bind address; no host settings were changed.") from None
                # macOS/Linux users may lack native low-port bind permission
                # while the Docker daemon can publish it. Inspect real listeners;
                # Docker remains the authoritative final bind, without takeover.
                code, listeners = self.process(["lsof", "-nP", f"-iTCP:{published}", "-sTCP:LISTEN", "-F", "n"], check=False)
                if code not in {0, 1} or (code == 1 and listeners.strip()):
                    raise WorkflowError(2, "PORT_PROBE_UNAVAILABLE", "Check local lsof listener inspection before publishing low ports.") from None
                if code == 0:
                    raise WorkflowError(3, "PORT_UNAVAILABLE", f"Free configured TCP port {published} or select a different port on fresh install; foreign processes will not be stopped.") from None
            except OSError:
                raise WorkflowError(3, "PORT_UNAVAILABLE", f"Free configured TCP port {published} or select a different port on fresh install; foreign processes will not be stopped.") from None
        info = self.json_command("info", "--format", "{{json .}}")
        free = "UNKNOWN"
        data_root = Path(info.get("DockerRootDir", "/nonexistent"))
        if info.get("OperatingSystem") != "Docker Desktop" and data_root.is_dir() and not self.child_env.get("DOCKER_HOST"):
            fs = os.statvfs(data_root)
            free = fs.f_bavail * fs.f_frsize
        return {"cpu": info.get("NCPU", "UNKNOWN"), "memory_bytes": info.get("MemTotal", "UNKNOWN"),
                "docker_data_free_bytes": free}

    def save(self, status: str, resources: dict[str, dict], **extra) -> None:
        if not self.mutating or not self.manifest or not self.settings:
            return
        state = {**self.state, "version": 1, "root": str(self.root), "env_file": str(self.env_file),
                 "project": self.settings["project"], "generation": self.manifest.get("generation_id"),
                 "origin": self.settings["origin"], "status": status, "stage": self.stage,
                 "containers": {k: v["Id"] for k, v in resources.items()}, **extra}
        fd, temporary = tempfile.mkstemp(prefix=".state-", dir=self.state_dir)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(state, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
            self.state = state
        finally:
            Path(temporary).unlink(missing_ok=True)

    def https_ready(self) -> bool:
        try:
            context = ssl.create_default_context(cafile=str(self.current / "tls/active/edge-ca.crt"))
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
            for path in ("/edge-health", "/login", "/api/backend/health", "/api/backend/ready"):
                with opener.open(self.settings["origin"] + path, timeout=self.remaining(3)) as response:
                    if response.status != 200:
                        return False
            issuer = self.settings["origin"] + "/identity/realms/nomosmart"
            with opener.open(issuer + "/.well-known/openid-configuration", timeout=self.remaining(3)) as response:
                discovery = json.loads(response.read(256 * 1024))
                return discovery.get("issuer") == issuer
        except (OSError, URLError, HTTPError, ValueError, ssl.SSLError):
            return False

    def configured(self, resources: dict[str, dict]) -> bool:
        for name, item in resources.items():
            expected = self.model["services"][name]
            actual = dict(pair.split("=", 1) for pair in item["Config"].get("Env", []) if "=" in pair)
            if any(actual.get(key) != str(value) for key, value in expected.get("environment", {}).items() if value is not None):
                return False
            if item["Config"].get("Image") != expected.get("image"):
                return False
        return True

    def classification(self, resources: dict[str, dict], *, probe: bool = True) -> str:
        if not resources:
            return "STOPPED"
        for name, item in resources.items():
            state = item["State"]
            if name in {"migration", "deployment-bootstrap", "opensearch-plugin-init"}:
                if state["Status"] == "exited" and state["ExitCode"]:
                    return "FAILED"
            elif state["Status"] in {"dead", "exited", "restarting"} or state.get("Health", {}).get("Status") == "unhealthy":
                return "FAILED"
        runtime = [v["State"] for k, v in resources.items() if k not in {"migration", "deployment-bootstrap", "opensearch-plugin-init"}]
        if runtime and all(s["Status"] in {"exited", "created"} for s in runtime):
            return "STOPPED"
        for name, service in self.model["services"].items():
            if name == "deployment-finalize":
                continue
            state = resources.get(name, {}).get("State", {})
            if name in {"migration", "deployment-bootstrap", "opensearch-plugin-init"}:
                if state.get("Status") != "exited" or state.get("ExitCode") != 0:
                    return "STARTING"
            elif not state.get("Running") or (service.get("healthcheck") and state.get("Health", {}).get("Status") != "healthy"):
                return "STARTING"
        return "READY" if self.configured(resources) and (not probe or self.https_ready()) else "STARTING"

    def wait(self, gate: str | None = None) -> dict[str, dict]:
        announced = 0.0
        while True:
            self.remaining()
            resources = self.inventory()
            if gate:
                state = resources.get(gate, {}).get("State", {})
                if state.get("Status") == "exited":
                    if state.get("ExitCode") != 0:
                        raise WorkflowError(4, "GATE_FAILED", f"Inspect the {gate} service/configuration; preserve data and rerun up after correcting the cause.")
                    return resources
            else:
                status = self.classification(resources)
                if status == "READY":
                    return resources
                if status == "FAILED":
                    failed = sorted(k for k, v in resources.items() if v["State"].get("Health", {}).get("Status") == "unhealthy" or v["State"].get("Status") in {"dead", "restarting"} or (v["State"].get("Status") == "exited" and v["State"].get("ExitCode")))
                    raise WorkflowError(4, "SERVICE_FAILED", "Inspect failed services: " + ", ".join(failed) + "; correct configuration then rerun up.")
            if time.monotonic() - announced >= 20:
                print(json.dumps({"stage": self.stage, "status": "waiting", "gate": gate}), flush=True)
                announced = time.monotonic()
            time.sleep(min(2, self.remaining()))

    def source_digest(self) -> str | None:
        if not (self.root / "frontend/Dockerfile").is_file() or not (self.root / "backend/Dockerfile").is_file():
            return None
        paths = set()
        for relative in ("frontend/src", "frontend/public", "frontend/scripts", "frontend/eslint-rules", "backend/app", "backend/vendor"):
            for path in (self.root / relative).rglob("*"):
                if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
                    paths.add(path)
        for relative in ("frontend/package.json", "frontend/package-lock.json", "frontend/Dockerfile", "frontend/next.config.ts", "frontend/tsconfig.json", "frontend/next-env.d.ts", "frontend/eslint.config.mjs", "frontend/.dockerignore", "backend/.dockerignore", "backend/migrate.py", "backend/Dockerfile", "backend/pyproject.toml", "backend/uv.lock", "backend/main.py", "backend/connection.py", "backend/models.py"):
            if (self.root / relative).is_file():
                paths.add(self.root / relative)
        digest = hashlib.sha256()
        for path in sorted(paths):
            digest.update(str(path.relative_to(self.root)).encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()

    def up(self, args) -> None:
        with self.lock():
            self.progress("PREFLIGHT")
            self.process(["openssl", "version"])
            self.docker("compose", "version", "--short")
            code, _ = self.docker("info", "--format", "{{.ServerVersion}}", check=False)
            if code:
                raise WorkflowError(2, "DAEMON_UNAVAILABLE", "Start/check the selected local Docker daemon before up.")
            fresh = not (self.env_file.exists() or self.env_file.is_symlink() or self.current.exists() or self.current.is_symlink())
            if fresh and self.current.parent.exists() and any(self.current.parent.iterdir()):
                raise WorkflowError(2, "UNKNOWN_GENERATION", "Inspect the incomplete generated directory; preserve its material and restore matching configuration before up.")
            if fresh:
                self.settings = selectors({"NOMOSMART_PUBLIC_HOST": args.public_host or package.DEFAULT_PUBLIC_HOST,
                                           "COMPOSE_PROJECT_NAME": args.project_name or "nomosmart",
                                           "EDGE_HTTP_PORT": str(args.http_port if args.http_port is not None else 80), "EDGE_HTTPS_PORT": str(args.https_port if args.https_port is not None else 443)})
                # Check names/ports before generating any credential material.
                _, existing = self.docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + self.settings["project"])
                if existing.strip():
                    raise WorkflowError(3, "FOREIGN_PROJECT", "Choose a different --project-name; do not overwrite an existing installation.")
                for resource in ("volume", "network"):
                    _, existing = self.docker(resource, "ls", "-q", "--filter", "label=com.docker.compose.project=" + self.settings["project"])
                    if existing.strip():
                        raise WorkflowError(3, "ORPHANED_PROJECT", "Restore the matching installation configuration or choose another project name; existing volumes/networks were preserved.")
                self.preflight({})
                self.progress("INITIALIZE")
                self.process([sys.executable, "-B", str(self.root / "deploy/package/nomosmart_package.py"), "init", "--target", "compose",
                              "--profile", "factory_acceptance", "--app-env", "development", "--no-display", "--random-initial-credentials",
                              "--public-host", self.settings["host"], "--compose-project", self.settings["project"],
                              "--http-port", str(self.settings["http"]), "--https-port", str(self.settings["https"])], limit=None)
            self.progress("CONFIG_VALIDATE")
            self.load()
            for key, value in (("host", args.public_host), ("project", args.project_name), ("http", args.http_port), ("https", args.https_port)):
                if value is not None and value != self.settings[key]:
                    raise WorkflowError(2, "EXISTING_CONFIG_CONFLICT", "First-install flags cannot change an existing installation; maintain its configuration explicitly.")
            resources = self.inventory()
            capacity = self.preflight(resources)
            print(json.dumps({"capacity": capacity}), flush=True)
            app_images = [self.model["services"][name]["image"] for name in ("frontend", "backend")]
            local_source_images = app_images == [f"nomosmart/{name}:local-{self.settings['project']}" for name in ("frontend", "backend")]
            digest = self.source_digest() if local_source_images or self.state.get("source_sha256") or args.build else None
            if args.build and any("@sha256:" in image for image in app_images):
                raise WorkflowError(2, "IMMUTABLE_IMAGE_BUILD", "Select reviewed local source image tags explicitly, or use the configured digest-pinned images without --build.")
            if digest and self.state.get("source_sha256") and digest != self.state["source_sha256"] and not args.build:
                raise WorkflowError(2, "SOURCE_CHANGED", "Run up --build to apply reviewed source changes; existing images/configuration have been preserved.")
            if self.classification(resources) == "READY" and not args.build:
                self.progress("READY")
                self.save("READY", resources, source_sha256=digest)
                self.summary("READY")
                return
            self.save("STARTING", resources)
            images_available = True
            if digest and not resources:
                for name in ("frontend", "backend"):
                    code, _ = self.docker("image", "inspect", self.model["services"][name]["image"], check=False)
                    images_available = images_available and code == 0
            if digest and (args.build or (local_source_images and (fresh or not images_available or (not resources and self.state.get("source_sha256") != digest)))):
                self.progress("BUILD")
                self.compose("build", "frontend", "backend", limit=None)
                self.save("STARTING", resources, source_sha256=digest)
            elif args.build:
                raise WorkflowError(2, "PACKAGE_NO_SOURCE", "Use the package's digest-pinned images; --build requires a source checkout.")
            self.progress("PULL")
            self.compose("pull", "--ignore-buildable", limit=None)
            # Compose skips buildable services even in a source-free package.
            # Resolve missing selected app images before any workload changes.
            for image in dict.fromkeys(app_images):
                code, _ = self.docker("image", "inspect", image, check=False)
                if code:
                    self.docker("pull", image, limit=None)
            base = [s for s in self.model["services"] if s not in {"migration", "deployment-bootstrap", "deployment-finalize", "backend", "frontend", "edge", "celery-worker", "celery-beat", "debug-ports"}]
            self.progress("START_DEPENDENCIES")
            if base:
                self.compose("up", "-d", "--no-build", *base, limit=None)
            self.progress("WAIT_MIGRATION")
            self.compose("up", "-d", "--no-build", "migration", limit=None)
            self.wait("migration")
            self.progress("WAIT_BOOTSTRAP")
            self.compose("up", "-d", "--no-build", "--no-deps", "deployment-bootstrap", limit=None)
            self.wait("deployment-bootstrap")
            self.progress("START")
            apps = [s for s in ("backend", "celery-worker", "celery-beat", "frontend", "edge", "debug-ports") if s in self.model["services"]]
            command = ["up", "-d", "--no-build", "--no-deps"]
            if args.build:
                command.append("--force-recreate")
            self.compose(*command, *apps, limit=None)
            self.progress("WAIT_READY")
            resources = self.wait()
            self.progress("READY")
            self.save("READY", resources, source_sha256=digest)
            self.summary("READY")

    def summary(self, status: str) -> dict:
        value = {"status": status, "project": self.settings["project"], "url": self.settings["origin"],
                 "initial_username": "nomosmart", "credential_file": str(self.current / "break_glass_initial_password"),
                 "ca_file": str(self.current / "tls/active/edge-ca.crt"),
                 "next_steps": ["Trust the local CA explicitly in your browser when using generated TLS.",
                                "Change the temporary password at first login; configure enterprise identity and AI models as needed."]}
        print(json.dumps(value, ensure_ascii=False), flush=True)
        return value

    def status(self) -> dict:
        if not (self.env_file.exists() or self.env_file.is_symlink() or self.current.exists() or self.current.is_symlink()):
            if self.current.parent.exists() and any(self.current.parent.iterdir()):
                return {"status": "INCOMPLETE_CONFIG", "reason": "UNKNOWN_GENERATION", "recovery": "Inspect and preserve incomplete generated material before up."}
            return {"status": "NOT_INITIALIZED"}
        try:
            self.load()
        except WorkflowError as error:
            if error.code != 2 or error.reason in {"TOOL_UNAVAILABLE"}:
                raise
            return {"status": "INCOMPLETE_CONFIG", "reason": error.reason, "recovery": error.recovery}
        resources = self.inventory()
        return {"status": self.classification(resources), "project": self.settings["project"], "url": self.settings["origin"],
                "services": {k: {"state": v["State"]["Status"], "health": v["State"].get("Health", {}).get("Status"), "exit_code": v["State"].get("ExitCode")} for k, v in resources.items()}}

    def down(self) -> None:
        with self.lock():
            self.load()
            self.progress("STOP")
            resources = self.inventory()
            self.save("STOPPING", resources)
            self.compose("down", "--timeout", "30", limit=None)
            if self.inventory():
                raise WorkflowError(4, "STOP_INCOMPLETE", "Inspect remaining containers before retrying down.")
            self.save("STOPPED", {})
            print(json.dumps({"status": "STOPPED", "volumes": "preserved", "configuration": "preserved"}))

    def logs(self, args) -> None:
        self.load()
        self.inventory()
        if args.service and args.service not in self.model["services"]:
            raise WorkflowError(2, "UNKNOWN_SERVICE", "Select a service listed by status.")
        command = ["docker", "compose", "--project-directory", str(self.root), "-f", str(self.root / "docker-compose.yml"),
                   "--env-file", str(self.env_file), "-p", self.settings["project"], "logs", "--no-color", "--no-log-prefix", "--tail", str(args.tail)]
        if args.follow:
            command.append("--follow")
        if args.service:
            command.append(args.service)
        with tempfile.TemporaryFile() as errors:
            self.child = subprocess.Popen(command, cwd=self.root, env=self.child_env, stdout=subprocess.PIPE,
                                          stderr=errors, start_new_session=True)
            try:
                for line in self.child.stdout:
                    print(safe_log(line.decode(errors="replace"), self.secret_values), flush=True)
                if self.child.wait():
                    raise WorkflowError(4, "LOGS_UNAVAILABLE", "Check service status and Docker connectivity.")
            finally:
                self.stop_child()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="nomosmart", description="Docker setup and lifecycle; persistent data is preserved.")
    commands = result.add_subparsers(dest="command", required=True)
    up = commands.add_parser("up", help="Initialize a fresh local installation or resume the configured installation")
    up.add_argument("--project-name")
    up.add_argument("--public-host")
    up.add_argument("--http-port", type=int)
    up.add_argument("--https-port", type=int)
    up.add_argument("--timeout", type=int, default=1800)
    up.add_argument("--build", action="store_true")
    status = commands.add_parser("status", help="Read live readiness and service states")
    status.add_argument("--json", action="store_true")
    logs = commands.add_parser("logs", help="Show bounded operational logs with sensitive content suppressed")
    logs.add_argument("service", nargs="?")
    logs.add_argument("--tail", type=int, default=100)
    logs.add_argument("--follow", action="store_true")
    commands.add_parser("down", help="Stop the owned installation; keep data volumes and credentials")
    return result


def main() -> int:
    args = parser().parse_args()
    timeout = getattr(args, "timeout", 1800)
    if not 30 <= timeout <= 7200 or not 1 <= getattr(args, "tail", 100) <= 1000:
        print(json.dumps({"code": 2, "reason": "INVALID_LIMIT", "recovery": "Use --timeout 30..7200 and --tail 1..1000."}), file=sys.stderr)
        return 2
    workflow = None
    try:
        workflow = Workflow(timeout=timeout)
        if args.command == "status":
            print(json.dumps(workflow.status(), ensure_ascii=False))
        else:
            getattr(workflow, args.command)(args) if args.command in {"up", "logs"} else workflow.down()
        return 0
    except KeyboardInterrupt:
        if workflow:
            workflow.stop_child()
        print(json.dumps({"code": 130, "stage": workflow.stage if workflow else "DISCOVER", "reason": "INTERRUPTED", "recovery": "Existing data/configuration are preserved; inspect status then rerun up."}), file=sys.stderr)
        return 130
    except WorkflowError as error:
        print(json.dumps({"code": error.code, "stage": workflow.stage if workflow else "DISCOVER", "reason": error.reason, "recovery": error.recovery}), file=sys.stderr)
        return error.code
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"code": 2, "stage": workflow.stage if workflow else "DISCOVER", "reason": "INVALID_CONFIG_OR_STATE", "recovery": "Restore the matching private configuration and inspect status; no secrets were regenerated."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
