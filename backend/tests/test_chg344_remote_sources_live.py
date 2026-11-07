"""RF-T01..06: actual sockets, CA validation, FTP daemons and product clients."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import unittest
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import DataConnection
from app.domain.connection_evidence import data_connection_fingerprint
from app.integrations.ftps_tls import ftps_ssl_context, ftps_trust_fingerprint
from app.integrations.remote_sources import FTPRemoteSourceClient, FTPSRemoteSourceClient


def certificate(root, stem, *, issuer=None, wrong_host=False, expired=False):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, stem)])
    now = datetime.now(UTC)
    builder = (x509.CertificateBuilder().subject_name(name).issuer_name(issuer[0].subject if issuer else name)
               .public_key(key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(now - timedelta(hours=2))
               .not_valid_after(now - timedelta(hours=1) if expired else now + timedelta(hours=5))
               .add_extension(x509.BasicConstraints(ca=issuer is None, path_length=None), critical=True)
               .add_extension(x509.SubjectAlternativeName([x509.DNSName("wrong.example.invalid")] if wrong_host else
                              [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False))
    cert = builder.sign(issuer[1] if issuer else key, hashes.SHA256())
    paths = (root / (stem + ".crt"), root / (stem + ".key"))
    paths[0].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    paths[1].write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    paths[1].chmod(0o600)
    return cert, key, paths


class RemoteSourcesLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
            from current_live_support import load_current_context
            load_current_context()
            private_root = Path(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"]).parent
            assert Path(os.environ["CHG344_FTP_PYTHON"]).is_relative_to(private_root)
            temporary_parent = private_root
        else:
            scope = json.loads(Path(os.environ["CHG344_TEST_SCOPE"]).read_text())
            UUID(scope["run_id"])
            assert scope["change_id"] == "CHG-344" and datetime.now(UTC).timestamp() < scope["deadline"]
            for name, expected in scope["sources"].items():
                assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
            temporary_parent = Path("/run/e2e")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ftp-live-", dir=temporary_parent)
        cls.root = Path(cls.temporary.name)
        cls.root.chmod(0o700)
        cls.body = b"# Acceptance\nComplete sentence and table source.\n"
        (cls.root / "source.md").write_bytes(cls.body)
        authority = certificate(cls.root, "authority")
        cls.ca = str(authority[2][0])
        certs = {}
        for kind in ("FTPS", "UNTRUSTED", "HOSTNAME", "EXPIRED"):
            value = certificate(cls.root, kind.lower(), issuer=None if kind == "UNTRUSTED" else authority,
                                wrong_host=kind == "HOSTNAME", expired=kind == "EXPIRED")
            certs[kind.lower()] = [str(p) for p in value[2]]
        cls.ports = {}
        for kind in ("FTP", "FTPS", "UNTRUSTED", "HOSTNAME", "EXPIRED", "UNSUPPORTED"):
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                cls.ports[kind] = listener.getsockname()[1]
        cls.password = secrets.token_hex(24)
        cls.stats = cls.root / "stats.json"
        cls.process = subprocess.Popen([os.environ["CHG344_FTP_PYTHON"], str(root / "backend/scripts/ftp_acceptance_server.py")],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        cls.process.stdin.write(json.dumps(dict(ports=cls.ports, password=cls.password, home=str(cls.root),
                                                stats=str(cls.stats), certs=certs)) + "\n")
        cls.process.stdin.close()
        if cls.process.stdout.readline().strip() != "FTP_SERVICES_READY":
            cls.process.terminate()
            raise RuntimeError("real_ftp_service_start_failed")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.process.stdout.close()
        cls.temporary.cleanup()

    def arguments(self, kind):
        result = dict(host="localhost", port=self.ports[kind], username="reader", credential=self.password,
                      remote_path="", file_name="source.md", timeout_seconds=2)
        if kind not in {"FTP", "UNSUPPORTED"}:
            result["ca_cert_path"] = self.ca
        return result

    def error(self, client, operation, args, expected, status=503):
        with self.assertRaises(AppError) as caught:
            getattr(client, operation)(**args)
        self.assertEqual(caught.exception.code, expected)
        self.assertEqual(caught.exception.status_code, status)
        self.assertNotIn(self.password, caught.exception.message)
        self.assertNotIn(str(self.root), caught.exception.message)

    def test_binary_probe_and_bounded_download(self):
        for kind in ("FTP", "FTPS"):
            with self.subTest(kind=kind):
                client = FTPRemoteSourceClient() if kind == "FTP" else FTPSRemoteSourceClient()
                before = json.loads(self.stats.read_text()) if self.stats.exists() else {}
                self.assertEqual(client.probe(**self.arguments(kind)), len(self.body))
                after = json.loads(self.stats.read_text())[kind]
                self.assertEqual(after.get("RETR", 0), before.get(kind, {}).get("RETR", 0))
                self.assertGreater(after.get("TYPE", 0), before.get(kind, {}).get("TYPE", 0))
                self.assertEqual(client.get_object(**self.arguments(kind), max_bytes=len(self.body)).body, self.body)
                self.error(client, "get_object", {**self.arguments(kind), "max_bytes": len(self.body) - 1},
                           "sync_file_too_large", 413)

    def test_invalid_certificates_fail_before_credentials(self):
        for kind in ("UNTRUSTED", "HOSTNAME", "EXPIRED"):
            for operation in ("probe", "get_object"):
                with self.subTest(kind=kind, operation=operation):
                    self.error(FTPSRemoteSourceClient(), operation, self.arguments(kind), "ftps_certificate_invalid")
            self.assertEqual(json.loads(self.stats.read_text()).get(kind, {}).get("USER", 0), 0)

    def test_missing_and_denied_are_unavailable(self):
        for kind in ("FTP", "FTPS"):
            client = FTPRemoteSourceClient() if kind == "FTP" else FTPSRemoteSourceClient()
            for operation in ("probe", "get_object"):
                self.error(client, operation, {**self.arguments(kind), "file_name": "missing.md"}, "remote_file_unavailable")
                self.error(client, operation, {**self.arguments(kind), "username": "denied"}, "remote_file_unavailable")
                self.error(client, operation, {**self.arguments(kind), "credential": "incorrect"}, "authentication_failed")
                self.error(client, operation, {**self.arguments(kind), "remote_path": "missing"}, "remote_file_unavailable")

    def test_unsupported_size_is_not_missing_or_success(self):
        self.error(FTPRemoteSourceClient(), "probe", self.arguments("UNSUPPORTED"), "remote_operation_unsupported")

    def test_stalled_transport_times_out(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            stop = threading.Event()
            def stalled():
                connection, _ = listener.accept()
                with connection:
                    stop.wait(3)
            thread = threading.Thread(target=stalled)
            thread.start()
            try:
                self.error(FTPRemoteSourceClient(), "probe", {**self.arguments("FTP"), "port": listener.getsockname()[1],
                                                            "timeout_seconds": 1}, "connection_timeout")
            finally:
                stop.set()
                thread.join(timeout=5)

    def test_ca_configuration_and_evidence_changes(self):
        import ssl
        context = ftps_ssl_context(self.ca)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(len(context.get_ca_certs()), len(ssl.create_default_context().get_ca_certs()))
        config = Settings(_env_file=None, FTPS_CA_CERT_PATH=self.ca)
        self.assertEqual(config.ftps_ca_cert_path, self.ca)
        mutable_ca = str(self.root / "mutable-ca.pem")
        Path(mutable_ca).write_bytes(Path(self.ca).read_bytes())
        first = ftps_trust_fingerprint(mutable_ca)
        connection = DataConnection(service_type="FTPS", connection_metadata={}, source_identity={})
        fingerprint = data_connection_fingerprint(connection, ftps_ca_cert_path=mutable_ca)
        other = certificate(self.root, "second-authority")
        Path(mutable_ca).write_bytes(other[2][0].read_bytes())
        self.assertNotEqual(first, ftps_trust_fingerprint(mutable_ca))
        self.assertNotEqual(fingerprint, data_connection_fingerprint(connection, ftps_ca_cert_path=mutable_ca))
        self.error(FTPSRemoteSourceClient(), "probe", {**self.arguments("FTPS"), "ca_cert_path": mutable_ca}, "ftps_certificate_invalid")
        invalid = self.root / "invalid-ca.pem"
        invalid.write_text("invalid public CA")
        for path in (str(invalid), str(self.root / "missing-ca.pem")):
            for operation in ("probe", "get_object"):
                self.error(FTPSRemoteSourceClient(), operation, {**self.arguments("FTPS"), "ca_cert_path": path}, "ftps_ca_unavailable")


if __name__ == "__main__":
    unittest.main()
