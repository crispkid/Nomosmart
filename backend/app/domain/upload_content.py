"""Byte-exact upload sources. Disk sources deliberately have no bytes shortcut."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from io import BytesIO, RawIOBase
import os
from time import monotonic
from typing import BinaryIO, Iterator

from app.core.errors import AppError


class UploadContent:
    size: int
    sha256: str
    chunk_size: int = 64 * 1024
    deadline: float | None = None

    def check_deadline(self) -> None:
        if self.deadline is not None and monotonic() >= self.deadline:
            raise AppError("upload_receive_timeout", "Upload deadline exceeded", status_code=408)

    @contextmanager
    def open(self) -> Iterator[BinaryIO]:
        raise NotImplementedError
        yield  # pragma: no cover

    def chunks(self) -> Iterator[bytes]:
        with self.open() as reader:
            while True:
                self.check_deadline()
                block = reader.read(self.chunk_size)
                if not block:
                    break
                yield block

    def prefix(self, length: int) -> bytes:
        with self.open() as reader:
            return reader.read(length)


class BytesContent(UploadContent):
    def __init__(self, value: bytes) -> None:
        self.value = value
        self.size = len(value)
        self.sha256 = hashlib.sha256(value).hexdigest()

    @contextmanager
    def open(self) -> Iterator[BinaryIO]:
        with BytesIO(self.value) as reader:
            yield reader


class _SliceReader(RawIOBase):
    """Independent seek cursor without duplicating/closing the owning scratch FD."""
    def __init__(self, source: DiskContent) -> None:
        self.source = source
        self.position = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        position = offset + (self.position if whence == os.SEEK_CUR else self.source.size if whence == os.SEEK_END else 0)
        if whence not in (os.SEEK_SET, os.SEEK_CUR, os.SEEK_END) or position < 0:
            raise ValueError("Invalid seek")
        self.position = position
        return position

    def read(self, size: int = -1) -> bytes:
        self._checkClosed()
        self.source.check_deadline()
        if not self.source.available:
            raise AppError("upload_too_large", "Uploaded file exceeds the limit", status_code=413)
        remaining = max(0, self.source.size - self.position)
        length = remaining if size < 0 else min(size, remaining)
        # Consumers must request bounded reads. ZIP directory reads are separately bounded.
        if length > 4 * 1024 * 1024:
            raise AppError("invalid_file_signature", "Unbounded upload read is not supported", status_code=422)
        result = os.pread(self.source.fd, length, self.source.offset + self.position)
        if len(result) != length:
            raise AppError("upload_temporary_storage_unavailable", "Upload storage is unavailable", status_code=503)
        self.position += len(result)
        return result

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


@dataclass(frozen=True)
class DiskContent(UploadContent):
    fd: int
    offset: int
    size: int
    sha256: str
    chunk_size: int = 64 * 1024
    deadline: float | None = None
    available: bool = True

    @contextmanager
    def open(self) -> Iterator[BinaryIO]:
        with _SliceReader(self) as reader:
            yield reader


def as_content(value: bytes | UploadContent) -> UploadContent:
    return BytesContent(value) if isinstance(value, bytes) else value
