"""Verify a genuine trusted-key provenance signature; refuse a changed real copy."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy/release"))
from nomosmart_release.contract import ReleaseContractError
from nomosmart_release.material_attestation import verify_material_attestation


class MaterialAttestationControls(unittest.TestCase):
    def test_actual_signature_and_one_altered_public_copy_refused(self):
        config = json.loads(Path(os.environ["NOMOSMART_MATERIAL_VERIFY_CONFIG"]).read_text())
        for name in ("material_root", "attestation_dir", "source_root"):
            config[name] = Path(config[name])
        actual = verify_material_attestation(**config)
        self.assertEqual(actual["status"], "verified")
        self.assertEqual(actual["purpose"], "local-material-source-attestation")
        self.assertFalse(actual["release_qualified"])
        with tempfile.TemporaryDirectory(prefix="material-tamper-", dir=config["attestation_dir"].parent) as temporary:
            changed = Path(temporary) / "changed"
            shutil.copytree(config["attestation_dir"], changed)
            path = changed / "RELEASE-ATTESTATION.json"
            value = json.loads(path.read_text())
            value["release_qualified"] = True
            path.write_text(json.dumps(value) + "\n")
            wrong = dict(config, attestation_dir=changed)
            with self.assertRaisesRegex(ReleaseContractError, "detached signature is invalid"):
                verify_material_attestation(**wrong)


if __name__ == "__main__":
    unittest.main()
