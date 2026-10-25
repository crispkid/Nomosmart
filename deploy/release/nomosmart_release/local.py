"""Assembly of the initial release from actual, source-bound verification reports."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from . import __version__
from .contract import ReleaseContractError, _bounded_file, _load_json, sha256_file, verify_release_package
from .contract_v4 import (
    qualification, PACKAGE_TYPE, PURPOSE, REQUIRED_GATES,
    SCHEMA_VERSION, _reference, validate_manifest, verify_payload,
)
from .publication import inspect_publication_files, validate_application_images


def collect_evidence(evidence_dir: Path, source_sha: str, *, coverage_acceptance: Path | None = None) -> tuple[dict[str, Any], set[str]]:
    """Read existing reports; never synthesize successful checks or coverage."""
    accepted = _acceptance_paths(evidence_dir, coverage_acceptance) if coverage_acceptance is not None else set()
    gates: dict[str, Any] = {}
    paths: set[str] = set(accepted)
    for name in sorted(REQUIRED_GATES):
        relative = f"gates/{name}.json"
        path = _bounded_file(evidence_dir, relative)
        report = _load_json(path, label=f"gate {name}")
        if (
            report.get("name") != name or report.get("source_sha") != source_sha
            or report.get("status") != ("accepted_exception" if coverage_acceptance is not None and name in {"frontend_coverage", "backend_coverage"} else "passed")
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



def _acceptance_paths(evidence_dir: Path, relative: Path) -> set[str]:
    """Collect actual receipt dependencies; do not create or alter gate outcomes."""
    paths: set[str] = set()
    def visit(reference: dict) -> Any:
        package_path = _reference(reference, label="acceptance artifact")
        if not package_path.startswith("evidence/artifacts/"):
            raise ReleaseContractError("acceptance artifacts require evidence/artifacts/")
        local = package_path.removeprefix("evidence/")
        file = _bounded_file(evidence_dir, local)
        if sha256_file(file) != reference["sha256"]:
            raise ReleaseContractError("acceptance artifact hash differs")
        paths.add(local)
        return _load_json(file, label="acceptance artifact")
    receipt_file = _bounded_file(evidence_dir, relative.as_posix())
    receipt = visit({"path": "evidence/" + relative.as_posix(), "sha256": sha256_file(receipt_file)})
    from .acceptance import INPUT_NAMES, KIND, SCHEMA_VERSION
    if receipt.get("kind") != KIND or receipt.get("schema_version") != SCHEMA_VERSION or set(receipt.get("inputs", {})) != INPUT_NAMES:
        raise ReleaseContractError("explicit coverage acceptance receipt required")
    def nested(value: Any) -> None:
        if isinstance(value, dict):
            if set(value) == {"path", "sha256"}:
                package_path = _reference(value, label="acceptance underlying evidence")
                if not package_path.startswith("evidence/artifacts/"):
                    raise ReleaseContractError("acceptance evidence path is invalid")
                local = package_path.removeprefix("evidence/")
                if sha256_file(_bounded_file(evidence_dir, local)) != value["sha256"]:
                    raise ReleaseContractError("acceptance underlying evidence hash differs")
                paths.add(local)
            else:
                for child in value.values(): nested(child)
        elif isinstance(value, list):
            for child in value: nested(child)
    for reference in receipt['inputs'].values():
        nested(visit(reference))
    return paths


def assemble_local_release(
    *, repo: Path, commit: str, release_id: str, image_inventory: Path,
    evidence_dir: Path, output_dir: Path, signing_fingerprint: str, public_key: Path,
    gpg_binary: str = "gpg", gpg_home: Path | None = None,
    coverage_acceptance: Path | None = None,
) -> dict[str, Any]:
    # Shared source/copy/archive primitives; the production builder is unchanged.
    from .cli import (
        PROHIBITED_CONTENT, ReleaseBuildError, _chart_digest, _chart_version,
        _copy_runtime, _deterministic_archive, _git, _payload_inventory, _safe_copy,
        _write_json, _sign_attestation, source_hygiene, source_identity,
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
    gates, evidence_paths = collect_evidence(evidence_dir, commit, coverage_acceptance=coverage_acceptance)
    if coverage_acceptance is None:
        schema_version, package_type, purpose = SCHEMA_VERSION, PACKAGE_TYPE, PURPOSE
        manifest_validator, payload_verifier = validate_manifest, verify_payload
    else:
        from . import contract_v5
        schema_version, package_type, purpose = contract_v5.SCHEMA_VERSION, contract_v5.PACKAGE_TYPE, contract_v5.PURPOSE
        manifest_validator, payload_verifier = contract_v5.validate_manifest, contract_v5.verify_payload
    output = output_dir.resolve()
    if output == repo or repo in output.parents:
        raise ReleaseBuildError("release output must be outside the source repository")
    output.mkdir(parents=True, exist_ok=True)
    final = output / f"nomosmart-{release_id}"
    archive = output / f"nomosmart-{release_id}.tar.gz"
    if any(path.exists() or path.is_symlink() for path in (final, archive, archive.with_suffix(archive.suffix + ".next"))):
        raise ReleaseBuildError("release output already exists and will not be overwritten")
    with tempfile.TemporaryDirectory(prefix="nomosmart-local-release-", dir=output) as temporary:
        staging = Path(temporary) / final.name
        staging.mkdir(mode=0o755)
        _copy_runtime(repo, staging)
        for relative in sorted(evidence_paths):
            path = _bounded_file(evidence_dir, relative)
            if any(pattern.search(path.read_bytes()) for pattern in PROHIBITED_CONTENT):
                raise ReleaseBuildError(f"verification evidence contains credential material: {relative}")
            _safe_copy(path, staging / "evidence" / relative)
        if coverage_acceptance is not None:
            # v5 includes the exact public application sources so the installed
            # verifier can recompute the source binding without trusting a path
            # or executable verifier supplied by an unverified package.
            receipt = _load_json(staging / "evidence" / coverage_acceptance, label="coverage acceptance")
            reference = receipt["inputs"]["source_manifest"]
            manifest_path = _bounded_file(staging, _reference(reference, label="source manifest"))
            if sha256_file(manifest_path) != reference["sha256"]:
                raise ReleaseContractError("source manifest hash differs")
            source_files = _load_json(manifest_path, label="source manifest")["files"]
            tracked = frozenset(repo / name for name in _git(repo, "ls-files", "-z").split("\0") if name)
            for name, digest in source_files.items():
                if not isinstance(name, str) or not name.startswith(("frontend/src/", "backend/app/")):
                    raise ReleaseContractError("acceptance source is outside application")
                path = _bounded_file(repo, name)
                if sha256_file(path) != digest:
                    raise ReleaseContractError("acceptance application source changed before assembly")
                _safe_copy(path, staging / name, tracked_sources=tracked)
        chart = staging / "deploy/helm/nomosmart"
        manifest = {
            "schema_version": schema_version, "package_type": package_type,
            "release_id": release_id, "purpose": purpose, "production_ready": False,
            "created_at": _git(repo, "show", "-s", "--format=%cI", commit),
            "source": source,
            "signing": {"type": "openpgp-detached", "fingerprint": signing_fingerprint.upper()},
            "qualification": qualification(),
            "compatibility": {
                "application": release_id, "api": "v1", "chart_version": _chart_version(chart),
                "chart_sha256": _chart_digest(chart),
            },
            "application_images": images, "gates": gates,
            "files": _payload_inventory(staging),
        }
        for key, relative in {
            "external_dependencies": "deploy/release/external-dependencies.lock.json",
            "migration_contract": "deploy/migrations/release-contract.json",
            "external_advisory": "evidence/external-advisory.json",
        }.items():
            manifest[key] = {"path": relative, "sha256": sha256_file(staging / relative)}
        if coverage_acceptance is not None:
            relative = "evidence/" + coverage_acceptance.as_posix()
            manifest["coverage_acceptance"] = {"path": relative, "sha256": sha256_file(staging / relative)}
        manifest_validator(manifest)
        payload_verifier(staging, manifest)  # Reject incomplete coverage before signing.
        _write_json(staging / "release-manifest.json", manifest)
        rows = [f"{row['sha256']}  {row['path']}" for row in manifest["files"]]
        rows.append(f"{sha256_file(staging / 'release-manifest.json')}  release-manifest.json")
        (staging / "SHA256SUMS").write_text("\n".join(sorted(rows)) + "\n", encoding="utf-8")
        _write_json(staging / "RELEASE-ATTESTATION.json", {
            "manifest_sha256": sha256_file(staging / "release-manifest.json"),
            "checksums_sha256": sha256_file(staging / "SHA256SUMS"),
        })
        _sign_attestation(staging, signing_fingerprint=signing_fingerprint.upper(),
            public_key=public_key, gpg_binary=gpg_binary, gpg_home=gpg_home)
        receipt = verify_release_package(staging, purpose=purpose,
            trusted_fingerprint=signing_fingerprint, gpg_binary=gpg_binary,
            expected_chart_sha256=_chart_digest(chart))
        if source_identity(repo, commit) != source:
            raise ReleaseBuildError("release source changed during assembly")
        source_hygiene(repo)
        shutil.move(str(staging), final)
    _deterministic_archive(final, archive, int(_git(repo, "show", "-s", "--format=%ct", commit)))
    return {
        **receipt, "status": "created", "package_dir": str(final), "archive": str(archive),
        "archive_sha256": sha256_file(archive),
    }
