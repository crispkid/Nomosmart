from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Final


MANIFEST_SCHEMA_VERSION: Final[int] = 2
PACKAGE_TYPE: Final[str] = "nomosmart-production-release"
CONTROL_FILES: Final[frozenset[str]] = frozenset(
    {
        "release-manifest.json",
        "SHA256SUMS",
        "RELEASE-ATTESTATION.json",
        "RELEASE-ATTESTATION.json.asc",
        "release-signing-key.asc",
    }
)
REQUIRED_GATES: Final[tuple[str, ...]] = (
    "governance",
    "frontend_tests",
    "backend_tests",
    "installer_tests",
    "e2e",
    "frontend_coverage",
    "backend_coverage",
    "dependency_cve",
    "container_cve",
    "license_inventory",
    "spdx",
    "helm",
    "deployment_policy",
    "image_digest",
)
REQUIRED_EVIDENCE: Final[tuple[str, ...]] = (
    "frontend_coverage",
    "backend_coverage",
    "container_cve",
    "license_inventory",
    "runtime_spdx",
)
REQUIRED_IMAGES: Final[tuple[str, ...]] = (
    "frontend",
    "backend",
    "migration",
    "postgresql",
    "redis",
    "rustfs",
    "opensearch",
    "neo4j",
    "keycloak",
)
FIXED_PLATFORM_IMAGES: Final[dict[str, str]] = {
    "cloudnativepg_operator": (
        "ghcr.io/cloudnative-pg/cloudnative-pg@"
        "sha256:a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb"
    ),
    "barman_cloud_plugin": (
        "ghcr.io/cloudnative-pg/plugin-barman-cloud@"
        "sha256:71589dbac582333442812b07b31f7ea4d00324a8358aac7ca507dabf9f4b6c96"
    ),
    "barman_cloud_sidecar": (
        "ghcr.io/cloudnative-pg/plugin-barman-cloud-sidecar@"
        "sha256:990361af3319f9e23aafa0f6d7981f99bf1f69b4e6a85cf1bc7d71d6f09bb288"
    ),
}
ALL_RUNTIME_IMAGE_NAMES: Final[tuple[str, ...]] = (
    *REQUIRED_IMAGES,
    *FIXED_PLATFORM_IMAGES,
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT = re.compile(r"^[0-9A-F]{40,64}$")
IMAGE_DIGEST = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


class ReleaseContractError(RuntimeError):
    pass


def canonical_json(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseContractError(f"{label} is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise ReleaseContractError(f"{label} must be a JSON object")
    return payload


def _bounded_file(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or candidate.as_posix() != relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or "\\" in relative or any(ord(char) < 32 for char in relative)
    ):
        raise ReleaseContractError(f"release path is unsafe: {relative}")
    cursor = root
    for part in candidate.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReleaseContractError(
                f"release path contains a symlink: {relative}"
            )
    try:
        cursor.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ReleaseContractError(
            f"release path escapes package root: {relative}"
        ) from exc
    if not cursor.is_file():
        raise ReleaseContractError(f"release file is missing: {relative}")
    return cursor


def _normalize_fingerprint(value: str) -> str:
    normalized = re.sub(r"\s+", "", value).upper()
    if not FINGERPRINT.fullmatch(normalized):
        raise ReleaseContractError(
            "trusted release signer fingerprint must contain 40 to 64 hex characters"
        )
    return normalized


def validate_manifest(payload: dict[str, Any]) -> None:
    if (
        payload.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or payload.get("package_type") != PACKAGE_TYPE
        or payload.get("production_ready") is not True
    ):
        raise ReleaseContractError(
            "release manifest type, schema, or Production identity is invalid"
        )
    source = payload.get("source")
    if (
        not isinstance(source, dict)
        or not FULL_GIT_SHA.fullmatch(str(source.get("git_sha") or ""))
        or source.get("clean") is not True
        or source.get("detached") is not True
        or not SHA256.fullmatch(str(source.get("tree_sha256") or ""))
    ):
        raise ReleaseContractError(
            "release source identity is incomplete or not clean and detached"
        )
    signer = payload.get("signing")
    if not isinstance(signer, dict):
        raise ReleaseContractError("release signing identity is missing")
    _normalize_fingerprint(str(signer.get("fingerprint") or ""))

    gates = payload.get("gates")
    if not isinstance(gates, dict) or set(gates) != set(REQUIRED_GATES):
        raise ReleaseContractError("release mandatory gate inventory is incomplete")
    gate_paths: set[str] = set()
    for name in REQUIRED_GATES:
        row = gates.get(name)
        if (
            not isinstance(row, dict)
            or row.get("status") != "passed"
            or row.get("source_sha") != source["git_sha"]
            or not SHA256.fullmatch(str(row.get("evidence_sha256") or ""))
            or not isinstance(row.get("path"), str)
        ):
            raise ReleaseContractError(
                f"release mandatory gate did not pass for the same source: {name}"
            )
        gate_paths.add(str(row["path"]))

    images = payload.get("images")
    if not isinstance(images, dict) or set(images) != set(REQUIRED_IMAGES):
        raise ReleaseContractError("release image inventory is incomplete")
    for name, reference in images.items():
        if not isinstance(reference, str) or not IMAGE_DIGEST.fullmatch(reference):
            raise ReleaseContractError(
                f"release image is not digest pinned: {name}"
            )

    platform_images = payload.get("platform_images")
    if platform_images != FIXED_PLATFORM_IMAGES:
        raise ReleaseContractError(
            "release fixed platform image inventory differs from the supported contract"
        )

    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != set(REQUIRED_EVIDENCE):
        raise ReleaseContractError("release evidence inventory is incomplete")
    for name, row in evidence.items():
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("path"), str)
            or not SHA256.fullmatch(str(row.get("sha256") or ""))
            or row.get("source_sha") != source["git_sha"]
        ):
            raise ReleaseContractError(f"release evidence is invalid: {name}")

    compatibility = payload.get("compatibility")
    if (
        not isinstance(compatibility, dict)
        or not compatibility.get("application")
        or not compatibility.get("api")
        or not compatibility.get("chart_version")
        or not SHA256.fullmatch(str(compatibility.get("chart_sha256") or ""))
    ):
        raise ReleaseContractError(
            "release compatibility identity is incomplete"
        )

    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ReleaseContractError("release payload file inventory is empty")
    seen: set[str] = set()
    for row in files:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("path"), str)
            or not SHA256.fullmatch(str(row.get("sha256") or ""))
            or not isinstance(row.get("size"), int)
            or int(row["size"]) < 0
        ):
            raise ReleaseContractError("release payload file inventory is invalid")
        relative = str(row["path"])
        if relative in seen or relative in CONTROL_FILES:
            raise ReleaseContractError(
                f"release payload file is duplicate or reserved: {relative}"
            )
        seen.add(relative)
    evidence_paths = {str(evidence[name]["path"]) for name in evidence}
    if not (evidence_paths | gate_paths).issubset(seen):
        raise ReleaseContractError(
            "release gate/evidence is not covered by the payload checksum inventory"
        )


def _verify_signature(
    package_root: Path,
    *,
    trusted_fingerprint: str,
    gpg_binary: str,
) -> str:
    trusted = _normalize_fingerprint(trusted_fingerprint)
    key_path = _bounded_file(package_root, "release-signing-key.asc")
    attestation = _bounded_file(package_root, "RELEASE-ATTESTATION.json")
    signature = _bounded_file(
        package_root, "RELEASE-ATTESTATION.json.asc"
    )
    with tempfile.TemporaryDirectory(
        prefix="nomosmart-release-verify-"
    ) as temporary:
        home = Path(temporary)
        os.chmod(home, 0o700)
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(home),
            "GNUPGHOME": str(home),
            "LANG": "C",
            "LC_ALL": "C",
        }
        try:
            imported = subprocess.run(
                [
                    gpg_binary,
                    "--batch",
                    "--no-tty",
                    "--homedir",
                    str(home),
                    "--import",
                    str(key_path),
                ],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
                timeout=30,
            )
            if imported.returncode != 0:
                raise ReleaseContractError(
                    "release public signing key could not be imported"
                )
            verified = subprocess.run(
                [
                    gpg_binary,
                    "--batch",
                    "--no-tty",
                    "--homedir",
                    str(home),
                    "--status-fd",
                    "1",
                    "--verify",
                    str(signature),
                    str(attestation),
                ],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise ReleaseContractError(
                "gpg is required to verify a Production release"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ReleaseContractError("release signature verification timed out") from exc
        if verified.returncode != 0:
            raise ReleaseContractError("release detached signature is invalid")
        valid: list[set[str]] = []
        for line in verified.stdout.splitlines():
            if line.startswith("[GNUPG:] VALIDSIG "):
                fields = line.split()
                if len(fields) >= 3:
                    identities = {fields[2].upper()}
                    if FINGERPRINT.fullmatch(fields[-1].upper()):
                        identities.add(fields[-1].upper())
                    valid.append(identities)
        if len(valid) != 1 or trusted not in valid[0]:
            raise ReleaseContractError(
                "release signature does not match the independently trusted signer"
            )
        return trusted


def verify_release_package(
    package_root: Path,
    *,
    trusted_fingerprint: str = "",
    expected_images: dict[str, str] | None = None,
    expected_chart_sha256: str | None = None,
    gpg_binary: str = "gpg",
    purpose: str = "production",
) -> dict[str, Any]:
    if purpose not in {"production", "installation-validation"}:
        raise ReleaseContractError("release verification purpose is invalid")
    if package_root.is_symlink():
        raise ReleaseContractError("release package root must not be a symlink")
    root = package_root.resolve()
    if (
        not root.is_dir()
        or root.is_symlink()
        or stat.S_IMODE(root.stat().st_mode) & 0o002
    ):
        raise ReleaseContractError(
            "release package root must be a non-symlink directory not writable by others"
        )
    manifest_path = _bounded_file(root, "release-manifest.json")
    checksums_path = _bounded_file(root, "SHA256SUMS")
    manifest = _load_json(manifest_path, label="release manifest")
    signer = None
    control_files = CONTROL_FILES
    if purpose == "installation-validation":
        from .contract_v3 import INTEGRITY_CONTROL_FILES, validate_manifest as validate_v3_manifest
        validate_v3_manifest(manifest)
        if trusted_fingerprint:
            raise ReleaseContractError("signer trust configuration does not apply to this package type")
        control_files = INTEGRITY_CONTROL_FILES
    else:
        validate_manifest(manifest)
        _normalize_fingerprint(trusted_fingerprint)
        attestation_path = _bounded_file(root, "RELEASE-ATTESTATION.json")
        attestation = _load_json(attestation_path, label="release attestation")
        if set(attestation) != {"manifest_sha256", "checksums_sha256"}:
            raise ReleaseContractError("release attestation fields are invalid")
        if (
            attestation["manifest_sha256"] != sha256_file(manifest_path)
            or attestation["checksums_sha256"] != sha256_file(checksums_path)
        ):
            raise ReleaseContractError("release attestation does not match manifest/checksum inventory")
        signer = _verify_signature(
            root, trusted_fingerprint=trusted_fingerprint, gpg_binary=gpg_binary,
        )
        if signer != _normalize_fingerprint(
            str((manifest.get("signing") or {}).get("fingerprint") or "")
        ):
            raise ReleaseContractError("signed release and manifest signer identities differ")

    _verify_inventory(root, manifest, control_files=control_files)

    if purpose == "installation-validation":
        from .contract_v3 import verify_payload
        runtime_images, platform_images = verify_payload(root, manifest)
    else:
        runtime_images, platform_images = manifest["images"], manifest["platform_images"]
    if expected_images is not None and runtime_images != expected_images:
        raise ReleaseContractError("installer image configuration differs from release images")
    if (
        expected_chart_sha256 is not None
        and manifest["compatibility"]["chart_sha256"] != expected_chart_sha256
    ):
        raise ReleaseContractError("installer Helm chart differs from release compatibility identity")
    result = {
        "status": "verified",
        "release_id": manifest.get("release_id"),
        "source_sha": manifest["source"]["git_sha"],
        "manifest_sha256": sha256_file(manifest_path),
        "checksums_sha256": sha256_file(checksums_path),
        "image_digests": dict(runtime_images),
        "platform_image_digests": dict(platform_images),
        "purpose": purpose,
        "production_ready": manifest["production_ready"],
    }
    if signer is not None:
        result["signer_fingerprint"] = signer
    else:
        result["integrity"] = dict(manifest["integrity"])
    return result


def _verify_inventory(
    root: Path, manifest: dict[str, Any], *, control_files: frozenset[str],
) -> None:
    """Check bytes and closed inventory; this alone does not authenticate a publisher."""
    manifest_path = _bounded_file(root, "release-manifest.json")
    checksums_path = _bounded_file(root, "SHA256SUMS")
    expected_rows: list[str] = []
    payload_paths: set[str] = set()
    for row in manifest["files"]:
        relative = str(row["path"])
        path = _bounded_file(root, relative)
        actual = sha256_file(path)
        if actual != row["sha256"] or path.stat().st_size != row["size"]:
            raise ReleaseContractError(
                f"release payload checksum or size differs: {relative}"
            )
        payload_paths.add(relative)
        expected_rows.append(f"{actual}  {relative}")
    for name, row in manifest["gates"].items():
        evidence_path = _bounded_file(root, str(row["path"]))
        if sha256_file(evidence_path) != row["evidence_sha256"]:
            raise ReleaseContractError(
                f"release mandatory gate evidence differs: {name}"
            )
    expected_rows.append(
        f"{sha256_file(manifest_path)}  release-manifest.json"
    )
    expected_checksum_text = "\n".join(sorted(expected_rows)) + "\n"
    try:
        checksum_text = checksums_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReleaseContractError("release checksum inventory is invalid") from exc
    if checksum_text != expected_checksum_text:
        raise ReleaseContractError(
            "release checksum inventory is non-canonical or incomplete"
        )

    actual_files: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ReleaseContractError(
                f"release package contains a symlink: {path.relative_to(root)}"
            )
        if path.is_file():
            actual_files.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise ReleaseContractError("release package contains a non-regular entry")
    allowed = payload_paths | set(control_files)
    unexpected = sorted(actual_files - allowed)
    missing = sorted(allowed - actual_files)
    if unexpected or missing:
        detail = unexpected or missing
        raise ReleaseContractError(
            "release package content differs from its closed inventory: "
            + ", ".join(detail[:10])
        )
