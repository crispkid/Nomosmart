"""Focused CHG-301 test/coverage harness; not full application release evidence.

No Docker/Kubernetes/Provider operations. Own temporary test files/keyrings only.
Run with CHG301_ISOLATED=1. Real GnuPG needs permission to start its private agent.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
TESTS = (
    "backend/tests/test_chg301_package_boundaries.py",
    "backend/tests/test_chg242_secret_packaging.py",
    "backend/tests/test_chg231_deployment_initialization.py",
    "backend/tests/test_chg229_full_stack_deployment.py",
    "backend/tests/test_chg262_docker_desktop_local.py::test_chg262_package_generates_strong_distinct_opensearch_local_passwords",
    "backend/tests/test_chg262_docker_desktop_local.py::test_chg262_package_flag_is_scoped_to_fresh_local_helm",
)
CONFIG = "backend/tests/chg301_coverage.ini"
SOURCES = ("deploy/package/nomosmart_package.py", "deploy/package/generate_opensearch_tls.py")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.environ.get("CHG301_ISOLATED") == "1", "explicit isolated-test opt-in required"
    assert len(sys.argv) == 1, "this focused harness does not accept test selection/threshold overrides"
    root = Path(tempfile.mkdtemp(prefix="chg301-package-evidence-", dir="/private/tmp"))
    root.chmod(0o700)
    files = sorted(set(SOURCES + tuple(t.split("::")[0] for t in TESTS) + (CONFIG, str(Path(__file__).relative_to(ROOT)))))
    before = {name: digest(ROOT / name) for name in files}
    environment = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    environment.update(PYTHONPATH=str(ROOT / "backend"), APP_ENV="test",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", COVERAGE_FILE=str(root / ".coverage"),
        PYTHONPYCACHEPREFIX=str(root / "pycache"))
    junit, report = root / "junit.xml", root / "coverage.json"
    command = [sys.executable, "-m", "pytest", "-p", "pytest_cov.plugin", "-c", "/dev/null",
        "--rootdir=.", "--noconftest", "-p", "no:cacheprovider", "--tb=short", "-q",
        "--basetemp=" + str(root / "test-files"), "--junitxml=" + str(junit), *TESTS,
        "--cov=deploy/package", "--cov-branch", "--cov-config=" + CONFIG,
        "--cov-fail-under=80", "--cov-report=term-missing", "--cov-report=json:" + str(report)]
    summary = {"scope": "CHG-301 package regression, not full Backend/Frontend release",
               "source_sha256": before, "command": command, "threshold": 80,
               "status": "FAIL"}
    try:
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=1200)
        summary["pytest_exit"] = result.returncode
        # Do not retain raw assertion output or captured TTY/Secret values.
        cases = list(ET.parse(junit).getroot().iter("testcase")) if junit.exists() else []
        summary["tests"] = [{"name": case.get("classname", "") + "." + case.get("name", ""),
            "status": "FAIL" if case.find("failure") is not None or case.find("error") is not None
                      else "SKIP" if case.find("skipped") is not None else "PASS"} for case in cases]
        assert result.returncode == 0 and len(cases) >= 81, "pytest failed/incomplete"
        assert all(case["status"] == "PASS" for case in summary["tests"]), "failed or skipped tests"
        data = json.loads(report.read_text())
        assert set(data["files"]) == set(SOURCES), "coverage source scope mismatch"
        summary["coverage"] = {}
        # Both modules, and the whole package: line AND branch minimums. Do not
        # hide a weak module behind the larger one's aggregate percentage.
        for name, totals in [(name, row["summary"]) for name, row in data["files"].items()] + [("TOTAL", data["totals"])]:
            assert totals["excluded_lines"] == 0 and totals["num_statements"] > 0 and totals["num_branches"] > 0
            values = {"lines": totals["covered_lines"] / totals["num_statements"] * 100,
                      "branches": totals["covered_branches"] / totals["num_branches"] * 100,
                      "combined": totals["percent_covered"]}
            summary["coverage"][name] = values
            assert min(values.values()) >= 80, "coverage threshold failed"
        assert before == {name: digest(ROOT / name) for name in files}, "source drift during verification"
        summary["coverage_sha256"] = digest(report)
        summary["status"] = "PASS"
    except Exception as exc:
        # Only bounded diagnostic categories, never pytest output/Secret values.
        summary["error_type"] = type(exc).__name__
    finally:
        if junit.exists(): junit.unlink()
        tests = root / "test-files"
        if tests.exists():
            assert tests.parent == root and not tests.is_symlink()
            shutil.rmtree(tests)
        pycache = root / "pycache"
        if pycache.exists():
            assert pycache.parent == root and not pycache.is_symlink()
            shutil.rmtree(pycache)
        summary["test_file_cleanup"] = not tests.exists()
        for artifact in root.iterdir():
            if artifact.is_file(): artifact.chmod(0o600)
        output = root / "result.json"
        output.write_text(json.dumps(summary, indent=2)); output.chmod(0o600)
        print(json.dumps({"status": summary["status"], "tests": len(summary.get("tests", [])),
                          "coverage": summary.get("coverage", {}), "evidence": str(output)}, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
