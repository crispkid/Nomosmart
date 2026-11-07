"""Admission and lifetime of one authenticated HTTP upload (not a PDF worker)."""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import stat
import tempfile
from threading import Lock
from time import monotonic

import anyio
from starlette.requests import Request
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import AppError

_lock = Lock()
_inflight = 0
_reserved = 0
_MARGIN = 16 * 1024 * 1024


def storage_error() -> AppError:
    return AppError("upload_temporary_storage_unavailable", "Upload temporary storage is unavailable", status_code=503)


def _disk_directory(path: str) -> int:
    """Use an owned private child of the disk mount, rejecting symlinks/tmpfs."""
    directory = Path(path)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        # fsGroup may propagate setgid; 02700 still grants no group/other access.
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) not in {0o700, 0o2700}):
            raise storage_error()
        mounts = Path('/proc/self/mountinfo')
        if mounts.exists():
            resolved = str(directory.resolve())
            match = ('', '')
            for line in mounts.read_text().splitlines():
                fields, fs = line.split(' - ', 1)
                mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields.split()[4])
                if (resolved == mount or resolved.startswith(mount.rstrip('/') + '/')) and len(mount) >= len(match[0]):
                    match = (mount, fs.split()[0])
            if not match[0] or match[1] in {'tmpfs', 'ramfs'}:
                raise storage_error()
        return fd
    except BaseException:
        os.close(fd)
        raise


class UploadLease:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.deadline = monotonic() + settings.upload_total_timeout_seconds
        self.file = None
        self.written = 0
        self.admitted = False

    def open(self) -> None:
        global _inflight, _reserved
        with _lock:
            if _inflight >= self.settings.upload_max_inflight:
                raise AppError("upload_capacity_exhausted", "Upload capacity is busy", status_code=503)
            if _reserved + self.settings.upload_request_max_bytes + _MARGIN > self.settings.upload_scratch_max_mib * 1024 * 1024:
                raise storage_error()
            _inflight += 1
            _reserved += self.settings.upload_request_max_bytes
            self.admitted = True
        try:
            fd = _disk_directory(self.settings.upload_scratch_dir)
            try:
                free = os.fstatvfs(fd)
                with _lock:
                    if free.f_bavail * free.f_frsize < _reserved + _MARGIN:
                        raise storage_error()
                # O_TMPFILE/unlinked temporary file: never keyed by the original filename.
                self.file = tempfile.TemporaryFile(dir=self.settings.upload_scratch_dir, buffering=0)
                os.fchmod(self.file.fileno(), 0o600)
            finally:
                os.close(fd)
        except BaseException:
            self.close()
            raise

    def write(self, block: bytes) -> None:
        if monotonic() >= self.deadline:
            raise AppError("upload_receive_timeout", "Upload deadline exceeded", status_code=408)
        if self.written + len(block) > self.settings.upload_request_max_bytes:
            raise storage_error()
        free = os.fstatvfs(self.file.fileno())
        if free.f_bavail * free.f_frsize < len(block) + _MARGIN:
            raise storage_error()
        if self.file.write(block) != len(block):
            raise storage_error()
        self.written += len(block)

    def close(self) -> None:
        global _inflight, _reserved
        try:
            if self.file is not None:
                self.file.close()
                self.file = None
        finally:
            with _lock:
                if self.admitted:
                    _inflight -= 1
                    _reserved -= self.settings.upload_request_max_bytes
                    self.admitted = False


@asynccontextmanager
async def receive_upload(request: Request):
    """Caller MUST authorize and validate required keys before entering."""
    from app.domain.multipart_upload import StreamingMultipart

    settings = request.app.state.settings
    lease = UploadLease(settings)
    try:
        await run_in_threadpool(lease.open)
        parser = StreamingMultipart(request.headers.get('content-type', ''), lease)
        received = 0
        iterator = request.stream().__aiter__()
        while True:
            remaining = lease.deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                with anyio.fail_after(min(remaining, settings.upload_idle_timeout_seconds)):
                    block = await anext(iterator)
            except StopAsyncIteration:
                break
            received += len(block)
            if received > settings.upload_request_max_bytes:
                raise AppError("upload_request_too_large", "Upload request exceeds the limit", status_code=413)
            # ASGI chunks are transport-owned. Feed bounded copies; never concatenate them.
            for start in range(0, len(block), settings.upload_io_chunk_kib * 1024):
                await run_in_threadpool(parser.write, block[start:start + settings.upload_io_chunk_kib * 1024])
        payload = await run_in_threadpool(parser.finish)
        yield payload
    except TimeoutError as exc:
        raise AppError("upload_receive_timeout", "Upload receive timed out", status_code=408) from exc
    except OSError as exc:
        raise storage_error() from exc
    finally:
        # Threadpool calls are shielded until completion; no FD closed under an S3 read.
        with anyio.CancelScope(shield=True):
            await run_in_threadpool(lease.close)
