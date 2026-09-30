"""Content and registry boundaries for NomoSmart-owned publication artifacts.

These checks establish ownership scope, not runtime compatibility or CVE status.
Official peripheral downloads are installation inputs, never publication targets.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Final, Iterable
import zipfile

from .contract import ReleaseContractError


APPLICATION_REPOSITORIES: Final[dict[str, str]] = {
    "frontend": "ghcr.io/crispkid/nomosmart/frontend",
    "backend": "ghcr.io/crispkid/nomosmart/backend",
}
# Exact existing application-library exceptions. A new wheel needs a reviewed
# source change; renaming a peripheral archive into vendor/ does not allow it.
VENDOR_WHEELS: Final[dict[str, str]] = {
    "backend/vendor/anyio/anyio-4.14.2+nomosmart.1-py3-none-any.whl":
        "c281016d17e53b15e0e866bfb4818290223eec5c4493d078b00d70c43eb0226d",
    "backend/vendor/anyio/4.14.2+nomosmart.2/anyio-4.14.2+nomosmart.2-py3-none-any.whl":
        "be38c4b59b4129d0f4c8a2e42a868faa4cfe7781a3d560da2e2f0e7625a58e3a",
    "backend/vendor/python-multipart/0.0.32+nomosmart.1/python_multipart-0.0.32+nomosmart.1-py3-none-any.whl":
        "50ea368e317d8db958a2714fc643e1aa57fc6bd310c41d4bb9de42388b1e8f5c",
}
MAX_FILE_BYTES: Final[int] = 64 * 1024 * 1024
MAX_WHEEL_EXPANDED_BYTES: Final[int] = 16 * 1024 * 1024
PROHIBITED_SUFFIXES: Final[tuple[str, ...]] = (
    ".tar", ".tgz", ".gz", ".bz2", ".xz", ".zst", ".zip", ".jar", ".war",
    ".whl", ".7z", ".rar", ".rpm", ".deb", ".apk", ".exe", ".dll", ".so",
    ".dylib", ".bin", ".iso", ".oci",
)
PROHIBITED_MAGIC: Final[tuple[bytes, ...]] = (
    b"\x7fELF", b"MZ", b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08",
    b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00", b"\x28\xb5\x2f\xfd",
    b"7z\xbc\xaf\x27\x1c", b"Rar!", b"!<arch>\n", b"\xed\xab\xee\xdb",
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
)
IMAGE_MAGIC: Final[dict[str, tuple[bytes, ...]]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".ico": (b"\x00\x00\x01\x00",),
}


def _relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value or path.is_absolute() or path.as_posix() != value
        or any(part in {".", "..", ""} for part in value.split("/"))
        or "\\" in value or any(ord(char) < 32 for char in value)
    ):
        raise ReleaseContractError("publication path is not canonical and relative")
    return path


def _regular_file(root: Path, relative: str) -> Path:
    path = _relative_path(relative)
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseContractError(f"publication contains a symlink: {relative}")
    if not current.is_file() or not stat.S_ISREG(current.stat().st_mode):
        raise ReleaseContractError(f"publication file is missing or not regular: {relative}")
    if current.stat().st_size > MAX_FILE_BYTES:
        raise ReleaseContractError(f"publication file exceeds review bound: {relative}")
    return current


def _source_content(relative: str, content: bytes) -> None:
    lowered = relative.lower()
    if (
        lowered.endswith(PROHIBITED_SUFFIXES)
        or content.startswith(PROHIBITED_MAGIC)
        or content[257:262] == b"ustar"
    ):
        raise ReleaseContractError(f"software binary/archive is outside publication scope: {relative}")
    suffix = PurePosixPath(relative).suffix.lower()
    if suffix in IMAGE_MAGIC:
        # Existing design assets include a JPEG stored with a .png extension.
        # Identify approved raster content by bytes, not by its filename alone.
        if not content.startswith(tuple(magic for values in IMAGE_MAGIC.values() for magic in values)):
            raise ReleaseContractError(f"publication image content/type differs: {relative}")
        return
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseContractError(f"unreviewed binary publication content: {relative}") from exc
    if b"\x00" in content:
        raise ReleaseContractError(f"binary data in publication source: {relative}")


def _vendor_wheel(root: Path, relative: str, content: bytes) -> None:
    if hashlib.sha256(content).hexdigest() != VENDOR_WHEELS[relative]:
        raise ReleaseContractError(f"application wheel differs from reviewed content: {relative}")
    parent = PurePosixPath(relative).parent
    provenance_path = _regular_file(root, str(parent / "provenance.json"))
    license_path = _regular_file(root, str(parent / "LICENSE"))
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ReleaseContractError(f"application wheel provenance is invalid: {relative}") from exc
    if not isinstance(provenance, dict) or (
        provenance.get("license_sha256") != hashlib.sha256(license_path.read_bytes()).hexdigest()
    ):
        raise ReleaseContractError(f"application wheel license differs: {relative}")
    expected = provenance.get("output_member_sha256")
    if not isinstance(expected, dict) or not expected:
        raise ReleaseContractError(f"application wheel member provenance is missing: {relative}")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(members) > 1024 or len(names) != len(set(names)) or set(names) != set(expected):
                raise ReleaseContractError(f"application wheel member inventory differs: {relative}")
            if sum(member.file_size for member in members) > MAX_WHEEL_EXPANDED_BYTES:
                raise ReleaseContractError(f"application wheel expanded size exceeds bound: {relative}")
            for member in members:
                _relative_path(member.filename)
                mode = stat.S_IFMT(member.external_attr >> 16)
                if member.is_dir() or mode not in {0, stat.S_IFREG} or member.flag_bits & 1:
                    raise ReleaseContractError(f"application wheel contains a special member: {relative}")
                data = archive.read(member)
                _source_content(member.filename, data)
                if hashlib.sha256(data).hexdigest() != expected[member.filename]:
                    raise ReleaseContractError(f"application wheel member checksum differs: {relative}")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ReleaseContractError(f"application wheel cannot be inspected: {relative}") from exc


def inspect_publication_files(
    root: Path, paths: Iterable[str], *, allow_application_wheels: bool = False,
) -> dict[str, int]:
    """Inspect an explicit inventory without expanding archives onto the filesystem."""
    if root.is_symlink() or not root.is_dir():
        raise ReleaseContractError("publication root must be a regular directory")
    seen: set[str] = set()
    wheel_count = 0
    for relative in paths:
        if relative in seen:
            raise ReleaseContractError(f"duplicate publication path: {relative}")
        seen.add(relative)
        path = _regular_file(root, relative)
        content = path.read_bytes()
        if allow_application_wheels and relative in VENDOR_WHEELS:
            # Keep license and provenance in the same delivered inventory.
            _vendor_wheel(root, relative, content)
            wheel_count += 1
        else:
            _source_content(relative, content)
    for relative in set(VENDOR_WHEELS) & seen:
        parent = PurePosixPath(relative).parent
        if not {str(parent / "LICENSE"), str(parent / "provenance.json")} <= seen:
            raise ReleaseContractError(f"application wheel metadata is outside inventory: {relative}")
    return {"files_checked": len(seen), "application_wheels_checked": wheel_count}


def validate_application_images(images: object, *, version: str) -> dict[str, str]:
    """Validate publication destinations; never pull, build, tag or push an image."""
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
        raise ReleaseContractError("publication version must be an explicit product version")
    if not isinstance(images, dict) or set(images) != set(APPLICATION_REPOSITORIES):
        raise ReleaseContractError("publication image inventory must contain only frontend and backend")
    for name, repository in APPLICATION_REPOSITORIES.items():
        value = images[name]
        if not isinstance(value, str) or not re.fullmatch(
            re.escape(f"{repository}:{version}") + r"@sha256:[0-9a-f]{64}", value,
        ):
            raise ReleaseContractError(f"publication target is not the owned versioned application: {name}")
    return dict(sorted(images.items()))
