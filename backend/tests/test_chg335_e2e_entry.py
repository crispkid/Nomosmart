"""Real CLI/private filesystem refusal; not generation or Provider acceptance."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "backend/scripts/e2e_governance_fixture.py"


def invoke(action, manifest, *args):
    env = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1",
           "E2E_ISOLATION": "fresh-disposable", "E2E_WRITERS_QUIESCED": "1"}
    result = subprocess.run([sys.executable, "-B", str(HELPER), action, "--manifest", str(manifest), *args],
                            env=env, capture_output=True, text=True, timeout=30)
    return result.returncode, json.loads(result.stdout)


def test_absent_generation_is_blocked_and_empty_owned_receipt_cleans():
    with tempfile.TemporaryDirectory(prefix="e2e-real-cli-") as directory:
        path = Path(directory).resolve() / "run.json"
        assert invoke("init", path)[0] == 0
        code, result = invoke("setup", path)
        assert code == 2 and result["code"] == "E2E_BLOCKED"
        assert result["reason"] == "genuine_generation_and_workflow_receipts_required"
        assert invoke("cleanup", path)[1]["status"] == "cleanup_complete"
        assert json.loads(path.read_text())["resources"] == []


def test_unowned_or_wrong_run_generation_receipt_is_failed_not_ready():
    with tempfile.TemporaryDirectory(prefix="e2e-real-cli-") as directory:
        path = Path(directory).resolve() / "run.json"
        assert invoke("init", path)[0] == 0
        capsule = path.parent / "generation.json"
        capsule.write_text(json.dumps({"version": 1, "run_id": "00000000-0000-0000-0000-000000000001"}))
        capsule.chmod(0o600)
        code, result = invoke("setup", path, "--generation-receipt", str(capsule))
        assert code == 1 and result["code"] == "generation_run_mismatch"
        assert json.loads(path.read_text())["resources"] == []
        assert invoke("cleanup", path)[0] == 0


def test_public_generation_file_is_rejected_by_real_cli():
    with tempfile.TemporaryDirectory(prefix="e2e-real-cli-") as directory:
        path = Path(directory).resolve() / "run.json"
        assert invoke("init", path)[0] == 0
        capsule = path.parent / "generation.json"
        capsule.write_text("{}"); capsule.chmod(0o644)
        code, result = invoke("setup", path, "--generation-receipt", str(capsule))
        assert code == 1 and result["code"] == "generation_receipt_not_private"
        assert invoke("cleanup", path)[0] == 0


def test_symlink_generation_file_is_rejected_by_real_cli():
    with tempfile.TemporaryDirectory(prefix="e2e-real-cli-") as directory:
        path = Path(directory).resolve() / "run.json"
        assert invoke("init", path)[0] == 0
        target = path.parent / "actual.json"; target.write_text("{}"); target.chmod(0o600)
        capsule = path.parent / "generation.json"; capsule.symlink_to(target)
        code, result = invoke("setup", path, "--generation-receipt", str(capsule))
        assert code == 1 and result["code"] == "generation_receipt_path_invalid"
        assert invoke("cleanup", path)[0] == 0
