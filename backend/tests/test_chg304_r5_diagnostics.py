"""Real stderr input / safe representation tests, not sandbox-success substitutes."""
from __future__ import annotations
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest


class Diagnostics(unittest.TestCase):
    def test_default_is_off_and_no_public_error_payload(self):
        from app.domain.ocr_sandbox import run_ocr_sandbox, _process_error
        self.assertIsNone(inspect.signature(run_ocr_sandbox).parameters["diagnostic_sink"].default)
        payload = b"bwrap: private-document-not-an-operation\n"
        error = _process_error("pdf_page_extract_failed", 1, payload)
        self.assertNotIn("private-document", str(error) + repr(error.details))
        self.assertEqual((error.code, error.status_code), ("pdf_page_extract_failed", 422))

    def test_real_untrusted_child_stderr_is_unknown_bounded_and_not_exposed(self):
        from app.domain.ocr_sandbox import _startup_diagnostic
        process = subprocess.run([sys.executable, "-c", "import os;os.write(2,b'bwrap: SECRET_TEST_ONLY_'*300)"],
                                 capture_output=True, timeout=5)
        report = _startup_diagnostic(process.stderr, process.returncode, mounts=[], root=Path("/tmp/synthetic"), inputs=(), outputs=())
        self.assertEqual(report["classification"], "UNKNOWN")
        self.assertEqual(report["prefix_bytes"], 4096)
        self.assertTrue(report["truncated"])
        self.assertEqual(report["messages"], [])
        self.assertNotIn("SECRET_TEST_ONLY", json.dumps(report))

    def test_fixed_operation_and_only_verified_path_can_be_classified(self):
        from app.domain.ocr_sandbox import _startup_diagnostic
        process = subprocess.run([sys.executable, "-c",
            "import os;os.write(2,b'bwrap: cannot open /proc/sys/user/max_user_namespaces: Read-only file system\\n')"],
            capture_output=True, timeout=5)
        report = _startup_diagnostic(process.stderr, 1, mounts=[], root=Path("/tmp/synthetic"), inputs=(), outputs=())
        self.assertEqual(report["classification"], "USER_NAMESPACE_CONTROL_UNAVAILABLE")
        self.assertEqual(len(report["messages"]), 1)


if __name__ == "__main__":
    unittest.main()
