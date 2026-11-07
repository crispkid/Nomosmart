"""Physical page regressions migrated to the current Worker-local PDF runner.

Generate one synthetic input using the bundled document runtime:
  python test_chg304_pdf_pages.py --create-fixture /private/tmp/.../sample.pdf
Run real tools with CHG304_PDF_SAMPLE; absence remains BLOCKED, not acceptance.
"""
from __future__ import annotations
import os
from pathlib import Path
import sys
import unittest

if len(sys.argv) == 3 and sys.argv[1] == "--create-fixture":
    from reportlab.pdfgen import canvas
    target = Path(sys.argv[2])
    if not str(target).startswith("/private/tmp/nomosmart-chg304-") or target.exists():
        raise SystemExit("new private run-owned output required")
    pdf = canvas.Canvas(str(target), pagesize=(600, 800), invariant=1)
    pdf.setFont("Helvetica", 18)
    pdf.drawString(45, 740, "FIRST PHYSICAL PAGE")
    pdf.drawString(45, 700, "Product A: 2.1 percent")
    pdf.showPage()
    pdf.showPage()  # Blank physical middle page, intentionally retained.
    pdf.setFont("Helvetica", 18)
    pdf.drawString(45, 740, "THIRD PHYSICAL PAGE")
    pdf.drawString(45, 700, "Product B: 2.3 percent")
    pdf.save()
    raise SystemExit(0)

from time import perf_counter
from app.core.config import Settings
from app.domain.extraction_pipeline import (
    _joined_page_ranges, _valid_page_ranges,
)
from local_pdf_compatibility import physical_pdf_inputs
from app.domain.markdown_structure import MarkdownStructureParser


class PageRangeTests(unittest.TestCase):
    def test_empty_pages_keep_indices_and_unicode_offsets(self):
        pages = ["", "# 一頁😀\n\n業務內容。", "", "第三段", ""]
        raw = "\n\n".join(pages)
        ranges = _joined_page_ranges(pages)
        self.assertEqual(_valid_page_ranges(ranges, raw), ranges)
        for index, item in enumerate(ranges):
            self.assertEqual(raw[item["start_offset"]:item["end_offset"]], pages[index])
            self.assertEqual(item["page"], index + 1)
        structure = MarkdownStructureParser().parse(raw, page_ranges=ranges)
        node = next(n for n in structure.nodes if n.text == "第三段")
        self.assertEqual((node.page_start, node.page_end), (4, 4))

    def test_bad_ranges_are_unknown_not_invented(self):
        for ranges in ([{"page": 0, "start_offset": 0, "end_offset": 1}],
                       [{"page": 1, "start_offset": 0, "end_offset": 9}],
                       [{"page": 2, "start_offset": 0, "end_offset": 1}, {"page": 1, "start_offset": 1, "end_offset": 2}]):
            self.assertEqual(_valid_page_ranges(ranges, "abc"), [])


@unittest.skipUnless(os.environ.get("CHG304_PDF_SAMPLE"), "BLOCKED: real PDF input not configured")
class PhysicalPDFTests(unittest.TestCase):
    def setUp(self):
        self.body = Path(os.environ["CHG304_PDF_SAMPLE"]).read_bytes()
        self.settings = Settings(_env_file=None)

    def test_real_text_pages_and_single_page_inputs(self):
        pages = physical_pdf_inputs(self.settings, self.body, text_only=True, deadline=perf_counter() + 60)
        self.assertEqual(len(pages), 3)
        self.assertIn("FIRST PHYSICAL PAGE", pages[0])
        self.assertEqual(pages[1], "")
        self.assertIn("THIRD PHYSICAL PAGE", pages[2])
        split = physical_pdf_inputs(self.settings, self.body, text_only=False, deadline=perf_counter() + 60)
        self.assertEqual(len(split), 3)
        for index, (_, media_type, body) in enumerate(split):
            self.assertEqual(media_type, "application/pdf")
            self.assertEqual(physical_pdf_inputs(self.settings, body, text_only=True, deadline=perf_counter() + 60), [pages[index]])

    def test_limits_and_expired_deadline_refuse_without_provider(self):
        from app.domain.local_pdf.errors import Rejected
        with self.assertRaises(Rejected) as caught:
            physical_pdf_inputs(self.settings.model_copy(update={"tesseract_max_pages": 2}), self.body,
                                text_only=False, deadline=perf_counter() + 60)
        self.assertEqual(caught.exception.code, "page_limit")
        with self.assertRaises(Rejected) as caught:
            physical_pdf_inputs(self.settings, self.body, text_only=True, deadline=perf_counter() - 1)
        self.assertEqual(caught.exception.code, "deadline")


if __name__ == "__main__":
    unittest.main()
