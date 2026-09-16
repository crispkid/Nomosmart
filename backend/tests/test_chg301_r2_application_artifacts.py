"""Current real app artifacts and immutable historical failures; no service mocks."""
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"backend/scripts"))
from chg301_r2_application_run import approval, compact_sarif, OLD
from chg301_r2_application_guard import digest
import chg301_r2_formal_dependencies as historical
from chg301_r2_application_cleanup import exact_pulled_reference

RUN = Path(os.environ["CHG301_R2_APPLICATION_EVIDENCE"]).resolve(strict=True)
INPUT_MANIFEST = Path(os.environ["CHG301_R2_APPLICATION_MANIFEST"])
assert INPUT_MANIFEST.parent.parent == RUN
RECORD = json.loads(INPUT_MANIFEST.read_bytes())


def final_artifact(component, stage, arch):
    rows = [v for v in RECORD["artifacts"].values() if v["component"] == component
            and v["stage"] == stage and v["platform"] == "linux/"+arch and v.get("cli", {}).get("status") == "PASS"]
    if component == "backend" and stage == "builder":
        rows = [r for r in rows if r["qualification"]]
    else:
        rows = [r for r in rows if not r["qualification"]]
    assert len(rows) == 1
    return rows[0]


def test_current_approval_does_not_reactivate_retired_scope():
    approval()
    with pytest.raises(ValueError, match="approval"):
        historical.approval_guard()
    assert RECORD["peripherals"] == "DEFERRED_PERIPHERAL_BY_USER"
    assert RECORD["provider_calls"] == RECORD["deployment_writes"] == 0


def test_only_qualified_unused_backend_build_tools_removed():
    before, after = RECORD["source_before"], RECORD["source_accepted"]
    assert {p for p in before if before[p] != after[p]} == {"backend/Dockerfile"}
    for path, sha in after.items():
        assert digest(ROOT/path) == sha
    old = (OLD/"backend-runner-r2/context/Dockerfile").read_bytes()
    assert (ROOT/"backend/Dockerfile").read_bytes() == old.replace(b"    build-essential \\\n", b"").replace(b"    libpq-dev \\\n", b"")


MATRIX = [(component, stage, arch) for component, stages in
          (("backend", ("builder", "runner")), ("frontend", ("base", "deps", "builder", "prod-deps", "runner")))
          for stage in stages for arch in ("arm64", "amd64")]


@pytest.mark.parametrize("component,stage,arch", MATRIX)
def test_actual_each_platform_stage_full_scan_and_cli(component, stage, arch):
    artifact = final_artifact(component, stage, arch)
    context = json.loads((Path(artifact["work"])/"context.json").read_bytes())
    assert context["recipe_sha256"] == digest(ROOT/component/"Dockerfile")
    for dest, source in context["sources"].items():
        # The qualification recipe is intentionally derived; every other file
        # matches repository bytes AND modes, not merely an artificial0600 copy.
        path = ROOT/source["source"]
        if not (dest == "Dockerfile" and artifact["qualification"]):
            assert digest(path) == source["sha256"]
        assert path.stat().st_mode & 0o777 == source["mode"]
    scan_path = Path(artifact["scan"]["path"])
    assert digest(scan_path) == artifact["scan"]["sha256"]
    scan = json.loads(scan_path.read_bytes())
    assert scan["image_id"] == artifact["id"]
    for report in scan["reports"].values():
        assert digest(Path(report["path"])) == report["sha256"]
    raw = json.loads(Path(scan["reports"]["cves"]["path"]).read_bytes())
    assert raw["version"] == "2.1.0" and raw["runs"]
    assert all(r["tool"]["driver"]["name"] == "docker scout" for r in raw["runs"])
    assert scan["findings"] == compact_sarif(Path(scan["reports"]["cves"]["path"]))
    assert not any(v["severity"] in {"HIGH", "CRITICAL"} for v in scan["findings"].values())
    sbom = json.loads(Path(scan["reports"]["sbom"]["path"]).read_bytes())
    assert len(sbom["packages"]) > 1
    containers = [p for p in sbom["packages"] if p.get("primaryPackagePurpose") == "CONTAINER"]
    assert len(containers) == 1
    assert any(artifact["id"] in r["referenceLocator"] for r in containers[0]["externalRefs"])
    cli_path = Path(artifact["cli"]["path"])
    assert digest(cli_path) == artifact["cli"]["sha256"]
    cli = json.loads(cli_path.read_bytes())
    assert cli["image_id"] == artifact["id"] and cli["status"] == "PASS"
    assert cli["exit_code"] == 0 and cli["removed"] and cli["baseline_unchanged"]
    if component == "backend" and stage == "builder":
        assert not {"build-essential", "linux-libc-dev", "libc6-dev", "libpq-dev"} & {p["name"] for p in sbom["packages"]}
        log = json.loads(Path(artifact["build_command"]).read_bytes())
        assert "--no-cache" in log["args"] and log["exit_code"] == 0


def test_actual_copy_mode_failure_not_erased():
    first = json.loads((RUN/"backend-builder-arm64-qualification/cli/result.json").read_bytes())
    assert first["status"] == "BLOCKED" and first["removed"]
    assert first["baseline_unchanged"]
    assert (OLD/"analysis/regression-final.xml").is_file()


def test_raw_findings_not_duplicated_into_large_manifest():
    assert (RUN/"manifest.json").stat().st_size < 2*1024**2
    assert (OLD/"manifest.json").stat().st_size > 100*1024**2
    for item in RECORD["commands"]:
        assert digest(Path(item["path"])) == item["sha256"]
        record = json.loads(Path(item["path"]).read_bytes())
        assert record["peak_rss_bytes"] <= 8*1024**3
        assert "termination_error" not in record


def test_actual_source_audit_reuse_and_ftp_exception_remain_explicit():
    path = Path(RECORD["source_audit"]["path"])
    assert digest(path) == RECORD["source_audit"]["sha256"]
    result = json.loads(path.read_bytes())
    assert result["dependency_audit"]["mode"] == "HISTORICAL_SAME_SOURCE_REUSE_NOT_NEW_ONLINE_AUDIT"
    assert all(v["status"] == "PASS" for v in result["dependency_audit"]["checks"].values())
    assert result["backend_sast"]["assessment"]["status"] == "ACCEPTED_RISK"
    assert len(result["backend_sast"]["assessment"]["accepted_findings"]) == 3
    assert not result["backend_sast"]["assessment"]["unaccepted_high_critical"]
    assert result["tool_sast"]["high_count"] == 0
    for source, sha in result["tool_sast"]["source_sha256"].items():
        assert digest(ROOT/source) == sha


def test_exact_pulled_digest_alias_does_not_allow_extra_tags():
    plan = json.loads((RUN/"cleanup/dry-run.json").read_bytes())
    image = next(p for p in plan["images"] if p["labels"] is None)
    assert exact_pulled_reference(image, image["id"])
    assert not exact_pulled_reference({**image, "tags": [*image["tags"], "redis:unowned"]}, image["id"])
    assert not exact_pulled_reference({**image, "digests": ["other@"+image["id"]]}, image["id"])
    assert not exact_pulled_reference(image, "sha256:"+"0"*64)
