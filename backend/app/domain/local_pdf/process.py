"""Owned synchronous children with deadlines and bounded diagnostics."""
from __future__ import annotations

import os
import errno
from pathlib import Path
import selectors
import signal
import subprocess
import sys
from threading import Event, Lock, Thread
import time

from .errors import Rejected, need


class Tools:
    def __init__(self, *, cwd, deadline, scratch_limit, check, heartbeat,
                 retry_attempts=1, retry_delay=5, retry_codes=()):
        self.cwd, self.deadline, self.scratch_limit = str(cwd), deadline, scratch_limit
        self.check, self.heartbeat = check, heartbeat
        self.exits = []
        self.stop_confirmed = True
        self.retry_attempts, self.retry_delay, self.retry_codes = retry_attempts, retry_delay, retry_codes
        self.retries_left = max(0, retry_attempts-1)

    def run(self, argv, *, stdout_limit=65536, stderr_limit=8192):
        need(time.monotonic() < self.deadline, "deadline")
        need(Path(argv[0]).is_absolute(), "runtime_unavailable")
        self.heartbeat()
        environment = {"PATH": os.pathsep.join((str(Path(argv[0]).parent), "/usr/bin", "/bin")),
                       "HOME": self.cwd, "TMPDIR": self.cwd, "LANG": "C.UTF-8", "OMP_THREAD_LIMIT": "1"}
        wrapper = str(Path(__file__).with_name("tool_exec.py"))
        for attempt in range(self.retry_attempts):
            try:
                child = subprocess.Popen([sys.executable, "-I", "-B", wrapper, str(self.scratch_limit), *argv],
                    cwd=self.cwd, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, close_fds=True, start_new_session=True)
                break
            except OSError as error:
                # Fork resource failure creates no child. Never retry a tool that
                # ran, unknown execution, malformed input or any paid operation.
                if (error.errno not in {errno.EAGAIN, errno.ENOMEM} or self.retries_left < 1
                        or "parser_start_failed_confirmed_stopped" not in self.retry_codes):
                    raise Rejected("runtime_unavailable") from None
                self.retries_left -= 1
                until = time.monotonic()+self.retry_delay
                while time.monotonic() < until:
                    need(time.monotonic() < self.deadline, "deadline")
                    self.heartbeat()
                    time.sleep(min(0.1, max(0, until-time.monotonic())))
        self.stop_confirmed = False
        ownership = Lock()
        finished, expired, stop_error = Event(), Event(), Event()
        kill_sent = False

        def kill_owned():
            nonlocal kill_sent
            if child.returncode is None and not kill_sent:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                kill_sent = True

        def deadline_guard():
            # A DB fencing/heartbeat call may block; it must not suspend the
            # child's wall-clock deadline. This thread never touches the DB.
            if not finished.wait(max(0, self.deadline-time.monotonic())):
                with ownership:
                    if child.returncode is None:
                        expired.set()
                        try:
                            kill_owned()
                        except OSError:
                            # Do not let a background exception imply a confirmed
                            # stop. The owner still attempts cleanup and keeps the
                            # admission unresolved if signal authority was lost.
                            stop_error.set()

        guard = Thread(target=deadline_guard, name="pdf-tool-deadline", daemon=True)
        outputs = {"out": bytearray(), "err": bytearray()}
        limits = {"out": stdout_limit, "err": stderr_limit}
        try:
            guard.start()
            with selectors.DefaultSelector() as selector:
                for stream, key in ((child.stdout, "out"), (child.stderr, "err")):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, key)
                while selector.get_map():
                    need(time.monotonic() < self.deadline, "deadline")
                    self.check()
                    self.heartbeat()
                    for key, _ in selector.select(min(0.1, max(0, self.deadline-time.monotonic()))):
                        block = os.read(key.fd, 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        need(len(outputs[key.data]) + len(block) <= limits[key.data], "output_limit")
                        outputs[key.data].extend(block)
                # EOF alone is not exit. Wait with a bounded deadline.
                while child.returncode is None:
                    need(time.monotonic() < self.deadline, "deadline")
                    self.check()
                    self.heartbeat()
                    if hasattr(os, "waitid"):
                        # Linux production: retain the child's PID until the owned
                        # group has received its final stop, avoiding PID reuse.
                        status = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                        if status is None:
                            time.sleep(min(0.05, max(0, self.deadline-time.monotonic())))
                            continue
                        with ownership:
                            kill_owned()
                            child.wait(timeout=5)
                        break
                    try:
                        with ownership:
                            child.wait(timeout=min(0.1, max(0.001, self.deadline-time.monotonic())))
                    except subprocess.TimeoutExpired:
                        continue
            need(not expired.is_set(), "deadline")
            need(child.returncode == 0, "encrypted_pdf" if b"password" in outputs["err"].lower() else "invalid_output")
            stderr = bytes(outputs["err"])
            if Path(argv[0]).name in {"pdfinfo", "pdftotext", "pdfseparate", "pdftoppm"} and stderr:
                raise Rejected("runtime_unavailable" if b"missing language pack" in stderr.lower() else "invalid_output")
            self.check()
            return bytes(outputs["out"])
        finally:
            # Only this still-owned, unreaped child's group. Never use stored PIDs.
            try:
                with ownership:
                    kill_owned()
                    child.wait(timeout=5)
                finished.set()
                if guard.ident is not None:
                    guard.join(timeout=5)
                self.exits.append({"pid": child.pid, "returncode": child.returncode})
                self.stop_confirmed = child.returncode is not None and not guard.is_alive() and not stop_error.is_set()
            finally:
                finished.set()
                child.stdout.close()
                child.stderr.close()
