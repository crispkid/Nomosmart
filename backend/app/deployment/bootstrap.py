from __future__ import annotations

import argparse
from ipaddress import ip_network
from pathlib import Path
from uuid import UUID
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Callable, Literal

import httpx
from neo4j.exceptions import AuthError
from pydantic import Field, SecretStr, model_validator
from sqlalchemy import create_engine, select, text

from app.core.config import Settings, create_neo4j_driver
from app.core.errors import AppError
from app.core.readiness_diagnostics import ReadinessDiagnostics, run_check
from app.deployment.migration_gate import MigrationGateError, migration_connection, migration_target_detail
from app.integrations.health import DependencyStatus
from app.integrations.redis_ha import redis_client
from app.integrations.s3_storage import S3ObjectStorage
from app.services.audit import add_audit


REQUIRED_TABLES = {
    "deployment_bootstrap_evidence",
    "users",
    "roles",
    "system_parameters",
    "system_parameter_section_revisions",
    "staging_retention_jobs",
    "projects",
    "documents",
    "document_versions",
    "ai_models",
    "data_connections",
    "file_scan_runs",
    "outbox_events",
}
BOOTSTRAP_CONTRACT_VERSION = 2
BOOTSTRAP_CHECK_NAMES = {
    "database",
    "redis",
    "s3",
    "opensearch",
    "neo4j",
    "authentication",
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
    "ocr_page_max_output_tokens",
    "ocr_request_max_output_tokens",
    "ocr_document_max_tokens",
}


class DeploymentBootstrapSettings(Settings):
    deployment_profile: Literal["auto", "bundled", "external-services"] = "auto"
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
            if connection.scalar(text("SELECT count(*) FROM system_parameter_section_revisions WHERE section IN ('general','documents') AND revision > 0")) != 2:
                raise BootstrapFailure("system_parameter_revisions_incomplete")
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














def run_bootstrap(settings: DeploymentBootstrapSettings, *, ensure: bool) -> list[BootstrapCheck]:
    _release_id(settings)
    _reject_retired_security_environment()
    database_check = _database_check(settings)
    provision_external = ensure and settings.deployment_profile != "external-services"
    if provision_external:
        _ensure_opensearch_service_identity(settings)
        _ensure_neo4j_service_identity(settings)
    checks = [
        database_check,
        _redis_check(settings),
        _s3_check(settings, ensure=provision_external),
        _opensearch_check(settings),
        _neo4j_check(settings),
    ]
    checks.append(_protocol_authentication_check(settings, ensure=ensure))
    if ensure:
        checks.append(_record_bootstrap_evidence(settings, checks))
    else:
        checks.append(_bootstrap_evidence_check(settings))
    return checks




def finalize_deployment(settings: DeploymentBootstrapSettings) -> list[BootstrapCheck]:
    from app.deployment.protocol_status import normal_admin_evidence
    from app.deployment.protocol_bootstrap import emergency_disable
    from app.db.session import get_session_factory
    try:
        with get_session_factory().begin() as session:
            evidence = normal_admin_evidence(session)
            emergency_disable(session)
            from app.security.auth_configuration import current_setting
            add_audit(session, actor_user_id=UUID(evidence["admin_user_id"]), action="auth.onboarding.completed", resource_type="identity_settings", resource_id=current_setting(session).id, result="success", request_id=None, summary={"mode": evidence["mode"], "sync_run_id": evidence["sync_run_id"]})
    except AppError as exc:
        raise BootstrapFailure(exc.code) from exc
    return [BootstrapCheck("authentication", "normal_administrator_verified"), BootstrapCheck("break_glass", "disabled_sessions_revoked")]


def _protocol_authentication_check(settings: Settings, *, ensure: bool = False) -> BootstrapCheck:
    from app.deployment.protocol_status import configuration_status
    from app.db.session import get_session_factory
    from app.security.auth_configuration import ProtocolConfiguration, current_setting
    try:
        try:
            mode = configuration_status(settings)
        except AppError as exc:
            if not ensure or exc.code != "auth_configuration_required" or not settings.auth_bootstrap_configuration:
                raise
            payload = json.loads(Path(settings.auth_bootstrap_configuration).read_text())
            cfg = ProtocolConfiguration.model_validate(payload["configuration"])
            from app.deployment.protocol_bootstrap import initialize
            with get_session_factory().begin() as session:
                initialize(session, settings, cfg, {"ldap_bind_password": settings.directory_bind_password.get_secret_value(), "oidc_client_secret": settings.oidc_client_secret.get_secret_value()}, payload["admin_group_id"], migration_bindings=payload.get("migration_bindings"))
            mode = cfg.auth_mode
        return BootstrapCheck("authentication", mode + "_configured")
    except AppError as exc:
        raise BootstrapFailure(exc.code) from exc
    except Exception as exc:
        raise BootstrapFailure("auth_configuration_unavailable") from exc


def _protocol_onboarding_check(settings: Settings) -> BootstrapCheck:
    from app.db.session import get_session_factory
    from app.db.models import AuditLog, IdentitySetting
    try:
        with get_session_factory()() as session:
            done = session.scalar(select(AuditLog.id).where(AuditLog.action == "auth.onboarding.completed", AuditLog.result == "success"))
            if not done:
                raise BootstrapFailure("normal_admin_login_required")
    except BootstrapFailure:
        raise
    except Exception as exc:
        raise BootstrapFailure("onboarding_evidence_unavailable") from exc
    return BootstrapCheck("onboarding", "normal_administrator_verified")


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
        ("deployment.authentication", lambda: _protocol_authentication_check(settings)),

    )
    if settings.deployment_phase == "operational":
        checks += (("deployment.onboarding", lambda: _protocol_onboarding_check(settings)),)
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
