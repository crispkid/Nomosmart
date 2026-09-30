from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    payload = ErrorBody(
        code=exc.code,
        message=exc.message,
        details=exc.details,
        request_id=request_id,
    )
    headers = {"Retry-After": "5"} if exc.code == "upload_capacity_exhausted" else None
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump(), headers=headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    details = {"errors": [{"location": list(error["loc"]), "type": error["type"]} for error in exc.errors()]}
    payload = ErrorBody(code="validation_error", message="Request validation failed", details=details, request_id=request_id)
    return JSONResponse(status_code=422, content=payload.model_dump())


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    code = "not_found" if exc.status_code == 404 else "http_error"
    payload = ErrorBody(code=code, message="Resource was not found" if exc.status_code == 404 else "Request failed", request_id=request_id)
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())
