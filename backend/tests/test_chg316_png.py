"""Actual Poppler input validation, not simulated renderer/provider behavior."""
from __future__ import annotations
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from app.core.config import Settings
from scripts.native_pdf_input import pdf_input


@pytest.fixture(scope="module")
def png_image(tmp_path_factory):
    directory = tmp_path_factory.mktemp("native-png")
    directory.chmod(0o700)
    evidence = {}
    try:
        tool = shutil.which("pdftoppm")
        if tool is None:
            raise RuntimeError("PNG_PREREQUISITE_POPPLER_MISSING")
        source = directory / "input.pdf"
        source.write_bytes(pdf_input())
        source.chmod(0o600)
        environment = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "TMPDIR") if key in os.environ}
        try:
            result = subprocess.run([tool, "-f", "1", "-l", "1", "-singlefile", "-r", "200", "-png",
                                     str(source), str(directory / "page")],
                                    env=environment, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("PNG_PREREQUISITE_RENDER_TIMEOUT") from error
        if result.returncode:
            raise RuntimeError("PNG_PREREQUISITE_RENDER_FAILED")
        target = directory / "page.png"
        if not target.is_file() or target.is_symlink():
            raise RuntimeError("PNG_PREREQUISITE_OUTPUT_MISSING")
        body = target.read_bytes()
        evidence = dict(poppler_exit=result.returncode, pdf_sha256=sha256(source.read_bytes()).hexdigest(),
                        png_sha256=sha256(body).hexdigest(), dimensions=list(struct.unpack(">II", body[16:24])))
        yield body
    finally:
        shutil.rmtree(directory)
        evidence["private_files_removed"] = not directory.exists()
        receipt = os.environ.get("NOMOSMART_NATIVE_PNG_RECEIPT")
        if receipt:
            path = Path(receipt)
            assert path.parent == Path("/run/regression") and not path.is_symlink()
            assert path.parent.stat().st_uid == os.getuid() and path.parent.stat().st_mode & 0o077 == 0
            path.write_text(json.dumps(evidence))
            path.chmod(0o600)


def test_complete_image_structure(png_image):
    from app.domain.local_pdf.png import validate_png
    v = validate_png(png_image, max_bytes=67108864, max_pixels=40000000)
    assert (v['width'], v['height'], v['bytes']) == (1701, 2201, len(png_image))


@pytest.mark.parametrize('damage', ['truncate', 'crc', 'trailing'])
def test_corrupt_image_rejected(damage, png_image):
    from app.domain.local_pdf.png import validate_png
    from app.domain.local_pdf.errors import Rejected
    s = png_image
    body = s[:-7] if damage == 'truncate' else s[:20] + bytes([s[20] ^ 1]) + s[21:] if damage == 'crc' else s + b'junk'
    with pytest.raises(Rejected):
        validate_png(body, max_bytes=67108864, max_pixels=40000000)


def test_resource_limits(png_image):
    from app.domain.local_pdf.png import validate_png
    from app.domain.local_pdf.errors import Rejected
    with pytest.raises(Rejected):
        validate_png(png_image, max_bytes=32, max_pixels=40000000)
    with pytest.raises(Rejected):
        validate_png(png_image, max_bytes=67108864, max_pixels=100)


def test_typed_dpi():
    assert Settings(_env_file=None, pdf_ocr_dpi=150).pdf_ocr_dpi == 150
    assert Settings(_env_file=None, NOMOSMART_PDF_OCR_DPI=300).pdf_ocr_dpi == 300
    from pydantic import ValidationError
    for v in [99, 301]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, pdf_ocr_dpi=v)
