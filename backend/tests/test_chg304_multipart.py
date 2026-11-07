"""Pure parser regression; real HTTP/storage acceptance is a separate test layer."""
import unittest

from app.core.errors import AppError
from app.domain.multipart_upload import parse_multipart
from app.domain.document_imports import UploadedFilePayload, source_text_snapshot


def envelope(payloads, boundary=b"boundary:304", extra=b""):
    return b"".join(
        b"--" + boundary + b"\r\nContent-Disposition: form-data; name=\"files\"; "
        + f'filename="file-{i}.md"'.encode() + b"\r\n" + extra
        + b"\r\n" + payload + b"\r\n"
        for i, payload in enumerate(payloads)
    ) + b"--" + boundary + b"--\r\n"


class MultipartBytesTests(unittest.TestCase):
    def test_markdown_snapshot_preserves_indentation_and_trailing_newlines(self):
        text = "    SELECT *\r\n\r\n# 中文😀\r\n \t\n"
        self.assertEqual(source_text_snapshot(UploadedFilePayload("source.md", "text/markdown", text.encode()), ".md"), text)
        self.assertIsNone(source_text_snapshot(UploadedFilePayload("blank.md", None, b" \r\n"), ".md"))

    def test_byte_exact_multiple_files(self):
        payloads = [b"x\n", b"\r\nx\r\n\r\n", b" \t\n", b"x--", b"\x00\xff\x80\r\n\t ", b"", "中文😀\n".encode()]
        result = parse_multipart(envelope(payloads), 'multipart/form-data; boundary="boundary:304"')
        self.assertEqual([file.content for file in result.files], payloads)
        self.assertEqual([file.filename for file in result.files], [f"file-{i}.md" for i in range(len(payloads))])

    def test_boundary_like_bytes_not_delimiters(self):
        payload = b"middle--boundary:304\r\n--boundary:304suffix\r\n--boundary:304--suffix\r\nend\n"
        self.assertEqual(parse_multipart(envelope([payload]), 'multipart/form-data; boundary="boundary:304"').files[0].content, payload)

    def test_utf8_filename_and_field(self):
        body = ('--b\r\nContent-Disposition: form-data; name="force_ocr"\r\n\r\nfalse\r\n'
                '--b\r\nContent-Disposition: form-data; name="files"; filename="中文.md"\r\n'
                'Content-Type: text/markdown\r\n\r\n內容\n\r\n--b--\r\n').encode()
        result = parse_multipart(body, "multipart/form-data; boundary=b")
        self.assertEqual(result.fields, {"force_ocr": "false"})
        self.assertEqual(result.files[0].filename, "中文.md")
        self.assertEqual(result.files[0].content, "內容\n".encode())

    def test_malformed_is_rejected_before_any_caller_writes(self):
        cases = [
            (envelope([b"x"])[:-18], 'multipart/form-data; boundary="boundary:304"'),
            (b"x", "multipart/form-data"),
            (envelope([b"x"]), "text/plain; boundary=boundary:304"),
            (envelope([b"x"]), 'multipart/form-data; boundary="b\r\nInjected: 1"'),
            (envelope([b"eA=="], extra=b"Content-Transfer-Encoding: base64\r\n"), 'multipart/form-data; boundary="boundary:304"'),
            (envelope([b"x"], extra=b'Content-Disposition: form-data; name="other"\r\n'), 'multipart/form-data; boundary="boundary:304"'),
        ]
        for body, header in cases:
            with self.subTest(header=header), self.assertRaises(AppError) as caught:
                parse_multipart(body, header)
            self.assertEqual(caught.exception.code, "invalid_multipart_request")

    def test_duplicate_fields_rejected(self):
        part = b'--b\r\nContent-Disposition: form-data; name="force_ocr"\r\n\r\ntrue\r\n'
        with self.assertRaises(AppError):
            parse_multipart(part * 2 + b"--b--\r\n", "multipart/form-data; boundary=b")


if __name__ == "__main__":
    unittest.main()
