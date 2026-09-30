from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import stat
from typing import Any, Final

from .config import InstallConfig
from .core import (
    DriftError,
    PreconditionError,
    atomic_private_json,
    ensure_private_directory,
    now,
    sha256_bytes,
    sha256_file,
)
from .helm import Helm
from .kube import CONFIG_ANNOTATION, OWNER_LABEL, Kubernetes
from .state import StateStore


FACTORY_PLAN_SCHEMA: Final[int] = 1
OPENLDAP_LONGHORN_VOLUME: Final[str] = (
    "pvc-aceaa515-e901-4771-bdb5-687d79d71aec"
)
LONGHORN_NAMESPACE: Final[str] = "longhorn-system"

NAMESPACED_RESOURCES: Final[tuple[str, ...]] = (
    "deployments.apps",
    "statefulsets.apps",
    "daemonsets.apps",
    "jobs.batch",
    "cronjobs.batch",
    "services",
    "ingresses.networking.k8s.io",
    "configmaps",
    "secrets",
    "persistentvolumeclaims",
    "networkpolicies.networking.k8s.io",
    "poddisruptionbudgets.policy",
    "serviceaccounts",
    "roles.rbac.authorization.k8s.io",
    "rolebindings.rbac.authorization.k8s.io",
    "leases.coordination.k8s.io",
    "clusters.postgresql.cnpg.io",
    "databaseroles.postgresql.cnpg.io",
    "databases.postgresql.cnpg.io",
    "backups.postgresql.cnpg.io",
    "scheduledbackups.postgresql.cnpg.io",
    "objectstores.barmancloud.cnpg.io",
    "volumesnapshots.snapshot.storage.k8s.io",
)


def _digest(payload: object) -> str:
    return sha256_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _identity(
    item: dict[str, Any],
    *,
    resource: str,
    namespace: str,
) -> dict[str, str]:
    metadata = item.get("metadata") or {}
    return {
        "api_version": str(item.get("apiVersion") or ""),
        "kind": str(item.get("kind") or ""),
        "resource": resource.split(".", 1)[0],
        "namespace": namespace,
        "name": str(metadata.get("name") or ""),
        "uid": str(metadata.get("uid") or ""),
        "resource_version": str(metadata.get("resourceVersion") or ""),
    }


class FactoryReinstall:
    """Digest-bound CHG-252 destructive plan, intentionally separate from reset."""

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

    def _list(
        self, resource: str, *, namespace: str | None
    ) -> list[dict[str, Any]]:
        arguments = ["get", resource]
        if namespace:
            arguments.extend(["--namespace", namespace])
        arguments.extend(["--ignore-not-found", "-o", "json"])
        result = self.kube.run(
            *arguments,
            namespace=False,
            accepted=frozenset({0, 1}),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PreconditionError(
                f"factory inventory returned invalid JSON for {resource}"
            ) from exc
        if not isinstance(payload, dict):
            raise PreconditionError(
                f"factory inventory is invalid for {resource}"
            )
        rows = payload.get("items")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return [payload] if payload.get("metadata") else []

    def _owned(self, item: dict[str, Any]) -> bool:
        metadata = item.get("metadata") or {}
        labels = metadata.get("labels") or {}
        annotations = metadata.get("annotations") or {}
        name = str(metadata.get("name") or "")
        return (
            labels.get("app.kubernetes.io/instance")
            == self.config.target.release
            or labels.get(OWNER_LABEL) == self.config.target.release
            or annotations.get("meta.helm.sh/release-name")
            == self.config.target.release
            or name.startswith(
                f"sh.helm.release.v1.{self.config.target.release}.v"
            )
        )

    def _protected_secret_names(self) -> set[str]:
        names = {
            "kube-root-ca.crt",
            self.config.identity.bind_secret_name,
            self.config.identity.ca_secret_name,
        }
        if self.config.application.registry_pull_secret:
            names.add(self.config.application.registry_pull_secret)
        return {name for name in names if name}

    def _local_generation(self) -> dict[str, str]:
        manifest = (
            self.config.application.package_dir / "current" / "manifest.json"
        )
        if not manifest.is_file() or manifest.is_symlink():
            return {"status": "missing"}
        if stat.S_IMODE(manifest.stat().st_mode) != 0o600:
            raise PreconditionError(
                "factory package manifest must remain mode 0600"
            )
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreconditionError(
                "factory package manifest is invalid"
            ) from exc
        return {
            "status": "present",
            "generation_id": str(payload.get("generation_id") or ""),
            "deployment_state": str(payload.get("deployment_state") or ""),
            "manifest_sha256": sha256_file(manifest),
        }

    def inventory(self) -> dict[str, Any]:
        target = self.kube.validate_identity()
        namespace = self.kube.json(
            "get", "namespace", self.config.target.namespace
        )
        namespace_metadata = namespace.get("metadata") or {}
        namespace_identity = {
            "name": self.config.target.namespace,
            "uid": str(namespace_metadata.get("uid") or ""),
            "resource_version": str(
                namespace_metadata.get("resourceVersion") or ""
            ),
            "rancher_project_id": str(
                (namespace_metadata.get("annotations") or {}).get(
                    "field.cattle.io/projectId"
                )
                or (namespace_metadata.get("labels") or {}).get(
                    "field.cattle.io/projectId"
                )
                or ""
            ),
            "installer_owner": str(
                (namespace_metadata.get("labels") or {}).get(OWNER_LABEL)
                or ""
            ),
            "installer_config_digest": str(
                (namespace_metadata.get("annotations") or {}).get(
                    CONFIG_ANNOTATION
                )
                or ""
            ),
        }
        try:
            helm = self.helm.status()
        except Exception as exc:
            raise PreconditionError(
                "factory inventory requires the exact live Helm release"
            ) from exc

        protected_secrets = self._protected_secret_names()
        namespaced: list[dict[str, str]] = []
        preserved: list[dict[str, str]] = []
        selected_pvcs: set[str] = set()
        for resource in NAMESPACED_RESOURCES:
            for item in self._list(
                resource, namespace=self.config.target.namespace
            ):
                identity = _identity(
                    item,
                    resource=resource,
                    namespace=self.config.target.namespace,
                )
                if (
                    identity["kind"] == "Secret"
                    and identity["name"] in protected_secrets
                ):
                    preserved.append({**identity, "reason": "immutable-input"})
                    continue
                snapshot_source = str(
                    (
                        ((item.get("spec") or {}).get("source") or {}).get(
                            "persistentVolumeClaimName"
                        )
                    )
                    or ""
                )
                if self._owned(item) or (
                    identity["kind"] == "VolumeSnapshot"
                    and snapshot_source in selected_pvcs
                ):
                    namespaced.append(identity)
                    if identity["kind"] == "PersistentVolumeClaim":
                        selected_pvcs.add(identity["name"])

        pvs: list[dict[str, str]] = []
        selected_pv_names: set[str] = set()
        for item in self._list("persistentvolumes", namespace=None):
            spec = item.get("spec") or {}
            claim = spec.get("claimRef") or {}
            if (
                str(claim.get("namespace") or "")
                == self.config.target.namespace
                and str(claim.get("name") or "") in selected_pvcs
            ):
                row = _identity(
                    item, resource="persistentvolumes", namespace=""
                )
                pvs.append(row)
                selected_pv_names.add(row["name"])

        longhorn_volumes: list[dict[str, Any]] = []
        foreign_longhorn: list[dict[str, Any]] = []
        for item in self._list(
            "volumes.longhorn.io", namespace=LONGHORN_NAMESPACE
        ):
            metadata = item.get("metadata") or {}
            spec = item.get("spec") or {}
            status = item.get("status") or {}
            kubernetes = status.get("kubernetesStatus") or {}
            name = str(metadata.get("name") or "")
            selected = (
                str(kubernetes.get("namespace") or "")
                == self.config.target.namespace
                and (
                    str(kubernetes.get("pvcName") or "") in selected_pvcs
                    or str(kubernetes.get("pvName") or "")
                    in selected_pv_names
                )
            )
            row: dict[str, Any] = {
                **_identity(
                    item,
                    resource="volumes",
                    namespace=LONGHORN_NAMESPACE,
                ),
                "pvc": str(kubernetes.get("pvcName") or ""),
                "pv": str(kubernetes.get("pvName") or ""),
                "state": str(status.get("state") or ""),
                "robustness": str(status.get("robustness") or ""),
                "node_id": str(
                    spec.get("nodeID")
                    or status.get("currentNodeID")
                    or ""
                ),
            }
            if selected:
                longhorn_volumes.append(row)
            elif (
                name == OPENLDAP_LONGHORN_VOLUME
                or str(kubernetes.get("namespace") or "")
                == self.config.target.namespace
            ):
                foreign_longhorn.append(
                    {**row, "reason": "openldap-or-foreign-owner"}
                )

        selected_volume_names = {
            str(row["name"]) for row in longhorn_volumes
        }
        longhorn_snapshots: list[dict[str, str]] = []
        for item in self._list(
            "snapshots.longhorn.io", namespace=LONGHORN_NAMESPACE
        ):
            volume = str((item.get("spec") or {}).get("volume") or "")
            if volume in selected_volume_names:
                row = _identity(
                    item,
                    resource="snapshots",
                    namespace=LONGHORN_NAMESPACE,
                )
                row["volume"] = volume
                longhorn_snapshots.append(row)

        cluster_scoped: list[dict[str, str]] = []

        blockers: list[str] = []
        if not namespace_identity["uid"]:
            blockers.append("namespace-uid-missing")
        if not namespace_identity["rancher_project_id"]:
            blockers.append("rancher-project-id-missing")
        if namespace_identity["installer_owner"] != self.config.target.release:
            blockers.append("namespace-installer-owner-drift")
        if (
            namespace_identity["installer_config_digest"]
            != self.config.digest
        ):
            blockers.append("namespace-config-digest-drift")
        if not selected_pvcs:
            blockers.append("nomosmart-pvc-inventory-empty")
        if any(
            row["name"] == OPENLDAP_LONGHORN_VOLUME
            for row in longhorn_volumes
        ):
            blockers.append("openldap-volume-selected")
        if any(
            row["node_id"]
            or str(row["state"]).lower() not in {"", "detached"}
            for row in longhorn_volumes
        ):
            blockers.append("nomosmart-longhorn-volume-still-attached")
        if any(
            row["name"] == OPENLDAP_LONGHORN_VOLUME
            for row in foreign_longhorn
        ) is False:
            blockers.append("openldap-volume-exclusion-not-observed")

        namespaced.sort(
            key=lambda row: (row["kind"], row["namespace"], row["name"])
        )
        pvs.sort(key=lambda row: row["name"])
        longhorn_volumes.sort(key=lambda row: row["name"])
        longhorn_snapshots.sort(key=lambda row: row["name"])
        cluster_scoped.sort(key=lambda row: (row["kind"], row["name"]))
        preserved.sort(key=lambda row: (row["kind"], row["name"]))
        foreign_longhorn.sort(key=lambda row: row["name"])
        inventory = {
            "target": target,
            "namespace": namespace_identity,
            "helm": helm,
            "delete": {
                "namespaced_resources": namespaced,
                "persistent_volumes": pvs,
                "longhorn_volumes": longhorn_volumes,
                "longhorn_snapshots": longhorn_snapshots,
                "cluster_scoped_resources": cluster_scoped,
            },
            "preserve": {
                "named_resources": preserved,
                "longhorn_volumes": foreign_longhorn,
                "systems": [
                    "OpenLDAP",
                    "RKE2",
                    "Rancher",
                    "Registry",
                    "DNS",
                    "Rancher Project",
                    "Kubernetes Namespace",
                ],
            },
            "local_package_generation": self._local_generation(),
            "backup_choice": "delete-without-backup",
            "blockers": sorted(set(blockers)),
        }
        inventory["inventory_digest"] = _digest(inventory)
        return inventory

    def plan(self, output: Path) -> dict[str, Any]:
        inventory = self.inventory()
        core: dict[str, Any] = {
            "schema_version": FACTORY_PLAN_SCHEMA,
            "change_id": "CHG-252",
            "created_at": now(),
            "destructive": True,
            "irreversible": True,
            "gate4_is_not_delete_approval": True,
            "inventory": inventory,
            "ready_for_permanent_delete_approval": not inventory["blockers"],
        }
        digest = _digest(core)
        plan = {
            **core,
            "plan_digest": digest,
            "approval_phrase": (
                "Peter permanently approves CHG-252 factory plan " + digest
            ),
        }
        atomic_private_json(output, plan, overwrite=False)
        return {
            "status": "planned",
            "read_only": True,
            "plan": str(output),
            "plan_digest": digest,
            "ready_for_permanent_delete_approval": (
                plan["ready_for_permanent_delete_approval"]
            ),
            "blockers": inventory["blockers"],
            "approval_phrase": plan["approval_phrase"],
            "delete_counts": {
                key: len(value)
                for key, value in inventory["delete"].items()
            },
        }

    def _load(self, path: Path) -> dict[str, Any]:
        if (
            not path.is_file()
            or path.is_symlink()
            or stat.S_IMODE(path.stat().st_mode) & 0o077
        ):
            raise PreconditionError(
                "factory plan must be an owner-only regular file"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreconditionError("factory plan is invalid") from exc
        if not isinstance(payload, dict):
            raise PreconditionError("factory plan is invalid")
        core = dict(payload)
        supplied = str(core.pop("plan_digest", ""))
        approval = str(core.pop("approval_phrase", ""))
        if (
            core.get("schema_version") != FACTORY_PLAN_SCHEMA
            or supplied != _digest(core)
            or approval
            != "Peter permanently approves CHG-252 factory plan " + supplied
        ):
            raise DriftError("factory plan digest or schema is invalid")
        return payload

    def _delete(self, row: dict[str, Any]) -> None:
        self.kube.delete_api_precondition(
            api_version=str(row["api_version"]),
            resource=str(row["resource"]),
            name=str(row["name"]),
            namespace=str(row.get("namespace") or "") or None,
            uid=str(row["uid"]),
            resource_version=str(row["resource_version"]),
        )

    def _archive_local_generation(self, expected: dict[str, str]) -> str:
        current = self.config.application.package_dir / "current"
        if expected.get("status") != "present":
            return "missing"
        manifest = current / "manifest.json"
        if (
            not manifest.is_file()
            or manifest.is_symlink()
            or sha256_file(manifest) != expected.get("manifest_sha256")
        ):
            raise DriftError(
                "local package generation changed after factory planning"
            )
        generation = str(expected.get("generation_id") or "")
        if not generation or "/" in generation or generation in {".", ".."}:
            raise DriftError("local package generation identity is invalid")
        previous = self.config.application.package_dir / "previous"
        ensure_private_directory(previous)
        target = previous / generation
        if target.exists():
            raise PreconditionError(
                "local previous package generation already exists"
            )
        os.replace(current, target)
        return str(target)

    def apply(
        self,
        path: Path,
        *,
        confirmation: str,
        approval: str,
    ) -> dict[str, Any]:
        plan = self._load(path)
        if confirmation != plan["plan_digest"]:
            raise PreconditionError(
                "factory confirmation must exactly match the plan digest"
            )
        if approval != plan["approval_phrase"]:
            raise PreconditionError(
                "Gate 4 is insufficient; exact permanent-delete approval phrase is required"
            )
        if not plan.get("ready_for_permanent_delete_approval"):
            raise PreconditionError(
                "factory plan has blockers and cannot be applied"
            )
        current = self.inventory()
        planned = plan["inventory"]
        if (
            current.get("inventory_digest")
            != planned.get("inventory_digest")
            or current.get("namespace") != planned.get("namespace")
            or current.get("target") != planned.get("target")
        ):
            raise DriftError(
                "factory target changed after planning; generate a new plan"
            )
        delete = planned["delete"]
        namespaced = delete["namespaced_resources"]
        kind_order = {
            "Deployment": 10,
            "StatefulSet": 10,
            "DaemonSet": 10,
            "CronJob": 10,
            "Job": 20,
            "Ingress": 30,
            "Service": 30,
            "NetworkPolicy": 30,
            "PodDisruptionBudget": 30,
            "Cluster": 40,
            "DatabaseRole": 40,
            "Database": 40,
            "Backup": 40,
            "ScheduledBackup": 40,
            "ObjectStore": 40,
            "RoleBinding": 50,
            "Role": 50,
            "ServiceAccount": 50,
            "Lease": 50,
            "ConfigMap": 60,
            "Secret": 70,
            "PersistentVolumeClaim": 80,
            "VolumeSnapshot": 80,
        }
        deleted: list[str] = []
        for row in sorted(
            namespaced,
            key=lambda item: (
                kind_order.get(str(item["kind"]), 45),
                str(item["kind"]),
                str(item["name"]),
            ),
        ):
            self._delete(row)
            deleted.append(f"{row['kind']}/{row['name']}")
        for group in (
            delete["longhorn_snapshots"],
            delete["longhorn_volumes"],
            delete["persistent_volumes"],
            delete["cluster_scoped_resources"],
        ):
            for row in group:
                self._delete(row)
                deleted.append(f"{row['kind']}/{row['name']}")

        local_archive = self._archive_local_generation(
            planned["local_package_generation"]
        )
        for local in (self.store.local_path, self.store.receipt_path):
            if local.is_file() and not local.is_symlink():
                local.unlink()
        return {
            "status": "factory-reset-complete",
            "change_id": "CHG-252",
            "plan_digest": plan["plan_digest"],
            "deleted": deleted,
            "deleted_count": len(deleted),
            "namespace_preserved": self.config.target.namespace,
            "rancher_project_preserved": planned["namespace"][
                "rancher_project_id"
            ],
            "local_credential_generation_archived": local_archive,
            "next_command": "nomosmart-install plan --config <config>",
            "services_left_running": False,
            "completed_at": datetime.now(UTC).isoformat(),
        }
