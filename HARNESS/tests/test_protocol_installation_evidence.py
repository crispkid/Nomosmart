"""Actual closed installation and two deliberately wrong metadata inputs; no install."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy/release"))
from nomosmart_release.contract import ReleaseContractError
from nomosmart_release.installation_evidence import compare_installed_payload


class InstallationEvidenceControls(unittest.TestCase):
    def test_actual_installation_and_two_mismatch_refusals(self):
        config = json.loads(Path(os.environ["NOMOSMART_INSTALLATION_SOURCE_CONFIG"]).read_text())
        for name in ("installed_package", "source_root", "capture_root"):
            config[name] = Path(config[name])
        actual = compare_installed_payload(**config)
        self.assertEqual(actual["status"], "verified")
        self.assertFalse(actual["live_namespace_revalidated"])
        self.assertTrue(actual["original_test_candidate_kept_unverified"])
        wrong_image = copy.deepcopy(config)
        wrong_image["application_images"]["backend"] = config["application_images"]["frontend"]
        with self.assertRaisesRegex(ReleaseContractError, "image differs"):
            compare_installed_payload(**wrong_image)
        wrong_uid = copy.deepcopy(config)
        wrong_uid["expected_namespace_uid"] = "00000000-0000-4000-8000-000000000000"
        with self.assertRaisesRegex(ReleaseContractError, "namespace ownership"):
            compare_installed_payload(**wrong_uid)


if __name__ == "__main__":
    unittest.main()
