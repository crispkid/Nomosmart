from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy" / "helm" / "nomosmart"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_removed_security_services_are_absent_from_deployment_sources() -> None:
    compose = yaml.safe_load(read("docker-compose.yml"))
    assert "vault" not in compose["services"]
    assert "clamav" not in compose["services"]
    assert "vault" not in compose.get("volumes", {})
    assert "clamav" not in compose.get("volumes", {})
    assert not (CHART / "templates" / "vault-policy.yaml").exists()
    assert not (CHART / "templates" / "clamav.yaml").exists()
    assert not (ROOT / "backend/app/security/vault.py").exists()


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_backend_and_worker_mount_the_runtime_kubernetes_secret() -> None:
    result = subprocess.run(
        [
            "helm",
            "template",
            "nomosmart",
            str(CHART),
            "--set",
            "installer.deploymentStage=application",
            "--set",
            "secrets.existingSecret=operator-runtime-secrets",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    documents = [row for row in yaml.safe_load_all(result.stdout) if isinstance(row, dict)]
    deployments = {
        row["metadata"]["name"]: row
        for row in documents
        if row.get("kind") == "Deployment"
    }
    for name in ("nomosmart-backend", "nomosmart-worker"):
        pod = deployments[name]["spec"]["template"]["spec"]
        volume = next(row for row in pod["volumes"] if row["name"] == "runtime-secret")
        assert volume["secret"] == {
            "secretName": "operator-runtime-secrets",
            "defaultMode": 256,
        }
        mount = next(
            row
            for row in pod["containers"][0]["volumeMounts"]
            if row["name"] == "runtime-secret"
        )
        assert mount["mountPath"] == "/var/run/nomosmart-secrets/operator-runtime-secrets"
        assert mount["readOnly"] is True


def test_runtime_secret_reference_contract_is_closed_and_file_backed() -> None:
    source = read("backend/app/security/secrets.py")
    assert 'parsed.scheme == "k8s-secret"' in source
    assert 'parsed.scheme == "compose-secret"' in source
    assert 'reference.startswith("vault://")' in source
    assert "legacy_vault_reference_requires_migration" in source
    assert "target_resolved.read_text" in source
    assert "wildcard = f\"{reference.name}#*\"" in source


def test_upgrade_preflight_blocks_legacy_references_and_unfinished_scan_work() -> None:
    source = read("backend/app/deployment/bootstrap.py")
    assert "api_key_secret_ref LIKE 'vault://%'" in source
    assert "credential_secret_ref LIKE 'vault://%'" in source
    assert "legacy_secret_references_require_migration" in source
    assert "topic = 'file.scan.requested'" in source
    assert "legacy_scan_work_requires_resolution" in source
    assert "retired_security_contract_environment_detected" in source
    assert "_reject_retired_security_environment()" in source


def test_shared_peripheral_default_is_excluded_from_cryptographic_uniqueness_gate() -> None:
    source = read("backend/app/deployment/bootstrap.py")
    validator = source.split("cryptographic = [", 1)[1].split("return self", 1)[0]
    assert "app_encryption_key" in validator
    assert "oidc_client_secret" in validator
    assert "keycloak_sync_client_secret" in validator
    assert "s3_secret_access_key" not in validator
    assert "opensearch_password" not in validator
    assert "neo4j_password" not in validator
    assert "keycloak_bootstrap_admin_password" not in validator
    assert '"P@ssw0rd" in populated' in validator


def test_bundled_realm_retires_totp_action_for_every_existing_user() -> None:
    source = read("backend/app/deployment/bootstrap.py")
    assert "def remove_totp_required_actions" in source
    assert 'users?first={first}&max={page_size}' in source
    assert 'if "CONFIGURE_TOTP" not in actions' in source
    assert 'action for action in actions if action != "CONFIGURE_TOTP"' in source
    assert "self.remove_totp_required_actions()" in source


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
@pytest.mark.parametrize("removed_root", ("vault", "clamav"))
def test_helm_rejects_retired_security_service_values(removed_root: str) -> None:
    result = subprocess.run(
        [
            "helm",
            "template",
            "nomosmart",
            str(CHART),
            "--set",
            f"{removed_root}.enabled=true",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert f"at '/{removed_root}': false schema" in result.stderr
