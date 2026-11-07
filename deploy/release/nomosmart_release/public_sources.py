"""Explicit, content-bound public inputs; reject unknown paths before opening them."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

DENIED_PARTS = frozenset({
    '.git', '.operator', '.artifacts', '.local-secrets', '.secrets', 'secrets',
    'generated', 'runtime', 'node_modules', '.next', '.next-dev', '.venv', 'venv',
    '__pycache__', '.pytest_cache', 'coverage', 'test-results', 'output', 'artifacts', '.cache',
})
MAX_BYTES = 64 * 1024 * 1024


class SourceBoundaryError(RuntimeError):
    """Only a stable code, never file contents or a detected secret."""


def relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise SourceBoundaryError('source_path_invalid')
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(p in {'', '.', '..'} for p in path.parts):
        raise SourceBoundaryError('source_path_invalid')
    if any(p.lower() in DENIED_PARTS for p in path.parts):
        raise SourceBoundaryError('source_private_path_denied')
    name = path.name.lower()
    if (((name.startswith('.env') or name.endswith('.env') or '.env.' in name) and not name.endswith('.example'))
            or name in {'connection.py', 'credentials.json', 'kubeconfig', 'id_rsa', 'id_ed25519'}
            or name.startswith('.coverage') or path.suffix.lower() in {'.key', '.pem', '.pfx', '.p12'}):
        raise SourceBoundaryError('source_private_file_denied')
    return path


def _read(root: Path, relative: PurePosixPath) -> tuple[bytes, os.stat_result]:
    """Open every ancestor without following symlinks, including a racing leaf."""
    directory = None
    descriptor = None
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= MAX_BYTES:
            raise SourceBoundaryError('source_file_identity_denied')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(MAX_BYTES + 1)
        after = os.fstat(descriptor)
        if (len(data) != before.st_size or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns or before.st_ctime_ns != after.st_ctime_ns):
            raise SourceBoundaryError('source_changed_during_read')
        return data, before
    except OSError:
        raise SourceBoundaryError('source_file_unavailable_or_symlink') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


@dataclass(frozen=True)
class PublicSourceInventory:
    root: Path
    files: dict[str, dict]

    @classmethod
    def freeze(cls, root: Path, approved_paths: list[str]) -> 'PublicSourceInventory':
        if not root.is_absolute() or root.is_symlink() or not root.is_dir() or root.resolve() != root:
            raise SourceBoundaryError('source_root_invalid')
        if not approved_paths or len(approved_paths) != len(set(approved_paths)):
            raise SourceBoundaryError('source_inventory_invalid')
        # Validate the complete requested list before reading even its first file.
        paths = [relative_path(path) for path in approved_paths]
        files = {}
        for path in sorted(paths):
            data, details = _read(root, path)
            files[path.as_posix()] = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
                                     'executable': bool(details.st_mode & 0o111)}
        return cls(root, files)

    @classmethod
    def load(cls, root: Path, path: Path, *, expected_sha256: str) -> 'PublicSourceInventory':
        if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077
                or path.stat().st_uid != os.getuid() or path.resolve() != path
                or path.parent.stat().st_mode & 0o077):
            raise SourceBoundaryError('source_inventory_private_file_required')
        body, identity = _read(path.parent, PurePosixPath(path.name))
        if identity.st_uid != os.getuid() or identity.st_mode & 0o077 or len(body) > 8 * 1024 * 1024:
            raise SourceBoundaryError('source_inventory_private_file_required')
        if hashlib.sha256(body).hexdigest() != expected_sha256:
            raise SourceBoundaryError('source_inventory_digest_mismatch')
        data = json.loads(body)
        if set(data) != {'version', 'source_root', 'files'} or data['version'] != 1 or data['source_root'] != str(root):
            raise SourceBoundaryError('source_inventory_identity_mismatch')
        if not isinstance(data['files'], dict) or not data['files']:
            raise SourceBoundaryError('source_inventory_invalid')
        for name, row in data['files'].items():
            relative_path(name)
            if (not isinstance(row, dict) or set(row) != {'sha256', 'size', 'executable'}
                    or not isinstance(row['sha256'], str) or len(row['sha256']) != 64
                    or any(c not in '0123456789abcdef' for c in row['sha256'])
                    or type(row['size']) is not int or not 0 <= row['size'] <= MAX_BYTES
                    or type(row['executable']) is not bool):
                raise SourceBoundaryError('source_inventory_entry_invalid')
        if not root.is_absolute() or root.is_symlink() or not root.is_dir() or root.resolve() != root:
            raise SourceBoundaryError('source_root_invalid')
        return cls(root, data['files'])

    def manifest(self) -> dict:
        return {'version': 1, 'source_root': str(self.root), 'files': self.files}

    def read(self, name: str) -> tuple[bytes, bool]:
        # This membership check intentionally precedes path metadata and opening.
        if name not in self.files:
            raise SourceBoundaryError('source_not_in_approved_inventory')
        path = relative_path(name)
        data, details = _read(self.root, path)
        expected = self.files[name]
        if (len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']
                or bool(details.st_mode & 0o111) != expected['executable']):
            raise SourceBoundaryError('source_content_drift')
        return data, expected['executable']

    def copy_to(self, destination: Path) -> None:
        parent = destination.parent
        if (not parent.is_absolute() or parent.is_symlink() or parent.resolve() != parent
                or parent.stat().st_mode & 0o077 or parent.stat().st_uid != os.getuid()):
            raise SourceBoundaryError('source_destination_private_parent_required')
        destination.mkdir(mode=0o700)
        for name in sorted(self.files):
            data, executable = self.read(name)
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with target.open('xb') as stream:
                target.chmod(0o700 if executable else 0o600)
                stream.write(data)
