"""Assembly of the initial release from actual, source-bound verification reports."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from . import __version__
from .contract import ReleaseContractError, _bounded_file, _load_json, sha256_file, verify_release_package
from .contract_v3 import (
    DEFERRED_GATES, INTEGRITY, INSTALLATION_RECEIPT, PACKAGE_TYPE, PURPOSE, REQUIRED_GATES,
    SCHEMA_VERSION, _reference, validate_manifest,
)
from .publication import inspect_publication_files, validate_application_images


def collect_evidence(evidence_dir: Path, source_sha: str) -> tuple[dict[str, Any], set[str]]:
    """Read existing reports; never synthesize successful checks or coverage."""
    gates: dict[str, Any] = {}
    paths: set[str] = set()
    for name in sorted(REQUIRED_GATES):
        relative = f"gates/{name}.json"
        path = _bounded_file(evidence_dir, relative)
        report = _load_json(path, label=f"gate {name}")
        if (
            report.get("name") != name or report.get("source_sha") != source_sha
            or report.get("status") != "passed"
            or type(report.get("exit_code")) is not int or report["exit_code"] != 0
            or not isinstance(report.get("command"), list) or not report["command"]
            or any(not isinstance(arg, str) or not arg for arg in report["command"])
            or not isinstance(report.get("artifacts"), list)
        ):
            raise ReleaseContractError(f"actual source-bound successful evidence required: {name}")
        gates[name] = {
            "status": report["status"], "source_sha": source_sha,
            "path": f"evidence/{relative}", "evidence_sha256": sha256_file(path),
        }
        paths.add(relative)
        for artifact in report["artifacts"]:
            relative_artifact = _reference(artifact, label=f"{name} artifact")
            if not relative_artifact.startswith("evidence/artifacts/"):
                raise ReleaseContractError("verification artifacts must be under evidence/artifacts/")
            local = relative_artifact.removeprefix("evidence/")
            if sha256_file(_bounded_file(evidence_dir, local)) != artifact["sha256"]:
                raise ReleaseContractError(f"verification artifact hash differs: {name}")
            paths.add(local)
    advisory_path = _bounded_file(evidence_dir, "external-advisory.json")
    advisory = _load_json(advisory_path, label="external advisory")
    if (
        advisory.get("source_sha") != source_sha
        or advisory.get("scope") != "official-external-dependencies"
        or advisory.get("publication_blocking") is not False
        or not isinstance(advisory.get("images"), dict)
    ):
        raise ReleaseContractError("actual source-bound external advisory required")
    paths.add("external-advisory.json")
    for row in advisory["images"].values():
        if not isinstance(row, dict) or not isinstance(row.get("platforms"), dict):
            raise ReleaseContractError("external advisory platforms are invalid")
        for scan in row["platforms"].values():
            if not isinstance(scan, dict):
                raise ReleaseContractError("external advisory scan is invalid")
            if scan.get("report") is not None:
                report = scan["report"]
                relative = _reference(report, label="external scan")
                if not relative.startswith("evidence/artifacts/"):
                    raise ReleaseContractError("external scan reports must be under evidence/artifacts/")
                local = relative.removeprefix("evidence/")
                if sha256_file(_bounded_file(evidence_dir, local)) != report["sha256"]:
                    raise ReleaseContractError("external scan report hash differs")
                paths.add(local)
    inspect_publication_files(evidence_dir, paths)
    return gates, paths


def assemble_validation_release(
    *, repo: Path, commit: str, release_id: str, image_inventory: Path,
    evidence_dir: Path, output_dir: Path,
) -> dict[str, Any]:
    # Shared source/copy/archive primitives; the production builder is unchanged.
    from .cli import (
        PROHIBITED_CONTENT, ReleaseBuildError, _chart_digest, _chart_version,
        _copy_runtime, _deterministic_archive, _git, _payload_inventory, _safe_copy,
        _write_json, source_hygiene, source_identity,
    )

    if release_id != __version__ or not re.fullmatch(r"\d+\.\d+\.\d+", release_id):
        raise ReleaseBuildError("release ID must match this release tool's version")
    repo = repo.resolve()
    source = source_identity(repo, commit)
    source_hygiene(repo)
    images = validate_application_images(
        _load_json(image_inventory, label="application images"), version=release_id,
    )
    if evidence_dir.is_symlink() or not evidence_dir.is_dir():
        raise ReleaseBuildError("evidence directory must be a regular directory")
    evidence_dir = evidence_dir.resolve()
    gates, evidence_paths = collect_evidence(evidence_dir, commit)
    output = output_dir.resolve()
    if output == repo or repo in output.parents:
        raise ReleaseBuildError("release output must be outside the source repository")
    output.mkdir(parents=True, exist_ok=True)
    final = output / f"nomosmart-{release_id}"
    archive = output / f"nomosmart-{release_id}.tar.gz"
    if any(path.exists() or path.is_symlink() for path in (final, archive, archive.with_suffix(archive.suffix + ".next"))):
        raise ReleaseBuildError("release output already exists and will not be overwritten")
    with tempfile.TemporaryDirectory(prefix="nomosmart-validation-", dir=output) as temporary:
        staging = Path(temporary) / final.name
        staging.mkdir(mode=0o755)
        _copy_runtime(repo, staging)
        for relative in sorted(evidence_paths):
            path = _bounded_file(evidence_dir, relative)
            if any(pattern.search(path.read_bytes()) for pattern in PROHIBITED_CONTENT):
                raise ReleaseBuildError(f"verification evidence contains credential material: {relative}")
            _safe_copy(path, staging / "evidence" / relative)
        chart = staging / "deploy/helm/nomosmart"
        manifest = {
            "schema_version": SCHEMA_VERSION, "package_type": PACKAGE_TYPE,
            "release_id": release_id, "purpose": PURPOSE, "production_ready": False,
            "created_at": _git(repo, "show", "-s", "--format=%cI", commit),
            "source": source, "integrity": dict(INTEGRITY),
            "compatibility": {
                "application": release_id, "api": "v1", "chart_version": _chart_version(chart),
                "chart_sha256": _chart_digest(chart),
            },
            "application_images": images, "gates": gates,
            "deferred_validation": {
                name: dict(INSTALLATION_RECEIPT) if name == "fresh_installation" else
                {"status": "deferred_by_user", "reason": "Run only after separate user authorization."}
                for name in sorted(DEFERRED_GATES)
            },
            "files": _payload_inventory(staging),
        }
        for key, relative in {
            "external_dependencies": "deploy/release/external-dependencies.lock.json",
            "migration_contract": "deploy/migrations/release-contract.json",
            "external_advisory": "evidence/external-advisory.json",
        }.items():
            manifest[key] = {"path": relative, "sha256": sha256_file(staging / relative)}
        validate_manifest(manifest)
        _write_json(staging / "release-manifest.json", manifest)
        rows = [f"{row['sha256']}  {row['path']}" for row in manifest["files"]]
        rows.append(f"{sha256_file(staging / 'release-manifest.json')}  release-manifest.json")
        (staging / "SHA256SUMS").write_text("\n".join(sorted(rows)) + "\n", encoding="utf-8")
        receipt = verify_release_package(staging, purpose=PURPOSE, expected_chart_sha256=_chart_digest(chart))
        if source_identity(repo, commit) != source:
            raise ReleaseBuildError("release source changed during assembly")
        source_hygiene(repo)
        shutil.move(str(staging), final)
    _deterministic_archive(final, archive, int(_git(repo, "show", "-s", "--format=%ct", commit)))
    return {
        **receipt, "status": "created", "package_dir": str(final), "archive": str(archive),
        "archive_sha256": sha256_file(archive),
    }
