#!/usr/bin/env python3
"""Write static PVs from a rendered capacity plan and explicit operator placement.

This does not apply Kubernetes resources or create/change node directories.
"""
import argparse
import json
from pathlib import Path, PurePosixPath
import re


def label(value):
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", value):
        raise ValueError(f"invalid Kubernetes name: {value}")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capacity-plan", type=Path, required=True)
    parser.add_argument("--placement", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--storage-class", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    namespace, storage_class = label(args.namespace), label(args.storage_class)
    plan = json.loads(args.capacity_plan.read_text())
    placement = json.loads(args.placement.read_text())
    if plan.get("apiVersion") != "capacity.nomosmart.io/v1alpha1" or plan.get("storageMode") != "static-pv":
        raise ValueError("expected the chart's static-pv capacity plan")
    claims = {}
    for row in plan["persistentVolumeClaims"]:
        if row["count"] != len(row["claims"]) or not re.fullmatch(r"[1-9][0-9]*(?:Ki|Mi|Gi|Ti)", row["size"]):
            raise ValueError("invalid capacity-plan claim inventory")
        for claim in row["claims"]:
            if claim in claims:
                raise ValueError("duplicate claim")
            claims[label(claim)] = row["size"]
    if not claims or not isinstance(placement, dict) or set(placement) != set(claims):
        raise ValueError("placement must cover every planned claim exactly once")
    volumes, paths, names = [], set(), set()
    for claim, size in claims.items():
        row = placement[claim]
        if not isinstance(row, dict) or set(row) != {"name", "node", "path"}:
            raise ValueError("each placement requires exactly name, node, path")
        name, node = label(row["name"]), label(row["node"])
        path = PurePosixPath(row["path"])
        if not path.is_absolute() or ".." in path.parts or len(path.parts) < 4 or str(path) != row["path"]:
            raise ValueError("local path must be a normalized absolute dedicated directory")
        if name in names or (node, str(path)) in paths:
            raise ValueError("PV names and node paths must be unique")
        names.add(name)
        paths.add((node, str(path)))
        volumes.append({"apiVersion": "v1", "kind": "PersistentVolume", "metadata": {"name": name}, "spec": {
            "capacity": {"storage": size}, "volumeMode": "Filesystem", "accessModes": ["ReadWriteOnce"],
            "persistentVolumeReclaimPolicy": "Retain", "storageClassName": storage_class,
            "claimRef": {"namespace": namespace, "name": claim}, "local": {"path": str(path)},
            "nodeAffinity": {"required": {"nodeSelectorTerms": [{"matchExpressions": [{
                "key": "kubernetes.io/hostname", "operator": "In", "values": [node]}]}]}}
        }})
    # Refuse accidental replacement of an operator's existing inventory.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"apiVersion": "v1", "kind": "List", "items": volumes}, stream, indent=2)
        stream.write("\n")
    print(f"Prepared {len(volumes)} static PVs; review node paths/ownership before applying {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as exc:
        raise SystemExit(str(exc))
