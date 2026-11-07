"""Real native shell/validation checks; no DB or business-success substitution."""
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from e2e_environment import container_environment


class PreparationInputs(unittest.TestCase):
    def test_real_shell_preserves_migration_role_and_private_paths(self):
        source=container_environment({"FLYWAY_USER":"nomosmart_migration", "CERT_PATH":"/run/e2e/pg-ca.crt"})
        result=subprocess.run(["/bin/sh","-c",source+"printf '%s\\n' \"$FLYWAY_USER\" \"$CERT_PATH\""],
                              env={"PATH":"/usr/bin:/bin"},capture_output=True,text=True,check=True,timeout=5)
        self.assertEqual(result.stdout.splitlines(),["nomosmart_migration","/run/e2e/pg-ca.crt"])

    def test_shell_syntax_and_expansion_are_rejected_before_execution(self):
        for value in ("bad'value","$(id)","a;b","x\ny","x`id`","a&b","a b"):
            with self.subTest(value=value), self.assertRaisesRegex(AssertionError,"unsafe_generated_environment"):
                container_environment({"FLYWAY_USER":value})

    def test_assignment_keys_cannot_be_commands_or_invalid_shell_names(self):
        for key in ("x;y","1ROLE","A B","A=1", "X\nY"):
            with self.subTest(key=key), self.assertRaisesRegex(AssertionError,"unsafe_generated_environment"):
                container_environment({key:"nomosmart_migration"})


if __name__=="__main__":
    unittest.main()
