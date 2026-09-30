from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .barman_cloud import (
    BarmanCloud,
    PLUGIN_IMAGE,
    PLUGIN_VERSION,
    RENDERED_MANIFEST_SHA256 as BARMAN_RENDERED_MANIFEST_SHA256,
    SIDECAR_IMAGE,
)
from .cloudnativepg import (
    CloudNativePG,
    OPERATOR_IMAGE,
    OPERATOR_VERSION,
    RENDERED_MANIFEST_SHA256 as CNPG_RENDERED_MANIFEST_SHA256,
)
from .config import InstallConfig
from .core import DriftError, InstallerError, now, sha256_bytes, sha256_file
from .directory import KeycloakDirectoryInstaller
from .helm import Helm
from .kube import Kubernetes
from .tls_client import TLSClient, TLSClientError


def _ready_condition(row: dict[str, Any]) -> bool:
    return any(
        item.get("type") == "Ready" and item.get("status") == "True"
        for item in (row.get("status") or {}).get("conditions") or []
    )


class Verifier:
    def __init__(
        self,
        config: InstallConfig,
        kube: Kubernetes,
        helm: Helm,
        directory: KeycloakDirectoryInstaller,
    ) -> None:
        self.config = config
        self.kube = kube
        self.helm = helm
        self.directory = directory

    def workloads(self) -> dict[str, Any]:
        external_profile = self.config.deployment_profile == "external-services"
        selector = f"app.kubernetes.io/instance={self.config.target.release}"
        deployments = self.kube.json(
            "get", "deployments", "-l", selector, namespace=True
        ).get("items") or []
        statefulsets = self.kube.json(
            "get", "statefulsets", "-l", selector, namespace=True
        ).get("items") or []
        pods = self.kube.json("get", "pods", "-l", selector, namespace=True).get(
            "items"
        ) or []
        pvcs = self.kube.json("get", "pvc", namespace=True).get("items") or []
        pdbs = self.kube.json(
            "get", "poddisruptionbudgets", "-l", selector, namespace=True
        ).get("items") or []
        if external_profile:
            postgresql_cluster: dict[str, Any] = {}
            postgresql_roles: list[dict[str, Any]] = []
            postgresql_databases: list[dict[str, Any]] = []
            postgresql_object_store: dict[str, Any] = {}
            postgresql_scheduled_backup: dict[str, Any] = {}
        else:
            postgresql_cluster = self.kube.json(
                "get",
                "clusters.postgresql.cnpg.io",
                f"{self._fullname()}-postgresql",
                namespace=True,
            )
            postgresql_roles = self.kube.json(
                "get",
                "databaseroles.postgresql.cnpg.io",
                namespace=True,
            ).get("items") or []
            postgresql_databases = self.kube.json(
                "get",
                "databases.postgresql.cnpg.io",
                namespace=True,
            ).get("items") or []
            postgresql_object_store = self.kube.json(
                "get",
                "objectstores.barmancloud.cnpg.io",
                f"{self._fullname()}-postgresql-backup",
                namespace=True,
            )
            postgresql_scheduled_backup = self.kube.json(
                "get",
                "scheduledbackups.postgresql.cnpg.io",
                f"{self._fullname()}-postgresql",
                namespace=True,
            )
        deployment_rows: list[dict[str, Any]] = []
        deployment_components: dict[str, dict[str, int]] = {}
        for row in deployments:
            desired = int((row.get("spec") or {}).get("replicas") or 0)
            available = int((row.get("status") or {}).get("availableReplicas") or 0)
            name = str((row.get("metadata") or {}).get("name") or "")
            component = str(
                ((row.get("metadata") or {}).get("labels") or {}).get(
                    "app.kubernetes.io/component"
                )
                or ""
            )
            deployment_rows.append(
                {
                    "name": name,
                    "component": component,
                    "desired": desired,
                    "available": available,
                }
            )
            if component:
                deployment_components[component] = {
                    "desired": desired,
                    "available": available,
                }
            if desired < 1 or available != desired:
                raise InstallerError(f"deployment/{name} is not fully available")
        for component in ("frontend", "backend", "worker"):
            evidence = deployment_components.get(component)
            if evidence is None or evidence["desired"] < 2:
                raise InstallerError(
                    f"production {component} Deployment does not have HA replicas"
                )
        beat = deployment_components.get("beat")
        if beat is None or beat["desired"] != 2:
            raise InstallerError(
                "production beat Deployment must have exactly two replicas"
            )
        deployment_expectations = (
            {}
            if external_profile
            else {
                "keycloak": 3,
                "redis-sentinel": 3,
            }
        )
        for component, expected in deployment_expectations.items():
            evidence = deployment_components.get(component)
            if evidence is None or evidence["desired"] != expected:
                raise InstallerError(
                    f"production {component} Deployment must have {expected} replicas"
                )
        stateful_rows: list[dict[str, Any]] = []
        stateful_components: dict[str, dict[str, int]] = {}
        for row in statefulsets:
            desired = int((row.get("spec") or {}).get("replicas") or 0)
            ready = int((row.get("status") or {}).get("readyReplicas") or 0)
            name = str((row.get("metadata") or {}).get("name") or "")
            component = str(
                ((row.get("metadata") or {}).get("labels") or {}).get(
                    "app.kubernetes.io/component"
                )
                or ""
            )
            stateful_rows.append(
                {
                    "name": name,
                    "component": component,
                    "desired": desired,
                    "ready": ready,
                }
            )
            if component:
                stateful_components[component] = {
                    "desired": desired,
                    "ready": ready,
                }
            if desired < 1 or ready != desired:
                raise InstallerError(f"statefulset/{name} is not fully ready")
        stateful_expectations = (
            {}
            if external_profile
            else {
                "opensearch": 3,
                "redis": 3,
                "rustfs": 4,
            }
        )
        for component, expected in stateful_expectations.items():
            evidence = stateful_components.get(component)
            if evidence is None or evidence["desired"] != expected:
                raise InstallerError(
                    f"production {component} StatefulSet must have {expected} replicas"
                )
        pod_rows: list[dict[str, Any]] = []
        component_nodes: dict[str, set[str]] = {
            "frontend": set(),
            "backend": set(),
            "worker": set(),
            "beat": set(),
        }
        if not external_profile:
            component_nodes.update(
                {
                    "keycloak": set(),
                    "opensearch": set(),
                    "postgresql": set(),
                    "redis": set(),
                    "redis-sentinel": set(),
                    "rustfs": set(),
                }
            )
        approved_images = {
            *self.config.images.inventory().values(),
            OPERATOR_IMAGE,
            PLUGIN_IMAGE,
            SIDECAR_IMAGE,
        }
        for row in pods:
            name = str((row.get("metadata") or {}).get("name") or "")
            phase = str((row.get("status") or {}).get("phase") or "")
            ready = _ready_condition(row)
            component = str(
                (
                    (row.get("metadata") or {}).get("labels") or {}
                ).get("app.kubernetes.io/component")
                or ""
            )
            pod_labels = (row.get("metadata") or {}).get("labels") or {}
            historical_installer_job = (
                pod_labels.get("nomosmart.io/installer-job") == "true"
                or pod_labels.get("nomosmart.io/installer-action")
                == "directory-reconcile"
            )
            node = str((row.get("spec") or {}).get("nodeName") or "")
            pod_images = sorted(
                {
                    str(container.get("image") or "")
                    for field in ("initContainers", "containers")
                    for container in (
                        (row.get("spec") or {}).get(field) or []
                    )
                    if container.get("image")
                }
            )
            unapproved = [
                image
                for image in pod_images
                if image not in approved_images
            ]
            if unapproved:
                raise InstallerError(
                    f"pod/{name} uses an image outside the approved digest inventory"
                )
            pod_rows.append(
                {
                    "name": name,
                    "component": component,
                    "node": node,
                    "phase": phase,
                    "ready": ready,
                    "images": pod_images,
                    "historical_installer_failure": (
                        phase == "Failed" and historical_installer_job
                    ),
                }
            )
            if (
                phase not in {"Succeeded", "Failed"}
                and not ready
            ) or (phase == "Failed" and not historical_installer_job):
                raise InstallerError(f"pod/{name} is not Ready")
            if component in component_nodes and phase == "Running" and ready:
                component_nodes[component].add(node)
        minimum_domains = {
            "frontend": 2,
            "backend": 2,
            "worker": 2,
            "beat": 2,
        }
        if not external_profile:
            minimum_domains.update(
                {
                    "keycloak": 3,
                    "opensearch": 3,
                    "postgresql": 3,
                    "redis": 3,
                    "redis-sentinel": 3,
                    "rustfs": 3,
                }
            )
        for component, nodes in component_nodes.items():
            if len(nodes) < minimum_domains[component]:
                raise InstallerError(
                    f"production {component} Pods are not spread across "
                    f"{minimum_domains[component]} nodes"
                )
        beat_roles: dict[str, str] = {}
        for pod in pod_rows:
            if (
                pod["component"] == "beat"
                and pod["phase"] == "Running"
                and pod["ready"]
            ):
                result = self.kube.run(
                    "exec",
                    pod["name"],
                    "--container",
                    "beat",
                    "--",
                    "cat",
                    "/tmp/nomosmart-beat-agent.role",
                    namespace=True,
                )
                beat_roles[pod["name"]] = result.stdout.strip()
        if sorted(beat_roles.values()) != ["active", "standby"]:
            raise InstallerError(
                "Celery Beat must have exactly one active and one standby Pod"
            )
        pvc_rows = [
            {
                "name": str((row.get("metadata") or {}).get("name") or ""),
                "phase": str((row.get("status") or {}).get("phase") or ""),
            }
            for row in pvcs
        ]
        if any(row["phase"] != "Bound" for row in pvc_rows):
            raise InstallerError("one or more NomoSmart PVCs are not Bound")
        pdb_rows: list[dict[str, Any]] = []
        for row in pdbs:
            name = str((row.get("metadata") or {}).get("name") or "")
            status = row.get("status") or {}
            current_healthy = int(status.get("currentHealthy") or 0)
            desired_healthy = int(status.get("desiredHealthy") or 0)
            disruptions_allowed = int(
                status.get("disruptionsAllowed") or 0
            )
            pdb_rows.append(
                {
                    "name": name,
                    "current_healthy": current_healthy,
                    "desired_healthy": desired_healthy,
                    "disruptions_allowed": disruptions_allowed,
                }
            )
            if (
                current_healthy < desired_healthy
                or disruptions_allowed < 1
            ):
                raise InstallerError(
                    f"poddisruptionbudget/{name} does not allow one safe disruption"
                )
        required_pdbs = {
            f"{self._fullname()}-{component}"
            for component in (
                "frontend",
                "backend",
                "worker",
                "beat",
            )
        }
        if not external_profile:
            required_pdbs.update(
                f"{self._fullname()}-{component}"
                for component in (
                    "keycloak",
                    "opensearch",
                    "postgresql",
                    "redis",
                    "redis-sentinel",
                    "rustfs",
                )
            )
        present_pdbs = {row["name"] for row in pdb_rows}
        missing_pdbs = sorted(required_pdbs - present_pdbs)
        if missing_pdbs:
            raise InstallerError(
                "required production PodDisruptionBudgets are missing: "
                + ", ".join(missing_pdbs)
            )
        if external_profile:
            postgresql = {
                "mode": "external",
                "status": "operator-owned",
            }
            postgresql_backup = {
                "mode": "external",
                "status": "operator-owned",
            }
        else:
            cluster_spec = postgresql_cluster.get("spec") or {}
            cluster_status = postgresql_cluster.get("status") or {}
            cluster_conditions = {
                str(row.get("type") or ""): str(row.get("status") or "")
                for row in cluster_status.get("conditions") or []
                if isinstance(row, dict)
            }
            postgresql = {
                "name": str(
                    (postgresql_cluster.get("metadata") or {}).get("name")
                    or ""
                ),
                "instances": int(cluster_spec.get("instances") or 0),
                "ready_instances": int(
                    cluster_status.get("readyInstances") or 0
                ),
                "current_primary": str(
                    cluster_status.get("currentPrimary") or ""
                ),
                "roles": sorted(
                    str((row.get("metadata") or {}).get("name") or "")
                    for row in postgresql_roles
                    if (row.get("status") or {}).get("applied") is True
                ),
                "databases": sorted(
                    str((row.get("metadata") or {}).get("name") or "")
                    for row in postgresql_databases
                    if (row.get("status") or {}).get("applied") is True
                ),
                "continuous_archiving": cluster_conditions.get(
                    "ContinuousArchiving"
                ),
                "last_backup_succeeded": cluster_conditions.get(
                    "LastBackupSucceeded"
                ),
            }
            expected_roles = {
                f"{self._fullname()}-postgresql-app",
                f"{self._fullname()}-postgresql-keycloak",
            }
            if (
                postgresql["instances"] != 3
                or postgresql["ready_instances"] != 3
                or not postgresql["current_primary"]
                or not expected_roles.issubset(set(postgresql["roles"]))
                or f"{self._fullname()}-postgresql-keycloak"
                not in postgresql["databases"]
                or postgresql["continuous_archiving"] != "True"
                or postgresql["last_backup_succeeded"] != "True"
            ):
                raise InstallerError(
                    "CloudNativePG three-instance cluster, roles or database is not ready"
                )
            backup_spec = postgresql_object_store.get("spec") or {}
            backup_configuration = backup_spec.get("configuration") or {}
            recovery_windows = (
                (postgresql_object_store.get("status") or {}).get(
                    "serverRecoveryWindow"
                )
                or {}
            )
            scheduled_spec = postgresql_scheduled_backup.get("spec") or {}
            completed_backup = self.kube.wait_cloudnativepg_backup(
                self._fullname(), timeout=30
            )
            if (
                not str(
                    backup_configuration.get("endpointURL") or ""
                ).startswith("https://")
                or not backup_configuration.get("endpointCA")
                or not recovery_windows
                or scheduled_spec.get("method") != "plugin"
                or (
                    (scheduled_spec.get("pluginConfiguration") or {}).get(
                        "name"
                    )
                    != "barman-cloud.cloudnative-pg.io"
                )
            ):
                raise InstallerError(
                    "CloudNativePG TLS ObjectStore, WAL recovery window or scheduled backup is not ready"
                )
            postgresql_backup = {
                "object_store": str(
                    (postgresql_object_store.get("metadata") or {}).get(
                        "name"
                    )
                    or ""
                ),
                "server_recovery_windows": sorted(recovery_windows),
                "schedule": str(scheduled_spec.get("schedule") or ""),
                "method": str(scheduled_spec.get("method") or ""),
                "completed_backup": completed_backup,
            }
        canonical = json.dumps(
            {
                "deployments": deployment_rows,
                "statefulsets": stateful_rows,
                "pods": pod_rows,
                "pvcs": pvc_rows,
                "poddisruptionbudgets": pdb_rows,
                "postgresql": postgresql,
                "postgresql_backup": postgresql_backup,
                "beat_roles": beat_roles,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "deployments": deployment_rows,
            "statefulsets": stateful_rows,
            "pods": pod_rows,
            "pvcs": pvc_rows,
            "poddisruptionbudgets": pdb_rows,
            "postgresql": postgresql,
            "postgresql_backup": postgresql_backup,
            "beat_roles": beat_roles,
            "placement": {
                component: sorted(nodes)
                for component, nodes in component_nodes.items()
            },
            "fingerprint": sha256_bytes(canonical.encode("utf-8")),
        }

    def public_endpoints(self) -> dict[str, Any]:
        ca_file = (
            self.config.application.package_dir
            / "current/tls/active/edge-ca.crt"
        )
        client = TLSClient(
            ca_file=str(ca_file),
            timeout=30,
            max_body=1024 * 1024,
            max_redirects=3,
        )
        paths = {
            "frontend": "/",
            "backend_readiness": "/api/backend/ready",
            "oidc_discovery": (
                f"/identity/realms/{self.config.identity.realm}"
                "/.well-known/openid-configuration"
            ),
        }
        result: dict[str, Any] = {}
        for name, path in paths.items():
            try:
                response = client.request(
                    "GET",
                    f"https://{self.config.application.public_host}{path}",
                    headers={"Accept": "application/json,text/html"},
                    content_types=(
                        ("text/html",)
                        if name == "frontend"
                        else ("application/json",)
                    ),
                )
                result[name] = {
                    "status": response.status,
                    "content_type": response.content_type,
                }
                if name == "backend_readiness":
                    try:
                        payload = json.loads(
                            response.body.decode("utf-8")
                        )
                    except (json.JSONDecodeError, UnicodeError) as exc:
                        raise InstallerError(
                            "public Backend readiness response is invalid"
                        ) from exc
                    if (
                        not isinstance(payload, dict)
                        or payload.get("status") != "ready"
                    ):
                        raise InstallerError(
                            "public Backend readiness is not ready"
                        )
                    result[name]["application_status"] = "ready"
            except TLSClientError as exc:
                raise InstallerError(f"public endpoint {name} is unavailable") from exc
            if result[name]["status"] != 200:
                raise InstallerError(f"public endpoint {name} is not healthy")
        return result

    def secret_fingerprints(self) -> dict[str, dict[str, str]]:
        names = {
            self.config.application.runtime_secret,
            self.config.application.ingress_tls_secret,
        }
        if self.config.deployment_profile == "external-services":
            names.update(self.config.external_ca_secret_names)
        else:
            names.update(
                {
                    self.config.application.rustfs_tls_secret,
                    self.config.application.opensearch_tls_secret,
                    f"{self._fullname()}-postgresql-tls",
                    f"{self._fullname()}-postgresql-replication-tls",
                    f"{self._fullname()}-redis-tls",
                    f"{self._fullname()}-postgresql-superuser",
                    f"{self._fullname()}-postgresql-migration",
                    f"{self._fullname()}-postgresql-app",
                    f"{self._fullname()}-postgresql-keycloak",
                }
            )
        if self.config.identity.mode != "preconfigured":
            names.add(self.config.identity.bind_secret_name)
            names.add(self.config.identity.ca_secret_name)
        return {name: self.kube.secret_fingerprints(name) for name in sorted(names)}

    def verify(self) -> dict[str, Any]:
        target = self.kube.validate_identity()
        if self.kube.namespace_state() != "owned":
            raise DriftError(
                "target namespace is no longer owned by this installer"
            )
        helm = self.helm.status()
        if helm["status"] != "deployed":
            raise InstallerError("Helm release is not deployed")
        phase = self.kube.json(
            "get",
            "configmap",
            f"{self._fullname()}-config",
            namespace=True,
        )
        deployment_phase = str((phase.get("data") or {}).get("DEPLOYMENT_PHASE") or "")
        if deployment_phase != "operational":
            raise DriftError(
                "deployed release is no longer in the operational phase"
            )
        directory = self.directory.verify_provider()
        directory_mapping = self.directory.verify_application_mapping()
        workload = self.workloads()
        public = self.public_endpoints()
        if self.config.deployment_profile == "external-services":
            cloudnativepg = {"action": "not-required"}
            barman_cloud = {"action": "not-required"}
        else:
            cloudnativepg = CloudNativePG(self.config, self.kube).plan()
            barman_cloud = BarmanCloud(self.config, self.kube).plan()
            if cloudnativepg.get("action") != "reuse":
                raise InstallerError("CloudNativePG operator requires repair")
            if barman_cloud.get("action") != "reuse":
                raise InstallerError("Barman Cloud plugin requires repair")
        return {
            "schema_version": 1,
            "verified_at": now(),
            "status": "verified",
            "config_digest": self.config.digest,
            "target": target,
            "namespace": self.config.target.namespace,
            "release": self.config.target.release,
            "deployment_phase": deployment_phase,
            "helm": helm,
            "chart": {
                "path": str(self.config.application.chart),
                "version": self.config.chart_version,
                "chart_yaml_sha256": sha256_file(
                    self.config.application.chart / "Chart.yaml"
                ),
                "chart_tree_sha256": self.config.chart_digest,
            },
            "images": self.config.images.inventory(),
            "operators": (
                {}
                if self.config.deployment_profile == "external-services"
                else {
                    "cloudnativepg": {
                        "version": OPERATOR_VERSION,
                        "image": OPERATOR_IMAGE,
                        "rendered_manifest_sha256": CNPG_RENDERED_MANIFEST_SHA256,
                    },
                    "barman_cloud": {
                        "version": PLUGIN_VERSION,
                        "image": PLUGIN_IMAGE,
                        "sidecar_image": SIDECAR_IMAGE,
                        "rendered_manifest_sha256": BARMAN_RENDERED_MANIFEST_SHA256,
                    },
                }
            ),
            "resource_evidence": workload,
            "secret_fingerprints": self.secret_fingerprints(),
            "directory": directory,
            "directory_mapping": directory_mapping,
            "public_https": public,
            "pending_checkpoints": [],
        }

    def _fullname(self) -> str:
        release = self.config.target.release
        return (release if "nomosmart" in release else f"{release}-nomosmart")[
            :63
        ].rstrip("-")
