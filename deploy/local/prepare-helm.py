#!/usr/bin/env python3
"""Prepare private local Helm inputs from a fresh package; never apply them."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--package-dir", type=Path, required=True)
parser.add_argument("--namespace", required=True)
parser.add_argument("--release", required=True)
parser.add_argument("--storage-class", required=True)
parser.add_argument("--ingress-class", required=True)
parser.add_argument("--ingress-namespace", required=True)
parser.add_argument("--frontend-image", required=True)
parser.add_argument("--backend-image", required=True)
parser.add_argument("--admin-cidr", required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
from ipaddress import ip_network
for cidr in args.admin_cidr.split(","):
    if ip_network(cidr.strip()).prefixlen == 0:
        raise SystemExit("admin CIDR must be restricted")
for value in (args.namespace, args.release, args.storage_class, args.ingress_class, args.ingress_namespace):
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
        raise SystemExit("namespace/release/class must be a DNS label")
for value in (args.frontend_image, args.backend_image):
    if not re.fullmatch(r"[^\s]+:[^@\s]+@sha256:[a-f0-9]{64}", value):
        raise SystemExit("images require an explicit tag and sha256 digest")
pkg = args.package_dir / "current"
manifest = json.loads((pkg / "manifest.json").read_text())
if any(manifest.get(k) != v for k, v in {
    "schema_version": 3, "target": "helm", "profile": "factory_acceptance", "app_env": "development",
    "credential_mode": "initial_random", "helm_namespace": args.namespace,
    "helm_release": args.release, "helm_fullname": args.release}.items()):
    raise SystemExit("expected a fresh random-credential local Helm package for this target")
if pkg.is_symlink() or pkg.stat().st_mode & 0o777 != 0o700:
    raise SystemExit("package directory must be private and regular")
runtime = {}
for row in manifest["secrets"].values():
    relative = Path(row["file"])
    path = pkg / relative
    if relative.is_absolute() or len(relative.parts) != 1 or path.is_symlink() or path.stat().st_mode & 0o777 != 0o600:
        raise SystemExit("unsafe runtime secret file")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != row["sha256"]:
        raise SystemExit("runtime secret fingerprint mismatch")
    runtime[row["file"]] = base64.b64encode(content).decode()
name, ns = args.release, args.namespace
items = [{"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "nomosmart-runtime-secrets", "namespace": ns},
    "type": "Opaque", "data": runtime}]
sets = {
    "ingress": {"tls.crt": "edge.crt", "tls.key": "edge.key"},
    "postgresql": {"tls.crt": "postgresql.crt", "tls.key": "postgresql.key", "ca.crt": "postgresql-ca.crt"},
    "redis": {"tls.crt": "redis.crt", "tls.key": "redis.key", "ca.crt": "redis-ca.crt"},
    "rustfs": {"tls.crt": "rustfs.crt", "tls.key": "rustfs.key", "ca.crt": "rustfs-ca.crt"},
    "opensearch": {"tls.crt": "opensearch.crt", "tls.key": "opensearch.key", "transport.crt": "opensearch-transport.crt",
        "transport.key": "opensearch-transport.key", "ca.crt": "opensearch-ca.crt"}}
for component, files in sets.items():
    data = {}
    for key, filename in files.items():
        path = pkg / "tls/active" / filename
        if path.is_symlink() or path.stat().st_mode & 0o777 != 0o600:
            raise SystemExit("unsafe TLS file")
        data[key] = base64.b64encode(path.read_bytes()).decode()
    items.append({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name + "-" + component + "-tls", "namespace": ns},
        "type": "kubernetes.io/tls", "data": data})
values = {"fullnameOverride": name, "global": {"publicHost": manifest["certificates"]["public_host"],
    "publicOrigin": "https://" + manifest["certificates"]["public_host"]}, "image": {},
    "bootstrap": {"evidenceRelease": name + "-local", "onboardingAdminAllowCidr": args.admin_cidr},
    "migration": {"jdbcUrl": "jdbc:postgresql://" + name + "-postgresql:5432/nomosmart?sslmode=verify-full&sslrootcert=/etc/nomosmart/tls/postgresql-ca.crt"},
    "ingress": {"className": args.ingress_class, "tls": [{"secretName": name + "-ingress-tls", "hosts": [manifest["certificates"]["public_host"]]}]},
    "networkPolicy": {"ingressController": {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": args.ingress_namespace}},
        "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}}}}}
for component, image in (("frontend", args.frontend_image), ("backend", args.backend_image)):
    repository, tag = image.split("@", 1)[0].rsplit(":", 1)
    values["image"][component] = {"repository": repository, "tag": tag + "@" + image.split("@", 1)[1], "pullPolicy": "IfNotPresent"}
for component in ("postgresql", "redis", "rustfs", "opensearch", "neo4j"):
    values[component] = {"persistence": {"storageClass": args.storage_class}}
    if component != "neo4j":
        values[component]["tls"] = {"secretName": name + "-" + component + "-tls"}
args.output_dir.mkdir(mode=0o700)
for filename, payload in (("secrets.json", {"apiVersion": "v1", "kind": "List", "items": items}), ("values.json", values)):
    path = args.output_dir / filename
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
print(f"Prepared private Helm inputs in {args.output_dir}; review them before applying")
