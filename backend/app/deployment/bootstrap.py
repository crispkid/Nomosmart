from __future__ import annotations

import argparse
from datetime import UTC, datetime
from ipaddress import ip_network
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Callable, Literal
from urllib.parse import quote, urlparse

import httpx
from neo4j.exceptions import AuthError
from pydantic import Field, SecretStr, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import Settings, create_neo4j_driver
from app.core.readiness_diagnostics import ReadinessDiagnostics, run_check
from app.db.models import IdentitySyncRun
from app.deployment.migration_gate import MigrationGateError, migration_connection, migration_target_detail
from app.integrations.health import DependencyStatus
from app.integrations.keycloak import NOMOSMART_BROWSER_FLOW, KeycloakAdminClient, nomosmart_realm_theme_ready, nomosmart_realm_theme_settings
from app.integrations.redis_ha import redis_client
from app.integrations.s3_storage import S3ObjectStorage
from app.services.audit import add_audit
from app.services.identity_sync import reconcile_snapshot


REQUIRED_TABLES = {
    "deployment_bootstrap_evidence",
    "users",
    "roles",
    "system_parameters",
    "projects",
    "documents",
    "document_versions",
    "ai_models",
    "data_connections",
    "file_scan_runs",
    "outbox_events",
}
BOOTSTRAP_CONTRACT_VERSION = 1
BOOTSTRAP_CHECK_NAMES = {
    "database",
    "redis",
    "s3",
    "opensearch",
    "neo4j",
    "keycloak",
    "oidc",
}
RETIRED_SECURITY_ENV_PREFIXES = ("VAULT_", "CLAMAV_", "MALWARE_SCANNER_")
RETIRED_SECURITY_ENV_NAMES = {
    "QUARANTINE_BUCKET",
    "QUARANTINE_RETENTION_HOURS",
}
REQUIRED_SYSTEM_PARAMETERS = {
    "max_upload_size_mb",
    "default_timezone",
    "staging_index_ttl_days",
    "session_expired_form_draft_ttl_minutes",
}


class DeploymentBootstrapSettings(Settings):
    deployment_keycloak_mode: Literal["manage", "verify"] = "verify"
    keycloak_bootstrap_admin_username: str = ""
    keycloak_bootstrap_admin_password: SecretStr = SecretStr("")
    break_glass_initial_password: SecretStr = SecretStr("")
    opensearch_admin_username: str = "admin"
    opensearch_admin_password: SecretStr = SecretStr("")
    neo4j_admin_username: str = "neo4j"
    neo4j_admin_password: SecretStr = SecretStr("")
    neo4j_community_admin_equivalent_accepted: bool = False
    onboarding_admin_allow_cidr: str = "127.0.0.1/32"
    deployment_phase: Literal["onboarding", "operational", "factory_acceptance"] = "operational"
    local_development_platform: str = "disabled"
    known_local_credential_risk_accepted: bool = False
    local_credential_mode: str = "public-defaults"
    deployment_bootstrap_wait_seconds: int = Field(default=0, ge=0, le=3600)
    deployment_finalization_admin_username: str = ""
    deployment_finalization_admin_group: str = ""

    @model_validator(mode="after")
    def validate_first_use_profile(self) -> "DeploymentBootstrapSettings":
        initial_password = self.break_glass_initial_password.get_secret_value()
        docker_desktop_local = self.local_development_platform == "docker-desktop"
        if self.local_credential_mode not in {"public-defaults", "generated"}:
            raise ValueError("local credential mode is unsupported")
        generated_local = self.local_credential_mode == "generated"
        if generated_local and (self.app_env != "development" or self.deployment_phase != "factory_acceptance"):
            raise ValueError("generated local credentials require development factory_acceptance")
        if self.deployment_phase == "factory_acceptance" and self.app_env != "development":
            raise ValueError("factory_acceptance requires APP_ENV=development")
        if self.app_env == "production" and self.deployment_phase == "factory_acceptance":
            raise ValueError("production cannot use factory_acceptance")
        if docker_desktop_local and (
            self.app_env != "development"
            or self.deployment_phase != "factory_acceptance"
            or (not self.known_local_credential_risk_accepted and not generated_local)
        ):
            raise ValueError(
                "Docker Desktop local credentials require development factory_acceptance with explicit risk acceptance"
            )
        expected_first_use_password = "P@ssw0rd" if docker_desktop_local else "nomosmart"
        if (
            self.deployment_phase in {"onboarding", "factory_acceptance"}
            and not generated_local
            and initial_password != expected_first_use_password
        ):
            raise ValueError("first-use break-glass password does not match the approved deployment profile")
        if generated_local and (len(initial_password) < 16 or initial_password in {"nomosmart", "P@ssw0rd"}):
            raise ValueError("generated local first-use password must be a strong non-public value")
        if self.deployment_phase == "operational" and initial_password in {"nomosmart", "P@ssw0rd"}:
            raise ValueError("operational break-glass password must be rotated")
        if self.app_env == "production" and self.deployment_phase == "onboarding":
            try:
                networks = [
                    ip_network(item.strip(), strict=False)
                    for item in self.onboarding_admin_allow_cidr.split(",")
                    if item.strip()
                ]
            except ValueError as exc:
                raise ValueError("production onboarding admin allowlist must contain valid CIDRs") from exc
            if not networks or any(network.prefixlen == 0 for network in networks):
                raise ValueError("production onboarding requires a restricted admin allowlist")
        if self.app_env == "production":
            cryptographic = [
                initial_password,
                self.app_encryption_key.get_secret_value(),
                self.oidc_client_secret.get_secret_value(),
                self.keycloak_sync_client_secret.get_secret_value(),
            ]
            populated = [value for value in cryptographic if value]
            if len(populated) != len(set(populated)) or "P@ssw0rd" in populated:
                raise ValueError("production human and cryptographic credentials must remain independent from peripheral defaults")
        return self


class BootstrapFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BootstrapCheck:
    name: str
    detail: str


def _release_id(settings: Settings) -> str:
    release_id = settings.deployment_bootstrap_release.strip()
    if not release_id or len(release_id) > 255 or not all(character.isalnum() or character in "._:-" for character in release_id):
        raise BootstrapFailure("deployment_release_invalid")
    return release_id


def _reject_retired_security_environment() -> None:
    if any(
        name in RETIRED_SECURITY_ENV_NAMES
        or name.startswith(RETIRED_SECURITY_ENV_PREFIXES)
        for name in os.environ
    ):
        raise BootstrapFailure("retired_security_contract_environment_detected")


def _database_check(settings: Settings) -> BootstrapCheck:
    try:
        with migration_connection(settings) as connection:
            tables = set(
                connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = current_schema() AND table_name = ANY(:names)"
                    ),
                    {"names": sorted(REQUIRED_TABLES)},
                )
            )
            if tables != REQUIRED_TABLES:
                raise BootstrapFailure("database_schema_incomplete")
            parameters = set(
                connection.scalars(
                    text("SELECT key FROM system_parameters WHERE key = ANY(:keys)"),
                    {"keys": sorted(REQUIRED_SYSTEM_PARAMETERS)},
                )
            )
            if parameters != REQUIRED_SYSTEM_PARAMETERS:
                raise BootstrapFailure("system_parameters_incomplete")
            legacy_secret_refs = int(
                connection.scalar(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM ai_models "
                        " WHERE deleted_at IS NULL AND api_key_secret_ref LIKE 'vault://%') + "
                        "(SELECT count(*) FROM data_connections "
                        " WHERE enabled = true AND credential_secret_ref LIKE 'vault://%')"
                    )
                )
                or 0
            )
            if legacy_secret_refs:
                raise BootstrapFailure("legacy_secret_references_require_migration")
            unfinished_scans = int(
                connection.scalar(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM file_scan_runs "
                        " WHERE status IN ('quarantine', 'queued', 'processing', 'running', 'retry', 'retrying')) + "
                        "(SELECT count(*) FROM outbox_events "
                        " WHERE topic = 'file.scan.requested' "
                        " AND status IN ('pending', 'processing', 'retry', 'retrying'))"
                    )
                )
                or 0
            )
            if unfinished_scans:
                raise BootstrapFailure("legacy_scan_work_requires_resolution")
    except MigrationGateError as exc:
        raise BootstrapFailure(exc.code) from exc
    except BootstrapFailure:
        raise
    except Exception as exc:
        raise BootstrapFailure("database_unavailable") from exc
    return BootstrapCheck("database", migration_target_detail(settings))


def _bootstrap_evidence_check(settings: Settings) -> BootstrapCheck:
    release_id = _release_id(settings)
    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT contract_version, check_names "
                    "FROM deployment_bootstrap_evidence WHERE release_id = :release_id"
                ),
                {"release_id": release_id},
            ).mappings().one_or_none()
    except Exception as exc:
        raise BootstrapFailure("deployment_evidence_unavailable") from exc
    finally:
        engine.dispose()
    if row is None:
        raise BootstrapFailure("deployment_evidence_missing")
    if int(row["contract_version"]) != BOOTSTRAP_CONTRACT_VERSION:
        raise BootstrapFailure("deployment_evidence_incompatible")
    names = row["check_names"]
    if not isinstance(names, list) or set(str(name) for name in names) != BOOTSTRAP_CHECK_NAMES:
        raise BootstrapFailure("deployment_evidence_incomplete")
    return BootstrapCheck("deployment_evidence", "current_release_ready")


def _record_bootstrap_evidence(settings: Settings, checks: list[BootstrapCheck]) -> BootstrapCheck:
    release_id = _release_id(settings)
    check_names = sorted(check.name for check in checks)
    if set(check_names) != BOOTSTRAP_CHECK_NAMES:
        raise BootstrapFailure("deployment_evidence_incomplete")
    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO deployment_bootstrap_evidence "
                    "(release_id, contract_version, check_names) "
                    "VALUES (:release_id, :contract_version, CAST(:check_names AS jsonb)) "
                    "ON CONFLICT (release_id) DO NOTHING"
                ),
                {
                    "release_id": release_id,
                    "contract_version": BOOTSTRAP_CONTRACT_VERSION,
                    "check_names": json.dumps(check_names),
                },
            )
    except Exception as exc:
        raise BootstrapFailure("deployment_evidence_write_failed") from exc
    finally:
        engine.dispose()
    return _bootstrap_evidence_check(settings)


def _redis_check(settings: Settings) -> BootstrapCheck:
    try:
        client = redis_client(settings, socket_timeout=3)
        if client.ping() is not True:
            raise BootstrapFailure("redis_unavailable")
        client.close()
    except BootstrapFailure:
        raise
    except Exception as exc:
        raise BootstrapFailure("redis_unavailable") from exc
    return BootstrapCheck("redis", "reachable")


def _s3_check(settings: Settings, *, ensure: bool) -> BootstrapCheck:
    storage = S3ObjectStorage(settings)
    buckets = (settings.s3_bucket,)
    try:
        for bucket in buckets:
            if not bucket.strip():
                raise BootstrapFailure("s3_bucket_missing")
            if ensure:
                storage.ensure_bucket(bucket)
            elif storage.bucket_status(bucket) != "existing":
                raise BootstrapFailure("s3_bucket_missing")
    except BootstrapFailure:
        raise
    except Exception as exc:
        raise BootstrapFailure("s3_unavailable") from exc
    return BootstrapCheck("s3", "buckets_ready")


def _opensearch_check(settings: Settings) -> BootstrapCheck:
    try:
        response = httpx.get(
            f"{settings.opensearch_url.rstrip('/')}/_cluster/health",
            auth=(settings.opensearch_username.get_secret_value(), settings.opensearch_password.get_secret_value()),
            timeout=5,
            verify=settings.opensearch_httpx_verify,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") not in {"green", "yellow"}:
            raise BootstrapFailure("opensearch_not_ready")
    except BootstrapFailure:
        raise
    except Exception as exc:
        raise BootstrapFailure("opensearch_unavailable") from exc
    return BootstrapCheck("opensearch", "cluster_ready")


def _ensure_opensearch_service_identity(settings: DeploymentBootstrapSettings) -> BootstrapCheck:
    username = settings.opensearch_username.get_secret_value().strip()
    password = settings.opensearch_password.get_secret_value()
    admin_username = settings.opensearch_admin_username.strip()
    admin_password = settings.opensearch_admin_password.get_secret_value()
    if not all((username, password, admin_username, admin_password)) or username == admin_username:
        raise BootstrapFailure("opensearch_service_identity_invalid")
    base_url = settings.opensearch_url.rstrip("/")
    admin_auth = (admin_username, admin_password)
    role = "nomosmart-runtime"
    role_payload = {
        "cluster_permissions": ["cluster_monitor"],
        "index_permissions": [
            {
                "index_patterns": [f"{settings.opensearch_index_prefix}*"],
                "allowed_actions": ["crud", "create_index", "manage"],
            }
        ],
        "tenant_permissions": [],
    }
    try:
        with httpx.Client(timeout=10, verify=settings.opensearch_httpx_verify) as client:
            for path, payload in (
                (f"/_plugins/_security/api/roles/{role}", role_payload),
                (
                    f"/_plugins/_security/api/internalusers/{username}",
                    {"password": password, "backend_roles": [role], "attributes": {}},
                ),
                (
                    f"/_plugins/_security/api/rolesmapping/{role}",
                    {"backend_roles": [role], "hosts": [], "users": [username]},
                ),
            ):
                response = client.put(f"{base_url}{path}", auth=admin_auth, json=payload)
                response.raise_for_status()
    except Exception as exc:
        raise BootstrapFailure("opensearch_service_identity_failed") from exc
    return BootstrapCheck("opensearch_identity", "service_identity_ready")


def _neo4j_check(settings: Settings) -> BootstrapCheck:
    edition = "unknown"
    try:
        driver = create_neo4j_driver(settings)
        driver.verify_connectivity()
        with driver.session(database=settings.neo4j_database) as session:
            session.run("RETURN 1 AS ready").consume()
            component = session.run("CALL dbms.components() YIELD edition RETURN edition").single()
            edition = str(component["edition"] if component is not None else "unknown").lower()
        driver.close()
    except Exception as exc:
        raise BootstrapFailure("neo4j_unavailable") from exc
    detail = "neo4j_community_admin_equivalent" if "community" in edition else f"reachable_{edition}"
    return BootstrapCheck("neo4j", detail)


def _cypher_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise BootstrapFailure("neo4j_service_identity_invalid")
    return f"`{value}`"


def _ensure_neo4j_service_identity(settings: DeploymentBootstrapSettings) -> BootstrapCheck:
    username = settings.neo4j_username.get_secret_value().strip()
    password = settings.neo4j_password.get_secret_value()
    admin_username = settings.neo4j_admin_username.strip()
    admin_password = settings.neo4j_admin_password.get_secret_value()
    if not all((username, password, admin_username, admin_password)) or username == admin_username:
        raise BootstrapFailure("neo4j_service_identity_invalid")
    identifier = _cypher_identifier(username)
    try:
        with create_neo4j_driver(settings, auth=(admin_username, admin_password)) as driver:
            with driver.session(database=settings.neo4j_database) as data_session:
                component = data_session.run("CALL dbms.components() YIELD edition RETURN edition").single()
                edition = str(component["edition"] if component is not None else "").lower()
            if "community" in edition and not settings.neo4j_community_admin_equivalent_accepted:
                raise BootstrapFailure("neo4j_community_admin_equivalent_risk_not_accepted")
            with driver.session(database="system") as session:
                exists = session.run("SHOW USERS YIELD user WHERE user = $username RETURN count(*) AS count", username=username).single()
                if exists is None or int(exists["count"]) == 0:
                    session.run(
                        f"CREATE USER {identifier} SET PLAINTEXT PASSWORD $password CHANGE NOT REQUIRED",
                        password=password,
                    ).consume()
                else:
                    try:
                        with create_neo4j_driver(settings, auth=(username, password)) as service_driver:
                            service_driver.verify_connectivity()
                    except AuthError:
                        session.run(
                            f"ALTER USER {identifier} SET PLAINTEXT PASSWORD $password CHANGE NOT REQUIRED",
                            password=password,
                        ).consume()
                if "enterprise" in edition:
                    session.run(f"GRANT ROLE editor TO {identifier}").consume()
    except BootstrapFailure:
        raise
    except Exception as exc:
        raise BootstrapFailure("neo4j_service_identity_failed") from exc
    detail = "community_admin_equivalent_accepted" if "community" in edition else "service_identity_ready"
    return BootstrapCheck("neo4j_identity", detail)


def _realm_name(settings: Settings) -> str:
    path = urlparse(settings.oidc_issuer_url).path.rstrip("/")
    marker = "/realms/"
    if marker not in path:
        raise BootstrapFailure("oidc_issuer_invalid")
    realm = path.rsplit(marker, 1)[-1]
    if not realm or "/" in realm:
        raise BootstrapFailure("oidc_issuer_invalid")
    return realm


def _oidc_discovery_check(settings: Settings) -> BootstrapCheck:
    issuer = settings.oidc_issuer_url.rstrip("/")
    try:
        response = httpx.get(settings.oidc_discovery_endpoint, timeout=5, follow_redirects=False)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or str(payload.get("issuer") or "").rstrip("/") != issuer:
            raise BootstrapFailure("oidc_discovery_invalid")
        if not payload.get("jwks_uri") and not settings.oidc_jwks_url.strip():
            raise BootstrapFailure("oidc_discovery_invalid")
    except BootstrapFailure:
        raise
    except Exception as exc:
        raise BootstrapFailure("oidc_unavailable") from exc
    return BootstrapCheck("oidc", "discovery_ready")


class _KeycloakBootstrapClient:
    def __init__(self, settings: DeploymentBootstrapSettings) -> None:
        self.settings = settings
        self.base_url = settings.keycloak_admin_endpoint.rstrip("/")
        self.realm = _realm_name(settings)
        self.client = httpx.Client(timeout=10, follow_redirects=False)
        try:
            self.token = self._admin_token()
            self.using_bootstrap_admin = True
        except BootstrapFailure as exc:
            if exc.code not in {"keycloak_bootstrap_admin_missing", "keycloak_bootstrap_auth_failed"}:
                raise
            self.token = self._service_token()
            self.using_bootstrap_admin = False

    def close(self) -> None:
        self.client.close()

    def _admin_token(self) -> str:
        username = self.settings.keycloak_bootstrap_admin_username.strip()
        password = self.settings.keycloak_bootstrap_admin_password.get_secret_value()
        if not username or not password:
            raise BootstrapFailure("keycloak_bootstrap_admin_missing")
        try:
            response = self.client.post(
                f"{self.base_url}/realms/master/protocol/openid-connect/token",
                data={"grant_type": "password", "client_id": "admin-cli", "username": username, "password": password},
            )
            response.raise_for_status()
            token = response.json().get("access_token")
        except Exception as exc:
            raise BootstrapFailure("keycloak_bootstrap_auth_failed") from exc
        if not isinstance(token, str) or not token:
            raise BootstrapFailure("keycloak_bootstrap_auth_failed")
        return token

    def _service_token(self) -> str:
        client_id = self.settings.keycloak_sync_client_id.strip()
        client_secret = self.settings.keycloak_sync_client_secret.get_secret_value()
        if not client_id or not client_secret:
            raise BootstrapFailure("keycloak_management_identity_missing")
        try:
            response = self.client.post(
                f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token",
                data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            )
            response.raise_for_status()
            token = response.json().get("access_token")
        except Exception as exc:
            raise BootstrapFailure("keycloak_management_auth_failed") from exc
        if not isinstance(token, str) or not token:
            raise BootstrapFailure("keycloak_management_auth_failed")
        return token

    def disable_bootstrap_admin(self) -> None:
        if not self.using_bootstrap_admin:
            return
        username = self.settings.keycloak_bootstrap_admin_username.strip()
        response = self.client.get(
            f"{self.base_url}/admin/realms/master/users",
            headers=self.headers,
            params={"username": username, "exact": "true", "max": 2},
        )
        if response.status_code != 200:
            raise BootstrapFailure("keycloak_bootstrap_admin_disable_failed")
        users = response.json()
        matches = [row for row in users if isinstance(row, dict) and str(row.get("username") or "") == username]
        if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
            raise BootstrapFailure("keycloak_bootstrap_admin_invalid")
        user_id = str(matches[0]["id"])
        payload = dict(matches[0])
        payload["enabled"] = False
        self._request("PUT", f"/admin/realms/master/users/{user_id}", payload=payload)
        self._request("POST", f"/admin/realms/master/users/{user_id}/logout")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, path: str, *, payload: object | None = None, expected: set[int] | None = None) -> httpx.Response:
        try:
            response = self.client.request(method, f"{self.base_url}{path}", headers=self.headers, json=payload)
        except httpx.HTTPError as exc:
            raise BootstrapFailure("keycloak_unavailable") from exc
        allowed = expected or {200, 201, 204}
        if response.status_code not in allowed:
            raise BootstrapFailure("keycloak_admin_request_failed")
        return response

    def ensure_realm(self) -> None:
        theme_settings = nomosmart_realm_theme_settings()
        response = self._request("GET", f"/admin/realms/{self.realm}", expected={200, 404})
        if response.status_code == 404:
            self._request(
                "POST",
                "/admin/realms",
                payload={"realm": self.realm, "enabled": True, "registrationAllowed": False, **theme_settings},
            )
            self.ensure_password_only_browser_flow()
            return
        payload = response.json()
        if not isinstance(payload, dict):
            raise BootstrapFailure("keycloak_response_invalid")
        if not payload.get("enabled", False):
            raise BootstrapFailure("keycloak_realm_incompatible")
        if not nomosmart_realm_theme_ready(payload) or payload.get("registrationAllowed") is not False:
            self._request("PUT", f"/admin/realms/{self.realm}", payload={**payload, **theme_settings, "registrationAllowed": False})
        self.ensure_password_only_browser_flow()
        updated = self._request("GET", f"/admin/realms/{self.realm}").json()
        if (
            not isinstance(updated, dict)
            or not updated.get("enabled", False)
            or updated.get("registrationAllowed") is not False
            or updated.get("browserFlow") != NOMOSMART_BROWSER_FLOW
            or not nomosmart_realm_theme_ready(updated)
        ):
            raise BootstrapFailure("keycloak_realm_incompatible")

    def ensure_password_only_browser_flow(self) -> None:
        realm_path = f"/admin/realms/{self.realm}"
        realm = self._request("GET", realm_path).json()
        flows = self._request("GET", f"{realm_path}/authentication/flows").json()
        if not isinstance(realm, dict) or not isinstance(flows, list):
            raise BootstrapFailure("keycloak_response_invalid")
        managed = [row for row in flows if isinstance(row, dict) and row.get("alias") == NOMOSMART_BROWSER_FLOW]
        if not managed:
            source_alias = str(realm.get("browserFlow") or "browser")
            self._request(
                "POST",
                f"{realm_path}/authentication/flows/{quote(source_alias, safe='')}/copy",
                payload={"newName": NOMOSMART_BROWSER_FLOW},
            )
        executions_path = f"{realm_path}/authentication/flows/{quote(NOMOSMART_BROWSER_FLOW, safe='')}/executions"
        executions = self._request("GET", executions_path).json()
        if not isinstance(executions, list):
            raise BootstrapFailure("keycloak_response_invalid")
        for execution in executions:
            if not isinstance(execution, dict):
                continue
            identity = " ".join(
                str(execution.get(key) or "")
                for key in ("providerId", "displayName", "flowAlias")
            ).casefold()
            execution_id = execution.get("id")
            if "otp" in identity and isinstance(execution_id, str) and execution_id:
                self._request("DELETE", f"{realm_path}/authentication/executions/{execution_id}")
        verified = self._request("GET", executions_path).json()
        if not isinstance(verified, list) or any(
            "otp" in " ".join(str(row.get(key) or "") for key in ("providerId", "displayName", "flowAlias")).casefold()
            for row in verified
            if isinstance(row, dict)
        ):
            raise BootstrapFailure("keycloak_password_only_flow_incompatible")
        self._request(
            "PUT",
            realm_path,
            payload={**realm, **nomosmart_realm_theme_settings(), "registrationAllowed": False, "browserFlow": NOMOSMART_BROWSER_FLOW},
        )
        self.remove_totp_required_actions()

    def remove_totp_required_actions(self) -> None:
        """Retire only the TOTP action while preserving every unrelated user action."""

        first = 0
        page_size = 100
        while True:
            payload = self._request(
                "GET",
                f"/admin/realms/{self.realm}/users?first={first}&max={page_size}",
            ).json()
            if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
                raise BootstrapFailure("keycloak_response_invalid")
            for user in payload:
                actions = [str(action) for action in (user.get("requiredActions") or []) if action]
                if "CONFIGURE_TOTP" not in actions:
                    continue
                user_id = user.get("id")
                if not isinstance(user_id, str) or not user_id:
                    raise BootstrapFailure("keycloak_response_invalid")
                self._request(
                    "PUT",
                    f"/admin/realms/{self.realm}/users/{user_id}",
                    payload={
                        **user,
                        "requiredActions": [
                            action for action in actions if action != "CONFIGURE_TOTP"
                        ],
                    },
                )
            if len(payload) < page_size:
                return
            first += page_size

    @staticmethod
    def _flatten_groups(groups: list[dict[str, object]]) -> list[dict[str, object]]:
        flattened: list[dict[str, object]] = []

        def visit(group: dict[str, object], parent_path: str = "") -> None:
            row = dict(group)
            children = row.pop("subGroups", [])
            name = str(row.get("name") or "")
            row["path"] = row.get("path") or f"{parent_path}/{name}"
            flattened.append(row)
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        visit(child, str(row["path"]))

        for group in groups:
            visit(group)
        return flattened

    def _groups(self) -> list[dict[str, object]]:
        payload = self._request("GET", f"/admin/realms/{self.realm}/groups?max=1000&briefRepresentation=false").json()
        if not isinstance(payload, list):
            raise BootstrapFailure("keycloak_response_invalid")
        return self._flatten_groups([row for row in payload if isinstance(row, dict)])

    def ensure_group_path(self, path: str) -> str:
        normalized = path.rstrip("/")
        parent_id: str | None = None
        current_path = ""
        for segment in normalized.strip("/").split("/"):
            current_path = f"{current_path}/{segment}"
            match = next((row for row in self._groups() if str(row.get("path") or "") == current_path), None)
            if match is None:
                if parent_id is None:
                    self._request("POST", f"/admin/realms/{self.realm}/groups", payload={"name": segment})
                else:
                    self._request("POST", f"/admin/realms/{self.realm}/groups/{parent_id}/children", payload={"name": segment})
                match = next((row for row in self._groups() if str(row.get("path") or "") == current_path), None)
            group_id = match.get("id") if isinstance(match, dict) else None
            if not isinstance(group_id, str) or not group_id:
                raise BootstrapFailure("keycloak_group_invalid")
            parent_id = group_id
        if parent_id is None:
            raise BootstrapFailure("keycloak_group_invalid")
        return parent_id

    def ensure_group(self, name: str) -> None:
        self.ensure_group_path(f"/{name.strip('/')}")

    def ensure_ldap_group_mapper_path(self, path: str) -> None:
        self.ensure_group_path(path)
        component_type = "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
        providers_payload = self._request("GET", f"/admin/realms/{self.realm}/components?type=org.keycloak.storage.UserStorageProvider").json()
        if not isinstance(providers_payload, list):
            raise BootstrapFailure("keycloak_response_invalid")
        ldap_providers = [row for row in providers_payload if isinstance(row, dict) and row.get("providerId") == "ldap" and isinstance(row.get("id"), str)]
        if len(ldap_providers) != 1:
            raise BootstrapFailure("keycloak_ldap_provider_invalid")
        provider_id = str(ldap_providers[0]["id"])
        payload = self._request("GET", f"/admin/realms/{self.realm}/components?parent={provider_id}&type={component_type}").json()
        if not isinstance(payload, list):
            raise BootstrapFailure("keycloak_response_invalid")
        mappers = [row for row in payload if isinstance(row, dict) and row.get("providerId") == "group-ldap-mapper"]
        if len(mappers) != 1 or not isinstance(mappers[0].get("id"), str):
            raise BootstrapFailure("keycloak_ldap_group_mapper_invalid")
        mapper = dict(mappers[0])
        config = dict(mapper.get("config") or {})
        current = config.get("groups.path")
        actual = str(current[0] if isinstance(current, list) and current else current or "").rstrip("/") or "/"
        expected = path.rstrip("/") or "/"
        if actual != expected:
            config["groups.path"] = [expected]
            mapper["config"] = config
            self._request("PUT", f"/admin/realms/{self.realm}/components/{mapper['id']}", payload=mapper)
        verified = self._request("GET", f"/admin/realms/{self.realm}/components/{mapper['id']}").json()
        verified_config = verified.get("config") if isinstance(verified, dict) and isinstance(verified.get("config"), dict) else {}
        verified_value = verified_config.get("groups.path")
        verified_path = str(verified_value[0] if isinstance(verified_value, list) and verified_value else verified_value or "").rstrip("/") or "/"
        if verified_path != expected:
            raise BootstrapFailure("keycloak_ldap_group_path_mismatch")

    def _client_rows(self, client_id: str) -> list[dict[str, object]]:
        response = self._request("GET", f"/admin/realms/{self.realm}/clients?clientId={client_id}")
        payload = response.json()
        if not isinstance(payload, list):
            raise BootstrapFailure("keycloak_response_invalid")
        return [item for item in payload if isinstance(item, dict) and item.get("clientId") == client_id]

    def ensure_client(self, payload: dict[str, object]) -> str:
        client_id = str(payload["clientId"])
        rows = self._client_rows(client_id)
        if not rows:
            self._request("POST", f"/admin/realms/{self.realm}/clients", payload=payload)
            rows = self._client_rows(client_id)
        if len(rows) != 1 or not isinstance(rows[0].get("id"), str):
            raise BootstrapFailure("keycloak_client_invalid")
        existing = rows[0]
        for key in ("enabled", "publicClient", "standardFlowEnabled", "directAccessGrantsEnabled", "serviceAccountsEnabled"):
            if bool(existing.get(key, False)) != bool(payload.get(key, False)):
                raise BootstrapFailure("keycloak_client_incompatible")
        requires_update = False
        merged = dict(existing)
        for key in ("redirectUris", "webOrigins"):
            required = {str(item) for item in payload.get(key, []) if item}
            actual = {str(item) for item in existing.get(key, []) if item}
            if not required.issubset(actual):
                merged[key] = sorted(actual | required)
                requires_update = True
        if requires_update:
            self._request("PUT", f"/admin/realms/{self.realm}/clients/{existing['id']}", payload=merged)
            rows = self._client_rows(client_id)
            if len(rows) != 1:
                raise BootstrapFailure("keycloak_client_invalid")
            existing = rows[0]
            for key in ("redirectUris", "webOrigins"):
                required = {str(item) for item in payload.get(key, []) if item}
                actual = {str(item) for item in existing.get(key, []) if item}
                if not required.issubset(actual):
                    raise BootstrapFailure("keycloak_client_incompatible")
        return str(existing["id"])

    def ensure_audience_mapper(self, frontend_internal_id: str) -> None:
        path = f"/admin/realms/{self.realm}/clients/{frontend_internal_id}/protocol-mappers/models"
        response = self._request("GET", path)
        rows = response.json()
        expected = {
            "name": "nomosmart-backend-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {
                "included.client.audience": self.settings.oidc_audience,
                "id.token.claim": "false",
                "access.token.claim": "true",
            },
        }
        match = next((row for row in rows if isinstance(row, dict) and row.get("name") == expected["name"]), None)
        if match is None:
            self._request("POST", path, payload=expected)
            return
        config = match.get("config") if isinstance(match.get("config"), dict) else {}
        if config.get("included.client.audience") != self.settings.oidc_audience:
            raise BootstrapFailure("keycloak_mapper_incompatible")

    def ensure_sync_service_roles(self, sync_internal_id: str) -> None:
        service_user = self._request(
            "GET",
            f"/admin/realms/{self.realm}/clients/{sync_internal_id}/service-account-user",
        ).json()
        service_user_id = service_user.get("id") if isinstance(service_user, dict) else None
        realm_management = self._client_rows("realm-management")
        if not isinstance(service_user_id, str) or len(realm_management) != 1 or not isinstance(realm_management[0].get("id"), str):
            raise BootstrapFailure("keycloak_service_account_invalid")
        management_id = str(realm_management[0]["id"])
        desired: list[dict[str, object]] = []
        for role_name in (
            "query-users",
            "view-users",
            "manage-users",
            "view-clients",
            "manage-clients",
            "view-realm",
            "manage-realm",
        ):
            role = self._request(
                "GET",
                f"/admin/realms/{self.realm}/clients/{management_id}/roles/{role_name}",
            ).json()
            if not isinstance(role, dict) or not role.get("id"):
                raise BootstrapFailure("keycloak_service_role_missing")
            desired.append(role)
        self._request(
            "POST",
            f"/admin/realms/{self.realm}/users/{service_user_id}/role-mappings/clients/{management_id}",
            payload=desired,
        )

    def verify_client_secret(self, client_id: str, secret: str) -> None:
        try:
            response = self.client.post(
                f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token",
                data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
            )
        except httpx.HTTPError as exc:
            raise BootstrapFailure("keycloak_client_auth_failed") from exc
        if response.status_code >= 400:
            raise BootstrapFailure("keycloak_client_auth_failed")


def _keycloak_manage(settings: DeploymentBootstrapSettings) -> BootstrapCheck:
    if not settings.break_glass_username.strip() or not settings.break_glass_runbook_uri.strip() or not settings.break_glass_alerting_evidence.strip():
        raise BootstrapFailure("break_glass_evidence_missing")
    manager = _KeycloakBootstrapClient(settings)
    try:
        manager.ensure_realm()
        manager.ensure_group(settings.break_glass_system_admin_group)
        if settings.deployment_phase == "operational":
            manager.ensure_ldap_group_mapper_path(settings.keycloak_ldap_group_path)
        origin = settings.frontend_app_origin.rstrip("/")
        frontend_id = manager.ensure_client(
            {
                "clientId": settings.oidc_frontend_client_id,
                "name": "NomoSmart Frontend",
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": True,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": False,
                "redirectUris": [
                    f"{origin}/auth/callback",
                    f"{origin}/login",
                    f"{origin}/api/backend/system/identity-settings/reauth/callback",
                ],
                "webOrigins": [origin],
                "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": f"{origin}/login"},
            }
        )
        manager.ensure_audience_mapper(frontend_id)
        for client_id, secret in (
            (settings.oidc_client_id, settings.oidc_client_secret.get_secret_value()),
            (settings.keycloak_sync_client_id, settings.keycloak_sync_client_secret.get_secret_value()),
        ):
            if not secret:
                raise BootstrapFailure("keycloak_client_secret_missing")
            internal_id = manager.ensure_client(
                {
                    "clientId": client_id,
                    "enabled": True,
                    "protocol": "openid-connect",
                    "publicClient": False,
                    "standardFlowEnabled": False,
                    "directAccessGrantsEnabled": False,
                    "serviceAccountsEnabled": True,
                    "secret": secret,
                    "redirectUris": [],
                    "webOrigins": [],
                }
            )
            if client_id == settings.keycloak_sync_client_id:
                manager.ensure_sync_service_roles(internal_id)
            manager.verify_client_secret(client_id, secret)
        identity_client = KeycloakAdminClient(
            base_url=settings.keycloak_admin_endpoint,
            realm=_realm_name(settings),
            client_id=settings.keycloak_sync_client_id,
            client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
        )
        try:
            identity_client.ensure_break_glass_user(
                username=settings.break_glass_username,
                initial_password=settings.break_glass_initial_password.get_secret_value() or None,
                system_admin_group=settings.break_glass_system_admin_group,
                enabled=settings.deployment_phase in {"onboarding", "factory_acceptance"},
            )
        except Exception as exc:
            raise BootstrapFailure("break_glass_provisioning_failed") from exc
        _reconcile_identity_database(settings, client=identity_client)
        # The initial administrator is disabled only after the replacement
        # management identity, break-glass account, and database reconciliation
        # have all succeeded.
        manager.disable_bootstrap_admin()
    finally:
        manager.close()
    detail = "realm_clients_onboarding_ready" if settings.deployment_phase != "operational" else "realm_clients_identity_ready"
    return BootstrapCheck("keycloak", detail)


def _keycloak_verify(settings: DeploymentBootstrapSettings) -> BootstrapCheck:
    if not settings.break_glass_username.strip() or not settings.break_glass_runbook_uri.strip() or not settings.break_glass_alerting_evidence.strip():
        raise BootstrapFailure("break_glass_evidence_missing")
    client = KeycloakAdminClient(
        base_url=settings.keycloak_admin_endpoint,
        realm=_realm_name(settings),
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
    )
    try:
        client.verify_initialization_resources(
            frontend_client_id=settings.oidc_frontend_client_id,
            confidential_client_ids=(settings.oidc_client_id, settings.keycloak_sync_client_id),
            audience=settings.oidc_audience,
            frontend_origin=settings.frontend_app_origin,
            system_admin_group=settings.break_glass_system_admin_group,
        )
        if settings.deployment_phase == "operational":
            client.verify_ldap_group_mapper_path(settings.keycloak_ldap_group_path)
    except Exception as exc:
        raise BootstrapFailure("keycloak_resources_unavailable") from exc
    _reconcile_identity_database(settings, client=client)
    return BootstrapCheck("keycloak", "realm_clients_identity_verified")


def _reconcile_identity_database(settings: DeploymentBootstrapSettings, *, client: KeycloakAdminClient | None = None) -> None:
    identity_client = client or KeycloakAdminClient(
        base_url=settings.keycloak_admin_endpoint,
        realm=_realm_name(settings),
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
    )
    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        snapshot = identity_client.snapshot()
        with Session(engine) as session:
            run = IdentitySyncRun(
                source="keycloak",
                status="running",
                trigger_type="deployment",
                requested_scope="people_and_groups",
                phase="reconciliation",
                started_at=datetime.now(UTC),
                users_created=0,
                users_updated=0,
                users_disabled=0,
                groups_created=0,
                groups_updated=0,
                role_memberships_updated=0,
                attempt=1,
            )
            session.add(run)
            session.flush()
            reconcile_snapshot(
                session,
                run,
                snapshot,
                ldap_group_path=settings.keycloak_ldap_group_path,
                break_glass_username=settings.break_glass_username,
            )
            add_audit(
                session,
                actor_user_id=None,
                action="deployment.identity.reconcile",
                resource_type="identity_sync_run",
                resource_id=run.id,
                result="success",
                request_id=None,
                summary={"trigger_type": "deployment"},
            )
            session.commit()
    except Exception as exc:
        raise BootstrapFailure("keycloak_identity_reconciliation_failed") from exc
    finally:
        engine.dispose()


def run_bootstrap(settings: DeploymentBootstrapSettings, *, ensure: bool) -> list[BootstrapCheck]:
    _release_id(settings)
    _reject_retired_security_environment()
    database_check = _database_check(settings)
    if ensure:
        _ensure_opensearch_service_identity(settings)
        _ensure_neo4j_service_identity(settings)
    checks = [
        database_check,
        _redis_check(settings),
        _s3_check(settings, ensure=ensure),
        _opensearch_check(settings),
        _neo4j_check(settings),
    ]
    if ensure and settings.deployment_keycloak_mode == "manage":
        checks.append(_keycloak_manage(settings))
    else:
        checks.append(_keycloak_verify(settings))
    checks.append(_oidc_discovery_check(settings))
    if ensure:
        checks.append(_record_bootstrap_evidence(settings, checks))
    else:
        checks.append(_bootstrap_evidence_check(settings))
    return checks


def _verify_finalization_database_evidence(
    settings: Settings,
    *,
    break_glass_keycloak_user_id: str,
    federated_admin_keycloak_user_id: str | None,
) -> None:
    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            break_glass_id = connection.scalar(
                text("SELECT id FROM users WHERE keycloak_user_id = :keycloak_user_id AND is_active = true"),
                {"keycloak_user_id": break_glass_keycloak_user_id},
            )
            if break_glass_id is None:
                raise BootstrapFailure("break_glass_identity_not_synchronized")
            login_seen = connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM audit_logs "
                    "WHERE actor_user_id = :user_id AND action = 'auth.login.success' AND result = 'success')"
                ),
                {"user_id": break_glass_id},
            )
            if not login_seen:
                raise BootstrapFailure("break_glass_login_evidence_missing")
            membership = connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM role_users ru JOIN roles r ON r.id = ru.role_id "
                    "WHERE ru.user_id = :user_id AND ru.source = 'break_glass' "
                    "AND r.name = 'system-admin' AND r.is_active = true AND r.deleted_at IS NULL)"
                ),
                {"user_id": break_glass_id},
            )
            if not membership:
                raise BootstrapFailure("break_glass_membership_evidence_missing")
            if settings.app_env == "production":
                if not federated_admin_keycloak_user_id:
                    raise BootstrapFailure("federated_admin_identity_missing")
                directory_sync = connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM identity_sync_runs "
                        "WHERE source = 'keycloak' AND status = 'succeeded' "
                        "AND trigger_type IN ('deployment', 'manual', 'scheduled'))"
                    )
                )
                directory_user = connection.scalar(text("SELECT EXISTS (SELECT 1 FROM users WHERE auth_source = 'ldap' AND is_active = true)"))
                federated_admin = connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM role_users ru "
                        "JOIN roles r ON r.id = ru.role_id JOIN users u ON u.id = ru.user_id "
                        "WHERE u.keycloak_user_id = :federated_admin_keycloak_user_id "
                        "AND ru.source = 'external_sync' "
                        "AND r.name = 'system-admin' AND r.is_active = true AND r.deleted_at IS NULL "
                        "AND u.is_active = true AND u.auth_source = 'ldap')"
                    ),
                    {"federated_admin_keycloak_user_id": federated_admin_keycloak_user_id},
                )
                federated_login = connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM audit_logs a "
                        "JOIN users u ON u.id = a.actor_user_id "
                        "WHERE u.keycloak_user_id = :federated_admin_keycloak_user_id "
                        "AND a.action = 'auth.login.success' AND a.result = 'success')"
                    ),
                    {
                        "federated_admin_keycloak_user_id": (
                            federated_admin_keycloak_user_id
                        )
                    },
                )
                if not directory_sync or not directory_user:
                    raise BootstrapFailure("directory_initial_sync_evidence_missing")
                if not federated_admin:
                    raise BootstrapFailure("non_break_glass_system_admin_missing")
                if not federated_login:
                    raise BootstrapFailure("federated_admin_login_evidence_missing")
    except BootstrapFailure:
        raise
    except Exception as exc:
        raise BootstrapFailure("deployment_finalization_evidence_unavailable") from exc
    finally:
        engine.dispose()


def finalize_deployment(settings: DeploymentBootstrapSettings) -> list[BootstrapCheck]:
    if settings.deployment_phase not in {"onboarding", "factory_acceptance"}:
        raise BootstrapFailure("deployment_phase_not_finalizable")
    client = KeycloakAdminClient(
        base_url=settings.keycloak_admin_endpoint,
        realm=_realm_name(settings),
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
    )
    try:
        break_glass_keycloak_user_id = client.verify_break_glass_onboarding_complete(
            settings.break_glass_username,
            system_admin_group=settings.break_glass_system_admin_group,
            # Retrying after the account was disabled but before the audit row
            # committed must remain safe and idempotent.
            allow_disabled=True,
        )
        federated_admin_keycloak_user_id: str | None = None
        if settings.app_env == "production":
            if not settings.deployment_finalization_admin_username.strip() or not settings.deployment_finalization_admin_group.strip():
                raise BootstrapFailure("federated_admin_finalization_config_missing")
            federated_admin_keycloak_user_id = client.verify_federated_admin_onboarding_complete(
                settings.deployment_finalization_admin_username,
                external_group=settings.deployment_finalization_admin_group,
            )
            client.verify_ldap_group_mapper_path(settings.keycloak_ldap_group_path)
        _reconcile_identity_database(settings, client=client)
        _verify_finalization_database_evidence(
            settings,
            break_glass_keycloak_user_id=break_glass_keycloak_user_id,
            federated_admin_keycloak_user_id=federated_admin_keycloak_user_id,
        )
        # Mutation occurs only after every Keycloak and database precondition passes.
        client.disable_break_glass_user(settings.break_glass_username)
    except BootstrapFailure:
        raise
    except Exception as exc:
        raise BootstrapFailure("deployment_finalization_failed") from exc

    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        with Session(engine) as session:
            add_audit(
                session,
                actor_user_id=None,
                action="deployment.first_use.finalized",
                resource_type="deployment",
                resource_id=None,
                result="success",
                request_id=None,
                summary={
                    "release_id": _release_id(settings),
                    "completion_state": "operational" if settings.app_env == "production" else "acceptance_complete",
                },
            )
            session.commit()
    except Exception as exc:
        raise BootstrapFailure("deployment_finalization_audit_failed") from exc
    finally:
        engine.dispose()
    return [
        BootstrapCheck("break_glass", "disabled_sessions_revoked"),
        BootstrapCheck("deployment", "operational" if settings.app_env == "production" else "acceptance_complete"),
    ]


def _runtime_bootstrap_check(name: str, callback: Callable[[], BootstrapCheck]) -> DependencyStatus:
    try:
        check = callback()
        return DependencyStatus(name, True, check.detail if name == "deployment.database" else "ready")
    except BootstrapFailure as exc:
        return DependencyStatus(name, False, exc.code)


def runtime_bootstrap_status(settings: Settings, *, recorder: ReadinessDiagnostics | None = None) -> list[DependencyStatus]:
    checks: tuple[tuple[str, Callable[[], BootstrapCheck]], ...] = (
        ("deployment.evidence", lambda: _bootstrap_evidence_check(settings)),
        ("deployment.database", lambda: _database_check(settings)),
        ("deployment.s3", lambda: _s3_check(settings, ensure=False)),
        ("deployment.oidc", lambda: _oidc_discovery_check(settings)),
    )
    statuses: list[DependencyStatus] = []
    for name, callback in checks:
        statuses.append(run_check(recorder, name, lambda: _runtime_bootstrap_check(name, callback)))
    return statuses


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NomoSmart deployment bootstrap")
    parser.add_argument("--mode", choices=("ensure", "check", "finalize"), default="ensure")
    parser.add_argument("--wait-seconds", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        settings = DeploymentBootstrapSettings()
    except ValueError:
        print(json.dumps({"status": "failed", "code": "deployment_configuration_invalid"}), file=sys.stderr)
        return 1
    wait_seconds = settings.deployment_bootstrap_wait_seconds if args.wait_seconds is None else max(0, args.wait_seconds)
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            checks = finalize_deployment(settings) if args.mode == "finalize" else run_bootstrap(settings, ensure=args.mode == "ensure")
            print(json.dumps({"status": "ready", "mode": args.mode, "checks": [asdict(check) for check in checks]}, sort_keys=True))
            return 0
        except BootstrapFailure as exc:
            if time.monotonic() >= deadline:
                print(json.dumps({"status": "failed", "mode": args.mode, "code": exc.code}, sort_keys=True), file=sys.stderr)
                return 1
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
