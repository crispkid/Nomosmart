"""Compare final public runtime to a genuine closed installation; no live claim."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from .contract import ReleaseContractError, _bounded_file, _load_json, sha256_file
from .cli import _chart_digest

CAPTURES = frozenset({"birth", "install_execution", "install_stdout", "finalize_execution",
                      "finalize_stdout", "verify_execution", "verify_stdout", "pods", "closure", "restore"})
TOOL_DELTAS = frozenset({"deploy/release/runtime-files.protocol.json", "deploy/release/nomosmart_release/quality_reports.py",
    "deploy/release/nomosmart_release/cli.py", "deploy/release/nomosmart_release/material_attestation.py",
    "deploy/release/nomosmart_release/installation_evidence.py"})


def compare_installed_payload(*, installed_package: Path, source_root: Path,
                              capture_root: Path, capture_references: dict,
                              expected_namespace_uid: str, expected_operation_uuid: str,
                              application_images: dict) -> dict:
    """Read immutable capture bytes and actual package files, never status booleans alone."""
    from .contract_test_candidate import verify_test_candidate
    verify_test_candidate(installed_package)
    manifest = _load_json(_bounded_file(installed_package, "release-manifest.json"), label="installed test candidate")
    if set(capture_references) != CAPTURES:
        raise ReleaseContractError("installation capture inventory is incomplete")
    actual = {}
    for name, ref in capture_references.items():
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise ReleaseContractError("installation capture reference is invalid")
        path = _bounded_file(capture_root, ref["path"])
        if sha256_file(path) != ref["sha256"]:
            raise ReleaseContractError("installation capture hash differs")
        actual[name] = _load_json(path, label="installation capture") if name != "pods" else json.loads(path.read_text())
    UUID(expected_namespace_uid); UUID(expected_operation_uuid)
    birth = actual["birth"]; closed = actual["closure"]
    if (birth.get("uid") != expected_namespace_uid or closed.get("namespace_UID") != expected_namespace_uid
            or birth.get("operation_uuid") != expected_operation_uuid
            or closed.get("helm_release_and_namespace_absent") is not True):
        raise ReleaseContractError("installation namespace ownership or closure differs")
    for action, code, status in [("install", 10, "action-required"), ("finalize", 0, "deployed"), ("verify", 0, "deployed")]:
        execution = actual[action + "_execution"]; out = actual[action + "_stdout"]
        if (execution.get("exit") != code or execution.get("wait_completed") is not True
                or type(execution.get("pid")) is not int or execution["pid"] <= 0
                or action not in execution.get("argv", [])
                or execution.get("stdout_sha256") != capture_references[action + "_stdout"]["sha256"]
                or out.get("status") != status or out.get("auth_contract_revision") != 2):
            raise ReleaseContractError("actual installation command/output differs")
        if action != "install" and (out.get("namespace_uid") != expected_namespace_uid
                or out.get("onboarding") != "normal_administrator_verified"
                or out.get("secret_values_read") is not False):
            raise ReleaseContractError("installation normal administrator or namespace differs")
    if (actual["restore"].get("all_rows_and_tables_equal") is not True
            or actual["restore"].get("protected_parent_unchanged") is not True
            or actual["restore"].get("write_refusal_SQLSTATE") != "25006"):
        raise ReleaseContractError("real restore preservation evidence differs")
    image_rows = manifest["images"]
    for component in ("backend", "frontend"):
        indexes = {row["index_digest"] for row in image_rows if row["component"] == component}
        if len(indexes) != 1 or not application_images.get(component, "").endswith("@" + next(iter(indexes))):
            raise ReleaseContractError("final application image differs from installed material")
        leaves = {row["manifest_digest"] for row in image_rows if row["component"] == component}
        matches = [pod for pod in actual["pods"] if "-" + component + "-" in pod.get("name", "")
                   and pod.get("ready") is True and pod.get("phase") == "Running"]
        if (len(matches) != 1 or len(matches[0].get("images", [])) != 1
                or not any(matches[0]["images"][0].endswith("@" + leaf) for leaf in leaves)):
            raise ReleaseContractError("actual installed Pod image or readiness differs")
    old_list = _load_json(_bounded_file(installed_package, manifest["runtime_files"]["path"]), label="installed runtime list")
    new_list = _load_json(_bounded_file(source_root, "deploy/release/runtime-files.protocol.json"), label="final runtime list")
    old_names = set(old_list["files"]); new_names = set(new_list["files"])
    if old_names - new_names or not (new_names - old_names) <= TOOL_DELTAS:
        raise ReleaseContractError("installed runtime file inventory differs outside release tools")
    differences = []
    for name in sorted(new_names):
        new_hash = sha256_file(_bounded_file(source_root, name))
        old_hash = sha256_file(_bounded_file(installed_package, name)) if name in old_names else None
        if new_hash != old_hash:
            if name not in TOOL_DELTAS:
                raise ReleaseContractError("installed runtime content differs outside release tools")
            differences.append({"path": name, "installed_sha256": old_hash, "final_sha256": new_hash})
    chart = _chart_digest(source_root / "deploy/helm/nomosmart")
    if chart != manifest["compatibility"]["chart_sha256"]:
        raise ReleaseContractError("final chart differs from actual installed chart")
    return {"status": "verified", "kind": "recorded-installation-source-bridge",
            "live_namespace_revalidated": False, "namespace_uid": expected_namespace_uid,
            "original_installed_at": birth["created_at"], "original_closed_at": closed["closed_at_utc"],
            "original_test_candidate_kept_unverified": True, "runtime_files_compared": len(new_names),
            "explicit_release_tool_differences": differences, "chart_sha256": chart,
            "application_images": application_images, "capture_references": capture_references,
            "new_installations": 0, "new_model_calls": 0}
