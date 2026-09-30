from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router, public_api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, app_error_handler, http_error_handler, validation_error_handler
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    effective_settings = settings or get_settings()
    configure_logging(effective_settings.log_level, effective_settings.log_format)
    application = FastAPI(title="NomoSmart API", version="0.1.1")
    application.state.settings = effective_settings
    application.add_middleware(RequestIdMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=effective_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id", "X-NomoSmart-API-Key"],
        expose_headers=["X-Total-Count"],
    )
    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.include_router(api_router)
    application.include_router(public_api_router)

    @application.get("/")
    def welcome() -> dict[str, str]:
        return {"message": "NomoSmart API", "version": "v1"}

    return application


app = create_app()
