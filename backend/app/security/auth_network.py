"""Operator-controlled endpoint and CA policy shared by OIDC and LDAP."""
from __future__ import annotations

from ipaddress import ip_address, ip_network
from pathlib import Path
import socket
import ssl
from urllib.parse import urlparse
import httpx

from app.core.config import Settings
from app.core.errors import AppError


def trusted_ca(settings: Settings, reference: str = "") -> str | None:
    if not reference:
        return None
    path = Path(reference)
    try:
        root = Path(settings.auth_trust_root).resolve(strict=True)
        if not path.is_absolute():
            path = root / path
        if not path.resolve(strict=True).is_relative_to(root) or not path.is_file():
            raise ValueError("untrusted path")
    except (OSError, ValueError) as exc:
        raise AppError("auth_ca_invalid", "Authentication CA reference is not available", status_code=422) from exc
    return str(path.resolve())


def resolve_endpoint(settings: Settings, url: str, *, schemes: tuple[str, ...] = ("https",)) -> tuple[str, tuple[str, ...]]:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise AppError("auth_endpoint_invalid", "Authentication endpoint is invalid", status_code=422) from exc
    if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise AppError("auth_endpoint_invalid", "Authentication endpoint is not permitted", status_code=422)
    if parsed.scheme in {"ldap", "ldaps"} and (parsed.query or parsed.params or parsed.path not in {"", "/"}):
        raise AppError("auth_endpoint_invalid", "Directory endpoint must not include search parameters", status_code=422)
    host = parsed.hostname.lower().rstrip(".")
    allowed_hosts = {h.strip().lower().rstrip(".") for h in settings.auth_endpoint_allowed_hosts.split(",") if h.strip()}
    networks = [ip_network(c.strip(), strict=False) for c in settings.auth_endpoint_allowed_cidrs.split(",") if c.strip()]
    try:
        addresses = {ip_address(row[4][0]) for row in socket.getaddrinfo(host, port or (636 if parsed.scheme == "ldaps" else 389 if parsed.scheme == "ldap" else 443), type=socket.SOCK_STREAM)}
    except (OSError, ValueError) as exc:
        raise AppError("identity_provider_unavailable", "Authentication service cannot be resolved", status_code=503) from exc
    if not addresses:
        raise AppError("identity_provider_unavailable", "Authentication service cannot be resolved", status_code=503)
    for address in addresses:
        if address.is_link_local or address.is_multicast or address.is_unspecified:
            raise AppError("auth_endpoint_denied", "Authentication endpoint is not permitted", status_code=422)
        explicit = host in allowed_hosts or any(address.version == network.version and address in network for network in networks)
        if address.is_loopback and not explicit or (address.is_private or address.is_reserved) and not explicit:
            raise AppError("auth_endpoint_denied", "Authentication endpoint requires an operator allowlist", status_code=422)
    return host, tuple(sorted(str(address) for address in addresses))


def validate_endpoint(settings: Settings, url: str, *, schemes: tuple[str, ...] = ("https",)) -> str:
    resolve_endpoint(settings, url, schemes=schemes)
    return url


def tls_context(settings: Settings, reference: str = "") -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=trusted_ca(settings, reference))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class BoundedAuthStream(httpx.SyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    def __iter__(self):
        count = 0
        for chunk in self.stream:
            count += len(chunk)
            if count > 1048576:
                raise AppError("auth_response_limit", "Authentication response exceeds the permitted size", status_code=503)
            yield chunk

    def close(self):
        self.stream.close()


class PinnedAuthTransport(httpx.BaseTransport):
    """Connect to the checked IP while preserving the original TLS identity."""
    def __init__(self, settings: Settings, reference: str = ""):
        self.settings = settings
        self.transport = httpx.HTTPTransport(verify=tls_context(settings, reference), retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host, addresses = resolve_endpoint(self.settings, str(request.url))
        headers = request.headers.copy()
        headers["Accept-Encoding"] = "identity"
        headers["Host"] = request.url.netloc.decode("ascii")
        pinned = httpx.Request(request.method, request.url.copy_with(host=addresses[0]), headers=headers, stream=request.stream, extensions={**request.extensions, "sni_hostname": host})
        response = self.transport.handle_request(pinned)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            response.close()
            raise AppError("auth_response_encoding", "Authentication service returned unsupported encoding", status_code=503)
        response.stream = BoundedAuthStream(response.stream)
        return response

    def close(self) -> None:
        self.transport.close()
