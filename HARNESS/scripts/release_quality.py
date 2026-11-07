#!/usr/bin/env python3
"""Read-only current quality review. Never starts services or reruns product tests."""
from __future__ import annotations
import argparse
from pathlib import Path
import json
import os
import sys


def verify_review(root:Path, review_path:Path, *, readiness=False):
    sys.path.insert(0,str(root/"deploy/release"))
    from nomosmart_release.contract import ReleaseContractError, sha256_file, _load_json
    from nomosmart_release.quality_reports import (read_reference, verify_measurements,
        verify_case_review, verify_assessment_references, validate_policy, assess_readiness,
        verify_regression_statistics)
    # The active source policy is authoritative, not an arbitrary policy supplied by a report.
    policy_path=root/"deploy/release/quality-policy.json"
    policy=_load_json(policy_path,label="active quality policy");validate_policy(policy)
    value=_load_json(review_path,label="quality review index")
    if not isinstance(value,dict) or value.get("schema_version")!=1 or value.get("kind")!="offline-source-quality-review":
        raise ReleaseContractError("unknown quality review index")
    base=review_path.parent
    if value.get("policy_sha256")!=sha256_file(policy_path):raise ReleaseContractError("quality policy identity differs")
    bundle=read_reference(base,value["measurements"])
    measured=verify_measurements(base,bundle,source_sha=value["source_sha"],source_root=root)
    public_measured={k:v for k,v in measured.items()if k!="source_files"}
    if not readiness:return public_measured
    ledger=read_reference(base,value["case_review"])
    unresolved=verify_case_review(ledger)
    assessment=read_reference(base,value["assessment"])
    if assessment.get("case_review_unresolved")!=len(unresolved):raise ReleaseContractError("unknown case scope was hidden")
    if assessment.get("measurement_status")!=measured["measurement_status"]:raise ReleaseContractError("measurement validity differs")
    verify_assessment_references(base,assessment,source_root=root,case_review=ledger)
    statistics=read_reference(base,value["regression_statistics"])
    verify_regression_statistics(statistics,value["source_sha"])
    result=assess_readiness(policy,assessment,policy_sha256=value["policy_sha256"],source_sha=value["source_sha"])
    for side,row in statistics["suites"].items():
        for ref in row["evidence"]:read_reference(base,ref)
        for failure in row["failures"]:
            if failure["triage"]in {"critical","unknown"}:result["blockers"].append({"kind":"regression_failure","id":side,"reason":failure["reason"]})
        if row["unknowns"]:result["blockers"].append({"kind":"regression_scope","id":side,"count":len(row["unknowns"])})
    if result["blockers"]:result["status"]="NOT_READY"
    result["measurement"]=public_measured
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["coverage","readiness"])
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--review",type=Path,default=None)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args(argv);root=args.root.resolve()
    sys.path.insert(0,str(root/"deploy/release"))
    from nomosmart_release.contract import ReleaseContractError
    review=args.review or (Path(os.environ["NOMOSMART_QUALITY_REVIEW"])if os.environ.get("NOMOSMART_QUALITY_REVIEW")else root/"test-results/quality-review/index.json")
    try:
        result=verify_review(root,review,readiness=args.command=="readiness")
        code=int(args.command=="readiness"and result["status"]!="READY_FOR_LOCAL_RELEASE_REVIEW")
    except (ReleaseContractError,OSError,ValueError,KeyError,TypeError)as exc:
        # Safe diagnostic category only; private artifact values and paths are not echoed.
        result={"status":"NOT_READY"if args.command=="readiness"else "INVALID_OR_MISSING_MEASUREMENT","reason":str(exc)if isinstance(exc,ReleaseContractError)else type(exc).__name__,"production_ready":False};code=1
    payload=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.output:
        if args.output.exists():raise SystemExit("refuse overwriting a prior quality result")
        args.output.write_text(payload)
    print(payload,end="");return code

if __name__=="__main__":raise SystemExit(main())
