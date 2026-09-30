from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import socket
import time
from typing import Any

from .config import InstallConfig
from .core import DriftError, InstallerError, PreconditionError, Runner, sha256_bytes


OWNER_LABEL = "nomosmart.io/installer-owner"
CONFIG_ANNOTATION = "nomosmart.io/installer-config-digest"


class Kubernetes:
    def __init__(self, config: InstallConfig, runner: Runner) -> None:
        self.config = config
        self.runner = runner
        self.base = ["kubectl", "--context", config.target.context]

    def run(
        self,
        *arguments: str,
        namespace: bool | str = False,
        input_text: str | None = None,
        timeout: int = 120,
        accepted: frozenset[int] = frozenset({0}),
        sensitive_output: bool = False,
    ):
        command = [*self.base]
        if namespace:
            command.extend(
                [
                    "--namespace",
                    namespace
                    if isinstance(namespace, str)
                    else self.config.target.namespace,
                ]
            )
        command.extend(arguments)
        return self.runner.run(
            command,
            input_text=input_text,
            timeout=timeout,
            accepted=accepted,
            sensitive_output=sensitive_output,
        )

    def json(
        self, *arguments: str, namespace: bool | str = False
    ) -> dict[str, Any]:
        result = self.run(*arguments, "-o", "json", namespace=namespace)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise InstallerError("kubectl returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise InstallerError("kubectl returned an invalid object")
        return payload

    def exists(
        self, kind: str, name: str, *, namespace: bool | str = True
    ) -> bool:
        result = self.run(
            "get",
            kind,
            name,
            namespace=namespace,
            accepted=frozenset({0, 1}),
        )
        return result.returncode == 0

    def current_context(self) -> str:
        return self.run("config", "current-context").stdout.strip()

    def api_server(self) -> str:
        payload = self.json("config", "view", "--minify")
        clusters = payload.get("clusters") or []
        if len(clusters) != 1:
            raise PreconditionError("kubeconfig must resolve exactly one current cluster")
        cluster = clusters[0].get("cluster") if isinstance(clusters[0], dict) else {}
        server = str(cluster.get("server") or "").rstrip("/")
        if not server:
            raise PreconditionError("kubeconfig current cluster has no API server")
        return server

    def cluster_uid(self) -> str:
        payload = self.json("get", "namespace", "kube-system")
        uid = str((payload.get("metadata") or {}).get("uid") or "")
        if not uid:
            raise PreconditionError("kube-system namespace has no cluster UID")
        return uid

    def validate_identity(self) -> dict[str, str]:
        actual = {
            "context": self.current_context(),
            "api_server": self.api_server(),
            "cluster_uid": self.cluster_uid(),
        }
        expected = {
            "context": self.config.target.context,
            "api_server": self.config.target.api_server.rstrip("/"),
            "cluster_uid": self.config.target.cluster_uid,
        }
        mismatches = [key for key in expected if actual[key] != expected[key]]
        if mismatches:
            raise PreconditionError("target identity mismatch: " + ", ".join(mismatches))
        return actual

    def validate_rbac(self) -> None:
        checks = [
            ("get", "nodes", False),
            ("list", "nodes", False),
            ("get", "storageclasses.storage.k8s.io", False),
            ("get", "ingressclasses.networking.k8s.io", False),
            ("create", "namespaces", False),
            ("get", "secrets", True),
            ("list", "secrets", True),
            ("create", "secrets", True),
            ("patch", "secrets", True),
            ("update", "secrets", True),
            ("get", "configmaps", True),
            ("list", "configmaps", True),
            ("create", "configmaps", True),
            ("patch", "configmaps", True),
            ("get", "leases.coordination.k8s.io", True),
            ("create", "leases.coordination.k8s.io", True),
            ("update", "leases.coordination.k8s.io", True),
            ("patch", "leases.coordination.k8s.io", True),
            ("delete", "leases.coordination.k8s.io", True),
            ("create", "deployments.apps", True),
            ("get", "deployments.apps", True),
            ("list", "deployments.apps", True),
            ("watch", "deployments.apps", True),
            ("update", "deployments.apps", True),
            ("patch", "deployments.apps", True),
            ("create", "statefulsets.apps", True),
            ("get", "statefulsets.apps", True),
            ("list", "statefulsets.apps", True),
            ("watch", "statefulsets.apps", True),
            ("update", "statefulsets.apps", True),
            ("patch", "statefulsets.apps", True),
            ("create", "jobs.batch", True),
            ("get", "jobs.batch", True),
            ("list", "jobs.batch", True),
            ("watch", "jobs.batch", True),
            ("patch", "jobs.batch", True),
            ("get", "pods", True),
            ("list", "pods", True),
            ("watch", "pods", True),
            ("create", "pods/exec", True),
            ("create", "services", True),
            ("get", "services", True),
            ("list", "services", True),
            ("update", "services", True),
            ("patch", "services", True),
            ("create", "persistentvolumeclaims", True),
            ("get", "persistentvolumeclaims", True),
            ("list", "persistentvolumeclaims", True),
            ("create", "ingresses.networking.k8s.io", True),
            ("get", "ingresses.networking.k8s.io", True),
            ("list", "ingresses.networking.k8s.io", True),
            ("update", "ingresses.networking.k8s.io", True),
            ("patch", "ingresses.networking.k8s.io", True),
            ("list", "ingresses.networking.k8s.io", False),
            ("create", "networkpolicies.networking.k8s.io", True),
            ("patch", "networkpolicies.networking.k8s.io", True),
            ("create", "poddisruptionbudgets.policy", True),
            ("get", "poddisruptionbudgets.policy", True),
            ("list", "poddisruptionbudgets.policy", True),
            ("update", "poddisruptionbudgets.policy", True),
            ("patch", "poddisruptionbudgets.policy", True),
            ("create", "serviceaccounts", True),
            ("patch", "serviceaccounts", True),
            ("create", "roles.rbac.authorization.k8s.io", True),
            ("patch", "roles.rbac.authorization.k8s.io", True),
            ("create", "rolebindings.rbac.authorization.k8s.io", True),
            ("patch", "rolebindings.rbac.authorization.k8s.io", True),
        ]
        denied: list[str] = []
        for verb, resource, namespaced in checks:
            command = ["auth", "can-i", verb, resource]
            if namespaced:
                command.extend(["--namespace", self.config.target.namespace])
            elif resource == "ingresses.networking.k8s.io":
                command.append("--all-namespaces")
            result = self.run(*command)
            if result.stdout.strip().lower() != "yes":
                denied.append(f"{verb}:{resource}")
        if denied:
            raise PreconditionError("operator RBAC is incomplete: " + ", ".join(denied))
        longhorn_namespace = "longhorn-system"
        longhorn_checks = (
            ("list", "nodes.longhorn.io"),
            ("list", "volumes.longhorn.io"),
            ("list", "replicas.longhorn.io"),
        )
        longhorn_denied = []
        for verb, resource in longhorn_checks:
            result = self.run(
                "auth",
                "can-i",
                verb,
                resource,
                namespace=longhorn_namespace,
            )
            if result.stdout.strip().lower() != "yes":
                longhorn_denied.append(f"{verb}:{resource}")
        for verb, resource in (
            ("get", "persistentvolumes"),
            ("list", "persistentvolumes"),
        ):
            result = self.run("auth", "can-i", verb, resource)
            if result.stdout.strip().lower() != "yes":
                longhorn_denied.append(f"{verb}:{resource}")
        for resource in ("pods", "deployments.apps"):
            result = self.run(
                "auth", "can-i", "list", resource, "--all-namespaces"
            )
            if result.stdout.strip().lower() != "yes":
                longhorn_denied.append(f"list-all-namespaces:{resource}")
        if longhorn_denied:
            raise PreconditionError(
                "capacity inventory RBAC is incomplete: "
                + ", ".join(longhorn_denied)
            )

    def validate_nodes(self, minimum: int = 3) -> list[str]:
        payload = self.json("get", "nodes")
        ready: list[str] = []
        for node in payload.get("items") or []:
            if (node.get("spec") or {}).get("unschedulable"):
                continue
            conditions = (node.get("status") or {}).get("conditions") or []
            if any(item.get("type") == "Ready" and item.get("status") == "True" for item in conditions):
                ready.append(str((node.get("metadata") or {}).get("name") or ""))
        ready = [item for item in ready if item]
        if len(ready) < minimum:
            raise PreconditionError(f"cluster has {len(ready)} Ready schedulable nodes; {minimum} are required")
        return sorted(ready)

    def validate_platform_classes(self) -> None:
        self.run("get", "storageclass", self.config.application.storage_class)
        self.run("get", "ingressclass", self.config.application.ingress_class)

    def validate_ingress_controller(self) -> list[str]:
        namespace = self.config.application.ingress_controller_namespace
        selector = (
            "app.kubernetes.io/name="
            f"{self.config.application.ingress_controller_name}"
        )
        payload = self.json(
            "get",
            "pods",
            "--namespace",
            namespace,
            "--selector",
            selector,
        )
        ready = sorted(
            str((row.get("metadata") or {}).get("name") or "")
            for row in payload.get("items") or []
            if any(
                condition.get("type") == "Ready"
                and condition.get("status") == "True"
                for condition in (
                    (row.get("status") or {}).get("conditions") or []
                )
            )
        )
        ready = [name for name in ready if name]
        if not ready:
            raise PreconditionError(
                "configured ingress controller selector has no Ready Pods"
            )
        return ready

    def wait_cloudnativepg_cluster(
        self,
        fullname: str,
        *,
        instances: int = 3,
        timeout: int = 1200,
    ) -> dict[str, Any]:
        cluster_name = f"{fullname}-postgresql"
        role_names = {
            f"{cluster_name}-app",
            f"{cluster_name}-keycloak",
        }
        database_name = f"{cluster_name}-keycloak"
        deadline = time.monotonic() + timeout
        last_status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                cluster = self.json(
                    "get",
                    "clusters.postgresql.cnpg.io",
                    cluster_name,
                    namespace=True,
                )
                status = cluster.get("status") or {}
                conditions = status.get("conditions") or []
                cluster_ready = (
                    int(status.get("readyInstances") or 0) == instances
                    and any(
                        item.get("type") == "Ready"
                        and item.get("status") == "True"
                        for item in conditions
                    )
                )
                roles = self.json(
                    "get",
                    "databaseroles.postgresql.cnpg.io",
                    namespace=True,
                ).get("items") or []
                applied_roles = {
                    str((row.get("metadata") or {}).get("name") or "")
                    for row in roles
                    if (row.get("status") or {}).get("applied") is True
                    and (row.get("status") or {}).get("observedGeneration")
                    == (row.get("metadata") or {}).get("generation")
                }
                database = self.json(
                    "get",
                    "databases.postgresql.cnpg.io",
                    database_name,
                    namespace=True,
                )
                database_applied = (
                    (database.get("status") or {}).get("applied") is True
                    and (database.get("status") or {}).get(
                        "observedGeneration"
                    )
                    == (database.get("metadata") or {}).get("generation")
                )
                last_status = {
                    "cluster": cluster_name,
                    "ready_instances": int(
                        status.get("readyInstances") or 0
                    ),
                    "current_primary": str(
                        status.get("currentPrimary") or ""
                    ),
                    "applied_roles": sorted(applied_roles & role_names),
                    "database": database_name,
                    "database_applied": database_applied,
                }
                if (
                    cluster_ready
                    and role_names.issubset(applied_roles)
                    and database_applied
                ):
                    return last_status
            except InstallerError:
                last_status = {"cluster": cluster_name, "status": "waiting"}
            time.sleep(5)
        raise PreconditionError(
            "CloudNativePG cluster/database/roles did not become ready: "
            + json.dumps(last_status, sort_keys=True)
        )

    def wait_cloudnativepg_backup(
        self,
        fullname: str,
        *,
        timeout: int = 1800,
        interval: float = 5.0,
    ) -> dict[str, Any]:
        cluster_name = f"{fullname}-postgresql"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            payload = self.json(
                "get", "backups.postgresql.cnpg.io", namespace=True
            )
            matches = [
                row
                for row in payload.get("items") or []
                if isinstance(row, dict)
                and str(
                    (((row.get("spec") or {}).get("cluster") or {}).get("name"))
                    or ""
                )
                == cluster_name
            ]
            matches.sort(
                key=lambda row: str(
                    (row.get("metadata") or {}).get("creationTimestamp") or ""
                ),
                reverse=True,
            )
            for row in matches:
                phase = str((row.get("status") or {}).get("phase") or "").lower()
                name = str((row.get("metadata") or {}).get("name") or "")
                if phase == "completed":
                    return {
                        "name": name,
                        "phase": phase,
                        "started_at": str(
                            (row.get("status") or {}).get("startedAt") or ""
                        ),
                        "stopped_at": str(
                            (row.get("status") or {}).get("stoppedAt") or ""
                        ),
                    }
                if phase in {"failed", "stopped"}:
                    raise InstallerError(
                        f"CloudNativePG Backup/{name} ended in phase {phase}"
                    )
            time.sleep(interval)
        raise InstallerError(
            f"CloudNativePG Cluster/{cluster_name} has no completed backup"
        )

    def validate_dns(self) -> list[str]:
        try:
            rows = socket.getaddrinfo(
                self.config.application.public_host,
                443,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise PreconditionError("public hostname does not resolve from the operator host") from exc
        addresses = sorted({str(row[4][0]) for row in rows})
        if not addresses:
            raise PreconditionError("public hostname has no address")
        return addresses

    def validate_public_https_path(self, addresses: list[str]) -> str:
        for address in addresses:
            try:
                with socket.create_connection((address, 443), timeout=5):
                    return address
            except OSError:
                continue
        raise PreconditionError(
            "operator host cannot reach TCP/443 for the public hostname"
        )

    def validate_public_host_collision(self) -> None:
        payload = self.json(
            "get", "ingresses", "--all-namespaces"
        )
        host = self.config.application.public_host.casefold()
        collisions: list[str] = []
        for row in payload.get("items") or []:
            metadata = row.get("metadata") or {}
            namespace = str(metadata.get("namespace") or "")
            name = str(metadata.get("name") or "")
            labels = metadata.get("labels") or {}
            rules = (row.get("spec") or {}).get("rules") or []
            tls_rows = (row.get("spec") or {}).get("tls") or []
            hosts = {
                str(rule.get("host") or "").rstrip(".").casefold()
                for rule in rules
            }
            hosts.update(
                str(item).rstrip(".").casefold()
                for tls in tls_rows
                for item in (tls.get("hosts") or [])
            )
            if host not in hosts:
                continue
            if (
                namespace == self.config.target.namespace
                and labels.get("app.kubernetes.io/instance")
                == self.config.target.release
            ):
                continue
            collisions.append(f"{namespace}/{name}")
        if collisions:
            raise PreconditionError(
                "public hostname is already claimed by ingress/"
                + ", ingress/".join(sorted(collisions))
            )

    def namespace_state(self) -> str:
        if not self.exists("namespace", self.config.target.namespace, namespace=False):
            return "absent"
        payload = self.json("get", "namespace", self.config.target.namespace)
        namespace_metadata = payload.get("metadata") or {}
        labels = namespace_metadata.get("labels") or {}
        owned = labels.get(OWNER_LABEL) == self.config.target.release
        if owned and (
            (namespace_metadata.get("annotations") or {}).get(
                CONFIG_ANNOTATION
            )
            != self.config.digest
        ):
            raise DriftError(
                "owned target namespace configuration digest differs"
            )
        state_name = f"{self.config.target.release}-installer-state"
        if owned and self.exists("configmap", state_name):
            state = self.json("get", "configmap", state_name, namespace=True)
            state_metadata = state.get("metadata") or {}
            state_labels = state_metadata.get("labels") or {}
            if (
                state_labels.get(OWNER_LABEL)
                != self.config.target.release
                or (state_metadata.get("annotations") or {}).get(
                    CONFIG_ANNOTATION
                )
                != self.config.digest
            ):
                raise DriftError(
                    "target namespace has an incompatible installer state ConfigMap"
                )
            return "owned"
        resources = self.json(
            "get",
            "all,configmap,secret,pvc,ingress,lease",
            "--ignore-not-found",
            namespace=True,
        )
        allowed_input_secrets: set[str] = set()
        if self.config.identity.mode != "preconfigured":
            allowed_input_secrets.update(
                {
                    self.config.identity.bind_secret_name,
                    self.config.identity.ca_secret_name,
                }
            )
        if (
            self.config.deployment_profile == "external-services"
            and self.config.application.runtime_secret_mode == "existing"
        ):
            allowed_input_secrets.add(self.config.application.runtime_secret)
            allowed_input_secrets.update(self.config.external_ca_secret_names)
        if self.config.application.registry_pull_secret:
            allowed_input_secrets.add(
                self.config.application.registry_pull_secret
            )
        unexpected = []
        for row in resources.get("items") or []:
            kind = str(row.get("kind") or "")
            metadata = row.get("metadata") or {}
            name = str(metadata.get("name") or "")
            if kind == "ConfigMap" and name == "kube-root-ca.crt":
                continue
            if kind == "Secret" and name in allowed_input_secrets:
                continue
            if (
                kind == "Lease"
                and name == f"{self.config.target.release}-installer"
                and (metadata.get("labels") or {}).get(OWNER_LABEL)
                == self.config.target.release
                and (metadata.get("annotations") or {}).get(
                    CONFIG_ANNOTATION
                )
                == self.config.digest
            ):
                continue
            unexpected.append(f"{kind}/{name}")
        if unexpected:
            raise PreconditionError("target namespace exists with unowned resources")
        return "owned" if owned else "empty"

    def ensure_namespace(self) -> None:
        state = self.namespace_state()
        manifest = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": self.config.target.namespace,
                "labels": {OWNER_LABEL: self.config.target.release},
                "annotations": {CONFIG_ANNOTATION: self.config.digest},
            },
        }
        if state == "absent":
            self.run("create", "-f", "-", input_text=json.dumps(manifest))
        elif state == "empty":
            self.run(
                "apply",
                "-f",
                "-",
                input_text=json.dumps(manifest),
            )
        else:
            payload = self.json("get", "namespace", self.config.target.namespace)
            annotation = str(((payload.get("metadata") or {}).get("annotations") or {}).get(CONFIG_ANNOTATION) or "")
            if annotation and annotation != self.config.digest:
                raise DriftError("owned namespace configuration digest does not match")

    def secret_fingerprints(self, name: str) -> dict[str, str]:
        payload = self.json("get", "secret", name, namespace=True)
        result: dict[str, str] = {}
        for key, encoded in ((payload.get("data") or {}).items()):
            try:
                result[str(key)] = sha256_bytes(base64.b64decode(str(encoded), validate=True))
            except ValueError as exc:
                raise DriftError(f"secret/{name} key {key} is not valid base64") from exc
        return result

    def ensure_secret(
        self,
        name: str,
        files: dict[str, Path],
        *,
        component: str,
        secret_type: str | None = None,
        extra_labels: dict[str, str] | None = None,
    ) -> dict[str, str]:
        expected = {key: sha256_bytes(path.read_bytes()) for key, path in files.items()}
        if self.exists("secret", name):
            payload = self.json("get", "secret", name, namespace=True)
            metadata = payload.get("metadata") or {}
            labels = metadata.get("labels") or {}
            annotations = metadata.get("annotations") or {}
            if labels.get(OWNER_LABEL) != self.config.target.release:
                raise DriftError(f"secret/{name} exists but is not installer-owned")
            if annotations.get(CONFIG_ANNOTATION) != self.config.digest:
                raise DriftError(f"secret/{name} configuration digest does not match")
            if self.secret_fingerprints(name) != expected:
                raise DriftError(f"secret/{name} data fingerprint does not match")
            return expected
        data = {key: base64.b64encode(path.read_bytes()).decode("ascii") for key, path in files.items()}
        manifest = {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": secret_type or ("kubernetes.io/tls" if set(files) == {"tls.crt", "tls.key"} else "Opaque"),
            "metadata": {
                "name": name,
                "namespace": self.config.target.namespace,
                "labels": {
                    OWNER_LABEL: self.config.target.release,
                    "app.kubernetes.io/component": component,
                    **(extra_labels or {}),
                },
                "annotations": {CONFIG_ANNOTATION: self.config.digest},
            },
            "data": data,
        }
        self.run(
            "create",
            "-f",
            "-",
            namespace=False,
            input_text=json.dumps(manifest),
            sensitive_output=True,
        )
        return expected

    def ensure_basic_auth_secret(
        self,
        name: str,
        *,
        username: str,
        password_file: Path,
        component: str,
    ) -> dict[str, str]:
        values = {
            "username": username.encode("utf-8"),
            "password": password_file.read_bytes(),
        }
        expected = {key: sha256_bytes(value) for key, value in values.items()}
        if self.exists("secret", name):
            payload = self.json("get", "secret", name, namespace=True)
            metadata = payload.get("metadata") or {}
            labels = metadata.get("labels") or {}
            annotations = metadata.get("annotations") or {}
            if labels.get(OWNER_LABEL) != self.config.target.release:
                raise DriftError(f"secret/{name} exists but is not installer-owned")
            if annotations.get(CONFIG_ANNOTATION) != self.config.digest:
                raise DriftError(f"secret/{name} configuration digest does not match")
            if payload.get("type") != "kubernetes.io/basic-auth":
                raise DriftError(f"secret/{name} is not kubernetes.io/basic-auth")
            if self.secret_fingerprints(name) != expected:
                raise DriftError(f"secret/{name} data fingerprint does not match")
            return expected
        manifest = {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "kubernetes.io/basic-auth",
            "metadata": {
                "name": name,
                "namespace": self.config.target.namespace,
                "labels": {
                    OWNER_LABEL: self.config.target.release,
                    "app.kubernetes.io/component": component,
                    "cnpg.io/reload": "true",
                },
                "annotations": {CONFIG_ANNOTATION: self.config.digest},
            },
            "data": {
                key: base64.b64encode(value).decode("ascii")
                for key, value in values.items()
            },
        }
        self.run(
            "create",
            "-f",
            "-",
            namespace=False,
            input_text=json.dumps(manifest),
            sensitive_output=True,
        )
        return expected

    def remove_owned_secret_key(self, name: str, key: str) -> dict[str, str]:
        payload = self.json("get", "secret", name, namespace=True)
        metadata = payload.get("metadata") or {}
        if (
            (metadata.get("labels") or {}).get(OWNER_LABEL)
            != self.config.target.release
            or (metadata.get("annotations") or {}).get(CONFIG_ANNOTATION)
            != self.config.digest
        ):
            raise DriftError(
                f"secret/{name} is not owned by this installer configuration"
            )
        if key not in (payload.get("data") or {}):
            return self.secret_fingerprints(name)
        escaped_key = key.replace("~", "~0").replace("/", "~1")
        patch = json.dumps(
            [{"op": "remove", "path": f"/data/{escaped_key}"}]
        )
        self.run(
            "patch",
            "secret",
            name,
            "--type=json",
            "-p",
            patch,
            namespace=True,
        )
        return self.secret_fingerprints(name)

    def get_secret_value(self, name: str, key: str) -> str:
        payload = self.json("get", "secret", name, namespace=True)
        encoded = str((payload.get("data") or {}).get(key) or "")
        if not encoded:
            raise PreconditionError(f"secret/{name} is missing required key {key}")
        try:
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise PreconditionError(f"secret/{name} key {key} is invalid") from exc

    def apply_object(self, manifest: dict[str, Any], *, sensitive: bool = False) -> None:
        self.run(
            "apply",
            "-f",
            "-",
            input_text=json.dumps(manifest),
            sensitive_output=sensitive,
        )

    def delete(self, kind: str, name: str) -> None:
        self.run("delete", kind, name, "--ignore-not-found", namespace=True)

    def delete_precondition(
        self,
        kind: str,
        name: str,
        *,
        uid: str,
        resource_version: str,
    ) -> None:
        resource = {
            "ConfigMap": "configmaps",
            "Lease": "leases",
        }.get(kind)
        if resource is None or not uid or not resource_version:
            raise DriftError("delete precondition identity is invalid")
        payload = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "preconditions": {
                "uid": uid,
                "resourceVersion": resource_version,
            },
        }
        api = "api/v1" if kind == "ConfigMap" else "apis/coordination.k8s.io/v1"
        path = (
            f"/{api}/namespaces/{self.config.target.namespace}/"
            f"{resource}/{name}"
        )
        self.run(
            "delete",
            "--raw",
            path,
            "-f",
            "-",
            input_text=json.dumps(payload),
            namespace=False,
        )

    def delete_api_precondition(
        self,
        *,
        api_version: str,
        resource: str,
        name: str,
        namespace: str | None,
        uid: str,
        resource_version: str,
    ) -> None:
        if (
            not api_version
            or not resource
            or "/" in resource
            or not name
            or not uid
            or not resource_version
        ):
            raise DriftError("factory delete precondition identity is invalid")
        if api_version == "v1":
            api = "api/v1"
        elif "/" in api_version:
            group, version = api_version.split("/", 1)
            api = f"apis/{group}/{version}"
        else:
            raise DriftError("factory delete API version is invalid")
        payload = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "propagationPolicy": "Foreground",
            "preconditions": {
                "uid": uid,
                "resourceVersion": resource_version,
            },
        }
        path = (
            f"/{api}/namespaces/{namespace}/{resource}/{name}"
            if namespace
            else f"/{api}/{resource}/{name}"
        )
        self.run(
            "delete",
            "--raw",
            path,
            "-f",
            "-",
            input_text=json.dumps(payload),
            namespace=False,
            timeout=600,
        )

    def release_namespace_metadata(
        self, *, uid: str, resource_version: str
    ) -> None:
        payload = self.json(
            "get", "namespace", self.config.target.namespace
        )
        metadata = payload.get("metadata") or {}
        if (
            str(metadata.get("uid") or "") != uid
            or str(metadata.get("resourceVersion") or "")
            != resource_version
            or (metadata.get("labels") or {}).get(OWNER_LABEL)
            != self.config.target.release
            or (metadata.get("annotations") or {}).get(
                CONFIG_ANNOTATION
            )
            != self.config.digest
        ):
            raise DriftError(
                "Namespace ownership changed before reset apply"
            )
        escaped_owner = OWNER_LABEL.replace("~", "~0").replace("/", "~1")
        escaped_config = CONFIG_ANNOTATION.replace("~", "~0").replace("/", "~1")
        patch = json.dumps(
            [
                {
                    "op": "test",
                    "path": "/metadata/resourceVersion",
                    "value": resource_version,
                },
                {
                    "op": "remove",
                    "path": f"/metadata/labels/{escaped_owner}",
                },
                {
                    "op": "remove",
                    "path": f"/metadata/annotations/{escaped_config}",
                },
            ]
        )
        self.run(
            "patch",
            "namespace",
            self.config.target.namespace,
            "--type=json",
            "-p",
            patch,
            namespace=False,
        )

    @staticmethod
    def job_terminal_state(
        job: dict[str, Any],
        pods: list[dict[str, Any]],
    ) -> dict[str, Any]:
        status = job.get("status") or {}
        spec = job.get("spec") or {}
        conditions = status.get("conditions") or []
        if any(
            row.get("type") == "Complete"
            and row.get("status") == "True"
            for row in conditions
        ) or int(status.get("succeeded") or 0) > 0:
            return {
                "terminal": True,
                "status": "complete",
                "reason": "complete",
                "exit_codes": [],
            }
        failed_condition = next(
            (
                row
                for row in conditions
                if row.get("type") == "Failed"
                and row.get("status") == "True"
            ),
            None,
        )
        exit_codes: list[int] = []
        waiting_reasons: set[str] = set()
        terminal_pods = 0
        for pod in pods:
            pod_terminal = False
            for container in (
                (pod.get("status") or {}).get("initContainerStatuses")
                or []
            ) + (
                (pod.get("status") or {}).get("containerStatuses")
                or []
            ):
                state = container.get("state") or {}
                terminated = state.get("terminated")
                waiting = state.get("waiting")
                if isinstance(terminated, dict):
                    pod_terminal = True
                    exit_codes.append(
                        int(terminated.get("exitCode") or 0)
                    )
                elif isinstance(waiting, dict):
                    reason = str(waiting.get("reason") or "")
                    if reason:
                        waiting_reasons.add(reason)
            if pod_terminal:
                terminal_pods += 1
        if failed_condition is not None:
            reason = str(failed_condition.get("reason") or "")
            return {
                "terminal": True,
                "status": "failed",
                "reason": (
                    "deadline-exceeded"
                    if reason == "DeadlineExceeded"
                    else "backoff-limit-exceeded"
                    if reason == "BackoffLimitExceeded"
                    else "job-failed"
                ),
                "exit_codes": sorted(set(exit_codes)),
            }
        permanent_waiting = {
            "CreateContainerConfigError",
            "ErrImagePull",
            "ImagePullBackOff",
            "InvalidImageName",
            "RunContainerError",
        }
        if waiting_reasons & permanent_waiting:
            return {
                "terminal": True,
                "status": "failed",
                "reason": "pod-configuration-failed",
                "exit_codes": sorted(set(exit_codes)),
            }
        failed = int(status.get("failed") or 0)
        backoff = int(spec.get("backoffLimit") or 0)
        active = int(status.get("active") or 0)
        if (
            failed > backoff
            or (
                failed > 0
                and active == 0
                and terminal_pods > 0
                and all(code != 0 for code in exit_codes)
            )
        ):
            return {
                "terminal": True,
                "status": "failed",
                "reason": "container-exit-failed",
                "exit_codes": sorted(set(exit_codes)),
            }
        return {
            "terminal": False,
            "status": "running",
            "reason": "pending",
            "exit_codes": sorted(set(exit_codes)),
        }

    def job_state(self, name: str) -> dict[str, Any]:
        if not self.exists("job", name):
            return {
                "terminal": False,
                "status": "missing",
                "reason": "job-missing",
                "exit_codes": [],
            }
        job = self.json("get", "job", name, namespace=True)
        pods = self.json(
            "get",
            "pods",
            "--selector",
            f"job-name={name}",
            namespace=True,
        ).get("items") or []
        return self.job_terminal_state(
            job,
            [row for row in pods if isinstance(row, dict)],
        )

    def wait_job_terminal(
        self,
        name: str,
        *,
        timeout: int = 900,
        interval: float = 2.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            result = self.job_state(name)
            if result["terminal"]:
                if result["status"] == "failed":
                    exit_codes = ",".join(
                        str(code) for code in result["exit_codes"]
                    ) or "unknown"
                    raise InstallerError(
                        f"Job/{name} failed: {result['reason']} "
                        f"(exit={exit_codes})"
                    )
                return result
            if time.monotonic() >= deadline:
                raise InstallerError(
                    f"Job/{name} did not reach a terminal state before timeout"
                )
            time.sleep(interval)

    def lease_payload(self, name: str) -> dict[str, Any] | None:
        if not self.exists("lease", name):
            return None
        return self.json("get", "lease", name, namespace=True)

    @staticmethod
    def lease_active(payload: dict[str, Any], *, holder: str, duration: int) -> bool:
        spec = payload.get("spec") or {}
        current = str(spec.get("holderIdentity") or "")
        if not current or current == holder:
            return False
        value = str(spec.get("renewTime") or spec.get("acquireTime") or "")
        try:
            renewed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return True
        return datetime.now(UTC) < renewed + timedelta(seconds=int(spec.get("leaseDurationSeconds") or duration))
