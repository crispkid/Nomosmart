"""Read the migration contract shipped inside the verified release package."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
from typing import Any
import zlib

CONTRACT_PATH = Path(__file__).with_name("release-contract.json")


def release_contract(*, contract_path: Path = CONTRACT_PATH, sql_root: Path | None = None) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if (not isinstance(contract, dict) or type(contract.get("schema_version")) is not int
            or contract["schema_version"] != 1):
        raise ValueError("invalid migration release contract schema")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(contract.get("release_version", ""))):
        raise ValueError("invalid migration release version")
    version = contract.get("required_version")
    if (not isinstance(version, str) or len(version) > 80
            or not re.fullmatch(r"[0-9]+(?:[._][0-9]+)*", version)
            or not any(int(part) for part in re.split(r"[._]", version))):
        raise ValueError("invalid migration target version")
    targets = contract.get("targets")
    if not isinstance(targets, dict) or set(targets) != {"SQL", "SQL_BASELINE"}:
        raise ValueError("invalid migration target types")
    for kind, prefix in (("SQL", "V"), ("SQL_BASELINE", "B")):
        target = targets[kind]
        if not isinstance(target, dict) or type(target.get("checksum")) is not int:
            raise ValueError("invalid migration checksum")
        if not -(2**31) <= target["checksum"] < 2**31:
            raise ValueError("migration checksum out of range")
        if not re.fullmatch(r"[0-9a-f]{64}", str(target.get("sha256", ""))):
            raise ValueError("invalid migration source hash")
        if not re.fullmatch(prefix + re.escape(contract["required_version"]) + r"__[a-z0-9_]+\.sql", str(target.get("file", ""))):
            raise ValueError("invalid migration source filename")
        if sql_root is not None:
            path = sql_root / target["file"]
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != target["sha256"]:
                raise ValueError("migration source hash differs")
            checksum = zlib.crc32("".join(path.read_text(encoding="utf-8-sig").splitlines()).encode("utf-8"))
            if (checksum if checksum < 2**31 else checksum - 2**32) != target["checksum"]:
                raise ValueError("migration Flyway checksum differs")
    return contract


def helm_values() -> dict[str, str]:
    contract = release_contract()
    return {
        "requiredVersion": contract["required_version"],
        "requiredChecksum": str(contract["targets"]["SQL"]["checksum"]),
        "baselineChecksum": str(contract["targets"]["SQL_BASELINE"]["checksum"]),
    }


def environment() -> dict[str, str]:
    values = helm_values()
    return {
        "MIGRATION_REQUIRED_VERSION": values["requiredVersion"],
        "MIGRATION_REQUIRED_CHECKSUM": values["requiredChecksum"],
        "MIGRATION_BASELINE_CHECKSUM": values["baselineChecksum"],
    }
