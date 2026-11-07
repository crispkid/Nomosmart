"""Real temporary HTTPS endpoints, native URL policy, no TLS bypass."""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
import os
import ssl
import sys
import tempfile
from threading import Thread
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy/installer'))
from nomosmart_installer.tls_client import TLSClient, TLSClientError, _approved_origin


class InstallerOriginLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='nomosmart-chg330-tls-')
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'CHG330 ephemeral HTTPS')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
        root = Path(cls.directory.name)
        cls.ca = root/'public-ca.pem'; cls.ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private = root/'server-key.pem'; private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())); private.chmod(0o600)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(str(cls.ca),str(private))
        cls.arrivals = []

        class OriginService(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                cls.arrivals.append((self.server.server_port,self.path))
                destinations = {'/same':'/final','/cross':cls.other_url+'/final','/host':cls.url.replace('127.0.0.1','localhost')+'/final','/downgrade':cls.url.replace('https:','http:')+'/final','/userinfo':cls.url.replace('https://','https://owned@')+'/final'}
                if self.path in destinations:
                    self.send_response(302);self.send_header('Location',destinations[self.path]);self.end_headers()
                else:
                    self.send_response(200);self.send_header('Content-Type','text/plain');self.end_headers();self.wfile.write(b'owned HTTPS source')

        configured_ports = os.environ.get('NMS_CURRENT_INSTALLER_TLS_PORTS')
        if configured_ports is not None and configured_ports != '18888,18889':
            cls.directory.cleanup()
            raise ValueError('Current native TLS ports must be reserved 18888,18889')
        ports = (18888,18889) if configured_ports is not None else (0,0)
        cls.servers = []
        try:
            for port in ports:
                cls.servers.append(ThreadingHTTPServer(('127.0.0.1',port),OriginService))
        except BaseException:
            for server in cls.servers:
                server.server_close()
            cls.directory.cleanup()
            raise
        cls.url = 'https://127.0.0.1:'+str(cls.servers[0].server_port)
        cls.other_url = 'https://127.0.0.1:'+str(cls.servers[1].server_port)
        cls.threads = []
        for server in cls.servers:
            server.socket = context.wrap_socket(server.socket,server_side=True)
            thread = Thread(target=server.serve_forever,daemon=True);thread.start();cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for server in cls.servers:
            server.shutdown();server.server_close()
        for thread in cls.threads:
            thread.join(timeout=2)
        cls.directory.cleanup()

    def client(self, **kwargs):
        return TLSClient(ca_file=str(self.ca),timeout=2,**kwargs)

    def test_real_same_origin_redirect_and_final_url(self):
        result = self.client().request('GET',self.url+'/same')
        self.assertEqual(result.status,200)
        self.assertEqual(result.final_url,self.url+'/final')
        self.assertEqual(result.body,b'owned HTTPS source')

    def test_same_host_other_port_rejected_before_other_service_arrival(self):
        before = len([x for x in self.arrivals if x[0]==self.servers[1].server_port])
        with self.assertRaises(TLSClientError):
            self.client().request('GET',self.url+'/cross')
        self.assertEqual(len([x for x in self.arrivals if x[0]==self.servers[1].server_port]),before)

    def test_other_host_downgrade_and_userinfo_are_rejected(self):
        for path in ('/host','/downgrade','/userinfo'):
            with self.subTest(path=path), self.assertRaises(TLSClientError):
                self.client().request('GET',self.url+path)

    def test_default_port_matches_explicit_443_and_paths_do_not_change_origin(self):
        self.assertEqual(_approved_origin('https://LOCALHOST/a'),_approved_origin('https://localhost:443/b'))
        self.assertNotEqual(_approved_origin('https://localhost'),_approved_origin('https://localhost:8443'))

    def test_invalid_initial_origins_are_safe_errors(self):
        for url in ('https://localhost:invalid/','https://localhost:65536/','https://localhost:-1/','https://owned@localhost/','https://[broken/','https:///missing','http://localhost/'):
            with self.subTest(url=url), self.assertRaises(TLSClientError):
                _approved_origin(url)

    def test_directory_no_redirect_and_body_limits_stay_enforced(self):
        with self.assertRaises(TLSClientError):
            self.client(max_redirects=0).request('GET',self.url+'/same')
        with self.assertRaises(TLSClientError):
            self.client(max_body=3).request('GET',self.url+'/final')

    def test_untrusted_ca_is_rejected(self):
        from certifi import where
        client = TLSClient(ca_file=where(),timeout=2)
        with self.assertRaises(TLSClientError):
            client.request('GET',self.url+'/final')


if __name__ == '__main__':
    unittest.main()
