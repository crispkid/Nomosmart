"""Official installation inputs; these references are not publication targets."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .contract import FIXED_PLATFORM_IMAGES, ReleaseContractError, SHA256


LOCK_PATH = Path(__file__).resolve().parents[1] / "external-dependencies.lock.json"
PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})
OFFICIAL_REPOSITORIES = {
    "migration": "flyway/flyway",
    "postgresql": "postgres",
    "postgresql_operator": "ghcr.io/cloudnative-pg/postgresql",
    "redis": "redis",
    "rustfs": "rustfs/rustfs",
    "opensearch": "opensearchproject/opensearch",
    "neo4j": "neo4j",
    "keycloak": "quay.io/keycloak/keycloak",
    "edge": "nginx",
    "debug_proxy": "alpine/socat",
    "cloudnativepg_operator": "ghcr.io/cloudnative-pg/cloudnative-pg",
    "barman_cloud_plugin": "ghcr.io/cloudnative-pg/plugin-barman-cloud",
    "barman_cloud_sidecar": "ghcr.io/cloudnative-pg/plugin-barman-cloud-sidecar",
}
OFFICIAL_DOWNLOADS = {
    "opensearch_repository_s3": r"https://artifacts\.opensearch\.org/releases/plugins/repository-s3/(\d+\.\d+\.\d+)/repository-s3-\1\.zip",
    "cloudnativepg_manifest": r"https://raw\.githubusercontent\.com/cloudnative-pg/cloudnative-pg/v(\d+\.\d+\.\d+)/releases/cnpg-\1\.yaml",
    "barman_manifest": r"https://github\.com/cloudnative-pg/plugin-barman-cloud/releases/download/v\d+\.\d+\.\d+/manifest\.yaml",
}


def validate_dependencies(payload: Any, *, version: str) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "release_version", "images", "downloads"}
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != 1
        or payload.get("release_version") != version
    ):
        raise ReleaseContractError("official dependency lock type or version is invalid")
    images = payload["images"]
    if not isinstance(images, dict) or set(images) != set(OFFICIAL_REPOSITORIES):
        raise ReleaseContractError("official dependency image inventory differs")
    for name, repository in OFFICIAL_REPOSITORIES.items():
        row = images[name]
        if not isinstance(row, dict) or set(row) != {"reference", "platforms"}:
            raise ReleaseContractError(f"official dependency fields differ: {name}")
        reference = row["reference"]
        pattern = re.escape(repository) + r":[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}"
        if not isinstance(reference, str) or not re.fullmatch(pattern, reference):
            raise ReleaseContractError(f"official dependency source or digest is invalid: {name}")
        tag = reference.split("@", 1)[0].rsplit(":", 1)[1]
        if tag in {"latest", "stable", "main", "master"}:
            raise ReleaseContractError(f"official dependency requires a version tag: {name}")
        platforms = row["platforms"]
        if not isinstance(platforms, dict) or set(platforms) != PLATFORMS or any(
            not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            for digest in platforms.values()
        ):
            raise ReleaseContractError(f"official dependency platform identity is incomplete: {name}")
        if name in FIXED_PLATFORM_IMAGES and (
            repository + "@" + reference.split("@", 1)[1] != FIXED_PLATFORM_IMAGES[name]
        ):
            raise ReleaseContractError(f"official platform differs from installer contract: {name}")
    downloads = payload["downloads"]
    if not isinstance(downloads, dict) or set(downloads) != set(OFFICIAL_DOWNLOADS):
        raise ReleaseContractError("official download inventory differs")
    for name, pattern in OFFICIAL_DOWNLOADS.items():
        row = downloads[name]
        if (
            not isinstance(row, dict) or set(row) != {"url", "sha256"}
            or not isinstance(row["url"], str) or not re.fullmatch(pattern, row["url"])
            or not isinstance(row["sha256"], str) or not SHA256.fullmatch(row["sha256"])
        ):
            raise ReleaseContractError(f"official download URL or checksum is invalid: {name}")
    opensearch_version = images["opensearch"]["reference"].split("@", 1)[0].rsplit(":", 1)[1]
    if f"/repository-s3/{opensearch_version}/" not in downloads["opensearch_repository_s3"]["url"]:
        raise ReleaseContractError("OpenSearch and repository-s3 versions differ")
    return payload


def load_dependencies(path: Path = LOCK_PATH, *, version: str = "0.1.2") -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReleaseContractError("official dependency lock is unavailable or invalid") from exc
    return validate_dependencies(payload, version=version)


def installer_images(application_images: dict[str, str], dependencies: dict[str, Any]) -> dict[str, str]:
    """The installer's PostgreSQL image is the CNPG operand, not standalone PG."""
    result = dict(application_images)
    result.update({name: dependencies["images"][name]["reference"] for name in (
        "migration", "redis", "rustfs", "opensearch", "neo4j", "keycloak"
    )})
    result["postgresql"] = dependencies["images"]["postgresql_operator"]["reference"]
    return result
