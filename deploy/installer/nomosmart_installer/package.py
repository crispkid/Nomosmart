from __future__ import annotations

import json
from pathlib import Path
import stat
from typing import Any

from .config import EXTERNAL_RUNTIME_SECRET_KEYS, InstallConfig
from .core import DriftError, PreconditionError, Runner, atomic_private_json, now, sha256_file
from .kube import Kubernetes


PACKAGE_SCHEMA_VERSION = 3


class PackageManager:
    def __init__(self, config: InstallConfig, runner: Runner, kube: Kubernetes, repository: Path) -> None:
        self.config = config
        self.runner = runner
        self.kube = kube
        self.repository = repository
        self.current = config.application.package_dir / "current"

    def initialize(self) -> dict[str, Any]:
        manifest_path = self.current / "manifest.json"
        if manifest_path.is_file():
            self.validate_local_for_plan()
            manifest = self._manifest()
            self._validate_reusable_manifest(manifest, bind_missing=True)
            return manifest
        command = [
            str(self.repository / "deploy/package/nomosmart-package"),
            "init",
            "--target",
            "helm",
            "--profile",
            "factory_acceptance" if self.config.local_installation else "production",
            "--app-env",
            "development" if self.config.local_installation else "production",
            "--output-dir",
            str(self.config.application.package_dir),
            "--public-host",
            self.config.application.public_host,
            "--helm-release",
            self.config.target.release,
            "--helm-fullname",
            self.config.helm_fullname,
            "--helm-namespace",
            self.config.target.namespace,
            "--no-display",
        ]
        if self.config.local_installation:
            command.extend(["--random-initial-credentials", "--postgresql-standalone"])
        if self.config.application.trusted_tls_dir is not None:
            command.extend(["--trusted-tls-dir", str(self.config.application.trusted_tls_dir)])
        if self.config.deployment_profile == "external-services":
            command.append("--external-services")
        self.runner.run(command, timeout=300)
        manifest = self._manifest()
        expected_profile = "factory_acceptance" if self.config.local_installation else "production"
        if manifest.get("target") != "helm" or manifest.get("profile") != expected_profile:
            raise DriftError("generated package target/profile does not match")
        certificate_host = str((manifest.get("certificates") or {}).get("public_host") or "")
        if certificate_host != self.config.application.public_host:
            raise DriftError("generated package public host does not match")
        manifest["installer_binding"] = self._binding()
        atomic_private_json(self.current / "manifest.json", manifest)
        self._validate_reusable_manifest(
            manifest, bind_missing=False
        )
        return manifest

    def _binding(self) -> dict[str, str]:
        return {
            "config_digest": self.config.digest,
            "cluster_uid": self.config.target.cluster_uid,
            "namespace": self.config.target.namespace,
            "release": self.config.target.release,
        }

    def _validate_reusable_manifest(
        self,
        manifest: dict[str, Any],
        *,
        bind_missing: bool,
    ) -> None:
        if (
            manifest.get("target") != "helm"
            or manifest.get("profile") != ("factory_acceptance" if self.config.local_installation else "production")
            or manifest.get("app_env") != ("development" if self.config.local_installation else "production")
            or str(manifest.get("helm_release") or "nomosmart")
            != self.config.target.release
            or str(manifest.get("helm_fullname") or "nomosmart")
            != self.config.helm_fullname
        ):
            raise DriftError(
                "existing package is not a production Helm package"
            )
        if manifest.get("deployment_state") != "onboarding":
            raise DriftError(
                "existing package is not in reusable onboarding state"
            )
        certificates = manifest.get("certificates") or {}
        allowed_tls_sources = (
            {"operator_provided", "operator_provided_edge"}
            if self.config.deployment_profile == "external-services"
            else {"operator_provided"}
        )
        if self.config.local_installation:
            allowed_tls_sources.add("bundled_self_signed")
        if (
            not isinstance(certificates, dict)
            or certificates.get("public_host")
            != self.config.application.public_host
            or certificates.get("active_source")
            not in allowed_tls_sources
        ):
            raise DriftError(
                "existing package trusted-TLS identity does not match"
            )
        binding = manifest.get("installer_binding")
        if binding is None and bind_missing:
            manifest["installer_binding"] = self._binding()
            atomic_private_json(self.current / "manifest.json", manifest)
        elif binding is not None and binding != self._binding():
            raise DriftError(
                "existing package is bound to another installer target/configuration"
            )
        rows = manifest.get("secrets")
        if not isinstance(rows, dict) or not rows:
            raise DriftError("existing package secret inventory is invalid")
        if not isinstance(
            rows.get("break_glass_initial_password"), dict
        ):
            raise DriftError(
                "existing package has no break-glass initial credential"
            )
        for logical, row in rows.items():
            if not isinstance(row, dict) or not isinstance(
                row.get("file"), str
            ):
                raise DriftError(
                    f"existing package secret entry is invalid: {logical}"
                )
            path = self._protected_file(str(row["file"]))
            if sha256_file(path) != row.get("sha256"):
                raise DriftError(
                    f"existing package secret fingerprint differs: {logical}"
                )
        self._verify_active_tls()

    def _verify_active_tls(self) -> None:
        trusted = self.config.application.trusted_tls_dir
        if trusted is None:
            raise PreconditionError(
                "production package reuse requires trusted TLS input"
            )
        names = (
            ("edge.crt", "edge.key", "edge-ca.crt")
            if self.config.deployment_profile == "external-services"
            else (
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
            )
        )
        for name in names:
            active = self._protected_file(f"tls/active/{name}")
            source = trusted / name
            if (
                not source.is_file()
                or source.is_symlink()
                or sha256_file(active) != sha256_file(source)
            ):
                raise DriftError(
                    f"existing package trusted TLS differs: {name}"
                )

    def validate_local_for_plan(self) -> str:
        root = self.config.application.package_dir
        if not root.exists():
            return "absent"
        if (
            not root.is_dir()
            or root.is_symlink()
            or stat.S_IMODE(root.stat().st_mode) != 0o700
        ):
            raise PreconditionError(
                "existing package directory must be a private regular directory"
            )
        children = {path.name for path in root.iterdir()}
        unknown = sorted(children - {"current", "previous"})
        if unknown:
            raise DriftError(
                "package directory contains unsupported entries: "
                + ", ".join(unknown)
            )
        for name in children:
            child = root / name
            if (
                not child.is_dir()
                or child.is_symlink()
                or stat.S_IMODE(child.stat().st_mode) != 0o700
            ):
                raise PreconditionError(
                    f"package {name} must be a private regular directory"
                )
        if not children:
            return "empty"
        if "current" not in children and children == {"previous"}:
            return "archived-only"
        if not (self.current / "manifest.json").is_file():
            raise DriftError(
                "non-empty package directory has no reusable current manifest"
            )
        manifest = self._manifest()
        self._validate_reusable_manifest(manifest, bind_missing=False)
        return "reusable"

    def _manifest(self) -> dict[str, Any]:
        path = self.current / "manifest.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreconditionError("generated package manifest is unavailable or invalid") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != PACKAGE_SCHEMA_VERSION
        ):
            raise PreconditionError(
                "generated package manifest schema is incompatible"
            )
        return payload

    def _bounded_path(self, relative: str) -> Path:
        candidate = Path(relative)
        if (
            candidate.is_absolute()
            or not candidate.parts
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise PreconditionError(
                f"generated package path is unsafe: {relative}"
            )
        cursor = self.current
        for part in candidate.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise PreconditionError(
                    f"generated package path contains a symlink: {relative}"
                )
        try:
            cursor.resolve().relative_to(self.current.resolve())
        except ValueError as exc:
            raise PreconditionError(
                f"generated package path escapes package root: {relative}"
            ) from exc
        return cursor

    def _protected_file(self, relative: str) -> Path:
        path = self._bounded_path(relative)
        if not path.is_file() or path.is_symlink():
            raise PreconditionError(f"generated package file is missing: {relative}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise PreconditionError(
                f"generated package file must be mode 0600: {relative}"
            )
        return path

    def create_secrets(self) -> dict[str, Any]:
        manifest = self._manifest()
        secret_rows = manifest.get("secrets")
        if not isinstance(secret_rows, dict):
            raise PreconditionError("generated package secret inventory is invalid")
        runtime_files: dict[str, Path] = {}
        inventory: list[dict[str, Any]] = []
        usernames = manifest.get("usernames") if isinstance(manifest.get("usernames"), dict) else {}
        postgresql_endpoint = (
            f"{self.config.helm_fullname}-postgresql:5432" if self.config.local_installation
            else f"{self.config.helm_fullname}-postgresql-rw:5432"
        )
        redis_endpoint = (
            f"{self.config.helm_fullname}-redis-sentinel:26379"
        )
        rustfs_endpoint = (
            f"https://{self.config.helm_fullname}-rustfs:9000"
        )
        opensearch_endpoint = (
            f"https://{self.config.helm_fullname}-opensearch:9200"
        )
        neo4j_endpoint = (
            f"bolt://{self.config.helm_fullname}-neo4j:7687"
        )
        username_keys = {
            "break_glass_initial_password": "break_glass",
            "postgres_admin_password": "postgres_admin",
            "postgres_app_password": "postgres_app",
            "postgres_migration_password": "postgres_migration",
            "database_migration_user": "postgres_migration",
            "database_migration_password": "postgres_migration",
            "database_url": "postgres_app",
            "keycloak_db_password": "keycloak_db",
            "keycloak_bootstrap_admin_password": "keycloak_bootstrap",
            "keycloak_bootstrap_admin_username": "keycloak_bootstrap",
            "keycloak_sync_client_secret": "keycloak_sync",
            "rustfs_secret_access_key": "rustfs",
            "s3_access_key_id": "rustfs",
            "redis_password": "redis_service",
            "redis_replication_password": "redis_replication",
            "redis_sentinel_password": "redis_sentinel",
            "redis_url": "redis_service",
            "celery_broker_url": "redis_service",
            "celery_result_backend": "redis_service",
            "opensearch_admin_password": "opensearch_admin",
            "opensearch_service_password": "opensearch_service",
            "neo4j_admin_password": "neo4j_admin",
            "neo4j_service_password": "neo4j_service",
            "neo4j_auth": "neo4j_admin",
        }
        endpoints = {
            "break_glass_initial_password": f"https://{self.config.application.public_host}/login",
            "postgres_admin_password": postgresql_endpoint,
            "postgres_app_password": f"{postgresql_endpoint}/nomosmart",
            "postgres_migration_password": f"{postgresql_endpoint}/nomosmart",
            "database_migration_password": f"{postgresql_endpoint}/nomosmart",
            "database_url": f"{postgresql_endpoint}/nomosmart",
            "keycloak_db_password": f"{postgresql_endpoint}/keycloak",
            "keycloak_bootstrap_admin_password": f"https://{self.config.application.public_host}/identity/admin",
            "keycloak_sync_client_secret": f"https://{self.config.application.public_host}/identity/realms/{self.config.identity.realm}",
            "oidc_client_secret": f"https://{self.config.application.public_host}/identity/realms/{self.config.identity.realm}",
            "rustfs_secret_access_key": rustfs_endpoint,
            "s3_access_key_id": rustfs_endpoint,
            "redis_password": redis_endpoint,
            "redis_replication_password": redis_endpoint,
            "redis_sentinel_password": redis_endpoint,
            "opensearch_admin_password": opensearch_endpoint,
            "opensearch_service_password": opensearch_endpoint,
            "neo4j_admin_password": neo4j_endpoint,
            "neo4j_service_password": neo4j_endpoint,
        }
        for logical, row in sorted(secret_rows.items()):
            if not isinstance(row, dict) or not isinstance(row.get("file"), str):
                raise PreconditionError("generated package secret entry is invalid")
            path = self._protected_file(str(row["file"]))
            digest = sha256_file(path)
            if digest != row.get("sha256"):
                raise DriftError(f"generated package fingerprint mismatch: {logical}")
            runtime_files[str(row["file"])] = path
            if self.config.application.runtime_secret_mode == "existing":
                # External-service profiles consume an operator-provisioned
                # runtime Secret.  Keep the package manifest for digest and
                # release binding, but never copy its generated values into
                # Kubernetes or report those values as the active custody.
                continue
            inventory.append(
                {
                    "logical_name": logical,
                    "username": usernames.get(
                        username_keys.get(logical, ""), ""
                    )
                    or (
                        "nomosmart-backend"
                        if logical == "oidc_client_secret"
                        else ""
                    ),
                    "endpoint": endpoints.get(logical, "internal application runtime"),
                    "purpose": "bootstrap_or_service_credential",
                    "secret_reference": f"secret/{self.config.application.runtime_secret}:{row['file']}",
                    "custody": str(path),
                    "custodian": "NomoSmart operator",
                    "sha256": digest,
                    "generation": manifest.get("generation_id"),
                    "state": "active",
                }
            )
        inventory.append(
            {
                "logical_name": "designated_federated_administrator",
                "username": self.config.identity.admin_username,
                "endpoint": f"https://{self.config.application.public_host}/login",
                "purpose": "non-break-glass System Admin and UAT administration",
                "secret_reference": "directory-managed credential; not held by installer",
                "custody": "enterprise directory",
                "custodian": "directory account owner",
                "generation": manifest.get("generation_id"),
                "state": "requires_first_password_login",
            }
        )
        if self.config.identity.mode != "preconfigured":
            inventory.append(
                {
                    "logical_name": "directory_bind_identity",
                    "username": self.config.identity.bind_dn,
                    "endpoint": self.config.identity.server_url,
                    "purpose": "Keycloak read-only directory federation",
                    "secret_reference": (
                        f"secret/{self.config.identity.bind_secret_name}:"
                        f"{self.config.identity.bind_secret_key}"
                    ),
                    "custody": "existing Kubernetes Secret",
                    "custodian": "directory/platform operator",
                    "generation": manifest.get("generation_id"),
                    "state": "referenced",
                }
            )
        if self.config.application.runtime_secret_mode == "existing":
            existing_runtime = self.config.application.runtime_secret
            if not self.kube.exists("secret", existing_runtime):
                raise PreconditionError(
                    f"external runtime secret/{existing_runtime} does not exist"
                )
            runtime_fingerprints = self.kube.secret_fingerprints(existing_runtime)
            required_keys = set(runtime_files)
            if self.config.deployment_profile == "external-services":
                required_keys = set(EXTERNAL_RUNTIME_SECRET_KEYS)
            missing = sorted(required_keys - set(runtime_fingerprints))
            if missing:
                raise PreconditionError(
                    "external runtime Secret is missing required key(s): "
                    + ", ".join(missing)
                )
            fingerprints = {existing_runtime: runtime_fingerprints}
            for logical, row in sorted(secret_rows.items()):
                if not isinstance(row, dict) or not isinstance(row.get("file"), str):
                    continue
                key = str(row["file"])
                if (
                    self.config.deployment_profile == "external-services"
                    and key not in EXTERNAL_RUNTIME_SECRET_KEYS
                ):
                    continue
                inventory.append(
                    {
                        "logical_name": logical,
                        "username": usernames.get(
                            username_keys.get(logical, ""), ""
                        )
                        or (
                            "nomosmart-backend"
                            if logical == "oidc_client_secret"
                            else ""
                        ),
                        "endpoint": endpoints.get(
                            logical, "external service runtime"
                        ),
                        "purpose": "external_service_runtime_reference",
                        "secret_reference": (
                            f"secret/{existing_runtime}:{key}"
                        ),
                        "custody": "existing Kubernetes Secret",
                        "custodian": "external service/platform operator",
                        "sha256": runtime_fingerprints.get(key, ""),
                        "generation": manifest.get("generation_id"),
                        "state": "referenced",
                    }
                )
        else:
            fingerprints = {
                self.config.application.runtime_secret: self.kube.ensure_secret(
                    self.config.application.runtime_secret,
                    runtime_files,
                    component="runtime",
                )
            }
        basic_auth_sets = {
            f"{self.config.helm_fullname}-postgresql-superuser": (
                "postgres",
                self._protected_file("POSTGRES_ADMIN_PASSWORD"),
            ),
            f"{self.config.helm_fullname}-postgresql-migration": (
                "nomosmart_migration",
                self._protected_file("POSTGRES_MIGRATION_PASSWORD"),
            ),
            f"{self.config.helm_fullname}-postgresql-app": (
                "nomosmart",
                self._protected_file("POSTGRES_PASSWORD"),
            ),
            f"{self.config.helm_fullname}-postgresql-keycloak": (
                "keycloak",
                self._protected_file("KEYCLOAK_DB_PASSWORD"),
            ),
        }
        if self.config.deployment_profile != "external-services":
            for name, (username, password_file) in basic_auth_sets.items():
                fingerprints[name] = self.kube.ensure_basic_auth_secret(
                    name,
                    username=username,
                    password_file=password_file,
                    component="postgresql",
                )
        tls_sets = {
            self.config.application.ingress_tls_secret: {
                "tls.crt": self._protected_file("tls/active/edge.crt"),
                "tls.key": self._protected_file("tls/active/edge.key"),
            },
            self.config.application.rustfs_tls_secret: {
                "tls.crt": self._protected_file("tls/active/rustfs.crt"),
                "tls.key": self._protected_file("tls/active/rustfs.key"),
                "ca.crt": self._protected_file("tls/active/rustfs-ca.crt"),
            },
            f"{self.config.helm_fullname}-postgresql-tls": {
                "tls.crt": self._protected_file("tls/active/postgresql.crt"),
                "tls.key": self._protected_file("tls/active/postgresql.key"),
                "ca.crt": self._protected_file("tls/active/postgresql-ca.crt"),
            },
            f"{self.config.helm_fullname}-postgresql-replication-tls": {
                "tls.crt": self._protected_file(
                    "tls/active/postgresql-replication.crt"
                ),
                "tls.key": self._protected_file(
                    "tls/active/postgresql-replication.key"
                ),
                "ca.crt": self._protected_file("tls/active/postgresql-ca.crt"),
            },
            f"{self.config.helm_fullname}-redis-tls": {
                "tls.crt": self._protected_file("tls/active/redis.crt"),
                "tls.key": self._protected_file("tls/active/redis.key"),
                "ca.crt": self._protected_file("tls/active/redis-ca.crt"),
            },
            self.config.application.opensearch_tls_secret: {
                "tls.crt": self._protected_file("tls/active/opensearch.crt"),
                "tls.key": self._protected_file("tls/active/opensearch.key"),
                "transport.crt": self._protected_file("tls/active/opensearch-transport.crt"),
                "transport.key": self._protected_file("tls/active/opensearch-transport.key"),
                "ca.crt": self._protected_file("tls/active/opensearch-ca.crt"),
            },
        }
        if self.config.deployment_profile == "external-services":
            # Only the public edge Secret is installer-owned in this profile;
            # external service CA/identity Secrets are operator-owned input.
            tls_sets = {
                self.config.application.ingress_tls_secret: tls_sets[
                    self.config.application.ingress_tls_secret
                ]
            }
        for name, files in tls_sets.items():
            fingerprints[name] = self.kube.ensure_secret(
                name,
                files,
                component="tls",
                secret_type="kubernetes.io/tls",
            )
        inventory_path = self.config.application.state_dir / "credential-inventory.json"
        atomic_private_json(
            inventory_path,
            {
                "schema_version": 1,
                "release": self.config.target.release,
                "namespace": self.config.target.namespace,
                "package_generation": manifest.get("generation_id"),
                "entries": inventory,
                "note": "Values remain only in the owner-controlled package or referenced Secret.",
            },
        )
        return {
            "generation_id": manifest.get("generation_id"),
            "deployment_state": manifest.get("deployment_state"),
            "manifest_sha256": sha256_file(self.current / "manifest.json"),
            "secret_fingerprints": fingerprints,
            "credential_inventory": str(inventory_path),
            "credential_inventory_sha256": sha256_file(inventory_path),
            "tls_source": (manifest.get("certificates") or {}).get("active_source"),
        }

    def verify_evidence(
        self,
        evidence: dict[str, Any],
        *,
        allow_pending_finalization: bool = False,
    ) -> None:
        manifest = self._manifest()
        if (
            manifest.get("generation_id") != evidence.get("generation_id")
            or manifest.get("installer_binding") != self._binding()
        ):
            raise DriftError(
                "generated package generation or target binding differs"
            )
        retired = self.break_glass_retired()
        if not (allow_pending_finalization and retired):
            if (
                sha256_file(self.current / "manifest.json")
                != evidence.get("manifest_sha256")
                or manifest.get("deployment_state")
                != evidence.get("deployment_state")
            ):
                raise DriftError(
                    "generated package manifest fingerprint differs"
                )
        rows = manifest.get("secrets")
        if not isinstance(rows, dict) or not rows:
            raise DriftError("generated package secret inventory is invalid")
        if not isinstance(
            rows.get("break_glass_initial_password"), dict
        ):
            raise DriftError(
                "generated package has no break-glass initial credential"
            )
        for logical, row in rows.items():
            if not isinstance(row, dict) or not isinstance(
                row.get("file"), str
            ):
                raise DriftError(
                    f"generated package secret entry is invalid: {logical}"
                )
            path = self._bounded_path(str(row["file"]))
            if logical == "break_glass_initial_password" and retired:
                if path.exists():
                    if not allow_pending_finalization:
                        raise DriftError(
                            "retired break-glass package value still exists"
                        )
                    self._protected_file(str(row["file"]))
                continue
            path = self._protected_file(str(row["file"]))
            if sha256_file(path) != row.get("sha256"):
                raise DriftError(
                    f"generated package secret fingerprint differs: {logical}"
                )
        inventory_path = (
            self.config.application.state_dir / "credential-inventory.json"
        )
        if (
            not inventory_path.is_file()
            or inventory_path.is_symlink()
            or stat.S_IMODE(inventory_path.stat().st_mode) != 0o600
        ):
            raise DriftError("credential inventory custody is invalid")
        try:
            inventory = json.loads(
                inventory_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise DriftError("credential inventory is invalid") from exc
        if (
            not isinstance(inventory, dict)
            or inventory.get("package_generation")
            != manifest.get("generation_id")
        ):
            raise DriftError(
                "credential inventory package generation differs"
            )
        if (
            not (allow_pending_finalization and retired)
            and sha256_file(inventory_path)
            != evidence.get("credential_inventory_sha256")
        ):
            raise DriftError(
                "credential inventory fingerprint differs"
            )
        self._verify_active_tls()

    def break_glass_retired(self) -> bool:
        try:
            manifest = self._manifest()
        except PreconditionError:
            return False
        row = (manifest.get("secrets") or {}).get(
            "break_glass_initial_password"
        )
        return bool(isinstance(row, dict) and row.get("retired"))

    def mark_finalized(self) -> dict[str, Any]:
        """Retire the first-use value only after live finalization succeeds."""
        manifest = self._manifest()
        row = (manifest.get("secrets") or {}).get(
            "break_glass_initial_password"
        )
        if not isinstance(row, dict):
            raise DriftError(
                "generated package has no break-glass initial credential"
            )
        retired_file: Path | None = None
        if isinstance(row.get("file"), str):
            retired_file = self._bounded_path(str(row["file"]))
        else:
            raise DriftError(
                "generated break-glass credential path is invalid"
            )
        if not row.get("retired"):
            self._protected_file(str(row.get("file") or ""))
            row["retired"] = True
            row["sha256"] = ""
        if manifest.get("deployment_state") not in {
            "operational",
            "acceptance_complete",
        }:
            manifest["deployment_state"] = "operational"
            manifest["finalized_at"] = now()
        atomic_private_json(self.current / "manifest.json", manifest)
        if retired_file is not None:
            if retired_file.is_symlink():
                raise PreconditionError(
                    "refusing to remove a symlinked retired credential"
                )
            retired_file.unlink(missing_ok=True)
        external_runtime = (
            self.config.deployment_profile == "external-services"
            and self.config.application.runtime_secret_mode == "existing"
        )
        if external_runtime:
            # The external profile never mutates an operator-owned runtime
            # Secret.  The Helm finalization Job has already disabled the
            # temporary account; the operator removes this one bootstrap key
            # in the documented follow-up upgrade.  Keep the fingerprint so a
            # resume/verify can prove the Secret was left untouched.
            runtime_fingerprints = self.kube.secret_fingerprints(
                self.config.application.runtime_secret
            )
        else:
            runtime_fingerprints = self.kube.remove_owned_secret_key(
                self.config.application.runtime_secret,
                "BREAK_GLASS_INITIAL_PASSWORD",
            )
        inventory_path = (
            self.config.application.state_dir / "credential-inventory.json"
        )
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PreconditionError("credential inventory is unavailable") from exc
        for entry in inventory.get("entries") or []:
            if (
                isinstance(entry, dict)
                and entry.get("logical_name") == "break_glass_initial_password"
            ):
                entry["state"] = (
                    "operator_remove_after_keycloak_disable"
                    if external_runtime
                    else "retired_after_keycloak_disable"
                )
                entry["finalized_at"] = now()
        inventory["deployment_state"] = "operational"
        atomic_private_json(inventory_path, inventory)
        return {
            "generation_id": manifest.get("generation_id"),
            "deployment_state": "operational",
            "credential_inventory": str(inventory_path),
            "credential_inventory_sha256": sha256_file(inventory_path),
            "break_glass_initial_password_removed": not external_runtime,
            "external_runtime_secret_unchanged": external_runtime,
            "manifest_sha256": sha256_file(
                self.current / "manifest.json"
            ),
            "runtime_secret_fingerprints": runtime_fingerprints,
        }
