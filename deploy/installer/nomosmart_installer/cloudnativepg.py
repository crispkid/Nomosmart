from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import InstallConfig
from .core import PreconditionError, atomic_private_write, sha256_file
from .kube import Kubernetes


OPERATOR_VERSION: Final[str] = "1.30.0"
OPERATOR_NAMESPACE: Final[str] = "cnpg-system"
OPERATOR_DEPLOYMENT: Final[str] = "cnpg-controller-manager"
UPSTREAM_IMAGE: Final[str] = (
    "ghcr.io/cloudnative-pg/cloudnative-pg:1.30.0"
)
OPERATOR_IMAGE: Final[str] = (
    "ghcr.io/cloudnative-pg/cloudnative-pg@"
    "sha256:a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb"
)
MANIFEST_URL: Final[str] = (
    "https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/"
    "v1.30.0/releases/cnpg-1.30.0.yaml"
)
MANIFEST_SHA256: Final[str] = (
    "f8bede43fe4ee0d478c2355b204a36876b2ae4faac60f2a9452280b293da3b88"
)
RENDERED_MANIFEST_SHA256: Final[str] = (
    "5ca16440ae140e323466d66e5c156cd937b13bada6bc9ccd687853bc35315f64"
)
REQUIRED_CRDS: Final[tuple[str, ...]] = (
    "clusters.postgresql.cnpg.io",
    "databases.postgresql.cnpg.io",
    "databaseroles.postgresql.cnpg.io",
)


class CloudNativePG:
    def __init__(self, config: InstallConfig, kube: Kubernetes) -> None:
        self.config = config
        self.kube = kube
        self.manifest = (
            config.application.state_dir
            / "artifacts"
            / f"cnpg-{OPERATOR_VERSION}.yaml"
        )

    def _deployment(self) -> dict[str, Any] | None:
        result = self.kube.run(
            "get",
            "deployment",
            OPERATOR_DEPLOYMENT,
            "--namespace",
            OPERATOR_NAMESPACE,
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
                "CloudNativePG operator Deployment is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise PreconditionError(
                "CloudNativePG operator Deployment is invalid"
            )
        return payload

    @staticmethod
    def _image(payload: dict[str, Any]) -> str:
        containers = (
            (((payload.get("spec") or {}).get("template") or {}).get("spec") or {})
            .get("containers")
            or []
        )
        controller = next(
            (
                row
                for row in containers
                if str(row.get("name") or "") == "manager"
            ),
            None,
        )
        return str((controller or {}).get("image") or "")

    def plan(self) -> dict[str, Any]:
        present_crds = sorted(
            name
            for name in REQUIRED_CRDS
            if self.kube.exists("crd", name, namespace=False)
        )
        deployment = self._deployment()
        if deployment is not None:
            image = self._image(deployment)
            if image != OPERATOR_IMAGE:
                raise PreconditionError(
                    "existing CloudNativePG operator image differs from the pinned identity"
                )
            complete = present_crds == sorted(REQUIRED_CRDS)
            cached = (
                self.manifest.is_file()
                and not self.manifest.is_symlink()
                and sha256_file(self.manifest) == RENDERED_MANIFEST_SHA256
            )
            if not complete and not cached:
                raise PreconditionError(
                    "CloudNativePG operator exists with incomplete required CRDs"
                )
            return {
                "action": "reuse" if complete else "repair",
                "version": OPERATOR_VERSION,
                "namespace": OPERATOR_NAMESPACE,
                "deployment": OPERATOR_DEPLOYMENT,
                "image": image,
                "required_crds": list(REQUIRED_CRDS),
                "manifest_sha256": MANIFEST_SHA256,
                "rendered_manifest_sha256": RENDERED_MANIFEST_SHA256,
            }
        cached = (
            self.manifest.is_file()
            and not self.manifest.is_symlink()
            and sha256_file(self.manifest) == RENDERED_MANIFEST_SHA256
        )
        if present_crds and not cached:
            raise PreconditionError(
                "CloudNativePG CRDs exist without the pinned operator deployment"
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
                "CloudNativePG operator installation RBAC is incomplete: "
                + ", ".join(denied)
            )
        return {
            "action": "repair" if present_crds else "install",
            "version": OPERATOR_VERSION,
            "namespace": OPERATOR_NAMESPACE,
            "deployment": OPERATOR_DEPLOYMENT,
            "image": OPERATOR_IMAGE,
            "required_crds": list(REQUIRED_CRDS),
            "manifest_url": MANIFEST_URL,
            "manifest_sha256": MANIFEST_SHA256,
            "rendered_manifest_sha256": RENDERED_MANIFEST_SHA256,
        }

    def _download(self) -> Path:
        if self.manifest.is_file() and not self.manifest.is_symlink():
            if sha256_file(self.manifest) == RENDERED_MANIFEST_SHA256:
                return self.manifest
            raise PreconditionError(
                "cached CloudNativePG manifest fingerprint differs"
            )
        request = Request(
            MANIFEST_URL,
            headers={"User-Agent": "NomoSmart-Installer/0.2"},
        )
        try:
            with urlopen(request, timeout=60) as response:
                payload = response.read(2 * 1024 * 1024 + 1)
        except (HTTPError, URLError, OSError) as exc:
            raise PreconditionError(
                "pinned CloudNativePG manifest download failed"
            ) from exc
        if len(payload) > 2 * 1024 * 1024:
            raise PreconditionError("CloudNativePG manifest exceeds size limit")
        if hashlib.sha256(payload).hexdigest() != MANIFEST_SHA256:
            raise PreconditionError(
                "downloaded CloudNativePG manifest fingerprint differs"
            )
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PreconditionError(
                "CloudNativePG manifest is not UTF-8"
            ) from exc
        if text.count(UPSTREAM_IMAGE) != 2:
            raise PreconditionError(
                "CloudNativePG manifest operator image contract differs"
            )
        text = text.replace(UPSTREAM_IMAGE, OPERATOR_IMAGE)
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != RENDERED_MANIFEST_SHA256:
            raise PreconditionError(
                "rendered CloudNativePG manifest fingerprint differs"
            )
        atomic_private_write(self.manifest, text)
        return self.manifest

    def ensure(self) -> dict[str, Any]:
        planned = self.plan()
        if planned["action"] in {"install", "repair"}:
            manifest = self._download()
            self.kube.run(
                "apply",
                "--server-side=true",
                "--field-manager=nomosmart-installer",
                "-f",
                str(manifest),
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
                    and self._image(deployment) == OPERATOR_IMAGE
                    and all(
                        self.kube.exists("crd", name, namespace=False)
                        for name in REQUIRED_CRDS
                    )
                ):
                    return {
                        **planned,
                        "status": "ready",
                        "available_replicas": available,
                        "cached_manifest_sha256": (
                            sha256_file(self.manifest)
                            if self.manifest.is_file()
                            else ""
                        ),
                    }
            time.sleep(5)
        raise PreconditionError(
            "CloudNativePG operator did not become Ready within 600 seconds"
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
