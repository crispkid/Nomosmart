"""BEAT-RESOURCES-001: real Helm CLI renders; no simulated services."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy/helm/nomosmart"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
WORKER = {"requests": {"cpu": "500m", "memory": "512Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}}


def render(override: dict, production: bool = False) -> subprocess.CompletedProcess[str]:
    args = ["helm", "template", "nomosmart", str(CHART)]
    if production:
        args += ["-f", str(CHART / "values-prod.yaml")]
    args += ["--set", "installer.deploymentStage=application", "--set-json", "worker.resources=" + json.dumps(WORKER), "-f", "-"]
    return subprocess.run(args, input=json.dumps(override), text=True, capture_output=True, check=False)


def documents(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stderr
    return {v["metadata"]["name"]: v for v in yaml.safe_load_all(result.stdout) if isinstance(v, dict)}


def resources(docs: dict, component: str) -> dict:
    return docs["nomosmart-" + component]["spec"]["template"]["spec"]["containers"][0]["resources"]


@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("beat", [{}, {"resources": None}, {"resources": {}}, {"resources": {"requests": {}, "limits": {}}}])
def test_legacy_fallback_is_identical(beat: dict, production: bool) -> None:
    baseline = documents(render({}, production))
    actual = documents(render({"beat": beat}, production))
    assert actual == baseline
    assert resources(actual, "worker") == resources(actual, "beat") == WORKER


@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("override,expected", [
    ({"requests": {"cpu": "250m"}}, {"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": WORKER["limits"]}),
    ({"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}}, {"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": WORKER["limits"]}),
    ({"limits": {"memory": "2Gi"}}, {"requests": WORKER["requests"], "limits": {"cpu": "1", "memory": "2Gi"}}),
    ({"requests": {"cpu": 0}}, {"requests": {"cpu": 0, "memory": "512Mi"}, "limits": WORKER["limits"]}),
])
def test_partial_override_is_independent_and_capacity_matches(override: dict, expected: dict, production: bool) -> None:
    baseline = documents(render({}, production))
    actual = documents(render({"beat": {"resources": override}}, production))
    assert resources(actual, "beat") == expected
    assert resources(actual, "worker") == WORKER
    before = baseline["nomosmart-beat"]["spec"]["template"]["spec"]["containers"][0]
    before["resources"] = expected
    if production:
        def capacity(docs: dict) -> dict:
            return json.loads(base64.b64decode(docs["nomosmart-capacity-plan"]["binaryData"]["plan.json"]))
        old, new = capacity(baseline), capacity(actual)
        for item in old["workloads"]:
            if item["name"] == "beat":
                item.update(expected)
        assert new == old
        baseline["nomosmart-capacity-plan"] = actual["nomosmart-capacity-plan"]
    assert actual == baseline  # No strategy, replica, PDB or unrelated changes.


@pytest.mark.parametrize("value", [True, [], "250m", {"cpu": "250m"}, {"requests": None}, {"limits": []}, {"requests": {"cpu": None}}, {"requests": {"cpu": True}}, {"requests": {"cpu": -1}}, {"limits": {"memory": ""}}, {"requests": {"cpu": {"value": 1}}}])
def test_schema_rejects_invalid_resource_structures(value: object) -> None:
    result = render({"beat": {"resources": value}})
    assert result.returncode != 0
    assert "beat/resources" in result.stderr or "beat.resources" in result.stderr
