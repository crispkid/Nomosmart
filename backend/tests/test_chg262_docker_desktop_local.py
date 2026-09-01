from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import string
import subprocess
import sys

import pytest
import yaml


REPOSITORY = Path(__file__).resolve().parents[2]
CHART = REPOSITORY / "deploy" / "helm" / "nomosmart"
LOCAL_VALUES = CHART / "values-docker-desktop.yaml"
PACKAGE_SCRIPT = REPOSITORY / "deploy" / "package" / "nomosmart_package.py"
MIGRATION_042 = REPOSITORY / "sql" / "migrations" / "V042__cloudnativepg_application_privileges.sql"

TEST_RANDOM_VALUES = {
    "APP_ENCRYPTION_KEY": "a" * 64,
    "OIDC_CLIENT_SECRET": "b" * 64,
    "KEYCLOAK_SYNC_CLIENT_SECRET": "c" * 64,
    "OPENSEARCH_ADMIN_PASSWORD": "Local-Admin-Strong-2026-Alpha",
    "OPENSEARCH_PASSWORD": "Local-Service-Strong-2026-Beta",
}


def _render(*arguments: str) -> subprocess.CompletedProcess[str]:
    command = [
        "helm",
        "template",
        "nomosmart-local",
        str(CHART),
        "--namespace",
        "nomosmart",
        "--values",
        str(LOCAL_VALUES),
    ]
    for key, value in TEST_RANDOM_VALUES.items():
        command.extend(("--set-string", f"secrets.data.{key}={value}"))
    command.extend(arguments)
    return subprocess.run(
        command,
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )


def _documents(*arguments: str) -> list[dict[str, object]]:
    result = _render(*arguments)
    assert result.returncode == 0, result.stderr
    return [row for row in yaml.safe_load_all(result.stdout) if isinstance(row, dict)]


def _named(documents: list[dict[str, object]], kind: str) -> dict[str, dict[str, object]]:
    return {
        str(row["metadata"]["name"]): row
        for row in documents
        if row.get("kind") == kind
    }


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_chg262_local_render_has_redis_ha_keycloak_local_cache_and_seven_pvcs() -> None:
    documents = _documents()
    statefulsets = _named(documents, "StatefulSet")
    deployments = _named(documents, "Deployment")
    redis_headless_fqdn = (
        "nomosmart-local-redis-headless.nomosmart.svc.cluster.local"
    )

    redis = statefulsets["nomosmart-local-redis"]
    assert redis["spec"]["replicas"] == 3
    sentinel = deployments["nomosmart-local-redis-sentinel"]
    assert sentinel["spec"]["replicas"] == 3
    sentinel_script = sentinel["spec"]["template"]["spec"]["containers"][0]["args"][0]
    assert (
        "sentinel monitor nomosmart nomosmart-local-redis-0."
        f"{redis_headless_fqdn} 6379 2"
    ) in sentinel_script
    redis_spread = redis["spec"]["template"]["spec"]["affinity"]["podAntiAffinity"]
    assert redis_spread["requiredDuringSchedulingIgnoredDuringExecution"][0]["topologyKey"] == "kubernetes.io/hostname"
    sentinel_spread = sentinel["spec"]["template"]["spec"]["affinity"]["podAntiAffinity"]
    assert sentinel_spread["requiredDuringSchedulingIgnoredDuringExecution"][0]["topologyKey"] == "kubernetes.io/hostname"
    expected_toleration = {
        "key": "node-role.kubernetes.io/control-plane",
        "operator": "Exists",
        "effect": "NoSchedule",
    }
    assert expected_toleration in redis["spec"]["template"]["spec"]["tolerations"]
    assert expected_toleration in sentinel["spec"]["template"]["spec"]["tolerations"]
    redis_container = redis["spec"]["template"]["spec"]["containers"][0]
    redis_script = redis_container["args"][0]
    assert redis_script.count("user %s on") == 1
    assert "Duplicate user" not in redis_script
    assert "appendonly yes" in redis_script
    assert "tls-replication yes" in redis_script
    assert f"replica-announce-ip $POD_NAME.{redis_headless_fqdn}" in redis_script
    assert "replicaof %s-0.%s-headless.nomosmart.svc.cluster.local" in redis_script
    redis_env = {row["name"]: row for row in redis_container["env"]}
    assert redis_env["REDIS_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"] == "REDIS_PASSWORD"
    assert redis_env["REDIS_REPLICATION_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"] == "REDIS_PASSWORD"
    assert redis_env["REDIS_SENTINEL_PASSWORD"]["valueFrom"]["secretKeyRef"]["key"] == "REDIS_PASSWORD"

    keycloak = deployments["nomosmart-local-keycloak"]
    assert keycloak["spec"]["replicas"] == 1
    keycloak_spec = keycloak["spec"]["template"]["spec"]
    assert "affinity" not in keycloak_spec
    keycloak_container = keycloak_spec["containers"][0]
    keycloak_env = {row["name"]: row for row in keycloak_container["env"]}
    assert keycloak_env["KC_CACHE"]["value"] == "local"
    assert keycloak_env["KC_HTTP_MANAGEMENT_RELATIVE_PATH"]["value"] == "/"
    assert "KC_CACHE_STACK" not in keycloak_env
    assert "KC_SPI_CACHE_EMBEDDED__DEFAULT__CLUSTER_NAME" not in keycloak_env
    assert {row["name"] for row in keycloak_container["ports"]} == {"http", "management"}

    application_deployments = _named(
        _documents("--set", "installer.deploymentStage=application"),
        "Deployment",
    )
    beat = application_deployments["nomosmart-local-beat"]
    assert beat["spec"]["template"]["spec"]["initContainers"][0]["name"] == (
        "deployment-evidence"
    )

    ingresses = _named(documents, "Ingress")
    public_ingress = ingresses["nomosmart-local"]
    assert public_ingress["metadata"]["annotations"][
        "nginx.ingress.kubernetes.io/whitelist-source-range"
    ] == "127.0.0.1/32,10.244.0.0/16"
    admin_ingress = ingresses["nomosmart-local-keycloak-admin"]
    assert admin_ingress["metadata"]["annotations"][
        "nginx.ingress.kubernetes.io/whitelist-source-range"
    ] == "127.0.0.1/32,10.244.0.0/16"

    opensearch = statefulsets["nomosmart-local-opensearch"]
    opensearch_env = {
        row["name"]: row
        for row in opensearch["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert opensearch_env["node.roles"]["value"] == (
        "cluster_manager,data,ingest,remote_cluster_client"
    )

    stateful_with_claims = [
        row
        for row in statefulsets.values()
        if row["spec"].get("volumeClaimTemplates")
    ]
    expected_claims = sum(int(row["spec"]["replicas"]) for row in stateful_with_claims)
    assert expected_claims == 7
    assert redis["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"] == "2Gi"

    budgets = _named(documents, "PodDisruptionBudget")
    assert budgets["nomosmart-local-redis"]["spec"]["minAvailable"] == 2
    assert budgets["nomosmart-local-redis-sentinel"]["spec"]["minAvailable"] == 2

    secrets = _named(documents, "Secret")
    runtime = secrets["nomosmart-local-secrets"]
    data = runtime["stringData"]
    fixed_keys = {
        "BREAK_GLASS_INITIAL_PASSWORD",
        "KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "S3_SECRET_ACCESS_KEY",
    }
    assert {data[key] for key in fixed_keys} == {"P@ssw0rd"}
    assert data["OPENSEARCH_ADMIN_PASSWORD"] == TEST_RANDOM_VALUES["OPENSEARCH_ADMIN_PASSWORD"]
    assert data["OPENSEARCH_PASSWORD"] == TEST_RANDOM_VALUES["OPENSEARCH_PASSWORD"]
    assert data["OPENSEARCH_ADMIN_PASSWORD"] != data["OPENSEARCH_PASSWORD"]
    assert data["DATABASE_URL"] == (
        "postgresql+psycopg2://nomosmart:P%40ssw0rd@"
        "nomosmart-local-postgresql:5432/nomosmart"
    )
    for key in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        assert "nomosmart:P%40ssw0rd@" in data[key]
        assert "nomosmart:P@ssw0rd@" not in data[key]

    config = _named(documents, "ConfigMap")["nomosmart-local-config"]["data"]
    assert config["LOCAL_DEVELOPMENT_PLATFORM"] == "docker-desktop"
    assert config["KNOWN_LOCAL_CREDENTIAL_RISK_ACCEPTED"] == "true"

    workloads = [
        row
        for row in documents
        if row.get("kind") in {"Deployment", "StatefulSet", "Job", "ConfigMap"}
    ]
    workload_yaml = yaml.safe_dump_all(workloads)
    assert "P@ssw0rd" not in workload_yaml
    for value in TEST_RANDOM_VALUES.values():
        assert value not in workload_yaml


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_chg262_distinct_redis_identities_keep_three_acl_records() -> None:
    result = _render(
        "--set",
        "localDevelopment.enabled=false",
        "--set-string",
        "redis.auth.username=app-user",
        "--set-string",
        "redis.auth.replicationUsername=replication-user",
        "--set-string",
        "redis.auth.sentinelUsername=sentinel-user",
    )
    assert result.returncode == 0, result.stderr
    documents = [row for row in yaml.safe_load_all(result.stdout) if isinstance(row, dict)]
    redis = _named(documents, "StatefulSet")["nomosmart-local-redis"]
    redis_script = redis["spec"]["template"]["spec"]["containers"][0]["args"][0]
    assert redis_script.count("user %s on") == 3


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
@pytest.mark.parametrize(
    "arguments",
    [
        ("--set", "backend.env.APP_ENV=production"),
        ("--set", "deploymentProfile=external-services"),
        ("--set", "redis.cluster.sentinelQuorum=1"),
        ("--set", "keycloak.cluster.replicas=2"),
        ("--set", "keycloak.cache.mode=ispn"),
    ],
)
def test_chg262_local_profile_rejects_unsafe_or_wrong_topology(arguments: tuple[str, str]) -> None:
    result = _render(*arguments)
    assert result.returncode != 0
    assert "P@ssw0rd" not in result.stderr
    assert TEST_RANDOM_VALUES["OPENSEARCH_ADMIN_PASSWORD"] not in result.stderr
    assert TEST_RANDOM_VALUES["OPENSEARCH_PASSWORD"] not in result.stderr


def _package_module():
    spec = importlib.util.spec_from_file_location("nomosmart_package_chg262", PACKAGE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_chg262_package_generates_strong_distinct_opensearch_local_passwords() -> None:
    module = _package_module()
    values = module._build_values(
        "factory_acceptance",
        "helm",
        first_use=True,
        helm_fullname="nomosmart-local",
        docker_desktop_local=True,
    )

    assert values["break_glass_initial_password"] == "P@ssw0rd"
    assert all(
        values[name] == "P@ssw0rd"
        for name in module.KNOWN_PERIPHERAL_SECRET_NAMES
        if name not in {"opensearch_admin_password", "opensearch_service_password"}
    )
    opensearch_values = {
        values["opensearch_admin_password"],
        values["opensearch_service_password"],
    }
    assert len(opensearch_values) == 2
    for value in opensearch_values:
        assert len(value) == 64
        assert any(character in string.ascii_lowercase for character in value)
        assert any(character in string.ascii_uppercase for character in value)
        assert any(character in string.digits for character in value)
        assert "-" in value
    assert "nomosmart:P%40ssw0rd@" in values["database_url"]
    assert "nomosmart:P%40ssw0rd@" in values["redis_url"]
    assert "nomosmart:P%40ssw0rd@" in values["celery_broker_url"]
    assert "nomosmart:P%40ssw0rd@" in values["celery_result_backend"]


def test_chg262_package_flag_is_scoped_to_fresh_local_helm(tmp_path: Path) -> None:
    module = _package_module()
    invalid = module._parser().parse_args(
        [
            "init",
            "--target",
            "compose",
            "--output-dir",
            str(tmp_path / "invalid"),
            "--profile",
            "factory_acceptance",
            "--app-env",
            "development",
            "--no-display",
            "--docker-desktop-local",
        ]
    )
    with pytest.raises(module.PackageError, match="only valid for a fresh Helm"):
        module.init_package(invalid)


def test_chg262_migration_default_privileges_follow_the_actual_executor() -> None:
    sql = MIGRATION_042.read_text(encoding="utf-8")

    assert sql.count("ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER") == 2
    assert 'FOR ROLE "nomosmart-migration"' not in sql


def test_chg262_bootstrap_accepts_fixed_password_only_for_approved_local_profile() -> None:
    backend_root = str(REPOSITORY / "backend")
    sys.path.insert(0, backend_root)
    try:
        from app.deployment.bootstrap import DeploymentBootstrapSettings
    finally:
        sys.path.remove(backend_root)

    settings = DeploymentBootstrapSettings(
        _env_file=None,
        app_env="development",
        deployment_phase="factory_acceptance",
        local_development_platform="docker-desktop",
        known_local_credential_risk_accepted=True,
        break_glass_initial_password="P@ssw0rd",
    )
    assert settings.local_development_platform == "docker-desktop"

    with pytest.raises(ValueError, match="explicit risk acceptance"):
        DeploymentBootstrapSettings(
            _env_file=None,
            app_env="development",
            deployment_phase="factory_acceptance",
            local_development_platform="docker-desktop",
            known_local_credential_risk_accepted=False,
            break_glass_initial_password="P@ssw0rd",
        )

    with pytest.raises(ValueError, match="approved deployment profile"):
        DeploymentBootstrapSettings(
            _env_file=None,
            app_env="development",
            deployment_phase="factory_acceptance",
            break_glass_initial_password="P@ssw0rd",
        )
