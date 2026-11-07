"""Native real cipher and disposable mounted Secret; no provider requests."""
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from uuid import uuid4

from pydantic import SecretStr
from app.core.config import Settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import AIModel
from app.domain.ai_provider import _resolve_api_key
from app.domain.embeddings import _resolve_model_api_key as embedding_key
from app.domain.extraction_pipeline import _resolve_model_api_key as ocr_key
from app.domain.ocr_timeout_policy import error_metadata
from app.domain.connection_probes import _resolve_model_credential as probe_key


class ModelCredentialPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='nomosmart-chg330-credential-')
        self.addCleanup(self.directory.cleanup)
        self.reference = 'compose-secret://owned-control'
        self.settings = Settings(_env_file=None, app_encryption_key=SecretStr(os.urandom(32).hex()), compose_secret_mount_root=self.directory.name, runtime_secret_allowed_refs=self.reference)
        self.model = AIModel(id=uuid4(), name='owned-native-model', is_active=False, api_key_secret_ref=None, api_key_encrypted=None)
        self.value = secrets.token_urlsafe(32)
        self.cipher = EnvelopeCipher(self.settings.encryption_key_bytes)

    def callers(self):
        return [('chat', lambda settings: _resolve_api_key(self.model, settings)), ('embedding', lambda settings: embedding_key(self.model, settings)), ('ocr', lambda settings: ocr_key(self.model, settings)), ('probe', lambda settings: probe_key(settings, self.model))]

    def assert_errors(self, settings, code, status):
        for name, call in self.callers():
            with self.subTest(caller=name):
                with self.assertRaises(AppError) as result:
                    call(settings)
                self.assertEqual((result.exception.code, result.exception.status_code), (code, status))
                self.assertNotIn(self.value, result.exception.message)
                self.assertNotIn(self.directory.name, result.exception.message)
                metadata = error_metadata(result.exception)
                self.assertNotIn(self.value, str(metadata))
                self.assertIsNot(metadata.get("ocr_diagnostics", {}).get("attempted"), True)

    def test_id_and_legacy_name_context_resolve_in_every_caller(self):
        for context in (f'ai-model:{self.model.id}', f'ai-model:{self.model.name}'):
            self.model.api_key_encrypted = self.cipher.encrypt(self.value, context=context)
            for name, call in self.callers():
                with self.subTest(context=context, caller=name):
                    self.assertTrue(call(self.settings) == self.value)

    def test_corrupt_model_envelope_is_one_safe_error(self):
        self.model.api_key_encrypted = 'invalid-owned-envelope'
        self.assert_errors(self.settings, 'model_credential_invalid', 503)
        with self.assertRaises(AppError) as result:
            self.cipher.decrypt(self.model.api_key_encrypted, context='native-generic')
        self.assertEqual((result.exception.code, result.exception.status_code), ('invalid_encrypted_value', 422))

    def test_production_rejects_legacy_before_decrypting(self):
        self.model.api_key_encrypted = self.cipher.encrypt(self.value, context=f'ai-model:{self.model.id}')
        self.assert_errors(self.settings.model_copy(update={'app_env':'production'}), 'legacy_model_credential_forbidden', 503)

    def test_real_secret_has_precedence_and_owner_only_permissions(self):
        target = Path(self.directory.name) / 'owned-control'
        target.write_text(self.value); target.chmod(0o600)
        self.model.api_key_secret_ref = self.reference
        self.model.api_key_encrypted = 'invalid-owned-envelope'
        production = self.settings.model_copy(update={'app_env':'production'})
        for name, call in self.callers():
            with self.subTest(caller=name):
                self.assertTrue(call(production) == self.value)
        self.assertEqual(target.stat().st_mode & 0o077, 0)

    def test_missing_and_unapproved_mounts_keep_original_safe_codes(self):
        self.model.api_key_secret_ref = self.reference
        production = self.settings.model_copy(update={'app_env':'production'})
        self.assert_errors(production, 'runtime_secret_unavailable', 503)
        self.model.api_key_secret_ref = 'compose-secret://not-authorized'
        self.assert_errors(production, 'runtime_secret_reference_denied', 403)

    def test_absent_credential_keeps_business_checks_at_callers(self):
        for name, call in self.callers():
            with self.subTest(caller=name):
                self.assertIsNone(call(self.settings))


if __name__ == '__main__':
    unittest.main()
