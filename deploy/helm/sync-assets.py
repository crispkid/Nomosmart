#!/usr/bin/env python3
"""Check or mechanically synchronize chart-owned SQL/theme source copies."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy/helm/nomosmart"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Update chart copies from canonical project sources")
    args = parser.parse_args()
    sources = {
        "sql": ROOT / "sql/migrations",
        "theme": ROOT / "deploy/keycloak/themes/nomosmart",
    }
    inventory = {}
    for group, source in sources.items():
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"source symlink is not allowed: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            if group == "sql" and path.suffix != ".sql":
                raise ValueError(f"unexpected migration source: {relative}")
            target = CHART / "files" / group / relative
            for parent in (target, *target.parents):
                if parent.is_symlink():
                    raise ValueError(f"chart symlink is not allowed: {parent}")
                if parent == CHART:
                    break
            content = path.read_bytes()
            content.decode("utf-8")
            if args.write:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            if not target.is_file() or target.read_bytes() != content:
                raise ValueError(f"chart source copy differs; run sync-assets.py --write: {target}")
            inventory[target.relative_to(CHART).as_posix()] = hashlib.sha256(content).hexdigest()
        actual = {path.relative_to(CHART).as_posix() for path in (CHART / "files" / group).rglob("*") if path.is_file()}
        if actual != {name for name in inventory if name.startswith(f"files/{group}/")}:
            raise ValueError(f"chart contains an unexpected {group} file; review explicitly")
    # One ConfigMap per source file bounds objects well below Kubernetes' 1MiB
    # limit, while the projected volume preserves all original SQL filenames.
    for relative in inventory:
        encoded = json.dumps({"data": {Path(relative).name: (CHART / relative).read_text()}}).encode()
        if len(encoded) > 512 * 1024:
            raise ValueError(f"chart source exceeds conservative ConfigMap bound: {relative}")
    script = ROOT / "deploy/opensearch/install-repository-s3.sh"
    target = CHART / "files/install-repository-s3.sh"
    if script.is_symlink() or target.is_symlink():
        raise ValueError("plugin initialization source must not be a symlink")
    if args.write:
        target.write_bytes(script.read_bytes())
    if not target.is_file() or target.read_bytes() != script.read_bytes():
        raise ValueError("chart plugin initialization script differs")
    inventory[target.relative_to(CHART).as_posix()] = hashlib.sha256(script.read_bytes()).hexdigest()
    print(json.dumps({"status": "passed", "files": len(inventory), "sha256": inventory}, sort_keys=True))


if __name__ == "__main__":
    main()
