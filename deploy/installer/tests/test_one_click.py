from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest


INSTALLER_DIR = Path(__file__).resolve().parents[1]
WRAPPER = INSTALLER_DIR / "nomosmart-one-click"
BUNDLED_EXAMPLE = INSTALLER_DIR / "nomosmart-install.example.toml"
EXTERNAL_EXAMPLE = INSTALLER_DIR / "nomosmart-install.external-services.example.toml"


class OneClickWrapperTests(unittest.TestCase):
    digest = "a" * 64

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package = self.root / "package"
        self.installer_dir = self.package / "deploy" / "installer"
        self.installer_dir.mkdir(parents=True)
        self.wrapper = self.installer_dir / WRAPPER.name
        shutil.copy2(WRAPPER, self.wrapper)
        shutil.copy2(BUNDLED_EXAMPLE, self.installer_dir / BUNDLED_EXAMPLE.name)
        shutil.copy2(EXTERNAL_EXAMPLE, self.installer_dir / EXTERNAL_EXAMPLE.name)
        self.wrapper.chmod(0o755)
        self.chart_dir = self.package / "deploy" / "helm" / "nomosmart"
        self.chart_dir.mkdir(parents=True)
        self.chart_dir = self.chart_dir.resolve()
        (self.chart_dir / "Chart.yaml").write_text(
            "apiVersion: v2\nname: nomosmart\nversion: 0.0.0\n",
            encoding="utf-8",
        )
        for values_name in (
            "values-prod.yaml",
            "values-external-services.example.yaml",
        ):
            (self.chart_dir / values_name).write_text("# test values\n", encoding="utf-8")

        self.private = self.root / "operator-private"
        self.private.mkdir(mode=0o700)
        self.private.chmod(0o700)
        self.config = self.private / "installer.toml"
        self.write_config("bundled")

        self.log = self.root / "calls.log"
        self.state = self.root / "state"
        fake = self.installer_dir / "nomosmart-install"
        fake.write_text(
            """#!/bin/sh
set -eu
printf '%s\\n' "$1" >> "$TEST_LOG"
case "$1" in
  plan) printf '%s\\n' '{"status":"ready","config_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}' ;;
  status)
    if [ -f "$TEST_STATE" ]; then
      printf '%s\\n' '{"status":"in-progress"}'
    else
      printf '%s\\n' '{"status":"not-installed"}'
    fi
    ;;
  install|resume)
    if [ "${TEST_FAIL_OPERATION:-}" = "$1" ]; then
      exit 30
    fi
    : > "$TEST_STATE"
    printf '%s\\n' '{"status":"complete"}'
    ;;
  verify) printf '%s\\n' '{"status":"verified"}' ;;
  *) exit 99 ;;
esac
""",
            encoding="utf-8",
        )
        fake.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_config(self, profile: str) -> None:
        self.config.write_text(
            'api_version = "install.nomosmart.io/v1alpha1"\n'
            f'deployment_profile = "{profile}"\n',
            encoding="utf-8",
        )

    def run_wrapper(
        self,
        *arguments: str,
        input_text: str | None = None,
        fail_operation: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update({
            "TEST_LOG": str(self.log),
            "TEST_STATE": str(self.state),
        })
        if fail_operation is not None:
            environment["TEST_FAIL_OPERATION"] = fail_operation
        return subprocess.run(
            [str(self.wrapper), *arguments],
            input=input_text,
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_help_is_available_without_config_or_cluster(self) -> None:
        completed = self.run_wrapper("--help")
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--profile bundled", completed.stdout)
        self.assertIn("--profile external-services", completed.stdout)
        self.assertIn("--init-config", completed.stdout)
        self.assertIn("config-only calls remain compatible", completed.stdout)
        self.assertIn("factory reset", completed.stdout)
        self.assertEqual(self.calls(), [])

    def test_bundled_init_creates_owner_only_config_without_installer_call(self) -> None:
        destination = self.private / "bundled.toml"
        completed = self.run_wrapper(
            "--profile",
            "bundled",
            "--config",
            str(destination),
            "--init-config",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        with destination.open("rb") as handle:
            created = tomllib.load(handle)
        self.assertEqual(created["deployment_profile"], "bundled")
        self.assertEqual(created["application"]["chart"], str(self.chart_dir))
        self.assertEqual(
            created["application"]["values"],
            [str(self.chart_dir / "values-prod.yaml")],
        )
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertIn("configuration template is ready", completed.stdout.lower())
        self.assertIn("--profile bundled", completed.stdout)
        self.assertIn("--plan-only", completed.stdout)
        self.assertEqual(self.calls(), [])

    def test_external_init_creates_strict_external_config(self) -> None:
        destination = self.private / "external.toml"
        completed = self.run_wrapper(
            "--init-config",
            "--profile",
            "external-services",
            "--config",
            str(destination),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        with destination.open("rb") as handle:
            created = tomllib.load(handle)
        self.assertEqual(created["deployment_profile"], "external-services")
        self.assertEqual(created["application"]["runtime_secret_mode"], "existing")
        self.assertEqual(created["application"]["chart"], str(self.chart_dir))
        self.assertEqual(
            created["application"]["values"],
            [
                str(self.chart_dir / "values-prod.yaml"),
                str(self.chart_dir / "values-external-services.example.yaml"),
            ],
        )
        self.assertEqual(self.calls(), [])

    def test_init_requires_the_profile_chart_files_in_the_same_package(self) -> None:
        (self.chart_dir / "values-prod.yaml").unlink()
        destination = self.private / "missing-chart-values.toml"
        completed = self.run_wrapper(
            "--profile", "bundled", "--config", str(destination), "--init-config"
        )
        self.assertEqual(completed.returncode, 20)
        self.assertIn("required Helm values file", completed.stderr)
        self.assertFalse(destination.exists())
        self.assertEqual(self.calls(), [])

    def test_init_never_overwrites_existing_destination_or_symlink(self) -> None:
        destination = self.private / "existing.toml"
        destination.write_text("preserve-me\n", encoding="utf-8")
        completed = self.run_wrapper(
            "--profile", "bundled", "--config", str(destination), "--init-config"
        )
        self.assertEqual(completed.returncode, 20)
        self.assertEqual(destination.read_text(encoding="utf-8"), "preserve-me\n")
        self.assertIn("left unchanged", completed.stderr)

        symlink = self.private / "linked.toml"
        symlink.symlink_to(destination)
        linked = self.run_wrapper(
            "--profile", "bundled", "--config", str(symlink), "--init-config"
        )
        self.assertEqual(linked.returncode, 20)
        self.assertTrue(symlink.is_symlink())
        self.assertEqual(destination.read_text(encoding="utf-8"), "preserve-me\n")
        self.assertEqual(self.calls(), [])

    def test_init_rejects_unsafe_parent_and_incompatible_options(self) -> None:
        unsafe = self.root / "shared"
        unsafe.mkdir(mode=0o755)
        unsafe.chmod(0o755)
        completed = self.run_wrapper(
            "--profile", "bundled", "--config", str(unsafe / "install.toml"), "--init-config"
        )
        self.assertEqual(completed.returncode, 20)
        self.assertIn("mode 0700", completed.stderr)
        self.assertFalse((unsafe / "install.toml").exists())

        real_private = self.root / "real-private"
        real_private.mkdir(mode=0o700)
        linked_parent = self.root / "linked-private"
        linked_parent.symlink_to(real_private, target_is_directory=True)
        linked = self.run_wrapper(
            "--profile",
            "bundled",
            "--config",
            str(linked_parent / "install.toml"),
            "--init-config",
        )
        self.assertEqual(linked.returncode, 20)
        self.assertIn("not a symlink", linked.stderr)
        self.assertFalse((real_private / "install.toml").exists())

        combined = self.run_wrapper(
            "--profile",
            "bundled",
            "--config",
            str(self.private / "combined.toml"),
            "--init-config",
            "--plan-only",
        )
        self.assertEqual(combined.returncode, 20)
        self.assertIn("local-only step", combined.stderr)
        self.assertEqual(self.calls(), [])

    def test_init_requires_explicit_supported_profile(self) -> None:
        missing = self.run_wrapper(
            "--config", str(self.private / "missing.toml"), "--init-config"
        )
        self.assertEqual(missing.returncode, 20)
        self.assertIn("select --profile", missing.stderr)

        unknown = self.run_wrapper(
            "--profile",
            "mixed",
            "--config",
            str(self.private / "unknown.toml"),
            "--init-config",
        )
        self.assertEqual(unknown.returncode, 20)
        self.assertIn("not supported", unknown.stderr)
        self.assertEqual(self.calls(), [])

    def test_profile_mismatch_and_malformed_toml_stop_before_plan(self) -> None:
        self.write_config("external-services")
        mismatch = self.run_wrapper(
            "--profile", "bundled", "--config", str(self.config), "--plan-only"
        )
        self.assertEqual(mismatch.returncode, 20)
        self.assertIn("does not match", mismatch.stderr)
        self.assertEqual(self.calls(), [])

        self.config.write_text("deployment_profile = [\n", encoding="utf-8")
        malformed = self.run_wrapper(
            "--profile", "bundled", "--config", str(self.config), "--plan-only"
        )
        self.assertEqual(malformed.returncode, 20)
        self.assertIn("does not contain a valid", malformed.stderr)
        self.assertEqual(self.calls(), [])

    def test_external_plan_only_shows_responsibility_and_never_reads_status(self) -> None:
        self.write_config("external-services")
        completed = self.run_wrapper(
            "--profile",
            "external-services",
            "--config",
            str(self.config),
            "--plan-only",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Profile confirmed: external-services", completed.stdout)
        self.assertIn("external services remain operator-owned", completed.stdout)
        self.assertIn("Plan preview complete", completed.stdout)
        self.assertEqual(self.calls(), ["plan"])

    def test_legacy_config_only_run_infers_profile_and_shows_migration_hint(self) -> None:
        completed = self.run_wrapper("--config", str(self.config), "--plan-only")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Configuration profile detected: bundled", completed.stdout)
        self.assertIn("--profile bundled", completed.stdout)
        self.assertEqual(self.calls(), ["plan"])

    def test_noninteractive_run_requires_explicit_confirmation(self) -> None:
        completed = self.run_wrapper(
            "--profile", "bundled", "--config", str(self.config), input_text=""
        )
        self.assertEqual(completed.returncode, 10)
        self.assertIn("Action required", completed.stderr)
        self.assertIn("No installation mutation", completed.stderr)
        self.assertEqual(self.calls(), ["plan", "status"])

    def test_yes_runs_install_status_and_verify(self) -> None:
        completed = self.run_wrapper(
            "--profile", "bundled", "--config", str(self.config), "--yes"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self.calls(),
            ["plan", "status", "install", "status", "verify"],
        )
        self.assertIn("verification is complete", completed.stdout)

    def test_mismatched_digest_cannot_start_install(self) -> None:
        completed = self.run_wrapper(
            "--profile",
            "bundled",
            "--config",
            str(self.config),
            "--confirm-digest",
            "b" * 64,
        )
        self.assertEqual(completed.returncode, 10)
        self.assertIn("does not match", completed.stderr)
        self.assertIn("remains unchanged", completed.stderr)
        self.assertEqual(self.calls(), ["plan", "status"])

    def test_existing_state_uses_resume(self) -> None:
        self.state.write_text("existing", encoding="utf-8")
        completed = self.run_wrapper(
            "--profile",
            "bundled",
            "--config",
            str(self.config),
            "--confirm-digest",
            self.digest,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self.calls(),
            ["plan", "status", "resume", "status", "verify"],
        )

    def test_operation_failure_retains_state_and_gives_next_step(self) -> None:
        completed = self.run_wrapper(
            "--profile",
            "bundled",
            "--config",
            str(self.config),
            "--yes",
            fail_operation="install",
        )
        self.assertEqual(completed.returncode, 30)
        self.assertIn("stopped safely", completed.stderr)
        self.assertIn("state is retained", completed.stderr)
        self.assertIn("same explicit-profile wrapper", completed.stderr)
        self.assertEqual(self.calls(), ["plan", "status", "install"])


if __name__ == "__main__":
    unittest.main()
