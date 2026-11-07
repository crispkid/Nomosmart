"""PROTAUTH-011/012: real deployment CLIs and private files, no running services.

Never read existing generated/runtime directories. The package-generator check
copies only explicitly named public source files into a disposable directory.
These are configuration checks, not runtime authentication or coverage evidence.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy/helm/nomosmart"


def command(args):
    return subprocess.run(args, cwd=ROOT, env=dict(os.environ, COMPOSE_DISABLE_ENV_FILE="1"),
                          capture_output=True, text=True, timeout=90)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class HelmPodHostAliases(unittest.TestCase):
    def test_owned_pod_name_mapping_preserves_tls(self):
        aliases = [{"ip": "192.0.2.10", "hostnames": ["postgres"]}]
        jdbc = "jdbc:postgresql://postgres:5432/nomosmart?sslmode=verify-full&sslrootcert=/etc/nomosmart/tls/postgresql-ca.crt"
        with tempfile.TemporaryDirectory(prefix="protocol-pod-dns-") as directory:
            path = Path(directory) / "values.json"
            path.write_text(json.dumps({"podHostAliases": aliases, "podDnsOverTcp": True,
                                        "migration": {"jdbcUrl": jdbc}}))
            result = command(["helm", "template", "protocol-dns", str(CHART), "-f", str(path),
                              "--set", "installer.deploymentStage=application"])
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = set()
        for row in yaml.safe_load_all(result.stdout):
            if not isinstance(row, dict) or row.get("kind") not in {"Deployment", "Job"}:
                continue
            component = row["metadata"].get("labels", {}).get("app.kubernetes.io/component")
            if component not in {"frontend", "backend", "worker", "beat", "migration", "deployment-bootstrap"}:
                continue
            pod = row["spec"]["template"]["spec"]
            self.assertEqual(pod["hostAliases"], aliases, component)
            checked.add(component)
            if component == "migration":
                self.assertIn("-url=" + jdbc, pod["containers"][0]["args"])
        self.assertTrue({"frontend", "backend", "worker", "beat", "migration"}.issubset(checked))


class DeploymentRemoval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [name for name in ["docker", "helm"] if shutil.which(name) is None]
        if required:
            raise RuntimeError("BLOCKED: required deployment CLI unavailable: " + ",".join(required))
        result = command(["docker", "compose", "--env-file", "deploy/docker/nomosmart.env.example",
                          "--profile", "*", "config", "--no-env-resolution", "--format", "json"])
        if result.returncode:
            raise RuntimeError("Compose public model failed: " + result.stderr)
        cls.compose = json.loads(result.stdout)

    def test_all_compose_profiles_exclude_provider_resources(self):
        self.assertNotIn("keycloak", self.compose["services"])
        self.assertFalse(any("keycloak" in name.lower() for name in self.compose.get("volumes", {})))
        self.assertFalse(any("keycloak" in name.lower() for name in self.compose.get("secrets", {})))
        for name, service in self.compose["services"].items():
            with self.subTest(service=name):
                self.assertNotIn("keycloak", service.get("image", "").lower())
                self.assertFalse(any("keycloak" in str(key).lower() for key in service.get("environment", {})))
                self.assertNotIn("keycloak", service.get("depends_on", {}))
        self.assertNotIn("TCP:keycloak", str(self.compose["services"].get("debug-ports", {})))
        self.assertIn("directory_bind_password", self.compose["secrets"])
        self.assertIn("AUTH_BOOTSTRAP_CONFIGURATION", self.compose["services"]["backend"]["environment"])
        for name in ("backend", "celery-worker", "celery-beat", "deployment-bootstrap", "deployment-finalize"):
            mounts = {row["target"]: row for row in self.compose["services"][name]["volumes"]}
            for target in ("/etc/nomosmart/auth-ca", "/etc/nomosmart/auth-bootstrap.json"):
                self.assertIn(target, mounts, name)
                self.assertTrue(mounts[target].get("read_only"), (name, target))
        for name in ("backend", "celery-worker", "celery-beat"):
            for field in ("DIRECTORY_BIND_PASSWORD_FILE", "OIDC_CLIENT_SECRET_FILE"):
                self.assertEqual(self.compose["services"][name]["environment"][field], "")
        self.assertEqual(self.compose["services"]["deployment-bootstrap"]["environment"]["DIRECTORY_BIND_PASSWORD_FILE"], "/run/secrets/directory_bind_password")

    def test_public_helm_profiles_render_without_provider(self):
        profiles = [[], ["values-dev.yaml"], ["values-bundled.example.yaml"], ["values-prod.yaml"],
                    ["values-prod.yaml", "values-external-services.example.yaml"], ["values-docker-desktop.yaml"]]
        for profile in profiles:
            with self.subTest(profile=profile or "default"):
                args = ["helm", "template", "protocol-check", str(CHART), "--set", "installer.deploymentStage=application"]
                for name in profile:
                    args += ["-f", str(CHART / name)]
                result = command(args)
                self.assertEqual(result.returncode, 0, result.stderr)
                resources = [row for row in yaml.safe_load_all(result.stdout) if isinstance(row, dict)]
                self.assertTrue(any(row["kind"] == "Deployment" for row in resources))
                for row in resources:
                    self.assertNotIn("keycloak", row["metadata"]["name"].lower())
                    if row["kind"] == "Secret":
                        self.assertFalse(any("keycloak" in key.lower() for key in row.get("stringData", {})))
                    if row["kind"] in {"Deployment", "StatefulSet", "Job"}:
                        pod = row["spec"]["template"]["spec"]
                        for container in pod.get("containers", []) + pod.get("initContainers", []):
                            self.assertNotIn("keycloak", container["image"].lower())
                            self.assertFalse(any("keycloak" in env["name"].lower() for env in container.get("env", [])))
                    if row["kind"] == "Ingress":
                        for rule in row["spec"].get("rules", []):
                            for path in rule["http"]["paths"]:
                                self.assertNotIn("keycloak", path["backend"]["service"]["name"].lower())

    def test_both_protocol_bootstrap_examples_render(self):
        for example in ["auth-bootstrap.example.json", "auth-bootstrap.oidc.example.json"]:
            with self.subTest(example=example), tempfile.TemporaryDirectory(prefix="protocol-values-") as directory:
                config = json.loads((ROOT / "deploy/docker" / example).read_text())
                path = Path(directory) / "values.json"
                path.write_text(json.dumps({"authentication": {"bootstrapConfiguration": config}}))
                result = command(["helm", "template", "protocol-check", str(CHART), "-f", str(path)])
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = [r for r in yaml.safe_load_all(result.stdout) if isinstance(r, dict)]
                self.assertTrue(any(r["metadata"]["name"].endswith("-auth-bootstrap") for r in rows))

    def test_removed_values_fail_before_apply(self):
        for value in ["keycloak.mode=bundled", "global.keycloakPath=/identity", "bootstrap.keycloakMode=manage",
                      "backend.env.KEYCLOAK_SYNC_CLIENT_ID=retired", "secrets.data.KEYCLOAK_DB_PASSWORD=retired",
                      "postgresql.auth.keycloakDatabase=retired"]:
            with self.subTest(value=value):
                result = command(["helm", "template", "protocol-check", str(CHART), "--set-string", value])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("keycloak", result.stderr.lower())

    def test_retired_ingress_target_is_rejected(self):
        hosts = yaml.safe_load((CHART / "values.yaml").read_text())["ingress"]["hosts"]
        hosts[0]["paths"][0]["service"] = "keycloak"
        with tempfile.TemporaryDirectory(prefix="protocol-ingress-") as directory:
            path = Path(directory) / "values.json"
            path.write_text(json.dumps({"ingress": {"hosts": hosts}}))
            result = command(["helm", "template", "protocol-check", str(CHART), "-f", str(path)])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ingress targets were removed", result.stderr)

    def test_current_installer_accepts_protocol_values_and_rejects_retired_component(self):
        import sys
        sys.path.insert(0, str(ROOT / "deploy/installer"))
        from nomosmart_installer.protocol import ProtocolInstaller
        from nomosmart_installer.core import PreconditionError
        with tempfile.TemporaryDirectory(prefix="protocol-target-") as directory:
            root = Path(directory)
            values = yaml.safe_load((CHART / "values-external-services.example.yaml").read_text())
            values["authentication"] = {"bootstrapConfiguration": json.loads(
                (ROOT / "deploy/docker/auth-bootstrap.example.json").read_text())}
            path = root / "values.json"
            path.write_text(json.dumps(values))
            target = root / "target.toml"
            target.write_text('api_version = "install.nomosmart.io/protocol-v2"\n[target]\n'
                              'context = "explicit-no-cluster-test"\nnamespace = "protocol-check"\n'
                              'release = "protocol-check"\ninstallation_id = "00000000-0000-4000-8000-000000000001"\n'
                              'values_file = "values.json"\nchart = ' + json.dumps(str(CHART)) + '\n')
            installer = ProtocolInstaller(target)
            self.assertEqual(installer.mode, "ldap")
            self.assertNotIn("keycloak", installer._values())
            values["keycloak"] = {"mode": "disabled"}
            path.write_text(json.dumps(values))
            with self.assertRaises(PreconditionError):
                ProtocolInstaller(target)

    def test_package_generator_has_no_product_credentials_or_guessed_issuer(self):
        with tempfile.TemporaryDirectory(prefix="protocol-package-") as directory:
            root = Path(directory)
            for name in ["deploy/package/nomosmart_package.py", "deploy/migrations/nomosmart_migrations.py",
                         "deploy/migrations/release-contract.json", "frontend/Dockerfile"]:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            (root / "deploy/docker").mkdir(parents=True)
            package = module(root / "deploy/package/nomosmart_package.py", "protocol_package_check")
            values = package._build_values(package.PRODUCTION_PROFILE, "compose", first_use=False,
                                            random_initial_credentials=True)
            self.assertFalse(any("keycloak" in name for name in values))
            self.assertIn("oidc_client_secret", values)
            package._write_compose_env(package.PRODUCTION_PROFILE, "production", public_host="example.test",
                                       runbook_uri="https://runbook.example.test", alerting_evidence="owned-test-input",
                                       random_initial_credentials=True, compose_project="protocol-check")
            text = (root / "deploy/docker/nomosmart.env").read_text()
            self.assertNotIn("keycloak", text.lower())
            self.assertNotIn("/identity/realms/", text)
            self.assertIn("COMPOSE_PROFILES=postgresql,redis,rustfs,opensearch,neo4j\n", text)

    def test_authentication_files_are_private_and_public_keyring_stays_empty(self):
        cli = module(ROOT / "deploy/docker/nomosmart_cli.py", "protocol_docker_check")
        with tempfile.TemporaryDirectory(prefix="protocol-auth-files-") as directory:
            root = Path(directory)
            shutil.copy2(ROOT / "docker-compose.yml", root / "docker-compose.yml")
            workflow = cli.Workflow(root)
            password = secrets.token_urlsafe(32)
            private = root / "operator-secret"
            private.write_text(password)
            private.chmod(0o600)
            workflow.validate_authentication_secret("directory_bind_password", private)
            self.assertTrue(password in workflow.secret_values)
            private.chmod(0o644)
            with self.assertRaises(cli.WorkflowError):
                workflow.validate_authentication_secret("directory_bind_password", private)
            private.chmod(0o600)
            alias = root / "alias"
            alias.symlink_to(private)
            with self.assertRaises(cli.WorkflowError):
                workflow.validate_authentication_secret("oidc_client_secret", alias)
            empty = root / "deploy/docker/auth-previous-keys.example.json"
            empty.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "deploy/docker/auth-previous-keys.example.json", empty)
            workflow.validate_authentication_secret("auth_previous_keys", empty)
            empty.write_text(json.dumps({"not-public": secrets.token_hex(32)}))
            with self.assertRaises(cli.WorkflowError):
                workflow.validate_authentication_secret("auth_previous_keys", empty)


if __name__ == "__main__":
    unittest.main()
