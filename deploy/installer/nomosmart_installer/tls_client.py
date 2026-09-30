from __future__ import annotations

from dataclasses import dataclass
import ssl
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)


class TLSClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class TLSResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]
    content_type: str
    final_url: str


class _RestrictedRedirect(HTTPRedirectHandler):
    def __init__(self, origin_host: str, maximum: int) -> None:
        super().__init__()
        self.origin_host = origin_host
        self.maximum = maximum
        self.count = 0

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        target = urlparse(new_url)
        if (
            target.scheme != "https"
            or target.hostname != self.origin_host
        ):
            raise TLSClientError(
                "HTTPS redirect left the approved origin"
            )
        self.count += 1
        if self.count > self.maximum:
            raise TLSClientError("HTTPS redirect limit exceeded")
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


class TLSClient:
    def __init__(
        self,
        *,
        ca_file: str | None = None,
        ca_data: str | None = None,
        timeout: float = 30.0,
        max_body: int = 1024 * 1024,
        max_redirects: int = 3,
    ) -> None:
        if bool(ca_file) == bool(ca_data):
            raise TLSClientError(
                "exactly one CA file or CA data input is required"
            )
        self.context = ssl.create_default_context(
            cafile=ca_file,
            cadata=ca_data,
        )
        self.context.check_hostname = True
        self.context.verify_mode = ssl.CERT_REQUIRED
        self.timeout = timeout
        self.max_body = max_body
        self.max_redirects = max_redirects

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset({200}),
        content_types: tuple[str, ...] = (),
    ) -> TLSResponse:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise TLSClientError(
                "TLS client requires an HTTPS URL without user information"
            )
        redirect = _RestrictedRedirect(
            parsed.hostname, self.max_redirects
        )
        opener = build_opener(HTTPSHandler(context=self.context), redirect)
        request = Request(
            url,
            data=body,
            headers=dict(headers or {}),
            method=method,
        )
        try:
            response = opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            response = exc
        except TLSClientError:
            raise
        except (URLError, TimeoutError, ssl.SSLError) as exc:
            raise TLSClientError(
                "HTTPS connection, CA, hostname, SNI, or timeout verification failed"
            ) from exc
        try:
            raw = response.read(self.max_body + 1)
            if len(raw) > self.max_body:
                raise TLSClientError("HTTPS response exceeded maximum body size")
            status = int(response.status)
            content_type = response.headers.get_content_type()
            final_url = response.geturl()
            final = urlparse(final_url)
            if (
                final.scheme != "https"
                or final.hostname != parsed.hostname
            ):
                raise TLSClientError(
                    "HTTPS final URL left the approved origin"
                )
            if status not in accepted_statuses:
                raise TLSClientError(
                    f"HTTPS endpoint returned unaccepted HTTP {status}"
                )
            if content_types and not any(
                content_type == expected
                or content_type.startswith(expected)
                for expected in content_types
            ):
                raise TLSClientError(
                    "HTTPS response content type is not accepted"
                )
            return TLSResponse(
                status=status,
                body=raw,
                headers=dict(response.headers.items()),
                content_type=content_type,
                final_url=final_url,
            )
        finally:
            response.close()
