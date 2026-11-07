"""CHG-412: true owned PostgreSQL, transactional controls, no provider output stand-ins."""
import json
import unittest
from uuid import UUID, uuid4
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from scripts.chg412_runtime import NativeHarness
from app.core.errors import AppError
from app.db.models import (FileProcessingPolicy, FileProcessingPolicyRevision, OCRDocumentReceipt,
                          Project, DocumentVersion, AIModelUsageEvent, ProjectArchiveRun)
from app.domain.file_processing_settings import load_policy, settings_from_snapshot, snapshot_setting, ACTIVE_KEYS
from app.domain.project_access import project_model_configuration, project_model_state_expressions
from app.domain.ocr_capabilities import require_native_capabilities
from app.domain.project_archival import begin_project_archive, _assert_archive_cleanup_safe, _purge_unfinished_database_rows, retry_project_archive_cleanup

class NativePdfSimplification(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.h = NativeHarness()
    @classmethod
    def tearDownClass(cls): cls.h.engine.dispose()
    def record(self, name, result):
        self.h.scope.record('native-controls/'+name+'.json', {'status':'PASS_COMPONENT_REAL_POSTGRES',
            'model_calls':0,'external_storage_IO':0,'transaction_rollback':True,**result})

    def test_policy_v2_and_immutable_v1_history(self):
        with self.h.sessions() as s:
            current = load_policy(s); self.assertEqual(current.schema_version, 2)
            self.assertEqual(set(current.settings.model_fields), ACTIVE_KEYS)
            before=json.loads((self.h.scope.root/'recovery/before055.json').read_text())
            for original in before['policy_history']:
                row=s.get(FileProcessingPolicyRevision,original['revision'])
                self.assertEqual(row.snapshot,original['snapshot']);self.assertEqual(row.content_hash,original['content_hash'])
                self.assertEqual(settings_from_snapshot(row.snapshot).content_hash,row.content_hash)
                self.assertEqual(snapshot_setting(row.snapshot,'document_processing_timeout_seconds'),row.snapshot['pdf_parser_timeout_seconds'])
            values=current.execution_values();self.assertEqual(settings_from_snapshot(values).content_hash,current.settings.content_hash)
            for invalid in ({**values,'_schema_version':3},{k:v for k,v in values.items()if k!='document_processing_timeout_seconds'},
                            {**values,'document_processing_max_concurrent':True}):
                with self.assertRaises(AppError):settings_from_snapshot(invalid)
            self.record('policy-v2-v1',{'active_keys':sorted(ACTIVE_KEYS),'historical_revisions':len(before['policy_history'])})

    def test_policy_metadata_tamper_is_refused_and_rolled_back(self):
        from app.db.models import SystemParameter
        with self.h.sessions() as s:
            row=s.scalar(select(SystemParameter).where(SystemParameter.key=='document_processing_timeout_seconds'))
            original=row.unit;row.unit='incorrect-test-unit';s.flush()
            with self.assertRaises(AppError) as e:load_policy(s)
            self.assertEqual(e.exception.code,'file_processing_parameter_metadata_invalid');s.rollback()
            self.assertEqual(s.scalar(select(SystemParameter).where(SystemParameter.key=='document_processing_timeout_seconds')).unit,original)
            self.record('policy-metadata-refusal',{'actual_error':e.exception.code})

    def test_model_project_SQL_eligibility_matches_real_projection(self):
        from app.db.models import AIModel
        with self.h.sessions() as s:
            ready,pdf=project_model_state_expressions(s)
            rows=s.execute(select(Project,ready,pdf).order_by(Project.id)).all();self.assertTrue(rows)
            for project,sqlready,sqlpdf in rows:
                self.assertEqual(project_model_configuration(s,project),('ready' if sqlready else 'incomplete',sqlpdf))
            native=s.get(AIModel,UUID('6585498e-63e5-4698-ac59-c3fea9e69d7e'));require_native_capabilities(native)
            retired=s.scalar(select(AIModel).where(AIModel.model_type=='OCR',AIModel.provider=='Tesseract'))
            self.assertIsNotNone(retired,'Genuine retained historical model prerequisite missing')
            with self.assertRaises(AppError) as e:require_native_capabilities(retired)
            self.assertEqual(e.exception.code,'ocr_native_model_required')
            self.record('model-project-eligibility',{'real_projects_compared':len(rows),'retired_model_rejected':True})

    def test_archive_receipt_original_identity_is_DB_immutable(self):
        owned=self.h.scope.proposal['owned_live_document'];vid=UUID(owned['version_id'])
        with self.h.sessions() as s:
            receipt=s.scalar(select(OCRDocumentReceipt).where(OCRDocumentReceipt.original_document_version_id==vid))
            self.assertIsNotNone(receipt);rid=receipt.id;original=receipt.original_step_id
            with self.assertRaises(IntegrityError):
                with s.begin_nested():s.execute(update(OCRDocumentReceipt).where(OCRDocumentReceipt.id==rid).values(original_step_id=uuid4()))
            self.assertEqual(s.get(OCRDocumentReceipt,rid,populate_existing=True).original_step_id,original)
            self.record('receipt-immutable-original',{'receipt_id':str(rid),'original_step_unchanged':True})

    def test_archive_unknown_receipt_refused_before_external_IO(self):
        with self.h.sessions() as s:
            receipt=s.scalar(select(OCRDocumentReceipt).where(OCRDocumentReceipt.status.in_(['intent','unknown'])))
            self.assertIsNotNone(receipt,'Genuine unresolved receipt prerequisite missing')
            project=s.get(Project,receipt.project_id);version=s.get(DocumentVersion,receipt.original_document_version_id)
            self.assertIsNotNone(version);self.assertTrue(project.name.startswith('nms411-00621cbd'))
            actor=project.created_by
            begin_project_archive(s,project_id=project.id,actor_user_id=actor,lock_version=project.lock_version,
                                  confirmation_name=project.name,request_id='CHG412-unknown-transaction')
            s.flush();run=s.scalar(select(ProjectArchiveRun).where(ProjectArchiveRun.project_id==project.id).order_by(ProjectArchiveRun.queued_at.desc()))
            if run.status=='failed':run=retry_project_archive_cleanup(s,project=project,actor_user_id=actor,request_id='CHG412-unknown-retry-transaction');s.flush()
            with self.assertRaises(AppError) as e:_assert_archive_cleanup_safe(s,project.id,[version],cleanup_run_id=run.id)
            self.assertEqual(e.exception.code,'ocr_document_provider_result_unknown');s.rollback()
            self.assertIsNotNone(s.get(DocumentVersion,version.id))
            self.record('archive-unknown-refused',{'actual_error':e.exception.code,'receipt_id':str(receipt.id),'content_preserved':True})

    def test_report_native_document_unknown_pages_uses_real_accounting(self):
        from app.api.routes.reports import _model_usage_rows
        pid=UUID(self.h.scope.proposal['owned_live_document']['project_id'])
        with self.h.sessions() as s:
            rows=_model_usage_rows(s,{pid},None,None,100,model_type='OCR')
            native=[r for r in rows if r['native_pdf_documents']>0];self.assertTrue(native,'Actual native OCR usage missing')
            for row in native:
                self.assertEqual(row['native_pdf_documents'],1);self.assertEqual(row['page_count_status'],'unknown')
                self.assertEqual(row['image_count_status'],'not_applicable');self.assertEqual(row['token_count_status'],'known')
                self.assertGreater(row['input_tokens'],0);self.assertGreater(row['output_tokens'],0)
            self.record('report-native-unknown',{'actual_native_rows':len(native),'pages':'unknown','images':'not_applicable','tokens':'known','historical_mixed_positive':'MISSING_ORIGINAL'})
