from __future__ import annotations

import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from xml.parsers import expat
from zipfile import BadZipFile, ZipFile, ZipInfo

from app.core.errors import AppError
from app.domain.upload_content import UploadContent, as_content


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


def inspect_docx_package(content: bytes | UploadContent, *, max_source_bytes: int) -> DocxInspection:
    source = as_content(content)
    if not source.prefix(2).startswith(b"PK"):
        raise AppError("invalid_file_signature", "DOCX file signature is invalid", status_code=422)
    try:
        with source.open() as reader, ZipFile(reader) as archive:
            entries = archive.infolist()
            _validate_entries(entries, max_source_bytes=max_source_bytes)
            names = {entry.filename for entry in entries}
            if len(names) != len(entries):
                raise AppError("invalid_docx_package", "DOCX contains duplicate package parts", status_code=422)
            for name in names:
                if name.endswith(".rels"):
                    _validate_relationships(_bounded_read(archive, name, max_bytes=2 * 1024 * 1024), name)
            required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
            if not required.issubset(names):
                raise AppError("invalid_docx_package", "DOCX package structure is invalid", status_code=422)
            content_types = _bounded_read(archive, "[Content_Types].xml", max_bytes=2 * 1024 * 1024)
            if DOCX_MAIN_CONTENT_TYPE.encode("utf-8") not in content_types:
                raise AppError("invalid_docx_package", "DOCX package content type is invalid", status_code=422)
            limit = max(max_source_bytes * 2, 8 * 1024 * 1024)
            if archive.getinfo("word/document.xml").file_size > limit:
                raise AppError("docx_package_limit_exceeded", "DOCX XML part exceeds the safe limit", status_code=422)
            with archive.open("word/document.xml") as document_xml:
                revision_count, visible_text_nodes = _inspect_xml_stream(document_xml, source=source, max_bytes=limit)
            return DocxInspection(
                entry_count=len(entries),
                expanded_bytes=sum(entry.file_size for entry in entries),
                has_comments="word/comments.xml" in names,
                revision_count=revision_count,
                visible_text_nodes=visible_text_nodes,
            )
    except AppError:
        raise
    except (BadZipFile, ElementTree.ParseError, expat.ExpatError, KeyError, OSError, RuntimeError) as exc:
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
    with BytesIO(document_xml) as reader:
        return _inspect_xml_stream(reader, source=as_content(document_xml), max_bytes=len(document_xml))


def _inspect_xml_stream(reader, *, source: UploadContent, max_bytes: int) -> tuple[int, int]:
    """SAX counts without retaining XML/text; reject DTD and oversized tokens/depth."""
    parser = expat.ParserCreate(namespace_separator="}")
    revision_count = 0
    visible_text_nodes = 0
    stack: list[list[object]] = []

    def start(name, attrs):
        nonlocal revision_count
        if len(stack) >= 1024:
            raise AppError("docx_package_limit_exceeded", "DOCX XML nesting exceeds the safe limit", status_code=422)
        local_name = name.rsplit("}", 1)[-1]
        if local_name in REVISION_ELEMENTS:
            revision_count += 1
        stack.append([local_name == "t", False])

    def text(value):
        if stack and stack[-1][0] and value.strip():
            stack[-1][1] = True

    def end(name):
        nonlocal visible_text_nodes
        if stack.pop()[1]:
            visible_text_nodes += 1

    def reject(*args):
        raise AppError("invalid_docx_package", "DOCX XML declarations are not supported", status_code=422)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    received = 0
    while block := reader.read(source.chunk_size):
        source.check_deadline()
        received += len(block)
        if received > max_bytes:
            raise AppError("docx_package_limit_exceeded", "DOCX XML part exceeds the safe limit", status_code=422)
        parser.Parse(block, False)
        if received - parser.CurrentByteIndex > 2 * 1024 * 1024:
            raise AppError("docx_package_limit_exceeded", "DOCX XML token exceeds the safe limit", status_code=422)
    parser.Parse(b"", True)
    return revision_count, visible_text_nodes


def _xml_root(body: bytes):
    if b"<!DOCTYPE" in body.replace(b"\x00", b"").upper():
        raise AppError("invalid_docx_package", "DOCX XML declarations are not supported", status_code=422)
    return ElementTree.fromstring(body)


def _validate_relationships(body: bytes, name: str) -> None:
    for entry in _xml_root(body):
        target = entry.get("Target", "")
        kind = entry.get("Type", "")
        external = entry.get("TargetMode", "").lower() == "external"
        try:
            parsed = urlsplit(target)
        except ValueError:
            raise AppError("invalid_docx_package", "DOCX relationship is invalid", status_code=422) from None
        # Hyperlinks are data, never downloads. Local file/UNC and all external
        # media/templates/OLE relationships are rejected before Pandoc starts.
        if external:
            if (kind.endswith("/hyperlink") and parsed.scheme.lower() in {"https", "http", "mailto"}
                    and not parsed.username and not parsed.password):
                continue
            raise AppError("invalid_docx_package", "DOCX external resource relationships are not supported", status_code=422)
        decoded = unquote(target)
        if not target or parsed.scheme or parsed.netloc or "\\" in decoded or decoded.startswith("/"):
            raise AppError("invalid_docx_package", "DOCX relationship path is unsafe", status_code=422)
        # Resolve against the owning part's directory; ../ is legitimate only
        # when it remains within the ZIP (e.g. a header linking shared media).
        depth = len(PurePosixPath(name).parent.parent.parts)
        for part in PurePosixPath(unquote(parsed.path)).parts:
            depth += -1 if part == ".." else 0 if part == "." else 1
            if depth < 0:
                raise AppError("invalid_docx_package", "DOCX relationship escapes the package", status_code=422)
