"""Real installed tools against the retained R14 PDFs, mounted read-only.

No generated/fake parser output, database, network, or model call. This does not
claim application workflow acceptance or database lease-release coverage.
"""
from __future__ import annotations
import hashlib
import importlib
import json
import os
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest

from app.core.config import Settings
from test_chg305_r20_local_pdf import policy


@unittest.skipUnless(os.environ.get('NOMOSMART_R15_IMAGE_SMOKE') == '1' or bool(os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT')),
                     'BLOCKED: requires the R15 product-image smoke and read-only R14 PDF samples')
class ExistingPDFSamples(unittest.TestCase):
    def setUp(self):
        self.current_samples = None
        if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
            from current_live_support import load_current_context
            context = load_current_context()
            allowed = {"test_chinese_blank_and_page_order_with_split_roundtrip",
                       "test_scan_fallback_and_actual_local_ocr", "test_malformed_pdf_reaps_child_and_cleans"}
            self.assertIn(self._testMethodName, allowed, "Product image packaging requires the actual candidate image")
            from scripts.current_e2e_governance_fixture import read_private
            root = Path(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"]).parent
            proof = read_private(root / "current-pdf-samples.json")
            authority = read_private(root / "scope.json")
            self.assertEqual(proof["operation_uuid"], authority["operation_uuid"])
            self.assertEqual(proof["run_id"], context["run_id"])
            self.assertEqual(proof["source_inventory_sha256"], authority["public_inventory"]["sha256"])
            self.assertEqual(proof["purpose"], "new_synthetic_current_native_tools_not_R14_custody_or_product_image")
            self.assertEqual(set(proof["samples"]), {"text-blank.pdf", "scanned.pdf"})
            import stat
            self.current_samples = {}
            for name, metadata in proof["samples"].items():
                path = root / "pdf-samples" / name
                self.assertEqual(path.resolve(), path)
                self.assertFalse(path.is_symlink())
                info = path.stat()
                self.assertEqual((info.st_uid, stat.S_IMODE(info.st_mode), info.st_nlink), (os.getuid(), 0o600, 1))
                data = path.read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), metadata["sha256"])
                self.assertEqual(len(data), metadata["bytes"])
                self.current_samples[name] = data

    def sample(self, name):
        return self.current_samples[name] if self.current_samples is not None else Path("/samples", name).read_bytes()

    def test_runtime_packaging_nonroot_and_installed_tools(self):
        self.assertEqual((os.getuid(), os.getgid()), (10001, 10001))
        for path in ('/app/tests','/app/pdf_executor','/app/pdf_coordinator','/app/pdf_start_guard'):
            self.assertFalse(Path(path).exists(), path)
        self.assertEqual(sorted(p.name for p in Path('/app/scripts').iterdir()), ['soft_deleted_residue_cleanup.py'])
        status = Path('/proc/self/status').read_text()
        self.assertIn('CapEff:\t0000000000000000', status)
        self.assertIn('NoNewPrivs:\t1', status)
        for name in ('app.domain.local_pdf.runner','app.domain.file_processing_dispatch'):
            importlib.import_module(name)
        versions = {}
        for name in ('pdfinfo','pdftotext','pdfseparate','pdftoppm','tesseract'):
            self.assertIsNotNone(shutil.which(name))
            q = subprocess.run([name, '--version' if name in ('tesseract') else '-v'],
                               capture_output=True,text=True,timeout=5)
            self.assertEqual(q.returncode, 0)
            versions[name] = (q.stdout or q.stderr).splitlines()[0]
        print(json.dumps({'runtime_uid':os.getuid(),'versions':versions}))

    def parse(self, body, program='text'):
        from app.domain.local_pdf.runner import LocalPDF
        with tempfile.TemporaryDirectory(prefix='r15-real-pdf-') as temporary:
            root = Path(temporary).resolve()
            root.chmod(0o2700)
            settings = Settings(_env_file=None).model_copy(update={'pdf_scratch_dir': str(root)})
            progress, heartbeats = [], []
            runner = LocalPDF(settings, policy(), heartbeat=lambda: heartbeats.append(True),
                              progress=lambda done, total: progress.append((done, total)))
            runner.setup()
            try:
                result = runner.run(body, program, ['eng'])
                pages = [runner.store.read(n) for n in range(1, result['pages'] + 1)]
                self.assertEqual(result['input_hash'], hashlib.sha256(body).hexdigest())
                self.assertEqual(result['sha256'], hashlib.sha256(b''.join(pages)).hexdigest())
                self.assertEqual(result['bytes'], sum(map(len, pages)))
                self.assertEqual(progress[-1], (len(pages), len(pages)))
                self.assertEqual(sorted(n for n, _ in progress), [n for n, _ in progress])
                self.assertTrue(heartbeats)
                runner.clean_parser()
                evidence = runner.stop_evidence('real-sample')
                self.assertGreater(evidence['child_count'], 0)
                self.assertTrue(evidence['all_children_reaped'])
                self.assertTrue(evidence['all_exits_zero'])
                return pages, result
            finally:
                runner.clean_parser()
                runner.store.close()
                runner.store.close()
                self.assertEqual(list(root.iterdir()), [])

    def test_chinese_blank_and_page_order_with_split_roundtrip(self):
        body = self.sample('text-blank.pdf')
        pages, result = self.parse(body, 'text_or_split')
        self.assertEqual(result['operation'], 'text')
        self.assertEqual(len(pages), 3)
        self.assertIn('房貸產品方案：提前清償規定。'.encode(), pages[0])
        self.assertIn(b'PHYSICAL PAGE 001', pages[0])
        self.assertEqual(pages[1], b'')
        self.assertIn(b'PHYSICAL PAGE 003', pages[2])
        split, result = self.parse(body, 'split')
        self.assertEqual(len(split), 3)
        for number, part in enumerate(split):
            self.assertTrue(part.startswith(b'%PDF-'))
            self.assertEqual(self.parse(part)[0], [pages[number]])

    def test_scan_fallback_and_actual_local_ocr(self):
        body = self.sample('scanned.pdf')
        pages, result = self.parse(body, 'text')
        self.assertEqual(pages, [b''])
        pages, result = self.parse(body, 'text_or_split')
        self.assertEqual(result['operation'], 'split')
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].startswith(b'%PDF-'))
        pages, result = self.parse(body, 'text_or_local_ocr')
        self.assertEqual(result['operation'], 'local_ocr')
        self.assertIn(b'PRODUCT A RATE 2.1 PERCENT', pages[0].upper())
        self.assertIn('tesseract', result['tools'])

    def test_malformed_pdf_reaps_child_and_cleans(self):
        from app.domain.local_pdf.errors import Rejected
        with self.assertRaises(Rejected):
            self.parse(b'%PDF-invalid')


if __name__ == '__main__':
    unittest.main(verbosity=2)
