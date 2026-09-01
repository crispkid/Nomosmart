#!/usr/bin/env python3
"""Fail-closed, cluster-aware production prerequisite validation for NomoSmart."""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
from typing import Any


RUNTIME_SECRET_KEYS = (
    "APP_ENCRYPTION_KEY",
    "DATABASE_URL",
    "DATABASE_MIGRATION_USER",
    "DATABASE_MIGRATION_PASSWORD",
    "OIDC_CLIENT_SECRET",
    "KEYCLOAK_SYNC_CLIENT_SECRET",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "OPENSEARCH_PASSWORD",
    "NEO4J_PASSWORD",
)
COMPATIBILITY_KEYS = (
    "application_contract",
    "schema_contract",
    "public_api_contract",
    "security_contract",
)


class PreflightError(RuntimeError):
    pass


def kubectl(*args: str) -> str:
    process = subprocess.run(
        ["kubectl", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout).strip().splitlines()
        raise PreflightError(detail[0][:300] if detail else "kubectl request failed")
    return process.stdout


def resource(kind: str, name: str, namespace: str) -> dict[str, Any]:
    try:
        return json.loads(kubectl("-n", namespace, "get", kind, name, "-o", "json"))
    except (json.JSONDecodeError, PreflightError) as exc:
        raise PreflightError(f"{kind}/{name} is missing or unreadable in namespace {namespace}") from exc


def validate_secret(name: str, namespace: str, keys: tuple[str, ...]) -> None:
    data = resource("secret", name, namespace).get("data") or {}
    for key in keys:
        encoded = data.get(key)
        if not encoded:
            raise PreflightError(f"secret/{name} is missing required key {key}")
        try:
            value = base64.b64decode(encoded, validate=True).decode("utf-8").strip()
        except (ValueError, UnicodeError) as exc:
            raise PreflightError(f"secret/{name} key {key} is not valid non-empty secret data") from exc
        normalized = value.upper()
        if (
            not value
            or "CHANGE_ME" in normalized
            or "PLACEHOLDER" in normalized
            or (len(value) >= 16 and set(value) <= {"0"})
        ):
            raise PreflightError(f"secret/{name} key {key} contains prohibited placeholder data")


def validate_configmap_key(name: str, namespace: str, key: str, expected: str | None = None) -> None:
    data = resource("configmap", name, namespace).get("data") or {}
    value = str(data.get(key) or "").strip()
    if not value:
        raise PreflightError(f"configmap/{name} is missing required key {key}")
    if expected is not None and value != expected:
        raise PreflightError(f"configmap/{name} key {key} is incompatible with the requested release")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--namespace", required=True)
    result.add_argument("--runtime-secret", required=True)
    result.add_argument("--ingress-tls-secret", required=True)
    result.add_argument("--opensearch-mode", choices=("bundled", "external"), required=True)
    result.add_argument("--opensearch-tls-secret", required=True)
    result.add_argument("--min-schedulable-nodes", type=int, default=3)
    result.add_argument("--compatibility-configmap")
    result.add_argument("--application-contract")
    result.add_argument("--schema-contract")
    result.add_argument("--public-api-contract")
    result.add_argument("--security-contract")
    result.add_argument("--sftp-known-hosts-configmap")
    result.add_argument("--deployment-configmap")
    result.add_argument("--require-operational", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if shutil.which("kubectl") is None:
        raise PreflightError("kubectl is required for cluster preflight")
    kubectl("version", "--request-timeout=10s")
    nodes = json.loads(kubectl("get", "nodes", "-o", "json")).get("items") or []
    schedulable = [
        node for node in nodes
        if not (node.get("spec") or {}).get("unschedulable")
        and all(
            condition.get("status") == "True"
            for condition in (node.get("status") or {}).get("conditions") or []
            if condition.get("type") == "Ready"
        )
    ]
    if len(schedulable) < args.min_schedulable_nodes:
        raise PreflightError(
            f"cluster has {len(schedulable)} schedulable Ready nodes; {args.min_schedulable_nodes} are required"
        )
    storage_classes = json.loads(kubectl("get", "storageclass", "-o", "json")).get("items") or []
    if not storage_classes:
        raise PreflightError("cluster has no StorageClass for required persistent workloads")
    validate_secret(args.runtime_secret, args.namespace, RUNTIME_SECRET_KEYS)
    validate_secret(args.ingress_tls_secret, args.namespace, ("tls.crt", "tls.key"))
    opensearch_keys = (
        ("tls.crt", "tls.key", "transport.crt", "transport.key", "ca.crt")
        if args.opensearch_mode == "bundled"
        else ("ca.crt",)
    )
    validate_secret(args.opensearch_tls_secret, args.namespace, opensearch_keys)
    if args.sftp_known_hosts_configmap:
        validate_configmap_key(args.sftp_known_hosts_configmap, args.namespace, "ssh_known_hosts")
    if args.require_operational:
        if not args.deployment_configmap:
            raise PreflightError(
                "deployment configmap is required when operational phase is required"
            )
        validate_configmap_key(
            args.deployment_configmap,
            args.namespace,
            "DEPLOYMENT_PHASE",
            "operational",
        )
    expected_contracts = {
        "application_contract": args.application_contract,
        "schema_contract": args.schema_contract,
        "public_api_contract": args.public_api_contract,
        "security_contract": args.security_contract,
    }
    if args.compatibility_configmap:
        for key in COMPATIBILITY_KEYS:
            validate_configmap_key(args.compatibility_configmap, args.namespace, key, expected_contracts[key])
    elif any(expected_contracts.values()):
        raise PreflightError("compatibility configmap is required when expected release identities are provided")
    print(
        "Helm preflight passed: referenced resources, node count, "
        "and compatibility identity are valid; CHG-252 physical capacity "
        "requires guided installer plan evidence"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PreflightError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"cluster preflight failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
