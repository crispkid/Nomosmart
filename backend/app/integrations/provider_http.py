"""Shared synchronous HTTP transport for AI provider JSON calls (CHG-424 D424-08 / OPT424-019).

Chat/Judge (non-streaming) and Embedding requests previously opened a new urllib connection,
including a TLS handshake, for every call. They now share one httpx client per process and TLS
verification mode, so keep-alive connections are reused. Redirects are never followed: a 3xx
answer is a provider rejection like any other non-2xx status. Environment proxy settings stay in
effect, as with urllib.
"""
from __future__ import annotations

import json
import os
import ssl
import threading
from typing import Any

import httpx


class ProviderRejectedError(Exception):
    """The provider answered with a non-2xx status (including 3xx, which is not followed)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider returned HTTP {status_code}")
        self.status_code = status_code


class ProviderUnavailableError(Exception):
    """The provider could not be reached, timed out or returned a body that is not JSON."""


_CLIENT_LOCK = threading.Lock()
_CLIENTS: dict[tuple[int, bool], httpx.Client] = {}


def _tls_verification(verify_tls: bool) -> ssl.SSLContext | bool:
    if not verify_tls:
        return ssl._create_unverified_context()  # noqa: S323 - operator-configured per model
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        return True


def provider_client(verify_tls: bool) -> httpx.Client:
    """Process-wide client per TLS mode; keyed by process id so forked workers get their own pool."""
    key = (os.getpid(), verify_tls)
    with _CLIENT_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = httpx.Client(verify=_tls_verification(verify_tls), follow_redirects=False, trust_env=True)
            _CLIENTS[key] = client
        return client


def post_provider_json(url: str, body: dict[str, Any], *, headers: dict[str, str] | None, timeout_seconds: float, verify_tls: bool) -> Any:
    """POST a JSON body and return the decoded JSON response, raising the two provider error types."""
    client = provider_client(verify_tls)
    try:
        response = client.post(
            url,
            content=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            timeout=timeout_seconds,
        )
    except (httpx.TransportError, TimeoutError, OSError) as exc:
        raise ProviderUnavailableError(str(type(exc).__name__)) from exc
    if not response.is_success:
        raise ProviderRejectedError(response.status_code)
    try:
        return json.loads(response.content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderUnavailableError("invalid_json") from exc
