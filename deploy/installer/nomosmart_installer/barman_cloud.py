from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import InstallConfig
from .core import PreconditionError, atomic_private_write, sha256_file
from .kube import Kubernetes


PLUGIN_VERSION: Final[str] = "0.13.0"
PLUGIN_NAMESPACE: Final[str] = "cnpg-system"
PLUGIN_DEPLOYMENT: Final[str] = "barman-cloud"
UPSTREAM_OPERATOR_IMAGE: Final[str] = (
    "ghcr.io/cloudnative-pg/plugin-barman-cloud:v0.13.0"
)
UPSTREAM_SIDECAR_IMAGE: Final[str] = (
    "ghcr.io/cloudnative-pg/plugin-barman-cloud-sidecar:v0.13.0"
)
PLUGIN_IMAGE: Final[str] = (
    "ghcr.io/cloudnative-pg/plugin-barman-cloud@"
    "sha256:71589dbac582333442812b07b31f7ea4d00324a8358aac7ca507dabf9f4b6c96"
)
SIDECAR_IMAGE: Final[str] = (
    "ghcr.io/cloudnative-pg/plugin-barman-cloud-sidecar@"
    "sha256:990361af3319f9e23aafa0f6d7981f99bf1f69b4e6a85cf1bc7d71d6f09bb288"
)
MANIFEST_URL: Final[str] = (
    "https://github.com/cloudnative-pg/plugin-barman-cloud/releases/"
    "download/v0.13.0/manifest.yaml"
)
MANIFEST_SHA256: Final[str] = (
    "d2e71e7b06822448f1a421f05781846cfdb9cc621e7ef32eef5e20c5133213b0"
)
RENDERED_MANIFEST_SHA256: Final[str] = (
    "dbb6d82026d6bc7a511f2f25b4e347194d7316b6c8a453b9302bf9d1042aa2ed"
)
REQUIRED_CRD: Final[str] = "objectstores.barmancloud.cnpg.io"
CERT_MANAGER_CRDS: Final[tuple[str, ...]] = (
    "certificates.cert-manager.io",
    "issuers.cert-manager.io",
)


class BarmanCloud:
    """Install the pinned CNPG-I backup plugin without floating image tags."""

    def __init__(self, config: InstallConfig, kube: Kubernetes) -> None:
        self.config = config
        self.kube = kube
        self.manifest = (
            config.application.state_dir
            / "artifacts"
            / f"plugin-barman-cloud-{PLUGIN_VERSION}.yaml"
        )

    def _deployment(self) -> dict[str, Any] | None:
        result = self.kube.run(
            "get",
            "deployment",
            PLUGIN_DEPLOYMENT,
            "--namespace",
            PLUGIN_NAMESPACE,
            "-o",
            "json",
            accepted=frozenset({0, 1}),
        )
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PreconditionError(
                "Barman Cloud plugin Deployment is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise PreconditionError(
                "Barman Cloud plugin Deployment is invalid"
            )
        return payload

    @staticmethod
    def _image(payload: dict[str, Any]) -> str:
        containers = (
            (((payload.get("spec") or {}).get("template") or {}).get("spec") or {})
            .get("containers")
            or []
        )
        plugin = next(
            (
                row
                for row in containers
                if str(row.get("name") or "") == "barman-cloud"
            ),
            None,
        )
        return str((plugin or {}).get("image") or "")

    def _cert_manager_ready(self) -> None:
        missing = [
            name
            for name in CERT_MANAGER_CRDS
            if not self.kube.exists("crd", name, namespace=False)
        ]
        if missing:
            raise PreconditionError(
                "Barman Cloud requires an existing Ready cert-manager; missing CRDs: "
                + ", ".join(missing)
            )
        deployments = self.kube.json(
            "get",
            "deployments",
            "--all-namespaces",
            "--selector",
            "app.kubernetes.io/name=cert-manager",
        ).get("items") or []
        if not any(
            int((row.get("spec") or {}).get("replicas") or 0) > 0
            and int((row.get("status") or {}).get("availableReplicas") or 0)
            == int((row.get("spec") or {}).get("replicas") or 0)
            for row in deployments
        ):
            raise PreconditionError(
                "Barman Cloud requires an existing Ready cert-manager controller"
            )

    def _validate_certificate_collisions(self) -> None:
        contracts = (
            (
                "issuer",
                "selfsigned-issuer",
                lambda row: (row.get("spec") or {}).get("selfSigned") == {},
            ),
            (
                "certificate",
                "barman-cloud-client",
                lambda row: (row.get("spec") or {}).get("secretName")
                == "barman-cloud-client-tls"
                and "client auth" in ((row.get("spec") or {}).get("usages") or []),
            ),
            (
                "certificate",
                "barman-cloud-server",
                lambda row: (row.get("spec") or {}).get("secretName")
                == "barman-cloud-server-tls"
                and "barman-cloud" in ((row.get("spec") or {}).get("dnsNames") or [])
                and "server auth" in ((row.get("spec") or {}).get("usages") or []),
            ),
        )
        for kind, name, compatible in contracts:
            if not self.kube.exists(kind, name, namespace=PLUGIN_NAMESPACE):
                continue
            payload = self.kube.json(
                "get", kind, name, namespace=PLUGIN_NAMESPACE
            )
            if not compatible(payload):
                raise PreconditionError(
                    f"existing {kind}/{name} collides with Barman Cloud plugin TLS"
                )

    def plan(self) -> dict[str, Any]:
        self._cert_manager_ready()
        self._validate_certificate_collisions()
        deployment = self._deployment()
        crd_present = self.kube.exists(
            "crd", REQUIRED_CRD, namespace=False
        )
        cached = (
            self.manifest.is_file()
            and not self.manifest.is_symlink()
            and sha256_file(self.manifest) == RENDERED_MANIFEST_SHA256
        )
        if deployment is not None:
            image = self._image(deployment)
            if image != PLUGIN_IMAGE:
                raise PreconditionError(
                    "existing Barman Cloud plugin image differs from the pinned identity"
                )
            if not crd_present and not cached:
                raise PreconditionError(
                    "Barman Cloud plugin exists with an incomplete ObjectStore CRD"
                )
            return {
                "action": "reuse" if crd_present else "repair",
                "version": PLUGIN_VERSION,
                "namespace": PLUGIN_NAMESPACE,
                "deployment": PLUGIN_DEPLOYMENT,
                "image": image,
                "sidecar_image": SIDECAR_IMAGE,
                "manifest_sha256": MANIFEST_SHA256,
                "rendered_manifest_sha256": RENDERED_MANIFEST_SHA256,
                "certificate_source": "cert-manager-self-signed-issuer",
            }
        if crd_present and not cached:
            raise PreconditionError(
                "Barman Cloud ObjectStore CRD exists without the pinned plugin"
            )
        checks = (
            ("create", "customresourcedefinitions.apiextensions.k8s.io"),
            ("patch", "customresourcedefinitions.apiextensions.k8s.io"),
            ("create", "clusterroles.rbac.authorization.k8s.io"),
            ("patch", "clusterroles.rbac.authorization.k8s.io"),
            ("create", "clusterrolebindings.rbac.authorization.k8s.io"),
            ("patch", "clusterrolebindings.rbac.authorization.k8s.io"),
        )
        denied: list[str] = []
        for verb, resource in checks:
            result = self.kube.run("auth", "can-i", verb, resource)
            if result.stdout.strip().lower() != "yes":
                denied.append(f"{verb}:{resource}")
        if denied:
            raise PreconditionError(
                "Barman Cloud plugin installation RBAC is incomplete: "
                + ", ".join(denied)
            )
        return {
            "action": "repair" if crd_present else "install",
            "version": PLUGIN_VERSION,
            "namespace": PLUGIN_NAMESPACE,
            "deployment": PLUGIN_DEPLOYMENT,
            "image": PLUGIN_IMAGE,
            "sidecar_image": SIDECAR_IMAGE,
            "manifest_url": MANIFEST_URL,
            "manifest_sha256": MANIFEST_SHA256,
            "rendered_manifest_sha256": RENDERED_MANIFEST_SHA256,
            "certificate_source": "cert-manager-self-signed-issuer",
        }

    @staticmethod
    def _pin_manifest(payload: bytes) -> str:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PreconditionError(
                "Barman Cloud manifest is not UTF-8"
            ) from exc
        if text.count(UPSTREAM_OPERATOR_IMAGE) != 1:
            raise PreconditionError(
                "Barman Cloud operator image contract differs"
            )
        match = re.search(
            r"SIDECAR_IMAGE: \|\n((?:    [A-Za-z0-9+/=]+\n)+)", text
        )
        if match is None:
            raise PreconditionError(
                "Barman Cloud sidecar image contract is unavailable"
            )
        encoded = "".join(match.group(1).split())
        try:
            upstream_sidecar = base64.b64decode(
                encoded, validate=True
            ).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise PreconditionError(
                "Barman Cloud sidecar image contract is invalid"
            ) from exc
        if upstream_sidecar != UPSTREAM_SIDECAR_IMAGE:
            raise PreconditionError(
                "Barman Cloud sidecar image identity differs"
            )
        pinned_sidecar = base64.b64encode(
            SIDECAR_IMAGE.encode("utf-8")
        ).decode("ascii")
        text = text.replace(UPSTREAM_OPERATOR_IMAGE, PLUGIN_IMAGE)
        text = text.replace(match.group(1), f"    {pinned_sidecar}\n")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != RENDERED_MANIFEST_SHA256:
            raise PreconditionError(
                "rendered Barman Cloud manifest fingerprint differs"
            )
        return text

    def _download(self) -> Path:
        if self.manifest.is_file() and not self.manifest.is_symlink():
            if sha256_file(self.manifest) == RENDERED_MANIFEST_SHA256:
                return self.manifest
            raise PreconditionError(
                "cached Barman Cloud manifest fingerprint differs"
            )
        request = Request(
            MANIFEST_URL,
            headers={"User-Agent": "NomoSmart-Installer/0.3"},
        )
        try:
            with urlopen(request, timeout=60) as response:
                payload = response.read(2 * 1024 * 1024 + 1)
        except (HTTPError, URLError, OSError) as exc:
            raise PreconditionError(
                "pinned Barman Cloud manifest download failed"
            ) from exc
        if len(payload) > 2 * 1024 * 1024:
            raise PreconditionError(
                "Barman Cloud manifest exceeds size limit"
            )
        if hashlib.sha256(payload).hexdigest() != MANIFEST_SHA256:
            raise PreconditionError(
                "downloaded Barman Cloud manifest fingerprint differs"
            )
        atomic_private_write(self.manifest, self._pin_manifest(payload))
        return self.manifest

    def ensure(self) -> dict[str, Any]:
        planned = self.plan()
        if planned["action"] in {"install", "repair"}:
            self.kube.run(
                "apply",
                "--server-side=true",
                "--field-manager=nomosmart-installer",
                "-f",
                str(self._download()),
                timeout=600,
            )
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            deployment = self._deployment()
            if deployment is not None:
                desired = int((deployment.get("spec") or {}).get("replicas") or 0)
                available = int(
                    (deployment.get("status") or {}).get("availableReplicas") or 0
                )
                if (
                    desired > 0
                    and available == desired
                    and self._image(deployment) == PLUGIN_IMAGE
                    and self.kube.exists("crd", REQUIRED_CRD, namespace=False)
                ):
                    return {
                        **planned,
                        "status": "ready",
                        "available_replicas": available,
                        "cached_manifest_sha256": sha256_file(self.manifest),
                    }
            time.sleep(5)
        raise PreconditionError(
            "Barman Cloud plugin did not become Ready within 600 seconds"
        )

    def prepare(self) -> dict[str, Any]:
        """Materialize and verify required local artifacts without cluster mutation."""
        planned = self.plan()
        if planned["action"] in {"install", "repair"}:
            manifest = self._download()
            return {
                **planned,
                "prepared_manifest": str(manifest),
                "cached_manifest_sha256": sha256_file(manifest),
            }
        return planned
