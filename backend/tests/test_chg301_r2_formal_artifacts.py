"""Real immutable candidate evidence and pure fail-closed policy checks.

Passing these checks does not mark blocked service compatibility as passing.
"""
from datetime import datetime, timedelta
import json
import os
import re
from pathlib import Path
import sys
import tarfile
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
import chg301_r2_formal_dependencies as formal
from chg301_r2_delivery import delivery_gate
from chg301_r2_high_risk import raw_findings, time_guard
from chg301_r2_node_qualification import file_sha

RUN = Path(os.environ["CHG301_R2_FORMAL_EVIDENCE"]).resolve(strict=True)
RECORD = json.loads((RUN / "manifest.json").read_bytes())


def test_current_approval_and_only_exact_approved_source_changes():
    # Historic approval is immutable evidence, not authority to restart its run.
    active = next(s for s in (ROOT/"DEVELOPMENT_PLAN.md").read_text().split("\n## ")[1:]
                  if s.splitlines()[0] == formal.SECTION)
    assert file_sha(formal.PLAN) == formal.PLAN_SHA
    assert all(s in active for s in (formal.APPROVAL, formal.PRE_SHA, "Gate 4 approval: APPROVED."))
    with pytest.raises(ValueError, match="approval"):
        formal.approval_guard()
    from chg301_r2_application_evidence import historical_sources
    actual = historical_sources(RECORD["source"])
    assert {p for p in actual if actual[p] != RECORD["source"][p]} == {"deploy/rustfs/Dockerfile", "frontend/Dockerfile", "backend/Dockerfile"}
    assert all(actual[p] == h for p, h in RECORD["source"].items() if p.startswith("sql/migrations/"))


def test_any_unrelated_source_change_still_refused():
    before = dict(RECORD["source"])
    before["backend/Dockerfile"] = "0" * 64
    with pytest.raises(ValueError, match="product_source_drift"):
        formal.source_guard(before)


def test_run_deadline_cannot_be_extended_by_retry():
    assert (datetime.fromisoformat(RECORD["deadline"]) - datetime.fromisoformat(RECORD["started_at"])).total_seconds() == 21600
    with pytest.raises(ValueError):
        time_guard(RECORD, datetime.fromisoformat(RECORD["deadline"]) + timedelta(seconds=1))


@pytest.mark.parametrize("name", sorted(formal.CANDIDATES))
def test_actual_official_candidate_digest_platform_and_full_raw_reports(name):
    scan = next(s for s in RECORD["scans"] if s["name"] == name)
    target = scan["target"]
    platforms = formal.candidate_manifests((RUN / "analysis" / (name + ".manifest.json")).read_bytes())
    assert platforms == target["platform_children"]
    assert target["manifest_digest"] == platforms["arm64"]
    assert target["scan_reference"].endswith("@" + platforms["arm64"])
    assert target["source_bound"] is False  # Base qualification is not adoption.
    for report in scan["reports"].values():
        path = Path(report["path"])
        assert RUN in path.parents and file_sha(path) == report["sha256"]
    assert scan["findings"] == raw_findings(json.loads(Path(scan["reports"]["cves"]["path"]).read_bytes()))
    sbom = json.loads(Path(scan["reports"]["sbom"]["path"]).read_bytes())
    roots = [p for p in sbom["packages"] if p.get("primaryPackagePurpose") == "CONTAINER"]
    assert len(roots) == 1
    assert any(platforms["arm64"] in r["referenceLocator"] for r in roots[0]["externalRefs"])


def test_actual_redis_other_platform_is_static_only():
    scan = json.loads((RUN / "analysis/redis-amd64-scan.json").read_bytes())
    assert scan["platform"] == "linux/amd64" and scan["runtime_tested"] is False
    for report in scan["reports"].values():
        assert file_sha(Path(report["path"])) == report["sha256"]
    findings = raw_findings(json.loads(Path(scan["reports"]["cves"]["path"]).read_bytes()))
    assert not any(f["severity"] in {"HIGH", "CRITICAL"} for f in findings.values())


def test_actual_final_rustfs_recipe_scan_and_live_contract_are_same_image():
    build = json.loads((RUN / "rustfs-final/result.json").read_bytes())
    context = json.loads((RUN / "rustfs-final/context.json").read_bytes())
    scan = json.loads((RUN / "rustfs-final/scan.json").read_bytes())
    assert build["exit_code"] == 0 and build["image_id"] == scan["image_id"]
    for name, source in context["sources"].items():
        assert file_sha(ROOT / source) == context["sha256"][name] == file_sha(RUN / "rustfs-final/context" / name)
    for report in scan["reports"].values():
        assert file_sha(Path(report["path"])) == report["sha256"]
    assert not any(f["severity"] in {"HIGH", "CRITICAL"} for f in scan["findings"].values())
    report = ET.parse(RUN / "analysis/final-live.xml").getroot()
    assert len(report.findall(".//testcase")) == 2 and not report.findall(".//failure")
    labs = [json.loads(p.read_bytes()) for p in RUN.glob("rustfs-live-*/journal.json")]
    matches = [v for v in labs if v["image_id"] == scan["image_id"]]
    assert len(matches) == 1
    assert matches[0]["source_sha256"]["deploy/rustfs/Dockerfile"] == context["sha256"]["Dockerfile"]


def test_rustfs_repaired_candidate_preserves_all_other_package_versions():
    base = next(s for s in RECORD["scans"] if s["name"] == "rustfs")
    fixed = next(s for s in RECORD["scans"] if s["name"] == "rustfs-repaired")
    assert len([f for f in base["findings"].values() if f["severity"] in {"HIGH", "CRITICAL"}]) == 18
    assert not any(f["severity"] in {"HIGH", "CRITICAL"} for f in fixed["findings"].values())
    # Registry SBOM uses installed APK names; local Scout also emits source
    # package aliases (openssl/nghttp2 etc). These are not additional installs.
    # Compare the actual apk-info before/after diff captured by the build.
    result = json.loads((RUN / "rustfs-build/result.json").read_bytes())
    log = RUN / "rustfs-build/build.stderr"
    assert file_sha(log) == result["log_sha256"]
    lines = [m[1] for line in log.read_text().splitlines()
             if (m := re.match(r"#7 \d+\.\d+ ([+-][a-z][^ ]*)$", line))]
    assert set(lines) == {
        "-curl-8.21.0-r0", "+curl-8.22.0-r0", "-libcurl-8.21.0-r0", "+libcurl-8.22.0-r0",
        "-libcrypto3-3.5.7-r0", "+libcrypto3-3.5.8-r0", "-libssl3-3.5.7-r0", "+libssl3-3.5.8-r0",
        "+su-exec-0.3-r0"}


def test_candidate_live_failure_history_is_not_erased():
    first = ET.parse(RUN / "analysis/live-attempt1.xml").getroot()
    second = ET.parse(RUN / "analysis/live-attempt2.xml").getroot()
    assert len(first.findall(".//failure")) == 2
    assert len(second.findall(".//failure")) == 2
    success = ET.parse(RUN / "analysis/rustfs-attempt3.xml").getroot()
    assert len(success.findall(".//testcase")) == 1 and not success.findall(".//failure")


def test_finished_owned_labs_cleaned_without_changing_protected_containers():
    journals = list(RUN.glob("*-live-*/journal.json"))
    assert len(journals) >= 6
    protected = {p["id"] for p in RECORD["baseline_before"]["containers"]}
    for path in journals:
        lab = json.loads(path.read_bytes())
        cleanup = json.loads((path.parent / "cleanup.json").read_bytes())
        assert cleanup["baseline_unchanged"]
        assert set(lab["containers"]).isdisjoint(protected)
        assert {p["id"] for p in cleanup["removed"] if p["kind"] == "container"} == set(lab["containers"])
        for command in lab["commands"]:
            args = command.get("args", [])
            if args[:1] == ["create"]:
                assert ["--cap-drop", "ALL"] == args[args.index("--cap-drop"):args.index("--cap-drop")+2]
                assert "no-new-privileges" in args and "--privileged" not in args
                assert args[args.index("--user")+1] in {"999:999", "10001:10001"}


def test_unresolved_official_highs_still_block_original_pr():
    rows = [{"uses": ["install"], "source_bound": True, "complete_scan": True,
             "findings": [dict(f, state="UNRESOLVED") for f in s["findings"].values()]}
            for s in RECORD["scans"] if s["name"] in formal.CANDIDATES]
    with pytest.raises(ValueError, match="high_requires_resolution"):
        delivery_gate(rows)


def test_official_npm_patch_material_and_bundle_are_checksum_bound():
    path = RUN / "analysis/npm-11.19.1.tgz"
    assert file_sha(path) == "9f58bff01604cb1b14008fef14dceb14d836a49225e45c6c2e37de3be3e707f0"
    expected = {"package/package.json": "11.19.1",
        "package/node_modules/brace-expansion/package.json": "5.0.9",
        "package/node_modules/ip-address/package.json": "10.5.0",
        "package/node_modules/tar/package.json": "7.5.22"}
    with tarfile.open(path) as archive:
        for name, version in expected.items():
            stream = archive.extractfile(name)  # Read only; never extract paths.
            assert stream and json.load(stream)["version"] == version
    recipe = (ROOT / "frontend/Dockerfile").read_text()
    assert "--checksum=sha256:" + file_sha(path) in recipe
    assert "--ignore-scripts --no-audit --no-fund" in recipe


@pytest.mark.parametrize("name", ["frontend-builder-r2", "frontend-runner-r3", "backend-runner-r2"])
def test_final_application_stage_scan_is_source_bound_and_has_no_raw_high(name):
    build = json.loads((RUN / name / "result.json").read_bytes())
    context = json.loads((RUN / name / "context.json").read_bytes())
    scan = json.loads((RUN / name / "scan.json").read_bytes())
    assert build["exit_code"] == 0 and scan["image_id"] == build["image_id"]
    assert build["resource_envelope"]["aggregate_cpu"] <= 4
    assert build["resource_envelope"]["aggregate_memory_bytes"] <= 8 * 1024**3
    for dest, source in context["sources"].items():
        assert context["sha256"][dest] == file_sha(RUN / name / "context" / dest)
        if source == "backend/Dockerfile":
            from chg301_r2_application_evidence import historical_sources
            historical_sources(RECORD["source"])
        else:
            assert file_sha(ROOT / source) == context["sha256"][dest]
    for report in scan["reports"].values():
        assert file_sha(Path(report["path"])) == report["sha256"]
    assert not any(f["severity"] in {"HIGH", "CRITICAL"} for f in scan["findings"].values())


def test_uv_official_hashes_and_application_locks_unchanged():
    metadata = json.loads((RUN / "analysis/uv-official-metadata.json").read_bytes())
    official = {v["digests"]["sha256"] for v in metadata["releases"]["0.11.33"]}
    recipe = (ROOT / "backend/Dockerfile").read_text()
    hashes = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", recipe))
    assert len(hashes) == 3 and hashes.issubset(official)
    assert "--require-hashes -r /dev/stdin" in recipe
    assert "uv sync --frozen --no-dev --no-editable" in recipe
    for name in ("frontend/package.json", "frontend/package-lock.json", "backend/pyproject.toml", "backend/uv.lock"):
        assert file_sha(ROOT / name) == RECORD["source"][name]


def test_backend_builder_uv_repair_does_not_silence_linux_header_findings():
    before = json.loads((RUN / "backend-builder/scan.json").read_bytes())
    after = json.loads((RUN / "backend-builder-r2/scan.json").read_bytes())
    old_uv = {key for key, f in before["findings"].items()
              if f["severity"] in {"HIGH", "CRITICAL"} and "/opt/uv/bin/uv" in f["locations"]}
    assert len(old_uv) == 5
    assert not old_uv.intersection(after["findings"])
    unresolved = [f for f in after["findings"].values() if f["severity"] in {"HIGH", "CRITICAL"}]
    assert unresolved and all(any(p.startswith("pkg:deb/ubuntu/linux@") for p in f["purls"]) for f in unresolved)
    assert after["status"] == "FINDINGS_REQUIRE_REVIEW"


def test_actual_networkless_application_cli_and_exact_cleanup():
    # Preserve the previous missing-receipt failure; require genuine replacement
    # evidence, never manufacture a result inside the old immutable run.
    assert not (RUN/"app-cli/result.json").exists()
    assert ET.parse(RUN/"analysis/regression-final.xml").findall(".//failure")
    current = Path(os.environ["CHG301_R2_APPLICATION_EVIDENCE"])
    manifest = json.loads(Path(os.environ["CHG301_R2_APPLICATION_MANIFEST"]).read_bytes())
    for name in ("frontend-builder-arm64", "frontend-runner-arm64", "backend-runner-arm64"):
        artifact = manifest["artifacts"][name]
        report = json.loads(Path(artifact["cli"]["path"]).read_bytes())
        assert report["image_id"] == artifact["id"] and report["exit_code"] == 0
        assert report["removed"] and report["baseline_unchanged"]
        owned = json.loads((Path(artifact["work"])/"cli/owned.json").read_bytes())
        rows = [json.loads(Path(r["path"]).read_bytes()) for r in manifest["commands"]]
        create = next(r for r in rows if "create" in r["args"] and owned["image_id"] in r["args"])
        args = create["args"]
        assert args[args.index("--network")+1] == "none"
        assert args[args.index("--user")+1] == "10001:10001"
        assert "--read-only" in args and "--privileged" not in args
