"""Actual owned PostgreSQL controls. No Provider output or session substitute."""
import unittest
from sqlalchemy import select,func,inspect,text
from scripts.chg411_acceptance import NativeLiveHarness
from app.core.errors import AppError
from app.db.models import AIModel,DocumentVersion,PipelineRun,Project,OCRDocumentReceipt
from app.domain.ocr_capabilities import require_native_capabilities
from app.domain.ocr_document_receipts import DocumentOCRJournal

class CurrentNativeAdmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.live=NativeLiveHarness()
    @classmethod
    def tearDownClass(cls):cls.live.engine.dispose()

    def test_owned_oid_role_and_tls_are_real(self):
        self.live.assert_database()
        with self.live.engine.connect() as c:
            role=c.execute(text('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()
        self.assertEqual(tuple(role),(False,False,False,False))
        self.live.record('owned-role-and-tls',{'owned_database_verified':True,'model_requests':0})

    def test_missing_claim_is_fenced_before_reservation(self):
        with self.live.session() as s:
            row=s.execute(select(PipelineRun,DocumentVersion,Project).join(DocumentVersion,DocumentVersion.id==PipelineRun.document_version_id).join(Project,Project.id==PipelineRun.project_id).limit(1)).one()
            run,version,project=row;model=s.scalar(select(AIModel).where(AIModel.model_type=='OCR').limit(1));self.assertIsNotNone(model)
            before=s.scalar(select(func.count()).select_from(OCRDocumentReceipt))
            journal=DocumentOCRJournal(session=s,settings=self.live.settings,project=project,pipeline=run,execution_claim=None,model=model,version=version,snapshot=(version.chunk_strategy or {}).get('ocr_snapshot') or {},request_sha256='0'*64,credential_fingerprint='0'*64)
            with self.assertRaises(AppError) as denied:journal.inspect_existing()
            self.assertEqual(denied.exception.code,'file_processing_task_fenced')
            self.assertEqual(s.scalar(select(func.count()).select_from(OCRDocumentReceipt)),before)
            self.live.record('missing-claim-fenced',{'code':denied.exception.code,'receipts_unchanged':True,'model_requests':0,'component_level_not_web_auth':True})

    def test_true_retired_model_cannot_be_a_native_provider(self):
        with self.live.session() as s:
            m=s.scalar(select(AIModel).where(AIModel.model_type=='OCR',AIModel.provider=='Tesseract').limit(1));self.assertIsNotNone(m,'Genuine historical model prerequisite absent')
            with self.assertRaises(AppError) as denied:require_native_capabilities(m)
            self.assertEqual(denied.exception.code,'ocr_native_model_required')
            self.live.record('retired-model-refused',{'model_id':str(m.id),'code':denied.exception.code,'model_requests':0})

    def test_current_additive_migration_target_is_real(self):
        from app.deployment.migration_gate import verify_migration_target
        with self.live.engine.connect() as c:
            verify_migration_target(c, "055", -187064222, None)
        self.live.record("v055-readonly-gate", {"target":"055","checksum":-187064222,"original_mutations":0,"model_requests":0})


class CurrentNativeBudget(unittest.TestCase):
    """Current request budgets use true database rows, without a Provider call."""
    @classmethod
    def setUpClass(cls):
        cls.live = NativeLiveHarness()

    @classmethod
    def tearDownClass(cls):
        cls.live.engine.dispose()

    def test_real_request_document_snapshot_and_remaining_budget(self):
        from app.domain.ocr_token_settings import load_native_settings, native_from_snapshot
        with self.live.session() as session:
            values = load_native_settings(session)
            self.assertGreater(values.request, 0)
            self.assertLessEqual(values.request, values.document)
            self.assertEqual(native_from_snapshot(values.snapshot()), values)
            self.assertEqual(values.request_limit(values.document), values.request)
            self.assertEqual(values.request_limit(1), 1)
            with self.assertRaises(AppError) as denied:
                values.request_limit(0)
            self.assertEqual(denied.exception.code, "ocr_document_output_budget_exhausted")
        self.live.record("native-request-budget", {"actual_rows":True,"model_requests":0})

    def test_snapshot_tamper_and_legacy_policy_are_rejected_by_native_reader(self):
        from app.domain.ocr_token_settings import load_native_settings, native_from_snapshot, load_settings, from_snapshot
        with self.live.session() as session:
            current = load_native_settings(session)
            historical = load_settings(session)
            # This validates policy compatibility, not a fabricated historical OCR result.
            self.assertEqual(from_snapshot(historical.snapshot()), historical)
            for damaged in ({**current.snapshot(), "ocr_document_max_tokens":current.document+1},
                            {**current.snapshot(), "ocr_request_max_output_tokens":True},
                            historical.snapshot()):
                with self.subTest(keys=sorted(damaged)):
                    with self.assertRaises(AppError) as denied:
                        native_from_snapshot(damaged)
                    self.assertEqual(denied.exception.code, "ocr_token_settings_invalid")
        self.live.record("native-snapshot-refusal", {"tamper_and_legacy_policy_denied":True,"historical_configuration_reader_retained":True,"historical_page_images_UI":False,"model_requests":0})

    def test_native_request_api_field_is_strict_and_omission_preserves_values(self):
        from pydantic import ValidationError
        from app.api.schemas import SystemParametersUpdatePayload
        base = dict(max_upload_size_mb=100, default_timezone="Asia/Taipei", staging_index_ttl_days=7)
        for invalid in (None, False, 1.5, "10000", 0, -2, 2147483648):
            with self.subTest(value_type=type(invalid).__name__):
                with self.assertRaises(ValidationError):
                    SystemParametersUpdatePayload(**base, ocr_request_max_output_tokens=invalid)
        omitted = SystemParametersUpdatePayload(**base).model_dump(exclude_unset=True)
        self.assertTrue({"ocr_request_max_output_tokens", "ocr_document_max_tokens"}.isdisjoint(omitted))
        self.live.record("native-budget-api-schema", {"strict_native_field":True,"omitted_values_not_reset":True,"model_requests":0,"schema_component_only":True})


class CurrentNativeImmutability(unittest.TestCase):
    def test_changed_native_model_revision_cannot_recount_or_replay(self):
        """Real uploaded source/SQL/S3, with only a non-listening local target.

        An unexpected missed guard cannot send a document or credential upstream.
        This tests the native contract, not the retired split-adapter helper.
        """
        import json
        import socket
        from uuid import UUID
        from app.domain.ocr_native import NativePDFOCRAdapter
        from app.domain.file_processing_dispatch import Claim
        live = NativeLiveHarness(services=True)
        try:
            evidence = json.loads((live.root / "ui-intent-controller/ready.json").read_text())
            with live.session() as session, socket.socket() as refused:
                refused.bind(("127.0.0.1", 0))
                target = "https://127.0.0.1:" + str(refused.getsockname()[1])
                run = session.get(PipelineRun, UUID(evidence["run_id"]))
                version = session.get(DocumentVersion, UUID(evidence["version_id"]))
                project = session.get(Project, UUID(evidence["project_id"]))
                receipt = session.get(OCRDocumentReceipt, UUID(evidence["receipt_id"]))
                self.assertEqual(project.name, live.scope.prefix + "-ui-intent")
                self.assertEqual(receipt.status, "intent")
                self.assertIsNone(receipt.attempted)
                self.assertIsNone(receipt.usage_event_id)
                model = session.get(AIModel, version.ocr_model_id)
                original_version = model.config_version
                original_configuration = dict(model.config)
                original_snapshot = dict(version.chunk_strategy["ocr_snapshot"])
                before_receipts = session.scalar(select(func.count()).select_from(OCRDocumentReceipt))
                binding = receipt.dispatch_binding
                claim = Claim(task_id=UUID(binding["task_id"]), claim_token=UUID(binding["task_claim"]),
                    execution_id=UUID(binding["execution_id"]), generation=UUID(binding["generation"]), run_id=run.id)
                model.config_version = original_version + 1
                model.config = {**original_configuration, "base_url": target}
                session.flush()
                adapter = NativePDFOCRAdapter(settings=live.settings, session=session,
                    project=project, pipeline=run, execution_claim=claim)
                with self.assertRaises(AppError) as denied:
                    adapter.prepare_call(model=model, version=version)
                self.assertEqual(denied.exception.code, "ocr_model_snapshot_changed")
                session.rollback()
                self.assertEqual(session.get(AIModel, model.id).config_version, original_version)
                self.assertEqual(session.get(AIModel, model.id).config, original_configuration)
                self.assertEqual(session.get(DocumentVersion, version.id).chunk_strategy["ocr_snapshot"], original_snapshot)
                self.assertEqual(session.scalar(select(func.count()).select_from(OCRDocumentReceipt)), before_receipts)
                actual = session.get(OCRDocumentReceipt, receipt.id)
                self.assertEqual(actual.status, "intent")
                self.assertIsNone(actual.attempted)
                self.assertIsNone(actual.usage_event_id)
            live.record("native-revision-before-count", {"real_uploaded_version":evidence["version_id"],
                "code":"ocr_model_snapshot_changed", "source_and_snapshot_preserved":True,
                "no_new_receipt_or_ledger":True,"only_transport_target":"actual non-listening local socket",
                "current_native_component":True,"legacy_split_helper_pass_claimed":False,"model_requests":0})
        finally:
            live.engine.dispose()
