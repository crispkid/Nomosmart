from __future__ import annotations

import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, ZipInfo

from app.core.errors import AppError


DOCX_MAX_ENTRIES = 4096
DOCX_MAX_COMPRESSION_RATIO = 200
DOCX_MAIN_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
REVISION_ELEMENTS = {"ins", "del", "moveFrom", "moveTo"}


@dataclass(frozen=True)
class DocxInspection:
    entry_count: int
    expanded_bytes: int
    has_comments: bool
    revision_count: int
    visible_text_nodes: int


def inspect_docx_package(content: bytes, *, max_source_bytes: int) -> DocxInspection:
    if not content.startswith(b"PK"):
        raise AppError("invalid_file_signature", "DOCX file signature is invalid", status_code=422)
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            _validate_entries(entries, max_source_bytes=max_source_bytes)
            names = {entry.filename for entry in entries}
            required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
            if not required.issubset(names):
                raise AppError("invalid_docx_package", "DOCX package structure is invalid", status_code=422)
            content_types = _bounded_read(archive, "[Content_Types].xml", max_bytes=2 * 1024 * 1024)
            if DOCX_MAIN_CONTENT_TYPE.encode("utf-8") not in content_types:
                raise AppError("invalid_docx_package", "DOCX package content type is invalid", status_code=422)
            document_xml = _bounded_read(archive, "word/document.xml", max_bytes=max(max_source_bytes * 2, 8 * 1024 * 1024))
            revision_count, visible_text_nodes = _inspect_document_xml(document_xml)
            return DocxInspection(
                entry_count=len(entries),
                expanded_bytes=sum(entry.file_size for entry in entries),
                has_comments="word/comments.xml" in names,
                revision_count=revision_count,
                visible_text_nodes=visible_text_nodes,
            )
    except AppError:
        raise
    except (BadZipFile, ElementTree.ParseError, KeyError, OSError, RuntimeError) as exc:
        raise AppError("invalid_docx_package", "DOCX package is malformed", status_code=422) from exc


def _validate_entries(entries: list[ZipInfo], *, max_source_bytes: int) -> None:
    if not entries or len(entries) > DOCX_MAX_ENTRIES:
        raise AppError("docx_package_limit_exceeded", "DOCX package contains too many entries", status_code=422)
    expanded_limit = max(max_source_bytes * 4, 32 * 1024 * 1024)
    expanded = 0
    for entry in entries:
        _validate_entry_path(entry)
        if entry.flag_bits & 0x1:
            raise AppError("invalid_docx_package", "Encrypted DOCX entries are not supported", status_code=422)
        unix_mode = entry.external_attr >> 16
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise AppError("invalid_docx_package", "DOCX symbolic links are not supported", status_code=422)
        expanded += entry.file_size
        if expanded > expanded_limit:
            raise AppError("docx_package_limit_exceeded", "DOCX expanded size exceeds the configured limit", status_code=422)
        if entry.file_size > 10 * 1024 * 1024:
            compressed = max(1, entry.compress_size)
            if entry.file_size / compressed > DOCX_MAX_COMPRESSION_RATIO:
                raise AppError("docx_package_limit_exceeded", "DOCX compression ratio exceeds the safe limit", status_code=422)


def _validate_entry_path(entry: ZipInfo) -> None:
    name = entry.filename
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or ".." in path.parts:
        raise AppError("invalid_docx_package", "DOCX package contains an unsafe path", status_code=422)


def _bounded_read(archive: ZipFile, name: str, *, max_bytes: int) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > max_bytes:
        raise AppError("docx_package_limit_exceeded", "DOCX XML part exceeds the safe limit", status_code=422)
    return archive.read(info)


def _inspect_document_xml(document_xml: bytes) -> tuple[int, int]:
    root = ElementTree.fromstring(document_xml)
    revision_count = 0
    visible_text_nodes = 0
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name in REVISION_ELEMENTS:
            revision_count += 1
        if local_name == "t" and element.text and element.text.strip():
            visible_text_nodes += 1
    return revision_count, visible_text_nodes
