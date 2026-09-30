#!/usr/bin/env python3
"""NomoSmart operator-owned Secret package initializer.

This command never writes a plaintext credential receipt. Raw values live only
in mode-0600 Secret files and, on an interactive first init, the operator TTY.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import string
import subprocess
import sys
from typing import Final
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "migrations"))
from nomosmart_migrations import environment as migration_environment


SCHEMA_VERSION: Final[int] = 3
FACTORY_PROFILE: Final[str] = "factory_acceptance"
PRODUCTION_PROFILE: Final[str] = "production"
DEFAULT_PUBLIC_HOST: Final[str] = "nomosmart.local"
TLS_VALID_DAYS: Final[int] = 365
DEFAULT_COMPOSE_DIR = Path(__file__).resolve().parents[1] / "docker" / "generated"
DEFAULT_HELM_DIR = Path(__file__).resolve().parent / "generated" / "helm"

TLS_FILES: Final[tuple[str, ...]] = (
    "edge.crt",
    "edge.key",
    "edge-ca.crt",
    "rustfs.crt",
    "rustfs.key",
    "rustfs-ca.crt",
    "postgresql.crt",
    "postgresql.key",
    "postgresql-replication.crt",
    "postgresql-replication.key",
    "postgresql-ca.crt",
    "redis.crt",
    "redis.key",
    "redis-ca.crt",
    "opensearch.crt",
    "opensearch.key",
    "opensearch-transport.crt",
    "opensearch-transport.key",
    "opensearch-ca.crt",
)
EDGE_TLS_FILES: Final[tuple[str, ...]] = (
    "edge.crt",
    "edge.key",
    "edge-ca.crt",
)

USERNAMES: Final[dict[str, str]] = {
    "break_glass": "nomosmart",
    "postgres_admin": "postgres",
    "postgres_app": "nomosmart",
    "postgres_migration": "nomosmart",
    "keycloak_db": "nomosmart",
    "keycloak_bootstrap": "nomosmart",
    "keycloak_sync": "nomosmart-sync",
    "rustfs": "nomosmart",
    "redis_service": "nomosmart",
    "redis_replication": "nomosmart",
    "redis_sentinel": "nomosmart",
    "opensearch_admin": "admin",
    "opensearch_service": "nomosmart",
    "neo4j_admin": "neo4j",
    "neo4j_service": "nomosmart",
}

PRIMITIVE_SECRET_NAMES: Final[tuple[str, ...]] = (
    "app_encryption_key",
    "postgres_admin_password",
    "postgres_app_password",
    "postgres_migration_password",
    "keycloak_db_password",
    "keycloak_bootstrap_admin_password",
    "oidc_client_secret",
    "keycloak_sync_client_secret",
    "rustfs_secret_access_key",
    "redis_password",
    "redis_replication_password",
    "redis_sentinel_password",
    "opensearch_admin_password",
    "opensearch_service_password",
    "neo4j_admin_password",
    "neo4j_service_password",
)

KNOWN_PERIPHERAL_SECRET_NAMES: Final[frozenset[str]] = frozenset(
    {
        "postgres_admin_password",
        "postgres_app_password",
        "postgres_migration_password",
        "keycloak_db_password",
        "keycloak_bootstrap_admin_password",
        "rustfs_secret_access_key",
        "redis_password",
        "redis_replication_password",
        "redis_sentinel_password",
        "opensearch_admin_password",
        "opensearch_service_password",
        "neo4j_admin_password",
        "neo4j_service_password",
    }
)

HELM_SECRET_KEYS: Final[dict[str, str]] = {
    "app_encryption_key": "APP_ENCRYPTION_KEY",
    "postgres_admin_password": "POSTGRES_ADMIN_PASSWORD",
    "postgres_app_password": "POSTGRES_PASSWORD",
    "postgres_migration_password": "POSTGRES_MIGRATION_PASSWORD",
    "keycloak_db_password": "KEYCLOAK_DB_PASSWORD",
    "keycloak_bootstrap_admin_password": "KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD",
    "keycloak_bootstrap_admin_username": "KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME",
    "oidc_client_secret": "OIDC_CLIENT_SECRET",
    "keycloak_sync_client_secret": "KEYCLOAK_SYNC_CLIENT_SECRET",
    "rustfs_secret_access_key": "S3_SECRET_ACCESS_KEY",
    "redis_password": "REDIS_PASSWORD",
    "redis_replication_password": "REDIS_REPLICATION_PASSWORD",
    "redis_sentinel_password": "REDIS_SENTINEL_PASSWORD",
    "opensearch_admin_password": "OPENSEARCH_ADMIN_PASSWORD",
    "opensearch_service_password": "OPENSEARCH_PASSWORD",
    "neo4j_admin_password": "NEO4J_ADMIN_PASSWORD",
    "neo4j_service_password": "NEO4J_PASSWORD",
    "break_glass_initial_password": "BREAK_GLASS_INITIAL_PASSWORD",
    "database_url": "DATABASE_URL",
    "database_migration_user": "DATABASE_MIGRATION_USER",
    "database_migration_password": "DATABASE_MIGRATION_PASSWORD",
    "redis_url": "REDIS_URL",
    "celery_broker_url": "CELERY_BROKER_URL",
    "celery_result_backend": "CELERY_RESULT_BACKEND",
    "s3_access_key_id": "S3_ACCESS_KEY_ID",
    "neo4j_auth": "NEO4J_AUTH",
}


class PackageError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _random_secret() -> str:
    return secrets.token_hex(32)


def _random_opensearch_password() -> str:
    # Keep the value URL-safe while satisfying OpenSearch's mandatory four
    # character classes.
    # Sixty random characters from this 64-character alphabet alone provide
    # 360 bits of entropy; the four mandatory characters add more randomness.
    alphabet = string.ascii_letters + string.digits + "-_"
    characters = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        "-",
        *(secrets.choice(alphabet) for _ in range(60)),
    ]
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ensure_private_directory(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise PackageError("output path must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PackageError("output directory permissions are too broad")


def _write_private(path: Path, value: str, *, trailing_newline: bool = True) -> None:
    if path.exists():
        raise PackageError("refusing to overwrite an existing generated file")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            if trailing_newline:
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _validate_public_host(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    if (
        not host
        or len(host) > 253
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
        or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in host.split("."))
    ):
        raise PackageError("public host must be a valid DNS hostname")
    return host


def _validate_dns_label(value: str, *, context: str) -> str:
    label = value.strip().lower()
    if (
        not label
        or len(label) > 63
        or not re.fullmatch(
            r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", label
        )
    ):
        raise PackageError(f"{context} must be a Kubernetes DNS label")
    return label


def _run_openssl(*arguments: str, input_text: str | None = None) -> str:
    if shutil.which("openssl") is None:
        raise PackageError("openssl is required to create and inspect the TLS package")
    completed = subprocess.run(
        ["openssl", *arguments],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PackageError("TLS generation or validation failed")
    return completed.stdout.strip()


def _copy_private(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise PackageError("trusted TLS source must contain regular files")
    if destination.exists():
        raise PackageError("refusing to overwrite existing TLS material")
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o600)


def _certificate_public_key(path: Path) -> str:
    return _run_openssl("x509", "-in", str(path), "-pubkey", "-noout")


def _private_key_public_key(path: Path) -> str:
    return _run_openssl("pkey", "-in", str(path), "-pubout")


def _certificate_metadata(path: Path, *, source: str) -> dict[str, str]:
    fingerprint = _run_openssl("x509", "-in", str(path), "-noout", "-fingerprint", "-sha256")
    return {
        "source": source,
        "sha256_fingerprint": fingerprint.split("=", 1)[-1].replace(":", "").lower(),
        "subject": _run_openssl("x509", "-in", str(path), "-noout", "-subject").split("=", 1)[-1].strip(),
        "issuer": _run_openssl("x509", "-in", str(path), "-noout", "-issuer").split("=", 1)[-1].strip(),
        "not_after": _run_openssl("x509", "-in", str(path), "-noout", "-enddate").split("=", 1)[-1].strip(),
        "subject_alt_name": _run_openssl("x509", "-in", str(path), "-noout", "-ext", "subjectAltName"),
    }


def _validate_certificate_set(
    directory: Path,
    *,
    public_host: str,
    source: str,
    target: str,
    helm_fullname: str,
    helm_release: str,
    helm_namespace: str,
) -> dict[str, dict[str, str]]:
    rustfs_host = f"{helm_fullname}-rustfs" if target == "helm" else "rustfs"
    opensearch_host = (
        f"{helm_fullname}-opensearch"
        if target == "helm"
        else "opensearch"
    )
    postgresql_host = (
        f"{helm_fullname}-postgresql-rw" if target == "helm" else "postgresql"
    )
    redis_host = (
        f"{helm_fullname}-redis-sentinel" if target == "helm" else "redis"
    )
    expected_names = {
        "edge": (f"DNS:{public_host}",),
        "rustfs": (f"DNS:{rustfs_host}",),
        "postgresql": (f"DNS:{postgresql_host}",),
        "redis": (f"DNS:{redis_host}",),
        "opensearch": (f"DNS:{opensearch_host}",),
    }
    metadata: dict[str, dict[str, str]] = {}
    for component, expected_sans in expected_names.items():
        certificate = directory / f"{component}.crt"
        private_key = directory / f"{component}.key"
        ca_certificate = directory / f"{component}-ca.crt"
        if not all(path.is_file() and not path.is_symlink() for path in (certificate, private_key, ca_certificate)):
            raise PackageError("TLS package is missing a required certificate, key, or CA file")
        if _certificate_public_key(certificate) != _private_key_public_key(private_key):
            raise PackageError("TLS private key does not match its certificate")
        _run_openssl("verify", "-CAfile", str(ca_certificate), str(certificate))
        certificate_metadata = _certificate_metadata(certificate, source=source)
        if any(
            expected_san not in certificate_metadata["subject_alt_name"]
            for expected_san in expected_sans
        ):
            raise PackageError("TLS certificate subjectAltName does not match its service")
        metadata[component] = certificate_metadata
    transport_certificate = directory / "opensearch-transport.crt"
    transport_key = directory / "opensearch-transport.key"
    opensearch_ca = directory / "opensearch-ca.crt"
    if not all(
        path.is_file() and not path.is_symlink()
        for path in (transport_certificate, transport_key, opensearch_ca)
    ):
        raise PackageError("TLS package is missing the OpenSearch transport identity")
    if _certificate_public_key(transport_certificate) != _private_key_public_key(transport_key):
        raise PackageError("OpenSearch transport private key does not match its certificate")
    _run_openssl("verify", "-CAfile", str(opensearch_ca), str(transport_certificate))
    transport_metadata = _certificate_metadata(transport_certificate, source=source)
    headless = f"{opensearch_host}-headless"
    expected_transport_sans = (
        f"DNS:*.{headless}",
        f"DNS:*.{headless}.{helm_namespace}.svc.cluster.local",
    ) if target == "helm" else ("DNS:opensearch",)
    if any(
        expected_san not in transport_metadata["subject_alt_name"]
        for expected_san in expected_transport_sans
    ):
        raise PackageError("OpenSearch transport certificate SAN does not match its peers")
    transport_eku = _run_openssl(
        "x509", "-in", str(transport_certificate), "-noout", "-ext", "extendedKeyUsage"
    )
    if "TLS Web Server Authentication" not in transport_eku or "TLS Web Client Authentication" not in transport_eku:
        raise PackageError("OpenSearch transport certificate requires serverAuth and clientAuth")
    metadata["opensearch_transport"] = transport_metadata
    replication_certificate = directory / "postgresql-replication.crt"
    replication_key = directory / "postgresql-replication.key"
    postgresql_ca = directory / "postgresql-ca.crt"
    if not all(
        path.is_file() and not path.is_symlink()
        for path in (replication_certificate, replication_key, postgresql_ca)
    ):
        raise PackageError("TLS package is missing the PostgreSQL replication identity")
    if _certificate_public_key(replication_certificate) != _private_key_public_key(replication_key):
        raise PackageError("PostgreSQL replication private key does not match its certificate")
    _run_openssl("verify", "-CAfile", str(postgresql_ca), str(replication_certificate))
    replication_eku = _run_openssl(
        "x509", "-in", str(replication_certificate), "-noout", "-ext", "extendedKeyUsage"
    )
    if "TLS Web Client Authentication" not in replication_eku:
        raise PackageError("PostgreSQL replication certificate requires clientAuth")
    metadata["postgresql_replication"] = _certificate_metadata(
        replication_certificate, source=source
    )
    return metadata


def _validate_edge_certificate_set(
    directory: Path,
    *,
    public_host: str,
    source: str,
) -> dict[str, str]:
    certificate = directory / "edge.crt"
    private_key = directory / "edge.key"
    ca_certificate = directory / "edge-ca.crt"
    if not all(
        path.is_file() and not path.is_symlink()
        for path in (certificate, private_key, ca_certificate)
    ):
        raise PackageError("external profile requires edge certificate, key and CA")
    if _certificate_public_key(certificate) != _private_key_public_key(private_key):
        raise PackageError("edge private key does not match its certificate")
    _run_openssl("verify", "-CAfile", str(ca_certificate), str(certificate))
    metadata = _certificate_metadata(certificate, source=source)
    if f"DNS:{public_host}" not in metadata["subject_alt_name"]:
        raise PackageError("edge certificate subjectAltName does not match public host")
    extended_key_usage = _run_openssl(
        "x509", "-in", str(certificate), "-noout", "-ext", "extendedKeyUsage"
    )
    if "TLS Web Server Authentication" not in extended_key_usage:
        raise PackageError("edge certificate requires serverAuth")
    return metadata


def _generate_bundled_tls(
    directory: Path,
    *,
    public_host: str,
    target: str,
    helm_fullname: str,
    helm_release: str,
    helm_namespace: str,
) -> dict[str, dict[str, str]]:
    _ensure_private_directory(directory)
    work = directory / ".work"
    _ensure_private_directory(work)
    ca_key = work / "ca.key"
    ca_certificate = work / "ca.crt"
    opensearch_ca_key = work / "opensearch-ca.key"
    opensearch_ca_certificate = work / "opensearch-ca.crt"
    try:
        _run_openssl(
            "req",
            "-x509",
            "-newkey",
            "rsa:3072",
            "-sha256",
            "-nodes",
            "-days",
            str(TLS_VALID_DAYS),
            "-subj",
            "/CN=NomoSmart Local Package CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_certificate),
        )
        os.chmod(ca_key, 0o600)
        os.chmod(ca_certificate, 0o600)
        _run_openssl(
            "req",
            "-x509",
            "-newkey",
            "rsa:3072",
            "-sha256",
            "-nodes",
            "-days",
            "3650",
            "-subj",
            "/CN=NomoSmart OpenSearch Private CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout",
            str(opensearch_ca_key),
            "-out",
            str(opensearch_ca_certificate),
        )
        os.chmod(opensearch_ca_key, 0o600)
        os.chmod(opensearch_ca_certificate, 0o600)
        rustfs_host = (
            f"{helm_fullname}-rustfs" if target == "helm" else "rustfs"
        )
        postgresql_host = (
            f"{helm_fullname}-postgresql-rw" if target == "helm" else "postgresql"
        )
        postgresql_base = (
            f"{helm_fullname}-postgresql" if target == "helm" else "postgresql"
        )
        redis_host = (
            f"{helm_fullname}-redis-sentinel" if target == "helm" else "redis"
        )
        redis_base = f"{helm_fullname}-redis" if target == "helm" else "redis"
        opensearch_host = (
            f"{helm_fullname}-opensearch"
            if target == "helm"
            else "opensearch"
        )
        targets = {
            "edge": (public_host, f"DNS:{public_host},DNS:localhost,IP:127.0.0.1"),
            "rustfs": (
                rustfs_host,
                f"DNS:rustfs,DNS:{rustfs_host},DNS:{rustfs_host}-headless,"
                f"DNS:*.{rustfs_host}-headless,DNS:*.{rustfs_host}-headless.{helm_namespace},"
                f"DNS:*.{rustfs_host}-headless.{helm_namespace}.svc,"
                f"DNS:*.{rustfs_host}-headless.{helm_namespace}.svc.cluster.local",
            ),
            "postgresql": (
                postgresql_host,
                f"DNS:postgresql,DNS:{postgresql_host},DNS:{postgresql_base}-r,"
                f"DNS:{postgresql_base}-ro,DNS:{postgresql_base}-rw.{helm_namespace},"
                f"DNS:{postgresql_base}-rw.{helm_namespace}.svc,"
                f"DNS:{postgresql_base}-rw.{helm_namespace}.svc.cluster.local,"
                f"DNS:*.{postgresql_base}-rw,DNS:*.{postgresql_base}-r,DNS:*.{postgresql_base}-ro,"
                f"DNS:{postgresql_base}-1,DNS:{postgresql_base}-2,DNS:{postgresql_base}-3,"
                f"DNS:{postgresql_base}-1.{helm_namespace}.svc.cluster.local,"
                f"DNS:{postgresql_base}-2.{helm_namespace}.svc.cluster.local,"
                f"DNS:{postgresql_base}-3.{helm_namespace}.svc.cluster.local",
            ),
            "redis": (
                redis_host,
                f"DNS:redis,DNS:{redis_host},DNS:{redis_base}-headless,"
                f"DNS:*.{redis_base}-headless,DNS:*.{redis_base}-headless.{helm_namespace},"
                f"DNS:*.{redis_base}-headless.{helm_namespace}.svc,"
                f"DNS:*.{redis_base}-headless.{helm_namespace}.svc.cluster.local",
            ),
            "opensearch": (
                opensearch_host,
                f"DNS:opensearch,DNS:{opensearch_host},"
                f"DNS:{opensearch_host}.{helm_namespace},"
                f"DNS:{opensearch_host}.{helm_namespace}.svc,"
                f"DNS:{opensearch_host}.{helm_namespace}.svc.cluster.local",
            ),
        }
        for component, (common_name, san) in targets.items():
            key = directory / f"{component}.key"
            certificate = directory / f"{component}.crt"
            request = work / f"{component}.csr"
            extensions = work / f"{component}.ext"
            _run_openssl(
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-nodes",
                "-subj",
                f"/CN={common_name}",
                "-keyout",
                str(key),
                "-out",
                str(request),
            )
            _write_private(
                extensions,
                "\n".join(
                    (
                        "basicConstraints=critical,CA:FALSE",
                        "keyUsage=critical,digitalSignature,keyEncipherment",
                        "extendedKeyUsage=serverAuth",
                        f"subjectAltName={san}",
                    )
                ),
            )
            signing_certificate = opensearch_ca_certificate if component == "opensearch" else ca_certificate
            signing_key = opensearch_ca_key if component == "opensearch" else ca_key
            _run_openssl(
                "x509",
                "-req",
                "-in",
                str(request),
                "-CA",
                str(signing_certificate),
                "-CAkey",
                str(signing_key),
                "-CAcreateserial",
                "-days",
                str(TLS_VALID_DAYS),
                "-sha256",
                "-extfile",
                str(extensions),
                "-out",
                str(certificate),
            )
            os.chmod(key, 0o600)
            os.chmod(certificate, 0o600)
            _copy_private(signing_certificate, directory / f"{component}-ca.crt")
        transport_key = directory / "opensearch-transport.key"
        transport_certificate = directory / "opensearch-transport.crt"
        transport_request = work / "opensearch-transport.csr"
        transport_extensions = work / "opensearch-transport.ext"
        headless = f"{opensearch_host}-headless"
        transport_san = (
            f"DNS:{headless},DNS:{headless}.{helm_namespace},"
            f"DNS:{headless}.{helm_namespace}.svc,"
            f"DNS:{headless}.{helm_namespace}.svc.cluster.local,"
            f"DNS:*.{headless},DNS:*.{headless}.{helm_namespace},"
            f"DNS:*.{headless}.{helm_namespace}.svc,"
            f"DNS:*.{headless}.{helm_namespace}.svc.cluster.local"
            if target == "helm"
            else "DNS:opensearch"
        )
        _run_openssl(
            "req", "-new", "-newkey", "rsa:2048", "-sha256", "-nodes",
            "-subj", "/CN=nomosmart-opensearch-node", "-keyout", str(transport_key),
            "-out", str(transport_request),
        )
        _write_private(
            transport_extensions,
            "\n".join((
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,keyEncipherment",
                "extendedKeyUsage=serverAuth,clientAuth",
                f"subjectAltName={transport_san}",
            )),
        )
        _run_openssl(
            "x509", "-req", "-in", str(transport_request), "-CA",
            str(opensearch_ca_certificate), "-CAkey", str(opensearch_ca_key),
            "-CAcreateserial", "-days", str(TLS_VALID_DAYS), "-sha256",
            "-extfile", str(transport_extensions), "-out", str(transport_certificate),
        )
        os.chmod(transport_key, 0o600)
        os.chmod(transport_certificate, 0o600)
        replication_key = directory / "postgresql-replication.key"
        replication_certificate = directory / "postgresql-replication.crt"
        replication_request = work / "postgresql-replication.csr"
        replication_extensions = work / "postgresql-replication.ext"
        _run_openssl(
            "req", "-new", "-newkey", "rsa:2048", "-sha256", "-nodes",
            "-subj", "/CN=streaming_replica", "-keyout", str(replication_key),
            "-out", str(replication_request),
        )
        _write_private(
            replication_extensions,
            "\n".join((
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,keyEncipherment",
                "extendedKeyUsage=clientAuth",
            )),
        )
        _run_openssl(
            "x509", "-req", "-in", str(replication_request), "-CA",
            str(ca_certificate), "-CAkey", str(ca_key), "-CAcreateserial",
            "-days", str(TLS_VALID_DAYS), "-sha256", "-extfile",
            str(replication_extensions), "-out", str(replication_certificate),
        )
        os.chmod(replication_key, 0o600)
        os.chmod(replication_certificate, 0o600)
        return _validate_certificate_set(
            directory,
            public_host=public_host,
            source="bundled_self_signed",
            target=target,
            helm_fullname=helm_fullname,
            helm_release=helm_release,
            helm_namespace=helm_namespace,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _copy_tls_set(source: Path, destination: Path) -> None:
    _ensure_private_directory(destination)
    for name in TLS_FILES:
        _copy_private(source / name, destination / name)


def _copy_tls_files(
    source: Path,
    destination: Path,
    names: tuple[str, ...],
) -> None:
    _ensure_private_directory(destination)
    for name in names:
        _copy_private(source / name, destination / name)


def _replace_private(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise PackageError("trusted TLS source must contain regular files")
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o600)


def _prepare_tls(
    staging: Path,
    *,
    public_host: str,
    trusted_tls_dir: str,
    external_services: bool = False,
    target: str,
    helm_fullname: str,
    helm_release: str,
    helm_namespace: str,
) -> dict[str, object]:
    tls_root = staging / "tls"
    _ensure_private_directory(tls_root)
    bundled = tls_root / "bundled"
    bundled_metadata = _generate_bundled_tls(
        bundled,
        public_host=public_host,
        target=target,
        helm_fullname=helm_fullname,
        helm_release=helm_release,
        helm_namespace=helm_namespace,
    )
    active_source = "bundled_self_signed"
    active_input = bundled
    operator_metadata: dict[str, dict[str, str]] | None = None
    if trusted_tls_dir and external_services:
        supplied = Path(trusted_tls_dir).expanduser().resolve()
        operator = tls_root / "operator"
        _copy_tls_files(supplied, operator, EDGE_TLS_FILES)
        operator_metadata = {
            "edge": _validate_edge_certificate_set(
                supplied,
                public_host=public_host,
                source="operator_provided",
            )
        }
        active_input = tls_root / "external-active"
        _copy_tls_set(bundled, active_input)
        for name in EDGE_TLS_FILES:
            _replace_private(supplied / name, active_input / name)
        active_source = "operator_provided_edge"
    elif trusted_tls_dir:
        supplied = Path(trusted_tls_dir).expanduser().resolve()
        operator = tls_root / "operator"
        _copy_tls_set(supplied, operator)
        operator_metadata = _validate_certificate_set(
            operator,
            public_host=public_host,
            source="operator_provided",
            target=target,
            helm_fullname=helm_fullname,
            helm_release=helm_release,
            helm_namespace=helm_namespace,
        )
        active_source = "operator_provided"
        active_input = operator
    active = tls_root / "active"
    _copy_tls_set(active_input, active)
    active_metadata = _validate_certificate_set(
        active,
        public_host=public_host,
        source=active_source,
        target=target,
        helm_fullname=helm_fullname,
        helm_release=helm_release,
        helm_namespace=helm_namespace,
    )
    return {
        "active_source": active_source,
        "public_host": public_host,
        "helm_fullname": helm_fullname if target == "helm" else "",
        "helm_release": helm_release if target == "helm" else "",
        "bundled": bundled_metadata,
        "active": active_metadata,
        "operator": operator_metadata,
    }


def _validate_profile(profile: str, app_env: str) -> None:
    if profile == FACTORY_PROFILE and app_env != "development":
        raise PackageError("factory acceptance requires APP_ENV=development")
    if profile == PRODUCTION_PROFILE and app_env != "production":
        raise PackageError("production profile requires APP_ENV=production")


def _build_values(
    profile: str,
    target: str,
    *,
    first_use: bool,
    helm_fullname: str = "nomosmart",
    docker_desktop_local: bool = False,
) -> dict[str, str]:
    values = {name: _random_secret() for name in PRIMITIVE_SECRET_NAMES}
    if first_use:
        for name in KNOWN_PERIPHERAL_SECRET_NAMES:
            values[name] = "P@ssw0rd"
    if target == "compose" or docker_desktop_local:
        values["opensearch_admin_password"] = _random_opensearch_password()
        values["opensearch_service_password"] = _random_opensearch_password()
        while values["opensearch_service_password"] == values["opensearch_admin_password"]:
            values["opensearch_service_password"] = _random_opensearch_password()
    elif not first_use:
        values["opensearch_admin_password"] = _random_opensearch_password()
    values["break_glass_initial_password"] = (
        "P@ssw0rd"
        if first_use and docker_desktop_local
        else "nomosmart"
        if first_use
        else _random_secret()
    )
    cryptographic_values = [
        values[name]
        for name in ("app_encryption_key", "oidc_client_secret", "keycloak_sync_client_secret")
    ]
    if len(cryptographic_values) != len(set(cryptographic_values)):
        raise PackageError("generated cryptographic secrets are not unique")

    postgres_app_password = values["postgres_app_password"]
    postgres_migration_password = values["postgres_migration_password"]
    redis_password = values["redis_password"]
    postgres_app_password_uri = quote(postgres_app_password, safe="")
    redis_password_uri = quote(redis_password, safe="")
    postgres_host = (
        f"{helm_fullname}-postgresql-rw"
        if target == "helm"
        else "postgresql"
    )
    redis_host = (
        f"{helm_fullname}-redis-sentinel" if target == "helm" else "redis"
    )
    redis_scheme = "sentinel" if target == "helm" else "redis"
    redis_port = 26379 if target == "helm" else 6379
    postgres_tls_query = (
        "?sslmode=verify-full&sslrootcert=/etc/nomosmart/tls/postgresql-ca.crt"
        if target == "helm"
        else ""
    )
    values.update(
        {
            "database_url": (
                "postgresql+psycopg2://nomosmart:"
                f"{postgres_app_password_uri}@{postgres_host}:5432/nomosmart"
                f"{postgres_tls_query}"
            ),
            "flyway_jdbc_url": (
                f"jdbc:postgresql://{postgres_host}:5432/nomosmart"
                f"{postgres_tls_query}"
            ),
            "database_migration_user": USERNAMES["postgres_migration"],
            "database_migration_password": postgres_migration_password,
            "keycloak_bootstrap_admin_username": USERNAMES["keycloak_bootstrap"],
            "redis_url": f"{redis_scheme}://{USERNAMES['redis_service']}:{redis_password_uri}@{redis_host}:{redis_port}/0",
            "celery_broker_url": f"{redis_scheme}://{USERNAMES['redis_service']}:{redis_password_uri}@{redis_host}:{redis_port}/0",
            "celery_result_backend": f"{redis_scheme}://{USERNAMES['redis_service']}:{redis_password_uri}@{redis_host}:{redis_port}/1",
            "s3_access_key_id": USERNAMES["rustfs"],
            "neo4j_auth": f"{USERNAMES['neo4j_admin']}/{values['neo4j_admin_password']}",
        }
    )
    return values


def _target_file_name(target: str, name: str) -> str:
    if target == "helm":
        return HELM_SECRET_KEYS.get(name, name.upper())
    return name


def _manifest(
    target: str,
    profile: str,
    app_env: str,
    generation_id: str,
    values: dict[str, str],
    *,
    certificates: dict[str, object],
    deployment_state: str,
    first_use: bool,
    docker_desktop_local: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generation_id": generation_id,
        "created_at": _now(),
        "target": target,
        "profile": profile,
        "app_env": app_env,
        "deployment_state": deployment_state,
        "credential_mode": (
            "docker_desktop_local_fixed_with_random_opensearch"
            if first_use and docker_desktop_local
            else "first_use_fixed"
            if first_use
            else "rotation_random"
        ),
        "displayed_once": False,
        "usernames": USERNAMES,
        "certificates": certificates,
        "secrets": {
            name: {"file": _target_file_name(target, name), "sha256": _sha256(value)}
            for name, value in sorted(values.items())
        },
    }


def _safe_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError("generated package manifest is unavailable or invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise PackageError("generated package manifest schema is incompatible")
    return payload


def _write_manifest(directory: Path, payload: dict[str, object]) -> None:
    _write_private(directory / "manifest.json", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _display_once(values: dict[str, str], profile: str) -> None:
    if not sys.stdout.isatty():
        raise PackageError("one-time credential display requires an interactive TTY; use --no-display for secret-target-only automation")
    print("\nNomoSmart one-time credential handoff")
    print("Store these values in the approved password manager now; they will not be shown again.\n")
    print(f"break-glass username: {USERNAMES['break_glass']}")
    print(f"break-glass temporary password: {values['break_glass_initial_password']}")
    print(f"profile: {profile}\n")
    for name in sorted(values):
        if name == "break_glass_initial_password":
            continue
        print(f"{name}: {values[name]}")
    print("\nRequired: change the temporary password at first login.")


def _replace_manifest(directory: Path, payload: dict[str, object]) -> None:
    target = directory / "manifest.json"
    temporary = directory / ".manifest.next"
    _write_private(temporary, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    os.replace(temporary, target)


def _write_compose_env(
    profile: str,
    app_env: str,
    *,
    public_host: str,
    runbook_uri: str,
    alerting_evidence: str,
) -> None:
    docker_dir = Path(__file__).resolve().parents[1] / "docker"
    env_path = docker_dir / "nomosmart.env"
    if env_path.exists():
        return
    deployment_phase = FACTORY_PROFILE if profile == FACTORY_PROFILE else "onboarding"
    content = "\n".join(
        (
            "# Generated non-sensitive NomoSmart Compose configuration.",
            "# Raw credentials are mounted from deploy/docker/generated/current.",
            "COMPOSE_PROJECT_NAME=nomosmart",
            "COMPOSE_PROFILES=postgresql,redis,rustfs,opensearch,neo4j,keycloak",
            f"APP_ENV={app_env}",
            f"DEPLOYMENT_PHASE={deployment_phase}",
            "DEPLOYMENT_BOOTSTRAP_RELEASE=compose-initial",
            *(f"{name}={value}" for name, value in migration_environment().items()),
            f"NOMOSMART_PUBLIC_HOST={public_host}",
            f"NOMOSMART_PUBLIC_ORIGIN=https://{public_host}",
            f"CORS_ALLOWED_ORIGINS=https://{public_host}",
            f"FRONTEND_APP_ORIGIN=https://{public_host}",
            f"NEXT_PUBLIC_APP_ORIGIN=https://{public_host}",
            f"OIDC_ISSUER_URL=https://{public_host}/identity/realms/nomosmart",
            f"NEXT_PUBLIC_OIDC_ISSUER_URL=https://{public_host}/identity/realms/nomosmart",
            f"KEYCLOAK_ADMIN_API_URL=https://{public_host}/identity",
            "EDGE_HOST_IP=127.0.0.1",
            "EDGE_HTTP_PORT=80",
            "EDGE_HTTPS_PORT=443",
            "EDGE_TLS_CERT_FILE=./deploy/docker/generated/current/tls/active/edge.crt",
            "EDGE_TLS_KEY_FILE=./deploy/docker/generated/current/tls/active/edge.key",
            "RUSTFS_TLS_CERT_FILE=./deploy/docker/generated/current/tls/active/rustfs.crt",
            "RUSTFS_TLS_KEY_FILE=./deploy/docker/generated/current/tls/active/rustfs.key",
            "RUSTFS_TLS_CA_FILE=./deploy/docker/generated/current/tls/active/rustfs-ca.crt",
            "OPENSEARCH_TLS_CERT_FILE=./deploy/docker/generated/current/tls/active/opensearch.crt",
            "OPENSEARCH_TLS_KEY_FILE=./deploy/docker/generated/current/tls/active/opensearch.key",
            "OPENSEARCH_TLS_CA_FILE=./deploy/docker/generated/current/tls/active/opensearch-ca.crt",
            "S3_VERIFY_TLS=true",
            "OPENSEARCH_VERIFY_TLS=true",
            "ONBOARDING_ADMIN_ALLOW_CIDR=127.0.0.1/32",
            "BREAK_GLASS_USERNAME=nomosmart",
            f"BREAK_GLASS_RUNBOOK_URI={runbook_uri}",
            f"BREAK_GLASS_ALERTING_EVIDENCE={alerting_evidence}",
            "POSTGRES_USER=nomosmart",
            "DATABASE_MIGRATION_USER=nomosmart",
            "KEYCLOAK_DB_USER=nomosmart",
            "KEYCLOAK_ADMIN=nomosmart",
            "S3_ACCESS_KEY_ID=nomosmart",
            "OPENSEARCH_USERNAME=nomosmart",
            "NEO4J_USERNAME=nomosmart",
            "NEO4J_COMMUNITY_ADMIN_EQUIVALENT_ACCEPTED=true",
            "REDIS_USERNAME=nomosmart",
            "KEYCLOAK_SYNC_CLIENT_ID=nomosmart-sync",
            "",
        )
    )
    _write_private(env_path, content.rstrip("\n"))


def _output_root(args: argparse.Namespace) -> Path:
    if args.output_dir:
        return Path(args.output_dir).expanduser().resolve()
    return DEFAULT_COMPOSE_DIR if args.target == "compose" else DEFAULT_HELM_DIR


def init_package(args: argparse.Namespace, *, rotating: bool = False) -> int:
    _validate_profile(args.profile, args.app_env)
    docker_desktop_local = bool(getattr(args, "docker_desktop_local", False))
    if docker_desktop_local and (
        rotating
        or args.target != "helm"
        or args.profile != FACTORY_PROFILE
        or args.app_env != "development"
        or args.external_services
    ):
        raise PackageError(
            "docker-desktop-local is only valid for a fresh Helm factory_acceptance/development package"
        )
    public_host = _validate_public_host(args.public_host)
    if args.target == "compose" and args.profile == PRODUCTION_PROFILE:
        if not args.break_glass_runbook_uri.startswith("https://") or not args.break_glass_alerting_evidence.strip():
            raise PackageError("production Compose init requires an HTTPS break-glass runbook and alerting evidence")
    if not args.no_display and not sys.stdout.isatty():
        raise PackageError("one-time credential display requires an interactive TTY; use --no-display for secret-target-only automation")
    root = _output_root(args)
    _ensure_private_directory(root)
    current = root / "current"
    existing_payload: dict[str, object] | None = None
    if current.exists() and not rotating:
        payload = _safe_manifest(current / "manifest.json")
        print(json.dumps({"status": "already_initialized", **payload}, ensure_ascii=False, sort_keys=True))
        return 0
    if current.exists():
        existing_payload = _safe_manifest(current / "manifest.json")

    generation_id = secrets.token_hex(8)
    staging = root / f".next-{generation_id}"
    _ensure_private_directory(staging)
    first_use = not rotating
    default_helm_fullname = (
        str(existing_payload.get("helm_fullname") or "nomosmart")
        if existing_payload
        else "nomosmart"
    )
    default_helm_release = (
        str(existing_payload.get("helm_release") or "nomosmart")
        if existing_payload
        else "nomosmart"
    )
    helm_fullname = (
        _validate_dns_label(
            args.helm_fullname or default_helm_fullname,
            context="Helm fullname",
        )
        if args.target == "helm"
        else "nomosmart"
    )
    helm_release = (
        _validate_dns_label(
            args.helm_release or default_helm_release,
            context="Helm release",
        )
        if args.target == "helm"
        else "nomosmart"
    )
    values = _build_values(
        args.profile,
        args.target,
        first_use=first_use,
        helm_fullname=helm_fullname,
        docker_desktop_local=docker_desktop_local,
    )
    trusted_tls_dir = args.trusted_tls_dir
    if (
        rotating
        and not trusted_tls_dir
        and existing_payload is not None
        and isinstance(existing_payload.get("certificates"), dict)
        and existing_payload["certificates"].get("active_source")
        in {"operator_provided", "operator_provided_edge"}
    ):
        trusted_tls_dir = str(current / "tls" / "operator")
    certificates = _prepare_tls(
        staging,
        public_host=public_host,
        trusted_tls_dir=trusted_tls_dir,
        external_services=bool(args.external_services),
        target=args.target,
        helm_fullname=helm_fullname,
        helm_release=helm_release,
        helm_namespace=(
            _validate_dns_label(args.helm_namespace or "nomosmart", context="Helm namespace")
            if args.target == "helm" else "nomosmart"
        ),
    )
    deployment_state = str(existing_payload.get("deployment_state", "onboarding")) if existing_payload else "onboarding"
    payload = _manifest(
        args.target,
        args.profile,
        args.app_env,
        generation_id,
        values,
        certificates=certificates,
        deployment_state=deployment_state,
        first_use=first_use,
        docker_desktop_local=docker_desktop_local,
    )
    if args.target == "helm":
        payload["helm_fullname"] = helm_fullname
        payload["helm_release"] = helm_release
        payload["helm_namespace"] = _validate_dns_label(
            args.helm_namespace or "nomosmart", context="Helm namespace"
        )
    archived_previous: Path | None = None
    try:
        for name, value in values.items():
            # Kubernetes Secret --from-file preserves every byte. Keep scalar
            # Secret files newline-free so env-var consumers receive the exact
            # credential rather than a credential with a trailing LF.
            _write_private(staging / _target_file_name(args.target, name), value, trailing_newline=False)
        _write_manifest(staging, payload)
        if current.exists():
            previous_root = root / "previous"
            _ensure_private_directory(previous_root)
            previous_manifest = _safe_manifest(current / "manifest.json")
            previous_id = str(previous_manifest["generation_id"])
            previous = previous_root / previous_id
            if previous.exists():
                raise PackageError("previous generation target already exists")
            os.replace(current, previous)
            archived_previous = previous
        try:
            os.replace(staging, current)
        except Exception:
            if archived_previous is not None and archived_previous.exists() and not current.exists():
                os.replace(archived_previous, current)
            raise
        if args.target == "compose" and not args.output_dir:
            runbook_uri = args.break_glass_runbook_uri or f"https://{public_host}/runbooks/break-glass"
            alerting_evidence = args.break_glass_alerting_evidence or "factory-terminal-acceptance"
            _write_compose_env(
                args.profile,
                args.app_env,
                public_host=public_host,
                runbook_uri=runbook_uri,
                alerting_evidence=alerting_evidence,
            )
        if not args.no_display:
            _display_once(values, args.profile)
            payload["displayed_once"] = True
            payload["displayed_at"] = _now()
            _replace_manifest(current, payload)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    print(
        json.dumps(
            {
                "status": "initialized",
                "generation_id": generation_id,
                "deployment_state": deployment_state,
                "tls_source": certificates["active_source"],
            },
            sort_keys=True,
        )
    )
    return 0


def status_package(args: argparse.Namespace) -> int:
    current = _output_root(args) / "current"
    payload = _safe_manifest(current / "manifest.json")
    print(json.dumps({"status": "ok", **payload}, ensure_ascii=False, sort_keys=True))
    return 0


def rotate_package(args: argparse.Namespace) -> int:
    root = _output_root(args)
    current = root / "current"
    if not current.exists():
        raise PackageError("package is not initialized")
    existing = _safe_manifest(current / "manifest.json")
    if existing.get("profile") != args.profile or existing.get("app_env") != args.app_env:
        raise PackageError("rotation profile must match the current generation")
    return init_package(args, rotating=True)


def finalize_package(args: argparse.Namespace) -> int:
    root = _output_root(args)
    current = root / "current"
    payload = _safe_manifest(current / "manifest.json")
    if payload.get("deployment_state") not in {"onboarding", "acceptance_complete"}:
        raise PackageError("package is not in an onboarding state")
    if args.target != "compose":
        raise PackageError("Helm finalization must run through the in-cluster finalization Job")
    repo = Path(__file__).resolve().parents[2]
    command = [
        "docker",
        "compose",
        "--env-file",
        "deploy/docker/nomosmart.env",
        "run",
        "--rm",
        "deployment-finalize",
    ]
    completed = subprocess.run(command, cwd=repo, check=False)
    if completed.returncode != 0:
        raise PackageError("live deployment finalization failed")
    secret_details = payload.get("secrets", {}).get("break_glass_initial_password", {})
    retired_file = current / str(secret_details.get("file") or "break_glass_initial_password")
    retired_value = _random_secret()
    temporary = current / ".break-glass-retired"
    _write_private(temporary, retired_value, trailing_newline=False)
    os.replace(temporary, retired_file)
    secret_details["sha256"] = _sha256(retired_value)
    secret_details["retired"] = True
    payload["deployment_state"] = "acceptance_complete" if payload.get("profile") == FACTORY_PROFILE else "operational"
    payload["finalized_at"] = _now()
    _replace_manifest(current, payload)
    print(json.dumps({"status": "finalized", "deployment_state": payload["deployment_state"]}, sort_keys=True))
    return 0


def _local_host_mapping(path: Path, hostname: str) -> bool:
    mappings: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PackageError("local hosts file is unavailable") from exc
    for line in lines:
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2 and hostname in fields[1:]:
            mappings.append(fields[0])
    return mappings == ["127.0.0.1"]


def _compose_project_running(project: str) -> bool:
    completed = subprocess.run(
        ["docker", "compose", "ls", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PackageError("Docker Compose runtime status is unavailable")
    try:
        rows = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise PackageError("Docker Compose runtime status is invalid") from exc
    return any(
        isinstance(row, dict)
        and row.get("Name") == project
        and "running" in str(row.get("Status", "")).lower()
        for row in rows
    )


def _minikube_profile_running(profile: str) -> bool:
    try:
        completed = subprocess.run(
            ["minikube", "status", "-p", profile, "-o", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    if completed.returncode != 0:
        return False
    try:
        status = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PackageError("minikube runtime status is invalid") from exc
    return str(status.get("Host", "")).lower() == "running"


def _listening_on_public_ports() -> list[int]:
    busy: list[int] = []
    for port in (80, 443):
        completed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            busy.append(port)
    return busy


def preflight_package(args: argparse.Namespace) -> int:
    if not _local_host_mapping(Path("/etc/hosts"), DEFAULT_PUBLIC_HOST):
        raise PackageError("nomosmart.local must map exactly once to 127.0.0.1 in /etc/hosts")
    if args.runtime == "compose" and _minikube_profile_running(args.minikube_profile):
        raise PackageError("stop the complete NomoSmart minikube runtime before starting Compose")
    if args.runtime == "minikube" and _compose_project_running(args.compose_project):
        raise PackageError("stop the complete NomoSmart Compose runtime before starting minikube")
    busy = _listening_on_public_ports()
    if busy:
        raise PackageError("loopback public ports are already in use: " + ",".join(str(port) for port in busy))
    print(
        json.dumps(
            {
                "status": "ready",
                "runtime": args.runtime,
                "public_host": DEFAULT_PUBLIC_HOST,
                "host_address": "127.0.0.1",
                "ports": [80, 443],
                "other_runtime": "stopped",
            },
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nomosmart-package")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(command: str) -> argparse.ArgumentParser:
        child = subparsers.add_parser(command)
        child.add_argument("--target", choices=("compose", "helm"), default="compose")
        child.add_argument("--output-dir")
        return child

    init_parser = common("init")
    init_parser.add_argument("--profile", choices=(FACTORY_PROFILE, PRODUCTION_PROFILE), required=True)
    init_parser.add_argument("--app-env", choices=("development", "production"), required=True)
    init_parser.add_argument("--no-display", action="store_true")
    init_parser.add_argument("--public-host", default=DEFAULT_PUBLIC_HOST)
    init_parser.add_argument("--trusted-tls-dir", default="")
    init_parser.add_argument(
        "--external-services",
        action="store_true",
        help="use operator-provided edge TLS and generated inactive internal TLS",
    )
    init_parser.add_argument("--helm-fullname", default="")
    init_parser.add_argument("--helm-release", default="")
    init_parser.add_argument("--helm-namespace", default="")
    init_parser.add_argument("--break-glass-runbook-uri", default="")
    init_parser.add_argument("--break-glass-alerting-evidence", default="")
    init_parser.add_argument(
        "--docker-desktop-local",
        action="store_true",
        help="generate the DEPLOY-020 local Helm credential profile with strong random OpenSearch passwords",
    )
    init_parser.set_defaults(func=init_package)

    status_parser = common("status")
    status_parser.set_defaults(func=status_package)

    rotate_parser = common("rotate")
    rotate_parser.add_argument("--profile", choices=(FACTORY_PROFILE, PRODUCTION_PROFILE), required=True)
    rotate_parser.add_argument("--app-env", choices=("development", "production"), required=True)
    rotate_parser.add_argument("--no-display", action="store_true")
    rotate_parser.add_argument("--public-host", default=DEFAULT_PUBLIC_HOST)
    rotate_parser.add_argument("--trusted-tls-dir", default="")
    rotate_parser.add_argument(
        "--external-services",
        action="store_true",
        help="use operator-provided edge TLS and generated inactive internal TLS",
    )
    rotate_parser.add_argument("--helm-fullname", default="")
    rotate_parser.add_argument("--helm-release", default="")
    rotate_parser.add_argument("--helm-namespace", default="")
    rotate_parser.add_argument("--break-glass-runbook-uri", default="")
    rotate_parser.add_argument("--break-glass-alerting-evidence", default="")
    rotate_parser.set_defaults(func=rotate_package)

    finalize_parser = common("finalize")
    finalize_parser.set_defaults(func=finalize_package)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--runtime", choices=("compose", "minikube"), required=True)
    preflight_parser.add_argument("--compose-project", default="nomosmart")
    preflight_parser.add_argument("--minikube-profile", default="nomosmart-acceptance")
    preflight_parser.set_defaults(func=preflight_package)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return int(args.func(args))
    except PackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
