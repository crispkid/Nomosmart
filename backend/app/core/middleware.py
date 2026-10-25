from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


logger = logging.getLogger("nomosmart.request")


class RequestIdMiddleware:
    """Preserve streaming errors instead of finalizing an incomplete response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get("X-Request-Id") or str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_code = 500
        headers_sent = False
        completed = False

        def log_fields(result: str, error_code: str | None = None) -> dict:
            fields = {
                "request_id": request_id,
                "method": scope["method"],
                "path": scope["path"],
                "status_code": status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "result": result,
            }
            if error_code is not None:
                fields["error_code"] = error_code
            return fields

        async def send_response(message: Message) -> None:
            nonlocal status_code, headers_sent, completed
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", []))}
                MutableHeaders(scope=message)["X-Request-Id"] = request_id
            await send(message)
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers_sent = True
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True

        try:
            await self.app(scope, receive, send_response)
        except asyncio.CancelledError:
            logger.info("request_cancelled", extra=log_fields("cancelled", "request_cancelled"))
            raise
        except Exception:
            logger.exception(
                "request_failed",
                extra=log_fields("error", "response_stream_failed" if headers_sent else "unhandled_exception"),
            )
            raise
        else:
            if completed:
                logger.info("request_completed", extra=log_fields("success" if status_code < 400 else "error"))
            else:
                logger.error("request_failed", extra=log_fields("error", "response_incomplete"))
