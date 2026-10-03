from __future__ import annotations

import argparse
from datetime import UTC, datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Final, Sequence

from . import __version__
from .publication import inspect_publication_files, validate_application_images
from .contract import (
    ALL_RUNTIME_IMAGE_NAMES,
    FIXED_PLATFORM_IMAGES,
    FULL_GIT_SHA,
    IMAGE_DIGEST,
    MANIFEST_SCHEMA_VERSION,
    PACKAGE_TYPE,
    REQUIRED_EVIDENCE,
    REQUIRED_GATES,
    REQUIRED_IMAGES,
    ReleaseContractError,
    canonical_json,
    sha256_file,
    validate_manifest,
    verify_release_package,
)


PROHIBITED_PATHS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(^|/)\.env(?:\.|$)", re.IGNORECASE),
    re.compile(r"(^|/)kubeconfig(?:\.|$)", re.IGNORECASE),
    re.compile(r"(^|/)(?:id_rsa|id_dsa|id_ecdsa|id_ed25519)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(^|/)(?:credentials?|credential-store)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(^|/).*private[-_.]?key.*$", re.IGNORECASE),
)
PROHIBITED_CONTENT = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(rb"\bhvs\.[A-Za-z0-9_-]{16,}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
)
PACKAGE_COPY_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (".", ("README.md", "README.zh-TW.md", "LICENSE", "docker-compose.yml", "nomosmart")),
    ("backend", (".env.example",)),
    ("frontend", (".env.example",)),
    ("deploy", ("README.md",)),
    ("deploy/local", ("README.md", "README.zh-TW.md", "prepare-static-pvs.py", "prepare-helm.py", "prepare-ingress.py", "source-tunnel.example.json")),
    ("deploy/docker", (
        "15-public-api-config.sh", "16-document-upload-config.sh", "17-public-origin-config.sh",
        "nomosmart_cli.py", "nginx.conf.template",
        "nomosmart.env.example", "compose-secret-entrypoint.sh", "secret-env-entrypoint.sh",
        "postgresql-init.sh", "ssh_known_hosts.example",
    )),
    ("sql/migrations", (".",)),
    ("deploy/keycloak/themes/nomosmart", (".",)),
    ("deploy/opensearch", ("install-repository-s3.sh",)),
    ("deploy/helm", ("sync-assets.py",)),
    (
        "deploy/installer",
        (
            "nomosmart-install",
            "nomosmart-one-click",
            "nomosmart-install.example.toml",
            "nomosmart-install.openldap.example.toml",
            "nomosmart-install.external-services.example.toml",
            "nomosmart_installer",
        ),
    ),
    (
        "deploy/package",
        (
            "nomosmart-package",
            "nomosmart_package.py",
            "generate-development-tls",
        ),
    ),
    ("deploy/helm/nomosmart", (".",)),
    ("deploy/migrations", ("release-contract.json", "nomosmart_migrations.py")),
    (
        "deploy/release",
        (
            "release-manifest.schema.json",
            "release-manifest-v3.schema.json",
            "external-dependencies.lock.json",
            "nomosmart-release",
            "nomosmart_release",
        ),
    ),
)
EVIDENCE_SOURCE_PATHS: Final[dict[str, str]] = {
    "frontend_coverage": "frontend/coverage/coverage-summary.json",
    "backend_coverage": "backend/coverage.json",
}
EVIDENCE_CAPTURE_PATHS: Final[dict[str, str]] = {
    "frontend_coverage": "artifacts/coverage/frontend-coverage-summary.json",
    "backend_coverage": "artifacts/coverage/backend-coverage.json",
}


class ReleaseBuildError(RuntimeError):
    pass


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    capture: bool = True,
    timeout: int = 60,
    accepted: frozenset[int] = frozenset({0}),
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=capture,
            check=False,
            env=environment,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ReleaseBuildError(
            f"required release command is unavailable: {command[0]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ReleaseBuildError(
            f"release command timed out: {command[0]}"
        ) from exc
    if completed.returncode not in accepted:
        raise ReleaseBuildError(
            f"release command failed with protected output: {command[0]}"
        )
    return completed


def _git(repo: Path, *arguments: str) -> str:
    return _run(
        ["git", "-C", str(repo), *arguments],
        cwd=repo,
    ).stdout.strip()


def source_identity(repo: Path, commit: str) -> dict[str, Any]:
    root = repo.resolve()
    if not root.is_dir() or root.is_symlink():
        raise ReleaseBuildError("release repository must be a regular directory")
    if not FULL_GIT_SHA.fullmatch(commit):
        raise ReleaseBuildError("release commit must be a full lowercase 40-character Git SHA")
    resolved = _git(root, "rev-parse", "--verify", f"{commit}^{{commit}}")
    if resolved != commit:
        raise ReleaseBuildError("release commit does not resolve exactly")
    if _git(root, "rev-parse", "HEAD") != commit:
        raise ReleaseBuildError("release checkout HEAD differs from the requested commit")
    symbolic = _run(
        ["git", "-C", str(root), "symbolic-ref", "-q", "HEAD"],
        cwd=root,
        accepted=frozenset({0, 1}),
    )
    if symbolic.returncode == 0:
        raise ReleaseBuildError("release checkout must be detached at the exact commit")
    status = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status:
        raise ReleaseBuildError("release checkout contains tracked or untracked changes")
    tree_rows = _git(root, "ls-tree", "-r", "--full-tree", commit)
    tree_sha = hashlib.sha256((tree_rows + "\n").encode("utf-8")).hexdigest()
    return {
        "git_sha": commit,
        "tree_sha256": tree_sha,
        "clean": True,
        "detached": True,
    }


def source_hygiene(repo: Path) -> dict[str, Any]:
    tracked = [
        row
        for row in _git(repo, "ls-files", "-z").split("\0")
        if row
    ]
    publication = inspect_publication_files(repo, tracked, allow_application_wheels=True)
    rejected: list[str] = []
    scanned = 0
    for relative in tracked:
        path = repo / relative
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        lowered = relative.lower()
        if lowered.endswith((".example", ".example.toml", ".example.yaml", ".example.yml")):
            path_rejected = False
        else:
            path_rejected = any(pattern.search(relative) for pattern in PROHIBITED_PATHS)
        if path_rejected:
            rejected.append(relative)
            continue
        if path.stat().st_size > 8 * 1024 * 1024:
            continue
        content = path.read_bytes()
        scanned += 1
        if any(pattern.search(content) for pattern in PROHIBITED_CONTENT):
            rejected.append(relative)
    if rejected:
        raise ReleaseBuildError(
            "source hygiene rejected prohibited credential material: "
            + ", ".join(sorted(rejected)[:20])
        )
    return {"tracked_files": len(tracked), "content_scanned_files": scanned, "publication": publication}


def _chart_digest(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and not candidate.is_symlink()
        and not any(
            part.startswith(".")
            for part in candidate.relative_to(path).parts
        )
    )
    if not files:
        raise ReleaseBuildError("Helm chart contains no files")
    for candidate in files:
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = candidate.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _chart_version(path: Path) -> str:
    for line in (path / "Chart.yaml").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(
            r"version:\s*[\"']?([^\"'\s]+)[\"']?\s*", line
        )
        if match:
            return match.group(1)
    raise ReleaseBuildError("Helm Chart.yaml has no version")


def _safe_copy(
    source: Path, destination: Path, *, tracked_sources: frozenset[Path] | None = None,
) -> None:
    if source.is_symlink():
        raise ReleaseBuildError(f"release payload source is a symlink: {source}")
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=False)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            if child.name in {
                "__pycache__",
                ".DS_Store",
                "generated",
                "tests",
            } or child.suffix in {".pyc", ".pyo"}:
                continue
            _safe_copy(child, destination / child.name, tracked_sources=tracked_sources)
        return
    if not source.is_file():
        raise ReleaseBuildError(f"release payload source is not a file: {source}")
    if tracked_sources is not None and source not in tracked_sources:
        raise ReleaseBuildError(f"runtime payload source is untracked/ignored: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, stat.S_IMODE(source.stat().st_mode) & 0o755 or 0o644)


def _copy_runtime(repo: Path, staging: Path) -> None:
    repo = repo.resolve()
    tracked = set(_git(repo, "ls-files", "-z").split("\0"))
    tracked_sources = frozenset(repo / relative for relative in tracked if relative)
    for base_relative, entries in PACKAGE_COPY_RULES:
        base = repo / base_relative
        for entry in entries:
            source = base if entry == "." else base / entry
            destination = (
                staging / base_relative
                if entry == "."
                else staging / base_relative / entry
            )
            _safe_copy(source, destination, tracked_sources=tracked_sources)
    # A clean Git status does not include ignored files. Never trust recursive
    # directory copies to exclude local credentials, generated output or tools.
    copied = [path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file()]
    unexpected = sorted(set(copied) - tracked)
    if unexpected:
        raise ReleaseBuildError("runtime payload includes untracked/ignored files: " + ", ".join(unexpected[:10]))
    inspect_publication_files(staging, copied)


def _load_image_inventory(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseBuildError("image inventory is unavailable or invalid") from exc
    if not isinstance(payload, dict) or set(payload) != set(REQUIRED_IMAGES):
        raise ReleaseBuildError("image inventory must contain every required release image")
    images: dict[str, str] = {}
    for name, value in payload.items():
        if not isinstance(value, str) or not IMAGE_DIGEST.fullmatch(value):
            raise ReleaseBuildError(f"image is not digest pinned: {name}")
        images[name] = value
    return dict(sorted(images.items()))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(payload))
    os.chmod(path, 0o644)


def _gate_record(
    evidence_dir: Path,
    *,
    name: str,
    source_sha: str,
    commands: list[list[str]],
    repo: Path,
    timeout: int = 7200,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    started_monotonic = time.monotonic()
    for command in commands:
        _run(
            command,
            cwd=repo,
            capture=False,
            timeout=timeout,
            environment=environment,
        )
    record = {
        "schema_version": 1,
        "gate": name,
        "status": "passed",
        "source_sha": source_sha,
        "commands": commands,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(time.monotonic() - started_monotonic, 3),
    }
    path = evidence_dir / "gates" / f"{name}.json"
    _write_json(path, record)
    return {
        "status": "passed",
        "source_sha": source_sha,
        "evidence_sha256": sha256_file(path),
        "path": f"evidence/gates/{name}.json",
    }


def _generate_license_inventory(
    security_dir: Path,
    evidence_dir: Path,
    source_sha: str,
    components: Sequence[str],
) -> None:
    packages: list[dict[str, str]] = []
    for component in components:
        path = security_dir / f"{component}.spdx.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseBuildError(
                f"{component} SPDX evidence is unavailable or invalid"
            ) from exc
        if payload.get("spdxVersion") != "SPDX-2.3":
            raise ReleaseBuildError(f"{component} SBOM is not SPDX 2.3")
        rows = payload.get("packages")
        if not isinstance(rows, list) or not rows:
            raise ReleaseBuildError(f"{component} SPDX package inventory is empty")
        for row in rows:
            if not isinstance(row, dict):
                raise ReleaseBuildError(f"{component} SPDX package row is invalid")
            packages.append(
                {
                    "component": component,
                    "name": str(row.get("name") or ""),
                    "version": str(row.get("versionInfo") or ""),
                    "license": str(
                        row.get("licenseDeclared")
                        or row.get("licenseConcluded")
                        or "NOASSERTION"
                    ),
                }
            )
    _write_json(
        evidence_dir / "license-inventory.json",
        {
            "schema_version": 1,
            "source_sha": source_sha,
            "packages": sorted(
                packages,
                key=lambda row: (
                    row["component"],
                    row["name"],
                    row["version"],
                ),
            ),
        },
    )


def _bind_container_cve_evidence(
    security_dir: Path,
    evidence_dir: Path,
    source_sha: str,
    gate: dict[str, Any],
    components: Sequence[str],
) -> dict[str, Any]:
    artifacts_dir = evidence_dir / "artifacts/container-cve"
    artifacts_dir.mkdir(parents=True)
    rows: list[dict[str, str]] = []
    for component in components:
        source = security_dir / f"{component}.scout.sarif.json"
        target = artifacts_dir / source.name
        _safe_copy(source, target)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseBuildError(
                f"{component} container CVE SARIF is invalid"
            ) from exc
        if payload.get("version") != "2.1.0":
            raise ReleaseBuildError(
                f"{component} container CVE evidence is not SARIF 2.1.0"
            )
        rows.append(
            {
                "component": component,
                "path": (
                    "evidence/artifacts/container-cve/"
                    f"{source.name}"
                ),
                "sha256": sha256_file(target),
            }
        )
    inventory_path = evidence_dir / "container-cve-inventory.json"
    _write_json(
        inventory_path,
        {
            "schema_version": 1,
            "source_sha": source_sha,
            "scanner": "docker-scout",
            "policy": "zero-critical-high",
            "artifacts": rows,
        },
    )
    gate_path = evidence_dir / "gates/container_cve.json"
    gate_record = json.loads(gate_path.read_text(encoding="utf-8"))
    gate_record["container_cve_inventory_sha256"] = sha256_file(
        inventory_path
    )
    _write_json(gate_path, gate_record)
    bound = dict(gate)
    bound["evidence_sha256"] = sha256_file(gate_path)
    return bound


def _bind_spdx_evidence(
    security_dir: Path,
    evidence_dir: Path,
    source_sha: str,
    gate: dict[str, Any],
    components: Sequence[str],
) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for component in components:
        path = security_dir / f"{component}.spdx.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseBuildError(
                f"{component} SPDX evidence is unavailable or invalid"
            ) from exc
        if payload.get("spdxVersion") != "SPDX-2.3":
            raise ReleaseBuildError(f"{component} SBOM is not SPDX 2.3")
        rows.append(
            {
                "component": component,
                "image": "fixed-platform" if component in FIXED_PLATFORM_IMAGES else "release-inventory",
                "path": f"evidence/artifacts/security/{path.name}",
                "sha256": sha256_file(path),
            }
        )
    inventory_path = evidence_dir / "spdx-inventory.json"
    _write_json(
        inventory_path,
        {
            "schema_version": 1,
            "source_sha": source_sha,
            "format": "SPDX-2.3",
            "artifacts": rows,
        },
    )
    gate_path = evidence_dir / "gates/spdx.json"
    gate_record = json.loads(gate_path.read_text(encoding="utf-8"))
    gate_record["spdx_inventory_sha256"] = sha256_file(inventory_path)
    _write_json(gate_path, gate_record)
    bound = dict(gate)
    bound["evidence_sha256"] = sha256_file(gate_path)
    return bound


def _verify_built_image_identity(
    repo: Path,
    evidence_dir: Path,
    source_sha: str,
    images: dict[str, str],
) -> Path:
    rows: list[dict[str, str]] = []
    local_sources = {
        "frontend": "nomosmart-frontend:local-security",
        "backend": "nomosmart-backend:local-security",
        "migration": "nomosmart-backend:local-security",
    }
    for component, local in local_sources.items():
        approved = images[component]
        _run(
            ["docker", "pull", approved],
            cwd=repo,
            capture=False,
            timeout=1800,
        )
        local_id = _run(
            ["docker", "image", "inspect", "--format={{.Id}}", local],
            cwd=repo,
        ).stdout.strip()
        approved_id = _run(
            [
                "docker",
                "image",
                "inspect",
                "--format={{.Id}}",
                approved,
            ],
            cwd=repo,
        ).stdout.strip()
        if (
            not re.fullmatch(r"sha256:[0-9a-f]{64}", local_id)
            or local_id != approved_id
        ):
            raise ReleaseBuildError(
                f"built {component} image content differs from the approved registry digest"
            )
        rows.append(
            {
                "component": component,
                "approved_reference": approved,
                "image_config_digest": local_id,
            }
        )
    path = evidence_dir / "artifacts/image-build-identity.json"
    _write_json(
        path,
        {
            "schema_version": 1,
            "source_sha": source_sha,
            "status": "matched",
            "images": rows,
        },
    )
    return path


def run_mandatory_gates(
    repo: Path,
    source_sha: str,
    evidence_dir: Path,
    image_inventory: Path,
) -> dict[str, dict[str, Any]]:
    harness = str(repo / "HARNESS/harness.sh")
    images = _load_image_inventory(image_inventory)
    runtime_images = {**images, **FIXED_PLATFORM_IMAGES}
    if set(runtime_images) != set(ALL_RUNTIME_IMAGE_NAMES):
        raise ReleaseBuildError("internal runtime image inventory is incomplete")
    security_dir = evidence_dir / "artifacts/security"
    security_dir.mkdir(parents=True)
    container_cve_commands = [[harness, "security:images"]]
    spdx_commands: list[list[str]] = []
    for component, image in runtime_images.items():
        container_cve_commands.append(
            [
                "docker",
                "scout",
                "cves",
                "--exit-code",
                "--only-severity",
                "critical,high",
                "--format",
                "sarif",
                "--output",
                str(security_dir / f"{component}.scout.sarif.json"),
                f"registry://{image}",
            ]
        )
        spdx_commands.append(
            [
                "docker",
                "scout",
                "sbom",
                "--format",
                "spdx",
                "--output",
                str(security_dir / f"{component}.spdx.json"),
                f"registry://{image}",
            ]
        )
    commands: dict[str, list[list[str]]] = {
        "governance": [
            [harness, name]
            for name in (
                "spec:doctor",
                "spec:trace",
                "plan:doctor",
                "plan:approved",
                "test:plan",
            )
        ],
        "frontend_tests": [[harness, "test:frontend"]],
        "backend_tests": [[harness, "test:backend"]],
        "installer_tests": [[harness, "test:installer"]],
        "e2e": [[harness, "test:e2e"]],
        "dependency_cve": [[harness, "security:dependencies"]],
        "container_cve": [
            *container_cve_commands,
        ],
        "spdx": spdx_commands,
        "helm": [[harness, "helm:lint"]],
        "deployment_policy": [[harness, "deploy:config-policy"]],
    }
    gates: dict[str, dict[str, Any]] = {}
    for name in (
        "governance",
        "frontend_tests",
        "backend_tests",
        "installer_tests",
        "e2e",
    ):
        gates[name] = _gate_record(
            evidence_dir,
            name=name,
            source_sha=source_sha,
            commands=commands[name],
            repo=repo,
        )

    coverage = _gate_record(
        evidence_dir,
        name="coverage",
        source_sha=source_sha,
        commands=[[harness, "coverage:check"]],
        repo=repo,
    )
    coverage_artifacts = evidence_dir / "artifacts/coverage"
    coverage_artifacts.mkdir(parents=True)
    for name, relative in EVIDENCE_SOURCE_PATHS.items():
        _safe_copy(
            repo / relative,
            evidence_dir / EVIDENCE_CAPTURE_PATHS[name],
        )
    for name in ("frontend_coverage", "backend_coverage"):
        copied = dict(coverage)
        copied["path"] = "evidence/gates/coverage.json"
        gates[name] = copied

    for name in ("dependency_cve", "container_cve", "spdx"):
        gates[name] = _gate_record(
            evidence_dir,
            name=name,
            source_sha=source_sha,
            commands=commands[name],
            repo=repo,
        )
    gates["container_cve"] = _bind_container_cve_evidence(
        security_dir,
        evidence_dir,
        source_sha,
        gates["container_cve"],
        ALL_RUNTIME_IMAGE_NAMES,
    )
    gates["spdx"] = _bind_spdx_evidence(
        security_dir,
        evidence_dir,
        source_sha,
        gates["spdx"],
        ALL_RUNTIME_IMAGE_NAMES,
    )
    _generate_license_inventory(
        security_dir,
        evidence_dir,
        source_sha,
        ALL_RUNTIME_IMAGE_NAMES,
    )
    license_path = evidence_dir / "license-inventory.json"
    license_record = {
        "schema_version": 1,
        "gate": "license_inventory",
        "status": "passed",
        "source_sha": source_sha,
        "inventory_sha256": sha256_file(license_path),
    }
    license_gate_path = evidence_dir / "gates/license_inventory.json"
    _write_json(license_gate_path, license_record)
    gates["license_inventory"] = {
        "status": "passed",
        "source_sha": source_sha,
        "evidence_sha256": sha256_file(license_gate_path),
        "path": "evidence/gates/license_inventory.json",
    }
    for name in ("helm", "deployment_policy"):
        gates[name] = _gate_record(
            evidence_dir,
            name=name,
            source_sha=source_sha,
            commands=commands[name],
            repo=repo,
        )
    image_identity_path = _verify_built_image_identity(
        repo, evidence_dir, source_sha, images
    )
    image_record_path = evidence_dir / "gates/image_digest.json"
    _write_json(
        image_record_path,
        {
            "schema_version": 1,
            "gate": "image_digest",
            "status": "passed",
            "source_sha": source_sha,
            "inventory_sha256": sha256_file(image_inventory),
            "build_identity_sha256": sha256_file(
                image_identity_path
            ),
        },
    )
    gates["image_digest"] = {
        "status": "passed",
        "source_sha": source_sha,
        "evidence_sha256": sha256_file(image_record_path),
        "path": "evidence/gates/image_digest.json",
    }
    if set(gates) != set(REQUIRED_GATES):
        raise ReleaseBuildError("internal mandatory gate inventory is incomplete")
    return gates


def _copy_evidence(
    evidence_dir: Path,
    staging: Path,
    source_sha: str,
) -> dict[str, dict[str, str]]:
    destination = staging / "evidence"
    _safe_copy(evidence_dir / "gates", destination / "gates")
    _safe_copy(
        evidence_dir / "artifacts",
        destination / "artifacts",
    )
    evidence: dict[str, dict[str, str]] = {}
    for name, relative in EVIDENCE_CAPTURE_PATHS.items():
        source = evidence_dir / relative
        target = destination / Path(relative).name
        _safe_copy(source, target)
        evidence[name] = {
            "path": target.relative_to(staging).as_posix(),
            "sha256": sha256_file(target),
            "source_sha": source_sha,
        }
    spdx_source = evidence_dir / "spdx-inventory.json"
    spdx_target = destination / "spdx-inventory.json"
    _safe_copy(spdx_source, spdx_target)
    evidence["runtime_spdx"] = {
        "path": spdx_target.relative_to(staging).as_posix(),
        "sha256": sha256_file(spdx_target),
        "source_sha": source_sha,
    }
    license_source = evidence_dir / "license-inventory.json"
    license_target = destination / "license-inventory.json"
    _safe_copy(license_source, license_target)
    evidence["license_inventory"] = {
        "path": license_target.relative_to(staging).as_posix(),
        "sha256": sha256_file(license_target),
        "source_sha": source_sha,
    }
    container_source = evidence_dir / "container-cve-inventory.json"
    container_target = destination / "container-cve-inventory.json"
    _safe_copy(container_source, container_target)
    evidence["container_cve"] = {
        "path": container_target.relative_to(staging).as_posix(),
        "sha256": sha256_file(container_target),
        "source_sha": source_sha,
    }
    if set(evidence) != set(REQUIRED_EVIDENCE):
        raise ReleaseBuildError("internal release evidence inventory is incomplete")
    return evidence


def _payload_inventory(staging: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(staging.rglob("*")):
        if path.is_symlink():
            raise ReleaseBuildError(
                f"release package contains a symlink: {path.relative_to(staging)}"
            )
        if path.is_file() and path.name not in {
            "release-manifest.json",
            "SHA256SUMS",
            "RELEASE-ATTESTATION.json",
            "RELEASE-ATTESTATION.json.asc",
            "release-signing-key.asc",
        }:
            rows.append(
                {
                    "path": path.relative_to(staging).as_posix(),
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
    inspect_publication_files(staging, [row["path"] for row in rows])
    return rows


def _public_key_fingerprint(path: Path, *, gpg_binary: str) -> str:
    completed = _run(
        [
            gpg_binary,
            "--batch",
            "--no-tty",
            "--with-colons",
            "--show-keys",
            str(path),
        ],
        cwd=path.parent,
    )
    fingerprints = [
        row.split(":")[9].upper()
        for row in completed.stdout.splitlines()
        if row.startswith("fpr:")
    ]
    if not fingerprints:
        raise ReleaseBuildError("release public key has no fingerprint")
    return fingerprints[0]


def _sign_attestation(
    staging: Path,
    *,
    signing_fingerprint: str,
    public_key: Path,
    gpg_binary: str,
    gpg_home: Path | None,
) -> None:
    key_target = staging / "release-signing-key.asc"
    _safe_copy(public_key, key_target)
    actual = _public_key_fingerprint(key_target, gpg_binary=gpg_binary)
    if actual != signing_fingerprint.upper():
        raise ReleaseBuildError(
            "release public key differs from the selected signing fingerprint"
        )
    command = [
        gpg_binary,
        "--batch",
        "--no-tty",
    ]
    if gpg_home is not None:
        command.extend(["--homedir", str(gpg_home)])
    command.extend(
        [
            "--local-user",
            signing_fingerprint,
            "--detach-sign",
            "--armor",
            "--output",
            str(staging / "RELEASE-ATTESTATION.json.asc"),
            str(staging / "RELEASE-ATTESTATION.json"),
        ]
    )
    _run(command, cwd=staging, timeout=120)


def _deterministic_archive(root: Path, destination: Path, epoch: int) -> None:
    temporary = destination.with_suffix(destination.suffix + ".next")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            mtime=epoch,
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in [root, *sorted(root.rglob("*"))]:
                    arcname = path.relative_to(root.parent).as_posix()
                    info = archive.gettarinfo(str(path), arcname=arcname)
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = epoch
                    if path.is_file():
                        with path.open("rb") as handle:
                            archive.addfile(info, handle)
                    else:
                        archive.addfile(info)
    os.replace(temporary, destination)


def assemble_release(
    *,
    repo: Path,
    source: dict[str, Any],
    release_id: str,
    images: dict[str, str],
    gates: dict[str, dict[str, Any]],
    evidence_dir: Path,
    output_dir: Path,
    signing_fingerprint: str,
    public_key: Path,
    gpg_binary: str = "gpg",
    gpg_home: Path | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", release_id):
        raise ReleaseBuildError("release ID contains unsupported characters")
    output = output_dir.resolve()
    try:
        output.relative_to(repo.resolve())
    except ValueError:
        pass
    else:
        raise ReleaseBuildError("release output must be outside the source repository")
    output.mkdir(parents=True, exist_ok=True)
    final = output / f"nomosmart-{release_id}"
    archive = output / f"nomosmart-{release_id}.tar.gz"
    if final.exists() or archive.exists():
        raise ReleaseBuildError("release output already exists and will not be overwritten")
    with tempfile.TemporaryDirectory(
        prefix="nomosmart-release-", dir=output
    ) as temporary:
        staging = Path(temporary) / final.name
        staging.mkdir(mode=0o755)
        _copy_runtime(repo, staging)
        evidence = _copy_evidence(
            evidence_dir, staging, source["git_sha"]
        )
        files = _payload_inventory(staging)
        chart = staging / "deploy/helm/nomosmart"
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "package_type": PACKAGE_TYPE,
            "release_id": release_id,
            "production_ready": True,
            "created_at": _git(
                repo, "show", "-s", "--format=%cI", source["git_sha"]
            ),
            "source": source,
            "compatibility": {
                "application": "nomosmart-v1.0",
                "api": "v1",
                "chart_version": _chart_version(chart),
                "chart_sha256": _chart_digest(chart),
            },
            "images": dict(sorted(images.items())),
            "platform_images": dict(sorted(FIXED_PLATFORM_IMAGES.items())),
            "gates": dict(sorted(gates.items())),
            "evidence": dict(sorted(evidence.items())),
            "files": files,
            "signing": {
                "type": "openpgp-detached",
                "fingerprint": signing_fingerprint.upper(),
            },
        }
        validate_manifest(manifest)
        manifest_path = staging / "release-manifest.json"
        _write_json(manifest_path, manifest)
        checksum_rows = [
            f"{row['sha256']}  {row['path']}" for row in files
        ]
        checksum_rows.append(
            f"{sha256_file(manifest_path)}  release-manifest.json"
        )
        checksums = staging / "SHA256SUMS"
        checksums.write_text(
            "\n".join(sorted(checksum_rows)) + "\n",
            encoding="utf-8",
        )
        _write_json(
            staging / "RELEASE-ATTESTATION.json",
            {
                "manifest_sha256": sha256_file(manifest_path),
                "checksums_sha256": sha256_file(checksums),
            },
        )
        _sign_attestation(
            staging,
            signing_fingerprint=signing_fingerprint.upper(),
            public_key=public_key,
            gpg_binary=gpg_binary,
            gpg_home=gpg_home,
        )
        verify_release_package(
            staging,
            trusted_fingerprint=signing_fingerprint,
            expected_images=images,
            expected_chart_sha256=manifest["compatibility"][
                "chart_sha256"
            ],
            gpg_binary=gpg_binary,
        )
        shutil.move(str(staging), final)
    epoch = int(
        _git(repo, "show", "-s", "--format=%ct", source["git_sha"])
    )
    _deterministic_archive(final, archive, epoch)
    return {
        "status": "created",
        "release_id": release_id,
        "source_sha": source["git_sha"],
        "package_dir": str(final),
        "archive": str(archive),
        "archive_sha256": sha256_file(archive),
        "signer_fingerprint": signing_fingerprint.upper(),
        "production_ready": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nomosmart-release",
        description=(
            "Provider-neutral, manually triggered NomoSmart Production release tool"
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    source = commands.add_parser("source-check")
    source.add_argument("--repo", required=True, type=Path)
    source.add_argument("--commit", required=True)

    publication = commands.add_parser("publication-check", help="Check owned image targets and tracked source content without publishing")
    publication.add_argument("--repo", required=True, type=Path)
    publication.add_argument("--image-inventory", type=Path)
    publication.add_argument("--release-version", default=__version__)

    verify = commands.add_parser("verify-package")
    verify.add_argument("--package", required=True, type=Path)
    verify.add_argument("--trusted-fingerprint", default="", help="Required for production packages")
    verify.add_argument("--gpg-binary", default="gpg")
    verify.add_argument("--purpose", choices=("production", "installation-validation"), default="production")

    validation = commands.add_parser("assemble-validation", help="Assemble from completed source-bound reports")
    validation.add_argument("--repo", required=True, type=Path)
    validation.add_argument("--commit", required=True)
    validation.add_argument("--release-id", required=True)
    validation.add_argument("--image-inventory", required=True, type=Path)
    validation.add_argument("--evidence-dir", required=True, type=Path)
    validation.add_argument("--output-dir", required=True, type=Path)

    create = commands.add_parser("create")
    create.add_argument("--repo", required=True, type=Path)
    create.add_argument("--commit", required=True)
    create.add_argument("--release-id", required=True)
    create.add_argument("--image-inventory", required=True, type=Path)
    create.add_argument("--output-dir", required=True, type=Path)
    create.add_argument("--signing-fingerprint", required=True)
    create.add_argument("--public-key", required=True, type=Path)
    create.add_argument("--gpg-binary", default="gpg")
    create.add_argument("--gpg-home", type=Path)
    return parser


def _emit(payload: object, *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        file=stream,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "assemble-validation":
            from .validation import assemble_validation_release
            _emit(assemble_validation_release(
                repo=args.repo, commit=args.commit, release_id=args.release_id,
                image_inventory=args.image_inventory, evidence_dir=args.evidence_dir,
                output_dir=args.output_dir,
            ))
            return 0
        if args.command == "publication-check":
            hygiene = source_hygiene(args.repo.resolve())
            images = None
            if args.image_inventory is not None:
                try:
                    inventory = json.loads(args.image_inventory.read_text(encoding="utf-8"))
                except (OSError, ValueError, UnicodeError) as exc:
                    raise ReleaseBuildError("publication image inventory is unavailable or invalid") from exc
                images = validate_application_images(inventory, version=args.release_version)
            _emit({"status": "passed", "scope": "publication-boundary-only", "hygiene": hygiene,
                   "application_images": images, "image_identity_verified": False, "production_ready": False})
            return 0
        if args.command == "source-check":
            identity = source_identity(args.repo, args.commit)
            hygiene = source_hygiene(args.repo.resolve())
            _emit({"status": "passed", "source": identity, "hygiene": hygiene})
            return 0
        if args.command == "verify-package":
            _emit(
                verify_release_package(
                    args.package,
                    trusted_fingerprint=args.trusted_fingerprint,
                    gpg_binary=args.gpg_binary,
                    purpose=args.purpose,
                )
            )
            return 0
        if args.command == "create":
            repo = args.repo.resolve()
            source = source_identity(repo, args.commit)
            source_hygiene(repo)
            images = _load_image_inventory(args.image_inventory)
            with tempfile.TemporaryDirectory(
                prefix="nomosmart-release-evidence-"
            ) as temporary:
                evidence_dir = Path(temporary)
                gates = run_mandatory_gates(
                    repo,
                    source["git_sha"],
                    evidence_dir,
                    args.image_inventory,
                )
                if source_identity(repo, args.commit) != source:
                    raise ReleaseBuildError(
                        "release source identity changed while mandatory gates ran"
                    )
                source_hygiene(repo)
                _emit(
                    assemble_release(
                        repo=repo,
                        source=source,
                        release_id=args.release_id,
                        images=images,
                        gates=gates,
                        evidence_dir=evidence_dir,
                        output_dir=args.output_dir,
                        signing_fingerprint=args.signing_fingerprint,
                        public_key=args.public_key,
                        gpg_binary=args.gpg_binary,
                        gpg_home=args.gpg_home,
                    )
                )
            return 0
        raise ReleaseBuildError("unsupported release command")
    except (ReleaseBuildError, ReleaseContractError) as exc:
        _emit(
            {
                "status": "failed",
                "failure_class": type(exc).__name__,
                "detail": str(exc),
                "production_ready": False,
            },
            stream=sys.stderr,
        )
        return 1
    except Exception:
        _emit(
            {
                "status": "failed",
                "failure_class": "UnexpectedReleaseFailure",
                "detail": "release failed without exposing protected command output",
                "production_ready": False,
            },
            stream=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
