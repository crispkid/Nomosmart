#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


INSTALLER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = INSTALLER_ROOT.parents[1]
sys.path.insert(0, str(INSTALLER_ROOT))

from nomosmart_installer.config import load_config
from nomosmart_installer.core import Redactor, Runner
from nomosmart_installer.kube import Kubernetes
from nomosmart_installer.orchestrator import Installer


def snapshot(kube: Kubernetes) -> dict[str, Any]:
    namespace = kube.config.target.namespace
    namespaces = kube.json("get", "namespaces")
    target_exists = kube.exists("namespace", namespace, namespace=False)
    resources: dict[str, Any] = {}
    if target_exists:
        for kind in (
            "all",
            "configmap",
            "secret",
            "pvc",
            "ingress",
            "lease",
            "job",
        ):
            payload = kube.json("get", kind, namespace=True)
            resources[kind] = sorted(
                (
                    str((row.get("metadata") or {}).get("uid") or ""),
                    str(
                        (row.get("metadata") or {}).get("resourceVersion")
                        or ""
                    ),
                )
                for row in payload.get("items") or []
            )
    return {
        "namespace_inventory": sorted(
            (
                str((row.get("metadata") or {}).get("name") or ""),
                str((row.get("metadata") or {}).get("uid") or ""),
            )
            for row in namespaces.get("items") or []
        ),
        "target_resources": resources,
    }


def main() -> int:
    config_value = os.environ.get("NOMOSMART_INSTALLER_LIVE_CONFIG", "").strip()
    if not config_value:
        print(
            "blocked: NOMOSMART_INSTALLER_LIVE_CONFIG is required for a real disposable cluster",
            file=sys.stderr,
        )
        return 2
    config = load_config(Path(config_value))
    runner = Runner(Redactor(), cwd=REPOSITORY)
    kube = Kubernetes(config, runner)
    installer = Installer(config)
    before = snapshot(kube)
    plan = installer.plan()
    after = snapshot(kube)
    if before != after:
        print("failed: read-only plan changed Kubernetes resource versions", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "plan-read-only-verified",
                "cluster_uid": plan["target"]["cluster_uid"],
                "config_digest": plan["config_digest"],
            },
            sort_keys=True,
        )
    )
    if os.environ.get("NOMOSMART_INSTALLER_LIVE_EXECUTE") != "YES":
        print(
            "blocked: set NOMOSMART_INSTALLER_LIVE_EXECUTE=YES only for an approved disposable target",
            file=sys.stderr,
        )
        return 2
    status = installer.status()
    command = "install" if status["status"] == "not-installed" else "resume"
    completed = subprocess.run(
        [
            str(INSTALLER_ROOT / "nomosmart-install"),
            command,
            "--config",
            str(config.source_path),
        ],
        cwd=REPOSITORY,
        check=False,
    )
    if completed.returncode == 10:
        print(
            "blocked: human password-login and directory-role checkpoint remains; complete it and rerun this command",
            file=sys.stderr,
        )
        return 2
    if completed.returncode != 0:
        return completed.returncode
    receipt = installer.verify()
    print(
        json.dumps(
            {
                "status": "live-installer-verified",
                "cluster_uid": receipt["target"]["cluster_uid"],
                "helm_revision": receipt["helm"]["revision"],
                "services_left_running": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
