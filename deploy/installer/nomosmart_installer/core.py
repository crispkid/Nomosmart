from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import threading
import time
from typing import Iterator, Sequence


TOKEN_PATTERNS = (
    re.compile(r"\bhvs\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\bhvb\.[A-Za-z0-9_-]+\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)


class InstallerError(RuntimeError):
    exit_code = 30


class PreconditionError(InstallerError):
    exit_code = 20


class ActionRequired(InstallerError):
    exit_code = 10


class DriftError(InstallerError):
    exit_code = 40


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class Redactor:
    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, value: str) -> None:
        normalized = value.strip()
        if len(normalized) >= 4:
            self._values.add(normalized)

    def text(self, value: str) -> str:
        redacted = value
        for secret in sorted(self._values, key=len, reverse=True):
            redacted = redacted.replace(secret, "[REDACTED]")
        for pattern in TOKEN_PATTERNS:
            redacted = pattern.sub("[REDACTED_TOKEN]", redacted)
        return redacted


class Runner:
    def __init__(self, redactor: Redactor, *, cwd: Path) -> None:
        self.redactor = redactor
        self.cwd = cwd
        self._children: dict[int, subprocess.Popen[str]] = {}
        self._children_lock = threading.Lock()
        self._requested_signal: int | None = None

    def forward_signal(self, signum: int) -> None:
        self._requested_signal = signum
        with self._children_lock:
            children = list(self._children.values())
        for process in children:
            if process.poll() is not None:
                continue
            try:
                os.killpg(process.pid, signum)
            except ProcessLookupError:
                continue

    @staticmethod
    def _stop_process_group(
        process: subprocess.Popen[str],
        signum: int,
        *,
        timeout: float = 10.0,
    ) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        for stream in (
            process.stdin,
            process.stdout,
            process.stderr,
        ):
            if stream is not None and not stream.closed:
                stream.close()

    def run(
        self,
        command: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: int = 120,
        accepted: frozenset[int] = frozenset({0}),
        sensitive_output: bool = False,
    ) -> CommandResult:
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                list(command),
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=self._environment(),
                start_new_session=True,
            )
            with self._children_lock:
                self._children[process.pid] = process
            stdout_raw, stderr_raw = process.communicate(
                input=input_text,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise PreconditionError(f"required command is unavailable: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                self._stop_process_group(process, signal.SIGTERM)
            raise InstallerError(f"command timed out: {command[0]}") from exc
        except KeyboardInterrupt:
            if process is not None:
                self._stop_process_group(
                    process,
                    self._requested_signal or signal.SIGINT,
                )
            raise
        finally:
            if process is not None:
                with self._children_lock:
                    self._children.pop(process.pid, None)
            self._requested_signal = None
        stdout = stdout_raw if sensitive_output else self.redactor.text(stdout_raw)
        stderr = stderr_raw if sensitive_output else self.redactor.text(stderr_raw)
        returncode = int(process.returncode)
        result = CommandResult(returncode, stdout, stderr)
        if returncode not in accepted:
            detail = (
                f"{command[0]} returned protected error output"
                if sensitive_output
                else next(
                    (line.strip() for line in (stderr or stdout).splitlines() if line.strip()),
                    f"{command[0]} exited {returncode}",
                )
            )
            raise InstallerError(f"{command[0]} failed: {detail[:500]}")
        return result

    @staticmethod
    def _environment() -> dict[str, str]:
        allowed = {
            "PATH",
            "HOME",
            "KUBECONFIG",
            "LANG",
            "LC_ALL",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "HELM_CACHE_HOME",
            "HELM_CONFIG_HOME",
            "HELM_DATA_HOME",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "NO_PROXY",
            "https_proxy",
            "http_proxy",
            "no_proxy",
        }
        return {key: value for key, value in os.environ.items() if key in allowed}


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def ensure_private_directory(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise PreconditionError(f"private directory must not be a symlink: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PreconditionError(f"private directory permissions are too broad: {path}")


def require_private_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise PreconditionError(f"protected input must be a regular file: {path}")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PreconditionError(f"protected input permissions are too broad: {path}")


def atomic_private_write(path: Path, value: str, *, overwrite: bool = True) -> None:
    ensure_private_directory(path.parent)
    if path.exists() and path.is_symlink():
        raise PreconditionError(f"refusing to replace symlink: {path}")
    if path.exists() and not overwrite:
        raise PreconditionError(f"refusing to overwrite protected artifact: {path}")
    temporary = path.parent / f".{path.name}.{os.getpid()}.next"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_private_json(path: Path, payload: object, *, overwrite: bool = True) -> None:
    atomic_private_write(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        overwrite=overwrite,
    )


@contextmanager
def local_lock(state_dir: Path) -> Iterator[None]:
    ensure_private_directory(state_dir)
    lock_path = state_dir / "installer.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PreconditionError("another local installer process holds the state lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def safe_identifier(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._:-]", "_", value)[:255]
