"""Bounded real child execution; no stale group signals or embedded raw reports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

GiB = 1024 ** 3


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        path.chmod(0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)


def processes() -> dict:
    # No command arguments, environments, usernames or sensitive contents.
    result = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,pgid=,uid=,rss="],
                            capture_output=True, check=True, timeout=10)
    return {int(row[0]): dict(zip(("parent", "group", "uid", "rss_kib"), map(int, row[1:])))
            for line in result.stdout.splitlines() if (row := line.split())}


def descendants(rows, root):
    selected = {root}
    while True:
        children = {pid for pid, row in rows.items() if row["parent"] in selected}
        if children <= selected:
            return selected
        selected |= children


def terminate_owned(proc, record) -> None:
    """A live, unreaped direct child is the identity anchor; never target old PIDs."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if proc.poll() is not None:
            record["already_exited"] = True
            return
        rows = processes()
        leader = rows.get(proc.pid)
        group = {pid for pid, row in rows.items() if row["group"] == proc.pid}
        if proc.poll() is not None:
            record["exit_race_observed"] = True
            return
        if (not leader or leader["parent"] != os.getpid() or leader["group"] != proc.pid
                or leader["uid"] != os.getuid() or not group
                or not group <= descendants(rows, proc.pid)
                or any(rows[pid]["uid"] != os.getuid() for pid in group)):
            raise RuntimeError("owned_child_identity_not_proven")
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            # ESRCH can be an ordinary exit race. EPERM is deliberately not caught.
            if proc.poll() is None:
                raise
            record["exit_race_observed"] = True
            return
        record.setdefault("signals", []).append({"group": proc.pid, "members": sorted(group), "signal": int(sig)})
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue
    raise RuntimeError("owned_child_not_stopped")


def execute(args, directory: Path, *, env=None, cwd=None, timeout=120,
            rss_limit=8*GiB, guard=None) -> dict:
    """Each command owns a new directory and stores raw output exactly once."""
    directory.mkdir(mode=0o700)
    record = {"args": args, "timeout_seconds": timeout, "rss_limit": rss_limit,
              "peak_rss_bytes": 0, "samples": 0, "termination": {}}
    started = time.monotonic()
    proc = None
    try:
        with (directory / "stdout").open("xb") as out, (directory / "stderr").open("xb") as err:
            proc = subprocess.Popen(args, stdout=out, stderr=err, env=env,
                                    cwd=cwd, start_new_session=True)
            record["child_pid"] = proc.pid
            while proc.poll() is None:
                rows = processes()
                selected = descendants(rows, os.getpid())
                rss = sum(rows[p]["rss_kib"] * 1024 for p in selected if p in rows)
                record["peak_rss_bytes"] = max(record["peak_rss_bytes"], rss)
                record["samples"] += 1
                if rss > rss_limit:
                    raise RuntimeError("host_process_rss_limit")
                if time.monotonic() - started >= timeout:
                    raise TimeoutError("owned_command_timeout")
                if guard:
                    guard()
                try:
                    proc.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    pass
            record["exit_code"] = proc.returncode
    except BaseException as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)
        if proc is not None:
            try:
                terminate_owned(proc, record["termination"])
            except BaseException as termination_error:
                record["termination_error"] = type(termination_error).__name__ + ": " + str(termination_error)
                raise
        raise
    finally:
        record["elapsed_seconds"] = round(time.monotonic()-started, 3)
        record["exit_code"] = proc.returncode if proc is not None else None
        record["reports"] = {name: {"path": str(directory/name), "sha256": digest(directory/name)}
                             for name in ("stdout", "stderr") if (directory/name).exists()}
        write_new(directory / "result.json", record)
    return record
