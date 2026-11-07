"""Real Linux upload scratch modes/lifetimes; run with owned disk and tmpfs mounts."""
import os
from pathlib import Path
import stat
import tempfile
import unittest

from app.core.config import Settings
from app.core.errors import AppError
from app.domain import upload_stream


class UploadScratchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('NOMOSMART_CURRENT_NATIVE_FILES_CONTEXT'):
            from current_native_files_support import verify_native_files_context
            verify_native_files_context()
        assert os.environ.get('NOMOSMART_R23R7_SCRATCH_TEST') == 'run-owned'
        assert os.getuid() == os.getgid() == 10001
        assert Path('/proc/self/mountinfo').is_file()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='upload-', dir='/scratch')
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.counts = upload_stream._inflight, upload_stream._reserved
        self.fds = len(os.listdir('/proc/self/fd'))

    def tearDown(self):
        self.root.chmod(0o700)
        self.temp.cleanup()
        self.assertEqual((upload_stream._inflight, upload_stream._reserved), self.counts)
        self.assertEqual(len(os.listdir('/proc/self/fd')), self.fds)

    def lease(self, path=None, **settings):
        config = Settings(_env_file=None, NOMOSMART_UPLOAD_SCRATCH_DIR=str(path or self.root), **settings)
        return upload_stream.UploadLease(config)

    def assert_private_file(self, path):
        lease = self.lease(path)
        try:
            lease.open()
            self.assertEqual(stat.S_IMODE(os.fstat(lease.file.fileno()).st_mode), 0o600)
            data = '原始\r\nMarkdown\x00😀'.encode()
            lease.write(data)
            lease.file.seek(0)
            self.assertEqual(lease.file.read(), data)
        finally:
            lease.close()
            lease.close()
        self.assertEqual(list(path.iterdir()), [])

    def test_0700_disk(self):
        self.assert_private_file(self.root)

    def test_02700_disk(self):
        self.root.chmod(0o2700)
        self.assert_private_file(self.root)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o2700)

    def test_natural_setgid_inheritance(self):
        self.root.chmod(0o2700)
        child = self.root / 'private'
        lease = self.lease(child)
        try:
            lease.open()
            self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o2700)
            self.assertEqual(child.stat().st_uid, os.getuid())
        finally:
            lease.close()
        self.assert_private_file(child)

    def test_unsafe_modes_rejected_without_mutation(self):
        for mode in (0o770, 0o777, 0o2770, 0o4700, 0o1700, 0o3700):
            with self.subTest(mode=oct(mode)):
                self.root.chmod(mode)
                self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), mode)
                lease = self.lease()
                try:
                    with self.assertRaises(AppError) as caught:
                        lease.open()
                    self.assertEqual(caught.exception.code, 'upload_temporary_storage_unavailable')
                    self.assertEqual(caught.exception.status_code, 503)
                finally:
                    lease.close()
                self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), mode)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_symlink_and_file_are_rejected(self):
        real = self.root / 'real'
        real.mkdir(mode=0o700)
        alias = self.root / 'alias'
        alias.symlink_to(real, target_is_directory=True)
        plain = self.root / 'plain'
        plain.write_bytes(b'unchanged')
        for path in (alias, plain):
            lease = self.lease(path)
            try:
                with self.assertRaises((OSError, AppError)):
                    lease.open()
            finally:
                lease.close()
        self.assertTrue(alias.is_symlink())
        self.assertEqual(plain.read_bytes(), b'unchanged')
        self.assertEqual(list(real.iterdir()), [])

    def test_wrong_owner_is_rejected(self):
        path = Path('/scratch/wrong-owner')
        self.assertEqual(path.stat().st_uid, 0)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        lease = self.lease(path)
        try:
            with self.assertRaises((OSError, AppError)):
                lease.open()
        finally:
            lease.close()
        self.assertEqual(path.stat().st_uid, 0)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

    def test_actual_tmpfs_rejected(self):
        path = Path('/memory')
        self.assertEqual(path.stat().st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        lease = self.lease(path)
        try:
            with self.assertRaises(AppError) as caught:
                lease.open()
            self.assertEqual(caught.exception.code, 'upload_temporary_storage_unavailable')
        finally:
            lease.close()
        self.assertEqual(list(path.iterdir()), [])

    def test_failure_releases_capacity_and_private_retry_succeeds(self):
        self.root.chmod(0o770)
        lease = self.lease(NOMOSMART_UPLOAD_MAX_INFLIGHT=1)
        with self.assertRaises(AppError):
            lease.open()
        self.assertFalse(lease.admitted)
        self.assertEqual((upload_stream._inflight, upload_stream._reserved), self.counts)
        self.root.chmod(0o700)
        self.assert_private_file(self.root)

    def test_full_slot_rejects_then_releases(self):
        lease = self.lease(NOMOSMART_UPLOAD_MAX_INFLIGHT=1)
        other = self.lease(NOMOSMART_UPLOAD_MAX_INFLIGHT=1)
        try:
            lease.open()
            with self.assertRaises(AppError) as caught:
                other.open()
            self.assertEqual(caught.exception.code, 'upload_capacity_exhausted')
        finally:
            other.close()
            lease.close()
        self.assert_private_file(self.root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
