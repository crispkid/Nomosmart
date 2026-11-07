"""Real mounted-file security checks; production inputs do not claim startup E2E."""
import os
from pathlib import Path
import sys
import unittest

from app.core.config import get_settings
from app.core.errors import AppError
from app.security.secrets import resolve_runtime_secret, validate_runtime_secret_mount


class RuntimeSecretPolicyLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = os.getenv("NOMOSMART_TEST_RUNTIME_SECRET_REF", "")
        if not cls.reference.startswith("compose-secret://"):
            raise RuntimeError("BLOCKED: provide a disposable mounted Secret reference, never a production credential")
        cls.settings = get_settings()
        cls.production = cls.settings.model_copy(update={"app_env": "production", "runtime_secret_allowed_refs": cls.reference})
        cls.target = Path(cls.settings.compose_secret_mount_root) / cls.reference.removeprefix("compose-secret://")
        if not cls.target.is_file():
            raise RuntimeError("BLOCKED: actual disposable runtime Secret is not mounted")

    def test_metadata_validation_does_not_open_secret_value(self):
        observed = []
        tracking = [True]

        def audit(event, args):
            if tracking[0] and event == "open" and str(args[0]) == str(self.target):
                observed.append(event)

        sys.addaudithook(audit)
        try:
            validate_runtime_secret_mount(self.production, self.reference)
        finally:
            tracking[0] = False
        self.assertEqual(observed, [])

    def test_real_mount_is_readable_without_a_plaintext_artifact(self):
        self.assertTrue(resolve_runtime_secret(self.production, self.reference))
        self.assertEqual(self.target.stat().st_mode & 0o077, 0)

    def test_unregistered_compose_platform_reference_is_denied_before_read(self):
        with self.assertRaises(AppError) as caught:
            resolve_runtime_secret(self.production, "compose-secret://app_encryption_key")
        self.assertEqual(caught.exception.code, "runtime_secret_reference_denied")

    def test_kubernetes_wildcard_does_not_authorize_platform_keys(self):
        settings = self.production.model_copy(update={"runtime_secret_allowed_refs": "platform#*"})
        with self.assertRaises(AppError) as caught:
            resolve_runtime_secret(settings, "k8s-secret://platform#app_encryption_key")
        self.assertEqual(caught.exception.code, "runtime_secret_reference_denied")

    def test_missing_allowed_file_fails_closed(self):
        reference = "compose-secret://chg329-no-file"
        settings = self.production.model_copy(update={"runtime_secret_allowed_refs": reference})
        with self.assertRaises(AppError) as caught:
            validate_runtime_secret_mount(settings, reference)
        self.assertEqual(caught.exception.code, "runtime_secret_unavailable")


if __name__ == "__main__":
    unittest.main()
