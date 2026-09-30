from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import InstallConfig
from .core import InstallerError, Runner, atomic_private_json
from .kube import Kubernetes


class Helm:
    def __init__(
        self,
        config: InstallConfig,
        runner: Runner,
        kube: Kubernetes | None = None,
    ) -> None:
        self.config = config
        self.runner = runner
        self.kube = kube

    def values_path(
        self,
        stage: str,
        *,
        finalize: bool = False,
        bootstrap_release: str = "",
    ) -> Path:
        suffix = "-finalize" if finalize else ""
        path = self.config.application.state_dir / f"values-{stage}{suffix}.json"
        payload = self.config.generated_helm_values(stage)
        if finalize:
            payload["installer"]["deploymentStage"] = "application"
            payload["bootstrap"]["deploymentPhase"] = "onboarding"
            payload["bootstrap"]["finalize"]["enabled"] = True
        if bootstrap_release:
            payload["bootstrap"]["evidenceRelease"] = bootstrap_release
        atomic_private_json(path, payload)
        return path

    def _target_flags(self) -> list[str]:
        return [
            "--kube-context",
            self.config.target.context,
            "--namespace",
            self.config.target.namespace,
        ]

    def render(self, stage: str) -> str:
        generated = self.values_path(stage)
        command = [
            "helm",
            "template",
            self.config.target.release,
            str(self.config.application.chart),
            *self._target_flags(),
        ]
        for path in self.config.application.values:
            command.extend(["--values", str(path)])
        command.extend(["--values", str(generated)])
        return self.runner.run(command, timeout=180).stdout

    def upgrade(
        self,
        stage: str,
        *,
        finalize: bool = False,
        bootstrap_release: str = "",
    ) -> int:
        generated = self.values_path(
            stage,
            finalize=finalize,
            bootstrap_release=bootstrap_release,
        )
        command = [
            "helm",
            "upgrade",
            "--install",
            self.config.target.release,
            str(self.config.application.chart),
            *self._target_flags(),
            "--history-max",
            "20",
            "--timeout",
            "30m",
        ]
        for path in self.config.application.values:
            command.extend(["--values", str(path)])
        command.extend(["--values", str(generated)])
        if stage != "foundation" or finalize:
            command.extend(["--wait", "--wait-for-jobs"])
        completed = self.runner.run(
            command,
            timeout=1900,
            accepted=frozenset({0, 1}),
        )
        revision: int | None = None
        try:
            revision = self.revision()
        except InstallerError:
            if completed.returncode == 0:
                raise
        expected_jobs: list[str] = []
        if revision is not None and stage == "application":
            fullname = (
                self.config.target.release
                if "nomosmart" in self.config.target.release
                else f"{self.config.target.release}-nomosmart"
            )[:63].rstrip("-")
            if finalize:
                expected_jobs = [f"{fullname}-finalize-{revision}"]
            else:
                expected_jobs = [
                    f"{fullname}-migration-{revision}",
                    f"{fullname}-bootstrap-{revision}",
                ]
        if self.kube is not None:
            for name in expected_jobs:
                state = self.kube.job_state(name)
                if state["terminal"] and state["status"] == "failed":
                    exit_codes = ",".join(
                        str(code) for code in state["exit_codes"]
                    ) or "unknown"
                    raise InstallerError(
                        f"Job/{name} failed: {state['reason']} "
                        f"(exit={exit_codes})"
                    )
        if completed.returncode != 0:
            raise InstallerError(
                "Helm upgrade failed before all workloads became healthy"
            )
        if revision is None:
            raise InstallerError("Helm upgrade has no release revision")
        if self.kube is not None:
            for name in expected_jobs:
                self.kube.wait_job_terminal(name, timeout=900)
        return revision

    def revision(self) -> int:
        result = self.runner.run(
            [
                "helm",
                "status",
                self.config.target.release,
                *self._target_flags(),
                "--output",
                "json",
            ]
        )
        try:
            payload = json.loads(result.stdout)
            revision = int(payload.get("version"))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise InstallerError("Helm returned invalid release revision") from exc
        return revision

    def status(self) -> dict[str, Any]:
        result = self.runner.run(
            [
                "helm",
                "status",
                self.config.target.release,
                *self._target_flags(),
                "--output",
                "json",
            ]
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise InstallerError("Helm returned invalid status JSON") from exc
        if not isinstance(payload, dict):
            raise InstallerError("Helm status is invalid")
        return {
            "revision": int(payload.get("version") or 0),
            "status": str((payload.get("info") or {}).get("status") or ""),
            "chart": str(payload.get("chart") or ""),
            "app_version": str(payload.get("app_version") or ""),
        }
