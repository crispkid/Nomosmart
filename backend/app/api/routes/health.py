from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.deployment.bootstrap import runtime_bootstrap_status
from app.integrations.health import check_dependencies


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@router.get("/ready", response_model=None)
def readiness(request: Request) -> dict[str, object] | JSONResponse:
    settings = request.app.state.settings
    statuses = [*check_dependencies(settings), *runtime_bootstrap_status(settings)]
    dependencies = {status.name: {"healthy": status.healthy, "detail": status.detail} for status in statuses}
    payload = {"status": "ready" if all(status.healthy for status in statuses) else "not_ready", "dependencies": dependencies}
    if payload["status"] != "ready":
        return JSONResponse(status_code=503, content=payload)
    return payload
