"""Historical CHG-304 bubblewrap matrix, not CHG-305 session acceptance.

Never run naked parsers to pass these cases. The R2 probe records BLOCKED before
this suite when its positive sandbox-start control cannot execute.
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
from time import perf_counter
import unittest

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.extraction_pipeline import _joined_page_ranges
from local_pdf_compatibility import physical_pdf_inputs


class ActualParserIsolationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="chg304-r2-live-")
        self.root = Path(self.directory.name)
        self.settings = Settings(_env_file=None,
            tesseract_sandbox_read_only_paths=json.loads(os.environ["CHG304_R2_RUNTIME_PATHS"]),
            max_upload_size_mb=1)
        self.source = self.root / "input.txt"
        self.source.write_text("R2_SYNTHETIC_INPUT")

    def tearDown(self):
        self.directory.cleanup()

    def run_parser(self, args, inputs=(), outputs=()):
        from app.domain.ocr_sandbox import run_ocr_sandbox
        return run_ocr_sandbox(self.settings, self.root, args, input_paths=tuple(inputs), output_paths=tuple(outputs),
            deadline=perf_counter() + 6, error_code="r2_probe_denied")

    def denied(self, args):
        with self.assertRaises(AppError) as caught:
            self.run_parser(args)
        self.assertEqual(caught.exception.code, "r2_probe_denied")  # Not a sandbox-start failure.

    def test_positive_input_read_and_parent_environment_exclusion(self):
        self.assertEqual(self.run_parser(["cat", str(self.source)], [self.source]).stdout, b"R2_SYNTHETIC_INPUT")
        key = "CHG304_R2_PARENT_CANARY"
        old = os.environ.get(key)
        os.environ[key] = "SYNTHETIC_ENV_ONLY"
        try:
            output = self.run_parser(["printenv"]).stdout.decode()
            self.assertNotIn(key, output)
            self.assertNotIn("SYNTHETIC_ENV_ONLY", output)
            self.assertEqual({line.split("=", 1)[0] for line in output.splitlines()}, {"PATH", "LANG", "LC_ALL", "HOME", "TMPDIR"})
        finally:
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def test_external_files_unlisted_sibling_parent_proc_and_inherited_fd_denied(self):
        sibling = self.root / "other-document.txt"
        sibling.write_text("SYNTHETIC_OTHER_DOCUMENT")
        descriptor = os.open(sibling, os.O_RDONLY)
        os.set_inheritable(descriptor, True)
        try:
            for path in (str(sibling), "/work/other-document.txt", f"/proc/{os.getpid()}/environ",
                         f"/proc/{os.getpid()}/fd/{descriptor}", f"/proc/self/fd/{descriptor}"):
                self.denied(["cat", path])
        finally:
            os.close(descriptor)

    def test_read_only_input_and_no_unlisted_output(self):
        with self.assertRaises(AppError) as caught:
            self.run_parser(["touch", str(self.source)], [self.source])
        self.assertEqual(caught.exception.code, "r2_probe_denied")
        self.denied(["touch", "/work/not-predeclared"])
        self.denied(["touch", "/usr/bin/cat"])
        self.assertEqual(self.source.read_text(), "R2_SYNTHETIC_INPUT")

    def test_input_symlink_cannot_export_unrelated_file(self):
        link = self.root / "link"
        link.symlink_to("/etc/passwd")
        with self.assertRaises(AppError) as caught:
            self.run_parser(["cat", str(link)], [link])
        self.assertEqual(caught.exception.code, "ocr_tesseract_runtime_unavailable")

    def test_pid_and_network_namespaces_differ(self):
        for name in ("pid", "net"):
            actual = self.run_parser(["readlink", f"/proc/self/ns/{name}"]).stdout.decode().strip()
            self.assertTrue(actual)
            self.assertNotEqual(actual, os.readlink(f"/proc/self/ns/{name}"))

    def test_parent_loopback_is_not_reachable(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(True)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"synthetic-parent-network-canary")
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.denied(["curl", "--noproxy", "*", "--connect-timeout", "1", "--max-time", "2",
                         f"http://127.0.0.1:{server.server_port}/"])
            self.assertEqual(hits, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

    def test_physical_pages_blank_offsets_split_and_tesseract(self):
        body = Path("/sample.pdf").read_bytes()
        pages = physical_pdf_inputs(self.settings, body, text_only=True, deadline=perf_counter() + 20)
        self.assertEqual(len(pages), 3)
        self.assertIn("FIRST PHYSICAL PAGE", pages[0])
        self.assertEqual(pages[1], "")
        self.assertIn("THIRD PHYSICAL PAGE", pages[2])
        self.assertEqual(_joined_page_ranges(pages)[1]["start_offset"], _joined_page_ranges(pages)[1]["end_offset"])
        split = physical_pdf_inputs(self.settings, body, text_only=False, deadline=perf_counter() + 20)
        self.assertEqual(len(split), 3)
        for index, (_, _, content) in enumerate(split):
            self.assertEqual(physical_pdf_inputs(self.settings, content, text_only=True, deadline=perf_counter() + 10), [pages[index]])
        pdf = self.root / "source.pdf"
        pdf.write_bytes(split[0][2])
        png = self.root / "image.png"
        self.run_parser(["pdftoppm", "-png", "-r", "100", "-singlefile", str(pdf), str(self.root / "image")], [pdf], [png])
        output = self.run_parser(["tesseract", str(png), "stdout", "-l", "eng"], [png]).stdout
        self.assertIn(b"PHYSICAL PAGE", output)

    def test_page_and_malformed_input_limits(self):
        from app.domain.local_pdf.errors import Rejected
        body = Path("/sample.pdf").read_bytes()
        with self.assertRaises(Rejected) as caught:
            physical_pdf_inputs(self.settings.model_copy(update={"tesseract_max_pages": 2}), body,
                text_only=False, deadline=perf_counter() + 10)
        self.assertEqual(caught.exception.code, "page_limit")
        with self.assertRaises(Rejected) as caught:
            physical_pdf_inputs(self.settings, b"%PDF-1.7\ntruncated", text_only=True, deadline=perf_counter() + 6)
        self.assertEqual(caught.exception.code, "invalid_output")


if __name__ == "__main__":
    unittest.main()
