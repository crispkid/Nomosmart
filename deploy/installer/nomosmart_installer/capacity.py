from __future__ import annotations

import base64
import json
import math
import re
from typing import Any

from .core import PreconditionError


CAPACITY_API_VERSION = "capacity.nomosmart.io/v1alpha1"
_CAPACITY_PLAN = re.compile(
    r"^\s*plan\.json:\s*[\"']?([A-Za-z0-9+/=]+)[\"']?\s*$",
    flags=re.MULTILINE,
)
_BINARY_SUFFIXES = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "Pi": 1024**5,
    "Ei": 1024**6,
}
_DECIMAL_SUFFIXES = {
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
    "P": 1000**5,
    "E": 1000**6,
}


def cpu_millis(value: Any) -> int:
    raw = str(value).strip()
    try:
        if raw.endswith("m"):
            result = int(raw[:-1])
        else:
            result = int(float(raw) * 1000)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PreconditionError(f"invalid Kubernetes CPU quantity: {raw}") from exc
    if result < 0:
        raise PreconditionError(f"negative Kubernetes CPU quantity: {raw}")
    return result


def bytes_quantity(value: Any) -> int:
    if isinstance(value, int):
        if value < 0:
            raise PreconditionError("negative Kubernetes storage quantity")
        return value
    raw = str(value).strip()
    match = re.fullmatch(r"([0-9]+)([KMGTPE]i|[KMGTPE])?", raw)
    if not match:
        raise PreconditionError(f"invalid Kubernetes byte quantity: {raw}")
    number = int(match.group(1))
    suffix = match.group(2) or ""
    return number * (_BINARY_SUFFIXES | _DECIMAL_SUFFIXES).get(suffix, 1)


def rendered_capacity_plan(rendered: str) -> dict[str, Any]:
    matches = _CAPACITY_PLAN.findall(rendered)
    if len(matches) != 1:
        raise PreconditionError("rendered Helm capacity plan is missing or ambiguous")
    try:
        payload = json.loads(base64.b64decode(matches[0], validate=True))
    except (ValueError, json.JSONDecodeError, UnicodeError) as exc:
        raise PreconditionError("rendered Helm capacity plan is invalid") from exc
    if not isinstance(payload, dict) or payload.get("apiVersion") != CAPACITY_API_VERSION:
        raise PreconditionError("rendered Helm capacity plan uses an unsupported contract")
    if not payload.get("workloads") or not isinstance(payload.get("persistentVolumeClaims"), list):
        raise PreconditionError("rendered Helm capacity plan is incomplete")
    return payload


def _resource_totals(plan: dict[str, Any]) -> dict[str, int]:
    totals = {
        "request_cpu_millis": 0,
        "request_memory_bytes": 0,
        "limit_cpu_millis": 0,
        "limit_memory_bytes": 0,
    }
    for row in plan.get("workloads") or []:
        if not isinstance(row, dict):
            raise PreconditionError("capacity workload entry is invalid")
        replicas = int(row.get("replicas") or 0)
        if replicas < 1:
            raise PreconditionError("capacity workload replica count must be positive")
        requests = row.get("requests") or {}
        limits = row.get("limits") or {}
        totals["request_cpu_millis"] += replicas * cpu_millis(requests.get("cpu", 0))
        totals["request_memory_bytes"] += replicas * bytes_quantity(requests.get("memory", 0))
        totals["limit_cpu_millis"] += replicas * cpu_millis(limits.get("cpu", 0))
        totals["limit_memory_bytes"] += replicas * bytes_quantity(limits.get("memory", 0))
    return totals


def _pvc_totals(plan: dict[str, Any]) -> dict[str, int]:
    logical = 0
    count = 0
    for row in plan.get("persistentVolumeClaims") or []:
        if not isinstance(row, dict):
            raise PreconditionError("capacity PVC entry is invalid")
        copies = int(row.get("count") or 0)
        if copies < 1:
            raise PreconditionError("capacity PVC count must be positive")
        logical += copies * bytes_quantity(row.get("size", 0))
        count += copies
    return {"pvc_count": count, "logical_bytes": logical}



def _effective_pod_resources(pod: dict[str, Any]) -> dict[str, int]:
    spec = pod.get("spec") or {}
    total = {
        "request_cpu_millis": 0,
        "request_memory_bytes": 0,
        "limit_cpu_millis": 0,
        "limit_memory_bytes": 0,
    }
    for container in spec.get("containers") or []:
        resources = container.get("resources") or {}
        requests = resources.get("requests") or {}
        limits = resources.get("limits") or {}
        total["request_cpu_millis"] += cpu_millis(requests.get("cpu", 0))
        total["request_memory_bytes"] += bytes_quantity(requests.get("memory", 0))
        total["limit_cpu_millis"] += cpu_millis(limits.get("cpu", 0))
        total["limit_memory_bytes"] += bytes_quantity(limits.get("memory", 0))
    init_max = {key: 0 for key in total}
    for container in spec.get("initContainers") or []:
        resources = container.get("resources") or {}
        requests = resources.get("requests") or {}
        limits = resources.get("limits") or {}
        current = {
            "request_cpu_millis": cpu_millis(requests.get("cpu", 0)),
            "request_memory_bytes": bytes_quantity(requests.get("memory", 0)),
            "limit_cpu_millis": cpu_millis(limits.get("cpu", 0)),
            "limit_memory_bytes": bytes_quantity(limits.get("memory", 0)),
        }
        for key, value in current.items():
            init_max[key] = max(init_max[key], value)
    overhead = spec.get("overhead") or {}
    total["request_cpu_millis"] = max(total["request_cpu_millis"], init_max["request_cpu_millis"]) + cpu_millis(overhead.get("cpu", 0))
    total["request_memory_bytes"] = max(total["request_memory_bytes"], init_max["request_memory_bytes"]) + bytes_quantity(overhead.get("memory", 0))
    total["limit_cpu_millis"] = max(total["limit_cpu_millis"], init_max["limit_cpu_millis"])
    total["limit_memory_bytes"] = max(total["limit_memory_bytes"], init_max["limit_memory_bytes"])
    return total


def _condition_true(conditions: Any, condition_type: str) -> bool:
    if isinstance(conditions, dict):
        candidate = conditions.get(condition_type) or {}
        return str(candidate.get("status") or "").lower() == "true"
    return any(
        isinstance(row, dict)
        and row.get("type") == condition_type
        and str(row.get("status") or "").lower() == "true"
        for row in (conditions or [])
    )


def _static_storage(kube: Any, plan: dict[str, Any], ready_nodes: list[str]) -> dict[str, Any]:
    path = kube.config.application.static_pv_manifest_file
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError) as exc:
        raise PreconditionError("static PV manifest must be a readable Kubernetes JSON List") from exc
    if not isinstance(manifest, dict) or manifest.get("kind") != "List" or manifest.get("apiVersion") != "v1":
        raise PreconditionError("static PV manifest must have apiVersion=v1 and kind=List")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise PreconditionError("static PV manifest has no PV items")
    wanted: dict[str, int] = {}
    for row in plan["persistentVolumeClaims"]:
        names = row.get("claims")
        if not isinstance(names, list) or len(names) != int(row["count"]):
            raise PreconditionError("static PV plan must identify every expected claim")
        for name in names:
            if name in wanted:
                raise PreconditionError("capacity plan repeats a PVC name")
            wanted[name] = bytes_quantity(row["size"])
    expected: dict[str, dict[str, Any]] = {}
    for pv in items:
        if not isinstance(pv, dict) or pv.get("kind") != "PersistentVolume" or pv.get("apiVersion") != "v1":
            raise PreconditionError("static PV manifest may contain only PersistentVolumes")
        spec = pv.get("spec") or {}
        name = (pv.get("metadata") or {}).get("name")
        claim = spec.get("claimRef") or {}
        claim_name = claim.get("name")
        if not name or name in expected or claim_name not in wanted or claim.get("namespace") != kube.config.target.namespace:
            raise PreconditionError("static PV name/claimRef does not match the installation")
        if spec.get("storageClassName") != kube.config.application.storage_class:
            raise PreconditionError(f"PV/{name} has a different StorageClass")
        if spec.get("persistentVolumeReclaimPolicy") != "Retain" or spec.get("volumeMode", "Filesystem") != "Filesystem":
            raise PreconditionError(f"PV/{name} requires Retain and Filesystem")
        if spec.get("accessModes") != ["ReadWriteOnce"] or bytes_quantity((spec.get("capacity") or {}).get("storage", 0)) < wanted[claim_name]:
            raise PreconditionError(f"PV/{name} accessModes/capacity do not satisfy the claim")
        local = spec.get("local") or {}
        data_path = local.get("path", "")
        terms = (((spec.get("nodeAffinity") or {}).get("required") or {}).get("nodeSelectorTerms") or [])
        if local:
            if not isinstance(data_path, str) or not data_path.startswith("/") or data_path == "/" or ".." in data_path.split("/"):
                raise PreconditionError(f"PV/{name} requires an absolute local data path")
            if len(terms) != 1:
                raise PreconditionError(f"local PV/{name} requires one explicit node affinity term")
            expressions = terms[0].get("matchExpressions") or []
            if len(expressions) != 1 or expressions[0].get("key") != "kubernetes.io/hostname" or expressions[0].get("operator") != "In":
                raise PreconditionError(f"local PV/{name} must bind an explicit hostname")
            nodes = expressions[0].get("values") or []
            if len(nodes) != 1 or nodes[0] not in ready_nodes:
                raise PreconditionError(f"local PV/{name} targets an unavailable node")
        actual = kube.json("get", "pv", name)
        live = actual.get("spec") or {}
        for field in ("storageClassName", "accessModes", "capacity", "persistentVolumeReclaimPolicy", "local", "csi", "nodeAffinity"):
            if live.get(field) != spec.get(field):
                raise PreconditionError(f"live PV/{name} differs from the approved manifest: {field}")
        live_claim = live.get("claimRef") or {}
        if live_claim.get("name") != claim_name or live_claim.get("namespace") != claim["namespace"]:
            raise PreconditionError(f"PV/{name} belongs to another claim")
        if live.get("volumeMode", "Filesystem") != "Filesystem":
            raise PreconditionError(f"PV/{name} has an incompatible volumeMode")
        phase = (actual.get("status") or {}).get("phase")
        if phase not in {"Available", "Bound"}:
            raise PreconditionError(f"PV/{name} is not Available or Bound")
        if phase == "Bound":
            current = kube.json("get", "pvc", claim_name, namespace=True)
            if (current.get("spec") or {}).get("volumeName") != name or live_claim.get("uid") != (current.get("metadata") or {}).get("uid"):
                raise PreconditionError(f"PV/{name} is bound to a different PVC identity")
        expected[name] = {"claim": claim_name, "capacity_bytes": bytes_quantity(spec["capacity"]["storage"]), "phase": phase,
                          "local_node": expressions[0]["values"][0] if local else None}
    if len(expected) != len(wanted) or {v["claim"] for v in expected.values()} != set(wanted):
        raise PreconditionError("static PV manifest must cover each planned PVC exactly once")
    return {"mode": "static-pv", "volumes": expected}


def validate_live_capacity(kube: Any, plan: dict[str, Any], ready_nodes: list[str]) -> dict[str, Any]:
    local = kube.config.local_installation
    if len(ready_nodes) < (1 if local else 3):
        raise PreconditionError("capacity plan has insufficient Ready schedulable nodes")
    minimum = plan.get("minimumNodeAllocatable") or {}
    planned = _resource_totals(plan)
    pvc = _pvc_totals(plan)
    reserve = plan.get("reservePercent") or {}
    required_cpu = math.ceil(planned["request_cpu_millis"] * (100 + int(reserve.get("cpu") or 0)) / 100)
    required_memory = math.ceil(planned["request_memory_bytes"] * (100 + int(reserve.get("memory") or 0)) / 100)
    required_storage = math.ceil(pvc["logical_bytes"] * (100 + int(reserve.get("storage") or 0)) / 100)
    nodes = {row["metadata"]["name"]: row for row in kube.json("get", "nodes").get("items") or []}
    evidence: dict[str, dict[str, int]] = {}
    for name in ready_nodes:
        allocatable = (nodes[name].get("status") or {}).get("allocatable") or {}
        cpu = cpu_millis(allocatable.get("cpu", 0))
        memory = bytes_quantity(allocatable.get("memory", 0))
        if cpu < cpu_millis(minimum.get("cpu", 0)) or memory < bytes_quantity(minimum.get("memory", 0)):
            raise PreconditionError(f"node/{name} allocatable is below the profile minimum")
        evidence[name] = {"allocatable_cpu_millis": cpu, "allocatable_memory_bytes": memory,
                          "outside_request_cpu_millis": 0, "outside_request_memory_bytes": 0,
                          "outside_limit_cpu_millis": 0, "outside_limit_memory_bytes": 0}
    for pod in kube.json("get", "pods", "--all-namespaces").get("items") or []:
        name = (pod.get("spec") or {}).get("nodeName")
        if name not in evidence or (pod.get("metadata") or {}).get("namespace") == kube.config.target.namespace or (pod.get("status") or {}).get("phase") in {"Succeeded", "Failed"}:
            continue
        for key, value in _effective_pod_resources(pod).items():
            evidence[name][f"outside_{key}"] += value
    total_cpu = sum(v["allocatable_cpu_millis"] for v in evidence.values())
    total_memory = sum(v["allocatable_memory_bytes"] for v in evidence.values())
    host: dict[str, int] = {}
    if local:
        try:
            info = json.loads(kube.runner.run(["docker", "info", "--format", "{{json .}}"], timeout=30).stdout)
            host = {"cpu_millis": int(info["NCPU"]) * 1000, "memory_bytes": int(info["MemTotal"])}
        except (ValueError, KeyError, TypeError) as exc:
            raise PreconditionError("Docker Desktop VM capacity is unavailable") from exc
        total_cpu = min(total_cpu, host["cpu_millis"])
        total_memory = min(total_memory, host["memory_bytes"])
    outside_cpu = sum(v["outside_request_cpu_millis"] for v in evidence.values())
    outside_memory = sum(v["outside_request_memory_bytes"] for v in evidence.values())
    if total_cpu - outside_cpu < required_cpu or total_memory - outside_memory < required_memory:
        raise PreconditionError("prospective CPU/memory capacity is insufficient (shared VM counted once)")
    for name, row in evidence.items():
        row["prospective_request_cpu_headroom_millis"] = row["allocatable_cpu_millis"] - row["outside_request_cpu_millis"]
        row["prospective_request_memory_headroom_bytes"] = row["allocatable_memory_bytes"] - row["outside_request_memory_bytes"]
        if not local and (row["prospective_request_cpu_headroom_millis"] < math.ceil(required_cpu/len(ready_nodes)) or row["prospective_request_memory_headroom_bytes"] < math.ceil(required_memory/len(ready_nodes))):
            raise PreconditionError(f"node/{name} has insufficient prospective request headroom")
    mode = kube.config.application.storage_mode
    if mode == "external":
        if pvc["pvc_count"]:
            raise PreconditionError("external storage profile unexpectedly renders PVCs")
        storage: dict[str, Any] = {"mode": "external", "status": "not-managed"}
    else:
        storage_class = kube.json("get", "storageclass", kube.config.application.storage_class)
        provisioner = storage_class.get("provisioner")
        if mode == "static-pv":
            if provisioner != "kubernetes.io/no-provisioner":
                raise PreconditionError("static-pv requires a no-provisioner StorageClass")
            storage = _static_storage(kube, plan, ready_nodes)
            local_nodes = {row["local_node"] for row in storage["volumes"].values() if row["local_node"]}
            filesystems = {}
            for name in sorted(local_nodes):
                summary = kube.json("get", "--raw", f"/api/v1/nodes/{name}/proxy/stats/summary")
                available = int(((summary.get("node") or {}).get("fs") or {}).get("availableBytes") or 0)
                filesystems[name] = available
            if filesystems:
                # Docker Desktop kind nodes share one VM disk; never sum it three times.
                available = min(filesystems.values()) if local else sum(filesystems.values())
                if available < required_storage:
                    raise PreconditionError("local PV filesystem has insufficient available capacity")
                storage["filesystem_available_bytes"] = available
                storage["node_filesystems"] = filesystems
        else:
            capacities = kube.json("get", "csistoragecapacities.storage.k8s.io", "--all-namespaces").get("items") or []
            pools = [bytes_quantity(row.get("capacity", 0)) for row in capacities if row.get("storageClassName") == kube.config.application.storage_class]
            if not pools or max(pools) < required_storage:
                raise PreconditionError("dynamic storage lacks sufficient CSIStorageCapacity evidence; configure static-pv or provide capacity reporting")
            storage = {"mode": "dynamic", "reported_pool_bytes": max(pools)}
        storage["storage_class"] = kube.config.application.storage_class
        storage["provisioner"] = provisioner
    return {"status": "ready", "node_count": len(ready_nodes), "platform_profile": kube.config.application.platform_profile,
            "planned_resources": planned, "planned_storage": pvc, "reserve_percent": reserve,
            "required_with_reserve": {"cpu_millis": required_cpu, "memory_bytes": required_memory, "storage_bytes": required_storage},
            "nodes": evidence, "shared_vm_capacity": host, "storage": storage}
