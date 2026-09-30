from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import signal
import ssl
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SERVICE_ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
READY_FILE = Path("/tmp/nomosmart-beat-agent.ready")
ROLE_FILE = Path("/tmp/nomosmart-beat-agent.role")


def _utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class LeaseConfig:
    namespace: str
    name: str
    holder: str
    duration: int
    renew_interval: int
    retry_interval: int
    api_server: str
    token_file: Path
    ca_file: Path

    @classmethod
    def from_environment(cls) -> "LeaseConfig":
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "").strip()
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443").strip()
        namespace_file = SERVICE_ACCOUNT / "namespace"
        namespace = os.environ.get("POD_NAMESPACE", "").strip()
        if not namespace and namespace_file.is_file():
            namespace = namespace_file.read_text(encoding="utf-8").strip()
        pod_name = os.environ.get("POD_NAME", "").strip()
        pod_uid = os.environ.get("POD_UID", "").strip()
        if not all((host, namespace, pod_name, pod_uid)):
            raise RuntimeError("Beat Lease identity or Kubernetes API endpoint is missing")
        duration = int(os.environ.get("BEAT_LEASE_DURATION_SECONDS", "30"))
        renew = int(os.environ.get("BEAT_LEASE_RENEW_SECONDS", "10"))
        retry = int(os.environ.get("BEAT_LEASE_RETRY_SECONDS", "5"))
        if duration < 15 or renew < 1 or retry < 1 or renew + retry >= duration:
            raise RuntimeError("Beat Lease timing is unsafe")
        return cls(
            namespace=namespace,
            name=os.environ.get("BEAT_LEASE_NAME", "nomosmart-celery-beat").strip(),
            holder=f"{pod_name}/{pod_uid}",
            duration=duration,
            renew_interval=renew,
            retry_interval=retry,
            api_server=f"https://{host}:{port}",
            token_file=SERVICE_ACCOUNT / "token",
            ca_file=SERVICE_ACCOUNT / "ca.crt",
        )


class KubernetesLease:
    def __init__(self, config: LeaseConfig) -> None:
        self.config = config
        self.context = ssl.create_default_context(cafile=str(config.ca_file))

    @property
    def url(self) -> str:
        return (
            f"{self.config.api_server}/apis/coordination.k8s.io/v1/namespaces/"
            f"{self.config.namespace}/leases/{self.config.name}"
        )

    def _headers(self) -> dict[str, str]:
        token = self.config.token_file.read_text(encoding="utf-8").strip()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        request = Request(
            self.url,
            method=method,
            data=(json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload else None),
            headers=self._headers(),
        )
        try:
            with urlopen(request, context=self.context, timeout=self.config.retry_interval) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(body)
            except json.JSONDecodeError:
                result = {}
            return exc.code, result
        except (OSError, URLError) as exc:
            raise RuntimeError("Kubernetes Lease API is unavailable") from exc

    def _create(self, now: datetime) -> bool:
        payload = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {"name": self.config.name, "namespace": self.config.namespace},
            "spec": {
                "holderIdentity": self.config.holder,
                "leaseDurationSeconds": self.config.duration,
                "acquireTime": now.isoformat().replace("+00:00", "Z"),
                "renewTime": now.isoformat().replace("+00:00", "Z"),
                "leaseTransitions": 0,
            },
        }
        request = Request(
            self.url.rsplit("/", 1)[0],
            method="POST",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=self._headers(),
        )
        try:
            with urlopen(request, context=self.context, timeout=self.config.retry_interval) as response:
                return response.status in {200, 201}
        except HTTPError as exc:
            if exc.code == 409:
                return False
            raise RuntimeError(
                f"Kubernetes Lease create failed with HTTP {exc.code}"
            ) from exc
        except (OSError, URLError) as exc:
            raise RuntimeError("Kubernetes Lease API is unavailable") from exc

    def acquire_or_renew(self) -> bool:
        now = datetime.now(UTC)
        status, current = self._request("GET")
        if status == 404:
            return self._create(now)
        if status != 200:
            raise RuntimeError(f"Kubernetes Lease read failed with HTTP {status}")
        spec = current.get("spec") or {}
        holder = str(spec.get("holderIdentity") or "")
        renew_time = _utc(spec.get("renewTime") or spec.get("acquireTime"))
        duration = int(spec.get("leaseDurationSeconds") or self.config.duration)
        expired = renew_time is None or renew_time + timedelta(seconds=duration) <= now
        if holder != self.config.holder and not expired:
            return False
        transitions = int(spec.get("leaseTransitions") or 0) + int(holder != self.config.holder)
        updated = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {
                "name": self.config.name,
                "namespace": self.config.namespace,
                "resourceVersion": (current.get("metadata") or {}).get("resourceVersion"),
            },
            "spec": {
                "holderIdentity": self.config.holder,
                "leaseDurationSeconds": self.config.duration,
                "acquireTime": spec.get("acquireTime") or now.isoformat().replace("+00:00", "Z"),
                "renewTime": now.isoformat().replace("+00:00", "Z"),
                "leaseTransitions": transitions,
            },
        }
        update_status, _ = self._request("PUT", updated)
        if update_status == 409:
            return False
        if update_status != 200:
            raise RuntimeError(f"Kubernetes Lease update failed with HTTP {update_status}")
        return True


def _write_role(role: str) -> None:
    ROLE_FILE.write_text(role + "\n", encoding="utf-8")


def _stop(child: subprocess.Popen[bytes] | None) -> None:
    if child is None or child.poll() is not None:
        return
    child.send_signal(signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def main() -> int:
    config = LeaseConfig.from_environment()
    lease = KubernetesLease(config)
    READY_FILE.unlink(missing_ok=True)
    _write_role("standby")
    child: subprocess.Popen[bytes] | None = None
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            try:
                leader = lease.acquire_or_renew()
            except RuntimeError:
                _stop(child)
                child = None
                READY_FILE.unlink(missing_ok=True)
                _write_role("degraded")
                time.sleep(config.retry_interval)
                continue
            READY_FILE.write_text("ready\n", encoding="utf-8")
            if leader:
                if child is None or child.poll() is not None:
                    child = subprocess.Popen(
                        ["celery", "-A", "app.worker.celery_app", "beat", "--loglevel=INFO", "--schedule=/tmp/celerybeat-schedule"],
                    )
                _write_role("active")
                time.sleep(config.renew_interval)
                continue
            _stop(child)
            child = None
            _write_role("standby")
            time.sleep(config.retry_interval)
    finally:
        _stop(child)
        READY_FILE.unlink(missing_ok=True)
        _write_role("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
