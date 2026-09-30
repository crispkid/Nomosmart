from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys
import tomllib
from typing import Any, Final
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "migrations"))
from nomosmart_migrations import CONTRACT_PATH, helm_values as migration_helm_values


API_VERSION: Final[str] = "install.nomosmart.io/v1alpha1"
PRODUCTION_API_VERSION: Final[str] = "install.nomosmart.io/v1alpha2"
API_VERSIONS: Final[frozenset[str]] = frozenset(
    {API_VERSION, PRODUCTION_API_VERSION}
)
DIRECTORY_MODES: Final[frozenset[str]] = frozenset(
    {"freeipa", "ldap", "active-directory", "preconfigured"}
)
DEPLOYMENT_PROFILES: Final[frozenset[str]] = frozenset(
    {"auto", "bundled", "external-services"}
)
RUNTIME_SECRET_MODES: Final[frozenset[str]] = frozenset({"generate", "existing"})
EXTERNAL_RUNTIME_SECRET_KEYS: Final[tuple[str, ...]] = (
    "APP_ENCRYPTION_KEY",
    "DATABASE_URL",
    "DATABASE_MIGRATION_USER",
    "DATABASE_MIGRATION_PASSWORD",
    "REDIS_URL",
    "REDIS_SENTINEL_PASSWORD",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "OPENSEARCH_ADMIN_PASSWORD",
    "OPENSEARCH_PASSWORD",
    "NEO4J_ADMIN_PASSWORD",
    "NEO4J_PASSWORD",
    "OIDC_CLIENT_SECRET",
    "KEYCLOAK_SYNC_CLIENT_SECRET",
    "BREAK_GLASS_INITIAL_PASSWORD",
)
DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
SHA_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
OPENPGP_FINGERPRINT = re.compile(r"^[0-9A-Fa-f]{40,64}$")
PROHIBITED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "password_value",
        "token",
        "token_value",
        "secret_value",
        "client_secret",
        "private_key",
        "vault_share",
        "root_token",
        "otp",
        "totp",
        "totp_seed",
    }
)


class ConfigError(ValueError):
    pass


def _required(table: dict[str, Any], key: str, *, context: str) -> Any:
    if key not in table:
        raise ConfigError(f"{context}.{key} is required")
    return table[key]


def _string(table: dict[str, Any], key: str, *, context: str, default: str | None = None) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _optional_string(table: dict[str, Any], key: str, *, context: str) -> str:
    value = table.get(key, "")
    if not isinstance(value, str):
        raise ConfigError(f"{context}.{key} must be a string")
    return value.strip()


def _boolean(table: dict[str, Any], key: str, *, context: str, default: bool = False) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{context}.{key} must be true or false")
    return value


def _table(root: dict[str, Any], key: str, *, required: bool = True) -> dict[str, Any]:
    value = root.get(key)
    if value is None and not required:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a table")
    return value


def _reject_unknown(table: dict[str, Any], allowed: set[str], *, context: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"{context} contains unsupported field(s): {', '.join(unknown)}")


def _path(value: str, base: Path, *, context: str, must_be_absolute: bool = False) -> Path:
    candidate = Path(value).expanduser()
    if must_be_absolute and not candidate.is_absolute():
        raise ConfigError(f"{context} must be an absolute path")
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def _https(value: str, *, context: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ConfigError(f"{context} must be an HTTPS URL without user information")
    return value.rstrip("/")


def _ldaps(value: str, *, context: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "ldaps"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ConfigError(
            f"{context} must be an LDAPS URL without user information"
        )
    return value.rstrip("/")


def _dns_label(value: str, *, context: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 63 or not DNS_LABEL.fullmatch(normalized):
        raise ConfigError(f"{context} must be a Kubernetes DNS label")
    return normalized


def _hostname(value: str, *, context: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if (
        not normalized
        or len(normalized) > 253
        or any(len(item) > 63 or not DNS_LABEL.fullmatch(item) for item in normalized.split("."))
    ):
        raise ConfigError(f"{context} must be a valid DNS hostname")
    return normalized


def _cidrs(value: str, *, context: str) -> str:
    rows = [item.strip() for item in value.split(",") if item.strip()]
    if not rows:
        raise ConfigError(f"{context} must contain at least one CIDR")
    networks: list[str] = []
    for row in rows:
        try:
            network = ipaddress.ip_network(row, strict=False)
        except ValueError as exc:
            raise ConfigError(f"{context} contains an invalid CIDR") from exc
        if network.prefixlen == 0:
            raise ConfigError(f"{context} must not allow the entire Internet")
        networks.append(str(network))
    return ",".join(networks)


def _image(value: str, *, context: str) -> str:
    normalized = value.strip()
    if not SHA_IMAGE.fullmatch(normalized):
        raise ConfigError(f"{context} must be pinned as repository:tag@sha256:<64 hex>")
    return normalized


def _split_image(value: str) -> tuple[str, str]:
    reference, digest = value.rsplit("@", 1)
    slash = reference.rfind("/")
    colon = reference.rfind(":")
    if colon <= slash:
        raise ConfigError("pinned image must include an explicit tag before its digest")
    return reference[:colon], f"{reference[colon + 1:]}@{digest}"


def _file_digest(path: Path, *, context: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ConfigError(f"{context} is unavailable: {path}") from exc


def _chart_digest(path: Path) -> str:
    if not path.is_dir() or path.is_symlink():
        raise ConfigError(f"application.chart must be a chart directory: {path}")
    digest = hashlib.sha256()
    files = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and not candidate.is_symlink()
        and not any(part.startswith(".") for part in candidate.relative_to(path).parts)
    )
    if not files:
        raise ConfigError("application.chart contains no files")
    for candidate in files:
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = candidate.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _reject_secret_material(value: Any, *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in PROHIBITED_KEYS:
                raise ConfigError(f"{path + '.' if path else ''}{key} is prohibited; use a Secret reference")
            _reject_secret_material(item, path=f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_material(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        upper = value.upper()
        if "-----BEGIN" in upper and ("PRIVATE KEY" in upper or "PGP PRIVATE" in upper):
            raise ConfigError(f"{path} contains prohibited private-key material")


@dataclass(frozen=True)
class TargetConfig:
    context: str
    api_server: str
    cluster_uid: str
    namespace: str
    release: str


@dataclass(frozen=True)
class ApplicationConfig:
    public_host: str
    ingress_class: str
    ingress_controller_namespace: str
    ingress_controller_name: str
    storage_class: str
    chart: Path
    values: tuple[Path, ...]
    package_dir: Path
    state_dir: Path
    trusted_tls_dir: Path | None
    registry_pull_secret: str
    runtime_secret: str
    runtime_secret_mode: str
    ingress_tls_secret: str
    rustfs_tls_secret: str
    opensearch_tls_secret: str
    onboarding_admin_allow_cidr: str
    break_glass_runbook_uri: str
    break_glass_alerting_evidence: str


@dataclass(frozen=True)
class ImageConfig:
    frontend: str
    backend: str
    migration: str
    postgresql: str
    redis: str
    rustfs: str
    opensearch: str
    neo4j: str
    keycloak: str

    @staticmethod
    def _helm_image(value: str) -> dict[str, str]:
        repository, tag = _split_image(value)
        return {"repository": repository, "tag": tag}

    def application_helm_values(self) -> dict[str, dict[str, str]]:
        return {
            name: self._helm_image(getattr(self, name))
            for name in ("frontend", "backend", "migration")
        }

    def inventory(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ReleaseConfig:
    required: bool
    package_dir: Path | None
    trusted_signer_fingerprint: str
    purpose: str = "production"
    isolated_environment_acknowledged: bool = False


@dataclass(frozen=True)
class IdentityConfig:
    mode: str
    realm: str
    provider_name: str
    mapper_name: str
    admin_username: str
    external_group_name: str
    local_role_name: str
    server_url: str
    users_dn: str
    groups_dn: str
    bind_dn: str
    bind_secret_name: str
    bind_secret_key: str
    ca_secret_name: str
    ca_secret_key: str
    username_attribute: str
    rdn_attribute: str
    uuid_attribute: str
    user_object_classes: tuple[str, ...]
    group_object_classes: tuple[str, ...]
    group_name_attribute: str
    membership_attribute: str
    membership_attribute_type: str
    membership_user_attribute: str
    user_search_scope: str
    preserve_group_inheritance: bool
    custom_user_filter: str
    group_path: str


@dataclass(frozen=True)
class InstallConfig:
    api_version: str
    deployment_profile: str
    target: TargetConfig
    application: ApplicationConfig
    images: ImageConfig
    release: ReleaseConfig
    identity: IdentityConfig
    source_path: Path

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload.pop("source_path", None)
        source_artifacts: dict[str, Any] = {
            "chart_tree_sha256": self.chart_digest,
            "migration_contract_sha256": _file_digest(CONTRACT_PATH, context="release migration contract"),
            "values_sha256": [
                _file_digest(path, context="application.values")
                for path in self.application.values
            ],
        }
        if self.application.trusted_tls_dir is not None:
            tls_names = (
                ("edge.crt", "edge.key", "edge-ca.crt")
                if self.deployment_profile == "external-services"
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
            source_artifacts["trusted_tls_sha256"] = {
                name: _file_digest(
                    self.application.trusted_tls_dir / name,
                    context=f"application.trusted_tls_dir/{name}",
                )
                for name in tls_names
            }
        if self.release.package_dir is not None:
            source_artifacts["release_manifest_sha256"] = _file_digest(
                self.release.package_dir / "release-manifest.json",
                context="release.package_dir/release-manifest.json",
            )
        payload["source_artifacts"] = source_artifacts

        def normalize(value: Any) -> Any:
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in sorted(value.items())}
            if isinstance(value, (list, tuple)):
                return [normalize(item) for item in value]
            return value

        canonical = json.dumps(normalize(payload), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def chart_digest(self) -> str:
        return _chart_digest(self.application.chart)

    @property
    def chart_version(self) -> str:
        chart_yaml = self.application.chart / "Chart.yaml"
        try:
            for line in chart_yaml.read_text(encoding="utf-8").splitlines():
                match = re.fullmatch(r"version:\s*[\"']?([^\"'\s]+)[\"']?\s*", line)
                if match:
                    return match.group(1)
        except OSError as exc:
            raise ConfigError("Helm Chart.yaml is unavailable") from exc
        raise ConfigError("Helm Chart.yaml has no version")

    @property
    def external_ca_secret_names(self) -> tuple[str, ...]:
        """Return CA Secret references declared by an external profile overlay.

        The chart values remain the source of truth for external endpoints. A
        small read-only extraction lets preflight allow and fingerprint those
        operator-owned Secrets without adding credential values to TOML.
        """
        if self.deployment_profile != "external-services":
            return ()
        names: set[str] = set()
        for path in self.application.values:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            names.update(
                match.group(1)
                for match in re.finditer(
                    r"^\s*caSecretName:\s*([a-z0-9](?:[-a-z0-9]*[a-z0-9])?)\s*(?:#.*)?$",
                    text,
                    flags=re.MULTILINE,
                )
            )
        return tuple(sorted(names))

    @property
    def identity_digest(self) -> str:
        canonical = json.dumps(
            asdict(self.identity),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def helm_fullname(self) -> str:
        release = self.target.release
        return (
            release
            if "nomosmart" in release
            else f"{release}-nomosmart"
        )[:63].rstrip("-")

    def generated_helm_values(self, stage: str) -> dict[str, Any]:
        host = self.application.public_host
        storage = self.application.storage_class
        fullname = self.helm_fullname
        values: dict[str, Any] = {
            "deploymentProfile": self.deployment_profile,
            "migration": migration_helm_values(),
            "installer": {"deploymentStage": stage},
            "global": {"publicHost": host, "publicOrigin": f"https://{host}"},
            "networkPolicy": {
                "ingressController": {
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": (
                                self.application.ingress_controller_namespace
                            )
                        }
                    },
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": (
                                self.application.ingress_controller_name
                            )
                        }
                    },
                }
            },
            "image": self.images.application_helm_values(),
            "secrets": {"existingSecret": self.application.runtime_secret, "data": {}},
            "bootstrap": {
                "deploymentPhase": "operational" if stage == "operational" else "onboarding",
                "onboardingAdminAllowCidr": self.application.onboarding_admin_allow_cidr,
                "finalize": {"enabled": False},
            },
            "frontend": {
                "env": {
                    "NEXT_PUBLIC_APP_ORIGIN": f"https://{host}",
                    "NEXT_PUBLIC_OIDC_ISSUER_URL": f"https://{host}/identity/realms/{self.identity.realm}",
                    "FRONTEND_APP_ORIGIN": f"https://{host}",
                    "FRONTEND_OIDC_ISSUER_URL": f"https://{host}/identity/realms/{self.identity.realm}",
                }
            },
            "backend": {
                "env": {
                    "APP_ENV": "production",
                    "CORS_ALLOWED_ORIGINS": f"https://{host}",
                    "FRONTEND_APP_ORIGIN": f"https://{host}",
                    "OIDC_ISSUER_URL": f"https://{host}/identity/realms/{self.identity.realm}",
                    "KEYCLOAK_LDAP_GROUP_PATH": self.identity.group_path,
                    "DEPLOYMENT_FINALIZATION_ADMIN_USERNAME": self.identity.admin_username,
                    "DEPLOYMENT_FINALIZATION_ADMIN_GROUP": self.identity.external_group_name,
                    "BREAK_GLASS_USERNAME": "nomosmart",
                    "BREAK_GLASS_RUNBOOK_URI": self.application.break_glass_runbook_uri,
                    "BREAK_GLASS_ALERTING_EVIDENCE": self.application.break_glass_alerting_evidence,
                }
            },
            "ingress": {
                "enabled": True,
                "className": self.application.ingress_class,
                "hosts": [
                    {
                        "host": host,
                        "paths": [
                            {"path": "/identity", "pathType": "Prefix", "service": "keycloak"},
                            {"path": "/", "pathType": "Prefix", "service": "frontend"},
                        ],
                    }
                ],
                "tls": [{"secretName": self.application.ingress_tls_secret, "hosts": [host]}],
            },
            "postgresql": {
                "tls": {
                    "secretName": f"{fullname}-postgresql-tls",
                    "replicationSecretName": (
                        f"{fullname}-postgresql-replication-tls"
                    ),
                },
                "auth": {
                    "superuserSecretName": f"{fullname}-postgresql-superuser",
                    "ownerSecretName": f"{fullname}-postgresql-migration",
                    "appSecretName": f"{fullname}-postgresql-app",
                    "keycloakSecretName": f"{fullname}-postgresql-keycloak",
                },
                "backup": {
                    "enabled": stage != "foundation",
                    "prepareBucket": stage == "foundation",
                    "endpointURL": f"https://{fullname}-rustfs:9000",
                    "credentialSecretName": self.application.runtime_secret,
                    "caSecretName": self.application.rustfs_tls_secret,
                },
            },
            "redis": {
                "tls": {"secretName": f"{fullname}-redis-tls"}
            },
            "rustfs": {"tls": {"secretName": self.application.rustfs_tls_secret}},
            "opensearch": {"tls": {"secretName": self.application.opensearch_tls_secret}},
            "directory": {
                "enabled": self.identity.mode != "preconfigured",
                "caSecretName": self.identity.ca_secret_name,
                "caKey": self.identity.ca_secret_key,
            },
        }
        if self.application.registry_pull_secret:
            values["imagePullSecrets"] = [
                {"name": self.application.registry_pull_secret}
            ]
        for component in (
            "postgresql",
            "redis",
            "rustfs",
            "opensearch",
            "neo4j",
            "keycloak",
        ):
            rendered_image = self.images._helm_image(
                getattr(self.images, component)
            )
            if component == "postgresql":
                values.setdefault("postgresql", {}).setdefault(
                    "cluster", {}
                )["image"] = rendered_image
            else:
                values.setdefault(component, {})["image"] = rendered_image
                if component == "opensearch":
                    values[component]["image"]["digest"] = self.images.opensearch.split("@", 1)[1]
        if self.identity.mode != "preconfigured":
            values.setdefault("keycloak", {})["trust"] = {
                "existingSecret": self.identity.ca_secret_name,
                "caKey": self.identity.ca_secret_key,
            }
        values.setdefault("keycloak", {})["adminIngress"] = {
            "enabled": True,
            "annotations": {
                "nginx.ingress.kubernetes.io/whitelist-source-range": (
                    self.application.onboarding_admin_allow_cidr
                )
            },
        }
        for component in (
            "postgresql",
            "redis",
            "rustfs",
            "opensearch",
            "neo4j",
            "keycloak",
        ):
            values.setdefault(component, {}).setdefault("persistence", {})["storageClass"] = storage
        return values


def load_config(path: Path) -> InstallConfig:
    source = path.expanduser().resolve()
    try:
        payload = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError("installer configuration is unavailable or invalid TOML") from exc
    if not isinstance(payload, dict):
        raise ConfigError("installer configuration must be a TOML object")
    _reject_secret_material(payload)
    _reject_unknown(
        payload,
        {
        "api_version",
            "deployment_profile",
            "target",
            "application",
            "images",
            "release",
            "identity",
        },
        context="root",
    )
    api_version = _string(payload, "api_version", context="root")
    if api_version not in API_VERSIONS:
        raise ConfigError(
            "api_version must be " + " or ".join(sorted(API_VERSIONS))
        )
    base = source.parent
    deployment_profile = _string(
        payload,
        "deployment_profile",
        context="root",
        default="auto",
    )
    if deployment_profile not in DEPLOYMENT_PROFILES:
        raise ConfigError(
            "deployment_profile must be auto, bundled, or external-services"
        )

    target_raw = _table(payload, "target")
    _reject_unknown(target_raw, {"context", "api_server", "cluster_uid", "namespace", "release"}, context="target")
    target = TargetConfig(
        context=_string(target_raw, "context", context="target"),
        api_server=_https(_string(target_raw, "api_server", context="target"), context="target.api_server"),
        cluster_uid=_string(target_raw, "cluster_uid", context="target"),
        namespace=_dns_label(_string(target_raw, "namespace", context="target"), context="target.namespace"),
        release=_dns_label(_string(target_raw, "release", context="target"), context="target.release"),
    )

    app_raw = _table(payload, "application")
    _reject_unknown(
        app_raw,
        {
            "public_host",
            "ingress_class",
            "ingress_controller_namespace",
            "ingress_controller_name",
            "storage_class",
            "chart",
            "values",
            "package_dir",
            "state_dir",
            "trusted_tls_dir",
            "registry_pull_secret",
            "runtime_secret",
            "runtime_secret_mode",
            "ingress_tls_secret",
            "rustfs_tls_secret",
            "opensearch_tls_secret",
            "onboarding_admin_allow_cidr",
            "break_glass_runbook_uri",
            "break_glass_alerting_evidence",
        },
        context="application",
    )
    values_raw = app_raw.get("values", [])
    if not isinstance(values_raw, list) or not all(isinstance(item, str) and item.strip() for item in values_raw):
        raise ConfigError("application.values must be an array of file paths")
    trusted_tls = _string(app_raw, "trusted_tls_dir", context="application")
    application = ApplicationConfig(
        public_host=_hostname(_string(app_raw, "public_host", context="application"), context="application.public_host"),
        ingress_class=_dns_label(_string(app_raw, "ingress_class", context="application"), context="application.ingress_class"),
        ingress_controller_namespace=_dns_label(
            _string(
                app_raw,
                "ingress_controller_namespace",
                context="application",
            ),
            context="application.ingress_controller_namespace",
        ),
        ingress_controller_name=_dns_label(
            _string(
                app_raw,
                "ingress_controller_name",
                context="application",
            ),
            context="application.ingress_controller_name",
        ),
        storage_class=_string(app_raw, "storage_class", context="application"),
        chart=_path(_string(app_raw, "chart", context="application"), base, context="application.chart"),
        values=tuple(_path(item, base, context="application.values") for item in values_raw),
        package_dir=_path(_string(app_raw, "package_dir", context="application"), base, context="application.package_dir"),
        state_dir=_path(_string(app_raw, "state_dir", context="application"), base, context="application.state_dir"),
        trusted_tls_dir=_path(trusted_tls, base, context="application.trusted_tls_dir"),
        registry_pull_secret=(
            _dns_label(
                _optional_string(
                    app_raw,
                    "registry_pull_secret",
                    context="application",
                ),
                context="application.registry_pull_secret",
            )
            if _optional_string(
                app_raw,
                "registry_pull_secret",
                context="application",
            )
            else ""
        ),
        runtime_secret=_dns_label(_string(app_raw, "runtime_secret", context="application"), context="application.runtime_secret"),
        runtime_secret_mode=_string(
            app_raw,
            "runtime_secret_mode",
            context="application",
            default="generate",
        ),
        ingress_tls_secret=_dns_label(_string(app_raw, "ingress_tls_secret", context="application"), context="application.ingress_tls_secret"),
        rustfs_tls_secret=_dns_label(_string(app_raw, "rustfs_tls_secret", context="application"), context="application.rustfs_tls_secret"),
        opensearch_tls_secret=_dns_label(_string(app_raw, "opensearch_tls_secret", context="application"), context="application.opensearch_tls_secret"),
        onboarding_admin_allow_cidr=_cidrs(
            _string(
                app_raw,
                "onboarding_admin_allow_cidr",
                context="application",
            ),
            context="application.onboarding_admin_allow_cidr",
        ),
        break_glass_runbook_uri=_https(
            _string(app_raw, "break_glass_runbook_uri", context="application"),
            context="application.break_glass_runbook_uri",
        ),
        break_glass_alerting_evidence=_string(
            app_raw,
            "break_glass_alerting_evidence",
            context="application",
        ),
    )
    if application.runtime_secret_mode not in RUNTIME_SECRET_MODES:
        raise ConfigError(
            "application.runtime_secret_mode must be generate or existing"
        )

    images_raw = _table(payload, "images")
    image_names = {
        "frontend",
        "backend",
        "migration",
        "postgresql",
        "redis",
        "rustfs",
        "opensearch",
        "neo4j",
        "keycloak",
    }
    _reject_unknown(images_raw, image_names, context="images")
    images = ImageConfig(
        **{
            name: _image(
                _string(images_raw, name, context="images"),
                context=f"images.{name}",
            )
            for name in sorted(image_names)
        }
    )

    release_raw = _table(payload, "release", required=False)
    _reject_unknown(
        release_raw,
        {"package_dir", "trusted_signer_fingerprint", "purpose", "isolated_environment_acknowledged"},
        context="release",
    )
    release_required = api_version == PRODUCTION_API_VERSION
    release_purpose = _optional_string(release_raw, "purpose", context="release") or "production"
    isolated_acknowledged = _boolean(release_raw, "isolated_environment_acknowledged", context="release")
    if release_purpose not in {"production", "installation-validation"}:
        raise ConfigError("release.purpose must be production or installation-validation")
    if release_purpose == "installation-validation" and (not release_required or not isolated_acknowledged):
        raise ConfigError(
            "installation-validation requires v1alpha2 and release.isolated_environment_acknowledged=true; "
            "target context, API server, cluster UID and namespace must identify an isolated environment"
        )
    release_package_value = _optional_string(
        release_raw, "package_dir", context="release"
    )
    release_fingerprint = re.sub(
        r"\s+",
        "",
        _optional_string(
            release_raw,
            "trusted_signer_fingerprint",
            context="release",
        ),
    ).upper()
    if release_required and not release_package_value:
        raise ConfigError("v1alpha2 requires release.package_dir")
    if release_required and release_purpose == "production" and not release_fingerprint:
        raise ConfigError(
            "Production v1alpha2 requires release.package_dir and an "
            "independently trusted release.trusted_signer_fingerprint"
        )
    if release_purpose == "installation-validation" and release_fingerprint:
        raise ConfigError("release.trusted_signer_fingerprint does not apply to installation-validation")
    if release_fingerprint and not OPENPGP_FINGERPRINT.fullmatch(
        release_fingerprint
    ):
        raise ConfigError(
            "release.trusted_signer_fingerprint must contain 40 to 64 hex characters"
        )
    release = ReleaseConfig(
        required=release_required,
        package_dir=(
            _path(
                release_package_value,
                base,
                context="release.package_dir",
            )
            if release_package_value
            else None
        ),
        trusted_signer_fingerprint=release_fingerprint,
        purpose=release_purpose,
        isolated_environment_acknowledged=isolated_acknowledged,
    )

    if deployment_profile == "external-services" and application.runtime_secret_mode != "existing":
        raise ConfigError(
            "external-services deployment_profile requires application.runtime_secret_mode=existing"
        )

    identity_raw = _table(payload, "identity")
    _reject_unknown(
        identity_raw,
        {
            "mode",
            "realm",
            "provider_name",
            "mapper_name",
            "admin_username",
            "external_group_name",
            "local_role_name",
            "server_url",
            "users_dn",
            "groups_dn",
            "bind_dn",
            "bind_secret_name",
            "bind_secret_key",
            "ca_secret_name",
            "ca_secret_key",
            "username_attribute",
            "rdn_attribute",
            "uuid_attribute",
            "user_object_classes",
            "group_object_classes",
            "group_name_attribute",
            "membership_attribute",
            "membership_attribute_type",
            "membership_user_attribute",
            "user_search_scope",
            "preserve_group_inheritance",
            "custom_user_filter",
            "group_path",
        },
        context="identity",
    )
    identity_mode = _string(identity_raw, "mode", context="identity")
    if identity_mode not in DIRECTORY_MODES:
        raise ConfigError("identity.mode must be freeipa, ldap, active-directory, or preconfigured")

    def string_tuple(key: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
        value = identity_raw.get(key, list(default))
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            raise ConfigError(f"identity.{key} must be an array of non-empty strings")
        return tuple(item.strip() for item in value)

    required_directory = identity_mode != "preconfigured"
    for field in (
        "server_url",
        "users_dn",
        "groups_dn",
        "bind_dn",
        "bind_secret_name",
        "bind_secret_key",
        "ca_secret_name",
        "ca_secret_key",
        "username_attribute",
        "rdn_attribute",
        "uuid_attribute",
        "membership_attribute",
        "membership_attribute_type",
        "membership_user_attribute",
        "group_name_attribute",
        "user_search_scope",
        "custom_user_filter",
    ):
        if required_directory:
            _required(identity_raw, field, context="identity")
    identity = IdentityConfig(
        mode=identity_mode,
        realm=_dns_label(_string(identity_raw, "realm", context="identity", default="nomosmart"), context="identity.realm"),
        provider_name=_dns_label(_string(identity_raw, "provider_name", context="identity"), context="identity.provider_name"),
        mapper_name=_dns_label(
            _string(identity_raw, "mapper_name", context="identity"),
            context="identity.mapper_name",
        ),
        admin_username=_string(identity_raw, "admin_username", context="identity"),
        external_group_name=_string(identity_raw, "external_group_name", context="identity"),
        local_role_name=_string(identity_raw, "local_role_name", context="identity"),
        server_url=(
            _ldaps(
                _string(identity_raw, "server_url", context="identity"),
                context="identity.server_url",
            )
            if required_directory
            else _optional_string(
                identity_raw, "server_url", context="identity"
            )
        ),
        users_dn=_optional_string(identity_raw, "users_dn", context="identity"),
        groups_dn=_optional_string(identity_raw, "groups_dn", context="identity"),
        bind_dn=_optional_string(identity_raw, "bind_dn", context="identity"),
        bind_secret_name=_optional_string(identity_raw, "bind_secret_name", context="identity"),
        bind_secret_key=_optional_string(identity_raw, "bind_secret_key", context="identity"),
        ca_secret_name=_optional_string(identity_raw, "ca_secret_name", context="identity"),
        ca_secret_key=_optional_string(identity_raw, "ca_secret_key", context="identity") or "ca.crt",
        username_attribute=_optional_string(identity_raw, "username_attribute", context="identity"),
        rdn_attribute=_optional_string(identity_raw, "rdn_attribute", context="identity"),
        uuid_attribute=_optional_string(identity_raw, "uuid_attribute", context="identity"),
        user_object_classes=string_tuple("user_object_classes"),
        group_object_classes=string_tuple("group_object_classes"),
        group_name_attribute=_optional_string(
            identity_raw, "group_name_attribute", context="identity"
        ),
        membership_attribute=_optional_string(identity_raw, "membership_attribute", context="identity"),
        membership_attribute_type=_optional_string(
            identity_raw, "membership_attribute_type", context="identity"
        ),
        membership_user_attribute=_optional_string(identity_raw, "membership_user_attribute", context="identity"),
        user_search_scope=_optional_string(
            identity_raw, "user_search_scope", context="identity"
        ),
        preserve_group_inheritance=_boolean(
            identity_raw,
            "preserve_group_inheritance",
            context="identity",
            default=True,
        ),
        custom_user_filter=_optional_string(identity_raw, "custom_user_filter", context="identity"),
        group_path=_string(identity_raw, "group_path", context="identity", default="/ldap"),
    )
    if required_directory and (not identity.user_object_classes or not identity.group_object_classes):
        raise ConfigError("directory profile requires user_object_classes and group_object_classes")
    if required_directory and identity.membership_attribute_type not in {"DN", "UID"}:
        raise ConfigError("identity.membership_attribute_type must be DN or UID")
    if required_directory and identity.user_search_scope not in {"one-level", "subtree"}:
        raise ConfigError("identity.user_search_scope must be one-level or subtree")
    if identity.local_role_name != "system-admin":
        raise ConfigError(
            "identity.local_role_name must be system-admin for the designated finalization administrator"
        )
    if (
        not identity.group_path.startswith("/")
        or "//" in identity.group_path
        or identity.group_path.endswith("/")
    ):
        raise ConfigError(
            "identity.group_path must be an absolute Keycloak group path without a trailing slash"
        )

    return InstallConfig(
        api_version=api_version,
        deployment_profile=deployment_profile,
        target=target,
        application=application,
        images=images,
        release=release,
        identity=identity,
        source_path=source,
    )
