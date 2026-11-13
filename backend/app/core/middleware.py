from __future__ import annotations

import logging
import re
import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.errors import unhandled_error_response


logger = logging.getLogger("nomosmart.request")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def request_id_from(value: str | None) -> str:
    # Client-supplied IDs reach logs and audit rows; accept only bounded tokens.
    return value if value and REQUEST_ID_PATTERN.fullmatch(value) else str(uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request_id_from(request.headers.get("X-Request-Id"))
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": 500, "latency_ms": latency_ms, "result": "error", "error_code": "unhandled_exception"},
            )
            return unhandled_error_response(request)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "request_completed",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "latency_ms": latency_ms, "result": "success" if response.status_code < 400 else "error"},
        )
        return response
