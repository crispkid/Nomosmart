#!/usr/bin/env python3
"""Render a disposable, namespace-scoped local ingress controller (no CRDs)."""
import argparse
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--namespace", required=True, help="controller namespace, already created")
parser.add_argument("--watch-namespace", required=True)
parser.add_argument("--class-name", required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
for value in (args.namespace, args.watch_namespace, args.class_name):
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
        raise SystemExit("namespace/class must be a DNS label")
name, ns, watched = args.class_name, args.namespace, args.watch_namespace
controller = "nomosmart.io/" + name
labels = {"app.kubernetes.io/name": "traefik", "app.kubernetes.io/instance": name}


def obj(api, kind, name, namespace=None, **fields):
    metadata = {"name": name, "labels": labels}
    if namespace:
        metadata["namespace"] = namespace
    return {"apiVersion": api, "kind": kind, "metadata": metadata, **fields}


subject = [{"kind": "ServiceAccount", "name": name, "namespace": ns}]
items = [
    obj("v1", "ServiceAccount", name, ns),
    obj("rbac.authorization.k8s.io/v1", "Role", name, watched, rules=[
        {"apiGroups": [""], "resources": ["services", "secrets", "configmaps"], "verbs": ["list", "watch"]},
        {"apiGroups": ["discovery.k8s.io"], "resources": ["endpointslices"], "verbs": ["list", "watch"]},
        {"apiGroups": ["networking.k8s.io"], "resources": ["ingresses"], "verbs": ["list", "watch"]},
        {"apiGroups": ["networking.k8s.io"], "resources": ["ingresses/status"], "verbs": ["update"]}]),
    obj("rbac.authorization.k8s.io/v1", "RoleBinding", name, watched, subjects=subject,
        roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": name}),
    obj("rbac.authorization.k8s.io/v1", "ClusterRole", name, rules=[
        {"apiGroups": ["networking.k8s.io"], "resources": ["ingressclasses"], "verbs": ["list", "watch"]}]),
    obj("rbac.authorization.k8s.io/v1", "ClusterRoleBinding", name, subjects=subject,
        roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": name}),
    obj("networking.k8s.io/v1", "IngressClass", name, spec={"controller": controller}),
    obj("v1", "Service", name, ns, spec={"selector": labels, "ports": [
        {"name": "http", "port": 80, "targetPort": 8080}, {"name": "https", "port": 443, "targetPort": 8443}]}),
    obj("apps/v1", "Deployment", name, ns, spec={"replicas": 1, "selector": {"matchLabels": labels},
        "template": {"metadata": {"labels": labels}, "spec": {"serviceAccountName": name,
            "securityContext": {"runAsNonRoot": True, "runAsUser": 65532, "runAsGroup": 65532,
                "seccompProfile": {"type": "RuntimeDefault"}}, "containers": [{"name": "traefik",
                "image": "traefik:v3.7.0@sha256:eb328e2c806c53aafbbace6c451fa54d268961261a85452fcf0fb752a30c17be",
                "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                    "capabilities": {"drop": ["ALL"]}},
                "args": ["--entrypoints.web.address=:8080", "--entrypoints.websecure.address=:8443",
                    "--entrypoints.health.address=:8082", "--ping=true", "--ping.entrypoint=health",
                    "--providers.kubernetesingressnginx=true",
                    "--providers.kubernetesingressnginx.watchnamespace=" + watched,
                    "--providers.kubernetesingressnginx.ingressclass=" + name,
                    "--providers.kubernetesingressnginx.controllerclass=" + controller,
                    "--providers.kubernetesingressnginx.watchingresswithoutclass=false",
                    "--providers.kubernetesingressnginx.ingressclassbyname=false",
                    "--providers.kubernetesingressnginx.allowcrossnamespaceresources=false",
                    "--providers.kubernetesingressnginx.allowsnippetannotations=false",
                    "--providers.kubernetesingressnginx.httpentrypoint=web",
                    "--providers.kubernetesingressnginx.httpsentrypoint=websecure"],
                "readinessProbe": {"httpGet": {"path": "/ping", "port": 8082}},
                "livenessProbe": {"httpGet": {"path": "/ping", "port": 8082}},
                "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "500m", "memory": "256Mi"}}
            }]}}})]
with args.output.open("x", encoding="utf-8") as stream:
    json.dump({"apiVersion": "v1", "kind": "List", "items": items}, stream, indent=2)
    stream.write("\n")
print(f"Prepared ingress for {watched} only; apply {args.output}, then forward the {ns}/{name} Service on loopback")
