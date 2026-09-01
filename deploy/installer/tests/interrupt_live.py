#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


INSTALLER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = INSTALLER_ROOT.parents[1]
sys.path.insert(0, str(INSTALLER_ROOT))

from nomosmart_installer.config import load_config
from nomosmart_installer.state import STAGES


def main() -> int:
    config_value = os.environ.get("NOMOSMART_INSTALLER_LIVE_CONFIG", "").strip()
    stage = os.environ.get("NOMOSMART_INSTALLER_INTERRUPT_STAGE", "").strip()
    signal_name = os.environ.get(
        "NOMOSMART_INSTALLER_INTERRUPT_SIGNAL", "SIGINT"
    ).strip()
    interrupt_signal = {
        "SIGINT": signal.SIGINT,
        "SIGTERM": signal.SIGTERM,
    }.get(signal_name)
    if (
        not config_value
        or stage not in STAGES
        or interrupt_signal is None
        or os.environ.get("NOMOSMART_INSTALLER_INTERRUPT_LIVE_APPROVED") != "YES"
    ):
        print(
            "blocked: real config, valid stage/SIGINT-or-SIGTERM, and explicit disposable-target approval are required",
            file=sys.stderr,
        )
        return 2
    config = load_config(Path(config_value))
    state_path = config.application.state_dir / "state.json"
    status = subprocess.run(
        [
            str(INSTALLER_ROOT / "nomosmart-install"),
            "status",
            "--config",
            str(config.source_path),
        ],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    operation = "install" if '"status": "not-installed"' in status.stdout else "resume"
    process = subprocess.Popen(
        [
            str(INSTALLER_ROOT / "nomosmart-install"),
            operation,
            "--config",
            str(config.source_path),
        ],
        cwd=REPOSITORY,
        start_new_session=True,
    )
    deadline = time.monotonic() + 1800
    observed = False
    while process.poll() is None and time.monotonic() < deadline:
        if state_path.is_file():
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if (
                payload.get("current_stage") == stage
                and stage not in (payload.get("completed_stages") or [])
            ):
                observed = True
                os.killpg(process.pid, interrupt_signal)
                break
        time.sleep(0.2)
    if not observed:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30)
        print("failed: requested stage was not observed before timeout", file=sys.stderr)
        return 1
    interrupted = process.wait(timeout=60)
    if interrupted == 0:
        print("failed: installer completed instead of preserving interruption", file=sys.stderr)
        return 1
    resumed = subprocess.run(
        [
            str(INSTALLER_ROOT / "nomosmart-install"),
            "resume",
            "--config",
            str(config.source_path),
        ],
        cwd=REPOSITORY,
        check=False,
    )
    if resumed.returncode == 10:
        print(
            "blocked: resume safely reached a human checkpoint; complete it and rerun",
            file=sys.stderr,
        )
        return 2
    if resumed.returncode != 0:
        return resumed.returncode
    print(
        json.dumps(
            {
                "status": "interrupt-resume-verified",
                "interrupted_stage": stage,
                "signal": signal_name,
                "services_left_running": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
