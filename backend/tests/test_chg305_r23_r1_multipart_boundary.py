"""Real parser callbacks/disk IO: callbacks observe production parser, not mocks."""
import hashlib
import os

import pytest
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError

from app.core.errors import AppError
from app.domain.multipart_upload import StreamingMultipart
from test_chg304_multipart import envelope
from test_chg305_r23_upload_stream import receiving

BOUNDARY = b'boundary:304'
CLOSE = b'\r\n--' + BOUNDARY + b'--'
HEADER = 'multipart/form-data; boundary="boundary:304"'


class Observation:
    def __init__(self, **kwargs):
        self.events = []
        self.parts = []
        self.parser = MultipartParser(BOUNDARY, {
            'on_part_begin': self.begin,
            'on_part_data': self.data,
            'on_part_end': lambda: self.events.append('part_end'),
            'on_end': lambda: self.events.append('end'),
        }, **kwargs)

    def begin(self):
        self.events.append('part_begin')
        self.parts.append(bytearray())

    def data(self, data, start, end):
        assert 'end' not in self.events
        self.parts[-1].extend(data[start:end])


@pytest.mark.parametrize('suffix', [b'x', b'--suffix', b' \ttext', b'\rX', b'\r', b'\x00\xff', b'\n'])
def test_every_split_preserves_candidate_bytes_and_order(suffix):
    value = b'lead\x00' + CLOSE + suffix + CLOSE + b'X' + b' tail \t\r\n'
    originals = [value, '第二份😀'.encode(), b'']
    body = envelope(originals)
    for split in range(len(body) + 1):
        observer = Observation()
        observer.parser.write(body[:split])
        observer.parser.write(body[split:])
        observer.parser.finalize()
        observer.parser.finalize()
        assert list(map(bytes, observer.parts)) == originals, split
        assert observer.events == ['part_begin', 'part_end'] * 3 + ['end']


def test_bytewise_disk_hash_and_overlapping_cr():
    original = (b'\x00\xff' + CLOSE + b' \tno' + CLOSE + b'\r' + CLOSE + b'X\r') * 50
    with receiving() as lease:
        parser = StreamingMultipart(HEADER, lease)
        for byte in envelope([original, b'sibling']):
            parser.write(bytes([byte]))
            assert len(parser.parser._closing) <= len(CLOSE) + 16384 + 1
        files = parser.finish().files
        assert [b''.join(file.source.chunks()) for file in files] == [original, b'sibling']
        assert files[0].source.size == len(original)
        assert files[0].source.sha256 == hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize('empty', [False, True])
@pytest.mark.parametrize('padding', [b'', b' ', b'\t \t'])
@pytest.mark.parametrize('ending', [b'', b'\r\n', b'\r\nepilogue\x00--boundary:304'])
def test_confirm_only_after_crlf_or_eof(empty, padding, ending):
    body = envelope([] if empty else [b'original'])[:-2] + padding
    observer = Observation()
    for byte in body:
        observer.parser.write(bytes([byte]))
    observer.parser.write(b'')
    assert 'end' not in observer.events
    assert 'part_end' not in observer.events
    if ending:
        observer.parser.write(ending[:1])
        assert 'end' not in observer.events
        observer.parser.write(ending[1:])
        assert observer.events.count('end') == 1
    observer.parser.finalize()
    observer.parser.finalize()
    assert list(map(bytes, observer.parts)) == ([] if empty else [b'original'])
    assert observer.events == (['end'] if empty else ['part_begin', 'part_end', 'end'])


@pytest.mark.parametrize('body', [b'', b'--boundary:304-', envelope([b'x'])[:-19],
    envelope([b'x'])[:-1], envelope([])[:-1], envelope([b'x'])[:-2] + b' suffix',
    envelope([b'x'])[:-2] + b' \t\r', envelope([])[:-2] + b' suffix'])
def test_incomplete_rejected_without_success_and_private_fd_closed(body):
    with pytest.raises(AppError) as error:
        with receiving(NOMOSMART_UPLOAD_MAX_INFLIGHT=1) as lease:
            fd = lease.file.fileno()
            file = lease.file
            parser = StreamingMultipart(HEADER, lease)
            for byte in body:
                parser.write(bytes([byte]))
            assert not parser.ended
            parser.finish()
    assert error.value.code == 'invalid_multipart_request'
    assert file.closed
    with pytest.raises(OSError):
        os.fstat(fd)
    with receiving(NOMOSMART_UPLOAD_MAX_INFLIGHT=1):
        pass


@pytest.mark.parametrize('extra', [0, 1])
def test_padding_at_typed_cap_and_one_over(extra):
    body = envelope([b'original'])[:-2] + b' ' * (4096 + extra) + b'\r\n'
    with receiving(NOMOSMART_UPLOAD_PART_HEADER_MAX_KIB=4) as lease:
        parser = StreamingMultipart(HEADER, lease)
        if extra:
            with pytest.raises(AppError) as error:
                for byte in body:
                    parser.write(bytes([byte]))
            assert error.value.code == 'invalid_multipart_request'
            assert not parser.ended
        else:
            for byte in body:
                parser.write(bytes([byte]))
                assert len(parser.parser._closing) <= len(CLOSE) + 4096 + 1
            assert b''.join(parser.finish().files[0].source.chunks()) == b'original'


@pytest.mark.parametrize('cap', [-1, True, 1.5, None, 65537])
def test_no_unbounded_padding_option(cap):
    with pytest.raises(ValueError):
        MultipartParser(BOUNDARY, max_boundary_padding_size=cap)


def test_zero_padding_cap_and_safe_eof_error():
    observer = Observation(max_boundary_padding_size=0)
    observer.parser.write(envelope([b'x'])[:-2] + b'\r')
    with pytest.raises(MultipartParseError):
        observer.parser.finalize()
    assert 'end' not in observer.events
    observer = Observation(max_boundary_padding_size=0)
    with pytest.raises(MultipartParseError):
        observer.parser.write(envelope([b'x'])[:-2] + b' ')
