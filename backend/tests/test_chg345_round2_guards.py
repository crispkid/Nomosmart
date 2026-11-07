"""Native continuation admission and actual saved graph input; no services."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from edited_content_acceptance_round2_authority import policy, capacity, initialize, require_binding
from ftp_generation_acceptance_gateway import Relay, AdmissionError
from scripts.edited_content_acceptance_graph_check import verify_binding
from scripts.edited_content_acceptance_saved_graph import saved_projection

ROOT = Path(__file__).resolve().parents[2]


class Round2Guards(unittest.TestCase):
    def setUp(self):
        self.value = policy(ROOT)
        self.temporary = tempfile.TemporaryDirectory(prefix="nomosmart-round2-native-")
        self.path = Path(self.temporary.name)
        initialize(ROOT, self.path)
        self.packet = {"change_id": "CHG-345", "continuation_round": 2,
            "plan_sha256": self.value["authority"]["approved_plan_sha256"], "run_id": str(uuid4()),
            "deadline": time.time() + 60, "previous_ledger_sha256": self.value["previous_ledger_sha256"],
            "models": [{"kind": k, "id": k, "model_name": k, "upstream_base": "https://example.invalid/v1", "api_key": ""}
                for k in ("OCR", "Chat", "Embedding")]}
        self.relay = None

    def tearDown(self):
        if self.relay:
            self.relay.journal_lock.close()
        self.temporary.cleanup()

    def test_actual_50_requests_nine_key_reads_and_original_stops_remain(self):
        self.assertEqual(len(self.value["requests"]), 50)
        self.assertEqual(self.value["key_reads"], 9)
        self.assertTrue(json.loads((self.value["round1_history"] / "model-journal.json").read_text())["stopped"])
        self.assertTrue(json.loads((self.value["history"] / "model-journal.json").read_text())["stopped"])
        capacity(ROOT, json.loads((self.path / "ledger.json").read_text()))

    def test_consumed_scope_cannot_allocate_again(self):
        invalid = json.loads((self.path / "ledger.json").read_text())
        invalid["runs"] = [{"state": "CLEANED"}]
        with self.assertRaisesRegex(AssertionError, "round2_single_fresh_allowance_exhausted"):
            capacity(ROOT, invalid)

    def test_native_relay_has_84_global_34_run_and_12_key_limit(self):
        self.relay = Relay(self.packet, evidence_root=self.path)
        self.assertEqual(self.relay.total_limits, {"OCR": 8, "Chat": 56, "Embedding": 20})
        self.assertEqual(self.relay.request_counts("Chat"), (32, 0, 0))
        self.assertEqual(self.value["authority"]["proposed_models_this_run"]["total"], 34)
        self.assertEqual(self.value["authority"]["proposed_key_reads_cumulative"], 12)
        self.assertEqual((self.path / "model-journal.json").stat().st_mode & 0o777, 0o600)

    def test_wrong_round_and_wrong_plan_are_denied(self):
        for field, wrong, code in (("continuation_round", 1, "round2_scope_binding_required"),
                                  ("plan_sha256", "0" * 64, "round2_plan_binding_required")):
            invalid = {**self.packet, field: wrong}
            with self.assertRaisesRegex(AssertionError, code):
                require_binding(invalid, self.value["authority"])

    def test_frozen_relay_cannot_rearm(self):
        self.relay = Relay(self.packet, evidence_root=self.path)
        self.relay.freeze()
        with self.assertRaisesRegex(AdmissionError, "purpose_sequence_denied"):
            self.relay.arm("generation1")
        self.assertEqual(json.loads((self.path / "model-journal.json").read_text())["requests"], self.value["requests"])

    def test_native_over_limit_input_is_denied_before_credentials_or_send(self):
        self.relay = Relay(self.packet, evidence_root=self.path)
        self.relay.arm("generation1")
        invalid_requests = [dict(copy.deepcopy(next(r for r in self.value["requests"] if r["kind"] == "Embedding")),
            run_id=self.packet["run_id"], sequence=51 + n, purpose="generation1") for n in range(8)]
        self.relay.data["requests"].extend(invalid_requests)
        with self.assertRaisesRegex(AdmissionError, "shared_request_allowance_exhausted"):
            self.relay.admit("Embedding", {"model": "Embedding", "input": ["Invalid admission input only"]})
        self.assertEqual(json.loads((self.path / "model-journal.json").read_text())["requests"], self.value["requests"])

    def test_actual_saved_graph_uses_same_live_comparison_branch(self):
        saved = self.value["round1_history"] / "b1342c7f-9de4-4ae3-9775-7075794774f4/generation-4.json"
        projection, preview, comparison = saved_projection(json.loads(saved.read_text()))
        verify_binding(projection, comparison=comparison)
        verify_binding(replace(projection, revision=preview["revision"]), preview=preview)
        with self.assertRaisesRegex(AssertionError, "candidate_graph_preview_source_mismatch"):
            verify_binding(projection, preview=preview)
        with self.assertRaisesRegex(AssertionError, "published_graph_projection_or_receipt_mismatch"):
            verify_binding(replace(projection, revision=preview["revision"]), comparison=comparison)


if __name__ == "__main__":
    unittest.main()
