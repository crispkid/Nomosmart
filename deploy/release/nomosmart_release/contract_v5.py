"""Explicit signed local risk-reviewed release; legacy v4 is never reinterpreted."""
from __future__ import annotations
from pathlib import Path
from .contract import ReleaseContractError
from .contract_v3 import REQUIRED_GATES as BUILD_GATES, verify_payload as verify_common_payload
from .contract_v4 import DEFERRED_GATES, EXCLUDED_GATES, _validate_manifest
from .quality_reports import (read_reference, validate_policy, verify_case_review,
    verify_measurements, verify_regression_statistics, verify_assessment_references, assess_readiness)

SCHEMA_VERSION=5
PACKAGE_TYPE="nomosmart-local-risk-reviewed-release"
PURPOSE="local-risk-reviewed-release"
QUALITY_REFERENCES=("quality_policy","quality_readiness","coverage_measurements","regression_statistics")
FILE_REFERENCES=("external_dependencies","external_advisory","migration_contract",*QUALITY_REFERENCES)
REQUIRED_GATES=BUILD_GATES|frozenset({"compose","local_helm","application_static_security","upgrade_restore","critical_scenarios","critical_e2e","coverage_measurement"})


def validate_manifest(payload):
    _validate_manifest(payload,schema_version=SCHEMA_VERSION,package_type=PACKAGE_TYPE,
        purpose=PURPOSE,required_gates=REQUIRED_GATES,file_references=FILE_REFERENCES)
    if payload["quality_policy"]["path"]!="deploy/release/quality-policy.json":
        raise ReleaseContractError("reviewed release must use its approved versioned quality policy")


def verify_payload(root:Path,payload):
    images,platforms=verify_common_payload(root,payload,protocol_contract=True)
    inventory={r["path"]:r["sha256"]for r in payload["files"]}
    def report(ref):return read_reference(root,ref,inventory=inventory)
    for field in ("deferred_validation","excluded_validation"):
        for name,row in payload[field].items():
            approval=report(row["approval"])
            if (not isinstance(approval,dict) or not approval.get("approver") or not approval.get("quote")
                    or not str(approval.get("change_id","")).startswith("CHG-")
                    or approval.get("decisions",{}).get(name)!=row["status"]):
                raise ReleaseContractError("reviewed release scope lacks its actual approval")
    source_sha=payload["source"]["git_sha"]
    policy=report(payload["quality_policy"]);validate_policy(policy)
    coverage=report(payload["coverage_measurements"])
    measured=verify_measurements(root,coverage,source_sha=source_sha,inventory=inventory)
    statistics=report(payload["regression_statistics"]);verify_regression_statistics(statistics,source_sha)
    for suite in statistics["suites"].values():
        for ref in suite["evidence"]:report(ref)
    ready=report(payload["quality_readiness"])
    if not isinstance(ready,dict) or set(ready)!={"assessment","decision","case_review"}:
        raise ReleaseContractError("reviewed release readiness report is incomplete")
    ledger=report(ready["case_review"])
    unresolved=verify_case_review(ledger)
    if ready["assessment"].get("case_review_unresolved")!=len(unresolved):
        raise ReleaseContractError("reviewed release hides unreviewed case scope")
    verify_assessment_references(root,ready["assessment"],inventory=inventory,reviewed_source_inventory=measured["source_files"],case_review=ledger)
    decision=assess_readiness(policy,ready["assessment"],policy_sha256=payload["quality_policy"]["sha256"],source_sha=source_sha)
    if ready["assessment"].get("measurement_status")!=measured["measurement_status"] or ready["decision"]!=decision or decision["status"]!="READY_FOR_LOCAL_RELEASE_REVIEW":
        raise ReleaseContractError("reviewed release has unresolved mandatory quality conditions")
    for suite in statistics["suites"].values():
        if suite["unknowns"] or any(r["triage"]in {"critical","unknown"}for r in suite["failures"]):
            raise ReleaseContractError("current regression failures or scope remain unreviewed")
    for name in REQUIRED_GATES:
        gate=payload["gates"][name];value=report({"path":gate["path"],"sha256":gate["evidence_sha256"]})
        if not value["artifacts"]:raise ReleaseContractError("reviewed release gate lacks actual artifacts: "+name)
    # Required quality gates must cite these exact reports, not unrelated passed artifacts.
    for gate_name,field in [("critical_scenarios","quality_readiness"),("coverage_measurement","coverage_measurements")]:
        gate=payload["gates"][gate_name]
        value=report({"path":gate["path"],"sha256":gate["evidence_sha256"]})
        if payload[field]not in value["artifacts"]:
            raise ReleaseContractError("quality gate is not bound to its declared report")
    gate=payload["gates"]["critical_e2e"]
    value=report({"path":gate["path"],"sha256":gate["evidence_sha256"]})
    matches=[r for r in value["artifacts"]if r["path"].endswith("critical-e2e-summary.json")]
    if len(matches)!=1:raise ReleaseContractError("actual critical E2E summary is missing")
    e2e=report(matches[0]);required_e2e={s["id"]for s in policy["scenarios"]if s["verification_level"]=="e2e"}
    if not isinstance(e2e,dict)or e2e.get("source_sha")!=source_sha or set(e2e.get("scenarios",{}))!=required_e2e:
        raise ReleaseContractError("critical E2E scenario scope differs")
    for sid,row in e2e["scenarios"].items():
        if not isinstance(row,dict)or row.get("status")!="verified"or not row.get("evidence"):
            raise ReleaseContractError("critical E2E did not complete")
        for ref in row["evidence"]:
            report(ref)
            if ref not in ready["assessment"]["scenarios"][sid]["evidence"]:
                raise ReleaseContractError("critical E2E evidence differs from the reviewed scenario")
    return images,platforms
