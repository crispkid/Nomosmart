"""Real local processes/files and pure policies. No DB/runtime/Provider substitute."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from app.domain.file_processing_settings import FileProcessingSettings, PlatformCapabilities, ACTIVE_KEYS, DEPRECATED_KEYS


def policy():
    return dict(document_processing_max_concurrent=10, pdf_parser_max_concurrent=10,
        pdf_parser_cpu_millicores=1000, pdf_parser_memory_mib=768, pdf_parser_scratch_mib=256,
        pdf_parser_timeout_seconds=60, pdf_parser_max_pages=200, pdf_parser_max_output_mib=16,
        pdf_parser_retry_max_attempts=1, pdf_parser_retry_delay_seconds=5,
        pdf_parser_retryable_error_codes=[], file_processing_progress_interval_seconds=2,
        file_processing_background_poll_interval_seconds=15)


class LocalProcesses(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="r20-process-")
        self.root = Path(self.temporary.name).resolve()
        self.heartbeats = []

    def tearDown(self):
        self.temporary.cleanup()

    def tools(self, seconds=5):
        from app.domain.local_pdf.process import Tools
        return Tools(cwd=self.root, deadline=time.monotonic()+seconds, scratch_limit=1024**2,
                     check=lambda: None, heartbeat=lambda: self.heartbeats.append(time.monotonic()))

    def test_actual_exit_output_and_environment_allowlist(self):
        tool = self.tools()
        body = tool.run([sys.executable, "-I", "-c", "import os,json; print(json.dumps(dict(os.environ)))"])
        env = json.loads(body)
        platform_added = {"__CF_USER_TEXT_ENCODING"} if sys.platform == "darwin" else set()
        self.assertLessEqual(set(env), {"PATH", "HOME", "TMPDIR", "LANG", "LC_CTYPE", "OMP_THREAD_LIMIT"} | platform_added)
        self.assertEqual(env["HOME"], str(self.root))
        self.assertTrue(tool.stop_confirmed)
        self.assertEqual(tool.exits[0]["returncode"], 0)
        self.assertTrue(self.heartbeats)

    def test_real_nonzero_exit_is_not_success_and_stderr_is_not_exposed(self):
        from app.domain.local_pdf.errors import Rejected
        tool = self.tools()
        with self.assertRaises(Rejected) as failure:
            tool.run([sys.executable, "-I", "-c", "import sys; sys.stderr.write('private document'); sys.exit(9)"])
        self.assertEqual(str(failure.exception), "invalid_output")
        self.assertEqual(tool.exits[0]["returncode"], 9)
        self.assertTrue(tool.stop_confirmed)

    def test_real_timeout_reaps_only_owned_child(self):
        from app.domain.local_pdf.errors import Rejected
        other = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"])
        try:
            tool = self.tools(.2)
            with self.assertRaises(Rejected) as failure:
                tool.run([sys.executable, "-I", "-c", "import time; time.sleep(30)"])
            self.assertEqual(failure.exception.code, "deadline")
            self.assertTrue(tool.stop_confirmed)
            self.assertLess(tool.exits[0]["returncode"], 0)
            self.assertIsNone(other.poll())
            with self.assertRaises(ProcessLookupError):
                os.kill(tool.exits[0]["pid"], 0)
        finally:
            other.terminate()
            other.wait(timeout=5)

    def test_real_stdout_and_stderr_limits(self):
        from app.domain.local_pdf.errors import Rejected
        for stream in ("stdout", "stderr"):
            tool = self.tools()
            with self.assertRaises(Rejected) as failure:
                tool.run([sys.executable, "-I", "-c", f"import sys; sys.{stream}.write('x'*1000000)"],
                         stdout_limit=128, stderr_limit=128)
            self.assertEqual(failure.exception.code, "output_limit")
            self.assertTrue(tool.stop_confirmed)

    def test_deadline_still_kills_while_owner_callback_is_blocked(self):
        from app.domain.local_pdf.errors import Rejected
        tool = self.tools(.15)
        calls = []
        def owner_callback():
            calls.append(time.monotonic())
            if len(calls) == 2:
                time.sleep(.6)
        tool.heartbeat = owner_callback
        with self.assertRaises(Rejected) as failure:
            tool.run([sys.executable, "-I", "-c",
                "import time; from pathlib import Path; time.sleep(.35); Path('too-late').write_text('late')"])
        self.assertEqual(failure.exception.code, "deadline")
        self.assertFalse((self.root / "too-late").exists())
        self.assertTrue(tool.stop_confirmed)

    def test_owner_cancellation_stops_actual_running_child(self):
        tool = self.tools()
        def cancel():
            if len(self.heartbeats) >= 2:
                raise InterruptedError("owner cancelled")
            self.heartbeats.append(time.monotonic())
        tool.heartbeat = cancel
        with self.assertRaises(InterruptedError):
            tool.run([sys.executable, "-I", "-c", "import time; time.sleep(30)"])
        self.assertTrue(tool.stop_confirmed)
        self.assertEqual(len(tool.exits), 1)


class PrivateFiles(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="r20-files-")
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)

    def tearDown(self):
        self.temporary.cleanup()

    def test_pages_preserve_blank_utf8_and_exact_cleanup(self):
        from app.domain.local_pdf.files import PageStore
        store = PageStore(self.root)
        for number, body in enumerate(("提前清償😀".encode(), b"", b"third page"), 1):
            store.stage(number, body, page_limit=100, total_limit=300)
            self.assertEqual(store.read(number), body)
        owned = store.path
        store.close()
        self.assertFalse(owned.exists())
        store.close()

    def test_tampered_page_is_rejected(self):
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import PageStore
        store = PageStore(self.root)
        store.stage(1, b"original", page_limit=100, total_limit=100)
        (store.path / store.pages[0][0]).write_bytes(b"modified")
        with self.assertRaises(Rejected):
            store.read(1)
        store.close()

    def test_unknown_file_is_not_deleted(self):
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import PageStore
        store = PageStore(self.root)
        unknown = store.path / "not-owned"
        unknown.write_bytes(b"leave me")
        with self.assertRaises(Rejected):
            store.close()
        self.assertEqual(unknown.read_bytes(), b"leave me")
        # A second close must not turn a prior failed cleanup into success.
        with self.assertRaises(Rejected):
            store.close()

    def test_workspace_missing_output_and_budget(self):
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import Workspace
        store = Workspace(self.root)
        store.write_input(b"%PDF-test input")
        store.target("text.txt")
        self.assertEqual(store.usage(), 15)
        with self.assertRaises(Rejected):
            store.read_file("input.pdf", 1)
        store.close()

    def test_unknown_workspace_content_retained_and_descriptors_closed(self):
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import Workspace
        store = Workspace(self.root)
        unknown = store.path / "not-owned"
        unknown.write_bytes(b"leave me")
        descriptors = (store.fd, store.root)
        with self.assertRaises(Rejected):
            store.close()
        self.assertEqual(unknown.read_bytes(), b"leave me")
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        with self.assertRaises(Rejected):
            store.close()

    def test_symlink_root_refused(self):
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import PageStore
        alias = self.root / "link"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((Rejected, OSError)):
            PageStore(alias)

    def test_private_root_created_without_changing_existing_permissions(self):
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import ensure_root
        target = self.root / "new"
        ensure_root(target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        target.chmod(0o755)
        with self.assertRaises(Rejected):
            ensure_root(target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)


class PolicyCompatibility(unittest.TestCase):
    def test_thirteen_values_and_hash_are_preserved(self):
        values = policy()
        actual = FileProcessingSettings.model_validate(values)
        digest = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(actual.content_hash, digest)
        self.assertEqual(actual.model_dump(mode="json"), values)
        self.assertEqual(ACTIVE_KEYS, {
            "document_processing_max_concurrent", "pdf_parser_timeout_seconds",
            "file_processing_progress_interval_seconds", "file_processing_background_poll_interval_seconds",
        })
        self.assertEqual(ACTIVE_KEYS | DEPRECATED_KEYS, set(values))
        self.assertFalse(ACTIVE_KEYS & DEPRECATED_KEYS)
        self.assertEqual(len(DEPRECATED_KEYS), 9)

    def test_scratch_no_longer_depends_on_retired_memory(self):
        actual = FileProcessingSettings.model_validate(policy() | {"pdf_parser_scratch_mib": 1024})
        PlatformCapabilities({}).validate(actual)

    def test_legacy_container_ceiling_ignored_only_for_retired_fields(self):
        values = FileProcessingSettings.model_validate(policy())
        caps = {k: getattr(values, k) for k in ("document_processing_max_concurrent", "pdf_parser_max_concurrent",
            "pdf_parser_scratch_mib", "pdf_parser_timeout_seconds", "pdf_parser_max_pages", "pdf_parser_max_output_mib")}
        PlatformCapabilities(caps | {"pdf_parser_cpu_millicores": 1, "pdf_parser_memory_mib": 1}).validate(values)
        from app.core.errors import AppError
        # Retired local-parser ceilings remain readable without governing native
        # input. Active document admission and total deadline must still reject.
        for active in ("document_processing_max_concurrent", "pdf_parser_timeout_seconds"):
            with self.subTest(active=active):
                with self.assertRaises(AppError):
                    PlatformCapabilities(caps | {active: 1}).validate(values)


if __name__ == "__main__":
    unittest.main()
