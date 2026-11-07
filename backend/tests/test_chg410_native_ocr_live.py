"""Actual CHG-410 clone controls; no provider substitute or generated result."""
import unittest
from uuid import UUID
from sqlalchemy import select

from scripts.chg410_native_ocr_acceptance import NativeLiveHarness
from app.core.errors import AppError
from app.db.models import AIModel
from app.domain.ocr_capabilities import normalize_native_capabilities, require_native_capabilities


class NativeOCRLivePrerequisites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A missing configured Lab prerequisite is an error, never a fake PASS.
        cls.live = NativeLiveHarness()

    @classmethod
    def tearDownClass(cls):
        cls.live.engine.dispose()

    def test_additive_receipt_constraints_and_native_budget(self):
        evidence = self.live.schema()
        self.assertGreater(evidence['request_limit'], 0)
        self.assertLessEqual(evidence['request_limit'], evidence['document_limit'])

    def test_retired_model_cannot_dispatch(self):
        with self.live.session() as session:
            model = session.scalar(select(AIModel).where(AIModel.model_type == 'OCR', AIModel.provider == 'Tesseract', AIModel.deleted_at.is_(None)).limit(1))
            self.assertIsNotNone(model, 'Historical actual Tesseract model prerequisite missing')
            with self.assertRaises(AppError) as denied:
                require_native_capabilities(model)
            self.assertEqual(denied.exception.code, 'ocr_native_model_required')
            self.live.record('N410-02-retired-model', {'model_id': str(model.id), 'error_code': denied.exception.code, 'provider_calls': 0})

    def test_real_selected_profile_and_invalid_boolean_limit(self):
        with self.live.session() as session:
            model = session.get(AIModel, self.live.selected_models()['OCR'])
            capabilities = require_native_capabilities(model)
            self.assertTrue(capabilities.profile['supports_pdf'])
            self.assertTrue(capabilities.profile['count_input_tokens'])
            self.assertLess(capabilities.limit('max_output_tokens'), capabilities.limit('context_window'))
            malformed = {**model.config, 'native_pdf': {**model.config['native_pdf'], 'max_input_bytes': True}}
            with self.assertRaises(AppError) as denied:
                normalize_native_capabilities(malformed)
            self.assertEqual(denied.exception.code, 'ocr_native_capability_invalid')
            self.live.record('N410-02-capability', {'model_id': str(model.id), 'config_version': model.config_version, 'invalid_boolean_limit_error': denied.exception.code, 'provider_calls': 0})
