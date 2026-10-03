from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import stat
from typing import Any

from .config import EXTERNAL_RUNTIME_SECRET_KEYS, InstallConfig
from .barman_cloud import BarmanCloud
from .capacity import rendered_capacity_plan, validate_live_capacity
from .cloudnativepg import CloudNativePG
from .core import PreconditionError, Runner, sha256_file
from .kube import OWNER_LABEL, Kubernetes
from .package import PackageManager


REQUIRED_TOOLS = ("kubectl", "helm", "openssl")
def _external_runtime_secret_keys(config: InstallConfig) -> tuple[str, ...]:
    """Return keys required before install, allowing post-finalization cleanup.

    A fresh external profile needs the temporary break-glass value for the
    onboarding/finalization Jobs.  Once the local package manifest proves that
    finalization retired that value, the operator may remove the key from the
    external Secret and subsequent read-only plan/verify runs must not require
    it again.
    """
    keys = list(EXTERNAL_RUNTIME_SECRET_KEYS)
    if config.deployment_profile != "external-services":
        return tuple(keys)
    manifest_path = config.application.package_dir / "current" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return tuple(keys)
    row = (manifest.get("secrets") or {}).get("break_glass_initial_password")
    if (
        manifest.get("deployment_state") in {"operational", "acceptance_complete"}
        and isinstance(row, dict)
        and row.get("retired") is True
    ):
        keys.remove("BREAK_GLASS_INITIAL_PASSWORD")
    return tuple(keys)


def _regular(path: Path, *, context: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise PreconditionError(f"{context} must be a regular file: {path}")


def _private_parent(path: Path, *, context: str) -> None:
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise PreconditionError(f"{context} parent directory must already exist")
    if stat.S_IMODE(parent.stat().st_mode) != 0o700:
        raise PreconditionError(f"{context} parent directory must be mode 0700")


def _local_artifacts(config: InstallConfig) -> None:
    _regular(config.application.chart / "Chart.yaml", context="Helm chart")
    _regular(config.application.chart / "Chart.lock", context="Helm dependency lock")
    for values in config.application.values:
        _regular(values, context="Helm values")
    if config.application.trusted_tls_dir is not None:
        tls_directory = config.application.trusted_tls_dir
        if (
            not tls_directory.is_dir()
            or tls_directory.is_symlink()
            or stat.S_IMODE(tls_directory.stat().st_mode) != 0o700
        ):
            raise PreconditionError(
                "trusted TLS directory must be a mode-0700 directory"
            )
        tls_names = (
            ("edge.crt", "edge.key", "edge-ca.crt")
            if config.deployment_profile == "external-services"
            else (
                "edge.crt",
                "edge.key",
                "edge-ca.crt",
                "postgresql.crt",
                "postgresql.key",
                "postgresql-replication.crt",
                "postgresql-replication.key",
                "postgresql-ca.crt",
                "redis.crt",
                "redis.key",
                "redis-ca.crt",
                "rustfs.crt",
                "rustfs.key",
                "rustfs-ca.crt",
                "opensearch.crt",
                "opensearch.key",
                "opensearch-transport.crt",
                "opensearch-transport.key",
                "opensearch-ca.crt",
            )
        )
        for name in tls_names:
            path = tls_directory / name
            _regular(path, context=f"trusted TLS {name}")
            if name.endswith(".key") and stat.S_IMODE(
                path.stat().st_mode
            ) != 0o600:
                raise PreconditionError(
                    f"trusted TLS private key permissions are too broad: {name}"
                )
    for directory, label in (
        (config.application.package_dir.parent, "package parent"),
        (config.application.state_dir.parent, "state parent"),
    ):
        if not directory.is_dir() or directory.is_symlink():
            raise PreconditionError(f"{label} must already exist: {directory}")


def _tool_versions(runner: Runner) -> dict[str, str]:
    kubectl = runner.run(
        ["kubectl", "version", "--client=true", "--output=json"]
    ).stdout
    try:
        kubectl_payload = json.loads(kubectl)
        client = kubectl_payload["clientVersion"]
        kubectl_version = (
            f"{client['major']}.{str(client['minor']).rstrip('+')}"
        )
        kubectl_major = int(str(client["major"]))
        kubectl_minor = int(re.sub(r"[^0-9].*$", "", str(client["minor"])))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PreconditionError("kubectl client version is invalid") from exc
    if kubectl_major != 1 or kubectl_minor < 28:
        raise PreconditionError("kubectl 1.28 or newer is required")
    helm_version = runner.run(
        ["helm", "version", "--template", "{{.Version}}"]
    ).stdout.strip()
    if not re.fullmatch(r"v(?:3|4)\.[0-9]+\.[0-9]+(?:[-+].*)?", helm_version):
        raise PreconditionError("Helm v3 or v4 is required")
    openssl_version = runner.run(["openssl", "version"]).stdout.strip()
    if not openssl_version:
        raise PreconditionError("OpenSSL version is unavailable")
    return {
        "kubectl": kubectl_version,
        "helm": helm_version,
        "openssl": openssl_version.splitlines()[0],
    }


def _tls_evidence(config: InstallConfig, runner: Runner) -> dict[str, str]:
    directory = config.application.trusted_tls_dir
    if directory is None:
        raise PreconditionError("production installer requires trusted_tls_dir")
    expected_hosts = {
        "edge": (config.application.public_host,),
    }
    if config.deployment_profile != "external-services":
        expected_hosts.update(
            {
                "postgresql": (
                    f"{config.helm_fullname}-postgresql-rw",
                    (
                        f"{config.helm_fullname}-postgresql-rw."
                        f"{config.target.namespace}.svc.cluster.local"
                    ),
                    f"{config.helm_fullname}-postgresql-1",
                    f"{config.helm_fullname}-postgresql-2",
                    f"{config.helm_fullname}-postgresql-3",
                ),
                "redis": (
                    f"{config.helm_fullname}-redis-sentinel",
                    (
                        f"{config.helm_fullname}-redis-sentinel."
                        f"{config.target.namespace}.svc.cluster.local"
                    ),
                    (
                        f"{config.helm_fullname}-redis-0."
                        f"{config.helm_fullname}-redis-headless."
                        f"{config.target.namespace}.svc.cluster.local"
                    ),
                ),
                "rustfs": (f"{config.helm_fullname}-rustfs",),
                "opensearch": (
                    f"{config.helm_fullname}-opensearch",
                    (
                        f"{config.helm_fullname}-opensearch."
                        f"{config.target.namespace}.svc.cluster.local"
                    ),
                ),
            }
        )
    evidence: dict[str, str] = {}
    if config.local_installation and config.deployment_profile == "bundled":
        expected_hosts["postgresql"] = (f"{config.helm_fullname}-postgresql",)
    for component, hostnames in expected_hosts.items():
        certificate = directory / f"{component}.crt"
        private_key = directory / f"{component}.key"
        ca = directory / f"{component}-ca.crt"
        runner.run(["openssl", "verify", "-CAfile", str(ca), str(certificate)])
        for hostname in hostnames:
            runner.run(
                [
                    "openssl",
                    "x509",
                    "-in",
                    str(certificate),
                    "-noout",
                    "-checkhost",
                    hostname,
                ]
            )
        certificate_public = runner.run(
            ["openssl", "x509", "-in", str(certificate), "-pubkey", "-noout"]
        ).stdout
        key_public = runner.run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout"]
        ).stdout
        if certificate_public != key_public:
            raise PreconditionError(
                f"trusted TLS private key does not match {component} certificate"
            )
        evidence[component] = sha256_file(certificate)
    if config.deployment_profile == "external-services":
        return evidence
    transport_certificate = directory / "opensearch-transport.crt"
    transport_key = directory / "opensearch-transport.key"
    opensearch_ca = directory / "opensearch-ca.crt"
    runner.run(
        ["openssl", "verify", "-CAfile", str(opensearch_ca), str(transport_certificate)]
    )
    transport_host = (
        f"{config.helm_fullname}-opensearch-0."
        f"{config.helm_fullname}-opensearch-headless."
        f"{config.target.namespace}.svc.cluster.local"
    )
    runner.run(
        [
            "openssl", "x509", "-in", str(transport_certificate),
            "-noout", "-checkhost", transport_host,
        ]
    )
    transport_public = runner.run(
        ["openssl", "x509", "-in", str(transport_certificate), "-pubkey", "-noout"]
    ).stdout
    transport_key_public = runner.run(
        ["openssl", "pkey", "-in", str(transport_key), "-pubout"]
    ).stdout
    if transport_public != transport_key_public:
        raise PreconditionError(
            "trusted TLS private key does not match OpenSearch transport certificate"
        )
    transport_eku = runner.run(
        [
            "openssl", "x509", "-in", str(transport_certificate),
            "-noout", "-ext", "extendedKeyUsage",
        ]
    ).stdout
    if (
        "TLS Web Server Authentication" not in transport_eku
        or "TLS Web Client Authentication" not in transport_eku
    ):
        raise PreconditionError(
            "OpenSearch transport certificate requires serverAuth and clientAuth"
        )
    evidence["opensearch_transport"] = sha256_file(transport_certificate)
    replication_certificate = directory / "postgresql-replication.crt"
    replication_key = directory / "postgresql-replication.key"
    postgresql_ca = directory / "postgresql-ca.crt"
    runner.run(
        [
            "openssl",
            "verify",
            "-CAfile",
            str(postgresql_ca),
            str(replication_certificate),
        ]
    )
    replication_public = runner.run(
        [
            "openssl",
            "x509",
            "-in",
            str(replication_certificate),
            "-pubkey",
            "-noout",
        ]
    ).stdout
    replication_key_public = runner.run(
        ["openssl", "pkey", "-in", str(replication_key), "-pubout"]
    ).stdout
    if replication_public != replication_key_public:
        raise PreconditionError(
            "trusted PostgreSQL replication private key does not match"
        )
    replication_eku = runner.run(
        [
            "openssl",
            "x509",
            "-in",
            str(replication_certificate),
            "-noout",
            "-ext",
            "extendedKeyUsage",
        ]
    ).stdout
    if "TLS Web Client Authentication" not in replication_eku:
        raise PreconditionError(
            "PostgreSQL replication certificate requires clientAuth"
        )
    evidence["postgresql_replication"] = sha256_file(
        replication_certificate
    )
    return evidence


def _rendered_helm_output(config: InstallConfig, runner: Runner) -> str:
    command = [
        "helm",
        "template",
        config.target.release,
        str(config.application.chart),
        "--namespace",
        config.target.namespace,
    ]
    for path in config.application.values:
        command.extend(["--values", str(path)])
    command.extend(["--values", "-"])
    result = runner.run(
        command,
        input_text=json.dumps(config.generated_helm_values("application")),
        timeout=180,
    )
    return result.stdout


def _rendered_image_inventory(
    config: InstallConfig, rendered_output: str
) -> list[str]:
    rendered = sorted(
        {
            match.group(1)
            for match in re.finditer(
                r'^\s*(?:image|imageName):\s*"?([^"\s]+)"?\s*$',
                rendered_output,
                flags=re.MULTILINE,
            )
        }
    )
    expected = set(config.images.inventory().values())
    if config.deployment_profile == "external-services":
        required = {
            getattr(config.images, name)
            for name in ("frontend", "backend", "migration")
        }
    else:
        required = expected
    if not rendered or not required.issubset(rendered):
        raise PreconditionError(
            "rendered Helm image inventory is incomplete or differs"
        )
    unexpected = [image for image in rendered if image not in expected]
    if unexpected or any("@sha256:" not in image for image in rendered):
        raise PreconditionError(
            "rendered Helm image inventory contains an unapproved identity"
        )
    return rendered


def _existing_secret_reference(
    kube: Kubernetes, name: str, key: str
) -> dict[str, str]:
    if not kube.exists("secret", name):
        raise PreconditionError(f"required secret/{name} does not exist")
    payload = kube.json("get", "secret", name, namespace=True)
    if not (payload.get("data") or {}).get(key):
        raise PreconditionError(f"secret/{name} is missing required key {key}")
    value = kube.get_secret_value(name, key).strip()
    normalized = value.upper()
    if (
        not value
        or "CHANGE_ME" in normalized
        or "PLACEHOLDER" in normalized
        or (len(value) >= 16 and set(value) <= {"0"})
    ):
        raise PreconditionError(
            f"secret/{name} key {key} contains prohibited placeholder data"
        )
    return kube.secret_fingerprints(name)


def _release_collision(config: InstallConfig, runner: Runner, kube: Kubernetes) -> str:
    result = runner.run(
        [
            "helm",
            "status",
            config.target.release,
            "--kube-context",
            config.target.context,
            "--namespace",
            config.target.namespace,
            "--output",
            "json",
        ],
        accepted=frozenset({0, 1}),
    )
    if result.returncode != 0:
        return "absent"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PreconditionError("existing Helm release status is invalid") from exc
    labels = {}
    if kube.exists("configmap", f"{config.target.release}-installer-state"):
        state = kube.json("get", "configmap", f"{config.target.release}-installer-state", namespace=True)
        labels = (state.get("metadata") or {}).get("labels") or {}
    if labels.get(OWNER_LABEL) != config.target.release:
        raise PreconditionError("target Helm release already exists without matching installer ownership")
    return str((payload.get("info") or {}).get("status") or "existing")


def build_plan(config: InstallConfig, runner: Runner, kube: Kubernetes) -> dict[str, Any]:
    for tool in REQUIRED_TOOLS:
        if shutil.which(tool) is None:
            raise PreconditionError(f"required command is unavailable: {tool}")
    _local_artifacts(config)
    repository = Path(__file__).resolve().parents[3]
    package_state = PackageManager(
        config, runner, kube, repository
    ).validate_local_for_plan()
    versions = _tool_versions(runner)
    tls = _tls_evidence(config, runner)
    rendered_output = _rendered_helm_output(config, runner)
    rendered_images = _rendered_image_inventory(config, rendered_output)
    capacity_plan = rendered_capacity_plan(rendered_output)
    identity = kube.validate_identity()
    kube.validate_rbac()
    if config.deployment_profile == "external-services" or config.local_installation:
        cloudnativepg = {
            "action": "not-required",
            "profile": "external-services",
        }
        barman_cloud = {
            "action": "not-required",
            "profile": "external-services",
        }
    else:
        cloudnativepg = CloudNativePG(config, kube).prepare()
        barman_cloud = BarmanCloud(config, kube).prepare()
    nodes = kube.validate_nodes(1 if config.local_installation else 3)
    kube.validate_platform_classes()
    capacity = validate_live_capacity(kube, capacity_plan, nodes)
    ingress_controller_pods = kube.validate_ingress_controller()
    kube.validate_public_host_collision()
    addresses = kube.validate_dns()
    reachable_address = kube.validate_public_https_path(addresses)
    namespace = kube.namespace_state()
    referenced_secrets: dict[str, dict[str, str]] = {}
    if config.identity.mode != "preconfigured":
        referenced_secrets[
            config.identity.bind_secret_name
        ] = _existing_secret_reference(
            kube,
            config.identity.bind_secret_name,
            config.identity.bind_secret_key,
        )
        referenced_secrets[
            config.identity.ca_secret_name
        ] = _existing_secret_reference(
            kube,
            config.identity.ca_secret_name,
            config.identity.ca_secret_key,
        )
    if config.application.registry_pull_secret:
        referenced_secrets[
            config.application.registry_pull_secret
        ] = _existing_secret_reference(
            kube,
            config.application.registry_pull_secret,
            ".dockerconfigjson",
        )
    if (
        config.deployment_profile == "external-services"
        and config.application.runtime_secret_mode == "existing"
    ):
        for key in _external_runtime_secret_keys(config):
            fingerprints = _existing_secret_reference(
                kube,
                config.application.runtime_secret,
                key,
            )
            referenced_secrets[
                f"{config.application.runtime_secret}:{key}"
            ] = {key: fingerprints[key]}
    if config.deployment_profile == "external-services":
        for name in config.external_ca_secret_names:
            referenced_secrets[name] = _existing_secret_reference(
                kube, name, "ca.crt"
            )
    release = _release_collision(config, runner, kube)
    fullname = (
        config.target.release
        if "nomosmart" in config.target.release
        else f"{config.target.release}-nomosmart"
    )[:63].rstrip("-")
    external_profile = config.deployment_profile == "external-services"
    planned_resources = [
        f"namespace/{config.target.namespace} (create or claim if empty)",
        f"configmap/{config.target.release}-installer-state",
        f"lease/{config.target.release}-installer",
        (
            f"secret/{config.application.runtime_secret} (existing reference)"
            if external_profile
            else f"secret/{config.application.runtime_secret}"
        ),
        f"secret/{config.application.ingress_tls_secret}",
    ]
    if not external_profile:
        planned_resources.extend(
            [
                f"secret/{config.application.rustfs_tls_secret}",
                f"secret/{config.application.opensearch_tls_secret}",
                f"secret/{fullname}-postgresql-tls",
                f"secret/{fullname}-postgresql-replication-tls",
                f"secret/{fullname}-redis-tls",
                "cloudnativepg-operator/cnpg-system (install exact 1.30.0 or reuse exact match)",
                "barman-cloud-plugin/cnpg-system (install exact 0.13.0 or reuse exact match; cert-manager self-signed TLS)",
            ]
        )
    else:
        planned_resources.extend(
            f"secret/{name} (existing external CA reference)"
            for name in config.external_ca_secret_names
        )
    planned_resources.extend(
        [
            (
                f"secret/{config.application.registry_pull_secret} "
                "(existing image-pull reference)"
                if config.application.registry_pull_secret
                else "image-pull secret (not configured)"
            ),
            f"helm-release/{config.target.release}",
            f"keycloak-provider/{config.identity.provider_name}",
            f"keycloak-mapper/{config.identity.mapper_name}",
            (
                "nomosmart-role-mapping/"
                f"{config.identity.external_group_name}:"
                f"{config.identity.local_role_name}"
            ),
        ]
    )
    return {
        "status": "ready",
        "read_only": True,
        "api_version": config.api_version,
        "tool_versions": versions,
        "config_digest": config.digest,
        "target": identity,
        "namespace": namespace,
        "helm_release": release,
        "local_package": package_state,
        "ready_schedulable_nodes": nodes,
        "capacity": capacity,
        "storage_class": config.application.storage_class,
        "ingress_class": config.application.ingress_class,
        "ingress_controller": {
            "namespace": (
                config.application.ingress_controller_namespace
            ),
            "name_label": config.application.ingress_controller_name,
            "ready_pods": ingress_controller_pods,
        },
        "public_host": config.application.public_host,
        "public_addresses": addresses,
        "public_https_reachable_address": reachable_address,
        "chart": {
            "path": str(config.application.chart),
            "version": config.chart_version,
            "chart_yaml_sha256": sha256_file(config.application.chart / "Chart.yaml"),
            "chart_tree_sha256": config.chart_digest,
        },
        "trusted_tls_certificate_fingerprints": tls,
        "images": config.images.inventory(),
        "rendered_images": rendered_images,
        "cloudnativepg": cloudnativepg,
        "barman_cloud": barman_cloud,
        "referenced_secret_fingerprints": referenced_secrets,
        "identity": {
            "mode": config.identity.mode,
            "provider_name": config.identity.provider_name,
            "admin_username": config.identity.admin_username,
            "group_path": config.identity.group_path,
            "authentication": "password_only",
        },
        "planned_resources": planned_resources,
        "human_checkpoints": [
            (
                "Federated administrator and break-glass first login, "
                "password change and OIDC"
            ),
        ],
        "stages": [
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
        ],
    }
