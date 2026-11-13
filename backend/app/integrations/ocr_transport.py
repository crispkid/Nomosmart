"""Single-attempt, bounded HTTP transport for native document OCR."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import json
import logging
import ssl

import httpx

from app.core.errors import AppError
from app.domain.ocr_timeout_policy import OCRRequestWindow, diagnostic_error, safe_provider_error


_private_request = ContextVar("private_ocr_http", default=False)


class _PrivateTransportLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx INFO includes the URL; httpcore DEBUG may include response headers.
        # Suppress only this request's library logs, never unrelated concurrent work.
        return not _private_request.get()


_privacy_filter = _PrivateTransportLogFilter()


def classify_transport_error(error: Exception, window: OCRRequestWindow) -> tuple[str, str]:
    for error_type, phase in ((httpx.ConnectTimeout, "connect"), (httpx.ReadTimeout, "read"),
                              (httpx.WriteTimeout, "write"), (httpx.PoolTimeout, "pool")):
        if isinstance(error, error_type):
            return window.timeout_kind, phase
    if isinstance(error, TimeoutError):
        return window.timeout_kind, "unknown"
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(seen) < 16:
        if isinstance(current, ssl.SSLError):
            return "tls_error", "unknown"
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    if isinstance(error, (json.JSONDecodeError, UnicodeError, httpx.DecodingError)):
        return "invalid_response", "response"
    if isinstance(error, (httpx.TransportError, OSError)):
        return "connection_error", "unknown"
    return "unknown", "unknown"


def decode_ocr_response(raw: bytes) -> dict[str, object]:
    """Decode only; callers must still prove the response met its deadline."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise diagnostic_error("ocr_adapter_unavailable", "OCR adapter response is invalid",
                               kind="invalid_response", phase="response", attempted=True) from None
    if not isinstance(payload, dict):
        raise diagnostic_error("ocr_adapter_response_invalid", "OCR response must be a JSON object",
                               kind="invalid_response", phase="response", attempted=True, status_code=502)
    return payload


async def _request(url: str, headers: dict[str, str], content: bytes,
                   verify: ssl.SSLContext | bool, window: OCRRequestWindow,
                   max_request_bytes: int | None = None, max_response_bytes: int | None = None) -> dict[str, object]:
    attempted = False
    response_status = None
    token = _private_request.set(True)
    try:
        window.check(attempted=False)
        if max_request_bytes is not None and len(content) > max_request_bytes:
            raise diagnostic_error("ocr_request_too_large", "OCR request exceeds its byte limit", kind="input_limit", attempted=False, status_code=422)
        client = httpx.AsyncClient(verify=verify, timeout=window.remaining(), trust_env=False, follow_redirects=False)
        # Client construction imports its transports; register filters on emitting loggers,
        # not the root logger (ancestor filters do not filter propagated child records).
        for name in tuple(logging.Logger.manager.loggerDict):
            if name == "httpx" or name.startswith("httpcore."):
                logging.getLogger(name).addFilter(_privacy_filter)
        async with client:
            try:
                async with asyncio.timeout(window.remaining()):
                    window.check(attempted=False)
                    attempted = True  # Dispatch may incur cost even if the response is lost.
                    async with client.stream("POST", url, headers=headers, content=content) as response:
                        response_status = response.status_code
                        if not 200 <= response.status_code < 300:
                            details: dict[str, object] = {"status_code": response.status_code}
                            raw = bytearray()
                            async for part in response.aiter_bytes():
                                raw.extend(part[:65537-len(raw)])
                                if len(raw) > 65536:
                                    break
                            if len(raw) <= 65536:
                                try:
                                    body = json.loads(raw)
                                    info = body.get("error") if isinstance(body, dict) else None
                                    if isinstance(info, dict):
                                        details.update(safe_provider_error({k: info.get(k) for k in ("type", "code", "param")}))
                                except (ValueError, UnicodeError):
                                    pass
                            error = AppError("ocr_adapter_provider_rejected", "OCR adapter provider rejected the request",
                                             status_code=502, details=details)
                            error.ocr_diagnostics = {"error_kind": "provider_rejected", "phase": "response", "attempted": True}
                            raise error
                        if max_response_bytes is None:
                            raw = await response.aread()
                        else:
                            length = response.headers.get("Content-Length")
                            if length and length.isdecimal() and int(length) > max_response_bytes:
                                raise diagnostic_error("ocr_response_too_large", "OCR response exceeds its byte limit", kind="output_limit", attempted=True, status_code=502)
                            bounded = bytearray()
                            async for part in response.aiter_bytes(chunk_size=65536):
                                if len(bounded) + len(part) > max_response_bytes:
                                    raise diagnostic_error("ocr_response_too_large", "OCR response exceeds its byte limit", kind="output_limit", attempted=True, status_code=502)
                                bounded.extend(part)
                            raw = bytes(bounded)
                    window.check(attempted=True)
                    payload = decode_ocr_response(raw)
                    window.check(attempted=True)
                    return payload
            except (httpx.HTTPError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
                kind, phase = classify_transport_error(exc, window)
                error = diagnostic_error("ocr_adapter_unavailable", "OCR adapter endpoint is unavailable",
                                         kind=kind, phase=phase, attempted=attempted)
                error.details = safe_provider_error({"status_code": response_status})
                raise error from None
    except AppError:
        raise
    except Exception as exc:
        # Also bound client construction/close failures; do not lose earlier paid pages.
        kind, phase = classify_transport_error(exc, window)
        raise diagnostic_error("ocr_adapter_unavailable", "OCR adapter endpoint is unavailable",
                               kind=kind, phase=phase, attempted=attempted) from None
    finally:
        _private_request.reset(token)


def post_ocr_json(*, url: str, headers: dict[str, str], body: dict[str, object],
                  verify: ssl.SSLContext | bool, window: OCRRequestWindow,
                   max_request_bytes: int | None = None, max_response_bytes: int | None = None) -> dict[str, object]:
    # The only production caller is a synchronous Worker. Never spawn a fallback thread.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise diagnostic_error("ocr_adapter_unavailable", "OCR transport requires a synchronous Worker",
                               kind="unknown", attempted=False)
    content = json.dumps(body).encode("utf-8")
    window.check(attempted=False)
    with asyncio.Runner() as runner:
        return runner.run(_request(url, headers, content, verify, window, max_request_bytes, max_response_bytes))
