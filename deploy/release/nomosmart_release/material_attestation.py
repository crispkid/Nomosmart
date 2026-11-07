"""Signed provenance for real public materials; never a qualified release package."""
from __future__ import annotations

import json
from pathlib import Path

from .contract import (FULL_GIT_SHA, SHA256, ReleaseContractError, _bounded_file,
                       _load_json, _normalize_fingerprint, _verify_signature,
                       canonical_json, sha256_file)
from .publication import inspect_publication_files

PURPOSE = "local-material-source-attestation"
REQUIRED_MATERIALS = frozenset({
    "runtime_inventory", "application_images", "backend_amd64_sbom", "backend_arm64_sbom",
    "frontend_amd64_sbom", "frontend_arm64_sbom", "security_review", "installation_bridge",
    "restore_proof", "quality_policy",
})


def _validate(material_root: Path, value: dict, *, trusted_fingerprint: str) -> None:
    fields = {"schema_version", "kind", "purpose", "release_qualified", "production_ready",
              "source", "trusted_fingerprint", "materials"}
    if (set(value) != fields or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1 or value.get("kind") != "nomosmart-material-source-attestation"
            or value.get("purpose") != PURPOSE or value.get("release_qualified") is not False
            or value.get("production_ready") is not False
            or value.get("trusted_fingerprint") != _normalize_fingerprint(trusted_fingerprint)):
        raise ReleaseContractError("material attestation identity or independent signer differs")
    source = value.get("source")
    if (not isinstance(source, dict) or set(source) != {"git_sha", "tree_sha256", "clean", "detached"}
            or not FULL_GIT_SHA.fullmatch(str(source.get("git_sha", "")))
            or not SHA256.fullmatch(str(source.get("tree_sha256", "")))
            or source.get("clean") is not True or source.get("detached") is not True):
        raise ReleaseContractError("material source must be clean, detached and content bound")
    rows = value.get("materials")
    if not isinstance(rows, dict) or set(rows) != REQUIRED_MATERIALS:
        raise ReleaseContractError("material attestation inventory is incomplete")
    names = set()
    for reference in rows.values():
        if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
                or not isinstance(reference["path"], str)
                or not SHA256.fullmatch(str(reference["sha256"]))
                or reference["path"] in names):
            raise ReleaseContractError("material reference is invalid or duplicate")
        path = _bounded_file(material_root, reference["path"])
        if sha256_file(path) != reference["sha256"]:
            raise ReleaseContractError("material content differs from signed provenance")
        names.add(reference["path"])
    inspect_publication_files(material_root, names)
    from .cli import PROHIBITED_CONTENT
    if any(pattern.search(_bounded_file(material_root, name).read_bytes())
           for name in names for pattern in PROHIBITED_CONTENT):
        raise ReleaseContractError("material contains prohibited credential content")


def create_material_attestation(*, material_root: Path, source_root: Path, commit: str,
                                materials: dict, output_dir: Path, public_key: Path,
                                trusted_fingerprint: str, gpg_binary: str = "gpg",
                                gpg_home: Path | None = None) -> dict:
    from .cli import _sign_attestation, source_hygiene, source_identity
    source = source_identity(source_root, commit)
    source_hygiene(source_root)
    value = {"schema_version": 1, "kind": "nomosmart-material-source-attestation",
             "purpose": PURPOSE, "release_qualified": False, "production_ready": False,
             "source": source, "trusted_fingerprint": _normalize_fingerprint(trusted_fingerprint),
             "materials": materials}
    _validate(material_root, value, trusted_fingerprint=trusted_fingerprint)
    if output_dir.exists() or output_dir.is_symlink():
        raise ReleaseContractError("material attestation output already exists")
    output_dir.mkdir(mode=0o700, parents=False)
    (output_dir / "RELEASE-ATTESTATION.json").write_bytes(canonical_json(value))
    _sign_attestation(output_dir, signing_fingerprint=trusted_fingerprint, public_key=public_key,
                      gpg_binary=gpg_binary, gpg_home=gpg_home)
    result = verify_material_attestation(material_root=material_root, attestation_dir=output_dir,
                                         trusted_fingerprint=trusted_fingerprint, gpg_binary=gpg_binary,
                                         source_root=source_root)
    if source_identity(source_root, commit) != source:
        raise ReleaseContractError("material source changed during signing")
    return result


def verify_material_attestation(*, material_root: Path, attestation_dir: Path,
                                trusted_fingerprint: str, gpg_binary: str = "gpg",
                                source_root: Path | None = None) -> dict:
    if attestation_dir.is_symlink() or not attestation_dir.is_dir():
        raise ReleaseContractError("material signature root is unsafe")
    signer = _verify_signature(attestation_dir, trusted_fingerprint=trusted_fingerprint,
                               gpg_binary=gpg_binary)
    path = _bounded_file(attestation_dir, "RELEASE-ATTESTATION.json")
    value = _load_json(path, label="material attestation")
    _validate(material_root, value, trusted_fingerprint=trusted_fingerprint)
    if source_root is not None:
        from .cli import source_identity
        if source_identity(source_root, value["source"]["git_sha"]) != value["source"]:
            raise ReleaseContractError("signed material source identity differs")
    return {"status": "verified", "purpose": PURPOSE, "release_qualified": False,
            "production_ready": False, "source": value["source"], "signer_fingerprint": signer,
            "attestation_sha256": sha256_file(path),
            "signature_sha256": sha256_file(_bounded_file(attestation_dir, "RELEASE-ATTESTATION.json.asc")),
            "material_count": len(value["materials"])}
