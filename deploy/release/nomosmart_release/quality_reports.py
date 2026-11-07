"""Risk-reviewed quality metadata. Measurement never implies functional success."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from typing import Any
from .contract import ReleaseContractError, SHA256, _bounded_file, _load_json, sha256_file
from .contract_v3 import _reference

POLICY_VERSION = 1
GROUPS = frozenset({"identity", "directory", "permissions", "ingestion", "governance", "retrieval", "data_safety", "security", "delivery", "workflow_ui"})

def _reject(message):
    raise ReleaseContractError(message)

def _metric(covered,total,*,label,require_target=False):
    if (type(covered) is not int or type(total) is not int or total<=0 or covered<0 or covered>total):
        _reject('coverage counters are invalid: '+label)
    result=100*covered/total
    if require_target and result<80:_reject('coverage is below 80%: '+label)
    return result


def verify_coverage(report: dict[str,Any],side: str, *, require_target=False) -> dict:
    if side=='frontend':
        total=report.get('total')
        if not isinstance(total,dict) or len(report)<2:_reject('frontend coverage file inventory is empty')
        for metric in ('lines','statements','functions','branches'):
            row=total.get(metric)
            if not isinstance(row,dict):_reject('frontend coverage metric is missing')
            pct=_metric(row.get('covered'),row.get('total'),label='frontend '+metric,require_target=require_target)
            reported=row.get('pct')
            if type(reported) not in {int,float} or not math.isfinite(reported) or abs(reported-pct)>0.02:
                _reject('frontend coverage percentage differs from counters')
            values=[r.get(metric) for name,r in report.items() if name!='total' and isinstance(r,dict)]
            if (len(values)!=len(report)-1 or any(not isinstance(v,dict) or type(v.get('total')) is not int or type(v.get('covered')) is not int or v['total']<0 or not 0<=v['covered']<=v['total'] for v in values)
                    or sum(v['total'] for v in values)!=row['total'] or sum(v['covered'] for v in values)!=row['covered']):
                _reject('frontend coverage totals differ from its files')
    elif side=='backend':
        if not isinstance(report.get('meta'),dict) or report['meta'].get('branch_coverage') is not True:
            _reject('backend branch measurement is required')
        total=report.get('totals');files=report.get('files')
        if not isinstance(total,dict) or not isinstance(files,dict) or not files:_reject('backend coverage file inventory is empty')
        for covered,denominator in [('covered_lines','num_statements'),('covered_branches','num_branches')]:
            _metric(total.get(covered),total.get(denominator),label='backend '+denominator,require_target=require_target)
            summaries=[row.get('summary') if isinstance(row,dict) else None for row in files.values()]
            if (any(not isinstance(s,dict) or type(s.get(covered)) is not int or type(s.get(denominator)) is not int or s[denominator]<0 or not 0<=s[covered]<=s[denominator] for s in summaries)
                    or sum(s[covered] for s in summaries)!=total[covered] or sum(s[denominator] for s in summaries)!=total[denominator]):
                _reject('backend coverage totals differ from its files')
    else:_reject('unknown coverage side')


    if side == "frontend":
        return {m: 100 * report["total"][m]["covered"] / report["total"][m]["total"] for m in ("lines", "statements", "functions", "branches")}
    return {"lines": 100 * total["covered_lines"] / total["num_statements"], "branches": 100 * total["covered_branches"] / total["num_branches"]}

def read_reference(root: Path, ref: dict, *, inventory=None):
    relative = _reference(ref, label="quality evidence")
    path = _bounded_file(root, relative)
    if sha256_file(path) != ref["sha256"] or (inventory is not None and inventory.get(relative) != ref["sha256"]):
        _reject("quality evidence content is not bound to its inventory")
    return _load_json(path, label="quality evidence")


def validate_policy(policy):
    if (not isinstance(policy, dict) or policy.get("schema_version") != POLICY_VERSION
            or type(policy.get("schema_version")) is not int or policy.get("policy_id") != "nomosmart-risk-quality-v1"
            or policy.get("scope") != "local-risk-reviewed-release"
            or policy.get("coverage") != {"measurement_required": True, "advisory_target_percent": 80, "below_target_blocks": False}
            or policy.get("critical_waiver_allowed") is not False):
        _reject("unknown or invalid quality policy")
    scenarios = policy.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        _reject("mandatory scenario inventory is empty")
    ids = set(); groups = set()
    for row in scenarios:
        if (not isinstance(row, dict) or set(row) != {"id", "group", "requirement", "behavior", "mandatory", "verification_level"}
                or row["mandatory"] is not True or row["group"] not in GROUPS
                or row["verification_level"] not in {"live", "native", "delivery", "e2e"}
                or any(not isinstance(row[k], str) or not row[k].strip() for k in ("id", "requirement", "behavior"))
                or row["id"] in ids):
            _reject("invalid or duplicate critical scenario")
        ids.add(row["id"]); groups.add(row["group"])
    if groups != GROUPS:
        _reject("critical behavior group is missing")
    return {r["id"]: r for r in scenarios}


def verify_case_review(ledger, *, expected_ids=None):
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1 or ledger.get("kind") != "current-risk-case-review":
        _reject("case review format is invalid")
    rows = ledger.get("cases")
    if not isinstance(rows, list) or not rows:
        _reject("case review is empty")
    ids=set(); unresolved=[]
    for row in rows:
        if not isinstance(row, dict) or not SHA256.fullmatch(str(row.get("case_id_sha256", ""))) or row["case_id_sha256"] in ids:
            _reject("case review contains duplicate or missing identities")
        ids.add(row["case_id_sha256"])
        state=row.get("review_status")
        if state not in {"CURRENT_MANDATORY", "CURRENT_SUPPORTING", "RETIRED_MECHANISM", "HISTORICAL_MISSING", "LOW_RISK_FOLLOWUP", "UNRESOLVED"}:
            _reject("unknown case scope cannot become low risk")
        if not row.get("reason") or not row.get("owner") or not row.get("source_review"):
            _reject("individual case review requires source, reason and owner")
        if state in {"RETIRED_MECHANISM", "LOW_RISK_FOLLOWUP"} and (not row.get("requirement") or not row.get("successor_scenarios")):
            _reject("retired or deferred behavior lacks current successors")
        if state == "LOW_RISK_FOLLOWUP" and (not row.get("follow_up") or not row.get("reviewed_by")):
            _reject("low risk follow-up requires an explicit review and follow-up")
        if state == "UNRESOLVED": unresolved.append(row["case_id_sha256"])
        if row.get("count_as_new_PASS") is not False:
            _reject("case classification must not create a new PASS")
    if expected_ids is not None and ids != set(expected_ids):
        _reject("case review identities differ from the frozen collection")
    for row in ledger.get("recorded_cases",[]):
        if (not isinstance(row,dict) or not SHA256.fullmatch(str(row.get("case_id_sha256","")))
                or row["case_id_sha256"] in ids or row.get("kind")!="recorded-live-acceptance"
                or not row.get("original_case_id") or not row.get("requirement")
                or not row.get("producer_source") or not row.get("source_review")
                or not row.get("owner") or row.get("count_as_new_PASS")is not False):
            _reject("recorded live case is not individually source reviewed")
        ids.add(row["case_id_sha256"])
        if not row.get("verified_scenario_links"):unresolved.append(row["case_id_sha256"])
    return unresolved


def verify_regression_statistics(value, source_sha):
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("source_sha") != source_sha or value.get("historical_results_relabelled") is not False
            or set(value.get("suites", {})) != {"frontend", "backend", "installer", "release"}):
        _reject("actual regression statistics are missing")
    for name, row in value["suites"].items():
        if (not isinstance(row, dict) or row.get("status") not in {"complete", "partial", "missing"}
                or not isinstance(row.get("evidence"), list)
                or not isinstance(row.get("failures"), list) or not isinstance(row.get("unknowns"), list)):
            _reject("invalid regression statistics: " + name)
        if row["status"] != "missing" and not row["evidence"]:
            _reject("regression statistics lack actual evidence: " + name)
        for failure in row["failures"]:
            if not isinstance(failure, dict) or failure.get("triage") not in {"critical", "low_risk", "retired", "unknown"} or not failure.get("reason"):
                _reject("current regression failure is not triaged")
    return value


def assess_readiness(policy, assessment, *, policy_sha256, source_sha):
    """Recompute from reviewed facts. Ignore a caller-supplied READY boolean."""
    scenarios=validate_policy(policy)
    if (not isinstance(assessment, dict) or assessment.get("schema_version") != 1
            or assessment.get("policy_sha256") != policy_sha256 or assessment.get("source_sha") != source_sha):
        _reject("quality assessment belongs to another policy or source")
    actual=assessment.get("scenarios")
    if not isinstance(actual, dict) or set(actual) != set(scenarios):
        _reject("critical scenario inventory differs from the policy")
    blockers=[]; verified=[]
    for identity, contract in scenarios.items():
        row=actual[identity]
        if not isinstance(row, dict) or row.get("status") not in {"verified", "missing", "failed", "unreviewed"}:
            _reject("invalid critical scenario result")
        if row["status"] == "verified":
            if (not row.get("evidence") or not row.get("source_files") or not row.get("review_reason")
                    or row.get("verification_level") != contract["verification_level"]
                    or row.get("qualification") != "source-bound-existing-evidence"):
                _reject("critical scenario lacks qualified evidence: " + identity)
            verified.append(identity)
        else: blockers.append({"kind":"critical_scenario", "id":identity, "status":row["status"], "reason":row.get("reason", "Missing qualified evidence")})
    if type(assessment.get("case_review_unresolved")) is not int or assessment["case_review_unresolved"] < 0:
        _reject("case review unresolved count is invalid")
    if assessment["case_review_unresolved"]: blockers.append({"kind":"unresolved_case_scope", "count":assessment["case_review_unresolved"]})
    risks=assessment.get("risks")
    if not isinstance(risks, list): _reject("risk review is missing")
    for risk in risks:
        if not isinstance(risk, dict) or risk.get("severity") not in {"critical", "high", "medium", "low", "unknown"} or not risk.get("reason") or not risk.get("owner"):
            _reject("invalid risk review")
        if risk["severity"] in {"unknown", "high", "critical"}:
            if risk.get("status") != "resolved":
                acceptance=risk.get("acceptance")
                if risk["severity"] == "unknown" or not isinstance(acceptance, dict) or not acceptance.get("scope") or not acceptance.get("approver") or not acceptance.get("evidence"):
                    blockers.append({"kind":"risk", "id":risk.get("id"), "reason":risk["reason"]})
                else:
                    try: expires=datetime.fromisoformat(acceptance["expires_at"].replace("Z", "+00:00"))
                    except (KeyError, TypeError, ValueError): _reject("risk acceptance expiry is missing")
                    if expires.tzinfo is None or expires <= datetime.now(timezone.utc): blockers.append({"kind":"expired_risk_acceptance", "id":risk.get("id")})
        elif not risk.get("follow_up"):
            _reject("known noncritical risk follow-up is missing")
    required = {"security", "compose", "helm", "migration_restore", "signature_source", "critical_e2e"}
    delivery=assessment.get("delivery")
    if not isinstance(delivery, dict) or set(delivery) != required: _reject("required delivery inventory differs")
    for name,row in delivery.items():
        if not isinstance(row,dict) or row.get("status") not in {"verified", "missing", "failed", "unreviewed"}: _reject("invalid delivery state")
        if row["status"] != "verified" or not row.get("evidence"): blockers.append({"kind":"delivery", "id":name,"reason":row.get("reason", "Missing evidence")})
    if assessment.get("measurement_status") != "valid": blockers.append({"kind":"coverage_measurement", "reason":"Valid complete-source measurement is required"})
    return {"schema_version":1,"kind":"risk-quality-readiness","policy_sha256":policy_sha256,"source_sha":source_sha,
        "status":"NOT_READY" if blockers else "READY_FOR_LOCAL_RELEASE_REVIEW", "verified_scenarios":verified,
        "blockers":blockers,"coverage_target_is_release_gate":False,"production_ready":False,"publication_authorized":False}


def verify_assessment_references(root, assessment, *, inventory=None, source_root=None, reviewed_source_inventory=None, case_review=None):
    """Bind every accepted fact to inventoried bytes and its reviewed source readset."""
    def refs(values):
        if not isinstance(values, list) or not values: _reject("qualified evidence reference list is empty")
        for ref in values: _verify_file_reference(root,ref,inventory=inventory)
    catalog={r["case_id_sha256"]:r for r in (case_review["cases"]+case_review.get("recorded_cases",[]))}if isinstance(case_review,dict)else {}
    for scenario,row in assessment["scenarios"].items():
        if row.get("status") != "verified": continue
        refs(row["evidence"])
        case_ids=row.get("case_ids_sha256")
        if not isinstance(case_ids,list)or not case_ids or len(set(case_ids))!=len(case_ids):
            _reject("verified scenario lacks individual qualified case identities")
        for identity in case_ids:
            case=catalog.get(identity)
            if not case or scenario not in case.get("verified_scenario_links",[]):
                _reject("candidate case links do not prove the verified scenario")
            review=case["source_review"]
            if case.get("kind")=="recorded-live-acceptance":
                _verify_file_reference(root,case["producer_source"],inventory=inventory)
                if case["producer_source"]["sha256"]!=review.get("producer_source_sha256"):
                    _reject("recorded case producer differs from its individual source review")
            elif row.get("source_files",{}).get(case["module"])!=review["module_sha256"]:
                _reject("verified scenario test source differs from its individual review")
        if row.get("proof_format")=="recorded-observation-v1":
            verify_recorded_observations(root,row,scenario,inventory=inventory)
            native_ids=[identity for identity in case_ids if catalog[identity].get("kind")!="recorded-live-acceptance"]
            if native_ids:verify_native_case_support(root,row,native_ids,inventory=inventory)
        elif row.get("proof_format")not in {None,"native-qualified-map-v1"}:
            _reject("unknown scenario proof format")
        else:
            verify_native_case_support(root,row,case_ids,inventory=inventory)
        for name,digest in row["source_files"].items():
            _reference({"path":name,"sha256":digest},label="scenario source")
            if source_root is not None:
                if sha256_file(_bounded_file(source_root,name)) != digest: _reject("scenario source has changed")
            elif reviewed_source_inventory is None or reviewed_source_inventory.get(name) != digest:
                _reject("scenario source is not inventoried")
    for risk in assessment["risks"]:
        if risk.get("acceptance"): refs(risk["acceptance"]["evidence"])
    for row in assessment["delivery"].values():
        if row.get("status") == "verified": refs(row["evidence"])


def verify_measurements(root, bundle, *, source_sha=None, inventory=None, source_root=None):
    if (not isinstance(bundle,dict) or bundle.get("schema_version") != 1
            or bundle.get("kind") != "source-bound-coverage-measurements"
            or set(bundle.get("sides",{})) != {"frontend","backend"}
            or bundle.get("functional_suite_pass") is not False
            or (source_sha is not None and bundle.get("source_sha") != source_sha)):
        _reject("coverage measurement identity is invalid")
    metrics={}; source_files={}
    for name,digest in bundle.get("dependency_source_files",{}).items():
        _reference({"path":name,"sha256":digest},label="reviewed source dependency")
        if source_root is not None and sha256_file(_bounded_file(source_root,name))!=digest:
            _reject("reviewed source dependency has changed")
        source_files[name]=digest
    for side,row in bundle["sides"].items():
        if not isinstance(row,dict) or not row.get("provenance") or not row.get("source_files"):
            _reject("coverage measurement lacks source or actual producer provenance")
        sources=row["source_files"]
        if not isinstance(sources,dict): _reject("coverage source inventory is invalid")
        for name,digest in sources.items():
            _reference({"path":name,"sha256":digest},label="coverage source")
            if not name.startswith("frontend/src/" if side=="frontend" else "backend/app/"):
                _reject("coverage source is outside application source")
            if source_root is not None and sha256_file(_bounded_file(source_root,name)) != digest:
                _reject("coverage measurement source has changed")
        report=read_reference(root,row["report"],inventory=inventory)
        measured=set(report)-{"total"} if side=="frontend" else set(report.get("files",{}))
        if measured != set(sources): _reject("coverage report omits or adds source files")
        metrics[side]=verify_coverage(report,side)
        for reference in row["provenance"]:
            path=_reference(reference,label="coverage producer")
            actual=_bounded_file(root,path)
            if sha256_file(actual)!=reference["sha256"] or (inventory is not None and inventory.get(path)!=reference["sha256"]):
                _reject("coverage producer content differs from bound provenance")
        if row.get("original_results_relabelled") is not False or row.get("instrumentation_changed") is not False:
            _reject("coverage measurement altered instrumentation or original outcomes")
        if source_root is not None:
            if side=="frontend":
                expected={p.relative_to(source_root).as_posix() for p in (source_root/"frontend/src").rglob("*") if p.is_file() and p.suffix in {".ts",".tsx"} and not p.relative_to(source_root).as_posix().startswith("frontend/src/app/api/")}
            else:
                expected={p.relative_to(source_root).as_posix() for p in (source_root/"backend/app").rglob("*.py") if p.relative_to(source_root).as_posix()!="backend/app/db/models.py"}
            if set(sources)!=expected: _reject("measurement source denominator is incomplete")
        source_files.update(sources)
    return {"measurement_status":"valid","metrics":metrics,"target_percent":80,
        "target_met":{s:all(v>=80 for v in m.values())for s,m in metrics.items()},
        "functional_suite_pass":False,"release_readiness_implied":False,"source_files":source_files}


def _verify_file_reference(root,ref,*,inventory=None):
    relative=_reference(ref,label="original evidence")
    actual=_bounded_file(root,relative)
    if sha256_file(actual)!=ref["sha256"]or(inventory is not None and inventory.get(relative)!=ref["sha256"]):
        _reject("original evidence differs from its bound bytes")
    return actual


def _pointer(value,path):
    """Small, non-executable path vocabulary for actual JSON observations."""
    if not isinstance(path,list)or not path or len(path)>32:_reject("observation pointer is invalid")
    for part in path:
        if isinstance(value,dict)and isinstance(part,str)and part in value:value=value[part]
        elif isinstance(value,list)and type(part)is int and 0<=part<len(value):value=value[part]
        else:_reject("original observation field is missing")
    return value


def verify_recorded_observations(root,row,scenario,*,inventory=None):
    """Read approved existing live/browser/deployment facts, never a PASS-only label.

    The package signature attests the explicit requirement-to-observation source
    review. Raw object digests, concrete observation predicates and source
    captures stay bound; normalization cannot create a provider/service result.
    """
    proof_ref=row.get("observation_proof")
    if proof_ref not in row["evidence"]:_reject("observation proof is outside scenario evidence")
    proof=read_reference(root,proof_ref,inventory=inventory)
    if (not isinstance(proof,dict)or proof.get("schema_version")!=1
            or proof.get("kind")!="recorded-scenario-observations"or proof.get("scenario")!=scenario
            or set(proof.get("case_ids_sha256",[]))!=set(row["case_ids_sha256"])
            or proof.get("original_results_relabelled")is not False
            or type(proof.get("new_feature_execution"))is not bool
            or not proof.get("reviewed_scope")or not proof.get("scope_authority")):
        _reject("recorded scenario proof identity or scope is invalid")
    refs={r["path"]:r["sha256"]for r in row["evidence"]}
    if proof["new_feature_execution"]:
        # A fresh live observation is distinct from retained evidence. Its exact
        # process result and original output bytes must both be present.
        executions=proof.get("execution_outputs")
        if not isinstance(executions,list)or not executions:
            _reject("fresh live observations lack waited process/output evidence")
        for pair in executions:
            if not isinstance(pair,dict)or set(pair)!={"execution","stdout","producer"}:
                _reject("fresh execution binding is invalid")
            er,sr,pr=pair["execution"],pair["stdout"],pair["producer"]
            if any(not isinstance(r,dict)or refs.get(r.get("path"))!=r.get("sha256")for r in [er,sr,pr]):
                _reject("fresh execution is outside scenario evidence")
            execution=read_reference(root,er,inventory=inventory)
            _verify_file_reference(root,sr,inventory=inventory)
            _verify_file_reference(root,pr,inventory=inventory)
            if (not isinstance(execution,dict)or execution.get("exit")!=0
                    or execution.get("wait_completed")is not True
                    or type(execution.get("pid"))is not int or execution["pid"]<=0
                    or not isinstance(execution.get("argv"),list)or not execution["argv"]
                    or execution.get("stdout_sha256")!=sr["sha256"]
                    or not SHA256.fullmatch(str(pr["sha256"]))):
                _reject("fresh live process did not complete with its bound output")
    checks=proof.get("checks");bindings=proof.get("source_bindings")
    if not isinstance(checks,list)or len(checks)<2 or not isinstance(bindings,list)or not bindings:
        _reject("recorded scenario requires concrete observations and source captures")
    concrete=0
    for check in checks:
        if not isinstance(check,dict)or not check.get("requirement_part"):_reject("unmapped observation cannot qualify a scenario")
        ref=check.get("artifact")
        if not isinstance(ref,dict)or refs.get(ref.get("path"))!=ref.get("sha256"):_reject("observation artifact is outside scenario evidence")
        actual=_pointer(read_reference(root,ref,inventory=inventory),check.get("pointer"))
        expected=check.get("expected");op=check.get("operator")
        if op=="equals":passed=type(actual)is type(expected)and actual==expected
        elif op=="at_least":passed=type(actual)in {int,float}and type(expected)in {int,float}and math.isfinite(actual)and actual>=expected
        elif op=="contains":passed=isinstance(actual,(list,str))and type(expected)in {int,str}and expected in actual
        elif op=="nonempty":passed=type(expected)is bool and expected is True and isinstance(actual,(dict,list,str))and bool(actual)
        else:_reject("unknown observation predicate")
        if not passed:_reject("original live observation does not satisfy its reviewed condition")
        if check["pointer"][-1]not in {"status","result","pass","passed","scoped_functional_status"}:concrete+=1
    if not concrete:_reject("status labels alone are not behavioral evidence")
    for binding in bindings:
        if not isinstance(binding,dict):_reject("source capture binding is invalid")
        name=binding.get("source_path");digest=binding.get("sha256");ref=binding.get("capture")
        if row["source_files"].get(name)!=digest or not isinstance(ref,dict)or refs.get(ref.get("path"))!=ref.get("sha256"):
            _reject("recorded source capture differs from current reviewed source")
        captured=_pointer(read_reference(root,ref,inventory=inventory),binding.get("pointer"))
        if captured!=digest:_reject("original producer did not capture this source digest")
    # All sources claimed by this observation must have actual captured hashes.
    if {b["source_path"]for b in bindings}!=set(row["source_files"]):
        _reject("recorded observation includes uncaptured source claims")


def verify_native_case_support(root,row,case_ids,*,inventory=None):
    report_pairs=[]
    for ref in row["evidence"]:
        actual=_verify_file_reference(root,ref,inventory=inventory)
        if actual.suffix==".json":report_pairs.append((read_reference(root,ref,inventory=inventory),ref))
    reports=[value for value,_ in report_pairs]
    # Recognize actual native qualification maps. A status string by itself grants nothing.
    maps=[v for v in reports if isinstance(v,dict)and (isinstance(v.get("per_node"),dict)or (v.get("case_id_encoding")=="sha256"and isinstance(v.get("per_case_sha256"),dict)))]
    if not maps:_reject("verified scenario lacks an actual per-case qualification map")
    evidence_hashes={r["sha256"]for r in row["evidence"]}
    supported=set()
    for value in maps:
        hashed=value.get("case_id_encoding")=="sha256"
        entries=value["per_case_sha256"]if hashed else value["per_node"]
        if value.get("unique_qualified")!=len(entries):_reject("qualified case map counters differ")
        for node,qualification in entries.items():
            if hashed and not SHA256.fullmatch(node):_reject("qualified hash identity is invalid")
            if not isinstance(node,str)or not isinstance(qualification,dict)or qualification.get("sha256")not in evidence_hashes:
                _reject("qualified case map lacks its original qualification bytes")
            q=next(v for v,r in report_pairs if r["sha256"]==qualification["sha256"])
            if (not isinstance(q,dict)or q.get("status")not in {"QUALIFIED_REUSE","FUNCTIONAL_NATIVE_QUALIFIED"}
                    or q.get("outcome",{}).get("functional_pass")is not True
                    or q.get("prior_failures_or_exit_rewritten")is not False
                    or not q.get("native_execution_sha256")or not q.get("junit_sha256")):
                _reject("original native qualification does not prove functional success")
            supported.add(node if hashed else hashlib.sha256(node.encode()).hexdigest())
    if not set(case_ids)<=supported:_reject("verified scenario cases are outside the actual qualified result")

