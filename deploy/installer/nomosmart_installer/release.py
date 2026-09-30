from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from .config import InstallConfig
from .core import PreconditionError


RELEASE_MODULE_ROOT = Path(__file__).resolve().parents[2] / "release"
if str(RELEASE_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_MODULE_ROOT))

try:
    from nomosmart_release.contract import (
        ReleaseContractError,
        verify_release_package,
    )
except ImportError as exc:  # pragma: no cover - package integrity guard
    raise RuntimeError(
        "Production release verification runtime is unavailable"
    ) from exc


class InstallerReleaseVerifier:
    def __init__(self, config: InstallConfig) -> None:
        self.config = config

    def verify(self) -> dict[str, Any]:
        release = self.config.release
        if release.purpose == "installation-validation" and (
            not release.required or not release.isolated_environment_acknowledged
        ):
            raise PreconditionError("installation-validation requires an explicitly acknowledged isolated target")
        if not release.required and release.package_dir is None:
            return {
                "status": "legacy-uat",
                "production_ready": False,
                "required": False,
            }
        if (
            release.package_dir is None
            or (release.purpose == "production" and not release.trusted_signer_fingerprint)
        ):
            raise PreconditionError(
                "Release package trust configuration is incomplete"
            )
        try:
            result = verify_release_package(
                release.package_dir,
                trusted_fingerprint=release.trusted_signer_fingerprint,
                expected_images=self.config.images.inventory(),
                expected_chart_sha256=self.config.chart_digest,
                purpose=release.purpose,
            )
        except ReleaseContractError as exc:
            raise PreconditionError(
                f"Release package verification failed: {exc}"
            ) from exc
        result["required"] = release.required
        return result
