"""Actual parser/disk/domain tests; no fake HTTP, database, storage or clock."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.multipart_upload import StreamingMultipart
from app.domain.upload_stream import UploadLease
from app.domain.document_imports import validate_file_payload, _source_text_metadata
from app.domain.uploads import build_storage_identity
from test_chg304_multipart import envelope
from docx_source_samples import docx_bytes


@contextmanager
def receiving(**limits):
    with tempfile.TemporaryDirectory(prefix='nomosmart-r23-test-') as directory:
        settings = Settings(_env_file=None, NOMOSMART_UPLOAD_SCRATCH_DIR=directory, **limits)
        lease = UploadLease(settings)
        lease.open()
        try:
            yield lease
        finally:
            lease.close()
        assert list(Path(directory).iterdir()) == []


def parse(lease, body, header='multipart/form-data; boundary="boundary:304"', step=7):
    parser = StreamingMultipart(header, lease)
    for start in range(0, len(body), step):
        parser.write(body[start:start+step])
    return parser.finish()


@pytest.mark.parametrize('step', [1, 7, 65536])
def test_real_disk_byte_exact_and_identity(step):
    values = [b'x\n', b'\r\nx\r\n\r\n', b' \t\n', b'x--', b'\x00\xff\x80\r\n\t ', b'', '中文😀\n'.encode()]
    with receiving() as lease:
        payload = parse(lease, envelope(values), step=step)
        for file, original in zip(payload.files, values, strict=True):
            assert b''.join(file.source.chunks()) == original
            assert file.source.sha256 == hashlib.sha256(original).hexdigest()
            assert build_storage_identity(file.content, file.filename, salt=b'0'*16) == build_storage_identity(original, file.filename, salt=b'0'*16)


def test_boundary_like_bytes_remain_content():
    value = b'middle--boundary:304\r\n--boundary:304suffix\r\n--boundary:304--suffix\r\nend\n'
    with receiving() as lease:
        assert b''.join(parse(lease, envelope([value])).files[0].source.chunks()) == value


@pytest.mark.parametrize('extra', [b'Content-Transfer-Encoding: base64\r\n', b'Content-Disposition: form-data; name="other"\r\n', b'Content-Type: multipart/mixed; boundary=inner\r\n'])
def test_reject_ambiguous_parts(extra):
    with receiving() as lease, pytest.raises(AppError, match='Multipart'):
        parse(lease, envelope([b'x'], extra=extra))


def test_truncated_and_duplicate_fields():
    for body in [envelope([b'one'])[:-19], b'--boundary:304\r\nContent-Disposition: form-data; name="a"\r\n\r\nx\r\n'*2+b'--boundary:304--\r\n']:
        with receiving() as lease, pytest.raises(AppError, match='Multipart'):
            parse(lease, body)


def test_file_over_limit_preserves_hash_and_next_sibling():
    first = b'x' * (1024*1024+1)
    with receiving(MAX_UPLOAD_SIZE_MB=1) as lease:
        result = parse(lease, envelope([first, b'sibling']), step=65536)
        assert result.files[0].source.sha256 == hashlib.sha256(first).hexdigest()
        with pytest.raises(AppError) as error:
            validate_file_payload(result.files[0], lease.settings)
        assert error.value.code == 'upload_too_large'
        assert b''.join(result.files[1].source.chunks()) == b'sibling'


def test_text_source_is_reference_not_full_snapshot():
    original = '  # 中文😀\r\n\r\n文字\n'.encode()
    with receiving() as lease:
        file = parse(lease, envelope([original])).files[0]
        validate_file_payload(file, lease.settings)
        assert _source_text_metadata(file, '.md', None) == {'source_text_object': {'version': 1, 'encoding': 'utf-8', 'sha256': hashlib.sha256(original).hexdigest()}}


def test_streamed_docx_real_zip_and_xml():
    original = docx_bytes(comments=True)
    with receiving() as lease:
        file = parse(lease, envelope([original])).files[0]
        # Multipart accepts bytes; the real document policy rejects a renamed ZIP.
        with pytest.raises(AppError) as error:
            validate_file_payload(file, lease.settings)
        assert error.value.code == 'invalid_file_signature'


def test_admission_releases_after_failure():
    with receiving(NOMOSMART_UPLOAD_MAX_INFLIGHT=1) as lease:
        second = UploadLease(lease.settings)
        with pytest.raises(AppError) as error:
            second.open()
        assert error.value.code == 'upload_capacity_exhausted'
        second.close()
    with receiving(NOMOSMART_UPLOAD_MAX_INFLIGHT=1):
        pass
