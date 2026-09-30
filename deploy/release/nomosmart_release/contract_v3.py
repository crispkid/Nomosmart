"""SHA256 installation-validation releases, distinct from Production v2."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .contract import (
    CONTROL_FILES, FULL_GIT_SHA, SHA256, ReleaseContractError,
    _bounded_file, _load_json, sha256_file,
)
from .dependencies import PLATFORMS, installer_images, load_dependencies
from .publication import _relative_path, inspect_publication_files, validate_application_images


SCHEMA_VERSION = 3
PACKAGE_TYPE = "nomosmart-installation-validation-release"
PURPOSE = "installation-validation"
INTEGRITY = {"method": "sha256"}
INTEGRITY_CONTROL_FILES = frozenset({"release-manifest.json", "SHA256SUMS"})
REQUIRED_GATES = frozenset({
    "governance", "publication_boundary", "release_contract", "migration",
    "deployment", "frontend_build", "backend_build", "dependency_cve",
    "container_cve", "license_inventory", "spdx", "image_digest",
})
DEFERRED_GATES = frozenset({
    "frontend_full_suite", "backend_full_suite", "installer_full_suite", "e2e",
    "frontend_coverage", "backend_coverage", "fresh_installation", "ldap_ad_acceptance",
})
INSTALLATION_RECEIPT = {
    "status": "external_receipt",
    "reason": "Final-artifact installation results are delivered in installation-verification.json.",
}
FILE_REFERENCES = ("external_dependencies", "external_advisory", "migration_contract")


def _reference(row: Any, *, label: str) -> str:
    if (
        not isinstance(row, dict) or set(row) != {"path", "sha256"}
        or not isinstance(row["path"], str)
        or not isinstance(row["sha256"], str) or not SHA256.fullmatch(row["sha256"])
    ):
        raise ReleaseContractError(f"release file reference is invalid: {label}")
    _relative_path(row["path"])
    return row["path"]


def validate_manifest(payload: dict[str, Any]) -> None:
    expected_fields = {
        "schema_version", "package_type", "release_id", "purpose", "production_ready",
        "created_at", "source", "compatibility", "application_images", "gates",
        "deferred_validation", "files", "integrity", *FILE_REFERENCES,
    }
    if (
        set(payload) != expected_fields
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != SCHEMA_VERSION
        or payload.get("package_type") != PACKAGE_TYPE
        or payload.get("purpose") != PURPOSE
        or payload.get("production_ready") is not False
        or not isinstance(payload.get("release_id"), str)
        or not re.fullmatch(r"\d+\.\d+\.\d+", payload["release_id"])
        or not isinstance(payload.get("created_at"), str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})", payload["created_at"])
    ):
        raise ReleaseContractError("installation-validation release identity is invalid")
    source = payload["source"]
    if (
        not isinstance(source, dict)
        or set(source) != {"git_sha", "tree_sha256", "clean", "detached"}
        or not FULL_GIT_SHA.fullmatch(str(source.get("git_sha", "")))
        or not SHA256.fullmatch(str(source.get("tree_sha256", "")))
        or source.get("clean") is not True or source.get("detached") is not True
    ):
        raise ReleaseContractError("release source must be clean, detached and content-bound")
    if payload["integrity"] != INTEGRITY:
        raise ReleaseContractError("release integrity method is invalid")
    validate_application_images(payload["application_images"], version=payload["release_id"])
    compatibility = payload["compatibility"]
    if (
        not isinstance(compatibility, dict)
        or set(compatibility) != {"application", "api", "chart_version", "chart_sha256"}
        or compatibility["application"] != payload["release_id"]
        or compatibility["chart_version"] != payload["release_id"]
        or compatibility["api"] != "v1"
        or not SHA256.fullmatch(str(compatibility["chart_sha256"]))
    ):
        raise ReleaseContractError("release compatibility identity is invalid")
    files = payload["files"]
    if not isinstance(files, list) or not files:
        raise ReleaseContractError("release file inventory is empty")
    inventory = {}
    for row in files:
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "size"}:
            raise ReleaseContractError("release file inventory fields are invalid")
        path = _reference({"path": row["path"], "sha256": row["sha256"]}, label="payload")
        if path in inventory or path in CONTROL_FILES or type(row["size"]) is not int or row["size"] < 0:
            raise ReleaseContractError("release file inventory is duplicate, reserved or invalid")
        inventory[path] = row["sha256"]
    for name in FILE_REFERENCES:
        path = _reference(payload[name], label=name)
        if inventory.get(path) != payload[name]["sha256"]:
            raise ReleaseContractError(f"release reference is outside checksum inventory: {name}")
    if payload["external_dependencies"]["path"] != "deploy/release/external-dependencies.lock.json":
        raise ReleaseContractError("official dependency lock has an unexpected location")
    if payload["migration_contract"]["path"] != "deploy/migrations/release-contract.json":
        raise ReleaseContractError("migration contract has an unexpected location")
    gates = payload["gates"]
    if not isinstance(gates, dict) or set(gates) != REQUIRED_GATES:
        raise ReleaseContractError("release pre-publication gate inventory differs")
    gate_paths = set()
    for name, row in gates.items():
        if (
            not isinstance(row, dict)
            or set(row) != {"status", "source_sha", "path", "evidence_sha256"}
            or row["status"] != "passed" or row["source_sha"] != source["git_sha"]
        ):
            raise ReleaseContractError(f"pre-publication gate did not pass for this source: {name}")
        path = _reference({"path": row["path"], "sha256": row["evidence_sha256"]}, label=name)
        if path in gate_paths or inventory.get(path) != row["evidence_sha256"]:
            raise ReleaseContractError(f"pre-publication gate evidence is not uniquely inventoried: {name}")
        gate_paths.add(path)
    deferred = payload["deferred_validation"]
    if not isinstance(deferred, dict) or set(deferred) != DEFERRED_GATES or any(
        row != {"status": "deferred_by_user", "reason": "Run only after separate user authorization."}
        and not (name == "fresh_installation" and row == INSTALLATION_RECEIPT)
        for name, row in deferred.items()
    ):
        raise ReleaseContractError("deferred acceptance must remain explicit and cannot be marked passed")


def verify_payload(root: Path, payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Validate inventoried content after shared checksum verification."""
    inventory = {row["path"]: row["sha256"] for row in payload["files"]}
    inspect_publication_files(root, inventory)

    def referenced(row: dict[str, Any], label: str) -> Path:
        relative = _reference(row, label=label)
        path = _bounded_file(root, relative)
        if inventory.get(relative) != row["sha256"] or sha256_file(path) != row["sha256"]:
            raise ReleaseContractError(f"release evidence differs from its inventory: {label}")
        return path

    dependencies = load_dependencies(
        referenced(payload["external_dependencies"], "external dependencies"), version=payload["release_id"]
    )
    for name, row in payload["gates"].items():
        report = _load_json(_bounded_file(root, row["path"]), label=f"gate {name}")
        if (
            report.get("name") != name or report.get("status") != "passed"
            or report.get("source_sha") != payload["source"]["git_sha"]
            or type(report.get("exit_code")) is not int or report["exit_code"] != 0
            or not isinstance(report.get("command"), list) or not report["command"]
            or any(not isinstance(arg, str) or not arg for arg in report["command"])
            or not isinstance(report.get("artifacts"), list)
        ):
            raise ReleaseContractError(f"gate report is not a successful source-bound command: {name}")
        for artifact in report["artifacts"]:
            referenced(artifact, f"{name} artifact")
        if name in {"dependency_cve", "container_cve", "spdx", "license_inventory", "image_digest"} and not report["artifacts"]:
            raise ReleaseContractError(f"gate requires underlying evidence artifacts: {name}")

    advisory = _load_json(referenced(payload["external_advisory"], "external advisory"), label="external advisory")
    if (
        advisory.get("scope") != "official-external-dependencies"
        or advisory.get("source_sha") != payload["source"]["git_sha"]
        or advisory.get("publication_blocking") is not False
        or not isinstance(advisory.get("images"), dict)
        or set(advisory["images"]) != set(dependencies["images"])
    ):
        raise ReleaseContractError("external advisory scope or inventory differs")
    for name, dependency in dependencies["images"].items():
        row = advisory["images"][name]
        if (
            not isinstance(row, dict) or row.get("reference") != dependency["reference"]
            or not isinstance(row.get("platforms"), dict) or set(row["platforms"]) != PLATFORMS
        ):
            raise ReleaseContractError(f"external advisory image identity differs: {name}")
        for platform, digest in dependency["platforms"].items():
            scan = row["platforms"][platform]
            if (
                not isinstance(scan, dict) or scan.get("digest") != digest
                or scan.get("status") not in {"findings", "no_findings", "failed", "unknown", "not_run"}
                or not isinstance(scan.get("detail"), str) or not scan["detail"].strip()
            ):
                raise ReleaseContractError(f"external scan status is invalid: {name}/{platform}")
            if scan["status"] in {"findings", "no_findings"}:
                referenced(scan.get("report"), f"{name}/{platform} scan")
            elif scan.get("report") is not None:
                referenced(scan["report"], f"{name}/{platform} diagnostic")

    # Use this verifier's own validator, not executable code from the package
    # under inspection. Validate the package's JSON and SQL as data.
    import importlib.util
    module_path = Path(__file__).resolve().parents[2] / "migrations/nomosmart_migrations.py"
    specification = importlib.util.spec_from_file_location("nomosmart_verified_migrations", module_path)
    if specification is None or specification.loader is None:
        raise ReleaseContractError("migration contract loader is unavailable")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    try:
        migration = module.release_contract(
            contract_path=referenced(payload["migration_contract"], "migration contract"),
            sql_root=root / "sql/migrations",
        )
    except (ValueError, OSError) as exc:
        raise ReleaseContractError("release migration contract or SQL content differs") from exc
    if migration["release_version"] != payload["release_id"]:
        raise ReleaseContractError("migration and application release versions differ")
    platform_images = {
        name: dependencies["images"][name]["reference"] for name in (
            "cloudnativepg_operator", "barman_cloud_plugin", "barman_cloud_sidecar"
        )
    }
    return installer_images(payload["application_images"], dependencies), platform_images
