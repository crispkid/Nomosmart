"""CHG-391 directly affected controls; real immutable runtime, no test doubles."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
from time import perf_counter, time_ns
import unittest

from app.core.config import Settings
from app.core.errors import AppError

OBSERVATIONS: dict = {"negative_inputs": []}


def children() -> str:
    return Path(f"/proc/self/task/{os.getpid()}/children").read_text().strip()


class ParserEnvironmentControls(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="chg391-live-")
        self.root = Path(self.directory.name)
        self.settings = Settings(_env_file=None,
            tesseract_sandbox_read_only_paths=json.loads(os.environ["CHG304_R2_RUNTIME_PATHS"]),
            max_upload_size_mb=1)

    def tearDown(self):
        self.directory.cleanup()

    def run_parser(self, args, inputs=(), outputs=(), settings=None):
        from app.domain.ocr_sandbox import run_ocr_sandbox
        return run_ocr_sandbox(settings or self.settings, self.root, args,
            input_paths=tuple(inputs), output_paths=tuple(outputs),
            deadline=perf_counter() + 10, error_code="chg391_probe_denied")

    def require_positive(self):
        if os.environ.get("CHG391_POSITIVE_SUCCEEDED") != "1":
            self.skipTest("BLOCKED: original positive environment case did not pass")

    def test_missing_env_and_assignment_ambiguous_command_refuse_before_launch(self):
        env = Path(shutil.which("env", path=os.defpath)).resolve(strict=True)
        without_env = [p for p in self.settings.tesseract_sandbox_read_only_paths
                       if Path(p).resolve(strict=True) != env]
        self.assertLess(len(without_env), len(self.settings.tesseract_sandbox_read_only_paths))
        settings = self.settings.model_copy(update={"tesseract_sandbox_read_only_paths": without_env})
        source = self.root / "input.txt"
        source.write_bytes(b"CHG391_SYNTHETIC_INPUT")
        output = self.root / "unexpected.out"
        for label, config, command in (
            ("missing_env", settings, ["cat", str(source)]),
            ("assignment_ambiguous", self.settings, ["chg391=invalid"]),
        ):
            with self.subTest(input=label):
                before = children()
                os.write(2, f"CHG391_NEGATIVE_BEGIN:{label}\n".encode())
                event = {"input": label, "PID": os.getpid(), "start_ns": time_ns(),
                         "children_before": before}
                try:
                    with self.assertRaises(AppError) as caught:
                        self.run_parser(command, [source], [output], settings=config)
                    self.assertEqual(caught.exception.code, "ocr_tesseract_runtime_unavailable")
                    self.assertEqual(caught.exception.status_code, 503)
                    self.assertFalse(output.exists())
                    self.assertEqual(source.read_bytes(), b"CHG391_SYNTHETIC_INPUT")
                    self.assertEqual(children(), before)
                    self.assertEqual(list(self.root.iterdir()), [source])
                    event.update(actual_code=caught.exception.code, actual_status=503,
                                 output_absent=True, children_after=children(), assertions_passed=True)
                finally:
                    event["end_ns"] = time_ns()
                    OBSERVATIONS["negative_inputs"].append(event)
                    os.write(2, f"CHG391_NEGATIVE_END:{label}\n".encode())

    def test_final_exec_retains_inner_cap0_nnp_and_readonly(self):
        self.require_positive()
        result = self.run_parser(["cat", "/proc/self/status", "/proc/self/mountinfo"])
        text = result.stdout.decode()
        fields = ("Uid:", "Gid:", "CapEff:", "CapBnd:", "NoNewPrivs:", "Seccomp:")
        status = [line for line in text.splitlines() if line.startswith(fields)]
        self.assertEqual(next(line for line in status if line.startswith("Uid:")).split()[1:], ["58903"] * 4)
        self.assertEqual(next(line for line in status if line.startswith("Gid:")).split()[1:], ["58903"] * 4)
        self.assertIn("CapEff:\t0000000000000000", status)
        self.assertIn("CapBnd:\t0000000000000000", status)
        self.assertIn("NoNewPrivs:\t1", status)
        mountinfo = [line for line in text.splitlines() if " - " in line]
        kept = {}
        for path in ("/", "/proc"):
            mounts = [line for line in mountinfo if line.split()[4] == path]
            self.assertEqual(len(mounts), 1)
            self.assertIn("ro", mounts[0].split()[5].split(","))
            kept[path] = mounts[0]
        OBSERVATIONS["inner_security"] = status
        OBSERVATIONS["inner_mounts"] = kept

    def test_one_page_raster_and_tesseract_after_env_normalization(self):
        self.require_positive()
        before = children()
        source = self.root / "source.pdf"
        source.write_bytes(Path("/sample.pdf").read_bytes())
        image = self.root / "first.png"
        self.run_parser(["pdftoppm", "-f", "1", "-l", "1", "-png", "-r", "100",
                         "-singlefile", str(source), str(self.root / "first")], [source], [image])
        self.assertTrue(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        result = self.run_parser(["tesseract", str(image), "stdout", "-l", "eng"], [image])
        self.assertIn(b"PHYSICAL PAGE", result.stdout)
        self.assertEqual(set(self.root.iterdir()), {source, image})
        self.assertEqual(children(), before)
        OBSERVATIONS["one_page_OCR"] = {"rendered_page": 1, "render_calls": 1,
            "tesseract_calls": 1, "expected_text_observed": True,
            "only_declared_output": True, "children_after": children()}
