"""Real private directories and child lifecycle. No mock services or stat values."""
from __future__ import annotations
import os
import errno
from pathlib import Path
import resource
import stat
import tempfile
import unittest

from app.core.config import Settings
from test_chg305_r20_local_pdf import policy


@unittest.skipUnless(os.environ.get('NOMOSMART_CURRENT_NATIVE_FILES_CONTEXT') or os.environ.get('NOMOSMART_R15_IMAGE_SMOKE') == '1' or os.environ.get('NOMOSMART_TEST_SCOPE') in {'/run/regression/current-scope.json', '/run/regression/chg349-scope.json', '/run/regression/chg351-scope.json', '/run/regression/chg361-scope.json'},
                     'BLOCKED: requires the R15 no-network image smoke and owned tmpfs mounts')
class StartupCleanup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('NOMOSMART_CURRENT_NATIVE_FILES_CONTEXT'):
            from current_native_files_support import verify_native_files_context
            verify_native_files_context()
            return
        if os.environ.get('NOMOSMART_TEST_SCOPE') in {'/run/regression/current-scope.json', '/run/regression/chg349-scope.json', '/run/regression/chg351-scope.json', '/run/regression/chg361-scope.json'}:
            from app.core.config import get_settings
            from owned_service_scope import verify_owned_services
            verify_owned_services(get_settings())
            status = Path('/proc/self/status').read_text()
            assert 'CapEff:\t0000000000000000' in status and 'NoNewPrivs:\t1' in status

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='r15-lifecycle-')
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, root=None):
        from app.domain.local_pdf.runner import LocalPDF
        settings = Settings(_env_file=None).model_copy(update={'pdf_scratch_dir': str(root or self.root)})
        self.progress = []
        self.heartbeats = []
        return LocalPDF(settings, policy(), heartbeat=lambda: self.heartbeats.append(True),
                        progress=lambda done,total: self.progress.append((done,total)))

    def test_exact_private_modes_and_inherited_setgid(self):
        from app.domain.local_pdf.files import PageStore, Workspace, ensure_root
        self.assertEqual(os.getuid(), 10001, 'Run the Linux image suite as the production UID')
        for mode in (0o700, 0o2700):
            with self.subTest(mode=oct(mode)):
                self.root.chmod(mode)
                ensure_root(self.root)
                leaf = self.root / ('leaf-'+str(mode))
                ensure_root(leaf)
                self.assertEqual(stat.S_IMODE(leaf.stat().st_mode), mode)
                for cls in (PageStore, Workspace):
                    store = cls(leaf)
                    self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), mode)
                    store.close()
                    store.close()
                self.assertEqual(list(leaf.iterdir()), [])
                self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), mode)

    def test_group_other_and_other_special_bits_rejected_unchanged(self):
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import PageStore, Workspace, ensure_root
        for mode in (0o770, 0o777, 0o2770, 0o4700, 0o1700, 0o3700):
            with self.subTest(mode=oct(mode)):
                self.root.chmod(mode)
                for operation in (ensure_root, PageStore, Workspace):
                    with self.assertRaises(Rejected):
                        operation(self.root)
                self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), mode)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_symlink_and_non_directory_are_not_changed(self):
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import PageStore, Workspace, ensure_root
        alias = self.root/'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        regular = self.root/'regular'
        regular.write_bytes(b'unchanged')
        for path in (alias, regular):
            for operation in (ensure_root, PageStore, Workspace):
                with self.assertRaises((Rejected, OSError)):
                    operation(path)
        self.assertTrue(alias.is_symlink())
        self.assertEqual(regular.read_bytes(), b'unchanged')

    def test_wrong_owner_rejected_without_mutation(self):
        # The smoke runner mounts this empty, private tmpfs with root ownership.
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import PageStore, Workspace, ensure_root
        root = Path('/owner-mismatch')
        self.assertEqual(root.stat().st_uid, 0)
        self.assertEqual(os.getuid(), 10001)
        for operation in (ensure_root, PageStore, Workspace):
            with self.assertRaises((Rejected, OSError)):
                operation(root)

    def test_prelaunch_invalid_root_can_prove_clean_failed_stop(self):
        from app.domain.local_pdf.errors import Rejected
        alias = self.root/'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        runner = self.runner(alias)
        with self.assertRaises((Rejected, OSError)):
            runner.setup()
        runner.clean_parser()
        runner.clean_parser()
        evidence = runner.stop_evidence('same-generation')
        self.assertEqual(evidence['child_count'], 0)
        self.assertTrue(evidence['cleanup_confirmed'])
        self.assertEqual(evidence['workload_uid'], runner.launch_uid)
        self.assertIsNone(runner.tools)
        self.assertEqual(set(self.root.iterdir()), {alias})

    def test_never_started_object_is_not_stop_evidence(self):
        from app.domain.local_pdf.errors import Rejected
        runner = self.runner()
        with self.assertRaises(Rejected):
            runner.clean_parser()
        with self.assertRaises(Rejected):
            runner.stop_evidence('unstarted')

    def test_real_fd_exhaustion_cleans_partial_setup(self):
        runner = self.runner()
        previous = resource.getrlimit(resource.RLIMIT_NOFILE)
        opened = []
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, previous[1]))
            while True:
                try:
                    opened.append(os.open('/dev/null', os.O_RDONLY))
                except OSError as error:
                    self.assertEqual(error.errno, errno.EMFILE)
                    break
            # Enough for a complete workspace, but not a second directory walk.
            for _ in range(3):
                os.close(opened.pop())
            with self.assertRaises(OSError) as failure:
                runner.setup()
            self.assertEqual(failure.exception.errno, errno.EMFILE)
        finally:
            for fd in opened:
                os.close(fd)
            resource.setrlimit(resource.RLIMIT_NOFILE, previous)
        self.assertTrue(runner.work.created)
        self.assertIsNotNone(runner.store)
        self.assertFalse(runner.store.created)
        self.assertTrue(runner.setup_cleanup_confirmed)
        self.assertIsNone(runner.work.fd)
        self.assertIsNone(runner.work.root)
        runner.clean_parser()
        self.assertEqual(runner.stop_evidence('partial')['child_count'], 0)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unknown_file_prevents_stop_proof_and_is_preserved(self):
        from app.domain.local_pdf.errors import Rejected
        runner = self.runner()
        runner.setup()
        unknown = runner.work.path/'unknown'
        unknown.write_bytes(b'preserve')
        with self.assertRaises(Rejected):
            runner.clean_parser()
        with self.assertRaises(Rejected):
            runner.clean_parser()
        with self.assertRaises(Rejected):
            runner.stop_evidence('unknown')
        self.assertEqual(unknown.read_bytes(), b'preserve')
        self.assertIsNone(runner.work.fd)
        self.assertIsNone(runner.work.root)
        runner.store.close()

    def test_replaced_directory_is_not_deleted(self):
        from app.domain.local_pdf.errors import Rejected
        from app.domain.local_pdf.files import PageStore
        store = PageStore(self.root)
        original = self.root/'original'
        store.path.rename(original)
        store.path.mkdir(mode=0o700)
        with self.assertRaises(Rejected):
            store.close()
        self.assertTrue(original.is_dir())
        self.assertTrue(store.path.is_dir())
        self.assertFalse(store.cleanup_confirmed)
        self.assertTrue(store.cleanup_failed)

    def test_closed_runner_cannot_launch_new_children(self):
        from app.domain.local_pdf.errors import Rejected
        runner = self.runner()
        runner.setup()
        with self.assertRaises(Rejected):
            runner.setup()
        runner.clean_parser()
        runner.store.close()
        with self.assertRaises(Rejected):
            runner.command('pdf_info_command', '-v')
        with self.assertRaises(Rejected):
            runner.run(b'%PDF-invalid', 'text', [])
        self.assertEqual(runner.tools.exits, [])

    def test_context_preserves_original_error_and_cleans_remaining_store(self):
        # Real context/resource behavior only; no database method is invoked.
        from sqlalchemy.orm import Session
        from app.domain.pdf_processing import PDFProcessing
        runner = self.runner()
        runner.setup()
        unknown = runner.work.path/'unknown'
        unknown.write_bytes(b'preserve')
        original = ValueError('original-safe-error')
        with Session() as session:
            owner = PDFProcessing(session=session, settings=runner.settings, claim=None,
                                  program='text', language_resolver=list)
            owner.local = runner
            with self.assertRaises(ValueError) as raised:
                with owner:
                    raise original
        self.assertIs(raised.exception, original)
        self.assertTrue(unknown.exists())
        self.assertTrue(runner.store.cleanup_confirmed)
        self.assertFalse(runner.cleaned)

    def test_context_cleanup_failure_is_visible_without_original_error(self):
        from sqlalchemy.orm import Session
        from app.core.errors import AppError
        from app.domain.pdf_processing import PDFProcessing
        runner = self.runner()
        runner.setup()
        (runner.work.path/'unknown').write_bytes(b'preserve')
        with Session() as session:
            owner = PDFProcessing(session=session, settings=runner.settings, claim=None,
                                  program='text', language_resolver=list)
            owner.local = runner
            with self.assertRaises(AppError) as raised:
                with owner:
                    pass
        self.assertEqual(raised.exception.code, 'file_processing_cleanup_failed')
        self.assertTrue(runner.store.cleanup_confirmed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
