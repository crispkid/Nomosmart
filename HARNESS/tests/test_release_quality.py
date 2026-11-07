"""CHG-419 T01..T04: read actual approved metadata, never execute business flows."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"deploy/release"),str(ROOT/"HARNESS/scripts")]
from nomosmart_release.contract import ReleaseContractError
from nomosmart_release.quality_reports import (validate_policy,verify_case_review,verify_measurements,verify_assessment_references,assess_readiness)


def artifact_root():
    configured=os.environ.get("NOMOSMART_QUALITY_REVIEW")
    if not configured:raise RuntimeError("actual approved review index is required")
    return Path(configured).resolve().parent


def load(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class QualityMetadataControls(unittest.TestCase):
    def test_C419_T01_actual_approval_and_unknown_policy_refusal(self):
        approval=load(ROOT/"docs/CHG-419-APPROVAL.json")
        self.assertEqual(approval["Gate4"],"APPROVED");self.assertEqual(approval["quote"],"同意")
        for row in approval["frozen_documents"]:self.assertEqual(digest(ROOT/row["path"]),row["sha256"])
        policy=load(ROOT/"deploy/release/quality-policy.json");self.assertEqual(len(validate_policy(policy)),31)
        damaged=copy.deepcopy(policy);damaged["schema_version"]=999
        with self.assertRaisesRegex(ReleaseContractError,"policy"):validate_policy(damaged)

    def test_C419_T02_actual_catalog_conservation_and_individual_review(self):
        base=artifact_root();proposal=load(ROOT/"docs/CHG-419-CASE-REVIEW-PROPOSAL.json");ledger=load(base/"case-review.json")
        ids={r["case_id_sha256"]for r in proposal["cases"]};self.assertEqual(len(ids),2576)
        unresolved=verify_case_review(ledger,expected_ids=ids);self.assertEqual(unresolved,[])
        rows=ledger["cases"];self.assertEqual(sum(r["prior_qualified_snapshot"]for r in rows),669)
        self.assertEqual(sum(r["frozen_inventory_disposition"]!="REQUIRED_CURRENT"for r in rows),57)
        self.assertEqual(sum(r["frozen_inventory_disposition"]=="REQUIRED_CURRENT"and not r["prior_qualified_snapshot"]for r in rows),1850)
        self.assertEqual(sum(r["nodeid"]is None for r in rows),2)
        self.assertTrue(all(r["source_review"]["module_sha256"]==digest(ROOT/r["module"])for r in rows))
        invalid=copy.deepcopy(ledger);invalid["cases"][0].update(review_status="LOW_RISK_FOLLOWUP",reason="",successor_scenarios=[])
        with self.assertRaises(ReleaseContractError):verify_case_review(invalid,expected_ids=ids)

    def test_C419_T03_real_low_measurements_and_corrupt_source_refusal(self):
        base=artifact_root();bundle=load(base/"measurements.json")
        actual=verify_measurements(base,bundle,source_root=ROOT)
        self.assertEqual(actual["measurement_status"],"valid");self.assertFalse(any(actual["target_met"].values()))
        self.assertFalse(actual["functional_suite_pass"]);self.assertFalse(actual["release_readiness_implied"])
        self.assertEqual(len(bundle["sides"]["frontend"]["source_files"]),149);self.assertEqual(len(bundle["sides"]["backend"]["source_files"]),155)
        invalid=copy.deepcopy(bundle);key=next(iter(invalid["sides"]["backend"]["source_files"]));invalid["sides"]["backend"]["source_files"][key]="0"*64
        with self.assertRaisesRegex(ReleaseContractError,"source has changed"):verify_measurements(base,invalid,source_root=ROOT)
        from nomosmart_release.quality_reports import verify_coverage
        report=load(base/"measurements/backend-coverage.json");report["totals"]["covered_lines"]+=1
        with self.assertRaisesRegex(ReleaseContractError,"totals differ"):verify_coverage(report,"backend")

    def test_C419_T04_real_owner_evidence_and_missing_critical_scenarios(self):
        base=artifact_root();policy=load(ROOT/"deploy/release/quality-policy.json");assessment=load(base/"assessment.json")
        verify_assessment_references(base,assessment,source_root=ROOT,case_review=load(base/"case-review.json"))
        self.assertEqual(assessment["scenarios"]["owner_protection"]["status"],"verified")
        actual=assess_readiness(policy,assessment,policy_sha256=digest(ROOT/"deploy/release/quality-policy.json"),source_sha=assessment["source_sha"])
        self.assertEqual(actual["status"],"NOT_READY");self.assertIn("owner_protection",actual["verified_scenarios"])
        self.assertTrue(any(b["kind"]=="critical_scenario"for b in actual["blockers"]))
        self.assertTrue(any(b["kind"]=="risk"for b in actual["blockers"]))
        damaged=copy.deepcopy(assessment);damaged["scenarios"]["owner_protection"]["case_ids_sha256"]=[]
        with self.assertRaisesRegex(ReleaseContractError,"individual qualified"):
            verify_assessment_references(base,damaged,source_root=ROOT,case_review=load(base/"case-review.json"))

class RecordedEvidenceControls(unittest.TestCase):
    """C420-T02: actual retained AD observations and native HTTPS qualifications."""
    def inputs(self, name):
        configured=os.environ.get("NOMOSMART_RECORDED_EVIDENCE")
        if not configured:raise RuntimeError("actual recorded evidence root is required")
        base=Path(configured).resolve()
        return base,load(base/("controls/"+name+"-row.json")),load(base/("controls/"+name+"-case.json"))

    def verify(self,base,row,case,scenario):
        assessment={"scenarios":{scenario:row},"risks":[],"delivery":{}}
        cases=case if isinstance(case,list) else [case]
        ledger={"cases":[c for c in cases if c.get("kind")!="recorded-live-acceptance"],
                "recorded_cases":[c for c in cases if c.get("kind")=="recorded-live-acceptance"]}
        verify_assessment_references(base,assessment,source_root=ROOT,case_review=ledger)

    def test_C420_T02_real_AD_observations_and_changed_source_refusal(self):
        base,row,case=self.inputs("ad")
        self.verify(base,row,case,"ldap_login")
        wrong=copy.deepcopy(row);name=next(iter(wrong["source_files"]))
        wrong["source_files"][name]="0"*64
        with self.assertRaises(ReleaseContractError):self.verify(base,wrong,case,"ldap_login")
        missing=copy.deepcopy(row)
        missing["evidence"]=[r for r in missing["evidence"] if r!=missing["observation_proof"]]
        with self.assertRaises(ReleaseContractError):self.verify(base,missing,case,"ldap_login")

    def test_C420_T02_real_native_hashed_identities_and_missing_original_refusal(self):
        base,row,case=self.inputs("native")
        self.verify(base,row,case,"role_union")
        missing=copy.deepcopy(row);missing["evidence"]=missing["evidence"][:1]
        with self.assertRaises(ReleaseContractError):self.verify(base,missing,case,"role_union")


    def test_C420_T02_mixed_actual_AD_and_native_LDAP_both_required(self):
        base,row,cases=self.inputs("mixed")
        self.verify(base,row,cases,"ldap_login")
        missing=copy.deepcopy(row)
        missing["evidence"]=[r for r in missing["evidence"] if "/native/qualification-" not in r["path"]]
        with self.assertRaises(ReleaseContractError):self.verify(base,missing,cases,"ldap_login")


if __name__=="__main__":unittest.main()
