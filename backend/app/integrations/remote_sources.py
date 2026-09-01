from __future__ import annotations

# DSYNC-001/NET-002 explicitly retain operator-selected plaintext FTP.
import ftplib  # nosec B402
import ipaddress
import json
import socket
from io import BytesIO, StringIO
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
                response = client.get(pinned_url, headers=request_headers, extensions={"sni_hostname": sni_hostname})
        except httpx.TimeoutException as exc:
            raise AppError("connection_timeout", "HTTP/API source timed out", status_code=503) from exc
        except httpx.HTTPError as exc:
            raise AppError("connection_failed", "HTTP/API source fetch failed", status_code=503) from exc
        if 300 <= response.status_code < 400:
            raise AppError("http_redirect_not_allowed", "HTTP/API source redirects are not allowed", status_code=422)
        if response.status_code == 404:
            raise AppError("remote_file_not_found", "HTTP/API source was not found", status_code=404)
        if response.status_code in {401, 403}:
            raise AppError("authentication_failed", "HTTP/API source authentication failed", status_code=503)
        if response.status_code >= 400:
            raise AppError("connection_failed", "HTTP/API source fetch failed", status_code=503, details={"status_code": response.status_code})
        if max_bytes is not None and len(response.content) > max_bytes:
            raise AppError("sync_file_too_large", "HTTP/API source exceeds the configured size limit", status_code=413)
        content_length = response.headers.get("content-length")
        return RemoteObject(body=response.content, etag=response.headers.get("etag"), content_type=response.headers.get("content-type"), content_length=int(content_length) if content_length and content_length.isdigit() else len(response.content))

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


class FTPRemoteSourceClient:
    def probe(self, *, host: str, port: int, username: str, credential: str, remote_path: str, file_name: str, timeout_seconds: int = 30) -> int | None:
        try:
            # DSYNC-001 explicitly defines this plaintext FTP transport option.
            with ftplib.FTP() as client:  # nosec B321
                client.connect(host=host, port=port, timeout=timeout_seconds)
                client.login(user=username, passwd=credential)
                if remote_path.strip("/"):
                    client.cwd(remote_path.strip("/"))
                return client.size(file_name)
        except ftplib.error_perm as exc:
            _raise_ftp_probe_error(exc)
        except (OSError, ftplib.Error) as exc:
            raise AppError("connection_failed", "FTP source connection failed", status_code=503) from exc

    def get_object(
        self,
        *,
        host: str,
        port: int,
        username: str,
        credential: str,
        remote_path: str,
        file_name: str,
        timeout_seconds: int = 30,
        max_bytes: int | None = None,
    ) -> RemoteObject:
        try:
            # DSYNC-001 explicitly defines this plaintext FTP transport option.
            with ftplib.FTP() as client:  # nosec B321
                client.connect(host=host, port=port, timeout=timeout_seconds)
                client.login(user=username, passwd=credential)
                body = _retrieve_ftp_binary(client, remote_path, file_name, max_bytes=max_bytes)
        except ftplib.error_perm as exc:
            message = str(exc)
            if message.startswith("550"):
                raise AppError("remote_file_not_found", "Remote file was not found", status_code=404) from exc
            if message.startswith("530"):
                raise AppError("authentication_failed", "Remote authentication failed", status_code=503) from exc
            raise AppError("connection_failed", "Remote file fetch failed", status_code=503) from exc
        except (OSError, ftplib.Error) as exc:
            raise AppError("connection_failed", "Remote file fetch failed", status_code=503) from exc
        return RemoteObject(body=body, content_type=None, content_length=len(body))


class FTPSRemoteSourceClient:
    def probe(self, *, host: str, port: int, username: str, credential: str, remote_path: str, file_name: str, timeout_seconds: int = 30) -> int | None:
        try:
            with ftplib.FTP_TLS() as client:
                client.connect(host=host, port=port, timeout=timeout_seconds)
                client.login(user=username, passwd=credential)
                client.prot_p()
                if remote_path.strip("/"):
                    client.cwd(remote_path.strip("/"))
                return client.size(file_name)
        except ftplib.error_perm as exc:
            _raise_ftp_probe_error(exc)
        except (OSError, ftplib.Error) as exc:
            raise AppError("connection_failed", "FTPS source connection failed", status_code=503) from exc

    def get_object(
        self,
        *,
        host: str,
        port: int,
        username: str,
        credential: str,
        remote_path: str,
        file_name: str,
        timeout_seconds: int = 30,
        max_bytes: int | None = None,
    ) -> RemoteObject:
        try:
            with ftplib.FTP_TLS() as client:
                client.connect(host=host, port=port, timeout=timeout_seconds)
                client.login(user=username, passwd=credential)
                client.prot_p()
                body = _retrieve_ftp_binary(client, remote_path, file_name, max_bytes=max_bytes)
        except ftplib.error_perm as exc:
            message = str(exc)
            if message.startswith("550"):
                raise AppError("remote_file_not_found", "Remote file was not found", status_code=404) from exc
            if message.startswith("530"):
                raise AppError("authentication_failed", "Remote authentication failed", status_code=503) from exc
            raise AppError("connection_failed", "Remote file fetch failed", status_code=503) from exc
        except (OSError, ftplib.Error) as exc:
            raise AppError("connection_failed", "Remote file fetch failed", status_code=503) from exc
        return RemoteObject(body=body, content_type=None, content_length=len(body))


class SFTPRemoteSourceClient:
    def probe(self, *, host: str, port: int, username: str, credential: str, remote_path: str, file_name: str, known_hosts_path: str, timeout_seconds: int = 30) -> int:
        try:
            import paramiko  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AppError("sftp_client_unavailable", "SFTP client dependency is not installed", status_code=503) from exc
        client = paramiko.SSHClient()
        try:
            client.load_host_keys(known_hosts_path)
        except OSError as exc:
            raise AppError("sftp_known_hosts_unavailable", "SFTP known-hosts file is unavailable", status_code=503) from exc
        try:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(
                hostname=host,
                port=port,
                username=username,
                timeout=timeout_seconds,
                banner_timeout=timeout_seconds,
                auth_timeout=timeout_seconds,
                look_for_keys=False,
                allow_agent=False,
                **_sftp_authentication(paramiko, credential),
            )
            sftp = client.open_sftp()
            try:
                remote_file = f"{remote_path.strip('/')}/{file_name}" if remote_path.strip("/") else file_name
                return int(sftp.stat(remote_file).st_size)
            finally:
                sftp.close()
        except FileNotFoundError as exc:
            raise AppError("remote_file_not_found", "Remote file was not found", status_code=404) from exc
        except AppError:
            raise
        except Exception as exc:
            raise AppError("connection_failed", "SFTP source connection failed or host key was rejected", status_code=503) from exc
        finally:
            client.close()

    def get_object(
        self,
        *,
        host: str,
        port: int,
        username: str,
        credential: str,
        remote_path: str,
        file_name: str,
        verify_host_key: bool = True,
        known_hosts_path: str | None = None,
        timeout_seconds: int = 30,
        max_bytes: int | None = None,
    ) -> RemoteObject:
        try:
            import paramiko  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised when optional dependency is absent
            raise AppError("sftp_client_unavailable", "SFTP client dependency is not installed", status_code=503) from exc
        client = paramiko.SSHClient()
        if not verify_host_key:
            raise AppError("sftp_host_key_verification_required", "SFTP host-key verification is required", status_code=422)
        if not known_hosts_path:
            raise AppError("sftp_known_hosts_unavailable", "SFTP known-hosts file is required", status_code=503)
        try:
            client.load_host_keys(known_hosts_path)
        except OSError as exc:
            raise AppError("sftp_known_hosts_unavailable", "SFTP known-hosts file is unavailable", status_code=503) from exc
        try:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(
                hostname=host,
                port=port,
                username=username,
                timeout=timeout_seconds,
                banner_timeout=timeout_seconds,
                auth_timeout=timeout_seconds,
                look_for_keys=False,
                allow_agent=False,
                **_sftp_authentication(paramiko, credential),
            )
            sftp = client.open_sftp()
            try:
                remote_file = f"{remote_path.strip('/')}/{file_name}" if remote_path.strip("/") else file_name
                with sftp.open(remote_file, "rb") as handle:
                    body = handle.read(max_bytes + 1 if max_bytes is not None else None)
            finally:
                sftp.close()
        except FileNotFoundError as exc:
            raise AppError("remote_file_not_found", "Remote file was not found", status_code=404) from exc
        except AppError:
            raise
        except Exception as exc:
            raise AppError("connection_failed", "Remote file fetch failed", status_code=503) from exc
        finally:
            client.close()
        if max_bytes is not None and len(body) > max_bytes:
            raise AppError("sync_file_too_large", "Remote file exceeds the configured size limit", status_code=413)
        return RemoteObject(body=body, content_type=None, content_length=len(body))


def _sftp_authentication(paramiko_module, credential: str) -> dict[str, object]:
    """Build password or memory-only private-key auth without key discovery."""

    stripped = credential.strip()
    if not stripped.startswith("{"):
        return {"password": credential}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise AppError("sftp_credential_invalid", "SFTP credential is invalid", status_code=422) from exc
    if not isinstance(payload, dict):
        raise AppError("sftp_credential_invalid", "SFTP credential is invalid", status_code=422)
    password = payload.get("password")
    private_key = payload.get("private_key")
    passphrase = payload.get("passphrase")
    if isinstance(password, str) and password and not private_key:
        return {"password": password}
    if not isinstance(private_key, str) or not private_key.strip():
        raise AppError("sftp_credential_invalid", "SFTP credential is incomplete", status_code=422)
    if passphrase is not None and not isinstance(passphrase, str):
        raise AppError("sftp_credential_invalid", "SFTP key passphrase is invalid", status_code=422)
    key_classes = [
        getattr(paramiko_module, name)
        for name in ("Ed25519Key", "ECDSAKey", "RSAKey", "DSSKey")
        if getattr(paramiko_module, name, None) is not None
    ]
    for key_class in key_classes:
        try:
            key = key_class.from_private_key(StringIO(private_key), password=passphrase or None)
            return {"pkey": key}
        except Exception:
            continue
    raise AppError(
        "sftp_private_key_invalid",
        "SFTP private key could not be loaded",
        status_code=422,
    )


def _retrieve_ftp_binary(client: ftplib.FTP, remote_path: str, file_name: str, *, max_bytes: int | None) -> bytes:
    if remote_path.strip("/"):
        client.cwd(remote_path.strip("/"))
    buffer = BytesIO()

    def write(chunk: bytes) -> None:
        if max_bytes is not None and buffer.tell() + len(chunk) > max_bytes:
            raise AppError("sync_file_too_large", "Remote file exceeds the configured size limit", status_code=413)
        buffer.write(chunk)

    client.retrbinary(f"RETR {file_name}", write)
    return buffer.getvalue()


def _raise_ftp_probe_error(exc: ftplib.error_perm) -> None:
    message = str(exc)
    if message.startswith("550"):
        raise AppError("remote_file_not_found", "Remote file was not found", status_code=404) from exc
    if message.startswith("530"):
        raise AppError("authentication_failed", "Remote authentication failed", status_code=503) from exc
    raise AppError("connection_failed", "Remote source connection failed", status_code=503) from exc


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
