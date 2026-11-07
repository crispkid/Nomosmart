"""Real parser/CLI input-boundary tests; no DB/runtime success is simulated.

Positive DB/auth/runtime proofs belong to R20R17-T02/T03/T04 live observations.
These tests intentionally do not claim that an accepted schema proves a stop.
"""
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import unittest

from pydantic import ValidationError
from app.deployment.file_processing_recovery import RecoveryScope, digest


class RecoveryInputBoundary(unittest.TestCase):
    def cli(self, payload):
        return subprocess.run([sys.executable, '-B', '-m', 'app.deployment.file_processing_recovery', 'preview'],
                              input=payload, capture_output=True, timeout=15)

    def test_malformed_input_is_sanitized_before_database_access(self):
        cases = [(b'[]', 'file_processing_cli_input_invalid'),
                 (b'{}', 'file_processing_cli_input_invalid'),
                 (b'x'*65537, 'file_processing_cli_input_limit'),
                 (b'{', 'file_processing_recovery_failed'),
                 (b'{"access_token":null,"scope":{}}', 'authentication_required')]
        for raw, expected in cases:
            with self.subTest(expected=expected):
                result = self.cli(raw)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b'')
                self.assertEqual(json.loads(result.stderr), {'error':expected})

    def test_arbitrary_stop_claim_is_not_a_scope(self):
        with self.assertRaises(ValidationError):
            RecoveryScope.model_validate({'stopped':True, 'cleanup_confirmed':True})
        raw = json.dumps({'access_token':'r17-sensitive-canary-not-a-jwt', 'scope':{'stopped':True}}).encode()
        result = self.cli(raw)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stderr), {'error':'file_processing_recovery_failed'})
        self.assertNotIn(b'canary', result.stdout+result.stderr)

    def test_malformed_credentials_are_rejected_before_opening_a_database(self):
        # A real OS socket reserves this port without listening. Any accidental
        # DB connection is refused; no database/identity response is replaced.
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            port = reserved.getsockname()[1]
            env = dict(os.environ, DATABASE_URL=f'postgresql+psycopg2://input_guard:unused@127.0.0.1:{port}/input_guard')
            cases = [({'session_cookie': None}, 'authentication_required'),
                     ({'session_cookie': ''}, 'authentication_required'),
                     ({'session_cookie': 'x', 'access_token': 'x'}, 'file_processing_cli_input_invalid')]
            for module, operation, extra in [('file_processing_policy', 'read', {}),
                                             ('file_processing_recovery', 'preview', {'scope': {}})]:
                for credential, expected in cases:
                    with self.subTest(module=module, expected=expected):
                        result = subprocess.run([sys.executable, '-B', '-m', 'app.deployment.' + module, operation],
                            input=json.dumps({**credential, **extra}).encode(), env=env,
                            capture_output=True, timeout=15)
                        self.assertEqual(result.returncode, 1)
                        self.assertEqual(result.stdout, b'')
                        self.assertEqual(json.loads(result.stderr), {'error': expected})

    def test_context_digest_is_order_independent_and_change_sensitive(self):
        self.assertEqual(digest({'one':1,'two':2}), digest({'two':2,'one':1}))
        self.assertNotEqual(digest({'one':1}), digest({'one':2}))

    def test_schema_requires_all_scope_fields_and_forbids_completed(self):
        schema = RecoveryScope.model_json_schema()
        self.assertEqual(set(schema['required']), set(schema['properties']))
        self.assertFalse(schema['additionalProperties'])
        self.assertNotIn('terminal', schema['properties'])
        self.assertEqual(schema['properties']['policy_revision']['minimum'], 1)


if __name__ == '__main__':
    unittest.main()
