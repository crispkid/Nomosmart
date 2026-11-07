"""Actual filesystem/coverage regressions. Source prepared in R11 A; not executed."""
import importlib.util
import json
import os
from pathlib import Path
import stat

from coverage import Coverage
import pytest

_source = Path(__file__).parents[1] / "scripts/chg305_r9/private_report.py"
_spec = importlib.util.spec_from_file_location("chg305_private_report", _source)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
write_private_report = _module.write_private_report


def test_actual_coverage_file_is_private_from_creation(tmp_path):
    tmp_path.chmod(0o700)
    destination = tmp_path / "coverage.json"
    coverage = Coverage(config_file=False, branch=True, data_file=None)
    coverage.start()
    # Collect actual helper execution, not injected lines or fabricated coverage.
    write_private_report(tmp_path / "first.json", lambda path: Path(path).write_text('{"actual": true}'))
    coverage.stop()
    modes = []

    def report(path):
        modes.append(stat.S_IMODE(os.stat(path).st_mode))
        coverage.json_report(outfile=path)
        modes.append(stat.S_IMODE(os.stat(path).st_mode))

    write_private_report(destination, report)
    assert modes == [0o600, 0o600]
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert "totals" in json.loads(destination.read_text())
    assert not list(tmp_path.glob(".report-*.tmp"))


def test_existing_file_and_symlink_not_overwritten(tmp_path):
    tmp_path.chmod(0o700)
    target = tmp_path / "retained.json"
    target.write_text("retained")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    for path in (target, link):
        with pytest.raises(FileExistsError):
            write_private_report(path, lambda filename: Path(filename).write_text("changed"))
    assert target.read_text() == "retained"


def test_real_writer_error_keeps_original_exception_and_no_published_report(tmp_path):
    tmp_path.chmod(0o700)
    destination = tmp_path / "coverage.json"

    def report(path):
        Path(path).write_text("partial")
        (tmp_path / "missing-input").read_bytes()

    with pytest.raises(FileNotFoundError):
        write_private_report(destination, report)
    assert not destination.exists()
    assert not list(tmp_path.glob(".report-*.tmp"))


def test_nonprivate_directory_rejected(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(PermissionError):
        write_private_report(tmp_path / "report.json", lambda path: Path(path).write_text("data"))
