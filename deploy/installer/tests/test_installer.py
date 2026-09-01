from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


INSTALLER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = INSTALLER_ROOT.parents[1]
sys.path.insert(0, str(INSTALLER_ROOT))

from nomosmart_installer.config import ConfigError, load_config
from nomosmart_installer.core import InstallerError, Redactor, Runner
from nomosmart_installer.diagnostics import InstallerDiagnostics
from nomosmart_installer.directory import (
    KeycloakDirectoryInstaller,
    onboarding_status_probe_script,
)
from nomosmart_installer.kube import Kubernetes
from nomosmart_installer.package import PackageManager
from nomosmart_installer.orchestrator import (
    recoverable_finalization_helm_status,
)
from nomosmart_installer.preflight import _rendered_image_inventory
from nomosmart_installer.state import STAGES, InstallerState


def config_text(root: Path) -> str:
    tls = root / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    for name in (
        "edge.crt",
        "edge.key",
        "edge-ca.crt",
        "postgresql.crt",
        "postgresql.key",
        "postgresql-replication.crt",
        "postgresql-replication.key",
        "postgresql-ca.crt",
        "redis.crt",
        "redis.key",
        "redis-ca.crt",
        "rustfs.crt",
        "rustfs.key",
        "rustfs-ca.crt",
        "opensearch.crt",
        "opensearch.key",
        "opensearch-transport.crt",
        "opensearch-transport.key",
        "opensearch-ca.crt",
    ):
        (tls / name).write_text(f"fixture-{name}", encoding="utf-8")
    return textwrap.dedent(
        f"""
        api_version = "install.nomosmart.io/v1alpha1"

        [target]
        context = "uat"
        api_server = "https://10.0.0.10:6443"
        cluster_uid = "cluster-uid"
        namespace = "nomosmart"
        release = "nomosmart"

        [application]
        public_host = "nomosmart.example.com"
        ingress_class = "nginx"
        ingress_controller_namespace = "ingress-nginx"
        ingress_controller_name = "ingress-nginx"
        storage_class = "local-path"
        chart = "{REPOSITORY / 'deploy/helm/nomosmart'}"
        values = ["{REPOSITORY / 'deploy/helm/nomosmart/values-prod.yaml'}"]
        package_dir = "{root / 'package'}"
        state_dir = "{root / 'state'}"
        trusted_tls_dir = "{root / 'tls'}"
        registry_pull_secret = "registry-pull"
        runtime_secret = "nomosmart-runtime-secrets"
        ingress_tls_secret = "nomosmart-ingress-tls"
        rustfs_tls_secret = "nomosmart-rustfs-tls"
        opensearch_tls_secret = "nomosmart-opensearch-tls"
        onboarding_admin_allow_cidr = "10.0.0.0/24"
        break_glass_runbook_uri = "https://runbooks.example.com/nomosmart"
        break_glass_alerting_evidence = "SEC-UAT-route"

        [images]
        frontend = "registry.example/frontend:1.0@sha256:{'a' * 64}"
        backend = "registry.example/backend:1.0@sha256:{'b' * 64}"
        migration = "registry.example/migration:1.0@sha256:{'c' * 64}"
        postgresql = "registry.example/postgresql:18.4-standard-trixie@sha256:{'d' * 64}"
        redis = "registry.example/redis:7.4@sha256:{'e' * 64}"
        rustfs = "registry.example/rustfs:1.0@sha256:{'f' * 64}"
        opensearch = "registry.example/opensearch:2.19@sha256:{'1' * 64}"
        neo4j = "registry.example/neo4j:5.26@sha256:{'2' * 64}"
        keycloak = "registry.example/keycloak:26.0@sha256:{'3' * 64}"

        [identity]
        mode = "freeipa"
        realm = "nomosmart"
        provider_name = "freeipa-uat"
        mapper_name = "freeipa-uat-groups"
        admin_username = "peter"
        external_group_name = "nomosmart-admins"
        local_role_name = "system-admin"
        server_url = "ldaps://ipa.example.com:636"
        users_dn = "cn=users,dc=example,dc=com"
        groups_dn = "cn=groups,dc=example,dc=com"
        bind_dn = "uid=bind,dc=example,dc=com"
        bind_secret_name = "directory-bind"
        bind_secret_key = "bind-password"
        ca_secret_name = "directory-ca"
        ca_secret_key = "ca.crt"
        username_attribute = "uid"
        rdn_attribute = "uid"
        uuid_attribute = "ipaUniqueID"
        user_object_classes = ["inetOrgPerson"]
        group_object_classes = ["groupOfNames"]
        group_name_attribute = "cn"
        membership_attribute = "member"
        membership_attribute_type = "DN"
        membership_user_attribute = "uid"
        user_search_scope = "one-level"
        preserve_group_inheritance = true
        custom_user_filter = "(objectClass=inetOrgPerson)"
        group_path = "/ldap"
        """
    )


def external_config_text(root: Path) -> str:
    return config_text(root)


class InstallerConfigTests(unittest.TestCase):
    def test_production_v1alpha2_requires_release_trust_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "install.toml"
            path.write_text(
                config_text(root).replace(
                    'api_version = "install.nomosmart.io/v1alpha1"',
                    'api_version = "install.nomosmart.io/v1alpha2"',
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_freeipa_and_openldap_examples_preserve_typed_directory_profiles(
        self,
    ) -> None:
        freeipa_path = INSTALLER_ROOT / "nomosmart-install.example.toml"
        openldap_path = (
            INSTALLER_ROOT / "nomosmart-install.openldap.example.toml"
        )
        freeipa = load_config(freeipa_path)
        openldap = load_config(openldap_path)

        self.assertEqual(freeipa.identity.mode, "freeipa")
        self.assertEqual(freeipa.identity.provider_name, "freeipa-uat")
        self.assertEqual(
            KeycloakDirectoryInstaller._vendor(freeipa.identity.mode),
            "rhds",
        )

        self.assertEqual(openldap.identity.mode, "ldap")
        self.assertEqual(openldap.identity.provider_name, "openldap-uat")
        self.assertEqual(openldap.identity.mapper_name, "openldap-uat-groups")
        self.assertEqual(openldap.identity.admin_username, "user01")
        self.assertEqual(
            openldap.identity.external_group_name,
            "nomosmart-uat-admins",
        )
        self.assertEqual(
            openldap.identity.server_url,
            "ldaps://ldap.ldap.svc.cluster.local:636",
        )
        self.assertEqual(
            openldap.identity.users_dn,
            "ou=users,dc=ldap,dc=ctbclab,dc=com",
        )
        self.assertEqual(
            openldap.identity.groups_dn,
            "ou=groups,dc=ldap,dc=ctbclab,dc=com",
        )
        self.assertEqual(
            openldap.identity.bind_dn,
            "cn=nomosmart-bind,ou=users,dc=ldap,dc=ctbclab,dc=com",
        )
        self.assertEqual(openldap.identity.rdn_attribute, "cn")
        self.assertEqual(openldap.identity.uuid_attribute, "entryUUID")
        self.assertEqual(
            openldap.identity.user_object_classes,
            ("inetOrgPerson",),
        )
        self.assertEqual(
            openldap.identity.group_object_classes,
            ("groupOfNames",),
        )
        self.assertEqual(
            openldap.identity.custom_user_filter,
            "(objectClass=inetOrgPerson)",
        )
        self.assertEqual(
            KeycloakDirectoryInstaller._vendor(openldap.identity.mode),
            "other",
        )
        self.assertEqual(
            openldap.application.ingress_controller_namespace,
            "kube-system",
        )
        self.assertEqual(
            openldap.application.ingress_controller_name,
            "rke2-ingress-nginx",
        )

        values = openldap.generated_helm_values("application")
        self.assertEqual(
            values["directory"]["caSecretName"],
            "nomosmart-directory-ca",
        )
        self.assertEqual(
            values["backend"]["env"][
                "DEPLOYMENT_FINALIZATION_ADMIN_USERNAME"
            ],
            "user01",
        )
        self.assertEqual(
            values["backend"]["env"][
                "DEPLOYMENT_FINALIZATION_ADMIN_GROUP"
            ],
            "nomosmart-uat-admins",
        )
        self.assertEqual(
            values["networkPolicy"]["ingressController"][
                "namespaceSelector"
            ]["matchLabels"]["kubernetes.io/metadata.name"],
            "kube-system",
        )
        self.assertEqual(
            values["networkPolicy"]["ingressController"][
                "podSelector"
            ]["matchLabels"]["app.kubernetes.io/name"],
            "rke2-ingress-nginx",
        )
        directory_installer = KeycloakDirectoryInstaller(
            openldap,
            SimpleNamespace(),
            Redactor(),
        )
        directory_installer._realm_component_parent = "realm-id"
        provider_config = directory_installer._provider_payload(
            "protected-bind-value"
        )["config"]
        mapper_config = directory_installer._mapper_payload(
            "provider-id"
        )["config"]
        for component_config in (provider_config, mapper_config):
            self.assertNotIn(
                "nomosmartInstallerOwner",
                component_config,
            )
            self.assertNotIn(
                "nomosmartInstallerIdentityDigest",
                component_config,
            )
        source = openldap_path.read_text(encoding="utf-8")
        self.assertNotIn('password = "', source)

    def test_named_profiles_are_typed_and_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundled_path = root / "bundled.toml"
            bundled_path.write_text(
                config_text(root).replace(
                    'api_version = "install.nomosmart.io/v1alpha1"',
                    'api_version = "install.nomosmart.io/v1alpha1"\n'
                    'deployment_profile = "bundled"',
                    1,
                ),
                encoding="utf-8",
            )
            bundled = load_config(bundled_path)
            self.assertEqual(bundled.deployment_profile, "bundled")
            self.assertEqual(
                bundled.generated_helm_values("application")[
                    "deploymentProfile"
                ],
                "bundled",
            )

            external_path = root / "external.toml"
            external_path.write_text(
                external_config_text(root).replace(
                    'api_version = "install.nomosmart.io/v1alpha1"',
                    'api_version = "install.nomosmart.io/v1alpha1"\n'
                    'deployment_profile = "external-services"',
                    1,
                ).replace(
                    'runtime_secret = "nomosmart-runtime-secrets"',
                    'runtime_secret = "nomosmart-runtime-secrets"\n'
                    'runtime_secret_mode = "existing"',
                    1,
                ),
                encoding="utf-8",
            )
            external = load_config(external_path)
            self.assertEqual(external.deployment_profile, "external-services")
            self.assertEqual(external.application.runtime_secret_mode, "existing")
            self.assertEqual(
                external.generated_helm_values("application")[
                    "deploymentProfile"
                ],
                "external-services",
            )
            self.assertNotEqual(bundled.digest, external.digest)

            invalid_runtime_path = root / "invalid-runtime.toml"
            invalid_runtime_path.write_text(
                external_config_text(root).replace(
                    'api_version = "install.nomosmart.io/v1alpha1"',
                    'api_version = "install.nomosmart.io/v1alpha1"\n'
                    'deployment_profile = "external-services"',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ConfigError, "runtime_secret_mode=existing"
            ):
                load_config(invalid_runtime_path)

    def test_external_finalization_does_not_mutate_operator_runtime_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_root = root / "package"
            current = package_root / "current"
            state_root = root / "state"
            current.mkdir(parents=True, mode=0o700)
            state_root.mkdir(mode=0o700)
            initial_value = "generated-break-glass"
            secret_file = current / "BREAK_GLASS_INITIAL_PASSWORD"
            secret_file.write_text(initial_value, encoding="utf-8")
            secret_file.chmod(0o600)
            manifest = {
                "schema_version": 3,
                "generation_id": "generation-1",
                "deployment_state": "onboarding",
                "secrets": {
                    "break_glass_initial_password": {
                        "file": "BREAK_GLASS_INITIAL_PASSWORD",
                        "sha256": hashlib.sha256(
                            initial_value.encode("utf-8")
                        ).hexdigest(),
                    }
                },
            }
            (current / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            inventory = {
                "entries": [
                    {"logical_name": "break_glass_initial_password"}
                ]
            }
            (state_root / "credential-inventory.json").write_text(
                json.dumps(inventory), encoding="utf-8"
            )

            class ExternalRuntimeKube:
                def secret_fingerprints(self, name: str) -> dict[str, str]:
                    self.name = name
                    return {"BREAK_GLASS_INITIAL_PASSWORD": "external-fingerprint"}

                def remove_owned_secret_key(self, *_args: object, **_kwargs: object) -> None:
                    raise AssertionError(
                        "external runtime Secret must not be mutated"
                    )

            config = SimpleNamespace(
                deployment_profile="external-services",
                application=SimpleNamespace(
                    package_dir=package_root,
                    state_dir=state_root,
                    runtime_secret="nomosmart-runtime-secrets",
                    runtime_secret_mode="existing",
                ),
            )
            package = PackageManager(
                config,
                SimpleNamespace(),
                ExternalRuntimeKube(),
                REPOSITORY,
            )
            result = package.mark_finalized()

            self.assertFalse(result["break_glass_initial_password_removed"])
            self.assertTrue(result["external_runtime_secret_unchanged"])
            self.assertFalse(secret_file.exists())
            finalized_manifest = json.loads(
                (current / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                finalized_manifest["secrets"][
                    "break_glass_initial_password"
                ]["retired"]
            )
            finalized_inventory = json.loads(
                (state_root / "credential-inventory.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                finalized_inventory["entries"][0]["state"],
                "operator_remove_after_keycloak_disable",
            )


    def test_onboarding_probe_supports_least_privilege_old_and_new_images(
        self,
    ) -> None:
        probe = onboarding_status_probe_script()

        self.assertIn("OnboardingStatusSettings", probe)
        self.assertIn("except ImportError:", probe)
        self.assertIn("class OnboardingStatusSettings(Settings):", probe)
        self.assertNotIn("DeploymentBootstrapSettings", probe)
        self.assertNotIn("break_glass_initial_password", probe)
        self.assertIn("allow_disabled=False", probe)
        recovery_probe = onboarding_status_probe_script(
            allow_disabled_break_glass=True
        )
        self.assertIn("allow_disabled=True", recovery_probe)

    def test_only_failed_post_identity_finalization_is_recoverable(self) -> None:
        state = SimpleNamespace(
            current_stage="operational-finalization",
            completed_stages=["identity-checkpoint"],
        )

        self.assertTrue(
            recoverable_finalization_helm_status(
                state,
                {"status": "failed"},
            )
        )
        self.assertFalse(
            recoverable_finalization_helm_status(
                state,
                {"status": "pending-upgrade"},
            )
        )
        state.current_stage = "migration-bootstrap-and-app"
        self.assertFalse(
            recoverable_finalization_helm_status(
                state,
                {"status": "failed"},
            )
        )

    def test_versioned_config_generates_stage_values_without_secret_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "install.toml"
            path.write_text(config_text(root), encoding="utf-8")
            config = load_config(path)
            values = config.generated_helm_values("foundation")
            encoded = json.dumps(values, sort_keys=True)
            self.assertEqual(values["installer"]["deploymentStage"], "foundation")
            self.assertEqual(
                values["keycloak"]["trust"]["existingSecret"],
                "directory-ca",
            )
            self.assertEqual(
                values["imagePullSecrets"], [{"name": "registry-pull"}]
            )
            self.assertIn(
                "@sha256:",
                values["postgresql"]["cluster"]["image"]["tag"],
            )
            self.assertNotIn("image", values["postgresql"])
            for component in (
                "redis",
                "rustfs",
                "opensearch",
                "neo4j",
                "keycloak",
            ):
                self.assertIn("@sha256:", values[component]["image"]["tag"])
            self.assertNotIn("bind-password", encoded)
            self.assertNotIn("root_token", encoded)

    def test_rendered_image_inventory_accepts_cloudnativepg_image_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "install.toml"
            path.write_text(config_text(root), encoding="utf-8")
            config = load_config(path)
            rendered = "\n".join(
                [
                    *(
                        f"image: {image}"
                        for name, image in config.images.inventory().items()
                        if name != "postgresql"
                    ),
                    f"imageName: {config.images.postgresql}",
                ]
            )
            inventory = _rendered_image_inventory(config, rendered)
            self.assertEqual(set(inventory), set(config.images.inventory().values()))

    def test_secret_bearing_config_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "install.toml"
            path.write_text(
                config_text(root) + '\npassword = "must-not-be-here"\n',
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_image_must_be_digest_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "install.toml"
            path.write_text(
                config_text(root).replace(
                    f"frontend:1.0@sha256:{'a' * 64}", "frontend:latest"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_onboarding_admin_cidr_must_be_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "install.toml"
            path.write_text(
                config_text(root).replace(
                    'onboarding_admin_allow_cidr = "10.0.0.0/24"',
                    'onboarding_admin_allow_cidr = "0.0.0.0/0"',
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_config(path)


    def test_state_is_bound_to_config_digest_and_fixed_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "install.toml"
            path.write_text(config_text(root), encoding="utf-8")
            config = load_config(path)
            state = InstallerState.fresh(config, "test")
            state.complete(STAGES[0], {"ready": True})
            state.validate(config)
            self.assertEqual(state.completed_stages, ["preflight"])
            self.assertNotIn("password", json.dumps(state.payload()).lower())






    def test_existing_namespace_allows_kubernetes_root_ca_and_directory_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "install.toml"
            path.write_text(config_text(root), encoding="utf-8")
            config = load_config(path)
            kube = object.__new__(Kubernetes)
            kube.config = config
            kube.exists = lambda kind, name, namespace=True: (
                kind == "namespace" and name == config.target.namespace
            )

            def payload(
                verb: str,
                resource: str,
                *args: str,
                namespace: bool = True,
            ) -> dict[str, object]:
                self.assertEqual(verb, "get")
                if resource == "namespace":
                    return {
                        "metadata": {
                            "name": config.target.namespace,
                            "labels": {},
                            "annotations": {},
                        }
                    }
                self.assertEqual(
                    resource,
                    "all,configmap,secret,pvc,ingress,lease",
                )
                return {
                    "items": [
                        {
                            "kind": "ConfigMap",
                            "metadata": {"name": "kube-root-ca.crt"},
                        },
                        {
                            "kind": "Secret",
                            "metadata": {"name": "directory-bind"},
                        },
                        {
                            "kind": "Secret",
                            "metadata": {"name": "directory-ca"},
                        },
                        {
                            "kind": "Secret",
                            "metadata": {"name": "registry-pull"},
                        },
                    ]
                }

            kube.json = payload
            self.assertEqual(kube.namespace_state(), "empty")

    def test_custom_release_binds_runtime_secret_and_service_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "install.toml"
            path.write_text(
                config_text(root).replace(
                    'release = "nomosmart"', 'release = "uat"'
                ),
                encoding="utf-8",
            )
            config = load_config(path)
            values = config.generated_helm_values("application")
            self.assertEqual(config.helm_fullname, "uat-nomosmart")
            self.assertEqual(
                values["secrets"]["existingSecret"],
                "nomosmart-runtime-secrets",
            )

    def test_redactor_removes_registered_and_token_values(self) -> None:
        redactor = Redactor()
        redactor.register("super-secret")
        access_token = "token" + "." + "abcdefghijklmnopqrstuvwxyz"
        value = redactor.text(
            f"value=super-secret token={access_token}"
        )
        self.assertNotIn("super-secret", value)
        self.assertNotIn("hvs.", value)

    def test_runner_times_out_and_terminates_its_process_group(self) -> None:
        runner = Runner(Redactor(), cwd=REPOSITORY)
        started = time.monotonic()
        with self.assertRaises(InstallerError):
            runner.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import subprocess,sys,time;"
                        "subprocess.Popen([sys.executable,'-c','import time;"
                        "time.sleep(60)']);time.sleep(60)"
                    ),
                ],
                timeout=1,
            )
        self.assertLess(time.monotonic() - started, 15)

    def test_job_terminal_state_fails_fast_without_message_content(self) -> None:
        failed = Kubernetes.job_terminal_state(
            {
                "spec": {"backoffLimit": 0},
                "status": {
                    "failed": 1,
                    "conditions": [
                        {
                            "type": "Failed",
                            "status": "True",
                            "reason": "BackoffLimitExceeded",
                            "message": "protected diagnostic",
                        }
                    ],
                },
            },
            [
                {
                    "status": {
                        "containerStatuses": [
                            {
                                "state": {
                                    "terminated": {"exitCode": 17}
                                }
                            }
                        ]
                    }
                }
            ],
        )
        self.assertTrue(failed["terminal"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["reason"], "backoff-limit-exceeded")
        self.assertNotIn("protected", json.dumps(failed))



    def test_reset_candidate_refuses_operational_and_protected_state(
        self,
    ) -> None:
        diagnostic = InstallerDiagnostics.__new__(
            InstallerDiagnostics
        )
        base = {
            "local_state": {
                "status": "present",
                "progress": {"completed_stages": ["preflight"]},
            },
            "cluster_state": {
                "status": "present",
                "progress": {"completed_stages": ["preflight"]},
            },
            "helm": {"status": "missing", "deployment_phase": ""},
            "lease": {"status": "stale"},
            "owned_resources": {"items": []},
        }
        self.assertTrue(diagnostic._reset_candidate(base))
        operational = json.loads(json.dumps(base))
        operational["cluster_state"]["progress"][
            "completed_stages"
        ].append("operational-finalization")
        self.assertFalse(diagnostic._reset_candidate(operational))
        protected = json.loads(json.dumps(base))
        protected["owned_resources"]["items"] = [
            {"kind": "Secret", "protected": True}
        ]
        self.assertFalse(diagnostic._reset_candidate(protected))

    def test_cli_config_failure_is_redacted_and_uses_exit_20(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.toml"
            path.write_text(
                'api_version = "install.nomosmart.io/v1alpha1"\n'
                'password = "must-not-be-printed"\n',
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    str(INSTALLER_ROOT / "nomosmart-install"),
                    "plan",
                    "--config",
                    str(path),
                ],
                cwd=REPOSITORY,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 20)
            payload = json.loads(completed.stderr)
            self.assertEqual(payload["exit_code"], 20)
            self.assertEqual(payload["failure_class"], "ConfigError")
            self.assertNotIn("must-not-be-printed", completed.stderr)


@unittest.skipUnless(shutil.which("helm"), "helm is unavailable")
class InstallerHelmStageTests(unittest.TestCase):
    def _render(
        self,
        stage: str,
        *,
        finalize: bool = False,
        evidence_release: str = "",
    ) -> str:
        command = [
            "helm",
            "template",
            "nomosmart",
            str(REPOSITORY / "deploy/helm/nomosmart"),
            "--values",
            str(REPOSITORY / "deploy/helm/nomosmart/values-prod.yaml"),
            "--set",
            f"installer.deploymentStage={stage}",
            "--set",
            "backend.env.BREAK_GLASS_ALERTING_EVIDENCE=SEC-UAT-route",
            "--set",
            f"bootstrap.finalize.enabled={'true' if finalize else 'false'}",
        ]
        if evidence_release:
            command.extend(
                ["--set", f"bootstrap.evidenceRelease={evidence_release}"]
            )
        return subprocess.run(
            command,
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def test_foundation_omits_application_workloads_and_jobs(self) -> None:
        rendered = self._render("foundation")
        for name in (
            "nomosmart-backend",
            "nomosmart-frontend",
            "nomosmart-worker",
            "nomosmart-beat",
        ):
            self.assertNotIn(
                f"kind: Deployment\nmetadata:\n  name: {name}", rendered
            )
        self.assertNotIn("name: nomosmart-migration-1", rendered)
        self.assertNotIn("name: nomosmart-bootstrap-1", rendered)

    def test_external_services_profile_has_only_application_workloads(self) -> None:
        rendered = subprocess.run(
            [
                "helm",
                "template",
                "nomosmart",
                str(REPOSITORY / "deploy/helm/nomosmart"),
                "--namespace",
                "nomosmart",
                "--values",
                str(REPOSITORY / "deploy/helm/nomosmart/values-prod.yaml"),
                "--values",
                str(
                    REPOSITORY
                    / "deploy/helm/nomosmart/values-external-services.example.yaml"
                ),
                "--set",
                "installer.deploymentStage=application",
                "--set",
                "bootstrap.deploymentPhase=onboarding",
            ],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("name: nomosmart-backend", rendered)
        self.assertIn("name: nomosmart-frontend", rendered)
        self.assertIn("app.kubernetes.io/component: beat", rendered)
        self.assertNotIn("MALWARE_SCANNER_MODE", rendered)
        self.assertIn("sslmode=verify-full", rendered)
        self.assertIn("external-postgresql-ca", rendered)
        self.assertNotIn("external-vault-ca", rendered)
        workload_names = []
        for document in rendered.split("\n---"):
            kind = re.search(r"(?m)^kind: (.+)$", document)
            name = re.search(r"(?m)^  name: (nomosmart-[a-z0-9-]+)$", document)
            if kind and name and kind.group(1) in {
                "Deployment",
                "StatefulSet",
                "Service",
                "Job",
            }:
                workload_names.append(name.group(1))
        for component in (
            "postgresql",
            "redis",
            "rustfs",
            "opensearch",
            "neo4j",
            "keycloak",
        ):
            self.assertFalse(
                any(
                    name == f"nomosmart-{component}"
                    or name.startswith(f"nomosmart-{component}-")
                    for name in workload_names
                ),
                msg=f"unexpected bundled workload: {component}",
            )

        mixed = subprocess.run(
            [
                "helm",
                "template",
                "nomosmart",
                str(REPOSITORY / "deploy/helm/nomosmart"),
                "--namespace",
                "nomosmart",
                "--values",
                str(REPOSITORY / "deploy/helm/nomosmart/values-prod.yaml"),
                "--set",
                "deploymentProfile=external-services",
            ],
            cwd=REPOSITORY,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(mixed.returncode, 0)
        self.assertIn("deploymentProfile=external-services", mixed.stderr)

    def test_application_runs_jobs_but_finalize_revision_does_not_repeat_them(self) -> None:
        application = self._render("application")
        self.assertIn("name: nomosmart-migration-1", application)
        self.assertIn("name: nomosmart-bootstrap-1", application)
        self.assertNotIn("vault-bootstrap-evidence", application)
        finalization = self._render(
            "application",
            finalize=True,
            evidence_release="nomosmart-previous",
        )
        self.assertNotIn("name: nomosmart-migration-1", finalization)
        self.assertNotIn("name: nomosmart-bootstrap-1", finalization)
        self.assertIn("name: nomosmart-finalize-1", finalization)
        self.assertIn(
            'DEPLOYMENT_BOOTSTRAP_RELEASE: "nomosmart-previous"',
            finalization,
        )



if __name__ == "__main__":
    unittest.main()
