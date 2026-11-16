from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse, urlunsplit

import httpx

from app.core.errors import AppError
from app.integrations.s3_storage import RemoteObject


class HTTPRemoteSourceClient:
    def get_object(
        self,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 30,
        verify_tls: bool = True,
        max_bytes: int | None = None,
        allowed_hosts: frozenset[str] = frozenset(),
        allowed_networks: tuple = (),
    ) -> RemoteObject:
        pinned_url, host_header, sni_hostname = _pinned_http_target(url, allowed_hosts=allowed_hosts, allowed_networks=allowed_networks)
        request_headers = {**(headers or {}), "host": host_header}
        try:
            with httpx.Client(verify=verify_tls, timeout=timeout_seconds, follow_redirects=False, trust_env=False) as client:
                with client.stream("GET", pinned_url, headers=request_headers, extensions={"sni_hostname": sni_hostname}) as response:
                    if 300 <= response.status_code < 400:
                        raise AppError("http_redirect_not_allowed", "HTTP/API source redirects are not allowed", status_code=422)
                    if response.status_code == 404:
                        raise AppError("remote_file_not_found", "HTTP/API source was not found", status_code=404)
                    if response.status_code in {401, 403}:
                        raise AppError("authentication_failed", "HTTP/API source authentication failed", status_code=503)
                    if response.status_code >= 400:
                        raise AppError("connection_failed", "HTTP/API source fetch failed", status_code=503, details={"status_code": response.status_code})
                    length_header = response.headers.get("content-length")
                    content_length = int(length_header) if length_header and length_header.isdigit() else None
                    if max_bytes is not None and content_length is not None and content_length > max_bytes:
                        raise AppError("sync_file_too_large", "HTTP/API source exceeds the configured size limit", status_code=413)
                    body = bytearray()
                    chunk_size = min(65536, max_bytes + 1) if max_bytes is not None else 65536
                    for chunk in response.iter_bytes(chunk_size=max(1, chunk_size)):
                        if max_bytes is not None and len(body) + len(chunk) > max_bytes:
                            raise AppError("sync_file_too_large", "HTTP/API source exceeds the configured size limit", status_code=413)
                        body.extend(chunk)
                    return RemoteObject(body=bytes(body), etag=response.headers.get("etag"), content_type=response.headers.get("content-type"), content_length=content_length if content_length is not None else len(body))
        except httpx.TimeoutException as exc:
            raise AppError("connection_timeout", "HTTP/API source timed out", status_code=503) from exc
        except httpx.HTTPError as exc:
            raise AppError("connection_failed", "HTTP/API source fetch failed", status_code=503) from exc

    def probe(
        self,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 30,
        verify_tls: bool = True,
        allowed_hosts: frozenset[str] = frozenset(),
        allowed_networks: tuple = (),
    ) -> int:
        pinned_url, host_header, sni_hostname = _pinned_http_target(url, allowed_hosts=allowed_hosts, allowed_networks=allowed_networks)
        request_headers = {**(headers or {}), "host": host_header}
        try:
            with httpx.Client(verify=verify_tls, timeout=timeout_seconds, follow_redirects=False, trust_env=False) as client:
                response = client.head(pinned_url, headers=request_headers, extensions={"sni_hostname": sni_hostname})
                if response.status_code in {405, 501}:
                    request_headers["range"] = "bytes=0-0"
                    with client.stream("GET", pinned_url, headers=request_headers, extensions={"sni_hostname": sni_hostname}) as streamed:
                        response = streamed
                        next(streamed.iter_bytes(), b"")
                        status_code = streamed.status_code
                else:
                    status_code = response.status_code
        except httpx.TimeoutException as exc:
            raise AppError("connection_timeout", "HTTP/API source timed out", status_code=503) from exc
        except httpx.HTTPError as exc:
            raise AppError("connection_failed", "HTTP/API source connection failed", status_code=503) from exc
        _validate_http_status(status_code)
        return status_code


def _guard_http_url(url: str, *, allowed_hosts: frozenset[str] = frozenset(), allowed_networks: tuple = ()) -> None:
    _pinned_http_target(url, allowed_hosts=allowed_hosts, allowed_networks=allowed_networks)


def _pinned_http_target(url: str, *, allowed_hosts: frozenset[str] = frozenset(), allowed_networks: tuple = ()) -> tuple[str, str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise AppError("http_source_url_invalid", "HTTP/API source URL is invalid", status_code=422)
    hostname = parsed.hostname.lower().rstrip(".")
    addresses = _resolved_addresses(hostname)
    host_allowed = hostname in allowed_hosts
    if any(_address_is_blocked(address) and not host_allowed and not any(address in network for network in allowed_networks) for address in addresses):
        raise AppError("http_source_ssrf_blocked", "HTTP/API source target is not allowed", status_code=422)
    address = addresses[0]
    pinned_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    if parsed.port:
        pinned_host = f"{pinned_host}:{parsed.port}"
    pinned_url = urlunsplit((parsed.scheme, pinned_host, parsed.path or "/", parsed.query, ""))
    host_header = hostname
    default_port = 443 if parsed.scheme == "https" else 80
    if parsed.port and parsed.port != default_port:
        host_header = f"{host_header}:{parsed.port}"
    return pinned_url, host_header, hostname


def _host_is_blocked(hostname: str) -> bool:
    return any(_address_is_blocked(address) for address in _resolved_addresses(hostname))


def _resolved_addresses(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(result[4][0]) for result in socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)]
        except OSError as exc:
            raise AppError("http_source_dns_failed", "HTTP/API source host could not be resolved", status_code=422) from exc
    return list(dict.fromkeys(addresses))


def _address_is_blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_loopback or address.is_link_local or address.is_private or address.is_multicast or address.is_reserved or address.is_unspecified


def _validate_http_status(status_code: int) -> None:
    if 300 <= status_code < 400:
        raise AppError("http_redirect_not_allowed", "HTTP/API source redirects are not allowed", status_code=422)
    if status_code == 404:
        raise AppError("remote_file_not_found", "HTTP/API source was not found", status_code=404)
    if status_code in {401, 403}:
        raise AppError("authentication_failed", "HTTP/API source authentication failed", status_code=503)
    if status_code >= 400:
        raise AppError("connection_failed", "HTTP/API source connection failed", status_code=503, details={"status_code": status_code})
