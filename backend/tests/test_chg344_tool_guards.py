"""Native tool guards only: real files/flock, no model replies or business outputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts.ftp_generation_acceptance_gateway import AdmissionError, Relay


class ToolGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nomosmart-chg344-guard-")
        previous = Path(self.temporary.name) / "local-guard-ledger.json"
        # This test actually makes zero requests. Its private input ledger is
        # not the historical authority and never substitutes for live proof.
        previous.write_text(json.dumps({"model_requests": [], "key_reads": 0}))
        self.packet = {"run_id": "guard-input-only", "deadline": time.time() + 60,
            "previous_ledger_path": str(previous), "previous_ledger_sha256": hashlib.sha256(previous.read_bytes()).hexdigest(),
            "admission_receipt": str(Path(self.temporary.name) / "missing-admission.json"), "admission_sha256": "0" * 64,
            "models": [{"kind": kind, "id": kind, "model_name": kind, "upstream_base": "https://example.invalid/v1", "api_key": ""}
                       for kind in ("OCR", "Chat", "Embedding")]}
        self.relay = Relay(self.packet, evidence_root=Path(self.temporary.name))

    def tearDown(self):
        # No accepted request is inserted into this or the real shared journal.
        self.assertEqual(json.loads(self.relay.path.read_text())["requests"], [])
        self.relay.journal_lock.close()
        self.temporary.cleanup()

    def rejected(self, kind, body, code):
        with self.assertRaises(AdmissionError) as caught:
            self.relay.admit(kind, body)
        self.assertEqual(str(caught.exception), code)

    def test_unarmed_request_is_denied_without_network_or_usage(self):
        self.rejected("Chat", {}, "model_segment_stopped_or_unarmed")

    def test_missing_upstream_key_is_denied_without_pending_charge(self):
        self.relay.arm("generation1")
        self.rejected("Chat", {"model": "Chat", "max_output_tokens": 2000}, "upstream_credential_not_loaded")

    def test_model_identity_is_checked_before_key_or_send(self):
        self.relay.arm("generation1")
        self.rejected("Chat", {"model": "unselected"}, "model_identity_mismatch")

    def test_input_and_output_limits_are_native_admission_failures(self):
        self.relay.arm("generation1")
        self.rejected("Chat", {"model": "Chat", "max_output_tokens": 2001}, "output_budget_exceeded")
        self.rejected("Chat", {"model": "Chat", "input": "x" * 6000, "max_output_tokens": 1}, "input_budget_exceeded")

    def test_ocr_cannot_replay_after_initial_generation(self):
        self.relay.arm("generation1")
        self.relay.arm("generation2")
        self.rejected("OCR", {"model": "OCR"}, "ocr_replay_denied")

    def test_remote_or_wrong_format_images_are_denied(self):
        self.relay.arm("generation1")
        self.rejected("OCR", {"model": "OCR", "image": "https://example.invalid/page.png"}, "remote_ocr_image_denied")
        self.rejected("OCR", {"model": "OCR", "image": "data:image/jpeg;base64,AA=="}, "image_format_not_allowed")

    def test_phase_skip_and_replay_are_denied(self):
        with self.assertRaises(AdmissionError):
            self.relay.arm("qa1")
        self.relay.arm("generation1")
        with self.assertRaises(AdmissionError):
            self.relay.arm("generation1")

    def test_missing_activation_receipt_is_safe_and_does_not_load_keys(self):
        with self.assertRaisesRegex(AdmissionError, "admission_receipt_unavailable"):
            self.relay.load_credentials({})
        self.assertTrue(all(not model["api_key"] for model in self.relay.models.values()))

    def test_actual_deadline_guard_does_not_modify_historical_authority(self):
        self.packet["deadline"] = time.time() - 1
        with self.assertRaisesRegex(AdmissionError, "owned_model_deadline"):
            self.relay.ledger_guard()

    def test_real_process_flock_and_private_file_permissions(self):
        self.assertEqual(self.relay.path.stat().st_mode & 0o777, 0o600)
        program = "import fcntl,sys; p=open(sys.argv[1],'a+');\ntry: fcntl.flock(p,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError: sys.exit(0)\nsys.exit(1)"
        process = subprocess.run([sys.executable, "-c", program, str(self.relay.journal_lock.name)], timeout=5, capture_output=True)
        self.assertEqual(process.returncode, 0, "another real process must be locked out")

    def test_actual_consumed_fresh_authority_rejects_without_allocating(self):
        from scripts.ftp_generation_acceptance_environment import OUTPUT, ROOT, require_fresh_capacity
        path = Path(os.environ.get("CHG344_HISTORY_LEDGER", OUTPUT / "ledger.json"))
        before = path.read_bytes()
        consumed = json.loads((ROOT / "docs/CHG-344-RUNTIME-ADDENDUM-STATUS.json").read_text())
        limit = consumed["proposed_total_limit"]
        minimum = consumed["original_fresh_used"] + consumed["additional_fresh_used"]
        self.assertEqual(limit, minimum, "the previous real supplemental grant is exhausted")
        with self.assertRaisesRegex(RuntimeError, "approved_fresh_allowance_exhausted"):
            require_fresh_capacity(json.loads(before), limit, minimum)
        self.assertEqual(path.read_bytes(), before)

    def test_actual_supplement_cannot_be_reused_after_history_removal(self):
        from scripts.ftp_generation_acceptance_environment import OUTPUT, fresh_authority, require_fresh_capacity
        limit, authority = fresh_authority()
        ledger = json.loads(Path(os.environ.get("CHG344_HISTORY_LEDGER", OUTPUT / "ledger.json")).read_text())
        ledger["runs"] = []  # Only an in-memory invalid input; original bytes stay.
        with self.assertRaisesRegex(RuntimeError, "fresh_history_missing_or_reset"):
            require_fresh_capacity(ledger, limit, authority["minimum_used"])

    def test_concurrent_private_evidence_writes_are_atomic_and_leave_no_pending_files(self):
        from scripts.ftp_generation_acceptance_environment import private_write
        path = Path(self.temporary.name) / "actual-private-write.json"
        values = [json.dumps({"writer": number, "payload": str(number) * 5000}) for number in range(12)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda value: private_write(path, value), values))
        self.assertIn(path.read_text(), values)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(path.parent.glob(path.name + ".pending-*")), [])

    def test_object_inventory_xml_rejects_actual_dtd_and_oversized_pages(self):
        from scripts.ftp_generation_acceptance_observer import parse_object_listing
        self.assertEqual(parse_object_listing(b"<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>").tag, "ListBucketResult")
        with self.assertRaisesRegex(ValueError, "object_inventory_dtd_denied"):
            parse_object_listing(b'<!DOCTYPE x [<!ENTITY repeated "unsafe">]><x>&repeated;</x>')
        with self.assertRaisesRegex(ValueError, "object_inventory_page_too_large"):
            parse_object_listing(b"x" * (2 * 1024**2 + 1))

    def public_test_ca(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Owned native trust guard")])
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
            .not_valid_after(datetime.now(UTC) + timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256()))
        path = Path(self.temporary.name) / "native-public-ca.pem"
        path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        return path

    def test_actual_httpx_ignores_ssl_cert_file_when_trust_env_is_false(self):
        ca = self.public_test_ca()
        program = "import httpx,ssl,os; expected=ssl.PEM_cert_to_DER_cert(open(os.environ['SSL_CERT_FILE']).read()); a=httpx.Client(verify=True,trust_env=False); b=httpx.Client(verify=True,trust_env=True); assert expected not in a._transport._pool._ssl_context.get_ca_certs(binary_form=True); assert expected in b._transport._pool._ssl_context.get_ca_certs(binary_form=True); a.close(); b.close()"
        from scripts.ftp_generation_acceptance_environment import tool_env
        process = subprocess.run([sys.executable, "-B", "-c", program], env={**tool_env(), "SSL_CERT_FILE": str(ca)}, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, "real default HTTPX context reproduces the missing trust path")

    def test_real_private_certifi_bundle_addition_preserves_public_roots_and_verification(self):
        import certifi
        import shutil
        ca = self.public_test_ca()
        packages = Path(self.temporary.name) / "private-packages"
        shutil.copytree(Path(certifi.__file__).parent, packages / "certifi", ignore=shutil.ignore_patterns("__pycache__"))
        program = "import certifi,ssl,httpx; from pathlib import Path; from scripts.ftp_generation_acceptance_trust import add_public_test_ca; import sys; ca=Path(sys.argv[1]); root=Path(sys.argv[2]); bundle=Path(certifi.where()); assert bundle.is_relative_to(root); result=add_public_test_ca(bundle,ca); assert result['roots_after']>=result['public_roots_before']; c=httpx.Client(verify=True,trust_env=False); ctx=c._transport._pool._ssl_context; assert ctx.verify_mode==ssl.CERT_REQUIRED and ctx.check_hostname; assert ssl.PEM_cert_to_DER_cert(ca.read_text()) in ctx.get_ca_certs(binary_form=True); again=add_public_test_ca(bundle,ca); assert again['bundle_sha256']==result['bundle_sha256'] and again['roots_after']==result['roots_after']; c.close()"
        backend = Path(__file__).resolve().parents[1]
        from scripts.ftp_generation_acceptance_environment import tool_env
        process = subprocess.run([sys.executable, "-B", "-c", program, str(ca), str(packages)],
            env={**tool_env(), "PYTHONPATH": str(packages) + os.pathsep + str(backend)}, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, "real copied certifi store must trust the CA without changing the host or disabling TLS")

    def test_review_cannot_resume_after_key_access_or_ambiguous_journal(self):
        from scripts.ftp_generation_acceptance_environment import zero_model_review_allowed
        path = Path(self.temporary.name) / "review-journal-input.json"
        self.assertTrue(zero_model_review_allowed({"original_model_key_reads": 0, "model_requests": 0}, path))
        self.assertFalse(zero_model_review_allowed({"original_model_key_reads": 3, "model_requests": 0}, path))
        self.assertFalse(zero_model_review_allowed({}, path))
        path.write_text("invalid json input")
        self.assertFalse(zero_model_review_allowed({"original_model_key_reads": 0, "model_requests": 0}, path))

    def test_native_neo4j_environment_names_work_without_shell_value_injection(self):
        from scripts.ftp_generation_acceptance_environment import valid_variables
        self.assertTrue(valid_variables({"NEO4J_server_memory_heap_initial__size": "384m", "NEO4J_dbms_ssl_policy_bolt_enabled": "true"}))
        self.assertTrue(valid_variables({"OPENSEARCH_JAVA_OPTS": "-Xms512m -Xmx512m"}))
        self.assertFalse(valid_variables({"unapproved_lowercase": "value"}))
        self.assertFalse(valid_variables({"INVALID-NAME": "value"}))
        for value in ("line\nbreak", "carriage\rreturn", "nul\0value", "quote'value", None):
            self.assertFalse(valid_variables({"NEO4J_AUTH": value}))

    def test_unique_active_models_need_no_default_flag_but_ambiguity_is_denied(self):
        from scripts.ftp_generation_acceptance_models import choose_model_ids
        rows = [{"id": kind, "model_type": kind, "is_default": False} for kind in ("OCR", "Chat", "Embedding")]
        self.assertEqual(choose_model_ids(rows), ["OCR", "Chat", "Embedding"])
        with self.assertRaisesRegex(RuntimeError, "original_model_selection_required"):
            choose_model_ids(rows + [{"id": "second", "model_type": "Chat", "is_default": False}])
        with self.assertRaisesRegex(RuntimeError, "original_model_selection_required"):
            choose_model_ids(rows[:-1])

    def test_observer_cannot_clear_all_or_missing_scroll_ids(self):
        import httpx
        from scripts.ftp_generation_acceptance_observer import clear_scroll
        with httpx.Client(base_url="https://example.invalid", trust_env=False) as client:
            for scroll in ("_all", "", None):
                with self.assertRaisesRegex(AssertionError, "owned_scroll_id_required"):
                    clear_scroll(client, scroll)

    def actual_history_copy(self):
        import shutil
        from scripts.ftp_generation_acceptance_environment import OUTPUT, ROOT
        from scripts.ftp_generation_acceptance_history import round6_policy
        reports = Path(os.environ.get("CHG344_HISTORY_LEDGER", OUTPUT / "ledger.json")).parent
        policy = round6_policy(ROOT, reports)
        fifth = json.loads((ROOT / "docs/CHG-344-RUNTIME-ROUND5-STATUS.json").read_text())["run_id"]
        copied = Path(self.temporary.name) / "real-history-copy"
        (copied / fifth).mkdir(parents=True)
        shutil.copyfile(reports / fifth / "result.json", copied / fifth / "result.json")
        raw = json.dumps(json.loads((reports / fifth / "result.json").read_text())["actual_model_journal"]).encode()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), policy["authority"]["historical_model_journal_sha256"])
        (copied / "model-journal.json").write_bytes(raw)
        return policy, copied

    def test_actual_history_prefix_rejects_tampered_usage_without_modifying_source(self):
        from scripts.ftp_generation_acceptance_history import require_history_prefix
        policy, copied = self.actual_history_copy()
        journal = json.loads((copied / "model-journal.json").read_text())
        require_history_prefix(journal, policy["requests"], "native-control-only")
        journal["requests"][0]["usage"]["input_tokens"] += 1
        with self.assertRaisesRegex(AssertionError, "historical_request_prefix_changed"):
            require_history_prefix(journal, policy["requests"], "native-control-only")

    def test_actual_prior_calls_count_globally_but_not_against_new_purpose_and_freeze_is_final(self):
        policy, copied = self.actual_history_copy()
        packet = {**self.packet, "round": 6, "run_id": "native-control-only",
            "previous_ledger_sha256": json.loads((copied / "model-journal.json").read_text())["previous_ledger_sha256"]}
        relay = Relay(packet, evidence_root=copied)
        try:
            relay.arm("generation1")
            self.assertEqual(relay.request_counts("OCR"), (2, 0, 0))
            self.assertEqual(relay.request_counts("Chat"), (4, 0, 0))
            self.assertEqual(relay.request_counts("Embedding"), (1, 0, 0))
            relay.freeze()
            with self.assertRaises(AdmissionError):
                relay.arm(None)
            with self.assertRaises(AdmissionError):
                relay.arm("generation2")
            with self.assertRaises(AdmissionError):
                relay.load_credentials({})
            self.assertTrue(json.loads(relay.path.read_text())["stopped"])
            self.assertEqual(json.loads(relay.path.read_text())["requests"], policy["requests"])
            child = subprocess.Popen([sys.executable, "-B", "-c", "import time;time.sleep(60)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                child.terminate()
                child.wait(timeout=5)
                self.assertIsNotNone(child.poll(), "real control process must stop")
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
        finally:
            relay.journal_lock.close()

    def test_zero_model_review_preserves_actual_seven_and_denies_current_key_access(self):
        from scripts.ftp_generation_acceptance_environment import zero_model_review_allowed
        policy, copied = self.actual_history_copy()
        report = {"run_id": "native-control-only", "historical_model_requests": policy["requests"],
            "model_requests": 7, "original_model_key_reads": 3, "run_model_requests": 0, "run_original_model_key_reads": 0}
        self.assertTrue(zero_model_review_allowed(report, copied / "model-journal.json"))
        report["run_original_model_key_reads"] = 3
        self.assertFalse(zero_model_review_allowed(report, copied / "model-journal.json"))

    def test_actual_saved_generation_reveals_obsolete_working_graph_and_tag_bodies(self):
        from scripts.ftp_generation_acceptance_environment import OUTPUT
        from scripts.ftp_generation_acceptance_observer import obsolete_derived_step_payloads
        reports = Path(os.environ.get("CHG344_HISTORY_LEDGER", OUTPUT / "ledger.json")).parent
        snapshot = json.loads((reports / "ca98548e-e31a-4ceb-b184-c8639a7d3e8e/generation-3.json").read_text())
        self.assertEqual(snapshot["protected_versions"], [])
        shadows = obsolete_derived_step_payloads(snapshot["sql"], snapshot["version_id"], snapshot["active_chunk_ids"])
        self.assertTrue(any(row["retired_chunk_nodes"] for row in shadows), "actual old graph output must be detected")
        self.assertTrue(any(row["retired_tag_targets"] for row in shadows), "actual old tag output must be detected")


if __name__ == "__main__":
    unittest.main()
