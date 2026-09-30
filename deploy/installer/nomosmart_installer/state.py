from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any, Final

from .config import InstallConfig
from .core import DriftError, InstallerError, PreconditionError, atomic_private_json, now, safe_identifier
from .kube import CONFIG_ANNOTATION, OWNER_LABEL, Kubernetes


STAGES: Final[tuple[str, ...]] = (
    "preflight",
    "package-and-secrets",
    "cloudnativepg-operator",
    "barman-cloud-plugin",
    "foundation",
    "migration-bootstrap-and-app",
    "directory-integration",
    "identity-checkpoint",
    "operational-finalization",
    "verification-receipt",
)
STATE_SCHEMA: Final[int] = 4


@dataclass
class InstallerState:
    schema_version: int
    installer_version: str
    chart_version: str
    target_cluster_uid: str
    target_context: str
    namespace: str
    release: str
    config_digest: str
    generation: int = 1
    current_stage: str = "preflight"
    completed_stages: list[str] = field(default_factory=list)
    postconditions: dict[str, Any] = field(default_factory=dict)
    helm_revision: int | None = None
    resource_fingerprints: dict[str, Any] = field(default_factory=dict)
    last_error: str = ""
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)

    @classmethod
    def fresh(cls, config: InstallConfig, installer_version: str) -> "InstallerState":
        return cls(
            schema_version=STATE_SCHEMA,
            installer_version=installer_version,
            chart_version=config.chart_version,
            target_cluster_uid=config.target.cluster_uid,
            target_context=config.target.context,
            namespace=config.target.namespace,
            release=config.target.release,
            config_digest=config.digest,
        )

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "InstallerState":
        if payload.get("schema_version") != STATE_SCHEMA:
            raise DriftError("installer state schema is incompatible")
        try:
            return cls(**payload)
        except TypeError as exc:
            raise DriftError("installer state is incomplete or incompatible") from exc

    def validate(self, config: InstallConfig) -> None:
        expected = {
            "target_cluster_uid": config.target.cluster_uid,
            "target_context": config.target.context,
            "namespace": config.target.namespace,
            "release": config.target.release,
            "config_digest": config.digest,
            "chart_version": config.chart_version,
        }
        drift = [key for key, value in expected.items() if getattr(self, key) != value]
        if drift:
            raise DriftError("installer state target/config mismatch: " + ", ".join(drift))
        if any(stage not in STAGES for stage in self.completed_stages):
            raise DriftError("installer state contains an unknown completed stage")

    def begin(self, stage: str) -> None:
        if stage not in STAGES:
            raise PreconditionError(f"unknown installer stage: {stage}")
        self.current_stage = stage
        self.last_error = ""
        self.updated_at = now()

    def complete(self, stage: str, evidence: dict[str, Any] | None = None) -> None:
        if stage not in self.completed_stages:
            self.completed_stages.append(stage)
        self.current_stage = stage
        if evidence is not None:
            self.postconditions[stage] = evidence
        self.last_error = ""
        self.updated_at = now()

    def fail(self, error: str) -> None:
        self.last_error = safe_identifier(error)
        self.updated_at = now()

    def payload(self) -> dict[str, Any]:
        return asdict(self)


class StateStore:
    def __init__(self, config: InstallConfig, kube: Kubernetes, installer_version: str) -> None:
        self.config = config
        self.kube = kube
        self.installer_version = installer_version
        self.name = f"{config.target.release}-installer-state"
        self.local_path = config.application.state_dir / "state.json"
        self.receipt_path = config.application.state_dir / "verification-receipt.json"

    def load(self, *, allow_missing: bool = True) -> InstallerState | None:
        local: InstallerState | None = None
        cluster: InstallerState | None = None
        if self.local_path.is_file():
            try:
                payload = json.loads(self.local_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise DriftError("local installer state is invalid") from exc
            if not isinstance(payload, dict):
                raise DriftError("local installer state is invalid")
            local = InstallerState.parse(payload)
        if self.kube.exists("configmap", self.name):
            payload = self.kube.json("get", "configmap", self.name, namespace=True)
            metadata = payload.get("metadata") or {}
            if (
                (metadata.get("labels") or {}).get(OWNER_LABEL)
                != self.config.target.release
                or (metadata.get("annotations") or {}).get(
                    CONFIG_ANNOTATION
                )
                != self.config.digest
            ):
                raise DriftError(
                    "cluster installer state has incompatible ownership"
                )
            raw = str((payload.get("data") or {}).get("state.json") or "")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise DriftError("cluster installer state is invalid") from exc
            if not isinstance(parsed, dict):
                raise DriftError("cluster installer state is invalid")
            cluster = InstallerState.parse(parsed)
        state: InstallerState | None
        if local and cluster and local.payload() != cluster.payload():
            state = self._recoverable_progress(local, cluster)
        else:
            state = local or cluster
        if state is None:
            if allow_missing:
                return None
            raise PreconditionError("installer state is unavailable; run install first")
        state.validate(self.config)
        if state.installer_version != self.installer_version:
            raise DriftError(
                "installer state was created by another installer version"
            )
        return state

    @staticmethod
    def _recoverable_progress(
        local: InstallerState,
        cluster: InstallerState,
    ) -> InstallerState:
        immutable = (
            "schema_version",
            "installer_version",
            "chart_version",
            "target_cluster_uid",
            "target_context",
            "namespace",
            "release",
            "config_digest",
            "generation",
            "created_at",
        )
        if any(getattr(local, key) != getattr(cluster, key) for key in immutable):
            raise DriftError("local and cluster installer state identity differs")
        local_completed = local.completed_stages
        cluster_completed = cluster.completed_stages
        common = min(len(local_completed), len(cluster_completed))
        if local_completed[:common] != cluster_completed[:common]:
            raise DriftError("local and cluster installer stage history diverges")
        for stage in local_completed[:common]:
            if local.postconditions.get(stage) != cluster.postconditions.get(stage):
                raise DriftError(
                    f"local and cluster postcondition differs for {stage}"
                )
        if len(local_completed) != len(cluster_completed):
            return local if len(local_completed) > len(cluster_completed) else cluster
        # A process can be interrupted between the local atomic write and the
        # ConfigMap apply while beginning/failing the same next stage. With equal
        # completed history, the newest safe metadata copy is recoverable.
        return local if local.updated_at >= cluster.updated_at else cluster

    def save(self, state: InstallerState) -> None:
        state.validate(self.config)
        existing: dict[str, Any] | None = None
        if self.kube.exists("configmap", self.name):
            existing = self.kube.json(
                "get", "configmap", self.name, namespace=True
            )
            metadata = existing.get("metadata") or {}
            if (
                (metadata.get("labels") or {}).get(OWNER_LABEL)
                != self.config.target.release
                or (metadata.get("annotations") or {}).get(
                    CONFIG_ANNOTATION
                )
                != self.config.digest
            ):
                raise DriftError(
                    "refusing to overwrite incompatible installer state"
                )
        atomic_private_json(self.local_path, state.payload())
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": self.name,
                "namespace": self.config.target.namespace,
                "labels": {OWNER_LABEL: self.config.target.release},
                "annotations": {CONFIG_ANNOTATION: self.config.digest},
            },
            "data": {"state.json": json.dumps(state.payload(), sort_keys=True, separators=(",", ":"))},
        }
        if existing is None:
            self.kube.run(
                "create",
                "-f",
                "-",
                input_text=json.dumps(manifest),
            )
            return
        resource_version = str(
            (existing.get("metadata") or {}).get("resourceVersion") or ""
        )
        if not resource_version:
            raise PreconditionError(
                "cluster installer state has no resourceVersion"
            )
        manifest["metadata"]["resourceVersion"] = resource_version
        self.kube.run(
            "replace",
            "-f",
            "-",
            input_text=json.dumps(manifest),
        )

    def fresh(self) -> InstallerState:
        state = InstallerState.fresh(self.config, self.installer_version)
        self.save(state)
        return state


class Lease:
    def __init__(self, config: InstallConfig, kube: Kubernetes, *, duration_seconds: int = 90) -> None:
        self.config = config
        self.kube = kube
        self.name = f"{config.target.release}-installer"
        self.duration_seconds = duration_seconds
        self.holder = f"{socket.gethostname()}:{os.getpid()}"
        self.acquired = False
        self._mutex = threading.Lock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat: threading.Thread | None = None
        self._heartbeat_error: str = ""
        self._last_renewal = 0.0

    def acquire(self) -> None:
        existing = self.kube.lease_payload(self.name)
        if existing is not None:
            metadata = existing.get("metadata") or {}
            if (
                (metadata.get("labels") or {}).get(OWNER_LABEL)
                != self.config.target.release
                or (metadata.get("annotations") or {}).get(
                    CONFIG_ANNOTATION
                )
                != self.config.digest
            ):
                raise DriftError(
                    "existing installer Lease has incompatible ownership"
                )
        if existing is not None and self.kube.lease_active(
            existing,
            holder=self.holder,
            duration=self.duration_seconds,
        ):
            raise PreconditionError("another installer holds the cluster Lease")
        timestamp = now()
        manifest = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {
                "name": self.name,
                "namespace": self.config.target.namespace,
                "labels": {OWNER_LABEL: self.config.target.release},
                "annotations": {CONFIG_ANNOTATION: self.config.digest},
            },
            "spec": {
                "holderIdentity": self.holder,
                "leaseDurationSeconds": self.duration_seconds,
                "acquireTime": timestamp,
                "renewTime": timestamp,
            },
        }
        if existing is None:
            self.kube.run(
                "create",
                "-f",
                "-",
                namespace=False,
                input_text=json.dumps(manifest),
            )
        else:
            resource_version = str(
                (existing.get("metadata") or {}).get("resourceVersion") or ""
            )
            if not resource_version:
                raise PreconditionError(
                    "existing installer Lease has no resourceVersion"
                )
            manifest["metadata"]["resourceVersion"] = resource_version
            self.kube.run(
                "replace",
                "-f",
                "-",
                namespace=False,
                input_text=json.dumps(manifest),
            )
        self.acquired = True
        self._last_renewal = time.monotonic()

    def renew(self) -> None:
        with self._mutex:
            if not self.acquired:
                raise PreconditionError("installer Lease is not held")
            existing = self.kube.lease_payload(self.name)
            if existing is None:
                raise PreconditionError("installer Lease disappeared")
            existing_spec = existing.get("spec") or {}
            if str(existing_spec.get("holderIdentity") or "") != self.holder:
                raise PreconditionError("installer Lease ownership was lost")
            resource_version = str(
                (existing.get("metadata") or {}).get("resourceVersion") or ""
            )
            if not resource_version:
                raise PreconditionError(
                    "installer Lease has no resourceVersion"
                )
            timestamp = now()
            manifest = {
                "apiVersion": "coordination.k8s.io/v1",
                "kind": "Lease",
                "metadata": {
                    "name": self.name,
                    "namespace": self.config.target.namespace,
                    "resourceVersion": resource_version,
                    "labels": {OWNER_LABEL: self.config.target.release},
                    "annotations": {
                        CONFIG_ANNOTATION: self.config.digest
                    },
                },
                "spec": {
                    "holderIdentity": self.holder,
                    "leaseDurationSeconds": self.duration_seconds,
                    "acquireTime": existing_spec.get("acquireTime")
                    or timestamp,
                    "renewTime": timestamp,
                },
            }
            self.kube.run(
                "replace",
                "-f",
                "-",
                namespace=False,
                input_text=json.dumps(manifest),
            )
            self._last_renewal = time.monotonic()
            self._heartbeat_error = ""

    def start_heartbeat(self) -> None:
        if not self.acquired or self._heartbeat is not None:
            raise PreconditionError(
                "installer Lease heartbeat cannot be started"
            )
        interval = max(5, self.duration_seconds // 3)
        self._heartbeat_stop.clear()

        def heartbeat() -> None:
            while not self._heartbeat_stop.wait(interval):
                try:
                    self.renew()
                except Exception as exc:
                    self._heartbeat_error = type(exc).__name__

        self._heartbeat = threading.Thread(
            target=heartbeat,
            name="nomosmart-installer-lease",
            daemon=True,
        )
        self._heartbeat.start()

    def check_heartbeat(self) -> None:
        if (
            self._heartbeat_error
            and time.monotonic() - self._last_renewal
            >= self.duration_seconds / 2
        ):
            raise PreconditionError(
                "installer Lease heartbeat could not be renewed"
            )

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        heartbeat = self._heartbeat
        if heartbeat is not None:
            heartbeat.join(timeout=5)
        self._heartbeat = None

    def release(self) -> None:
        self.stop_heartbeat()
        if not self.acquired:
            return
        if not self._mutex.acquire(timeout=5):
            self.acquired = False
            return
        try:
            try:
                existing = self.kube.lease_payload(self.name)
                if (
                    existing is not None
                    and str(
                        (existing.get("spec") or {}).get(
                            "holderIdentity"
                        )
                        or ""
                    )
                    == self.holder
                    and (
                        (existing.get("metadata") or {}).get("labels")
                        or {}
                    ).get(OWNER_LABEL)
                    == self.config.target.release
                    and (
                        (
                            (existing.get("metadata") or {}).get(
                                "annotations"
                            )
                            or {}
                        ).get(CONFIG_ANNOTATION)
                    )
                    == self.config.digest
                ):
                    metadata = existing.get("metadata") or {}
                    uid = str(metadata.get("uid") or "")
                    resource_version = str(
                        metadata.get("resourceVersion") or ""
                    )
                    if uid and resource_version:
                        self.kube.delete_precondition(
                            "Lease",
                            self.name,
                            uid=uid,
                            resource_version=resource_version,
                        )
            except InstallerError:
                # The bounded Lease expires even when the API is unavailable;
                # release failure must not mask the stage's real result.
                pass
            finally:
                self.acquired = False
        finally:
            self._mutex.release()
