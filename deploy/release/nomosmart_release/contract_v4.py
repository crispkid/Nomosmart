"""Signed formal software release with explicit local-only platform qualification."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .contract import (
    CONTROL_FILES, FULL_GIT_SHA, SHA256, ReleaseContractError,
    _bounded_file, _load_json, _normalize_fingerprint, sha256_file,
)
from .contract_v3 import (
    FILE_REFERENCES, REQUIRED_GATES as V3_GATES, _reference,
    verify_payload as verify_common_payload,
)
from .publication import validate_application_images

SCHEMA_VERSION = 4
PACKAGE_TYPE = "nomosmart-local-verified-release"
PURPOSE = "local-verified-release"
REQUIRED_GATES = V3_GATES | frozenset({
    "frontend_tests", "backend_tests", "installer_tests", "release_tests", "e2e",
    "frontend_coverage", "backend_coverage", "compose", "helm", "application_static_analysis",
})
DEFERRED_PLATFORM = frozenset({
    "production_multi_host_capacity", "production_fault_domains_and_ha",
    "production_network_isolation_qualification",
})


def qualification() -> dict[str, Any]:
    return {
        "scope": "local-docker-and-docker-desktop", "software_release": "formal",
        "production_platform_qualified": False,
        "deferred_platform": {name: {"status": "deferred_by_user"} for name in sorted(DEFERRED_PLATFORM)},
        "backup_restore": {"status": "excluded_by_user"},
    }


def validate_manifest(payload: dict[str, Any]) -> None:
    expected = {
        "schema_version", "package_type", "release_id", "purpose", "production_ready",
        "created_at", "source", "compatibility", "application_images", "gates",
        "qualification", "signing", "files", *FILE_REFERENCES,
    }
    if (
        set(payload) != expected or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != SCHEMA_VERSION or payload.get("package_type") != PACKAGE_TYPE
        or payload.get("purpose") != PURPOSE or payload.get("production_ready") is not False
        or not isinstance(payload.get("release_id"), str)
        or not re.fullmatch(r"\d+\.\d+\.\d+", payload["release_id"])
        or not isinstance(payload.get("created_at"), str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})", payload["created_at"])
    ):
        raise ReleaseContractError("local verified release identity is invalid")
    source = payload["source"]
    if (
        not isinstance(source, dict) or set(source) != {"git_sha", "tree_sha256", "clean", "detached"}
        or not FULL_GIT_SHA.fullmatch(str(source.get("git_sha", "")))
        or not SHA256.fullmatch(str(source.get("tree_sha256", "")))
        or source.get("clean") is not True or source.get("detached") is not True
    ):
        raise ReleaseContractError("release source must be clean, detached and content-bound")
    if payload["qualification"] != qualification():
        raise ReleaseContractError("local release qualification, platform deferrals or backup exclusion differ")
    signing = payload["signing"]
    if not isinstance(signing, dict) or set(signing) != {"type", "fingerprint"} or signing["type"] != "openpgp-detached":
        raise ReleaseContractError("local formal release requires an independently trusted OpenPGP signer")
    _normalize_fingerprint(str(signing["fingerprint"]))
    validate_application_images(payload["application_images"], version=payload["release_id"])
    compatibility = payload["compatibility"]
    if (
        not isinstance(compatibility, dict)
        or set(compatibility) != {"application", "api", "chart_version", "chart_sha256"}
        or compatibility["application"] != payload["release_id"] or compatibility["chart_version"] != payload["release_id"]
        or compatibility["api"] != "v1" or not SHA256.fullmatch(str(compatibility["chart_sha256"]))
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
    if payload["external_dependencies"]["path"] != "deploy/release/external-dependencies.lock.json" or payload["migration_contract"]["path"] != "deploy/migrations/release-contract.json":
        raise ReleaseContractError("release contract references have unexpected locations")
    gates = payload["gates"]
    if not isinstance(gates, dict) or set(gates) != REQUIRED_GATES:
        raise ReleaseContractError("local formal release mandatory gates are incomplete")
    seen = set()
    for name, row in gates.items():
        if (
            not isinstance(row, dict) or set(row) != {"status", "source_sha", "path", "evidence_sha256"}
            or row["status"] != "passed" or row["source_sha"] != source["git_sha"]
        ):
            raise ReleaseContractError(f"mandatory gate did not pass for this source: {name}")
        path = _reference({"path": row["path"], "sha256": row["evidence_sha256"]}, label=name)
        if path in seen or inventory.get(path) != row["evidence_sha256"]:
            raise ReleaseContractError(f"gate is not uniquely inventoried: {name}")
        seen.add(path)


def _coverage_summary(root: Path, report: dict[str, Any], name: str) -> dict[str, Any]:
    reference = report.get("coverage_summary")
    path = _reference(reference, label=name + " coverage summary")
    if reference not in report["artifacts"] or sha256_file(_bounded_file(root, path)) != reference["sha256"]:
        raise ReleaseContractError("coverage summary must be an inventoried underlying tool artifact")
    return _load_json(_bounded_file(root, path), label=name + " coverage summary")


def _coverage_ratio(covered: Any, total: Any) -> float:
    if type(covered) is not int or type(total) is not int or total <= 0 or not 0 <= covered <= total:
        raise ReleaseContractError("coverage counters are empty or invalid")
    return covered / total * 100


def verify_payload(root: Path, payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    images = verify_common_payload(root, payload)
    for name in REQUIRED_GATES:
        report = _load_json(_bounded_file(root, payload["gates"][name]["path"]), label=name)
        if not report["artifacts"]:
            raise ReleaseContractError(f"mandatory gate requires underlying evidence: {name}")
        if name not in {"frontend_coverage", "backend_coverage"}:
            continue
        summary = _coverage_summary(root, report, name)
        verify_coverage_summary(name, summary)
    return images


def verify_coverage_summary(name: str, summary: dict[str, Any]) -> None:
    if name not in {"frontend_coverage", "backend_coverage"}:
        raise ReleaseContractError("coverage gate name is invalid")
    if name == "frontend_coverage":
        total = summary.get("total", {})
        for metric in ("lines", "statements", "functions", "branches"):
            row = total.get(metric, {})
            ratio = _coverage_ratio(row.get("covered"), row.get("total"))
            if ratio < 80:
                raise ReleaseContractError(f"frontend {metric} coverage is below 80 percent")
    else:
        total = summary.get("totals", {})
        covered_lines, covered_branches = total.get("covered_lines"), total.get("covered_branches")
        statements, branches = total.get("num_statements"), total.get("num_branches")
        _coverage_ratio(covered_lines, statements); _coverage_ratio(covered_branches, branches)
        if _coverage_ratio(covered_lines + covered_branches, statements + branches) < 80:
            raise ReleaseContractError("backend application/branch coverage is below 80 percent")
