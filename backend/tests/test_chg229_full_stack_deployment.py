from __future__ import annotations

import json
from pathlib import Path
import shutil
import ssl
import subprocess

import certifi
import pytest
import yaml

from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy" / "helm" / "nomosmart"
PERIPHERALS = ("postgresql", "redis", "rustfs", "opensearch", "neo4j", "keycloak")


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_compose_defaults_to_the_complete_internal_stack_and_only_edge_publishes_ports() -> None:
    compose = yaml.safe_load(read("docker-compose.yml"))
    services = compose["services"]
    required = {
        "edge",
        "frontend",
        "backend",
        "celery-worker",
        "celery-beat",
        "migration",
        "deployment-bootstrap",
        *PERIPHERALS,
    }
    assert required <= services.keys()
    assert set(services["edge"]["ports"]) == {
        "${EDGE_HOST_IP:-127.0.0.1}:${EDGE_HTTP_PORT:-80}:80",
        "${EDGE_HOST_IP:-127.0.0.1}:${EDGE_HTTPS_PORT:-443}:443",
    }
    assert all("ports" not in service for name, service in services.items() if name not in {"edge", "debug-ports"})
    assert services["debug-ports"]["profiles"] == ["debug"]
    assert all(binding.startswith("127.0.0.1:") for binding in services["debug-ports"]["ports"])
    for name in PERIPHERALS:
        assert services[name]["profiles"] == [name]
        assert services["backend"]["depends_on"][name]["required"] is False
    env = read("deploy/docker/nomosmart.env.example")
    assert "COMPOSE_PROFILES=postgresql,redis,rustfs,opensearch,neo4j,keycloak" in env
    assert "RUSTFS_TLS_PATH" in read("docker-compose.yml")
    assert services["postgresql"]["volumes"][0] == "postgres_data:/var/lib/postgresql"
    assert services["postgresql"]["build"]["dockerfile"] == "postgresql/Dockerfile"
    assert services["postgresql"]["environment"]["POSTGRES_USER"] == "${POSTGRES_ADMIN_USER:-postgres}"
    assert services["postgresql"]["environment"]["NOMOSMART_DB_USER"] == "${POSTGRES_USER:-nomosmart}"
    assert "CREATE ROLE %I LOGIN PASSWORD %L" in read("deploy/docker/postgresql-init.sh")
    postgresql_image = read("deploy/postgresql/Dockerfile")
    assert "COPY --chmod=0555 docker/postgresql-init.sh" in postgresql_image
    assert "NOMOSMART_REMAP_SECRETS=1" in postgresql_image
    assert "secret-env-entrypoint.sh" in postgresql_image
    assert 'CMD ["postgres"]' in postgresql_image
    rustfs_health = " ".join(services["rustfs"]["healthcheck"]["test"])
    assert "curl --cacert /opt/rustfs-tls/rustfs_ca.pem" in rustfs_health
    assert "--resolve rustfs:9000:127.0.0.1" in rustfs_health
    assert "wget --ca-certificate" not in rustfs_health
    runbook = read("deploy/README.md")
    assert "--profile debug up -d debug-ports" in runbook
    assert "127.0.0.1" in runbook


def test_helm_defaults_every_peripheral_to_bundled_with_pinned_images_and_persistence() -> None:
    values = yaml.safe_load(read("deploy/helm/nomosmart/values.yaml"))
    for name in PERIPHERALS:
        component = values[name]
        assert component["mode"] == "bundled"
        assert component["image"]["tag"] not in {"latest", "stable", "main", "master"}
        assert component["external"]
    for name in ("postgresql", "redis", "rustfs", "opensearch", "neo4j"):
        assert values[name]["persistence"]["enabled"] is True
        assert values[name]["persistence"]["retain"] is True
    assert values["global"]["publicOrigin"].startswith("https://")
    assert values["rustfs"]["tls"]["secretName"]
    assert values["rustfs"]["image"]["repository"] == "nomosmart/rustfs"
    assert values["opensearch"]["tls"]["secretName"]
    opensearch = read("deploy/helm/nomosmart/templates/opensearch.yaml")
    assert '--resolve {{ $fullname }}-opensearch:' in opensearch
    assert ":127.0.0.1" in opensearch
    assert values["podSecurityContext"] | {"seccompProfile": {"type": "RuntimeDefault"}} == {
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "runAsGroup": 10001,
        "fsGroup": 10001,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    assert not (CHART / "templates" / "clamav.yaml").exists()
    bootstrap_init = read("deploy/helm/nomosmart/templates/_bootstrap-init.tpl")
    assert 'ne .Values.bootstrap.deploymentPhase "operational"' in bootstrap_init
    assert "key: {{ .Values.bootstrap.breakGlassPasswordKey }}" in bootstrap_init
    assert values["acceptedRisks"] == {
        "neo4jCommunityAdminEquivalent": True,
        "changeId": "CHG-243",
    }
    assert "curl --cacert /opt/rustfs-tls/rustfs_ca.pem" in read("deploy/helm/nomosmart/templates/rustfs.yaml")
    assert "ca.crt, path: rustfs_ca.pem" in read("deploy/helm/nomosmart/templates/rustfs.yaml")


def test_helm_schema_rejects_ambiguous_modes_and_floating_tags() -> None:
    schema = json.loads(read("deploy/helm/nomosmart/values.schema.json"))
    component_mode = schema["definitions"]["component"]["properties"]["mode"]
    image_tag = schema["definitions"]["image"]["properties"]["tag"]
    assert component_mode["enum"] == ["bundled", "external"]
    assert set(image_tag["not"]["enum"]) == {"latest", "stable", "main", "master"}
    for name in PERIPHERALS:
        expected = "#/definitions/opensearch" if name == "opensearch" else "#/definitions/component"
        assert schema["properties"][name]["$ref"] == expected


def test_migration_image_uses_the_verified_current_flyway_release() -> None:
    assert "FROM flyway/flyway:13.0.0-alpine" in read("deploy/migrations/Dockerfile")
    assert '"flyway/flyway:13.0.0-alpine"' in read("backend/scripts/migration_live_acceptance.py")


def test_backend_image_uses_the_frozen_dependency_lock() -> None:
    dockerfile = read("backend/Dockerfile")
    assert "COPY pyproject.toml uv.lock ./" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "pip install ." not in dockerfile
    assert "useradd --uid 10001" in dockerfile
    assert "USER nomosmart" in dockerfile


def test_frontend_and_migration_images_use_the_chart_numeric_non_root_identity() -> None:
    assert "adduser -S -u 10001" in read("frontend/Dockerfile")
    migration = read("deploy/migrations/Dockerfile")
    assert "adduser -S -D -h /home/nomosmart -u 10001" in migration
    assert "NOMOSMART_RUN_AS=10001:10001" in migration
    assert "USER 0" in migration
    assert "apk add --no-cache su-exec" in migration
    rustfs = read("deploy/rustfs/Dockerfile")
    assert "NOMOSMART_RUN_AS=10001:10001" in rustfs
    assert "USER 0" in rustfs
    assert "apk add --no-cache su-exec" in rustfs
    entrypoint = read("deploy/docker/secret-env-entrypoint.sh")
    assert "su-exec" in entrypoint
    assert "--reuid" in entrypoint
    assert "NOMOSMART_REMAP_SECRETS" in entrypoint
    assert "previous_umask" in entrypoint
    assert "/run/nomosmart/secrets" in entrypoint


def test_public_oidc_issuer_is_separate_from_internal_transport() -> None:
    compose = yaml.safe_load(read("docker-compose.yml"))
    frontend_env = compose["services"]["frontend"]["environment"]
    assert frontend_env["FRONTEND_OIDC_ISSUER_URL"].endswith("https://nomosmart.local/identity/realms/nomosmart}")
    assert frontend_env["FRONTEND_OIDC_INTERNAL_ISSUER_URL"].endswith("http://keycloak:8080/identity/realms/nomosmart}")
    settings = Settings(
        _env_file=None,
        oidc_issuer_url="https://nomosmart.example.test/identity/realms/nomosmart",
        oidc_discovery_url="http://keycloak:8080/identity/realms/nomosmart/.well-known/openid-configuration",
        oidc_jwks_url="http://keycloak:8080/identity/realms/nomosmart/protocol/openid-connect/certs",
        keycloak_admin_api_url="https://nomosmart.example.test/identity",
        keycloak_admin_internal_url="http://keycloak:8080/identity",
    )
    assert settings.oidc_issuer_url.startswith("https://")
    assert settings.oidc_discovery_endpoint.startswith("http://keycloak:")
    assert settings.oidc_jwks_endpoint.startswith("http://keycloak:")
    assert settings.keycloak_admin_endpoint == "http://keycloak:8080/identity"


def test_internal_service_ca_paths_create_verified_tls_contexts() -> None:
    settings = Settings(
        _env_file=None,
        s3_verify_tls=True,
        s3_ca_cert_path=certifi.where(),
        opensearch_verify_tls=True,
        opensearch_ca_cert_path=certifi.where(),
    )
    assert isinstance(settings.s3_httpx_verify, ssl.SSLContext)
    assert isinstance(settings.opensearch_httpx_verify, ssl.SSLContext)
    assert settings.opensearch_ssl_context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required for rendered-manifest acceptance")
def test_keycloak_network_policy_allows_only_required_application_components() -> None:
    rendered = subprocess.run(
        ["helm", "template", "nomosmart", str(CHART)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    policies = {
        item["metadata"]["name"]: item
        for item in yaml.safe_load_all(rendered)
        if isinstance(item, dict) and item.get("kind") == "NetworkPolicy"
    }
    keycloak_policy = policies["nomosmart-keycloak-ingress"]
    allowed_components = keycloak_policy["spec"]["ingress"][0]["from"][1]["podSelector"]["matchExpressions"][0]["values"]
    assert set(allowed_components) == {
        "frontend",
        "backend",
        "worker",
        "deployment-bootstrap",
        "deployment-finalize",
    }


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required for rendered-manifest acceptance")
def test_helm_renders_bundled_and_each_external_mode_exclusively() -> None:
    bundled = subprocess.run(
        ["helm", "template", "nomosmart", str(CHART)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    bundled_documents = [item for item in yaml.safe_load_all(bundled) if isinstance(item, dict)]
    rendered_services = {
        item["metadata"]["name"]
        for item in bundled_documents
        if item.get("kind") == "Service"
    }
    for name in PERIPHERALS:
        assert f"nomosmart-{name}" in rendered_services
    assert all(
        item.get("spec", {}).get("type", "ClusterIP") == "ClusterIP"
        for item in bundled_documents
        if item.get("kind") == "Service" and item["metadata"]["name"] in rendered_services
    )
    policies = {
        item["metadata"]["name"]: item
        for item in bundled_documents
        if item.get("kind") == "NetworkPolicy"
    }
    assert "nomosmart-default-deny-ingress" in policies
    neo4j_policy = policies["nomosmart-neo4j-ingress"]
    assert neo4j_policy["metadata"]["annotations"] == {
        "nomosmart.io/accepted-risk": "CHG-243",
        "nomosmart.io/risk-detail": "neo4j_community_admin_equivalent",
    }
    assert neo4j_policy["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 7687}]
    config = next(
        item
        for item in bundled_documents
        if item.get("kind") == "ConfigMap" and item.get("metadata", {}).get("name") == "nomosmart-config"
    )["data"]
    assert config["FRONTEND_OIDC_ISSUER_URL"] == "https://nomosmart.local/identity/realms/nomosmart"
    assert config["FRONTEND_OIDC_INTERNAL_ISSUER_URL"] == "http://nomosmart-keycloak:8080/identity/realms/nomosmart"
    keycloak_policy = policies["nomosmart-keycloak-ingress"]
    allowed_components = keycloak_policy["spec"]["ingress"][0]["from"][1]["podSelector"]["matchExpressions"][0]["values"]
    assert set(allowed_components) == {
        "frontend",
        "backend",
        "worker",
        "deployment-bootstrap",
        "deployment-finalize",
    }

    for name in PERIPHERALS:
        external = subprocess.run(
            ["helm", "template", "nomosmart", str(CHART), "--set", f"{name}.mode=external"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        documents = [item for item in yaml.safe_load_all(external) if isinstance(item, dict)]
        names = {
            item.get("metadata", {}).get("name")
            for item in documents
            if item.get("kind") in {"Service", "Deployment", "StatefulSet"}
        }
        assert f"nomosmart-{name}" not in names
