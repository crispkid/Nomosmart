"""Bounded validation of the non-interlaced 8-bit PNGs emitted by Poppler."""
import hashlib
import struct
import zlib

from .errors import need


def validate_png(body: bytes, *, max_bytes: int, max_pixels: int) -> dict:
    need(type(body) is bytes and 0 < len(body) <= max_bytes, "output_limit")
    need(body[:8] == b"\x89PNG\r\n\x1a\n", "invalid_output")
    offset, width, height, row_bytes, decoded = 8, 0, 0, 0, 0
    inflater = zlib.decompressobj()
    seen_header = seen_data = ended = False
    while offset < len(body):
        need(offset + 12 <= len(body), "invalid_output")
        length = struct.unpack_from(">I", body, offset)[0]
        kind = body[offset + 4:offset + 8]
        end = offset + length + 12
        need(end <= len(body), "invalid_output")
        data = body[offset + 8:end - 4]
        crc = struct.unpack_from(">I", body, end - 4)[0]
        need(zlib.crc32(kind + data) & 0xffffffff == crc, "invalid_output")
        if not seen_header:
            need(kind == b"IHDR" and length == 13, "invalid_output")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            need(width > 0 and height > 0 and width * height <= max_pixels, "output_limit")
            need(depth == 8 and color in {0, 2, 6} and compression == filtering == interlace == 0, "invalid_output")
            row_bytes = 1 + width * {0: 1, 2: 3, 6: 4}[color]
            seen_header = True
        elif kind == b"IHDR":
            need(False, "invalid_output")
        elif kind == b"IDAT":
            seen_data = True
            chunk = data
            try:
                while chunk:
                    output = inflater.decompress(chunk, 65536)
                    # Validate every row's filter byte without retaining the image.
                    for index in range((-decoded) % row_bytes, len(output), row_bytes):
                        need(output[index] <= 4, "invalid_output")
                    decoded += len(output)
                    need(decoded <= row_bytes * height, "output_limit")
                    chunk = inflater.unconsumed_tail
            except zlib.error:
                need(False, "invalid_output")
        elif kind == b"IEND":
            need(length == 0 and seen_data and inflater.eof and not inflater.unused_data
                 and decoded == row_bytes * height and end == len(body), "invalid_output")
            ended = True
        else:
            # Unknown critical chunks may change pixel interpretation.
            need(bool(kind[0] & 0x20), "invalid_output")
        offset = end
    need(seen_header and seen_data and ended, "invalid_output")
    return {"width": width, "height": height, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
