"""CHG-419 T05/T06: format/refusal boundaries and one actual offline settlement."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/"deploy/release"),str(ROOT/"deploy/installer"),str(ROOT/"HARNESS/scripts")]
from nomosmart_release.contract import ReleaseContractError,verify_release_package
from nomosmart_release.contract_v4 import verify_coverage,verify_full_suite
from nomosmart_release.contract_v5 import validate_manifest,REQUIRED_GATES,PURPOSE
from nomosmart_installer.protocol import ProtocolRelease
from release_quality import verify_review

class RiskReleaseControls(unittest.TestCase):
    def test_C419_T05_legacy_strict_and_explicit_v5_fail_closed(self):
        base=Path(os.environ["NOMOSMART_QUALITY_REVIEW"]).parent
        for side,file in [("frontend","frontend-coverage-summary.json"),("backend","backend-coverage.json")]:
            with self.assertRaisesRegex(ReleaseContractError,"below 80"):verify_coverage(json.loads((base/"measurements"/file).read_text()),side)
        with self.assertRaisesRegex(ReleaseContractError,"full suite"):
            verify_full_suite(json.loads((base/"measurements/backend-original-result.json").read_text()),json.loads((base/"index.json").read_text())["source_sha"])
        self.assertEqual(len(REQUIRED_GATES),19)
        self.assertNotIn("backend_full_suite",REQUIRED_GATES);self.assertIn("critical_scenarios",REQUIRED_GATES)
        # Controlled incomplete metadata only: no successful package or gate bundle is created.
        for invalid in ({"schema_version":5,"package_type":"nomosmart-protocol-test-candidate"},
                        {"schema_version":5,"package_type":"nomosmart-local-risk-reviewed-release","purpose":PURPOSE},
                        json.loads((ROOT/"deploy/release/release-manifest-v5.schema.json").read_text())):
            with self.assertRaises(ReleaseContractError):validate_manifest(invalid)
        with self.assertRaises(ReleaseContractError):verify_release_package(base,purpose=PURPOSE)
        with self.assertRaises(ValueError):ProtocolRelease.load({"package_dir":str(base),"trusted_signer_fingerprint":"","purpose":PURPOSE,"isolated_environment_acknowledged":True},base)
        from nomosmart_release.cli import _parser
        parsed=_parser().parse_args(["verify-package","--package",str(base),"--purpose",PURPOSE]);self.assertEqual(parsed.purpose,PURPOSE)
        schema=json.loads((ROOT/"deploy/release/release-manifest-v5.schema.json").read_text())
        self.assertEqual(set(schema["properties"]["gates"]["required"]),set(REQUIRED_GATES))
        self.assertFalse(schema["properties"]["production_ready"]["const"])

    def test_C419_T06_actual_offline_readiness_reports_real_gaps(self):
        review=Path(os.environ["NOMOSMART_QUALITY_REVIEW"])
        result=verify_review(ROOT,review,readiness=True)
        self.assertEqual(result["status"],"NOT_READY");self.assertEqual(result["measurement"]["measurement_status"],"valid")
        self.assertFalse(result["coverage_target_is_release_gate"]);self.assertFalse(result["production_ready"])
        self.assertFalse(result["publication_authorized"]);self.assertTrue(result["blockers"])

if __name__=="__main__":unittest.main()
