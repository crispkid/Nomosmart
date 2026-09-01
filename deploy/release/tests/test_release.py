from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


RELEASE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = RELEASE_ROOT.parents[1]
INSTALLER_ROOT = REPOSITORY / "deploy/installer"
sys.path.insert(0, str(RELEASE_ROOT))
sys.path.insert(0, str(INSTALLER_ROOT))

from nomosmart_release.cli import (
    ReleaseBuildError,
    assemble_release,
    source_identity,
)
from nomosmart_release.contract import (
    ALL_RUNTIME_IMAGE_NAMES,
    FIXED_PLATFORM_IMAGES,
    REQUIRED_GATES,
    REQUIRED_IMAGES,
    ReleaseContractError,
    canonical_json,
    sha256_file,
    verify_release_package,
)
from nomosmart_installer.barman_cloud import (  # noqa: E402
    PLUGIN_IMAGE,
    SIDECAR_IMAGE,
)
from nomosmart_installer.cloudnativepg import OPERATOR_IMAGE  # noqa: E402


class ReleaseContractTests(unittest.TestCase):
    def test_migration_build_context_is_strictly_allowlisted(self) -> None:
        rules = [
            line.strip()
            for line in (REPOSITORY / ".dockerignore").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(
            rules,
            [
                "**",
                "!sql",
                "!sql/migrations",
                "!sql/migrations/**",
                "!deploy",
                "!deploy/migrations",
                "!deploy/migrations/Dockerfile",
                "!deploy/docker",
                "!deploy/docker/secret-env-entrypoint.sh",
            ],
        )

    def test_fixed_platform_images_match_installer_runtime(self) -> None:
        self.assertEqual(
            FIXED_PLATFORM_IMAGES,
            {
                "cloudnativepg_operator": OPERATOR_IMAGE,
                "barman_cloud_plugin": PLUGIN_IMAGE,
                "barman_cloud_sidecar": SIDECAR_IMAGE,
            },
        )

    def test_source_identity_requires_detached_clean_exact_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.name", "NomoSmart Test"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "release-test@invalid"],
                cwd=repo,
                check=True,
            )
            (repo / "README.md").write_text("release\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "test"],
                cwd=repo,
                check=True,
            )
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            with self.assertRaises(ReleaseBuildError):
                source_identity(repo, commit)
            subprocess.run(
                ["git", "checkout", "--detach", "-q", commit],
                cwd=repo,
                check=True,
            )
            self.assertEqual(source_identity(repo, commit)["git_sha"], commit)
            (repo / "untracked").write_text("change", encoding="utf-8")
            with self.assertRaises(ReleaseBuildError):
                source_identity(repo, commit)

    @unittest.skipUnless(shutil.which("gpg"), "gpg is unavailable")
    def test_signed_package_verifies_without_git_or_builder_and_rejects_tamper(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gpg_home = root / "gnupg"
            gpg_home.mkdir(mode=0o700)
            subprocess.run(
                [
                    "gpg",
                    "--batch",
                    "--homedir",
                    str(gpg_home),
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase",
                    "",
                    "--quick-generate-key",
                    "NomoSmart Disposable Release Test <release-test@example.invalid>",
                    "ed25519",
                    "sign",
                    "0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            listing = subprocess.run(
                [
                    "gpg",
                    "--batch",
                    "--homedir",
                    str(gpg_home),
                    "--with-colons",
                    "--list-secret-keys",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            fingerprint = next(
                row.split(":")[9]
                for row in listing.splitlines()
                if row.startswith("fpr:")
            )
            public_key = root / "release-public.asc"
            exported = subprocess.run(
                [
                    "gpg",
                    "--batch",
                    "--homedir",
                    str(gpg_home),
                    "--armor",
                    "--export",
                    fingerprint,
                ],
                check=True,
                capture_output=True,
            ).stdout
            public_key.write_bytes(exported)

            source_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPOSITORY,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            evidence = root / "evidence"
            gates_dir = evidence / "gates"
            gates_dir.mkdir(parents=True)
            coverage_artifacts = evidence / "artifacts/coverage"
            coverage_artifacts.mkdir(parents=True)
            for name in (
                "frontend-coverage-summary.json",
                "backend-coverage.json",
            ):
                (coverage_artifacts / name).write_bytes(
                    canonical_json(
                        {
                            "schema_version": 1,
                            "source_sha": source_sha,
                            "status": "contract-test",
                        }
                    )
                )
            gates: dict[str, dict[str, str]] = {}
            for name in REQUIRED_GATES:
                path = gates_dir / f"{name}.json"
                path.write_bytes(
                    canonical_json(
                        {
                            "schema_version": 1,
                            "gate": name,
                            "status": "passed",
                            "source_sha": source_sha,
                        }
                    )
                )
                gates[name] = {
                    "status": "passed",
                    "source_sha": source_sha,
                    "evidence_sha256": sha256_file(path),
                    "path": f"evidence/gates/{name}.json",
                }
            (evidence / "license-inventory.json").write_bytes(
                canonical_json(
                    {
                        "schema_version": 1,
                        "source_sha": source_sha,
                        "packages": [],
                    }
                )
            )
            cve_artifacts = evidence / "artifacts/container-cve"
            cve_artifacts.mkdir(parents=True)
            cve_rows = []
            for component in ALL_RUNTIME_IMAGE_NAMES:
                path = cve_artifacts / f"{component}.scout.sarif.json"
                path.write_bytes(
                    canonical_json(
                        {
                            "version": "2.1.0",
                            "runs": [],
                        }
                    )
                )
                cve_rows.append(
                    {
                        "component": component,
                        "path": (
                            "evidence/artifacts/container-cve/"
                            f"{path.name}"
                        ),
                        "sha256": sha256_file(path),
                    }
                )
            (evidence / "container-cve-inventory.json").write_bytes(
                canonical_json(
                    {
                        "schema_version": 1,
                        "source_sha": source_sha,
                        "scanner": "docker-scout",
                        "policy": "zero-critical-high",
                        "artifacts": cve_rows,
                    }
                )
            )
            security_artifacts = evidence / "artifacts/security"
            security_artifacts.mkdir(parents=True)
            spdx_rows = []
            for component in ALL_RUNTIME_IMAGE_NAMES:
                spdx_path = security_artifacts / f"{component}.spdx.json"
                spdx_path.write_bytes(
                    canonical_json(
                        {
                            "spdxVersion": "SPDX-2.3",
                            "name": f"contract-fixture-{component}",
                            "packages": [
                                {
                                    "name": component,
                                    "versionInfo": "contract-test",
                                    "licenseDeclared": "NOASSERTION",
                                }
                            ],
                        }
                    )
                )
                spdx_rows.append(
                    {
                        "component": component,
                        "image": "fixed-platform" if component in FIXED_PLATFORM_IMAGES else "release-inventory",
                        "path": f"evidence/artifacts/security/{spdx_path.name}",
                        "sha256": sha256_file(spdx_path),
                    }
                )
            (evidence / "spdx-inventory.json").write_bytes(
                canonical_json(
                    {
                        "schema_version": 1,
                        "source_sha": source_sha,
                        "format": "SPDX-2.3",
                        "artifacts": spdx_rows,
                    }
                )
            )
            images = {
                name: f"registry.invalid/nomosmart/{name}:1.0@sha256:"
                + hashlib.sha256(name.encode("utf-8")).hexdigest()
                for name in REQUIRED_IMAGES
            }
            output = root / "output"
            source = {
                "git_sha": source_sha,
                "tree_sha256": "a" * 64,
                "clean": True,
                "detached": True,
            }
            result = assemble_release(
                repo=REPOSITORY,
                source=source,
                release_id="contract-test",
                images=images,
                gates=gates,
                evidence_dir=evidence,
                output_dir=output,
                signing_fingerprint=fingerprint,
                public_key=public_key,
                gpg_home=gpg_home,
            )
            package = Path(result["package_dir"])
            original_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(Path(shutil.which("gpg") or "").parent)
            try:
                verified = verify_release_package(
                    package,
                    trusted_fingerprint=fingerprint,
                    expected_images=images,
                    gpg_binary=shutil.which("gpg") or "gpg",
                )
            finally:
                os.environ["PATH"] = original_path
            self.assertTrue(verified["production_ready"])
            self.assertEqual(
                verified["platform_image_digests"], FIXED_PLATFORM_IMAGES
            )
            self.assertTrue(
                (package / "deploy/installer/nomosmart-one-click").is_file()
            )
            self.assertTrue(
                (package / "deploy/installer/nomosmart-one-click").stat().st_mode
                & 0o111
            )
            self.assertTrue(
                (package / "deploy/release/nomosmart-release").stat().st_mode
                & 0o111
            )
            with (
                package / "deploy/installer/nomosmart-install.example.toml"
            ).open("rb") as handle:
                bundled_example = tomllib.load(handle)
            with (
                package
                / "deploy/installer/nomosmart-install.external-services.example.toml"
            ).open("rb") as handle:
                external_example = tomllib.load(handle)
            self.assertEqual(bundled_example["deployment_profile"], "bundled")
            self.assertEqual(
                external_example["deployment_profile"], "external-services"
            )
            package_guide = (
                package / "deploy/release/PACKAGE_README.md"
            ).read_text(encoding="utf-8")
            self.assertIn("--profile bundled", package_guide)
            self.assertIn("--profile external-services", package_guide)
            self.assertIn("--init-config", package_guide)
            operator_private = root / "operator-private"
            operator_private.mkdir(mode=0o700)
            chart_root = package.resolve() / "deploy/helm/nomosmart"
            expected_values = {
                "bundled": ["values-prod.yaml"],
                "external-services": [
                    "values-prod.yaml",
                    "values-external-services.example.yaml",
                ],
            }
            for profile, values_names in expected_values.items():
                initialized_path = operator_private / f"{profile}.toml"
                initialized = subprocess.run(
                    [
                        str(package / "deploy/installer/nomosmart-one-click"),
                        "--profile",
                        profile,
                        "--config",
                        str(initialized_path),
                        "--init-config",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(initialized.returncode, 0, initialized.stderr)
                with initialized_path.open("rb") as handle:
                    initialized_config = tomllib.load(handle)
                self.assertEqual(
                    initialized_config["deployment_profile"], profile
                )
                self.assertEqual(
                    initialized_config["application"]["chart"], str(chart_root)
                )
                self.assertEqual(
                    initialized_config["application"]["values"],
                    [str(chart_root / name) for name in values_names],
                )
            self.assertFalse((package / "frontend/src").exists())
            self.assertFalse((package / "backend/app").exists())
            self.assertFalse(any(path.name == ".env" for path in package.rglob("*")))

            target = package / "deploy/installer/README.md"
            target.write_text(
                target.read_text(encoding="utf-8") + "\ntampered\n",
                encoding="utf-8",
            )
            with self.assertRaises(ReleaseContractError):
                verify_release_package(
                    package,
                    trusted_fingerprint=fingerprint,
                )

    def test_manifest_rejects_missing_mandatory_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            (package / "release-manifest.json").write_text(
                json.dumps({"schema_version": 2}),
                encoding="utf-8",
            )
            with self.assertRaises(ReleaseContractError):
                verify_release_package(
                    package,
                    trusted_fingerprint="A" * 40,
                )


if __name__ == "__main__":
    unittest.main()
