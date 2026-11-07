"""Real CLI/files/OpenSSL contracts; live Docker behavior has a separate runner."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("nomosmart_cli", ROOT / "deploy/docker/nomosmart_cli.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def test_launcher_resolves_root_outside_cwd(tmp_path):
    output = subprocess.run([str(ROOT / "nomosmart"), "--help"], cwd=tmp_path, capture_output=True, text=True)
    assert output.returncode == 0
    assert "{up,status,logs,down}" in output.stdout


@pytest.mark.parametrize("args", [["up", "--timeout", "29"], ["up", "--timeout", "7201"], ["logs", "--tail", "0"], ["down", "-v"]])
def test_invalid_cli_limits_before_docker(args, tmp_path):
    output = subprocess.run([str(ROOT / "nomosmart"), *args], cwd=tmp_path, capture_output=True, text=True)
    assert output.returncode == 2


def test_literal_environment_is_not_executable(tmp_path):
    target = tmp_path / "must-not-be-created"
    config = tmp_path / "literal.env"
    config.write_text("COMPOSE_PROJECT_NAME=isolated\nEXTRA=$(touch " + str(target) + ")\n")
    config.chmod(0o600)
    value = cli.read_env(config)
    assert value["COMPOSE_PROJECT_NAME"] == "isolated"
    assert value["EXTRA"].startswith("$(touch ")
    assert not target.exists()


@pytest.mark.parametrize("text", ["NAME=x\nNAME=y\n", "not an env entry\n", "NAME='unclosed\n"])
def test_ambiguous_environment_rejected(tmp_path, text):
    config = tmp_path / "bad.env"
    config.write_text(text)
    config.chmod(0o600)
    with pytest.raises(cli.WorkflowError):
        cli.read_env(config)


def test_private_config_and_symlink_rejected(tmp_path):
    config = tmp_path / "private.env"
    config.write_text("COMPOSE_PROJECT_NAME=isolated\n")
    config.chmod(0o644)
    with pytest.raises(cli.WorkflowError, match="PRIVATE_FILE_PERMISSIONS"):
        cli.read_env(config)
    config.chmod(0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(config)
    with pytest.raises(cli.WorkflowError, match="INCOMPLETE_CONFIG"):
        cli.read_env(alias)


@pytest.mark.parametrize("values", [
    {"EDGE_HTTP_PORT": "0"}, {"EDGE_HTTPS_PORT": "65536"}, {"EDGE_HTTP_PORT": "443"},
    {"EDGE_HTTPS_PORT": "00443"}, {"EDGE_HTTP_PORT": "text"},
    {"COMPOSE_PROJECT_NAME": "OtherProject"}, {"COMPOSE_PROJECT_NAME": "../outside"},
    {"NOMOSMART_PUBLIC_HOST": "x.test; touch elsewhere"}, {"EDGE_HOST_IP": "host.test"},
    {"EDGE_HTTPS_PORT": "8443", "NOMOSMART_PUBLIC_ORIGIN": "https://nomosmart.local"},
])
def test_invalid_selectors_fail_closed(values):
    with pytest.raises(cli.WorkflowError):
        cli.selectors(values)


def test_nondefault_origin_is_canonical():
    assert cli.selectors({"NOMOSMART_PUBLIC_HOST": "localhost", "EDGE_HTTPS_PORT": "8443"})["origin"] == "https://localhost:8443"
    assert cli.selectors({})["origin"] == "https://nomosmart.local"


def test_logs_do_not_echo_secret_or_arbitrary_content():
    actual_secret = secrets.token_hex(32)
    data = {"level": "INFO", "message": actual_secret, "authorization": actual_secret,
            "document_content": "confidential document body", "status_code": 200,
            "path": "/callback?code=" + actual_secret, "timestamp": "2026-10-03T10:00:00+00:00"}
    result = cli.safe_log(json.dumps(data), [actual_secret])
    assert actual_secret not in result
    assert "confidential document body" not in result
    assert "callback" not in result
    assert json.loads(result)["status_code"] == 200
    assert actual_secret not in cli.safe_log("Authorization: Bearer " + actual_secret, [actual_secret])


def test_real_process_lock_is_exclusive_and_released(tmp_path):
    shutil.copy2(ROOT / "docker-compose.yml", tmp_path / "docker-compose.yml")
    (tmp_path / "deploy/docker").mkdir(parents=True)
    first, second = cli.Workflow(tmp_path), cli.Workflow(tmp_path)
    with first.lock():
        with pytest.raises(cli.WorkflowError, match="BUSY"):
            with second.lock():
                raise AssertionError("second lock must not be acquired")
    with second.lock():
        assert second.mutating
    assert (first.state_dir / "lock").stat().st_mode & 0o777 == 0o600
    assert first.state_dir.stat().st_mode & 0o777 == 0o700


@pytest.fixture
def private_package_root():
    with tempfile.TemporaryDirectory(prefix="chg313-private-package-") as name:
        yield Path(name)


def test_real_package_generates_custom_port_and_preserves_generation(private_package_root):
    tmp_path = private_package_root
    # Copy only actual initializer dependencies. No local deployment inputs.
    for folder in ("deploy/package", "deploy/migrations"):
        target = tmp_path / folder
        target.mkdir(parents=True)
        for path in (ROOT / folder).glob("*.py"):
            shutil.copy2(path, target / path.name)
    shutil.copy2(ROOT / "deploy/migrations/release-contract.json", tmp_path / "deploy/migrations/release-contract.json")
    (tmp_path / "deploy/docker").mkdir()
    command = [sys.executable, "-B", str(tmp_path / "deploy/package/nomosmart_package.py"), "init",
               "--profile", "factory_acceptance", "--app-env", "development", "--no-display",
               "--random-initial-credentials", "--public-host", "localhost", "--compose-project", "isolated-real",
               "--http-port", "8081", "--https-port", "8443"]
    first = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert first.returncode == 0, "actual package initialization failed"
    env = tmp_path / "deploy/docker/nomosmart.env"
    values = cli.read_env(env)
    assert values["COMPOSE_PROJECT_NAME"] == "isolated-real"
    for name in ("NOMOSMART_PUBLIC_ORIGIN", "FRONTEND_APP_ORIGIN", "NEXT_PUBLIC_APP_ORIGIN", "CORS_ALLOWED_ORIGINS"):
        assert values[name] == "https://localhost:8443"
    # PROTAUTH-011: initialization cannot invent or bundle an external IdP.
    # The operator supplies the protocol connection separately.
    for name in ("OIDC_ISSUER_URL", "NEXT_PUBLIC_OIDC_ISSUER_URL", "FRONTEND_OIDC_ISSUER_URL"):
        assert name not in values
    assert set(values["COMPOSE_PROFILES"].split(",")) == {
        "postgresql", "redis", "rustfs", "opensearch", "neo4j",
    }
    generation = tmp_path / "deploy/docker/generated/current"
    before = {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in generation.rglob("*") if p.is_file()}
    again = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert again.returncode == 0
    after = {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in generation.rglob("*") if p.is_file()}
    assert before == after
    env.unlink()
    partial = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert partial.returncode == 2
    assert not env.exists()
