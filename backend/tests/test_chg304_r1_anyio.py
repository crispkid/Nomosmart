"""Actual loopback TLS and child processes; no Provider, mocks or altered trust.

Run directly in the approved private venv; keys are temporary and never printed.
"""
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

import anyio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


class TLSHostnameTests(unittest.TestCase):
    def handshake(self, certificate_hostname: str, requested_hostname: str):
        with tempfile.TemporaryDirectory(prefix="chg304-r1-tls-") as directory:
            root = Path(directory)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Isolated CHG304 TLS")])
            now = datetime.now(UTC)
            certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(certificate_hostname)]), critical=False)
                .sign(key, hashes.SHA256()))
            cert = root / "certificate.pem"
            private_key = root / "key.pem"
            cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            private_key.chmod(0o600)
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert, private_key)
            client_context = ssl.create_default_context(cafile=str(cert))
            self.assertTrue(client_context.check_hostname)
            self.assertEqual(client_context.verify_mode, ssl.CERT_REQUIRED)
            with socket.socket() as listener:
                selected_port = os.environ.get("NMS_CURRENT_ANYIO_TLS_PORT")
                if selected_port is not None and selected_port != "18488":
                    raise ValueError("Current native TLS port must be the reserved 18488")
                listener.bind(("127.0.0.1", int(selected_port) if selected_port is not None else 0))
                listener.listen(1)
                listener.settimeout(5)
                port = listener.getsockname()[1]
                server_errors = []

                def serve():
                    try:
                        raw, _ = listener.accept()
                        with raw:
                            raw.settimeout(5)
                            with server_context.wrap_socket(raw, server_side=True) as stream:
                                if stream.recv(1) == b"q":
                                    stream.sendall(b"a")
                                    stream.unwrap().close()  # Complete the real TLS close_notify exchange.
                    except ssl.SSLError:
                        pass  # A real hostname rejection produces a TLS alert at the peer.
                    except Exception as exc:
                        server_errors.append(type(exc).__name__)

                thread = threading.Thread(target=serve, daemon=True)
                thread.start()

                async def connect():
                    with anyio.fail_after(5):
                        stream = await anyio.connect_tcp("127.0.0.1", port, tls=True,
                            ssl_context=client_context, tls_hostname=requested_hostname)
                        async with stream:
                            await stream.send(b"q")
                            return await stream.receive(1)

                try:
                    return anyio.run(connect)
                finally:
                    thread.join(timeout=6)
                    self.assertFalse(thread.is_alive(), "TLS worker did not terminate")
                    self.assertEqual(server_errors, [])

    def test_correct_idna2008_name_is_accepted(self):
        self.assertEqual(self.handshake("xn--fa-hia.example.test", "faß.example.test"), b"a")

    def test_idna2003_lookalike_is_rejected(self):
        with self.assertRaises(Exception) as caught:
            self.handshake("fass.example.test", "faß.example.test")
        causes = []
        current = caught.exception
        while current is not None and current not in causes:
            causes.append(current)
            current = current.__cause__ or current.__context__
        self.assertTrue(any(isinstance(item, ssl.SSLCertVerificationError) for item in causes),
                        "Must reject because certificate verification failed, not timeout/connection error")

    def test_ascii_name_still_works(self):
        self.assertEqual(self.handshake("service.example.test", "service.example.test"), b"a")


class ProcessTests(unittest.TestCase):
    def run_workload(self, function_name):
        program = f"""import anyio, anyio.to_process
from chg304_r1_process_work import {function_name}
async def main():
    with anyio.fail_after(8):
        result = await anyio.to_process.run_sync({function_name}, cancellable=True)
        assert result == 1024 * 1024
anyio.run(main)
"""
        env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
        env.update(PYTHONPATH=os.pathsep.join(filter(None, [str(Path(__file__).parent), os.environ.get("PYTHONPATH")])),
                   PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-c", program], env=env, timeout=10,
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr[-300:].decode(errors="replace"))

    def test_process_pool_direct_fd_stderr_is_bounded_and_returns(self):
        # Retain the observed limitation; do not weaken this failure into a PASS.
        self.run_workload("write_stderr")

    def test_process_pool_python_stderr_is_bounded_and_returns(self):
        self.run_workload("write_python_stderr")

    @unittest.skipUnless(sys.platform == "linux", "POSIX supplementary-group denial requires isolated Linux")
    def test_extra_groups_denial_is_not_silently_ignored(self):
        self.assertNotEqual(os.getuid(), 0, "No root authority is granted for this test")
        invocation = [sys.executable, "-c", "print('CHILD_EXECUTED')"]
        with self.assertRaises(PermissionError):
            subprocess.run(invocation, extra_groups=[], check=True, timeout=5, capture_output=True)

        async def child():
            with anyio.fail_after(5):
                return await anyio.run_process(invocation, extra_groups=[])

        with self.assertRaises(PermissionError):
            anyio.run(child)


if __name__ == "__main__":
    print(f"AnyIO installed={version('anyio')}; runtime={sys.version.split()[0]}", flush=True)
    unittest.main()
