from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from urllib.parse import unquote, urlsplit

from app.core.config import Settings
from app.core.errors import AppError


_REFERENCE_SEGMENT = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


@dataclass(frozen=True)
class RuntimeSecretReference:
    provider: str
    name: str
    key: str | None = None


def _valid_segment(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 253
        and value not in {".", ".."}
        and all(character in _REFERENCE_SEGMENT for character in value)
    )


def parse_runtime_secret_reference(value: str) -> RuntimeSecretReference:
    """Parse the closed CHG-260 Kubernetes/Docker Secret reference surface."""

    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise AppError(
            "runtime_secret_reference_invalid",
            "Runtime secret reference is invalid",
            status_code=422,
        ) from exc
    if (
        parsed.username
        or parsed.password
        or port is not None
        or parsed.query
        or parsed.path not in {"", "/"}
    ):
        raise AppError(
            "runtime_secret_reference_invalid",
            "Runtime secret reference is invalid",
            status_code=422,
        )

    name = unquote(parsed.netloc)
    if not _valid_segment(name):
        raise AppError(
            "runtime_secret_reference_invalid",
            "Runtime secret reference is invalid",
            status_code=422,
        )

    if parsed.scheme == "k8s-secret":
        key = unquote(parsed.fragment)
        if not _valid_segment(key):
            raise AppError(
                "runtime_secret_reference_invalid",
                "Runtime secret reference is invalid",
                status_code=422,
            )
        return RuntimeSecretReference(provider="kubernetes", name=name, key=key)
    if parsed.scheme == "compose-secret" and not parsed.fragment:
        return RuntimeSecretReference(provider="compose", name=name)
    raise AppError(
        "runtime_secret_reference_invalid",
        "Runtime secret reference must use a supported mounted Secret provider",
        status_code=422,
    )


def validate_runtime_secret_reference(settings: Settings, reference: str) -> None:
    if reference.startswith("vault://"):
        raise AppError(
            "legacy_vault_reference_requires_migration",
            "Vault references are no longer supported; use a mounted Secret reference",
            status_code=422,
        )
    if settings.app_env != "production" and reference.startswith("env:"):
        name = reference.removeprefix("env:")
        if name and name.replace("_", "").isalnum():
            return
        raise AppError(
            "runtime_secret_reference_invalid",
            "Runtime secret reference is invalid",
            status_code=422,
        )
    parse_runtime_secret_reference(reference)


def _allowed_kubernetes_refs(settings: Settings) -> frozenset[str]:
    return frozenset(
        item.strip()
        for item in settings.runtime_secret_allowed_refs.split(",")
        if item.strip()
    )


def _read_mounted_secret(settings: Settings, reference: RuntimeSecretReference) -> str:
    if reference.provider == "kubernetes":
        canonical = f"{reference.name}#{reference.key}"
        allowlist = _allowed_kubernetes_refs(settings)
        wildcard = f"{reference.name}#*"
        if (
            settings.app_env == "production"
            and canonical not in allowlist
            and wildcard not in allowlist
        ):
            raise AppError(
                "runtime_secret_reference_denied",
                "Runtime secret reference is not mounted for this workload",
                status_code=403,
            )
        root = Path(settings.kubernetes_secret_mount_root)
        target = root / reference.name / str(reference.key)
    else:
        root = Path(settings.compose_secret_mount_root)
        target = root / reference.name

    try:
        root_resolved = root.resolve(strict=True)
        target_resolved = target.resolve(strict=True)
        target_resolved.relative_to(root_resolved)
        details = target_resolved.stat()
        if not stat.S_ISREG(details.st_mode):
            raise OSError
        if settings.app_env == "production" and stat.S_IMODE(details.st_mode) & 0o077:
            raise OSError
        value = target_resolved.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, ValueError) as exc:
        raise AppError(
            "runtime_secret_unavailable",
            "Mounted runtime secret is unavailable",
            status_code=503,
        ) from exc
    if not value:
        raise AppError(
            "runtime_secret_unavailable",
            "Mounted runtime secret is unavailable",
            status_code=503,
        )
    return value


def resolve_runtime_secret(settings: Settings, reference: str) -> str:
    if reference.startswith("vault://"):
        raise AppError(
            "legacy_vault_reference_requires_migration",
            "Legacy Vault reference must be migrated before this release can run",
            status_code=503,
        )
    if settings.app_env != "production" and reference.startswith("env:"):
        name = reference.removeprefix("env:")
        if name and name.replace("_", "").isalnum():
            value = os.getenv(name, "")
            if value:
                return value
    parsed = parse_runtime_secret_reference(reference)
    return _read_mounted_secret(settings, parsed)
