"""Private Worker staging only; no runtime access or recovery result adoption."""
from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import stat
import sys
from uuid import uuid4

from app.domain.local_pdf.errors import need


def _private_directory(meta):
    # fsGroup volumes propagate setgid; it grants no group/other access here.
    need(stat.S_ISDIR(meta.st_mode) and meta.st_uid == os.getuid()
         and stat.S_IMODE(meta.st_mode) in {0o700, 0o2700}, "runtime_unavailable")


def _open_directory(path):
    need(path.is_absolute() and ".." not in path.parts, "runtime_unavailable")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class PageStore:
    def __init__(self, root, *, deferred=False):
        path = Path(root)
        self.root_path = path
        self.root = None
        self.path = path / ("pdf-" + str(uuid4()))
        self.fd = None
        self.identity = None
        self.created = False
        self.open_attempted = False
        self.name = self.path.name
        self.pages = []
        self.names = set()
        self.bytes = 0
        self.cleanup_confirmed = False
        self.cleanup_failed = False
        if not deferred:
            try:
                self.open()
            except BaseException:
                try:
                    self.close()
                except BaseException:
                    pass  # Keep the original failure; no caller adopts this object.
                raise

    def open(self):
        """Allocate after the owner records this object, so partial setup is visible."""
        need(not self.open_attempted and not self.cleanup_confirmed, "runtime_unavailable")
        self.open_attempted = True
        self.root = _open_directory(self.root_path)
        _private_directory(os.fstat(self.root))
        self.created = None  # An interrupted creation is not proof of absence.
        try:
            os.mkdir(self.name, mode=0o700, dir_fd=self.root)
        except OSError as error:
            if error.errno != errno.EINTR:
                self.created = False
            raise
        self.created = True
        meta = os.stat(self.name, dir_fd=self.root, follow_symlinks=False)
        _private_directory(meta)
        self.identity = (meta.st_dev, meta.st_ino)
        self.fd = os.open(self.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.root)
        opened = os.fstat(self.fd)
        _private_directory(opened)
        need((opened.st_dev, opened.st_ino) == self.identity, "runtime_unavailable")

    def _check_identity(self):
        need(self.identity is not None, "cleanup_unconfirmed")
        meta = os.stat(self.name, dir_fd=self.root, follow_symlinks=False)
        _private_directory(meta)
        need((meta.st_dev, meta.st_ino) == self.identity, "runtime_unavailable")
        if self.fd is not None:
            opened = os.fstat(self.fd)
            need((opened.st_dev, opened.st_ino) == self.identity, "runtime_unavailable")

    def _close_descriptors(self):
        pending_error = sys.exc_info()[0] is not None
        failure = None
        for attribute in ("fd", "root"):
            descriptor = getattr(self, attribute)
            if descriptor is not None:
                setattr(self, attribute, None)
                try:
                    os.close(descriptor)
                except OSError as error:
                    failure = failure or error
        if failure is not None:
            self.cleanup_failed = True
            self.cleanup_confirmed = False
            if not pending_error:
                raise failure

    def stage(self, number, body, *, page_limit, total_limit):
        need(number == len(self.pages) + 1 and len(body) <= page_limit
             and self.bytes + len(body) <= total_limit, "output_limit")
        name = f"page-{number:06}.bin"
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        self.names.add(name)
        with os.fdopen(fd, "wb") as stream:
            need(stream.write(body) == len(body), "runtime_unavailable")
            stream.flush()
            os.fsync(stream.fileno())
        self.pages.append((name, len(body), hashlib.sha256(body).hexdigest()))
        self.bytes += len(body)

    def read(self, number):
        name, length, digest = self.pages[number - 1]
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            need(stat.S_ISREG(meta.st_mode) and stat.S_IMODE(meta.st_mode) == 0o600
                 and meta.st_uid == os.getuid() and meta.st_nlink == 1 and meta.st_size == length, "invalid_output")
            body = stream.read(length + 1)
            need(len(body) == length and hashlib.sha256(body).hexdigest() == digest, "invalid_output")
            return body

    def close(self):
        need(not self.cleanup_failed, "cleanup_unconfirmed")
        if self.cleanup_confirmed:
            return
        try:
            need(self.created is not None, "cleanup_unconfirmed")
            if not self.created:
                self.cleanup_confirmed = True
                return
            self._check_identity()
            if self.fd is None:
                # mkdir succeeded but opening it failed. rmdir succeeds only if empty;
                # never enumerate/delete unknown children through an unverified path.
                os.rmdir(self.name, dir_fd=self.root)
                self.cleanup_confirmed = True
                return
            need(set(os.listdir(self.fd)) == self.names, "runtime_unavailable")
            for name in tuple(self.names):
                meta = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
                need(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid()
                     and meta.st_nlink == 1, "runtime_unavailable")
                os.unlink(name, dir_fd=self.fd)
                self.names.remove(name)
            self._check_identity()
            os.rmdir(self.name, dir_fd=self.root)
            self.cleanup_confirmed = True
        except BaseException:
            self.cleanup_failed = True
            raise
        finally:
            self._close_descriptors()


def ensure_root(root):
    """Create only the configured leaf under an existing, nonsymlink parent."""
    path = Path(root)
    need(path.is_absolute() and ".." not in path.parts, "runtime_unavailable")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        try:
            os.mkdir(path.name, mode=0o700, dir_fd=descriptor)
        except FileExistsError:
            pass
        leaf = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
        try:
            _private_directory(os.fstat(leaf))
        finally:
            os.close(leaf)
    finally:
        os.close(descriptor)


class Workspace(PageStore):
    """Exact-owned parser scratch, separate from document-owned result pages."""
    def target(self, name):
        need(name in {"input.pdf", "text.txt", "raster.png"} or
             (name.startswith("split-") and name.endswith(".pdf") and name[6:-4].isdigit()))
        self.names.add(name)
        return str(self.path / name)

    def write_input(self, body):
        self.target("input.pdf")
        fd = os.open("input.pdf", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        with os.fdopen(fd, "wb") as stream:
            need(stream.write(body) == len(body), "runtime_unavailable")

    def read_file(self, name, maximum):
        need(name in self.names)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(fd)
            need(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and meta.st_nlink == 1
                 and meta.st_size <= maximum, "output_limit")
            body = stream.read(maximum + 1)
            need(len(body) == meta.st_size, "invalid_output")
            return body

    def usage(self):
        actual = set(os.listdir(self.fd))
        need(actual <= self.names, "invalid_output")
        size = 0
        for name in actual:
            meta = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            need(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and meta.st_nlink == 1, "invalid_output")
            size += meta.st_size
        return size

    def discard(self, name):
        if name in os.listdir(self.fd):
            self.usage()
            os.unlink(name, dir_fd=self.fd)
        self.names.discard(name)

    def close(self):
        if self.fd is not None:
            try:
                self._check_identity()
                self.usage()
            except BaseException:
                # Preserve unknown content, but do not leak Worker descriptors.
                self.cleanup_failed = True
                self._close_descriptors()
                raise
            # Tools may fail before producing a pre-registered output.
            self.names.intersection_update(os.listdir(self.fd))
        super().close()
