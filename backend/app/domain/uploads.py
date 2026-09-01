from __future__ import annotations

import hashlib
import secrets
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath


CANONICAL_EXTENSIONS = {
    ".pdf": ".pdf",
    ".docx": ".docx",
    ".txt": ".txt",
    ".md": ".md",
    ".markdown": ".md",
    ".csv": ".csv",
    ".json": ".json",
}

FILE_SOURCE_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md"})
HTTP_RESPONSE_EXTENSIONS = frozenset({*FILE_SOURCE_EXTENSIONS, ".csv", ".json"})


@dataclass(frozen=True)
class StorageIdentity:
    content_sha256: str
    storage_name_salt: str
    storage_name_hash: str
    canonical_extension: str

    @property
    def object_name(self) -> str:
        return f"{self.storage_name_hash}{self.canonical_extension}"


def canonical_extension(filename: str) -> str:
    extension = PurePath(filename).suffix.lower()
    if extension not in CANONICAL_EXTENSIONS:
        raise ValueError("unsupported file extension")
    return CANONICAL_EXTENSIONS[extension]


def validate_source_extension(filename: str, *, http_response: bool = False) -> str:
    extension = canonical_extension(filename)
    allowed = HTTP_RESPONSE_EXTENSIONS if http_response else FILE_SOURCE_EXTENSIONS
    if extension not in allowed:
        raise ValueError("unsupported source extension")
    return extension


def sanitize_original_filename(filename: str, *, max_length: int = 255) -> str:
    normalized = unicodedata.normalize("NFC", PurePath(filename).name)
    cleaned = "".join(character for character in normalized if character.isprintable() and character not in "\x00/\\")
    cleaned = cleaned.strip(" .")
    if not cleaned:
        raise ValueError("filename is empty after sanitization")
    return cleaned[:max_length]


def build_storage_identity(content: bytes, filename: str, *, salt: bytes | None = None) -> StorageIdentity:
    actual_salt = salt or secrets.token_bytes(16)
    if len(actual_salt) < 16:
        raise ValueError("storage-name salt must be at least 16 bytes")
    content_digest = hashlib.sha256(content).digest()
    storage_digest = hashlib.sha256(actual_salt + content_digest).hexdigest()
    return StorageIdentity(
        content_sha256=content_digest.hex(),
        storage_name_salt=actual_salt.hex(),
        storage_name_hash=storage_digest,
        canonical_extension=canonical_extension(filename),
    )


def build_storage_key(project_id: str, document_id: str, version_id: str, identity: StorageIdentity) -> str:
    return f"projects/{project_id}/documents/{document_id}/versions/{version_id}/source/{identity.object_name}"
