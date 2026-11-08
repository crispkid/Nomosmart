"""SYSUX-021: bounded reads against an owned real HTTP file server."""
from datetime import UTC, datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import time
import unittest

from app.core.errors import AppError
from app.integrations.remote_sources import HTTPRemoteSourceClient


class HTTPStreamLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get("NMS422_HTTP_LIVE_CONTEXT")
        if not path:
            raise RuntimeError("Owned real HTTP context is required; no synthetic responses permitted")
        cls.context = json.loads(Path(path).read_text())
        owner = json.loads(Path(cls.context["owner_file"]).read_text())
        if owner["execution_closed"] or datetime.now(UTC) >= datetime.fromisoformat(owner["deadline"]):
            raise RuntimeError("Owned execution window is closed")
        if owner["run_uuid"] != cls.context["run_uuid"] or owner["change_id"] != "CHG-422":
            raise RuntimeError("HTTP source ownership mismatch")
        source = Path(__file__).resolve().parents[1] / "app/integrations/remote_sources.py"
        if hashlib.sha256(source.read_bytes()).hexdigest() != cls.context["product_source_sha256"]:
            raise RuntimeError("HTTP product source changed")
        cls.client = HTTPRemoteSourceClient()
        cls.limit = 1024 * 1024
        cls.kwargs = {"verify_tls": True, "allowed_hosts": frozenset({"127.0.0.1"}),
                      "allowed_networks": (ipaddress.ip_network("127.0.0.1/32"),)}

    def fetch(self, route, limit):
        return self.client.get_object(url=self.context["origin"] + route, max_bytes=limit, **self.kwargs)

    def observation(self, route):
        time.sleep(.15)
        rows = json.loads(Path(self.context["requests_file"]).read_text())
        row = next(row for row in reversed(rows) if row["path"] == route)
        self.assertFalse(row["authorization_present"])
        return row

    def reject_large(self, route):
        with self.assertRaises(AppError) as result:
            self.fetch(route, self.limit)
        self.assertEqual(result.exception.code, "sync_file_too_large")
        self.assertEqual(result.exception.status_code, 413)
        row = self.observation(route)
        self.assertFalse(row["complete"], "Oversized source must not be downloaded completely")
        self.assertLess(row["sent_bytes"], 2 * self.limit)
        return row

    def test_known_length_is_rejected_before_full_download(self):
        self.reject_large("/publication-checklist-large.txt")

    def test_chunked_is_closed_at_streaming_limit(self):
        row = self.reject_large("/publication-checklist-large-chunked.txt")
        self.assertGreaterEqual(row["sent_bytes"], self.limit)
        self.assertLessEqual(row["sent_bytes"], self.limit + 2 * 65536)

    def test_small_file_keeps_bytes_and_metadata(self):
        expected = Path(self.context["small_file"]).read_bytes()
        result = self.fetch("/publication-checklist.txt", len(expected))
        self.assertEqual(result.body, expected)
        self.assertEqual(result.content_length, len(expected))
        self.assertEqual(result.content_type, "text/plain; charset=utf-8")
        self.assertEqual(result.etag, '"chg422-' + str(len(expected)) + '"')

    def test_existing_unlimited_caller_keeps_bytes(self):
        result = self.fetch("/publication-checklist.txt", None)
        self.assertEqual(result.body, Path(self.context["small_file"]).read_bytes())

    def test_not_found_keeps_existing_error(self):
        with self.assertRaises(AppError) as result:
            self.fetch("/absent-owned-input.txt", self.limit)
        self.assertEqual(result.exception.code, "remote_file_not_found")
        self.assertEqual(result.exception.status_code, 404)
