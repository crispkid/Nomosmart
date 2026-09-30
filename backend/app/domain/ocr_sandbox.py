"""Credential-free parser namespace and bounded process lifetime (ACFIX-018).

Only operator-selected immutable runtime assets and explicitly named per-call
input/output files enter the namespace. Never fall back to an unsandboxed parser.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
import resource
import re
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
from time import perf_counter

from app.core.config import Settings
from app.core.errors import AppError


# These are security-policy roots, not implicit mounts. Every asset must still
# be explicitly configured, present, immutable and checked for nested mounts.
_FILE_ROOTS = tuple(Path(p) for p in ("/usr/bin", "/usr/lib", "/lib", "/lib64"))
_DATA_ROOTS = tuple(Path(p) for p in (
    "/usr/share/fonts", "/usr/share/fontconfig", "/etc/fonts",
    "/usr/share/poppler", "/usr/share/tesseract-ocr",
))


def _startup_diagnostic(stderr: bytes, return_code: int, *,
                        mounts: list[tuple[Path, Path]], root: Path,
                        inputs: tuple[Path, ...], outputs: tuple[Path, ...]) -> dict:
    """Opt-in internal diagnostics: never return arbitrary parser/document text.

    A bounded prefix is matched against a closed vocabulary, not an arbitrary
    bwrap-prefixed string. Paths must be fixed system targets or validated assets.
    Unknown messages retain only length/hash. No general application logging.
    """
    limit = 4096
    prefix = stderr[:limit]
    targets = {"/": "/", "/proc": "/proc", "/proc/sys/user/max_user_namespaces": "/proc/sys/user/max_user_namespaces",
               "/proc/sys/kernel/overflowuid": "/proc/sys/kernel/overflowuid", "/proc/sys/kernel/overflowgid": "/proc/sys/kernel/overflowgid",
               "/dev": "/dev", "/dev/pts": "/dev/pts", "/dev/shm": "/dev/shm", "/dev/ptmx": "/dev/ptmx",
               "/newroot": "/newroot", "/tmp": "/tmp", "/work": "/work", str(root): "<work>"}
    for index, pair in enumerate(mounts):
        for path in pair:
            targets[str(path)] = f"<runtime:{index}>"
    for label, paths in (("input", inputs), ("output", outputs)):
        for index, path in enumerate(paths):
            targets[str(path)] = targets["/work/" + path.name] = f"<{label}:{index}>"
    errors = ("Operation not permitted", "Permission denied", "Read-only file system",
              "No such file or directory", "Invalid argument", "File exists", "Not a directory", "No space left on device")
    # Include bwrap's fixed newroot aliases, never arbitrary path descendants.
    for target, label in tuple(targets.items()):
        if target.startswith("/"):
            targets["/newroot" + target] = label
            targets["/oldroot" + target] = label
    operations = ("cannot open", "Can't open", "Can't read", "Can't chdir to", "execvp",
                  "Can't bind mount", "Can't find source path", "Can't mkdir", "Can't remount",
                  "Can't mkdir parents for", "Can't create file at", "Can't create file",
                  "Can't remount readonly on", "Can't mount proc on", "Can't mount tmpfs on",
                  "Can't mount devpts on", "Can't access")
    fixed = ("Creating new namespace failed", "pivot_root", "pivot_root(/newroot)", "unmount old root",
             "umount old root", "unshare user ns", "unshare pid ns", "Setting userns2 failed",
             "Creating newroot failed", "Creating oldroot failed", "sysctl user.max_user_namespaces = 1")
    permitted = {}
    for error in errors:
        for operation in fixed:
            message = f"bwrap: {operation}: {error}"
            permitted[message] = message
        for operation in operations:
            for target, label in targets.items():
                permitted[f"bwrap: {operation} {target}: {error}"] = f"bwrap: {operation} {label}: {error}"
    messages = []
    # bwrap versions add punctuation/qualifiers to these operations. Keep a
    # closed vocabulary fallback, not arbitrary startup prose or unknown paths.
    vocabulary = set(" ".join((*operations, *fixed, *errors,
        "bwrap Failed failed Unable unable to on from source destination mounting bind remount mount file directory parents create make slave readonly read-only tmpfs proc devpts device setup namespace ns user pid filesystem Too many levels of symbolic links No such device Cannot allocate memory Error error resolving symlink")).translate(str.maketrans({c: " " for c in ":'\"(),"})).split())
    for line in prefix.decode("utf-8", errors="replace").splitlines():
        clean = "".join(char for char in line if char.isprintable())
        if clean in permitted:
            messages.append(permitted[clean])
        elif clean.startswith("bwrap: "):
            labels = {}
            def replace_path(match):
                path = match.group(0)
                if path not in targets:
                    return "UNRECOGNIZED_PATH"
                key = f"PATHLABEL{len(labels)}"
                labels[key] = targets[path]
                return key
            safe = re.sub(r"/[^\s:'\"(),]+|/(?=[\s:'\"(),]|$)", replace_path, clean)
            words = safe.translate(str.maketrans({c: " " for c in ":'\"(),"})).split()
            if words and all(word in vocabulary or word in labels for word in words):
                for key, label in labels.items():
                    safe = safe.replace(key, label)
                messages.append(safe)
    messages = list(dict.fromkeys(messages))[:8]
    classification = "UNKNOWN"
    if messages:
        if any("/proc/sys/" in line or "user.max_user_namespaces" in line for line in messages):
            classification = "USER_NAMESPACE_CONTROL_UNAVAILABLE"
        elif any("not permitted" in line or "Permission denied" in line for line in messages):
            classification = "PERMISSION_DENIED"
        else:
            classification = "BWRAP_STARTUP_ERROR"
    elif return_code == 0 and not stderr:
        classification = "NO_STDERR"
    return {"stage": "sandbox_process_exit", "return_code": return_code,
            "classification": classification, "stderr_length": len(stderr),
            "stderr_sha256": sha256(stderr).hexdigest(), "prefix_bytes": len(prefix),
            "truncated": len(stderr) > limit, "messages": messages}


def _unavailable() -> AppError:
    return AppError("ocr_tesseract_runtime_unavailable", "OCR sandbox runtime configuration is unavailable", status_code=503)


def _process_error(error_code: str, return_code: int, stderr: bytes) -> AppError:
    if b"bwrap:" in stderr and any(value in stderr.lower() for value in
            (b"operation not permitted", b"permission denied", b"no permissions")):
        return AppError("ocr_sandbox_permission_denied", "OCR sandbox cannot start under the current runtime permissions", status_code=503)
    if error_code == "ocr_tesseract_runtime_unavailable":
        return _unavailable()
    return AppError(error_code, "Tesseract could not process the document", status_code=422,
                    details={"return_code": return_code})


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == base or base in path.parents for base in roots)


def runtime_mounts(paths: list[str]) -> list[tuple[Path, Path]]:
    """Validate destinations AND canonical targets; return only explicit mounts."""
    if not paths or len(paths) > 512:
        raise _unavailable()
    try:
        # Do not inspect mount payloads. An injected volume below /usr/share or
        # /lib must not inherit permission merely from its location.
        mounts = []
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            value = line.split()[4]
            for escape, char in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
                value = value.replace(escape, char)
            if value != "/":
                mounts.append(Path(value))
        pairs: set[tuple[Path, Path]] = set()
        for value in paths:
            requested = Path(value)
            if not requested.is_absolute() or ".." in requested.parts or str(requested) != value:
                raise _unavailable()
            canonical = requested.resolve(strict=True)
            for path in (requested, canonical):
                if not (_within(path, _DATA_ROOTS) or
                        (_within(path, _FILE_ROOTS) and path.is_file())):
                    raise _unavailable()
                if any(mount == path or mount in path.parents or path in mount.parents for mount in mounts):
                    raise _unavailable()
            # No recursive mount of executable/library trees. Directory assets
            # have a bounded walk, with symlinks checked rather than followed.
            pending = [canonical]
            count = 0
            while pending:
                item = pending.pop()
                count += 1
                if count > 20000:
                    raise _unavailable()
                attrs = item.lstat()
                if stat.S_ISLNK(attrs.st_mode):
                    target = item.resolve(strict=True)
                    if not _within(target, _DATA_ROOTS):
                        raise _unavailable()
                    target_attrs = target.stat()
                    if target_attrs.st_uid != 0 or target_attrs.st_mode & 0o022:
                        raise _unavailable()
                elif not (stat.S_ISREG(attrs.st_mode) or stat.S_ISDIR(attrs.st_mode)):
                    raise _unavailable()
                elif attrs.st_uid != 0 or attrs.st_mode & 0o022:
                    raise _unavailable()
                elif stat.S_ISDIR(attrs.st_mode):
                    pending.extend(item.iterdir())
            # Parent directories may not be replaceable by the application UID.
            for parent in canonical.parents:
                attrs = parent.stat()
                if attrs.st_uid != 0 or attrs.st_mode & 0o022:
                    raise _unavailable()
            pairs.add((canonical, requested))
            pairs.add((canonical, canonical))
        return sorted(pairs, key=lambda pair: (len(pair[1].parts), str(pair[1])))
    except (OSError, ValueError, RuntimeError) as exc:
        raise _unavailable() from exc


def _limits(settings: Settings, file_limit: int) -> None:
    memory = settings.tesseract_max_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (settings.tesseract_timeout_seconds, settings.tesseract_timeout_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))


def collect_bounded(process: subprocess.Popen, *, deadline: float, output_limit: int) -> tuple[bytes, bytes]:
    """Drain both pipes without unbounded communicate(); always reap our group.

    Caller must create a new session. No parser is launched by this helper.
    The bubblewrap PID namespace also kills descendants that change their PGID.
    """
    streams = (process.stdout, process.stderr)
    chunks: list[list[bytes]] = [[], []]
    total = 0
    try:
        with selectors.DefaultSelector() as selector:
            for index, stream in enumerate(streams):
                assert stream is not None
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, index)
            while selector.get_map() or process.poll() is None:
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    raise AppError("ocr_tesseract_timeout", "Tesseract exceeded its time limit", status_code=503)
                for key, _ in selector.select(min(remaining, 0.1)):
                    data = os.read(key.fd, min(65536, output_limit - total + 1))
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(data)
                    if total > output_limit:
                        raise AppError("ocr_tesseract_output_limit", "Tesseract output exceeds the safe limit", status_code=422)
                    chunks[key.data].append(data)
            process.wait(timeout=max(0.01, deadline - perf_counter()))
        return b"".join(chunks[0]), b"".join(chunks[1])
    finally:
        # PID is the leader of our dedicated session; no parent/shared PGID.
        # Kill even after the leader exits, to reclaim pipe-holding descendants.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        for stream in streams:
            if stream is not None:
                stream.close()


def run_ocr_sandbox(
    settings: Settings, root: Path, command: list[str], *, deadline: float,
    error_code: str, input_paths: tuple[Path, ...] = (), output_paths: tuple[Path, ...] = (),
    diagnostic_sink: Callable[[dict], None] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if deadline <= perf_counter():
        raise AppError("ocr_tesseract_timeout", "Tesseract exceeded its time limit", status_code=503)
    created: list[Path] = []
    success = False
    try:
        mounts = runtime_mounts(settings.tesseract_sandbox_read_only_paths)
        root = root.resolve(strict=True)
        attrs = root.stat()
        if not root.is_dir() or attrs.st_uid != os.getuid() or attrs.st_mode & 0o077 or os.getuid() == 0:
            raise _unavailable()
        if len(output_paths) > settings.tesseract_max_pages or len(set(input_paths + output_paths)) != len(input_paths + output_paths):
            raise _unavailable()
        sandbox = shlex.split(settings.tesseract_sandbox_command)
        if len(sandbox) != 1 or not command:
            raise _unavailable()
        bwrap = shutil.which(sandbox[0], path=os.defpath)
        executable = shutil.which(command[0], path=os.defpath)
        if not bwrap or not executable or not os.access(executable, os.X_OK):
            raise _unavailable()
        executable = str(Path(executable).resolve(strict=True))
        if Path(executable) not in {source for source, _ in mounts}:
            raise _unavailable()
        budget = settings.max_upload_size_mb * 1024 * 1024 * 4
        arguments = [bwrap, "--unshare-user", "--uid", str(os.getuid()), "--gid", str(os.getgid()),
            "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts", "--disable-userns",
            "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv"]
        environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": "/tmp", "TMPDIR": "/tmp"}
        for key, value in environment.items():
            arguments += ["--setenv", key, value]
        for source, destination in mounts:
            arguments += ["--ro-bind", str(source), str(destination)]
        arguments += ["--dev", "/dev", "--proc", "/proc", "--remount-ro", "/proc",
            "--size", str(budget), "--tmpfs", "/tmp", "--dir", "/work"]
        for path in input_paths:
            attrs = path.lstat()
            if path.parent != root or not stat.S_ISREG(attrs.st_mode) or path.resolve(strict=True) != path:
                raise _unavailable()
            arguments += ["--ro-bind", str(path), "/work/" + path.name]
        for path in output_paths:
            if path.parent != root or path.name in {"", ".", ".."}:
                raise _unavailable()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            created.append(path)
            arguments += ["--bind", str(path), "/work/" + path.name]
        args = [executable, *command[1:]]
        args = ["/work/" + value[len(str(root)) + 1:] if value.startswith(str(root) + "/") else value for value in args]
        arguments += ["--chdir", "/work", "--remount-ro", "/", "--", *args]
        process = subprocess.Popen(arguments, cwd=root, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, start_new_session=True,
            preexec_fn=lambda: _limits(settings, max(1, budget // max(1, len(output_paths)))))
        stdout, stderr = collect_bounded(process, deadline=deadline, output_limit=budget)
        if diagnostic_sink is not None:
            # Child is already reaped. A broken diagnostic consumer must neither
            # hide the real result nor prevent failed-output cleanup in finally.
            try:
                diagnostic_sink(_startup_diagnostic(stderr, process.returncode,
                    mounts=mounts, root=root, inputs=input_paths, outputs=output_paths))
            except Exception:
                pass
        if process.returncode != 0:
            raise _process_error(error_code, process.returncode, stderr)
        success = True
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise _unavailable() from exc
    finally:
        if not success:
            for path in created:
                path.unlink(missing_ok=True)
