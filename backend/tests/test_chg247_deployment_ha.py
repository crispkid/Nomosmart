from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy/helm/nomosmart"


def _render(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "helm",
            "template",
            "nomosmart",
            str(CHART),
            "-f",
            str(CHART / "values-prod.yaml"),
            "--set",
            "installer.deploymentStage=application",
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_production_application_tier_is_replicated_separated_and_disruption_safe() -> None:
    result = _render()
    assert result.returncode == 0, result.stderr
    documents = [item for item in yaml.safe_load_all(result.stdout) if isinstance(item, dict)]
    deployments = {
        item["metadata"]["name"]: item
        for item in documents
        if item.get("kind") == "Deployment"
    }
    for component in ("frontend", "backend", "worker"):
        deployment = deployments[f"nomosmart-{component}"]
        assert deployment["spec"]["replicas"] == 2
        assert deployment["spec"]["strategy"]["rollingUpdate"] == {
            "maxUnavailable": 0,
            "maxSurge": 1,
        }
        affinity = deployment["spec"]["template"]["spec"]["affinity"]["podAntiAffinity"]
        rule = affinity["requiredDuringSchedulingIgnoredDuringExecution"][0]
        assert rule["topologyKey"] == "kubernetes.io/hostname"
        assert rule["labelSelector"]["matchLabels"]["app.kubernetes.io/component"] == component
    assert deployments["nomosmart-beat"]["spec"]["replicas"] == 2
    assert deployments["nomosmart-beat"]["spec"]["strategy"]["rollingUpdate"] == {
        "maxUnavailable": 0,
        "maxSurge": 1,
    }

    budgets = {
        item["metadata"]["name"]: item
        for item in documents
        if item.get("kind") == "PodDisruptionBudget"
    }
    for component in ("frontend", "backend", "worker", "beat"):
        assert budgets[f"nomosmart-{component}"]["spec"]["minAvailable"] == 1


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
@pytest.mark.parametrize(
    "override,expected",
    [
        ("replicaCount.backend=1", "/replicaCount/backend"),
        ("highAvailability.enabled=false", "/highAvailability/enabled"),
        ("highAvailability.rollingUpdate.maxUnavailable=1", "/highAvailability/rollingUpdate/maxUnavailable"),
    ],
)
def test_production_policy_rejects_unsafe_cross_field_values(override: str, expected: str) -> None:
    result = _render("--set", override)
    assert result.returncode != 0
    assert expected in result.stderr
