"""Decode the form envelope without normalizing uploaded file bytes."""
from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.errors import MessageError, UndecodableBytesDefect
from email.parser import BytesParser
import re
import hashlib

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError

from app.core.errors import AppError
from app.domain.document_imports import UploadedFilePayload
from app.domain.upload_content import DiskContent


@dataclass(frozen=True)
class MultipartPayload:
    fields: dict[str, str]
    files: list[UploadedFilePayload]


class StreamingMultipart:
    """Incremental boundary parser; only bounded MIME *headers* use email parsing."""
    def __init__(self, content_type: str, lease) -> None:
        self.lease = lease
        self.fields: dict[str, str] = {}
        self.files: list[UploadedFilePayload] = []
        self.metadata_size = 0
        self.ended = False
        try:
            if '\r' in content_type or '\n' in content_type or len(content_type) > lease.settings.upload_part_header_max_kib * 1024:
                raise ValueError('header')
            header = BytesParser(policy=policy.default.clone(raise_on_defect=True)).parsebytes(
                b'Content-Type: ' + content_type.encode('ascii') + b'\r\n\r\n', headersonly=True)
            boundary = header.get_boundary()
            if header.get_content_type() != 'multipart/form-data' or not boundary or not re.fullmatch(r"[0-9A-Za-z'()+_,./:=? -]{1,70}", boundary) or boundary.endswith(' '):
                raise ValueError('boundary')
            self.parser = MultipartParser(boundary, {
                'on_part_begin': self.begin, 'on_header_field': self.header_data,
                'on_header_value': self.value_data, 'on_header_end': self.header_end,
                'on_headers_finished': self.headers_finished, 'on_part_data': self.data,
                'on_part_end': self.end_part, 'on_end': self.end,
            }, max_boundary_padding_size=lease.settings.upload_part_header_max_kib * 1024)
        except (MessageError, ValueError, UnicodeError) as exc:
            raise self.invalid() from exc

    @staticmethod
    def invalid() -> AppError:
        return AppError('invalid_multipart_request', 'Multipart request is invalid', status_code=400)

    def metadata(self, size: int) -> None:
        self.metadata_size += size
        if self.metadata_size > self.lease.settings.upload_metadata_max_kib * 1024:
            raise self.invalid()

    def begin(self) -> None:
        # Fixed per-part overhead bounds empty parts too, without a separate file-count policy.
        self.metadata(256)
        self.headers = bytearray()
        self.current_header = bytearray()
        self.current_value = bytearray()
        self.field_value = bytearray()
        self.part_size = 0
        self.digest = hashlib.sha256()
        self.offset = self.lease.file.tell()

    def _header(self, target: bytearray, data: bytes, start: int, end: int) -> None:
        size = end - start
        self.metadata(size)
        if len(self.headers) + len(self.current_header) + len(self.current_value) + size + 4 > self.lease.settings.upload_part_header_max_kib * 1024:
            raise self.invalid()
        target.extend(data[start:end])

    def header_data(self, data, start, end) -> None:
        self._header(self.current_header, data, start, end)

    def value_data(self, data, start, end) -> None:
        self._header(self.current_value, data, start, end)

    def header_end(self) -> None:
        self.metadata(4)
        self.headers.extend(self.current_header + b': ' + self.current_value + b'\r\n')
        self.current_header.clear()
        self.current_value.clear()

    def headers_finished(self) -> None:
        try:
            self.headers.decode('utf-8')
            part = BytesParser(policy=policy.default.clone(raise_on_defect=True)).parsebytes(bytes(self.headers) + b'\r\n', headersonly=True)
            if part.get_content_disposition() != 'form-data' or part.get_content_maintype() == 'multipart':
                raise ValueError('part')
            for name in ('Content-Disposition', 'Content-Type', 'Content-Transfer-Encoding'):
                value = part.get(name)
                if len(part.get_all(name, [])) > 1 or any(not isinstance(d, UndecodableBytesDefect) for d in getattr(value, 'defects', ())):
                    raise ValueError('header')
            if part.get('Content-Transfer-Encoding', 'binary').lower() not in {'binary', '8bit', '7bit'}:
                raise ValueError('encoding')
            self.name = part.get_param('name', header='content-disposition')
            if not isinstance(self.name, str) or not self.name:
                raise ValueError('name')
            self.filename = part.get_filename()
            self.content_type = str(part['Content-Type']) if 'Content-Type' in part else None
        except (MessageError, ValueError, UnicodeError) as exc:
            raise self.invalid() from exc

    def data(self, data, start, end) -> None:
        block = data[start:end]
        self.part_size += len(block)
        if self.filename is None:
            self.metadata(len(block))
            self.field_value.extend(block)
        else:
            self.digest.update(block)
            if self.part_size <= self.lease.settings.max_upload_size_mb * 1024 * 1024:
                self.lease.write(block)

    def end_part(self) -> None:
        if self.filename is None:
            try:
                if self.name in self.fields:
                    raise ValueError('duplicate')
                self.fields[self.name] = self.field_value.decode('utf-8')
            except (ValueError, UnicodeError) as exc:
                raise self.invalid() from exc
        elif self.filename:
            self.files.append(UploadedFilePayload(self.filename, self.content_type, DiskContent(
                fd=self.lease.file.fileno(), offset=self.offset, size=self.part_size,
                sha256=self.digest.hexdigest(), chunk_size=self.lease.settings.upload_io_chunk_kib * 1024,
                deadline=self.lease.deadline,
                available=self.part_size <= self.lease.settings.max_upload_size_mb * 1024 * 1024)))

    def end(self) -> None:
        self.ended = True

    def write(self, block: bytes) -> None:
        try:
            if self.parser.write(block) != len(block):
                raise self.invalid()
        except MultipartParseError as exc:
            raise self.invalid() from exc

    def finish(self) -> MultipartPayload:
        try:
            self.parser.finalize()
        except MultipartParseError as exc:
            raise self.invalid() from exc
        if not self.ended:
            raise self.invalid()
        return MultipartPayload(self.fields, self.files)


def parse_multipart(body: bytes, content_type: str) -> MultipartPayload:
    """Use the stdlib MIME boundary parser; reject ambiguous/encoded form data.

    The CRLF preceding a delimiter belongs to the envelope. All earlier bytes,
    including trailing whitespace and boundary-like *non-delimiter* lines, belong
    to the file. MIME transfer decoding is deliberately prohibited for HTTP forms.
    File size, extension, malware and authorization checks remain at the caller.
    """
    try:
        if "\r" in content_type or "\n" in content_type:
            raise ValueError("header_injection")
        header = content_type.encode("ascii")
        message = BytesParser(policy=policy.default.clone(raise_on_defect=True)).parsebytes(
            b"Content-Type: " + header + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        boundary = message.get_boundary()
        if (message.get_content_type() != "multipart/form-data" or not boundary
                or not re.fullmatch(r"[0-9A-Za-z'()+_,./:=? -]{1,70}", boundary)
                or boundary.endswith(" ") or not message.is_multipart()):
            raise ValueError("invalid_boundary")
        fields: dict[str, str] = {}
        files: list[UploadedFilePayload] = []
        for part in message.iter_parts():
            if part.is_multipart() or part.get_content_disposition() != "form-data":
                raise ValueError("invalid_part")
            for name in ("Content-Disposition", "Content-Type", "Content-Transfer-Encoding"):
                if len(part.get_all(name, [])) > 1:
                    raise ValueError("duplicate_header")
                value = part.get(name)
                if value is not None and any(not isinstance(defect, UndecodableBytesDefect) for defect in getattr(value, "defects", ())):
                    raise ValueError("invalid_header")
            # HTTP form filenames may be UTF-8, unlike legacy ASCII-only MIME.
            # Validate the original bytes instead of accepting replacement text.
            for _name, value in part.raw_items():
                value.encode("ascii", "surrogateescape").decode("utf-8")
            if part.get("Content-Transfer-Encoding", "binary").lower() not in {"binary", "8bit", "7bit"}:
                raise ValueError("transfer_encoding_not_allowed")
            name = part.get_param("name", header="content-disposition")
            if not isinstance(name, str) or not name:
                raise ValueError("field_name_missing")
            content = part.get_payload(decode=True)
            if not isinstance(content, bytes):
                raise ValueError("invalid_payload")
            filename = part.get_filename()
            if filename is not None:
                if filename:
                    files.append(UploadedFilePayload(
                        filename=filename, content_type=str(part["Content-Type"]) if "Content-Type" in part else None,
                        content=content,
                    ))
            else:
                if name in fields:
                    raise ValueError("duplicate_field")
                fields[name] = content.decode("utf-8")
        return MultipartPayload(fields=fields, files=files)
    except (MessageError, ValueError, UnicodeError) as exc:
        raise AppError("invalid_multipart_request", "Multipart request is invalid", status_code=400) from exc
