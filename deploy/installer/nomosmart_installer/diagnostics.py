from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any

from .config import InstallConfig
from .core import (
    DriftError,
    InstallerError,
    PreconditionError,
    atomic_private_json,
    ensure_private_directory,
    now,
    sha256_bytes,
)
from .helm import Helm
from .kube import CONFIG_ANNOTATION, OWNER_LABEL, Kubernetes
from .state import StateStore


RESET_PLAN_SCHEMA = 1
PROTECTED_KINDS = frozenset(
    {
        "PersistentVolume",
        "PersistentVolumeClaim",
        "Secret",
        "StatefulSet",
    }
)


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256_bytes(encoded)


def _metadata_identity(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") or {}
    return {
        "name": str(metadata.get("name") or ""),
        "namespace": str(metadata.get("namespace") or ""),
        "uid": str(metadata.get("uid") or ""),
        "resource_version": str(metadata.get("resourceVersion") or ""),
        "owner": str(
            (metadata.get("labels") or {}).get(OWNER_LABEL) or ""
        ),
        "config_digest": str(
            (metadata.get("annotations") or {}).get(CONFIG_ANNOTATION)
            or ""
        ),
    }


class InstallerDiagnostics:
    def __init__(
        self,
        config: InstallConfig,
        kube: Kubernetes,
        helm: Helm,
        store: StateStore,
    ) -> None:
        self.config = config
        self.kube = kube
        self.helm = helm
        self.store = store

    def _local_state(self) -> dict[str, Any]:
        path = self.store.local_path
        if not path.exists():
            return {"status": "missing", "path": str(path)}
        if (
            not path.is_file()
            or path.is_symlink()
            or stat.S_IMODE(path.stat().st_mode) & 0o077
        ):
            return {
                "status": "unsafe-to-repair",
                "path": str(path),
                "reason": "local-state-type-or-permission",
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "drift",
                "path": str(path),
                "reason": "invalid-json",
            }
        if not isinstance(payload, dict):
            return {
                "status": "drift",
                "path": str(path),
                "reason": "invalid-state-object",
            }
        return {
            "status": "present",
            "path": str(path),
            "identity": {
                "schema_version": payload.get("schema_version"),
                "installer_version": payload.get("installer_version"),
                "chart_version": payload.get("chart_version"),
                "cluster_uid": payload.get("target_cluster_uid"),
                "context": payload.get("target_context"),
                "namespace": payload.get("namespace"),
                "release": payload.get("release"),
                "config_digest": payload.get("config_digest"),
                "generation": payload.get("generation"),
            },
            "progress": {
                "current_stage": payload.get("current_stage"),
                "completed_stages": payload.get("completed_stages")
                if isinstance(payload.get("completed_stages"), list)
                else [],
                "last_error": payload.get("last_error"),
                "updated_at": payload.get("updated_at"),
            },
            "sha256": _digest(payload),
        }

    def _cluster_state(self, namespace_exists: bool) -> dict[str, Any]:
        if not namespace_exists or not self.kube.exists(
            "configmap", self.store.name
        ):
            return {"status": "missing", "name": self.store.name}
        payload = self.kube.json(
            "get", "configmap", self.store.name, namespace=True
        )
        identity = _metadata_identity(payload)
        raw = str((payload.get("data") or {}).get("state.json") or "")
        try:
            state = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "status": "drift",
                "identity": identity,
                "reason": "invalid-state-json",
            }
        if not isinstance(state, dict):
            return {
                "status": "drift",
                "identity": identity,
                "reason": "invalid-state-object",
            }
        return {
            "status": "present",
            "identity": identity,
            "state_identity": {
                "schema_version": state.get("schema_version"),
                "installer_version": state.get("installer_version"),
                "chart_version": state.get("chart_version"),
                "cluster_uid": state.get("target_cluster_uid"),
                "context": state.get("target_context"),
                "namespace": state.get("namespace"),
                "release": state.get("release"),
                "config_digest": state.get("config_digest"),
                "generation": state.get("generation"),
            },
            "progress": {
                "current_stage": state.get("current_stage"),
                "completed_stages": state.get("completed_stages")
                if isinstance(state.get("completed_stages"), list)
                else [],
                "last_error": state.get("last_error"),
                "updated_at": state.get("updated_at"),
            },
            "sha256": _digest(state),
        }

    def _namespace(self) -> tuple[bool, dict[str, Any]]:
        name = self.config.target.namespace
        if not self.kube.exists("namespace", name, namespace=False):
            return False, {"status": "missing", "name": name}
        payload = self.kube.json("get", "namespace", name)
        identity = _metadata_identity(payload)
        expected = (
            identity["owner"] == self.config.target.release
            and identity["config_digest"] == self.config.digest
        )
        return True, {
            "status": "matching" if expected else "drift",
            "identity": identity,
        }

    def _lease(self, namespace_exists: bool) -> dict[str, Any]:
        name = f"{self.config.target.release}-installer"
        if not namespace_exists:
            return {"status": "missing", "name": name}
        payload = self.kube.lease_payload(name)
        if payload is None:
            return {"status": "missing", "name": name}
        identity = _metadata_identity(payload)
        spec = payload.get("spec") or {}
        duration = int(spec.get("leaseDurationSeconds") or 90)
        active = self.kube.lease_active(
            payload,
            holder="nomosmart-doctor-never-holder",
            duration=duration,
        )
        ownership_matches = (
            identity["owner"] == self.config.target.release
            and identity["config_digest"] == self.config.digest
        )
        return {
            "status": (
                "active"
                if ownership_matches and active
                else "stale"
                if ownership_matches
                else "drift"
            ),
            "identity": identity,
            "holder": str(spec.get("holderIdentity") or ""),
            "renew_time": str(
                spec.get("renewTime") or spec.get("acquireTime") or ""
            ),
            "duration_seconds": duration,
        }

    def _helm(self, namespace_exists: bool) -> dict[str, Any]:
        if not namespace_exists:
            return {"status": "missing"}
        try:
            status = self.helm.status()
        except InstallerError:
            return {"status": "missing"}
        fullname = (
            self.config.target.release
            if "nomosmart" in self.config.target.release
            else f"{self.config.target.release}-nomosmart"
        )[:63].rstrip("-")
        phase = ""
        config_name = f"{fullname}-config"
        if self.kube.exists("configmap", config_name):
            payload = self.kube.json(
                "get", "configmap", config_name, namespace=True
            )
            phase = str(
                (payload.get("data") or {}).get("DEPLOYMENT_PHASE")
                or (payload.get("data") or {}).get(
                    "INSTALLER_DEPLOYMENT_STAGE"
                )
                or ""
            )
        return {
            **status,
            "deployment_phase": phase,
        }

    def _owned_resources(
        self, namespace_exists: bool
    ) -> dict[str, Any]:
        if not namespace_exists:
            return {"status": "missing", "items": [], "fingerprint": ""}
        payload = self.kube.json(
            "get",
            (
                "all,configmaps,secrets,leases,jobs.batch,"
                "ingresses.networking.k8s.io,persistentvolumeclaims"
            ),
            "--ignore-not-found",
            "--selector",
            f"{OWNER_LABEL}={self.config.target.release}",
            namespace=True,
        )
        rows: list[dict[str, Any]] = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            rows.append(
                {
                    "api_version": str(item.get("apiVersion") or ""),
                    "kind": str(item.get("kind") or ""),
                    "name": str(metadata.get("name") or ""),
                    "uid": str(metadata.get("uid") or ""),
                    "resource_version": str(
                        metadata.get("resourceVersion") or ""
                    ),
                    "config_digest": str(
                        (metadata.get("annotations") or {}).get(
                            CONFIG_ANNOTATION
                        )
                        or ""
                    ),
                    "protected": str(item.get("kind") or "")
                    in PROTECTED_KINDS,
                }
            )
        rows.sort(key=lambda row: (row["kind"], row["name"]))
        return {
            "status": "present" if rows else "missing",
            "items": rows,
            "fingerprint": _digest(rows) if rows else "",
        }

    @staticmethod
    def _state_matches(
        local: dict[str, Any], cluster: dict[str, Any]
    ) -> bool:
        if local["status"] == "missing" and cluster["status"] == "missing":
            return True
        return (
            local["status"] == "present"
            and cluster["status"] == "present"
            and local.get("sha256") == cluster.get("sha256")
            and local.get("identity") == cluster.get("state_identity")
        )

    def doctor(self) -> dict[str, Any]:
        target = self.kube.validate_identity()
        namespace_exists, namespace = self._namespace()
        local = self._local_state()
        cluster = self._cluster_state(namespace_exists)
        lease = self._lease(namespace_exists)
        helm = self._helm(namespace_exists)
        resources = self._owned_resources(namespace_exists)
        state_match = self._state_matches(local, cluster)
        classifications: list[str] = []
        if local["status"] == "missing" and cluster["status"] == "missing":
            classifications.append("missing")
        if not state_match or namespace.get("status") == "drift":
            classifications.append("drift")
        if lease.get("status") == "stale":
            classifications.append("stale")
        if any(
            row.get("protected") for row in resources.get("items", [])
        ):
            classifications.append("unsafe-to-repair")
        if not classifications:
            classifications.append("match")
        observed = {
            "target": target,
            "namespace": namespace,
            "local_state": local,
            "cluster_state": cluster,
            "state_match": state_match,
            "lease": lease,
            "helm": helm,
            "owned_resources": resources,
        }
        return {
            "status": "diagnosed",
            "read_only": True,
            "classifications": sorted(set(classifications)),
            "target": target,
            "config_digest": self.config.digest,
            "observed": observed,
            "observed_digest": _digest(observed),
            "recommendation": (
                "reset-plan"
                if self._reset_candidate(observed)
                else "resume-or-operator-runbook"
            ),
        }

    def _reset_candidate(self, observed: dict[str, Any]) -> bool:
        local = observed["local_state"]
        cluster = observed["cluster_state"]
        state_exists = (
            local.get("status") == "present"
            or cluster.get("status") == "present"
        )
        completed = set(
            (local.get("progress") or {}).get("completed_stages") or []
        ) | set(
            (cluster.get("progress") or {}).get("completed_stages") or []
        )
        helm = observed["helm"]
        return (
            state_exists
            and "operational-finalization" not in completed
            and helm.get("deployment_phase") != "operational"
            and helm.get("status") in {"missing", ""}
            and observed["lease"].get("status") != "active"
            and not any(
                row.get("protected")
                for row in observed["owned_resources"].get("items", [])
            )
        )

    def reset_plan(self, output: Path) -> dict[str, Any]:
        diagnostic = self.doctor()
        observed = diagnostic["observed"]
        if not self._reset_candidate(observed):
            raise PreconditionError(
                "reset is refused: attempt is operational, active, contains "
                "protected resources, has a Helm release, or is not an eligible "
                "failed/incomplete abandoned attempt"
            )
        operations: list[dict[str, Any]] = []
        cluster = observed["cluster_state"]
        if cluster.get("status") == "present":
            operations.append(
                {
                    "action": "delete",
                    "kind": "ConfigMap",
                    "name": self.store.name,
                    "uid": cluster["identity"]["uid"],
                    "resource_version": cluster["identity"][
                        "resource_version"
                    ],
                }
            )
        lease = observed["lease"]
        if lease.get("status") == "stale":
            operations.append(
                {
                    "action": "delete",
                    "kind": "Lease",
                    "name": f"{self.config.target.release}-installer",
                    "uid": lease["identity"]["uid"],
                    "resource_version": lease["identity"][
                        "resource_version"
                    ],
                }
            )
        namespace = observed["namespace"]
        if (
            namespace.get("status") == "matching"
            and namespace.get("identity", {}).get("owner")
            == self.config.target.release
        ):
            operations.append(
                {
                    "action": "release-namespace-metadata",
                    "kind": "Namespace",
                    "name": self.config.target.namespace,
                    "uid": namespace["identity"]["uid"],
                    "resource_version": namespace["identity"][
                        "resource_version"
                    ],
                }
            )
        local_files = [
            str(path)
            for path in (
                self.store.local_path,
                self.store.receipt_path,
            )
            if path.is_file() and not path.is_symlink()
        ]
        plan: dict[str, Any] = {
            "schema_version": RESET_PLAN_SCHEMA,
            "created_at": now(),
            "target": {
                "cluster_uid": self.config.target.cluster_uid,
                "context": self.config.target.context,
                "namespace": self.config.target.namespace,
                "release": self.config.target.release,
                "config_digest": self.config.digest,
            },
            "observed_digest": diagnostic["observed_digest"],
            "operations": operations,
            "archive_local_files": local_files,
            "preserved": [
                "PersistentVolume",
                "PersistentVolumeClaim",
                "Kubernetes Secret",
                "business data",
                "external input",
                "Rancher Project metadata",
                "Kubernetes system metadata",
            ],
        }
        plan["plan_digest"] = _digest(plan)
        atomic_private_json(output, plan, overwrite=False)
        return {
            "status": "planned",
            "plan": str(output),
            "plan_digest": plan["plan_digest"],
            "operation_count": len(operations),
            "preserved": plan["preserved"],
        }

    def _load_plan(self, path: Path) -> dict[str, Any]:
        if (
            not path.is_file()
            or path.is_symlink()
            or stat.S_IMODE(path.stat().st_mode) & 0o077
        ):
            raise PreconditionError(
                "reset plan must be an owner-only regular file"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreconditionError("reset plan is invalid") from exc
        if not isinstance(payload, dict):
            raise PreconditionError("reset plan is invalid")
        supplied = str(payload.get("plan_digest") or "")
        unsigned = dict(payload)
        unsigned.pop("plan_digest", None)
        if (
            payload.get("schema_version") != RESET_PLAN_SCHEMA
            or supplied != _digest(unsigned)
        ):
            raise DriftError("reset plan digest or schema is invalid")
        return payload

    def reset_apply(
        self, plan_path: Path, *, confirmation: str
    ) -> dict[str, Any]:
        plan = self._load_plan(plan_path)
        if confirmation != plan["plan_digest"]:
            raise PreconditionError(
                "reset confirmation must exactly match the plan digest"
            )
        expected_target = {
            "cluster_uid": self.config.target.cluster_uid,
            "context": self.config.target.context,
            "namespace": self.config.target.namespace,
            "release": self.config.target.release,
            "config_digest": self.config.digest,
        }
        if plan.get("target") != expected_target:
            raise DriftError("reset plan target identity differs")
        current = self.doctor()
        if current["observed_digest"] != plan["observed_digest"]:
            raise DriftError(
                "reset observations changed after planning; generate a new plan"
            )
        if not self._reset_candidate(current["observed"]):
            raise PreconditionError("reset candidate is no longer safe")

        archive = (
            self.config.application.state_dir
            / "attempts"
            / (
                datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                + "-"
                + str(plan["plan_digest"])[:12]
            )
        )
        ensure_private_directory(archive)
        archived: list[str] = []
        for raw in plan.get("archive_local_files") or []:
            source = Path(str(raw))
            if source not in {
                self.store.local_path,
                self.store.receipt_path,
            }:
                raise DriftError("reset plan contains an unsupported local path")
            if source.is_file() and not source.is_symlink():
                target = archive / source.name
                shutil.copy2(source, target)
                os.chmod(target, 0o600)
                archived.append(str(target))

        for operation in plan.get("operations") or []:
            if operation.get("action") == "delete":
                kind = str(operation.get("kind") or "")
                if kind not in {"ConfigMap", "Lease"}:
                    raise DriftError("reset plan contains a protected delete kind")
                self.kube.delete_precondition(
                    kind,
                    str(operation["name"]),
                    uid=str(operation["uid"]),
                    resource_version=str(operation["resource_version"]),
                )
            elif operation.get("action") == "release-namespace-metadata":
                self.kube.release_namespace_metadata(
                    uid=str(operation["uid"]),
                    resource_version=str(operation["resource_version"]),
                )
            else:
                raise DriftError("reset plan contains an unsupported operation")

        for raw in plan.get("archive_local_files") or []:
            source = Path(str(raw))
            if source.is_file() and not source.is_symlink():
                source.unlink()
        return {
            "status": "reset",
            "plan_digest": plan["plan_digest"],
            "archive": str(archive),
            "archived_files": archived,
            "protected_data_deleted": False,
            "next_command": "plan",
        }
