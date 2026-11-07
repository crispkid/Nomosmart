from __future__ import annotations

from hashlib import sha256

from ldap_filter import Filter, ParseError

from app.core.errors import AppError


def _escapes_are_hex_encoded(value: str) -> bool:
    index = 0
    hexadecimal = frozenset("0123456789abcdefABCDEF")
    while index < len(value):
        if value[index] != "\\":
            index += 1
            continue
        if index + 2 >= len(value) or value[index + 1] not in hexadecimal or value[index + 2] not in hexadecimal:
            return False
        index += 3
    return True


def validate_directory_filter(value: str) -> str:
    normalized = value.strip()
    if len(normalized.encode("utf-8")) > 2048:
        raise AppError("directory_filter_too_long", "Directory filter exceeds 2048 UTF-8 bytes", status_code=422)
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise AppError("directory_filter_invalid", "Directory filter contains control characters", status_code=422)
    if not normalized:
        return ""
    if not _escapes_are_hex_encoded(normalized):
        raise AppError("directory_filter_invalid", "Directory filter contains an invalid escape", status_code=422)
    try:
        Filter.parse(normalized)
    except (ParseError, ValueError, TypeError) as exc:
        raise AppError("directory_filter_invalid", "Directory filter is not a valid RFC 4515 filter", status_code=422) from exc
    return normalized


def directory_filter_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
