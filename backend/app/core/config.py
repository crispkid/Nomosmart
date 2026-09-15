from __future__ import annotations

from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
import os
from pathlib import Path
import ssl
import stat
from typing import Any
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


SECRET_FILE_FIELDS = frozenset(
    {
        "app_encryption_key",
        "celery_broker_url",
        "celery_result_backend",
        "database_url",
        "keycloak_bootstrap_admin_password",
        "keycloak_sync_client_secret",
        "neo4j_admin_password",
        "neo4j_password",
        "oidc_client_secret",
        "opensearch_admin_password",
        "opensearch_password",
        "redis_url",
        "s3_access_key_id",
        "s3_secret_access_key",
        "break_glass_initial_password",
    }
)


class SecretFileSettingsSource(PydanticBaseSettingsSource):
    """Load explicitly allowlisted settings from operator-owned *_FILE paths."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    @staticmethod
    def _read(path_value: str, *, production: bool) -> str:
        path = Path(path_value)
        try:
            details = path.lstat()
        except OSError as exc:
            raise ValueError("Configured Secret file is unavailable") from exc
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
            raise ValueError("Configured Secret path must be a regular file")
        managed_runtime_secret = path.is_absolute() and str(path).startswith("/run/secrets/")
        if production and not managed_runtime_secret and stat.S_IMODE(details.st_mode) & 0o077:
            raise ValueError("Production Secret files must not grant group or other permissions")
        try:
            value = path.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise ValueError("Configured Secret file cannot be read") from exc
        if not value:
            raise ValueError("Configured Secret file is empty")
        return value

    def __call__(self) -> dict[str, Any]:
        production = str(os.environ.get("APP_ENV") or self.current_state.get("app_env") or "").lower() == "production"
        values: dict[str, Any] = {}
        for field_name in SECRET_FILE_FIELDS & self.settings_cls.model_fields.keys():
            env_name = field_name.upper()
            file_path = os.environ.get(f"{env_name}_FILE", "").strip()
            if not file_path:
                continue
            file_value = self._read(file_path, production=production)
            direct_value = os.environ.get(env_name)
            if direct_value is not None and direct_value != file_value and production:
                raise ValueError(f"{env_name} and {env_name}_FILE conflict")
            if direct_value is None:
                values[field_name] = file_value
        return values


class MigrationTargetSettings(BaseSettings):
    """Release target shared with Frontend init; no database credentials."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")
    migration_required_version: str = Field(default="", max_length=80, pattern=r"^$|^[0-9]+(?:[._][0-9]+)*$")
    migration_required_checksum: int | None = Field(default=None, ge=-(2**31), le=2**31 - 1)
    migration_check_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @field_validator("migration_required_checksum", mode="before")
    @classmethod
    def validate_migration_checksum(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None  # The runtime gate rejects missing contracts.
        if type(value) is int:
            return value
        if isinstance(value, str):
            unsigned = value[1:] if value.startswith("-") else value
            if unsigned and unsigned.isascii() and unsigned.isdecimal():
                return int(value)
        raise ValueError("Migration checksum must be a signed 32-bit integer")

    @classmethod
    def settings_customise_sources(
        cls, settings_cls: type[BaseSettings], init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource, dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, dotenv_settings, SecretFileSettingsSource(settings_cls), file_secret_settings)


class MigrationProbeSettings(MigrationTargetSettings):
    """Read-only database probe; no unrelated application credentials."""

    database_url: SecretStr


class Settings(MigrationProbeSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    cors_allowed_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    frontend_app_origin: str = "http://127.0.0.1:3000"

    database_url: SecretStr = SecretStr("postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/nomosmart")
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    celery_broker_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    celery_result_backend: SecretStr = SecretStr("redis://127.0.0.1:6379/1")
    redis_ha_mode: Literal["standalone", "sentinel"] = "standalone"
    redis_sentinel_nodes: str = ""
    redis_sentinel_master_name: str = "nomosmart"
    redis_sentinel_username: str = "nomosmart"
    redis_sentinel_password: SecretStr = SecretStr("")
    redis_tls_ca_cert_path: str = ""

    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "nomosmart"
    s3_access_key_id: SecretStr = SecretStr("")
    s3_secret_access_key: SecretStr = SecretStr("")
    s3_use_ssl: bool = False
    s3_verify_tls: bool = False
    s3_path_style_access: bool = True
    s3_ca_cert_path: str = ""
    s3_postgresql_backup_bucket: str = "nomosmart-postgresql-backups"

    opensearch_url: str = "https://127.0.0.1:9200"
    opensearch_username: SecretStr = SecretStr("nomosmart")
    opensearch_password: SecretStr = SecretStr("")
    opensearch_verify_tls: bool = False
    opensearch_index_prefix: str = "nomosmart-dev"
    opensearch_staging_live_write: bool = True
    opensearch_ca_cert_path: str = ""

    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_database: str = "neo4j"
    neo4j_username: SecretStr = SecretStr("nomosmart")
    neo4j_password: SecretStr = SecretStr("")
    neo4j_ca_cert_path: str = ""

    oidc_issuer_url: str = "http://127.0.0.1:8080/realms/nomosmart"
    oidc_discovery_url: str = ""
    oidc_jwks_url: str = ""
    oidc_client_id: str = "nomosmart-backend"
    oidc_client_secret: SecretStr = SecretStr("")
    oidc_audience: str = "nomosmart-backend"
    oidc_frontend_client_id: str = "nomosmart-frontend"
    keycloak_admin_api_url: str = "http://127.0.0.1:8080"
    keycloak_admin_internal_url: str = ""
    keycloak_sync_client_id: str = "nomosmart-sync"
    keycloak_sync_client_secret: SecretStr = SecretStr("")
    keycloak_ldap_group_path: str = "/ldap"
    break_glass_username: str = ""
    break_glass_system_admin_group: str = "system-admin"
    break_glass_runbook_uri: str = ""
    break_glass_alerting_evidence: str = ""
    identity_sync_schedule: str = "0 2 * * *"
    identity_sync_timezone: str = "Asia/Taipei"
    identity_sync_enabled: bool = True
    identity_sync_scope: Literal["people", "groups", "people_and_groups"] = "people_and_groups"
    identity_sync_queue_timeout_seconds: int = Field(default=300, ge=30, le=3600)
    identity_sync_run_timeout_seconds: int = Field(default=1800, ge=300, le=86400)
    identity_sync_heartbeat_seconds: int = Field(default=30, ge=10, le=300)
    identity_sync_keycloak_provider_timeout_seconds: int = Field(default=600, ge=30, le=1800)

    app_encryption_key: SecretStr = SecretStr("0" * 64)
    default_timezone: str = "Asia/Taipei"
    max_upload_size_mb: int = Field(
        default=100,
        ge=1,
        le=10240,
        validation_alias=AliasChoices("NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB", "MAX_UPLOAD_SIZE_MB"),
    )
    staging_index_ttl_days: int = Field(default=7, ge=1, le=3650)
    ingestion_worker_lease_seconds: int = Field(default=300, ge=30, le=3600)
    target_chunk_tokens: int = Field(default=500, ge=16, le=100000)
    max_chunk_tokens: int = Field(default=700, ge=16, le=100000)
    min_chunk_tokens: int = Field(default=80, ge=1, le=100000)
    chunk_overlap_tokens: int = Field(default=60, ge=0, le=50000)
    heading_context_enabled: bool = True
    max_heading_depth: int = Field(default=4, ge=1, le=12)
    max_context_prefix_tokens: int = Field(default=96, ge=1, le=2000)
    document_title_context_enabled: bool = True
    table_chunk_max_rows: int = Field(default=10, ge=1, le=1000)
    remove_repeated_header_footer: bool = True
    pandoc_command: str = "pandoc"
    pandoc_sandbox_command: str = "bwrap"
    pandoc_timeout_seconds: int = Field(default=120, ge=10, le=1800)
    pandoc_max_memory_mb: int = Field(default=512, ge=128, le=8192)
    pandoc_cache_dir: str = "/tmp/nomosmart-pandoc-cache"
    tesseract_command: str = "tesseract"
    tesseract_pdf_command: str = "pdftoppm"
    tesseract_sandbox_command: str = "bwrap"
    tesseract_timeout_seconds: int = Field(default=120, ge=10, le=1800)
    tesseract_max_memory_mb: int = Field(default=512, ge=128, le=8192)
    tesseract_max_pages: int = Field(default=200, ge=1, le=2000)
    http_source_allowed_hosts: str = ""
    http_source_allowed_cidrs: str = ""
    sftp_known_hosts_path: str = "/etc/nomosmart/ssh_known_hosts"
    public_api_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    public_api_invalid_auth_requests_per_minute: int = Field(default=20, ge=1, le=10000)
    public_api_idempotency_ttl_hours: int = Field(default=24, ge=1, le=720)
    public_api_idempotency_lease_seconds: int = Field(default=300, ge=30, le=3600)
    public_api_content_retention_days: int = Field(default=30, ge=1, le=3650)
    public_api_record_retention_days: int = Field(default=365, ge=1, le=3650)
    validation_max_attempts: int = Field(default=3, ge=1, le=10)
    report_export_batch_size: int = Field(default=500, ge=50, le=2000)
    report_export_timeout_seconds: int = Field(default=300, ge=30, le=3600)
    deployment_bootstrap_release: str = ""
    kubernetes_secret_mount_root: str = "/var/run/nomosmart-secrets"
    compose_secret_mount_root: str = "/run/secrets"
    runtime_secret_allowed_refs: str = ""

    @field_validator("app_encryption_key")
    @classmethod
    def validate_encryption_key(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) != 64:
            raise ValueError("APP_ENCRYPTION_KEY must be 64 hexadecimal characters")
        try:
            bytes.fromhex(raw)
        except ValueError as exc:
            raise ValueError("APP_ENCRYPTION_KEY must be valid hexadecimal") from exc
        return value

    @field_validator("identity_sync_schedule")
    @classmethod
    def validate_identity_sync_schedule(cls, value: str) -> str:
        if len(value.split()) != 5:
            raise ValueError("IDENTITY_SYNC_SCHEDULE must be a five-field cron expression")
        return value

    @field_validator("keycloak_ldap_group_path")
    @classmethod
    def validate_keycloak_ldap_group_path(cls, value: str) -> str:
        path = value.strip().rstrip("/")
        if not path.startswith("/") or path == "/" or "//" in path:
            raise ValueError("KEYCLOAK_LDAP_GROUP_PATH must be a non-root absolute Keycloak group path")
        segments = path[1:].split("/")
        if any(not segment or segment in {".", ".."} for segment in segments):
            raise ValueError("KEYCLOAK_LDAP_GROUP_PATH contains an invalid segment")
        return path

    @field_validator("http_source_allowed_cidrs")
    @classmethod
    def validate_network_cidrs(cls, value: str) -> str:
        for item in (part.strip() for part in value.split(",")):
            if item:
                try:
                    ip_network(item, strict=False)
                except ValueError as exc:
                    raise ValueError("Network allowlists must use valid IPv4 or IPv6 CIDR notation") from exc
        return value

    @field_validator("http_source_allowed_hosts")
    @classmethod
    def validate_http_source_allowed_hosts(cls, value: str) -> str:
        for host in (item.strip().lower().rstrip(".") for item in value.split(",") if item.strip()):
            if "://" in host or "/" in host or "@" in host or not all(character.isalnum() or character in ".:-_" for character in host):
                raise ValueError("HTTP_SOURCE_ALLOWED_HOSTS must contain hostnames or IP literals only")
        return value

    @model_validator(mode="after")
    def validate_production_security(self) -> Self:
        if self.identity_sync_keycloak_provider_timeout_seconds > self.identity_sync_run_timeout_seconds:
            raise ValueError("IDENTITY_SYNC_KEYCLOAK_PROVIDER_TIMEOUT_SECONDS must not exceed IDENTITY_SYNC_RUN_TIMEOUT_SECONDS")
        if not self.min_chunk_tokens <= self.target_chunk_tokens <= self.max_chunk_tokens:
            raise ValueError("Chunk token limits must satisfy MIN_CHUNK_TOKENS <= TARGET_CHUNK_TOKENS <= MAX_CHUNK_TOKENS")
        if self.chunk_overlap_tokens >= self.max_chunk_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be smaller than MAX_CHUNK_TOKENS")
        if self.app_env != "production":
            return self

        errors: list[str] = []
        encryption_key = self.app_encryption_key.get_secret_value()
        if encryption_key == "0" * 64:
            errors.append("APP_ENCRYPTION_KEY must not use the all-zero development key")
        if not self.opensearch_staging_live_write:
            errors.append("OPENSEARCH_STAGING_LIVE_WRITE must be enabled")
        if not self.redis_url.get_secret_value().strip():
            errors.append("REDIS_URL is required for public API rate limiting")
        if self.redis_ha_mode == "sentinel":
            if not self.redis_sentinel_nodes.strip():
                errors.append("REDIS_SENTINEL_NODES is required in Sentinel mode")
            if not self.redis_sentinel_master_name.strip():
                errors.append("REDIS_SENTINEL_MASTER_NAME is required in Sentinel mode")
            if not self.redis_sentinel_password.get_secret_value().strip():
                errors.append("REDIS_SENTINEL_PASSWORD is required in Sentinel mode")
            if not self.redis_tls_ca_cert_path.strip():
                errors.append("REDIS_TLS_CA_CERT_PATH is required in Sentinel mode")
        if self.public_api_content_retention_days > self.public_api_record_retention_days:
            errors.append("PUBLIC_API_CONTENT_RETENTION_DAYS must not exceed PUBLIC_API_RECORD_RETENTION_DAYS")
        if not self.pandoc_command.strip():
            errors.append("PANDOC_COMMAND must be configured")
        if not self.pandoc_sandbox_command.strip():
            errors.append("PANDOC_SANDBOX_COMMAND must be configured")
        if not self.deployment_bootstrap_release.strip():
            errors.append("DEPLOYMENT_BOOTSTRAP_RELEASE must identify the current deployment")
        if not self.break_glass_alerting_evidence.strip() or "CHANGE_ME" in self.break_glass_alerting_evidence.upper():
            errors.append("BREAK_GLASS_ALERTING_EVIDENCE must identify a real production alert route")

        self._require_production_https("OIDC_ISSUER_URL", self.oidc_issuer_url, errors)
        self._require_production_https("KEYCLOAK_ADMIN_API_URL", self.keycloak_admin_api_url, errors)
        self._require_production_https("FRONTEND_APP_ORIGIN", self.frontend_app_origin, errors)
        self._require_production_https("BREAK_GLASS_RUNBOOK_URI", self.break_glass_runbook_uri, errors)
        self._require_production_https("S3_ENDPOINT_URL", self.s3_endpoint_url, errors)
        self._require_production_https("OPENSEARCH_URL", self.opensearch_url, errors)
        for origin in self.cors_origins:
            self._require_production_https("CORS_ALLOWED_ORIGINS", origin, errors)

        if not self.s3_use_ssl or not self.s3_verify_tls:
            errors.append("S3_USE_SSL and S3_VERIFY_TLS must be enabled")
        if not self.opensearch_verify_tls:
            errors.append("OPENSEARCH_VERIFY_TLS must be enabled")
        if self.neo4j_uri.strip().lower().startswith("neo4j+s://") and not self.neo4j_ca_cert_path.strip():
            errors.append("NEO4J_CA_CERT_PATH is required for neo4j+s://")
        if not Path(self.kubernetes_secret_mount_root).is_absolute():
            errors.append("KUBERNETES_SECRET_MOUNT_ROOT must be an absolute path")
        if not Path(self.compose_secret_mount_root).is_absolute():
            errors.append("COMPOSE_SECRET_MOUNT_ROOT must be an absolute path")

        required_secrets = {
            "DATABASE_URL": self.database_url,
            "S3_ACCESS_KEY_ID": self.s3_access_key_id,
            "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
            "OPENSEARCH_PASSWORD": self.opensearch_password,
            "NEO4J_PASSWORD": self.neo4j_password,
            "OIDC_CLIENT_SECRET": self.oidc_client_secret,
            "KEYCLOAK_SYNC_CLIENT_SECRET": self.keycloak_sync_client_secret,
        }
        for name, secret in required_secrets.items():
            raw = secret.get_secret_value().strip()
            if not raw or "CHANGE_ME" in raw.upper():
                errors.append(f"{name} must be provided by a production secret source")
        if "postgres:postgres@" in self.database_url.get_secret_value().lower():
            errors.append("DATABASE_URL must not use the development postgres credential")

        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(errors))
        return self

    @staticmethod
    def _require_production_https(name: str, value: str, errors: list[str]) -> None:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or host in {"localhost", "127.0.0.1", "::1"}:
            errors.append(f"{name} must use a non-local HTTPS URL")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]

    @property
    def http_source_allowed_networks(self) -> tuple[IPv4Network | IPv6Network, ...]:
        return self._parse_networks(self.http_source_allowed_cidrs)

    @property
    def http_source_allowed_hostnames(self) -> frozenset[str]:
        return frozenset(item.strip().lower().rstrip(".") for item in self.http_source_allowed_hosts.split(",") if item.strip())

    @staticmethod
    def _parse_networks(value: str) -> tuple[IPv4Network | IPv6Network, ...]:
        return tuple(ip_network(item.strip(), strict=False) for item in value.split(",") if item.strip())

    @property
    def encryption_key_bytes(self) -> bytes:
        return bytes.fromhex(self.app_encryption_key.get_secret_value())

    def safe_summary(self) -> dict[str, object]:
        return {
            "app_env": self.app_env,
            "app_host": self.app_host,
            "app_port": self.app_port,
            "database_configured": bool(self.database_url.get_secret_value()),
            "redis_configured": bool(self.redis_url.get_secret_value()),
            "s3_endpoint_url": self.s3_endpoint_url,
            "s3_bucket": self.s3_bucket,
            "opensearch_url": self.opensearch_url,
            "neo4j_uri": self.neo4j_uri,
            "oidc_issuer_url": self.oidc_issuer_url,
            "oidc_internal_transport_configured": bool(
                self.oidc_discovery_url or self.oidc_jwks_url or self.keycloak_admin_internal_url
            ),
        }

    @property
    def oidc_discovery_endpoint(self) -> str:
        return self.oidc_discovery_url.strip() or f"{self.oidc_issuer_url.rstrip('/')}/.well-known/openid-configuration"

    @property
    def oidc_jwks_endpoint(self) -> str:
        return self.oidc_jwks_url.strip() or f"{self.oidc_issuer_url.rstrip('/')}/protocol/openid-connect/certs"

    @property
    def keycloak_admin_endpoint(self) -> str:
        return self.keycloak_admin_internal_url.strip() or self.keycloak_admin_api_url

    @property
    def opensearch_ssl_context(self) -> ssl.SSLContext | None:
        if not self.opensearch_verify_tls:
            return ssl._create_unverified_context()  # noqa: SLF001 - explicit Development-only setting
        if self.opensearch_ca_cert_path.strip():
            return ssl.create_default_context(cafile=self.opensearch_ca_cert_path)
        return None

    @property
    def opensearch_httpx_verify(self) -> bool | ssl.SSLContext:
        return self.opensearch_ssl_context or self.opensearch_verify_tls

    @property
    def s3_httpx_verify(self) -> bool | ssl.SSLContext:
        if self.s3_verify_tls and self.s3_ca_cert_path.strip():
            return ssl.create_default_context(cafile=self.s3_ca_cert_path)
        return self.s3_verify_tls


def neo4j_driver_options(settings: Settings) -> dict[str, object]:
    """Return strict Neo4j TLS trust options for the configured CA file."""
    ca_path = settings.neo4j_ca_cert_path.strip()
    if not ca_path:
        return {}
    try:
        details = Path(ca_path).lstat()
    except OSError as exc:
        raise ValueError("NEO4J_CA_CERT_PATH is unavailable") from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise ValueError("NEO4J_CA_CERT_PATH must be a regular file")
    try:
        from neo4j import TrustCustomCAs
    except ImportError as exc:  # pragma: no cover - dependency contract
        raise ValueError("Neo4j driver is required for custom CA trust") from exc
    return {"trusted_certificates": TrustCustomCAs(ca_path)}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
