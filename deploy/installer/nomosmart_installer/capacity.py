from __future__ import annotations

import base64
import json
import math
import re
from typing import Any

from .core import PreconditionError


CAPACITY_API_VERSION = "capacity.nomosmart.io/v1alpha1"
OPENLDAP_LONGHORN_VOLUME = "pvc-aceaa515-e901-4771-bdb5-687d79d71aec"
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
    if not payload.get("workloads") or not payload.get("persistentVolumeClaims"):
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
    replication = int(((plan.get("longhorn") or {}).get("requiredReplicaCount")) or 0)
    if replication != 1:
        raise PreconditionError("CHG-252 Longhorn physical replication must be exactly one")
    return {
        "pvc_count": count,
        "logical_bytes": logical,
        "physical_bytes": logical * replication,
        "longhorn_replica_count": replication,
    }


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


def _longhorn_reclaimable(kube: Any, namespace: str, longhorn_namespace: str) -> tuple[dict[str, int], list[str]]:
    if not kube.exists("namespace", namespace, namespace=False):
        return {}, []
    claims = kube.json("get", "persistentvolumeclaims", namespace=True).get("items") or []
    volumes_by_pv = {
        str((row.get("metadata") or {}).get("name") or ""): row
        for row in (kube.json("get", "persistentvolumes").get("items") or [])
    }
    handles: set[str] = set()
    for claim in claims:
        pv_name = str((claim.get("spec") or {}).get("volumeName") or "")
        csi = ((volumes_by_pv.get(pv_name, {}).get("spec") or {}).get("csi") or {})
        if csi.get("driver") == "driver.longhorn.io":
            handle = str(csi.get("volumeHandle") or "")
            if handle:
                handles.add(handle)
    if OPENLDAP_LONGHORN_VOLUME in handles:
        raise PreconditionError("protected OpenLDAP Longhorn volume resolved inside NomoSmart capacity inventory")
    longhorn_volumes = {
        str((row.get("metadata") or {}).get("name") or ""): row
        for row in (
            kube.json("get", "volumes.longhorn.io", namespace=longhorn_namespace).get("items") or []
        )
    }
    actual_by_volume = {
        name: bytes_quantity((longhorn_volumes.get(name, {}).get("status") or {}).get("actualSize") or 0)
        for name in handles
        if name in longhorn_volumes
    }
    reclaim_by_node: dict[str, int] = {}
    replicas = kube.json(
        "get", "replicas.longhorn.io", namespace=longhorn_namespace
    ).get("items") or []
    for replica in replicas:
        spec = replica.get("spec") or {}
        volume_name = str(spec.get("volumeName") or "")
        node_name = str(spec.get("nodeID") or "")
        if volume_name in actual_by_volume and node_name:
            reclaim_by_node[node_name] = (
                reclaim_by_node.get(node_name, 0) + actual_by_volume[volume_name]
            )
    return reclaim_by_node, sorted(handles)


def validate_live_capacity(kube: Any, plan: dict[str, Any], ready_nodes: list[str]) -> dict[str, Any]:
    if len(ready_nodes) != 3:
        raise PreconditionError("CHG-252 capacity requires exactly three Ready schedulable nodes")
    minimum = plan.get("minimumNodeAllocatable") or {}
    minimum_cpu = cpu_millis(minimum.get("cpu", 0))
    minimum_memory = bytes_quantity(minimum.get("memory", 0))
    planned = _resource_totals(plan)
    pvc = _pvc_totals(plan)
    reserve = plan.get("reservePercent") or {}
    required_cpu = math.ceil(planned["request_cpu_millis"] * (100 + int(reserve.get("cpu") or 0)) / 100)
    required_memory = math.ceil(planned["request_memory_bytes"] * (100 + int(reserve.get("memory") or 0)) / 100)

    nodes = {
        str((row.get("metadata") or {}).get("name") or ""): row
        for row in (kube.json("get", "nodes").get("items") or [])
    }
    node_evidence: dict[str, dict[str, int]] = {}
    for name in ready_nodes:
        allocatable = (nodes.get(name, {}).get("status") or {}).get("allocatable") or {}
        cpu = cpu_millis(allocatable.get("cpu", 0))
        memory = bytes_quantity(allocatable.get("memory", 0))
        if cpu < minimum_cpu or memory < minimum_memory:
            raise PreconditionError(f"node/{name} allocatable capacity is below the CHG-252 minimum")
        node_evidence[name] = {
            "allocatable_cpu_millis": cpu,
            "allocatable_memory_bytes": memory,
            "outside_request_cpu_millis": 0,
            "outside_request_memory_bytes": 0,
            "outside_limit_cpu_millis": 0,
            "outside_limit_memory_bytes": 0,
        }
    pods = kube.json("get", "pods", "--all-namespaces").get("items") or []
    for pod in pods:
        metadata = pod.get("metadata") or {}
        spec = pod.get("spec") or {}
        status = pod.get("status") or {}
        node_name = str(spec.get("nodeName") or "")
        if (
            node_name not in node_evidence
            or metadata.get("namespace") == kube.config.target.namespace
            or status.get("phase") in {"Succeeded", "Failed"}
        ):
            continue
        used = _effective_pod_resources(pod)
        for key, value in used.items():
            node_evidence[node_name][f"outside_{key}"] = value
    per_node_cpu = math.ceil(required_cpu / len(ready_nodes))
    per_node_memory = math.ceil(required_memory / len(ready_nodes))
    for name, row in node_evidence.items():
        row["prospective_request_cpu_headroom_millis"] = row["allocatable_cpu_millis"] - row["outside_request_cpu_millis"]
        row["prospective_request_memory_headroom_bytes"] = row["allocatable_memory_bytes"] - row["outside_request_memory_bytes"]
        row["prospective_limit_cpu_headroom_millis"] = row["allocatable_cpu_millis"] - row["outside_limit_cpu_millis"]
        row["prospective_limit_memory_headroom_bytes"] = row["allocatable_memory_bytes"] - row["outside_limit_memory_bytes"]
        if row["prospective_request_cpu_headroom_millis"] < per_node_cpu:
            raise PreconditionError(f"node/{name} has insufficient prospective CPU request headroom")
        if row["prospective_request_memory_headroom_bytes"] < per_node_memory:
            raise PreconditionError(f"node/{name} has insufficient prospective memory request headroom")

    policy = plan.get("longhorn") or {}
    storage_class = kube.json("get", "storageclass", kube.config.application.storage_class)
    if storage_class.get("provisioner") != policy.get("provisioner"):
        raise PreconditionError("CHG-252 StorageClass must use the Longhorn CSI provisioner")
    parameters = storage_class.get("parameters") or {}
    if str(parameters.get("numberOfReplicas") or "") != str(policy.get("requiredReplicaCount")):
        raise PreconditionError("CHG-252 Longhorn StorageClass must explicitly use one replica")
    locality = str(parameters.get("dataLocality") or "")
    if locality not in set(policy.get("allowedDataLocality") or []):
        raise PreconditionError("CHG-252 Longhorn StorageClass has an unapproved data locality")

    longhorn_namespace = str(policy.get("namespace") or "")
    reclaim_by_node, reclaimable_volumes = _longhorn_reclaimable(
        kube, kube.config.target.namespace, longhorn_namespace
    )
    longhorn_nodes = {
        str((row.get("metadata") or {}).get("name") or ""): row
        for row in (
            kube.json("get", "nodes.longhorn.io", namespace=longhorn_namespace).get("items") or []
        )
    }
    required_storage = math.ceil(
        pvc["physical_bytes"] * (100 + int(reserve.get("storage") or 0)) / 100
    )
    per_node_storage = math.ceil(required_storage / len(ready_nodes))
    storage_evidence: dict[str, dict[str, int]] = {}
    for name in ready_nodes:
        row = longhorn_nodes.get(name)
        if not row or (row.get("spec") or {}).get("allowScheduling") is False:
            raise PreconditionError(f"Longhorn node/{name} is absent or scheduling is disabled")
        if not _condition_true((row.get("status") or {}).get("conditions"), "Ready"):
            raise PreconditionError(f"Longhorn node/{name} is not Ready")
        disk_specs = (row.get("spec") or {}).get("disks") or {}
        disk_statuses = (row.get("status") or {}).get("diskStatus") or {}
        usable = []
        for disk_id, disk in disk_statuses.items():
            disk_spec = disk_specs.get(disk_id) or {}
            if disk_spec.get("allowScheduling") is False:
                continue
            conditions = disk.get("conditions") or []
            if not _condition_true(conditions, "Ready") or not _condition_true(conditions, "Schedulable"):
                continue
            usable.append(disk)
        if not usable:
            raise PreconditionError(f"Longhorn node/{name} has no Ready schedulable disk")
        maximum = sum(bytes_quantity(disk.get("storageMaximum") or 0) for disk in usable)
        available = sum(bytes_quantity(disk.get("storageAvailable") or 0) for disk in usable)
        scheduled = sum(bytes_quantity(disk.get("storageScheduled") or 0) for disk in usable)
        prospective = min(maximum, available + reclaim_by_node.get(name, 0))
        storage_evidence[name] = {
            "maximum_bytes": maximum,
            "available_bytes": available,
            "scheduled_bytes": scheduled,
            "reclaimable_actual_bytes": reclaim_by_node.get(name, 0),
            "prospective_available_bytes": prospective,
        }
        if prospective < per_node_storage:
            raise PreconditionError(f"Longhorn node/{name} has insufficient prospective physical capacity")

    return {
        "status": "ready",
        "node_count": len(ready_nodes),
        "planned_resources": planned,
        "planned_storage": pvc,
        "reserve_percent": {
            "cpu": int(reserve.get("cpu") or 0),
            "memory": int(reserve.get("memory") or 0),
            "storage": int(reserve.get("storage") or 0),
        },
        "required_with_reserve": {
            "cpu_millis": required_cpu,
            "memory_bytes": required_memory,
            "physical_storage_bytes": required_storage,
        },
        "nodes": node_evidence,
        "longhorn": {
            "namespace": longhorn_namespace,
            "storage_class": kube.config.application.storage_class,
            "provisioner": storage_class.get("provisioner"),
            "replica_count": int(parameters.get("numberOfReplicas") or 0),
            "data_locality": locality,
            "nodes": storage_evidence,
            "reclaimable_nomosmart_volumes": reclaimable_volumes,
            "protected_openldap_volume": OPENLDAP_LONGHORN_VOLUME,
        },
    }
