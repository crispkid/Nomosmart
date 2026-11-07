"""Real filesystem/process checks, not mocks or sandbox-success substitutes."""
from __future__ import annotations
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from time import perf_counter, sleep
import unittest

from app.core.config import Settings
from app.core.errors import AppError


class ParserConfigTests(unittest.TestCase):
    def test_invalid_json_and_types_fail_closed_without_breaking_settings(self):
        for value in ("{invalid", "null", '"/usr"', '[1]', {}, None):
            settings = Settings(_env_file=None, tesseract_sandbox_read_only_paths=value)
            self.assertEqual(settings.tesseract_sandbox_read_only_paths, [])
        self.assertEqual(Settings(_env_file=None, tesseract_sandbox_read_only_paths='["/usr/bin/pdfinfo"]').tesseract_sandbox_read_only_paths, ["/usr/bin/pdfinfo"])

    def test_real_environment_malformed_json_does_not_fail_boot(self):
        result = subprocess.run([sys.executable, "-c",
            "from app.core.config import Settings; assert Settings(_env_file=None).tesseract_sandbox_read_only_paths == []"],
            env={"PATH": os.defpath, "PYTHONPATH": os.environ["PYTHONPATH"], "PYTHONDONTWRITEBYTECODE": "1",
                 "TESSERACT_SANDBOX_READ_ONLY_PATHS": "bad-json"}, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr[-200:])

    def test_empty_runtime_refuses_before_creating_output(self):
        from app.domain.ocr_sandbox import run_ocr_sandbox
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "out.pdf"
            with self.assertRaises(AppError) as caught:
                run_ocr_sandbox(Settings(_env_file=None, tesseract_sandbox_read_only_paths=[]), root,
                    ["pdfinfo"], deadline=perf_counter() + 5, error_code="pdf_failed", output_paths=(target,))
            self.assertEqual(caught.exception.code, "ocr_tesseract_runtime_unavailable")
            self.assertFalse(target.exists())

    @unittest.skipUnless(sys.platform == "linux", "real Linux mountinfo required")
    def test_sensitive_broad_relative_and_actual_symlink_paths_rejected(self):
        from app.domain.ocr_sandbox import runtime_mounts
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / "parser-link"
            link.symlink_to("/etc/passwd")
            for paths in (["/"], ["/usr"], ["/usr/lib"], ["/etc"], ["/proc/self/environ"], ["/run/secrets"],
                          ["/usr/bin/../lib"], ["usr/bin/pdfinfo"], [str(link)], ["/usr/bin/no-such-parser"]):
                with self.assertRaises(AppError) as caught:
                    runtime_mounts(paths)
                self.assertEqual(caught.exception.code, "ocr_tesseract_runtime_unavailable")


class BoundedProcessTests(unittest.TestCase):
    def start(self, program):
        # These are lifecycle probes, not an unsandboxed PDF/OCR fallback.
        return subprocess.Popen([sys.executable, "-c", program], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, start_new_session=True,
            env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})

    def test_real_stdout_and_stderr_are_both_drained(self):
        from app.domain.ocr_sandbox import collect_bounded
        process = self.start("import os; os.write(1,b'a'*32768); os.write(2,b'b'*32768)")
        output, errors = collect_bounded(process, deadline=perf_counter() + 5, output_limit=65536)
        self.assertEqual((len(output), len(errors), process.returncode), (32768, 32768, 0))
        self.assertTrue(process.stdout.closed and process.stderr.closed)

    def test_real_nonzero_exit_preserves_runtime_and_document_error_contracts(self):
        from app.domain.ocr_sandbox import _process_error, collect_bounded
        process = self.start("import os; os.write(2,b'private-test-payload'); raise SystemExit(7)")
        _, stderr = collect_bounded(process, deadline=perf_counter() + 5, output_limit=1024)
        self.assertEqual(process.returncode, 7)
        for code, status in (("ocr_tesseract_runtime_unavailable", 503), ("ocr_tesseract_failed", 422)):
            with self.subTest(code=code):
                error = _process_error(code, process.returncode, stderr)
                self.assertEqual((error.code, error.status_code), (code, status))
                self.assertNotIn("private-test-payload", str(error) + repr(error.details))

    def test_real_combined_output_limit_kills_process(self):
        from app.domain.ocr_sandbox import collect_bounded
        process = self.start("import os; os.write(1,b'a'*40000); os.write(2,b'b'*40000)")
        with self.assertRaises(AppError) as caught:
            collect_bounded(process, deadline=perf_counter() + 5, output_limit=65536)
        self.assertEqual(caught.exception.code, "ocr_tesseract_output_limit")
        self.assertIsNotNone(process.poll())

    def test_real_timeout_closes_pipes_and_reaps_own_leader(self):
        from app.domain.ocr_sandbox import collect_bounded
        process = self.start("import time; time.sleep(20)")
        with self.assertRaises(AppError) as caught:
            collect_bounded(process, deadline=perf_counter() + 0.2, output_limit=1024)
        self.assertEqual(caught.exception.code, "ocr_tesseract_timeout")
        self.assertEqual(process.returncode, -signal.SIGKILL)
        self.assertTrue(process.stdout.closed and process.stderr.closed)

    @unittest.skipUnless(sys.platform == "linux", "Linux child process observation")
    def test_pipe_holding_child_does_not_survive_timeout(self):
        from app.domain.ocr_sandbox import collect_bounded
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "child.pid"
            program = ("import os,time; from pathlib import Path; pid=os.fork(); "
                       f"Path({str(receipt)!r}).write_text(str(pid)) if pid else None; time.sleep(20)")
            process = self.start(program)
            deadline = perf_counter() + 3
            while not receipt.exists() and perf_counter() < deadline:
                sleep(0.02)
            self.assertTrue(receipt.exists())
            child = int(receipt.read_text())
            with self.assertRaises(AppError):
                collect_bounded(process, deadline=perf_counter() + 0.1, output_limit=1024)
            deadline = perf_counter() + 2
            child_state = ""
            while perf_counter() < deadline:
                path = Path(f"/proc/{child}/status")
                if not path.exists():
                    child_state = "absent"
                    break
                child_state = next(line for line in path.read_text().splitlines() if line.startswith("State:"))
                if "Z" in child_state:
                    break  # Exited orphan awaits container PID1 reaping; not running.
                sleep(0.02)
            self.assertTrue(child_state == "absent" or "Z" in child_state)


if __name__ == "__main__":
    unittest.main()
