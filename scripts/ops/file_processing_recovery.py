#!/usr/bin/env python3
"""Observe an exact Kubernetes Worker through an existing Docker node transport.

No platform writes, host mounts, credentials, fabricated child exits or public
endpoint. capture/watch produce private metadata evidence. preview/commit invoke
the authenticated Backend CLI with a token supplied only on stdin. Deployment
and normal scaling remain separate approved operator actions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from uuid import UUID


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def check(condition, code):
    if not condition:
        raise RuntimeError(code)


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        s = os.fstat(fd)
        check(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and s.st_mode & 0o077 == 0
              and s.st_size <= 65536, "private_input_invalid")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return json.loads(stream.read(65537))
    finally:
        os.close(fd)


def write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


class Observer:
    def __init__(self, configuration):
        self.c = configuration
        self.scope = configuration["scope"]
        for field in ("worker_uid", "node_uid", "parser_generation", "launch_uid", "actor_id"):
            check(str(UUID(self.scope[field])) == self.scope[field], "invalid_identity")
        for field in ("container_id", "node_container_id", "scratch_before_sha256"):
            check(bool(re.fullmatch(r"[a-f0-9]{64}", self.scope[field])), "invalid_digest")
        for field in ("namespace", "node", "worker_pod", "release", "backend_pod"):
            check(bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", configuration[field])), "invalid_name")
        self.k = ["kubectl", "--context", configuration["kube_context"], "--request-timeout=15s"]
        self.d = ["docker", "--context", configuration["docker_context"]]
        self.node_exec = [*self.d, "exec", self.scope["node_container_id"]]
        self.scratch = f'/var/lib/kubelet/pods/{self.scope["worker_uid"]}/volumes/kubernetes.io~empty-dir/pdf-scratch'

    def command(self, args, body=None):
        result = subprocess.run(args, input=body, capture_output=True, timeout=25)
        check(result.returncode == 0, "management_read_failed")
        return result.stdout

    def get(self, kind, name, *, optional=False):
        data = self.command([*self.k, "-n", self.c["namespace"], "get", kind, name,
                             *(["--ignore-not-found"] if optional else []), "-o", "json"])
        return json.loads(data) if data.strip() else None

    def node(self):
        node = self.get("node", self.c["node"])
        check(node["metadata"]["uid"] == self.scope["node_uid"]
              and all(c["status"] == ("True" if c["type"] == "Ready" else "False")
                      for c in node["status"]["conditions"]
                      if c["type"] in {"Ready", "MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"})
              and any(c["type"] == "Ready" for c in node["status"]["conditions"]), "node_not_healthy")
        info = json.loads(self.command([*self.d, "inspect", "--format",
            '{"id":{{json .Id}},"hostname":{{json .Config.Hostname}},"running":{{json .State.Running}},'
            '"started":{{json .State.StartedAt}},"restart_count":{{json .RestartCount}},"networks":{{json .NetworkSettings.Networks}}}',
            self.scope["node_container_id"]]))
        addresses = {a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP"}
        check(info["id"] == self.scope["node_container_id"] and info["hostname"] == self.c["node"]
              and info["running"] is True and any(v["IPAddress"] in addresses for v in info["networks"].values()),
              "node_transport_mismatch")
        return {k:info[k] for k in ("id", "hostname", "started", "restart_count")}

    def runtime(self):
        rows = json.loads(self.command([*self.node_exec, "crictl", "ps", "-a", "--id",
                                       self.scope["container_id"], "-o", "json"]))["containers"]
        if not rows:
            return None
        check(len(rows) == 1 and rows[0]["id"] == self.scope["container_id"], "runtime_ambiguous")
        value = json.loads(self.command([*self.node_exec, "crictl", "inspect", "--quiet", "--output", "go-template",
                                       "--template", "{{json .status}}", self.scope["container_id"]]))
        labels = value["labels"]
        check(value["id"] == self.scope["container_id"] and labels["io.kubernetes.pod.uid"] == self.scope["worker_uid"]
              and labels["io.kubernetes.pod.name"] == self.c["worker_pod"]
              and labels["io.kubernetes.pod.namespace"] == self.c["namespace"]
              and labels["io.kubernetes.container.name"] == "worker", "runtime_identity_changed")
        mounts = [m for m in value["mounts"] if m["containerPath"] == "/run/pdf-work"]
        check(len(mounts) == 1 and mounts[0]["hostPath"] == self.scratch and mounts[0]["readonly"] is False,
              "scratch_mount_mismatch")
        return {k:value[k] for k in ("id", "state", "startedAt", "finishedAt", "exitCode", "reason", "imageRef")}

    def scratch_stat(self):
        # Validate each existing ancestor without following symlinks. Missing a
        # root is an error, not evidence that the target volume was removed.
        parts = Path(self.scratch).parts
        observed = []
        for n in range(2, len(parts)+1):
            path = str(Path(*parts[:n]))
            result = subprocess.run([*self.node_exec, "stat", "-c", "%F|%u|%g|%a|%d|%i", path],
                                    capture_output=True, timeout=15)
            if result.returncode:
                check(n >= 6 and b"No such file or directory" in result.stderr, "scratch_stat_unavailable")
                return {"absent": True, "first_missing": path, "ancestors": observed}
            values = result.stdout.decode().strip().split("|")
            check(len(values) == 6 and values[0] == "directory", "scratch_ancestor_not_directory")
            observed.append({"path": path, "stat": values})
        return {"absent": False, "ancestors": observed}

    def maintenance(self):
        result = {}
        for component in ("frontend", "beat"):
            row = self.get("deployment", self.c["release"]+"-"+component)
            check(row["metadata"]["uid"] == self.c["maintenance_uids"][component]
                  and row["spec"]["replicas"] == 0 and row["status"].get("replicas",0) == 0, "intake_not_paused")
            pods = json.loads(self.command([*self.k, "-n", self.c["namespace"], "get", "pods", "-l",
                "app.kubernetes.io/instance="+self.c["release"]+",app.kubernetes.io/component="+component,"-o","json"]))["items"]
            check(not pods, "maintenance_pods_remaining")
            result[component] = {"uid":row["metadata"]["uid"], "replicas":0}
        service = self.get("service", self.c["release"]+"-backend")
        check(service["metadata"]["uid"] == self.c["maintenance_uids"]["backend_service"]
              and service["spec"]["selector"] == self.c["maintenance_selector"], "backend_entry_not_paused")
        endpoints = json.loads(self.command([*self.k,"-n",self.c["namespace"],"get","endpointslices",
            "-l","kubernetes.io/service-name="+service["metadata"]["name"],"-o","json"]))["items"]
        check(all(not e.get("endpoints") for e in endpoints), "backend_entry_has_endpoints")
        result["backend_service"] = {"uid":service["metadata"]["uid"], "selector":service["spec"]["selector"]}
        return digest(result)

    def capture(self):
        node = self.node()
        pod = self.get("pod", self.c["worker_pod"])
        check(pod["metadata"]["uid"] == self.scope["worker_uid"] and pod["spec"]["nodeName"] == self.c["node"]
              and not pod["metadata"].get("deletionTimestamp"), "old_worker_changed")
        status = next(c for c in pod["status"]["containerStatuses"] if c["name"] == "worker")
        check(status["containerID"] == "containerd://"+self.scope["container_id"] and "running" in status["state"],
              "worker_container_changed")
        runtime, scratch = self.runtime(), self.scratch_stat()
        check(runtime is not None and runtime["state"] == "CONTAINER_RUNNING" and not scratch["absent"], "capture_not_running")
        check(digest(scratch) == self.scope["scratch_before_sha256"], "scratch_before_changed")
        return {"scope_sha256":digest(self.scope), "utc":utc(), "node":node, "runtime":runtime, "scratch":scratch}

    def watch(self, capture):
        check(capture["scope_sha256"] == digest(self.scope), "scope_changed")
        deadline = time.monotonic()+180
        last_print = 0
        terminal = None
        while time.monotonic() < deadline:
            check(self.node() == capture["node"], "node_restarted")
            runtime = self.runtime()
            if runtime and runtime["state"] == "CONTAINER_EXITED":
                check(runtime["exitCode"] == 0 and runtime["reason"] == "Completed"
                      and runtime["startedAt"] == capture["runtime"]["startedAt"], "worker_not_normally_stopped")
                check(datetime.fromisoformat(runtime["finishedAt"].replace("Z","+00:00")) >=
                      datetime.fromisoformat(capture["utc"]), "stale_termination")
                terminal = runtime
            check(runtime is not None or terminal is not None, "runtime_disappeared_without_terminal")
            if terminal:
                scratch = self.scratch_stat()
                pod = self.get("pod", self.c["worker_pod"], optional=True)
                if scratch["absent"] and pod is None:
                    return {"scope_sha256":digest(self.scope), "capture":capture, "terminal":terminal,
                            "scratch_after":scratch, "utc":utc(), "maintenance_sha256":self.maintenance()}
            if time.monotonic()-last_print > 10:
                print(json.dumps({"waiting_for":"normal_stop_and_scratch_clearance","terminal_seen":terminal is not None}), flush=True)
                last_print = time.monotonic()
            time.sleep(0.5)
        raise RuntimeError("terminal_observation_timeout")

    def evidence(self, journal):
        check(journal["scope_sha256"] == digest(self.scope) and self.node() == journal["capture"]["node"], "journal_identity_changed")
        terminal = journal["terminal"]
        check(terminal["state"] == "CONTAINER_EXITED" and terminal["exitCode"] == 0
              and terminal["reason"] == "Completed", "normal_terminal_missing")
        runtime = self.runtime()
        check(runtime is None or runtime == terminal, "old_runtime_not_terminal")
        check(self.get("pod", self.c["worker_pod"], optional=True) is None and self.scratch_stat()["absent"], "old_worker_not_clean")
        maintenance = self.maintenance()
        check(maintenance == journal["maintenance_sha256"], "maintenance_changed")
        s = self.scope
        return {"source":"operator_runtime_terminal_v1", "scope_sha256":digest(s),
                "generation":s["parser_generation"], "workload_uid":s["launch_uid"], "worker_uid":s["worker_uid"],
                "node_uid":s["node_uid"], "node_container_id":s["node_container_id"], "container_id":s["container_id"],
                "started_at":terminal["startedAt"], "finished_at":terminal["finishedAt"], "observed_at":utc(),
                "exit_code":0, "scratch_before_sha256":s["scratch_before_sha256"], "scratch_absent":True,
                "runtime_stopped":True, "maintenance_sha256":maintenance, "actor_id":s["actor_id"]}

    def invoke(self, operation, evidence=None):
        token = sys.stdin.buffer.read(32769).decode().strip()
        check(1 <= len(token) <= 32768, "private_token_input_invalid")
        pod = self.get("pod", self.c["backend_pod"])
        check(pod["metadata"]["uid"] == self.c["backend_uid"], "backend_changed")
        payload = {"access_token":token, "scope":self.scope}
        if evidence is not None:
            payload["evidence"] = evidence
        result = self.command([*self.k,"-n",self.c["namespace"],"exec","-i",self.c["backend_pod"],"-c","backend","--",
                               "python","-B","-m","app.deployment.file_processing_recovery",operation], json.dumps(payload).encode())
        value = json.loads(result)
        check(value["scope_sha256"] == digest(self.scope), "backend_scope_mismatch")
        return value


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("operation", choices=("capture", "watch", "preview", "commit"))
    cli.add_argument("--configuration", type=Path, required=True)
    cli.add_argument("--capture", type=Path)
    cli.add_argument("--journal", type=Path)
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()
    try:
        observer = Observer(read_private(args.configuration))
        if args.operation == "capture":
            check(args.output is not None, "output_required")
            result = observer.capture()
        elif args.operation == "watch":
            check(args.capture is not None and args.output is not None, "capture_and_output_required")
            result = observer.watch(read_private(args.capture))
        elif args.operation == "preview":
            result = observer.invoke("preview")
        else:
            check(args.journal is not None and args.output is not None and not args.output.exists(), "unique_commit_output_required")
            evidence = observer.evidence(read_private(args.journal))
            # Record intent before submission: an uncertain response requires a
            # read-only DB reconciliation, never an automatic write retry.
            write_private(args.output.with_suffix(".intent.json"), {"scope_sha256":digest(observer.scope), "utc":utc(), "evidence":evidence})
            result = observer.invoke("commit", evidence)
        if args.output:
            write_private(args.output, result)
        print(json.dumps({"operation":args.operation, "status":result.get("status","observed"),
                          "scope_sha256":digest(observer.scope)}))
        return 0
    except Exception as error:
        code = str(error) if type(error) is RuntimeError and re.fullmatch(r"[a-z_]+", str(error)) else "operator_check_failed"
        print(json.dumps({"error":code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
