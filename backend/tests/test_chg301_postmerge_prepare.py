"""Real immutable preparation receipts, not replacement/fake service tests."""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from chg301_postmerge_prepare import (HEAD, PLAN, PLAN_SHA, ROOT, TAGS, approval,
                                    canonical_render)
from chg301_r2_application_guard import digest
from chg301_r2_application_run import compact_sarif


def evidence():
    path = Path(os.environ["CHG301_POSTMERGE_MANIFEST"])
    assert path.parent.parent == Path("/private/tmp")
    assert path.parent.name.startswith("chg301-postmerge-") and path.name in {"test-input.json", "test-input-final.json"}
    assert not path.is_symlink() and not path.parent.is_symlink()
    return path.parent, json.loads(path.read_bytes())


def test_frozen_current_preparation_approval():
    approval()
    assert digest(PLAN) == PLAN_SHA
    _, result = evidence()
    assert result["plan_sha256"] == PLAN_SHA
    assert result["deployment_writes"] == result["provider_calls"] == 0
    assert result["release"][0]["revision"] == 37


def test_real_commands_have_immutable_raw_receipts():
    _, result = evidence()
    for command in result["commands"]:
        path = Path(command["path"])
        assert command["status"] == "RECORDED"
        assert digest(path) == command["sha256"]
        raw = json.loads(path.read_bytes())
        assert raw["peak_rss_bytes"] <= 8*1024**3
        assert raw["timeout_seconds"] <= 1800
        assert not raw.get("termination_error")
        for report in raw["reports"].values():
            assert digest(Path(report["path"])) == report["sha256"]


@pytest.mark.parametrize("name", ["backend-builder", "backend-runner", "frontend-base", "frontend-deps",
                                  "frontend-builder", "frontend-prod-deps", "frontend-runner"])
def test_actual_arm64_stage_context_scan_and_cli(name):
    _, result = evidence()
    artifact = result["artifacts"][name]
    assert artifact["platform"] == "linux/arm64"
    work = Path(artifact["work"])
    context = json.loads((work/"context.json").read_bytes())
    assert context["commit"] == HEAD
    for relative, row in context["sources"].items():
        assert digest(ROOT/row["source"]) == row["sha256"] == digest(work/"context"/relative)
        assert (work/"context"/relative).stat().st_mode & 0o777 == row["mode"]
    scan_path = Path(artifact["scan"]["path"])
    assert digest(scan_path) == artifact["scan"]["sha256"]
    scan = json.loads(scan_path.read_bytes())
    assert scan["image_id"] == artifact["id"]
    for report in scan["reports"].values():
        assert digest(Path(report["path"])) == report["sha256"]
    assert not any(f["severity"] in {"HIGH", "CRITICAL"} for f in compact_sarif(Path(scan["reports"]["cves"]["path"])).values())
    assert json.loads(Path(scan["reports"]["sbom"]["path"]).read_bytes())["spdxVersion"] == "SPDX-2.3"
    cli = json.loads(Path(artifact["cli"]["path"]).read_bytes())
    assert digest(Path(artifact["cli"]["path"])) == artifact["cli"]["sha256"]
    assert cli["image_id"] == artifact["id"] and cli["status"] == "PASS" and cli["baseline_unchanged"]
    assert json.loads((work/"cli"/"cleanup.json").read_bytes())["removed"] == cli["container_id"]


def test_candidate_tags_and_frontend_contract():
    _, result = evidence()
    for component, tag in TAGS.items():
        assert result["artifacts"][component+"-runner"]["tag"] == tag
    row = result["artifacts"]["frontend-builder"]["contracts"]
    assert digest(Path(row["path"])) == row["sha256"]
    assert json.loads(Path(row["path"]).read_bytes())["status"] == "PASS"


def test_readonly_v049_metadata_baseline():
    _, result = evidence()
    value = json.loads(Path(result["live_baseline_before"]).read_bytes())
    assert value["database"]["readonly"] == "on"
    assert value["database"]["migration"]["last"] == {"version": "049", "checksum": -1579162252, "success": True}
    assert value["database"]["owner_parity_errors"] == 0
    for rows in value["kubernetes"]["secrets"].values():
        assert all(set(row) == {"name", "uid", "resourceVersion"} for row in rows)
    assert len([r for r in value["kubernetes"]["resources"] if r["kind"] == "PersistentVolumeClaim"]) == 7
    comparison = json.loads(Path(result["baseline_comparison"]["path"]).read_bytes())
    assert comparison == {"resources_equal": True, "runtime_secret_metadata_equal": True,
                          "helm_secret_metadata_equal": True, "changed_tables": [], "v049_equal": True}


def test_real_render_is_reproducible_and_hidden_secret():
    root, result = evidence()
    render = result["render"]
    assert render["status"] == "PASS_SIMULATION_ONLY" and render["unexpected"] == []
    comparison = json.loads(Path(render["comparison"]["path"]).read_bytes())
    assert comparison["removed_helm_owned"] == []
    assert comparison["new_objects"] == ["Job/nomosmart-local-bootstrap-38", "Job/nomosmart-local-migration-38"]
    assert all(j["policy"] == "keep" for j in comparison["retained_audit_jobs"])
    first, second = [Path(p).read_bytes() for p in render["raw_paths"]]
    assert canonical_render(first) == canonical_render(second)
    assert hashlib.sha256(canonical_render(first)).hexdigest() == render["sha256"]
    assert (root/"render-canonical.yaml").read_bytes() == canonical_render(first)
    for raw in (b"no Helm output", first+ b"\nHOOKS:\n"):
        with pytest.raises(ValueError):
            canonical_render(raw)


def test_unsuppressed_static_scan_and_exact_risk_acceptance():
    _, result = evidence()
    report = Path(result["sast"]["path"])
    assert digest(report) == result["sast"]["sha256"]
    risk = json.loads(report.read_bytes())
    assert risk["status"] == "ACCEPTED_RISK" and len(risk["accepted_findings"]) == 3
    assert risk["unaccepted_high_critical"] == []
    assert digest(Path(risk["raw_path"])) == risk["raw_sha256"]
    raw = json.loads(Path(risk["raw_path"]).read_bytes())
    assert raw["errors"] == [] and raw["metrics"]["_totals"]["skipped_tests"] == 0
    assert raw["metrics"]["_totals"]["loc"] >= 30000
    for path, expected in risk["source_sha256"].items():
        assert digest(ROOT/path) == expected


def test_exact_owned_cleanup_retains_only_two_candidates():
    _, result = evidence()
    cleanup = result["cleanup"]
    assert cleanup["containers_unchanged"] and cleanup["networks_unchanged"]
    assert cleanup["missing_baseline_images"] == []
    assert cleanup["extra_images"] == cleanup["retained_candidates"] and len(cleanup["extra_images"]) == 2
    for row in result["artifacts"].values():
        if row["stage"] != "runner":
            assert json.loads((Path(row["work"])/"cleanup.json").read_bytes())["removed"] == row["id"]
