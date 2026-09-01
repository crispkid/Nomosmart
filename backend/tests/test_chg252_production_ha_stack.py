from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest
import yaml


REPOSITORY = Path(__file__).resolve().parents[2]
CHART = REPOSITORY / "deploy/helm/nomosmart"
VALUES = CHART / "values-prod.yaml"
INSTALLER = REPOSITORY / "deploy/installer"
sys.path.insert(0, str(INSTALLER))

from nomosmart_installer.cloudnativepg import (  # noqa: E402
    MANIFEST_SHA256,
    OPERATOR_IMAGE,
    OPERATOR_VERSION,
)
from nomosmart_installer.barman_cloud import (  # noqa: E402
    MANIFEST_SHA256 as BARMAN_MANIFEST_SHA256,
    PLUGIN_IMAGE as BARMAN_PLUGIN_IMAGE,
    PLUGIN_VERSION as BARMAN_PLUGIN_VERSION,
    RENDERED_MANIFEST_SHA256 as BARMAN_RENDERED_MANIFEST_SHA256,
    SIDECAR_IMAGE as BARMAN_SIDECAR_IMAGE,
)
from nomosmart_installer.core import PreconditionError  # noqa: E402
from nomosmart_installer.capacity import (  # noqa: E402
    bytes_quantity,
    rendered_capacity_plan,
    validate_live_capacity,
)
from nomosmart_installer.factory import (  # noqa: E402
    FactoryReinstall,
    OPENLDAP_LONGHORN_VOLUME,
)


def _render(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "helm",
            "template",
            "nomosmart",
            str(CHART),
            "--namespace",
            "nomosmart",
            "--values",
            str(VALUES),
            "--set",
            "installer.deploymentStage=application",
            *arguments,
        ],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )


def _documents() -> list[dict[str, object]]:
    result = _render()
    assert result.returncode == 0, result.stderr
    return [
        row
        for row in yaml.safe_load_all(result.stdout)
        if isinstance(row, dict)
    ]


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_chg252_exact_ha_topology_pdbs_and_failure_domains_render() -> None:
    documents = _documents()
    deployments = {
        row["metadata"]["name"]: row
        for row in documents
        if row.get("kind") == "Deployment"
    }
    statefulsets = {
        row["metadata"]["name"]: row
        for row in documents
        if row.get("kind") == "StatefulSet"
    }
    assert deployments["nomosmart-beat"]["spec"]["replicas"] == 2
    assert deployments["nomosmart-keycloak"]["spec"]["replicas"] == 3
    assert deployments["nomosmart-redis-sentinel"]["spec"]["replicas"] == 3
    assert statefulsets["nomosmart-opensearch"]["spec"]["replicas"] == 3
    assert statefulsets["nomosmart-redis"]["spec"]["replicas"] == 3
    assert statefulsets["nomosmart-rustfs"]["spec"]["replicas"] == 4

    budgets = {
        row["metadata"]["name"]: row["spec"]["minAvailable"]
        for row in documents
        if row.get("kind") == "PodDisruptionBudget"
    }
    assert budgets == {
        "nomosmart-backend": 1,
        "nomosmart-beat": 1,
        "nomosmart-frontend": 1,
        "nomosmart-keycloak": 2,
        "nomosmart-opensearch": 2,
        "nomosmart-postgresql": 2,
        "nomosmart-redis": 2,
        "nomosmart-redis-sentinel": 2,
        "nomosmart-rustfs": 3,
        "nomosmart-worker": 1,
    }
    rustfs_spec = statefulsets["nomosmart-rustfs"]["spec"]
    spread = rustfs_spec["template"]["spec"]["topologySpreadConstraints"][0]
    assert spread == {
        "maxSkew": 1,
        "topologyKey": "kubernetes.io/hostname",
        "whenUnsatisfiable": "DoNotSchedule",
        "labelSelector": {
            "matchLabels": {
                "app.kubernetes.io/name": "nomosmart",
                "app.kubernetes.io/instance": "nomosmart",
                "app.kubernetes.io/component": "rustfs",
            }
        },
    }
    assert rustfs_spec["template"]["spec"]["affinity"]["podAntiAffinity"].get(
        "requiredDuringSchedulingIgnoredDuringExecution"
    ) is None


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_chg252_cloudnativepg_redis_beat_and_internal_tls_contracts_render() -> None:
    documents = _documents()
    cluster = next(row for row in documents if row.get("kind") == "Cluster")
    assert cluster["apiVersion"] == "postgresql.cnpg.io/v1"
    assert cluster["spec"]["instances"] == 3
    assert cluster["spec"]["imageName"] == (
        "ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie@sha256:"
        "f0cc49632b5cc1e51f65ba03658c89bd31d64ea2672b14843a808a8d281417e1"
    )
    assert cluster["spec"]["postgresql"]["synchronous"] == {
        "method": "any",
        "number": 1,
        "dataDurability": "required",
        "failoverQuorum": True,
    }
    assert cluster["spec"]["postgresql"]["pg_hba"][0] == (
        "hostnossl all all all reject"
    )
    assert cluster["spec"]["certificates"] == {
        "serverCASecret": "nomosmart-postgresql-tls",
        "serverTLSSecret": "nomosmart-postgresql-tls",
        "clientCASecret": "nomosmart-postgresql-replication-tls",
        "replicationTLSSecret": "nomosmart-postgresql-replication-tls",
    }
    assert cluster["spec"]["plugins"] == [
        {
            "name": "barman-cloud.cloudnative-pg.io",
            "isWALArchiver": True,
            "parameters": {
                "barmanObjectName": "nomosmart-postgresql-backup"
            },
        }
    ]
    assert len([row for row in documents if row.get("kind") == "DatabaseRole"]) == 2
    assert len([row for row in documents if row.get("kind") == "Database"]) == 1

    statefulsets = {
        row["metadata"]["name"]: row
        for row in documents
        if row.get("kind") == "StatefulSet"
    }
    redis_command = statefulsets["nomosmart-redis"]["spec"]["template"]["spec"][
        "containers"
    ][0]["args"][0]
    assert "tls-port 6379" in redis_command
    assert "port 0" in redis_command
    assert "tls-replication yes" in redis_command
    assert "appendonly yes" in redis_command
    assert "nomosmart-service" not in redis_command
    rustfs = statefulsets["nomosmart-rustfs"]["spec"]["template"]["spec"]
    rustfs_env = {
        row["name"]: row.get("value")
        for row in rustfs["containers"][0]["env"]
    }
    assert rustfs_env["RUSTFS_VOLUMES"] == (
        "https://nomosmart-rustfs-{0...3}.nomosmart-rustfs-headless:9000/data"
    )

    deployments = {
        row["metadata"]["name"]: row
        for row in documents
        if row.get("kind") == "Deployment"
    }
    beat = deployments["nomosmart-beat"]["spec"]["template"]["spec"]
    assert beat["serviceAccountName"] == "nomosmart-beat"
    assert beat["containers"][0]["command"] == [
        "python",
        "-m",
        "app.beat_leader",
    ]
    assert "active|standby|degraded" in beat["containers"][0]["livenessProbe"][
        "exec"
    ]["command"][-1]
    assert any(
        volume["name"] == "internal-ca" for volume in beat["volumes"]
    )
    role = next(
        row
        for row in documents
        if row.get("kind") == "Role"
        and row["metadata"]["name"] == "nomosmart-beat-lease"
    )
    assert role["rules"][0]["resourceNames"] == ["nomosmart-celery-beat"]

    keycloak_container = deployments["nomosmart-keycloak"]["spec"]["template"][
        "spec"
    ]["containers"][0]
    assert keycloak_container["readinessProbe"]["httpGet"] == {
        "path": "/health/ready",
        "port": "management",
        "scheme": "HTTP",
    }
    object_store = next(
        row for row in documents if row.get("kind") == "ObjectStore"
    )
    configuration = object_store["spec"]["configuration"]
    assert configuration["destinationPath"] == (
        "s3://nomosmart-postgresql-backups/production"
    )
    assert configuration["endpointURL"] == "https://nomosmart-rustfs:9000"
    assert configuration["endpointCA"] == {
        "name": "nomosmart-rustfs-tls",
        "key": "ca.crt",
    }
    assert configuration["data"] == {
        "compression": "gzip",
        "encryption": "AES256",
    }
    assert configuration["wal"] == {
        "compression": "gzip",
        "encryption": "AES256",
    }
    assert object_store["spec"]["retentionPolicy"] == "30d"
    scheduled = next(
        row for row in documents if row.get("kind") == "ScheduledBackup"
    )
    assert scheduled["spec"]["method"] == "plugin"
    assert scheduled["spec"]["target"] == "prefer-standby"
    assert scheduled["spec"]["immediate"] is True


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
@pytest.mark.parametrize(
    "override,expected_path",
    [
        ("postgresql.cluster.instances=2", "/postgresql/cluster/instances"),
        ("redis.cluster.replicas=2", "/redis/cluster/replicas"),
        ("redis.cluster.sentinelQuorum=1", "/redis/cluster/sentinelQuorum"),
        ("rustfs.cluster.replicas=3", "/rustfs/cluster/replicas"),
        ("rustfs.cluster.parityShards=1", "/rustfs/cluster/parityShards"),
        ("beat.replicas=1", "/beat/replicas"),
        ("keycloak.cluster.replicas=2", "/keycloak/cluster/replicas"),
        ("postgresql.backup.enabled=false", "/postgresql/backup/enabled"),
        ("productionCapacity.enabled=false", "/productionCapacity/enabled"),
        (
            "productionCapacity.longhorn.requiredReplicaCount=3",
            "/productionCapacity/longhorn/requiredReplicaCount",
        ),
        (
            "productionCapacity.reservePercent.storage=20",
            "/productionCapacity/reservePercent/storage",
        ),
        (
            "postgresql.cluster.image.tag=18.4@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "/postgresql/cluster/image/tag",
        ),
    ],
)
def test_chg252_schema_rejects_under_provisioned_production_topology(
    override: str,
    expected_path: str,
) -> None:
    result = _render("--set", override)
    assert result.returncode != 0
    assert expected_path in result.stderr


def test_chg252_operator_and_package_supply_chain_contracts_are_pinned() -> None:
    assert OPERATOR_VERSION == "1.30.0"
    assert OPERATOR_IMAGE == (
        "ghcr.io/cloudnative-pg/cloudnative-pg@"
        "sha256:a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb"
    )
    assert MANIFEST_SHA256 == (
        "f8bede43fe4ee0d478c2355b204a36876b2ae4faac60f2a9452280b293da3b88"
    )
    assert BARMAN_PLUGIN_VERSION == "0.13.0"
    assert BARMAN_PLUGIN_IMAGE == (
        "ghcr.io/cloudnative-pg/plugin-barman-cloud@"
        "sha256:71589dbac582333442812b07b31f7ea4d00324a8358aac7ca507dabf9f4b6c96"
    )
    assert BARMAN_SIDECAR_IMAGE == (
        "ghcr.io/cloudnative-pg/plugin-barman-cloud-sidecar@"
        "sha256:990361af3319f9e23aafa0f6d7981f99bf1f69b4e6a85cf1bc7d71d6f09bb288"
    )
    assert BARMAN_MANIFEST_SHA256 == (
        "d2e71e7b06822448f1a421f05781846cfdb9cc621e7ef32eef5e20c5133213b0"
    )
    assert BARMAN_RENDERED_MANIFEST_SHA256 == (
        "dbb6d82026d6bc7a511f2f25b4e347194d7316b6c8a453b9302bf9d1042aa2ed"
    )
    production_values = yaml.safe_load(VALUES.read_text(encoding="utf-8"))
    assert production_values["postgresql"]["cluster"]["image"] == {
        "repository": "ghcr.io/cloudnative-pg/postgresql",
        "tag": (
            "18.4-standard-trixie@sha256:"
            "f0cc49632b5cc1e51f65ba03658c89bd31d64ea2672b14843a808a8d281417e1"
        ),
        "pullPolicy": "IfNotPresent",
    }
    package_source = (
        REPOSITORY / "deploy/package/nomosmart_package.py"
    ).read_text(encoding="utf-8")
    assert "SCHEMA_VERSION: Final[int] = 3" in package_source
    for name in (
        "postgresql.crt",
        "postgresql-replication.crt",
        "postgresql-ca.crt",
        "redis.crt",
        "redis-ca.crt",
    ):
        assert json.dumps(name) in package_source


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_chg252_development_profile_keeps_singleton_compatibility_boundary() -> None:
    result = subprocess.run(
        [
            "helm",
            "template",
            "nomosmart",
            str(CHART),
            "--namespace",
            "nomosmart",
            "--values",
            str(CHART / "values-dev.yaml"),
            "--set",
            "installer.deploymentStage=operational",
        ],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    documents = [
        row
        for row in yaml.safe_load_all(result.stdout)
        if isinstance(row, dict)
    ]
    assert not any(
        row.get("kind")
        in {"Cluster", "ObjectStore", "ScheduledBackup"}
        for row in documents
    )
    assert not any(
        row.get("kind") == "Deployment"
        and row["metadata"]["name"] == "nomosmart-redis-sentinel"
        for row in documents
    )
    deployments = {
        row["metadata"]["name"]: row
        for row in documents
        if row.get("kind") == "Deployment"
    }
    assert deployments["nomosmart-beat"]["spec"]["replicas"] == 1
    assert deployments["nomosmart-beat"]["spec"]["template"]["spec"][
        "containers"
    ][0]["command"] != ["python", "-m", "app.beat_leader"]


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_chg252_guided_foundation_prepares_bucket_before_enabling_wal_plugin() -> None:
    result = _render(
        "--set",
        "installer.deploymentStage=foundation",
        "--set",
        "postgresql.backup.enabled=false",
        "--set",
        "postgresql.backup.prepareBucket=true",
    )
    assert result.returncode == 0, result.stderr
    documents = [
        row
        for row in yaml.safe_load_all(result.stdout)
        if isinstance(row, dict)
    ]
    assert not any(
        row.get("kind") in {"ObjectStore", "ScheduledBackup"}
        for row in documents
    )
    job = next(
        row
        for row in documents
        if row.get("kind") == "Job"
        and "postgresql-backup-bucket" in row["metadata"]["name"]
    )
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == [
        "python",
        "-m",
        "app.deployment.storage_bootstrap",
    ]
    assert container["args"] == [
        "--bucket",
        "nomosmart-postgresql-backups",
    ]


def test_chg252_factory_plan_requires_separate_digest_bound_delete_approval() -> None:
    factory = FactoryReinstall.__new__(FactoryReinstall)
    inventory = {
        "target": {"cluster_uid": "cluster-uid"},
        "namespace": {
            "uid": "namespace-uid",
            "rancher_project_id": "c-1:p-1",
        },
        "helm": {"revision": 7, "status": "deployed"},
        "delete": {
            "namespaced_resources": [],
            "persistent_volumes": [],
            "longhorn_volumes": [],
            "longhorn_snapshots": [],
            "cluster_scoped_resources": [],
        },
        "preserve": {
            "systems": [
                "OpenLDAP",
                "RKE2",
                "Rancher",
                "Registry",
                "DNS",
                "Rancher Project",
                "Kubernetes Namespace",
            ],
            "longhorn_volumes": [
                {"name": OPENLDAP_LONGHORN_VOLUME}
            ],
        },
        "local_package_generation": {"status": "missing"},
        "backup_choice": "delete-without-backup",
        "blockers": [],
        "inventory_digest": "fixture-inventory",
    }
    factory.inventory = lambda: inventory  # type: ignore[method-assign]
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "factory-plan.json"
        result = factory.plan(path)
        assert result["ready_for_permanent_delete_approval"] is True
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["gate4_is_not_delete_approval"] is True
        assert payload["approval_phrase"].endswith(payload["plan_digest"])
        with pytest.raises(
            PreconditionError,
            match="Gate 4 is insufficient",
        ):
            factory.apply(
                path,
                confirmation=payload["plan_digest"],
                approval=(
                    "Peter approves CHG-252 Production HA Stack And Factory Reinstall"
                ),
            )


def test_chg252_factory_plan_with_attached_volume_cannot_request_delete_approval() -> None:
    factory = FactoryReinstall.__new__(FactoryReinstall)
    factory.inventory = lambda: {  # type: ignore[method-assign]
        "delete": {
            "namespaced_resources": [],
            "persistent_volumes": [],
            "longhorn_volumes": [{"name": "pvc-nomosmart", "state": "attached"}],
            "longhorn_snapshots": [],
            "cluster_scoped_resources": [],
        },
        "preserve": {
            "longhorn_volumes": [{"name": OPENLDAP_LONGHORN_VOLUME}]
        },
        "blockers": ["nomosmart-longhorn-volume-still-attached"],
    }
    with tempfile.TemporaryDirectory() as temporary:
        result = factory.plan(Path(temporary) / "blocked.json")
    assert result["ready_for_permanent_delete_approval"] is False
    assert result["blockers"] == [
        "nomosmart-longhorn-volume-still-attached"
    ]


class _CapacityKubernetes:
    def __init__(self, *, replicas: str = "1") -> None:
        self.config = SimpleNamespace(
            target=SimpleNamespace(namespace="nomosmart"),
            application=SimpleNamespace(storage_class="nomosmart-longhorn-r1"),
        )
        self.replicas = replicas

    def exists(self, kind: str, name: str, *, namespace: bool | str = True) -> bool:
        assert kind == "namespace"
        return False

    def json(self, *arguments: str, namespace: bool | str = False) -> dict[str, object]:
        resource = arguments[1]
        if resource == "nodes":
            return {
                "items": [
                    {
                        "metadata": {"name": f"rke2-{index}"},
                        "status": {
                            "allocatable": {"cpu": "8", "memory": "32Gi"}
                        },
                    }
                    for index in range(1, 4)
                ]
            }
        if resource == "pods":
            return {"items": []}
        if resource == "storageclass":
            return {
                "provisioner": "driver.longhorn.io",
                "parameters": {
                    "numberOfReplicas": self.replicas,
                    "dataLocality": "best-effort",
                },
            }
        if resource == "nodes.longhorn.io":
            assert namespace == "longhorn-system"
            return {
                "items": [
                    {
                        "metadata": {"name": f"rke2-{index}"},
                        "spec": {
                            "allowScheduling": True,
                            "disks": {"disk": {"allowScheduling": True}},
                        },
                        "status": {
                            "conditions": [{"type": "Ready", "status": "True"}],
                            "diskStatus": {
                                "disk": {
                                    "conditions": [
                                        {"type": "Ready", "status": "True"},
                                        {"type": "Schedulable", "status": "True"},
                                    ],
                                    "storageMaximum": str(300 * 1024**3),
                                    "storageAvailable": str(250 * 1024**3),
                                    "storageScheduled": "0",
                                }
                            },
                        },
                    }
                    for index in range(1, 4)
                ]
            }
        raise AssertionError((arguments, namespace))


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_chg252_capacity_plan_accounts_for_all_pvcs_and_live_headroom() -> None:
    rendered = _render()
    assert rendered.returncode == 0, rendered.stderr
    plan = rendered_capacity_plan(rendered.stdout)
    result = validate_live_capacity(
        _CapacityKubernetes(),
        plan,
        ["rke2-1", "rke2-2", "rke2-3"],
    )
    assert result["status"] == "ready"
    assert result["planned_storage"] == {
        "pvc_count": 14,
        "logical_bytes": bytes_quantity("385Gi"),
        "physical_bytes": bytes_quantity("385Gi"),
        "longhorn_replica_count": 1,
    }
    assert result["required_with_reserve"]["physical_storage_bytes"] == (
        bytes_quantity("385Gi") * 125 // 100
    )
    assert result["longhorn"]["replica_count"] == 1


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_chg252_capacity_rejects_layered_longhorn_replication() -> None:
    rendered = _render()
    assert rendered.returncode == 0, rendered.stderr
    with pytest.raises(
        PreconditionError,
        match="must explicitly use one replica",
    ):
        validate_live_capacity(
            _CapacityKubernetes(replicas="3"),
            rendered_capacity_plan(rendered.stdout),
            ["rke2-1", "rke2-2", "rke2-3"],
        )
