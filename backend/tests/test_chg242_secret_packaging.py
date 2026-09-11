from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import string
import subprocess
import sys

import pytest
import yaml

from app.core.config import Settings
from app.deployment.bootstrap import DeploymentBootstrapSettings


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SCRIPT = REPOSITORY_ROOT / "deploy" / "package" / "nomosmart_package.py"


def _assert_strong_opensearch_passwords(values: dict[str, str]) -> None:
    passwords = {
        values["opensearch_admin_password"],
        values["opensearch_service_password"],
    }
    assert len(passwords) == 2
    for value in passwords:
        assert len(value) == 64
        assert any(character in string.ascii_lowercase for character in value)
        assert any(character in string.ascii_uppercase for character in value)
        assert any(character in string.digits for character in value)
        assert "-" in value
        assert value != "P@ssw0rd"


def _module():
    spec = importlib.util.spec_from_file_location("nomosmart_package_chg242", PACKAGE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(module, output: Path, *, profile: str, app_env: str):
    arguments = [
            "init",
            "--target",
            "compose",
            "--output-dir",
            str(output),
            "--profile",
            profile,
            "--app-env",
            app_env,
            "--no-display",
        ]
    if profile == "production":
        arguments.extend(
            [
                "--break-glass-runbook-uri",
                "https://runbooks.example.test/nomosmart/break-glass",
                "--break-glass-alerting-evidence",
                "test-alert-route",
            ]
        )
    return module._parser().parse_args(arguments)


def _secret_values(current: Path, manifest: dict[str, object]) -> dict[str, str]:
    rows = manifest["secrets"]
    assert isinstance(rows, dict)
    return {name: (current / str(details["file"])).read_text(encoding="utf-8").strip() for name, details in rows.items()}


def test_factory_init_is_private_unique_idempotent_and_redacted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _module()
    output = tmp_path / "generated"
    args = _args(module, output, profile="factory_acceptance", app_env="development")

    assert module.init_package(args) == 0
    current = output / "current"
    manifest = json.loads((current / "manifest.json").read_text(encoding="utf-8"))
    values = _secret_values(current, manifest)

    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE(current.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in current.rglob("*") if path.is_dir())
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in current.rglob("*") if path.is_file())
    assert all(
        not (current / str(details["file"])).read_bytes().endswith(b"\n")
        for details in manifest["secrets"].values()
    )
    assert values["break_glass_initial_password"] == "nomosmart"
    assert all(
        values[name] == "P@ssw0rd"
        for name in module.KNOWN_PERIPHERAL_SECRET_NAMES
        if name not in {"opensearch_admin_password", "opensearch_service_password"}
    )
    _assert_strong_opensearch_passwords(values)
    cryptographic_names = {
        "app_encryption_key",
        "oidc_client_secret",
        "keycloak_sync_client_secret",
    }
    assert all(len(values[name]) == 64 for name in cryptographic_names)
    assert len({values[name] for name in cryptographic_names}) == len(cryptographic_names)
    assert set(manifest["usernames"].values()) <= {
        "nomosmart",
        "postgres",
        "admin",
        "neo4j",
        "nomosmart-sync",
    }
    assert manifest["credential_mode"] == "first_use_fixed"
    assert manifest["certificates"]["active_source"] == "bundled_self_signed"
    assert "DNS:nomosmart.local" in manifest["certificates"]["active"]["edge"]["subject_alt_name"]

    first_output = capsys.readouterr().out
    assert "nomosmart" not in first_output
    assert module.init_package(args) == 0
    second_output = capsys.readouterr().out
    assert "already_initialized" in second_output
    assert values["postgres_admin_password"] not in second_output


def test_production_uses_fixed_first_use_break_glass_and_rejects_factory_profile_mismatch(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "generated"
    production = _args(module, output, profile="production", app_env="production")
    assert module.init_package(production) == 0
    manifest = json.loads((output / "current" / "manifest.json").read_text(encoding="utf-8"))
    values = _secret_values(output / "current", manifest)
    assert values["break_glass_initial_password"] == "nomosmart"
    assert manifest["credential_mode"] == "first_use_fixed"
    _assert_strong_opensearch_passwords(values)

    mismatch = _args(module, tmp_path / "invalid", profile="factory_acceptance", app_env="production")
    with pytest.raises(module.PackageError, match="factory acceptance requires"):
        module.init_package(mismatch)


def test_rotate_preserves_previous_generation_and_never_emits_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _module()
    output = tmp_path / "generated"
    init_args = _args(module, output, profile="production", app_env="production")
    module.init_package(init_args)
    first = json.loads((output / "current" / "manifest.json").read_text(encoding="utf-8"))
    first_values = _secret_values(output / "current", first)
    capsys.readouterr()

    rotate_args = module._parser().parse_args(
        [
            "rotate",
            "--target",
            "compose",
            "--output-dir",
            str(output),
            "--profile",
            "production",
            "--app-env",
            "production",
            "--no-display",
            "--break-glass-runbook-uri",
            "https://runbooks.example.test/nomosmart/break-glass",
            "--break-glass-alerting-evidence",
            "test-alert-route",
        ]
    )
    assert module.rotate_package(rotate_args) == 0
    second = json.loads((output / "current" / "manifest.json").read_text(encoding="utf-8"))
    second_values = _secret_values(output / "current", second)
    emitted = capsys.readouterr().out

    assert first["generation_id"] != second["generation_id"]
    assert second["credential_mode"] == "rotation_random"
    assert second_values["break_glass_initial_password"] != "nomosmart"
    assert len(second_values["break_glass_initial_password"]) == 64
    assert (output / "previous" / str(first["generation_id"]) / "manifest.json").is_file()
    assert not any(value in emitted for value in first_values.values())


def test_settings_load_secret_file_without_exposing_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "app_encryption_key"
    secret.write_text("a" * 64 + "\n", encoding="utf-8")
    secret.chmod(0o600)
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("APP_ENCRYPTION_KEY_FILE", str(secret))
    monkeypatch.setenv("APP_ENV", "development")

    settings = Settings(_env_file=None)
    assert settings.app_encryption_key.get_secret_value() == "a" * 64
    assert "a" * 64 not in repr(settings)


def test_production_secret_file_rejects_conflict_symlink_and_broad_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "app_encryption_key"
    secret.write_text("a" * 64 + "\n", encoding="utf-8")
    secret.chmod(0o644)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_ENCRYPTION_KEY_FILE", str(secret))
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValueError, match="must not grant group or other permissions"):
        Settings(_env_file=None)

    secret.chmod(0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(secret)
    monkeypatch.setenv("APP_ENCRYPTION_KEY_FILE", str(alias))
    with pytest.raises(ValueError, match="regular file"):
        Settings(_env_file=None)

    monkeypatch.setenv("APP_ENCRYPTION_KEY_FILE", str(secret))
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "b" * 64)
    with pytest.raises(ValueError, match="APP_ENCRYPTION_KEY and APP_ENCRYPTION_KEY_FILE conflict"):
        Settings(_env_file=None)


def test_helm_package_uses_existing_secret_compatible_keys(tmp_path: Path) -> None:
    module = _module()
    args = module._parser().parse_args(
        [
            "init",
            "--target",
            "helm",
            "--output-dir",
            str(tmp_path / "helm"),
            "--profile",
            "production",
            "--app-env",
            "production",
            "--no-display",
        ]
    )
    assert module.init_package(args) == 0
    current = tmp_path / "helm" / "current"
    for key in (
        "APP_ENCRYPTION_KEY",
        "DATABASE_URL",
        "DATABASE_MIGRATION_PASSWORD",
        "REDIS_URL",
        "OPENSEARCH_ADMIN_PASSWORD",
        "OPENSEARCH_PASSWORD",
        "NEO4J_ADMIN_PASSWORD",
        "NEO4J_PASSWORD",
        "BREAK_GLASS_INITIAL_PASSWORD",
    ):
        assert (current / key).is_file()
        assert stat.S_IMODE((current / key).stat().st_mode) == 0o600
    assert (current / "tls/active/edge.crt").is_file()
    assert (current / "tls/bundled/opensearch-ca.crt").is_file()
    assert "@nomosmart-postgresql-rw:5432/nomosmart" in (current / "DATABASE_URL").read_text(encoding="utf-8")
    assert "@nomosmart-redis-sentinel:26379/0" in (current / "REDIS_URL").read_text(encoding="utf-8")
    assert "@nomosmart-redis-sentinel:26379/0" in (current / "CELERY_BROKER_URL").read_text(encoding="utf-8")
    assert "@nomosmart-redis-sentinel:26379/1" in (current / "CELERY_RESULT_BACKEND").read_text(encoding="utf-8")
    assert (current / "tls/active/postgresql-replication.crt").is_file()
    assert (current / "tls/active/redis-ca.crt").is_file()
    helm_manifest = json.loads((current / "manifest.json").read_text(encoding="utf-8"))
    assert "DNS:nomosmart-rustfs" in helm_manifest["certificates"]["active"]["rustfs"]["subject_alt_name"]
    assert "DNS:nomosmart-opensearch" in helm_manifest["certificates"]["active"]["opensearch"]["subject_alt_name"]


def test_tls_package_is_ca_verified_san_correct_and_operator_material_takes_precedence(tmp_path: Path) -> None:
    module = _module()
    first_output = tmp_path / "first"
    assert module.init_package(_args(module, first_output, profile="production", app_env="production")) == 0
    first_active = first_output / "current/tls/active"
    for component, hostname in (("edge", "nomosmart.local"), ("rustfs", "rustfs"), ("opensearch", "opensearch")):
        verified = subprocess.run(
            ["openssl", "verify", "-CAfile", str(first_active / f"{component}-ca.crt"), str(first_active / f"{component}.crt")],
            check=True,
            capture_output=True,
            text=True,
        )
        assert verified.stdout.strip().endswith(": OK")
        san = subprocess.run(
            ["openssl", "x509", "-in", str(first_active / f"{component}.crt"), "-noout", "-ext", "subjectAltName"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert f"DNS:{hostname}" in san

    trusted = tmp_path / "trusted"
    shutil.copytree(first_active, trusted)
    second_output = tmp_path / "second"
    args = _args(module, second_output, profile="production", app_env="production")
    args.trusted_tls_dir = str(trusted)
    assert module.init_package(args) == 0
    manifest = json.loads((second_output / "current/manifest.json").read_text(encoding="utf-8"))
    assert manifest["certificates"]["active_source"] == "operator_provided"
    assert (second_output / "current/tls/bundled/edge.crt").is_file()
    assert (second_output / "current/tls/operator/edge.crt").read_bytes() == (second_output / "current/tls/active/edge.crt").read_bytes()


def test_compose_limits_admin_secrets_to_bootstrap_and_finalize() -> None:
    compose = yaml.safe_load((REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    runtime = set(compose["services"]["backend"]["secrets"])
    bootstrap = set(compose["services"]["deployment-bootstrap"]["secrets"])
    assert {"opensearch_admin_password", "neo4j_admin_password"}.isdisjoint(runtime)
    assert {"opensearch_admin_password", "neo4j_admin_password"} <= bootstrap
    assert compose["services"]["deployment-finalize"]["profiles"] == ["finalize"]
    assert compose["services"]["rustfs"]["environment"]["NOMOSMART_SECRET_EXPORTS"]
    for name in ("backend", "celery-worker", "celery-beat", "deployment-bootstrap", "deployment-finalize"):
        assert compose["services"][name]["user"] == "0:0"
        assert compose["services"][name]["entrypoint"] == ["/opt/nomosmart/secret-env-entrypoint.sh"]
    assert compose["services"]["backend"]["environment"]["NOMOSMART_RUN_AS"] == "10001:10001"
    assert compose["services"]["backend"]["command"] == ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
    assert "~* &*" in " ".join(compose["services"]["redis"]["command"])
    assert "celerybeat-schedule.db" in " ".join(compose["services"]["celery-beat"]["healthcheck"]["test"])
    assert set(compose["services"]["edge"]["ports"]) == {
        "${EDGE_HOST_IP:-127.0.0.1}:${EDGE_HTTP_PORT:-80}:80",
        "${EDGE_HOST_IP:-127.0.0.1}:${EDGE_HTTPS_PORT:-443}:443",
    }
    assert compose["services"]["deployment-bootstrap"]["environment"]["NEO4J_COMMUNITY_ADMIN_EQUIVALENT_ACCEPTED"]


def test_factory_profile_is_guarded_by_development_environment() -> None:
    with pytest.raises(ValueError, match="factory_acceptance requires APP_ENV=development"):
        DeploymentBootstrapSettings(
            _env_file=None,
            app_env="test",
            deployment_phase="factory_acceptance",
            break_glass_initial_password="nomosmart",
        )


def test_first_use_finalize_requires_password_login_and_disables_sessions() -> None:
    bootstrap = (REPOSITORY_ROOT / "backend/app/deployment/bootstrap.py").read_text(encoding="utf-8")
    keycloak = (REPOSITORY_ROOT / "backend/app/integrations/keycloak.py").read_text(encoding="utf-8")
    auth = (REPOSITORY_ROOT / "backend/app/api/routes/auth.py").read_text(encoding="utf-8")
    assert "break_glass_login_evidence_missing" in bootstrap
    assert "non_break_glass_system_admin_missing" in bootstrap
    assert "verify_break_glass_onboarding_complete" in keycloak
    assert "allow_disabled=True" in bootstrap
    assert 'POST", f"users/{user_id}/logout"' in keycloak
    assert 'action="auth.login.success"' in auth


def test_break_glass_profile_is_complete_without_an_extra_verify_profile_action() -> None:
    keycloak = (REPOSITORY_ROOT / "backend/app/integrations/keycloak.py").read_text(encoding="utf-8")
    assert 'BREAK_GLASS_DEFAULT_EMAIL = "nomosmart@nomosmart.local"' in keycloak
    assert 'BREAK_GLASS_DEFAULT_FIRST_NAME = "NomoSmart"' in keycloak
    assert 'BREAK_GLASS_DEFAULT_LAST_NAME = "Administrator"' in keycloak
    for field in (
        '"email": BREAK_GLASS_DEFAULT_EMAIL',
        '"emailVerified": True',
        '"firstName": BREAK_GLASS_DEFAULT_FIRST_NAME',
        '"lastName": BREAK_GLASS_DEFAULT_LAST_NAME',
    ):
        assert field in keycloak
    assert "if required_actions:" in keycloak
    assert 'required_actions & {"UPDATE_PASSWORD", "CONFIGURE_TOTP"}' not in keycloak


def test_neo4j_service_identity_ensure_is_idempotent() -> None:
    bootstrap = (REPOSITORY_ROOT / "backend/app/deployment/bootstrap.py").read_text(encoding="utf-8")
    assert "service_driver.verify_connectivity()" in bootstrap
    assert "except AuthError:" in bootstrap
    assert "neo4j_least_privilege_requires_enterprise" not in bootstrap
    assert "neo4j_community_admin_equivalent_risk_not_accepted" in bootstrap
    assert "community_admin_equivalent_accepted" in bootstrap


def test_keycloak_management_identity_can_complete_idempotent_bootstrap() -> None:
    bootstrap = (REPOSITORY_ROOT / "backend/app/deployment/bootstrap.py").read_text(encoding="utf-8")
    assert '"manage-users"' in bootstrap
    assert '"manage-clients"' in bootstrap
    assert bootstrap.index("_reconcile_identity_database(settings, client=identity_client)") < bootstrap.index(
        "manager.disable_bootstrap_admin()"
    )


def test_compose_preflight_treats_missing_minikube_as_stopped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()

    def fake_run(command, *args, **kwargs):
        if command[0] == "minikube":
            raise FileNotFoundError(command[0])
        if command[0] == "lsof":
            return subprocess.CompletedProcess(command, 1, "", "")
        raise AssertionError(command)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_local_host_mapping", lambda *_args, **_kwargs: True)
    args = module._parser().parse_args(["preflight", "--runtime", "compose"])

    assert module.preflight_package(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"
    assert payload["runtime"] == "compose"
    assert payload["other_runtime"] == "stopped"
