"""Actual source/scan identity and pure scope policy; no service substitutes."""
import json
import base64
import os
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
import chg301_r2_delivery as delivery

RUN = Path(os.environ["CHG301_R2_DELIVERY_EVIDENCE"]).resolve(strict=True)
RECORD = json.loads((RUN / "manifest.json").read_bytes())


def test_current_approval_and_unchanged_real_product_source():
    # The closed run proves its actual historical approval, not authority to
    # execute again under the newly approved formal-dependency plan.
    actual = next(s for s in (ROOT / "DEVELOPMENT_PLAN.md").read_text().split("\n## ")[1:]
                  if s.splitlines()[0] == delivery.SECTION)
    assert delivery.file_sha(delivery.PLAN) == delivery.PLAN_SHA
    assert all(s in actual for s in (delivery.APPROVAL, delivery.PRE_SHA, "Gate 4 approval: APPROVED."))
    assert RECORD["plan_sha256"] == delivery.PLAN_SHA
    from chg301_r2_application_evidence import historical_sources
    # Verify the entire historical source byte-for-byte after reversing only
    # the current plan's exact RustFS and builder-npm recipe replacements.
    assert historical_sources(RECORD["source"]) == delivery.source_manifest()
    assert RECORD["runtime_mutations"] == RECORD["pr_writes"] == 0


def test_retired_delivery_runner_rejects_current_formal_dependency_approval():
    with pytest.raises(ValueError, match="delivery_current_approval_required"):
        delivery.approval_guard()


@pytest.mark.parametrize("uses,expected", [
    (["delivery"], "IN_SCOPE"), (["install"], "IN_SCOPE"), (["build"], "IN_SCOPE"),
    (["unused-test"], "DEFERRED_TEST_INFRA"), (["external"], "EXTERNAL_PREREQUISITE"),
    (["install", "unused-test"], "IN_SCOPE"), (["build", "unused-test"], "IN_SCOPE"),
    (["external", "install"], "IN_SCOPE"), (["external", "unused-test"], "UNRESOLVED"),
    ([], "UNRESOLVED"), (["guess"], "UNRESOLVED"),
])
def test_use_classification_not_global_cve_suppression(uses, expected):
    assert delivery.classify(uses) == expected


def test_actual_installer_operators_and_optional_compose_not_omitted():
    rows = RECORD["declared_uses"]
    for name in ("OPERATOR_IMAGE", "PLUGIN_IMAGE", "SIDECAR_IMAGE"):
        row = next(r for r in rows if r["use"] == "installer" and r["name"] == name)
        assert row["classification"] == "IN_SCOPE_INSTALL"
        assert "@sha256:" in row["value"]
    assert any("debug" in p for r in rows for p in r.get("profiles", []))
    assert "PENDING" in RECORD["closure_status"] or RECORD["closure_status"].startswith("PARTIAL")


def test_actual_existing_candidate_cannot_pass_without_source_binding():
    rows = [dict(t, uses=["install"]) for t in RECORD["targets"]]
    with pytest.raises(ValueError, match="evidence_incomplete"):
        delivery.delivery_gate(rows)


@pytest.mark.parametrize("state", ["UNRESOLVED", "INDETERMINATE", "PROPOSED_NOT_AFFECTED", "DEFERRED_TEST_INFRA"])
def test_actual_high_is_not_removed_by_renaming_its_state(state):
    findings = [f for s in RECORD["scans"] for f in s["findings"].values()
                if f["severity"] in {"HIGH", "CRITICAL"}]
    assert findings, "requires actual scanner evidence, not fabricated CVEs"
    # Pure policy input derived from an actual finding; not external PASS evidence.
    with pytest.raises(ValueError, match="high_requires_resolution"):
        delivery.delivery_gate([{"uses": ["install", "unused-test"], "source_bound": True,
                                 "complete_scan": True, "findings": [{**findings[0], "state": state}]}])


def test_actual_all_severity_reports_and_sboms_remain_bound():
    assert RECORD["scans"]
    for scan in RECORD["scans"]:
        for report in scan["reports"].values():
            path = Path(report["path"])
            assert RUN in path.parents
            assert delivery.file_sha(path) == report["sha256"]
        assert scan["findings"] == delivery.raw_findings(json.loads(Path(scan["reports"]["cves"]["path"]).read_bytes()))
        assert scan["not_source_or_release_acceptance"] is True


def test_empty_inventory_never_means_security_pass():
    with pytest.raises(ValueError, match="missing_delivery_inventory"):
        delivery.delivery_gate([])


def test_each_real_sbom_describes_the_exact_scanned_image():
    assert len(RECORD["scans"]) == len(RECORD["targets"]) == 16
    for scan in RECORD["scans"]:
        doc = json.loads(Path(scan["reports"]["sbom"]["path"]).read_bytes())
        roots = [p for p in doc["packages"] if p.get("primaryPackagePurpose") == "CONTAINER"]
        assert len(roots) == 1 and len(doc["packages"]) > 1
        identity = scan["target"].get("manifest_digest") or scan["target"]["identity"]["id"]
        assert any(identity in r["referenceLocator"] for r in roots[0]["externalRefs"])


def test_real_offline_routes_include_init_jobs_and_operator_operand():
    rows = RECORD["rendered_images"]
    assert any("initContainers" in r["path"] for r in rows)
    assert any(r["kind"] == "Job" and "finalize" in r["name"] for r in rows)
    assert any(r["kind"] == "Cluster" and r["path"] == "spec.imageName" for r in rows)
    external = [r for r in rows if "external-services" in r["case"]]
    assert external
    assert not any(r["kind"] in {"Cluster", "StatefulSet"} for r in external)


def test_real_public_operator_manifests_and_encoded_sidecar_are_bound():
    for entry in RECORD["official_manifests"]:
        path = RUN / "analysis" / (entry["name"] + "-pinned.yaml")
        assert delivery.file_sha(path) == entry["rendered_sha256"]
        assert entry["image"] in path.read_text()
        if entry["sidecar"]:
            documents = list(yaml.safe_load_all(path.read_bytes()))
            encoded = [d["data"]["SIDECAR_IMAGE"] for d in documents if "SIDECAR_IMAGE" in d.get("data", {})]
            assert len(encoded) == 1
            assert base64.b64decode(encoded[0]).decode() == entry["sidecar"]


def test_real_local_audit_is_not_misrepresented_as_fresh_online_check():
    audit = RECORD["local_audit"]
    assert audit["same_source_files"] == 140
    assert audit["fresh_online_audit"].startswith("BLOCKED_PERMISSION")
    assert delivery.file_sha(Path(audit["historical_path"])) == audit["historical_sha256"]
    assert delivery.file_sha(Path(audit["bandit_path"])) == audit["bandit_sha256"]
    assert audit["not_release_acceptance"]
