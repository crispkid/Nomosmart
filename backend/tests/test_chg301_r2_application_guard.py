"""Actual harmless local child processes, no mocked process/service behavior."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from chg301_r2_application_guard import execute, terminate_owned


def test_actual_natural_exit_and_measured_resources(tmp_path):
    result = execute([sys.executable, "-c", "import time; time.sleep(.2); print('natural')"], tmp_path/"natural")
    assert result["exit_code"] == 0 and result["peak_rss_bytes"] > 0
    assert not result["termination"]
    assert (tmp_path/"natural/stdout").read_text().strip() == "natural"


def test_actual_timeout_stops_only_its_live_child(tmp_path):
    with pytest.raises(TimeoutError):
        execute([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path/"timeout", timeout=.2)
    result = json.loads((tmp_path/"timeout/result.json").read_text())
    assert result["exit_code"] is not None
    assert result["termination"]["signals"][0]["members"] == [result["child_pid"]]
    assert result["peak_rss_bytes"] > 0


@pytest.mark.parametrize("attempt", range(5))
def test_reaped_child_is_never_signalled(attempt):
    child = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    assert child.wait(timeout=5) == 0
    record = {}
    terminate_owned(child, record)
    assert record == {"already_exited": True}


def test_actual_small_rss_limit_stops_owned_process(tmp_path):
    with pytest.raises(RuntimeError, match="host_process_rss_limit"):
        execute([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path/"memory", rss_limit=1)
    result = json.loads((tmp_path/"memory/result.json").read_text())
    assert result["peak_rss_bytes"] > 1 and result["exit_code"] is not None
    assert "termination_error" not in result


def test_actual_nonzero_exit_is_preserved(tmp_path):
    result = execute([sys.executable, "-c", "raise SystemExit(7)"], tmp_path/"nonzero")
    assert result["exit_code"] == 7
