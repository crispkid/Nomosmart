"""Bounded Worker-owned child, not an OS isolation boundary."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from app.core.errors import AppError


@dataclass(frozen=True)
class ChildResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def run_office_child(argv: list[str], *, cwd: Path, timeout: float, memory_bytes: int,
                     file_bytes: int) -> ChildResult:
    """Only fixed operator-controlled argv; stop/reap before caller cleans cwd.

    No inherited secrets, shell, preexec_fn in a multithreaded Worker, or shared
    UID-wide process limit. The private wrapper applies limits before exec.
    """
    if os.geteuid() == 0 or not argv or not Path(argv[0]).is_absolute():
        raise AppError("pandoc_sandbox_unavailable", "Pandoc requires a non-root bounded runtime", status_code=503)
    env = {"PATH": os.pathsep.join((str(Path(argv[0]).parent), "/usr/bin", "/bin")),
           "HOME": str(cwd), "TMPDIR": str(cwd), "LANG": "C.UTF-8"}
    deadline = time.monotonic() + timeout
    try:
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", str(Path(__file__).with_name("office_tool_exec.py")),
             str(memory_bytes), str(max(1, int(timeout))), str(file_bytes), *argv],
            cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, close_fds=True, start_new_session=True,
        )
    except OSError:
        raise AppError("pandoc_unavailable", "Pandoc could not start", status_code=503) from None
    buffers = {"stdout": bytearray(), "stderr": bytearray()}

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise AppError("pandoc_timeout", "Pandoc conversion exceeded its time limit", status_code=503)
        return value

    def stop_owned():
        # Never signal a persisted/reaped PID. Linux waitid(WNOWAIT) below keeps
        # ownership of the PID until the final group stop and wait.
        if child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)

    try:
        with selectors.DefaultSelector() as selector:
            for stream, name in ((child.stdout, "stdout"), (child.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                for key, _ in selector.select(min(0.1, remaining())):
                    body = os.read(key.fd, 8192)
                    if not body:
                        selector.unregister(key.fileobj)
                    elif len(buffers[key.data]) + len(body) > 65536:
                        raise AppError("pandoc_output_invalid", "Pandoc diagnostic output exceeds the safe limit", status_code=422)
                    else:
                        buffers[key.data].extend(body)
            if hasattr(os, "waitid"):
                while os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                    time.sleep(min(0.05, remaining()))
                stop_owned()
            else:
                child.wait(timeout=remaining())
        return ChildResult(child.returncode, bytes(buffers["stdout"]), bytes(buffers["stderr"]))
    except subprocess.TimeoutExpired:
        raise AppError("pandoc_timeout", "Pandoc conversion exceeded its time limit", status_code=503) from None
    finally:
        try:
            stop_owned()
        finally:
            child.stdout.close()
            child.stderr.close()

