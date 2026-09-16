from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_retired_initialization_runtime_surface_is_absent() -> None:
    retired_files = (
        "frontend/src/app/setup/page.tsx",
        "backend/app/api/routes/system_initialization.py",
        "backend/app/domain/system_initialization.py",
        "backend/app/security/initialization_access.py",
    )
    assert all(not (ROOT / path).exists() for path in retired_files)

    runtime_sources = (
        "backend/app/api/router.py",
        "backend/app/api/schemas.py",
        "backend/app/core/config.py",
        "backend/app/db/models.py",
        "backend/app/main.py",
    )
    forbidden = (
        "SystemInitialization",
        "system_initialization",
        "system-initialization",
        "SYSTEM_INITIALIZATION_",
        "X-NomoSmart-Bootstrap-Token",
    )
    for path in runtime_sources:
        source = read(path)
        for value in forbidden:
            assert value not in source, f"{value} remains active in {path}"


def test_legacy_tables_are_preserved_but_excluded_from_new_bootstrap() -> None:
    legacy_create = read("sql/migrations/V008__system_initialization.sql")
    legacy_extension = read("sql/migrations/V024__initialization_last_known_good.sql")
    evidence = read("sql/migrations/V026__deployment_bootstrap_evidence.sql")
    bootstrap = read("backend/app/deployment/bootstrap.py")
    keycloak = read("backend/app/integrations/keycloak.py")

    assert "CREATE TABLE system_initialization_state" in legacy_create
    assert "CREATE TABLE system_initialization_steps" in legacy_create
    assert "ALTER TABLE system_initialization_state" in legacy_extension
    assert "CREATE TABLE deployment_bootstrap_evidence" in evidence
    assert "DROP TABLE" not in evidence
    assert "system_initialization_state" not in bootstrap
    assert "system_initialization_steps" not in bootstrap
    assert "app.api" not in bootstrap
    assert "pkce.code.challenge.method" in keycloak
    assert "oidc-audience-mapper" in keycloak
    assert "serviceAccountsEnabled" in keycloak


def test_compose_owns_migration_bootstrap_and_application_gate() -> None:
    compose_source = read("docker-compose.yml")
    compose = yaml.safe_load(compose_source)
    services = compose["services"]

    assert "migration" in services
    assert "deployment-bootstrap" in services
    assert services["deployment-bootstrap"]["depends_on"]["migration"]["condition"] == "service_completed_successfully"
    assert services["backend"]["depends_on"]["migration"]["condition"] == "service_completed_successfully"
    assert services["backend"]["depends_on"]["deployment-bootstrap"]["condition"] == "service_completed_successfully"
    for name in ("celery-worker", "celery-beat"):
        assert "backend" not in services[name]["depends_on"]
        assert services[name]["depends_on"]["migration"]["condition"] == "service_completed_successfully"
        assert services[name]["depends_on"]["deployment-bootstrap"]["condition"] == "service_completed_successfully"
        assert services[name]["depends_on"]["redis"]["condition"] == "service_healthy"
    assert "/api/v1/ready" in services["backend"]["healthcheck"]["test"][-1]
    assert "DEPLOYMENT_BOOTSTRAP_RELEASE" in services["backend"]["environment"]
    assert "SYSTEM_INITIALIZATION_" not in compose_source


def test_helm_uses_revision_scoped_jobs_and_init_gates_only() -> None:
    chart = ROOT / "deploy/helm/nomosmart"
    migration = read("deploy/helm/nomosmart/templates/migration-job.yaml")
    bootstrap = read("deploy/helm/nomosmart/templates/bootstrap-job.yaml")
    init_gate = read("deploy/helm/nomosmart/templates/_bootstrap-init.tpl")
    config = read("deploy/helm/nomosmart/templates/configmap.yaml")

    assert "kind: Job" in migration and ".Release.Revision" in migration
    assert "kind: Job" in bootstrap and ".Release.Revision" in bootstrap
    assert 'args: ["--mode", "ensure"' in bootstrap
    assert 'args: ["--mode", "check"' in init_gate
    assert "DEPLOYMENT_BOOTSTRAP_RELEASE" in config and ".Release.Revision" in config
    assert 'fail "DEPLOYMENT_BOOTSTRAP_RELEASE is chart-managed' in config
    init_helpers = {
        "backend": "nomosmart.bootstrapInitContainer",
        "frontend": "nomosmart.backendReadyInitContainer",
        "worker": "nomosmart.bootstrapEvidenceInitContainer",
        "beat": "nomosmart.bootstrapEvidenceInitContainer",
    }
    for workload, init_helper in init_helpers.items():
        source = read(f"deploy/helm/nomosmart/templates/{workload}-deployment.yaml")
        assert f'include "{init_helper}"' in source
        assert "nomosmart.io/deployment-release" in source

    raw_manifests = [
        path
        for path in (ROOT / "deploy").rglob("*.yaml")
        if chart not in path.parents
    ]
    assert all(path.name.endswith(".example.yaml") for path in raw_manifests)


def test_deployment_examples_and_chart_have_no_retired_settings() -> None:
    paths = (
        "backend/.env.example",
        "deploy/docker/nomosmart.env.example",
        "docker-compose.yml",
        "deploy/helm/nomosmart/values.yaml",
        "deploy/helm/nomosmart/values.schema.json",
        "deploy/helm/nomosmart/templates/configmap.yaml",
        "deploy/helm/nomosmart/templates/secret.yaml",
    )
    for path in paths:
        source = read(path)
        assert "SYSTEM_INITIALIZATION_" not in source
        assert "INITIALIZATION_BOOTSTRAP_TOKEN" not in source
