"""Real Poppler/Tesseract: explicitly BLOCKED without installed tools/assets.

Run separately from local lifecycle tests. Skips are NOT PDF acceptance PASS.
No network, containers, database or Provider; no fake model/transport.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

from app.core.config import Settings
from test_chg305_r20_local_pdf import policy
from pdf_local_samples import CHINESE, document


class RealPDFTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings(_env_file=None)
        missing = [name for name in ("pdfinfo", "pdftotext", "pdfseparate", "pdftoppm", "tesseract") if not shutil.which(name)]
        if missing or not importlib.util.find_spec("reportlab") or not importlib.util.find_spec("PIL"):
            raise unittest.SkipTest("BLOCKED: real Poppler/Tesseract, ReportLab and Pillow required")
        if not Path(cls.settings.pdf_encoding_data_dir).is_dir():
            raise unittest.SkipTest("BLOCKED: configured Poppler encoding assets required")

    def parse(self, body, program="text", **overrides):
        from app.domain.local_pdf.runner import LocalPDF
        with tempfile.TemporaryDirectory(prefix="r20-pdf-") as temporary:
            config = self.settings.model_copy(update={"pdf_scratch_dir": str(Path(temporary).resolve())})
            runner = LocalPDF(config, policy() | overrides, heartbeat=lambda: None, progress=lambda done,total: None)
            runner.setup()
            try:
                result = runner.run(body, program, ["eng"])
                pages = [runner.store.read(n) for n in range(1,result["pages"]+1)]
                runner.clean_parser()
                self.assertTrue(runner.stop_evidence("test-generation")["all_children_reaped"])
                return pages, result
            finally:
                runner.clean_parser()
                runner.store.close()
                self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_cjk_blanks_order_and_split_roundtrip(self):
        body = document()
        pages, result = self.parse(body)
        self.assertEqual(result["pages"], 3)
        self.assertIn(CHINESE.encode(), pages[0])
        self.assertEqual(pages[1], b"")
        self.assertIn(b"PHYSICAL PAGE 003", pages[2])
        split, _ = self.parse(body, "split")
        self.assertEqual(len(split), 3)
        for number, page in enumerate(split):
            self.assertEqual(self.parse(page)[0], [pages[number]])

    def test_40_200_pages_not_truncated(self):
        from app.domain.local_pdf.errors import Rejected
        for count in (40, 200):
            pages, _ = self.parse(document(count), pdf_parser_timeout_seconds=1800)
            self.assertEqual(len(pages), count)
            for number, page in enumerate(pages, 1):
                self.assertIn(f"PHYSICAL PAGE {number:03d}".encode(), page)
                self.assertIn(CHINESE.encode(), page)
        with self.assertRaises(Rejected) as failure:
            self.parse(document(201))
        self.assertEqual(failure.exception.code, "page_limit")

    def test_invalid_and_encrypted_reject(self):
        from app.domain.local_pdf.errors import Rejected
        for body in (b"%PDF-broken", document(1, encrypted=True)):
            with self.assertRaises(Rejected):
                self.parse(body)

    def test_text_first_fallback_and_local_ocr(self):
        body = document(scanned=True)
        pages, result = self.parse(body, "text_or_split")
        self.assertEqual(result["operation"], "split")
        self.assertEqual(len(pages), 3)
        text, result = self.parse(body, "text_or_local_ocr")
        self.assertEqual(result["operation"], "local_ocr")
        self.assertEqual(text[1], b"")
        self.assertIn(b"PRODUCT", text[0].upper())
        self.assertIn("tesseract", result["tools"])


if __name__ == "__main__":
    unittest.main()
