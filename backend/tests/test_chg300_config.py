"""Actual local Helm rendering/Compose parsing, not runtime acceptance."""
from pathlib import Path
import os
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def render(*extra):
    return subprocess.run(["helm", "template", "chg300", str(ROOT / "deploy/helm/nomosmart"),
        "--set", "installer.deploymentStage=application", *extra], capture_output=True, text=True,
        env={k: os.environ[k] for k in ("HOME", "PATH", "TMPDIR") if k in os.environ}, timeout=30)


@pytest.mark.parametrize("checksum", ["-2147483648", "2147483647", "0"])
def test_config_contract_is_shared_and_zero_is_not_missing(checksum):
    result = render("--set-string", "migration.requiredVersion=049", "--set-string", "migration.requiredChecksum=" + checksum)
    assert result.returncode == 0, result.stderr
    documents = [d for d in yaml.safe_load_all(result.stdout) if d]
    config = next(d for d in documents if d["kind"] == "ConfigMap" and d["metadata"]["name"].endswith("-config"))
    assert config["data"]["MIGRATION_REQUIRED_VERSION"] == "049"
    assert config["data"]["MIGRATION_REQUIRED_CHECKSUM"] == checksum
    assert config["data"]["MIGRATION_CHECK_TIMEOUT_SECONDS"] == "10"
    apps = [d for d in documents if d["kind"] == "Deployment" and d["metadata"].get("labels", {}).get(
        "app.kubernetes.io/component") in ("backend", "frontend", "worker", "beat")]
    assert len(apps) == 4
    for app in apps:
        for init in app["spec"]["template"]["spec"]["initContainers"]:
            # Source wiring, not evidence of a running Pod or completed migration.
            assert {"configMapRef": {"name": config["metadata"]["name"]}} in init.get("envFrom", [])
        if app["metadata"]["labels"]["app.kubernetes.io/component"] == "frontend":
            probe = app["spec"]["template"]["spec"]["initContainers"][0]
            assert "env" not in probe  # No new Frontend DB credential/network authority.
            code = probe["args"][0]
            assert "migration_readiness_matches(json.loads(content), settings)" in code
            compile(code, "rendered-frontend-probe", "exec")


@pytest.mark.parametrize("field,value", [
    ("requiredChecksum", "2147483648"), ("requiredChecksum", "-2147483649"),
    ("requiredChecksum", "1.2"), ("requiredVersion", "49;DROP"),
    ("checkTimeoutSeconds", "0"), ("checkTimeoutSeconds", "61"),
])
def test_invalid_release_values_are_rejected(field, value):
    values = {"requiredVersion": "049", "requiredChecksum": "123", field: value}
    args = []
    for name, item in values.items():
        args.extend(["--set" if name == "checkTimeoutSeconds" else "--set-string", "migration." + name + "=" + item])
    result = render(*args)
    assert result.returncode != 0


@pytest.mark.parametrize("field", ["requiredVersion", "requiredChecksum"])
def test_partial_release_contract_is_rejected(field):
    assert render("--set-string", "migration." + field + "=49").returncode != 0


@pytest.mark.parametrize("component,name", [
    ("backend", "MIGRATION_REQUIRED_VERSION"), ("frontend", "MIGRATION_REQUIRED_CHECKSUM"),
    ("backend", "migration_required_version"), ("frontend", "Migration_Check_Timeout_Seconds"),
])
def test_case_insensitive_environment_override_rejected(component, name):
    result = render("--set-string", component + ".env." + name + "=1")
    assert result.returncode != 0 and "chart-managed" in result.stderr


def test_compose_inherits_same_contract_without_resolving_private_env():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for service in ("backend", "celery-worker", "celery-beat", "deployment-bootstrap"):
        env = compose["services"][service]["environment"]
        assert env["MIGRATION_REQUIRED_VERSION"] == "${MIGRATION_REQUIRED_VERSION:-}"
        assert env["MIGRATION_REQUIRED_CHECKSUM"] == "${MIGRATION_REQUIRED_CHECKSUM:-}"
    assert compose["services"]["backend"]["depends_on"]["migration"]["condition"] == "service_completed_successfully"
