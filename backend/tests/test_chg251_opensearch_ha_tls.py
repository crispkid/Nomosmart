from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy/helm/nomosmart"
GENERATOR = ROOT / "deploy/package/generate-opensearch-tls"


def _render(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "helm",
            "template",
            "nomosmart",
            str(CHART),
            "--namespace",
            "nomosmart",
            "-f",
            str(CHART / "values-prod.yaml"),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_production_opensearch_is_three_node_quorum_tls_and_network_isolated() -> None:
    result = _render()
    assert result.returncode == 0, result.stderr
    documents = [item for item in yaml.safe_load_all(result.stdout) if isinstance(item, dict)]
    resources = {(item.get("kind"), item.get("metadata", {}).get("name")): item for item in documents}

    statefulset = resources[("StatefulSet", "nomosmart-opensearch")]
    expected_image = (
        "nomosmart/opensearch@"
        "sha256:4897a404a6791fcc1229a35c5d66f12260ce3b4231b09b513f0bf0dfacf4bb30"
    )
    assert statefulset["spec"]["replicas"] == 3
    assert statefulset["spec"]["podManagementPolicy"] == "Parallel"
    assert statefulset["spec"]["serviceName"] == "nomosmart-opensearch-headless"
    assert statefulset["spec"]["persistentVolumeClaimRetentionPolicy"] == {
        "whenDeleted": "Retain",
        "whenScaled": "Retain",
    }
    anti_affinity = statefulset["spec"]["template"]["spec"]["affinity"]["podAntiAffinity"]
    assert anti_affinity["requiredDuringSchedulingIgnoredDuringExecution"][0]["topologyKey"] == "kubernetes.io/hostname"
    env = {
        row["name"]: row.get("value")
        for row in statefulset["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert "discovery.type" not in env
    assert env["discovery.seed_hosts"] == "nomosmart-opensearch-headless.nomosmart.svc.cluster.local"
    assert env["cluster.initial_cluster_manager_nodes"] == (
        "nomosmart-opensearch-0,nomosmart-opensearch-1,nomosmart-opensearch-2"
    )
    assert env["plugins.security.ssl.transport.enforce_hostname_verification"] == "true"
    assert env["plugins.security.ssl.transport.resolve_hostname"] == "true"
    assert env["plugins.security.nodes_dn"] == '["CN=nomosmart-opensearch-node"]'
    assert env["plugins.security.ssl.transport.pemcert_filepath"] == "tls/transport.crt"
    assert "esnode.pem" not in result.stdout
    assert "root-ca.pem" not in result.stdout
    assert "verify=false" not in result.stdout
    assert statefulset["spec"]["template"]["spec"]["initContainers"][0]["image"] == expected_image
    assert statefulset["spec"]["template"]["spec"]["containers"][0]["image"] == expected_image

    client_service = resources[("Service", "nomosmart-opensearch")]
    assert client_service["spec"]["ports"] == [
        {"name": "https", "port": 9200, "targetPort": "https"}
    ]
    headless = resources[("Service", "nomosmart-opensearch-headless")]
    assert headless["spec"]["clusterIP"] == "None"
    assert headless["spec"]["publishNotReadyAddresses"] is True
    assert headless["spec"]["ports"] == [
        {"name": "transport", "port": 9300, "targetPort": "transport"}
    ]
    assert "9600" not in result.stdout
    assert resources[("PodDisruptionBudget", "nomosmart-opensearch")]["spec"]["minAvailable"] == 2

    policy = resources[("NetworkPolicy", "nomosmart-opensearch-ingress")]
    assert policy["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 9200}]
    assert policy["spec"]["ingress"][1]["ports"] == [{"protocol": "TCP", "port": 9300}]
    assert policy["spec"]["ingress"][1]["from"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/component"] == "opensearch"


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
@pytest.mark.parametrize(
    "override,expected",
    [
        ("opensearch.cluster.replicas=1", "/opensearch/cluster/replicas"),
        ("opensearch.cluster.bootstrapMode=single-node", "/opensearch/cluster/bootstrapMode"),
        ("opensearch.cluster.podDisruptionBudget.minAvailable=1", "/opensearch/cluster/podDisruptionBudget/minAvailable"),
        ("opensearch.tls.enforceHostnameVerification=false", "/opensearch/tls/enforceHostnameVerification"),
        ("opensearch.snapshot.enabled=false", "/opensearch/snapshot/enabled"),
        ("opensearch.image.digest=", "/opensearch/image/digest"),
    ],
)
def test_production_schema_rejects_unsafe_opensearch_values(override: str, expected: str) -> None:
    result = _render("--set", override)
    assert result.returncode != 0
    assert expected in result.stderr


@pytest.mark.skipif(shutil.which("helm") is None, reason="Helm is required")
def test_external_opensearch_renders_no_bundled_stateful_resources() -> None:
    result = _render("--set", "opensearch.mode=external")
    assert result.returncode == 0, result.stderr
    resources = {
        (item.get("kind"), item.get("metadata", {}).get("name"))
        for item in yaml.safe_load_all(result.stdout)
        if isinstance(item, dict)
    }
    for kind in ("StatefulSet", "PodDisruptionBudget"):
        assert (kind, "nomosmart-opensearch") not in resources
    assert ("Service", "nomosmart-opensearch") not in resources
    assert ("Service", "nomosmart-opensearch-headless") not in resources


@pytest.mark.skipif(
    not shutil.which("openssl") or not shutil.which("gpg"),
    reason="OpenSSL and GnuPG are required",
)
def test_private_ca_generator_produces_distinct_http_transport_and_encrypted_custody(tmp_path: Path) -> None:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    os.chmod(parent, 0o700)
    gpg_home = Path(tempfile.mkdtemp(prefix="chg251-gpg-", dir="/private/tmp"))
    os.chmod(gpg_home, 0o700)
    environment = dict(os.environ)
    environment["GNUPGHOME"] = str(gpg_home)
    try:
        generated = subprocess.run(
            [
                "gpg", "--batch", "--passphrase", "", "--quick-generate-key",
                "CHG-251 Test Recipient <chg251@example.invalid>", "rsa2048", "encrypt", "1d",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        if generated.returncode:
            pytest.skip(f"real GnuPG key generation unavailable: {generated.stderr.splitlines()[-1]}")
        public_key = parent / "recipient.asc"
        public_key.write_text(
            subprocess.run(
                ["gpg", "--batch", "--armor", "--export", "chg251@example.invalid"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout,
            encoding="utf-8",
        )
        os.chmod(public_key, 0o600)
        output = parent / "tls"
        custody = parent / "opensearch-ca-key.asc"
        result = subprocess.run(
            [
                str(GENERATOR),
                "--release", "nomosmart",
                "--namespace", "nomosmart",
                "--output-dir", str(output),
                "--pgp-public-key", str(public_key),
                "--custody-output", str(custody),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert stat.S_IMODE(output.stat().st_mode) == 0o700
        assert stat.S_IMODE(custody.stat().st_mode) == 0o600
        assert "BEGIN PGP MESSAGE" in custody.read_text(encoding="utf-8")
        assert not (output / "ca.key").exists()
        assert not any(path.name.endswith("ca.key") for path in parent.rglob("*"))
        assert {
            "tls.crt", "tls.key", "transport.crt", "transport.key", "ca.crt", "manifest.json"
        } == {path.name for path in output.iterdir()}
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["node_dn"] == "CN=nomosmart-opensearch-node"
        assert "nomosmart-opensearch.nomosmart.svc.cluster.local" in manifest["certificates"]["http"]["inspection"]
        assert "nomosmart-opensearch-0.nomosmart-opensearch-headless.nomosmart.svc.cluster.local" in manifest["certificates"]["transport"]["inspection"]
        assert "TLS Web Server Authentication" in manifest["certificates"]["transport"]["inspection"]
        assert "TLS Web Client Authentication" in manifest["certificates"]["transport"]["inspection"]
    finally:
        shutil.rmtree(gpg_home, ignore_errors=True)


def test_opensearch_image_is_pinned_and_adds_only_repository_s3() -> None:
    dockerfile = (ROOT / "deploy/opensearch/Dockerfile").read_text(encoding="utf-8")
    assert "opensearchproject/opensearch:2.19.6@sha256:" in dockerfile
    assert "opensearch-plugin install --batch repository-s3" in dockerfile
    assert "latest" not in dockerfile
