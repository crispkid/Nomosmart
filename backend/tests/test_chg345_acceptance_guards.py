"""Real immutable local evidence and negative tool admission, no provider output."""
import copy
import json
import os
from pathlib import Path
import unittest

from scripts.edited_content_acceptance_authority import policy, capacity
from scripts.ftp_generation_acceptance_history import require_history_prefix

ROOT = Path(__file__).resolve().parents[2]


class AcceptanceGuards(unittest.TestCase):
    def test_actual_23_request_history_and_old_stop_remain_intact(self):
        value = policy(ROOT)
        self.assertEqual(len(value["requests"]), 23)
        self.assertEqual(value["key_reads"], 6)
        self.assertTrue(json.loads((value["history"] / "model-journal.json").read_text())["stopped"])

    def test_changed_actual_billing_prefix_is_rejected(self):
        value = policy(ROOT)
        invalid = copy.deepcopy(value["requests"])
        invalid[0]["usage"]["input_tokens"] += 1
        with self.assertRaisesRegex(AssertionError, "historical_request_prefix_changed"):
            require_history_prefix({"requests": invalid}, value["requests"])

    def test_consumed_new_scope_does_not_grant_another_environment(self):
        value = policy(ROOT)
        invalid = {"fresh_limit": 1, "historical_344_ledger_sha256": value["authority"]["historical_344_ledger_sha256"],
            "model_requests": value["requests"], "key_reads": 6, "runs": [{"state": "CLEANED"}], "built_images": []}
        with self.assertRaisesRegex(AssertionError, "chg345_single_fresh_allowance_exhausted"):
            capacity(ROOT, invalid)

    def test_true_guard_limits_are_57_and_34_not_reset_to_zero(self):
        value = policy(ROOT)
        self.assertEqual(value["authority"]["proposed_shared_limits"]["total"], 57)
        self.assertEqual(value["authority"]["proposed_models_this_run"]["total"], 34)
        self.assertEqual(sum(r["kind"] == "OCR" for r in value["requests"]), 4)

    def test_actual_saved_published_receipt_has_its_own_lock_binding(self):
        from scripts.edited_content_acceptance_saved_graph import diagnose
        snapshot = json.loads((Path(os.environ.get("CHG345_ROUND1_HISTORY_ROOT", ROOT / ".operator/chg345/reports")) / "b1342c7f-9de4-4ae3-9775-7075794774f4/generation-4.json").read_text())
        result = diagnose(snapshot)
        self.assertTrue(result["actual_receipt_matches_current_lock"])
        self.assertTrue(result["same_actual_graph_at_preview_revision_matches_preview"])
        self.assertNotEqual(result["immutable_preview_digest"], result["actual_formal_graph_receipt"])


if __name__ == "__main__":
    unittest.main()
