"""Request-local readiness timing; never an alternative health decision."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import logging
import math
import time
from typing import Protocol, TypeVar


logger = logging.getLogger("nomosmart.readiness")
CHECK_NAMES = (
    "postgresql", "redis", "celery_broker", "celery_result_backend", "s3",
    "opensearch", "neo4j", "keycloak", "celery_worker", "deployment.evidence",
    "deployment.database", "deployment.s3", "deployment.oidc",
)
OUTCOMES = frozenset(("healthy", "unhealthy", "error"))


def safe_readiness_checks(value: object) -> list[dict[str, object]]:
    """Only fixed names, finite durations and outcomes may enter the JSON log."""
    if not isinstance(value, list):
        return []
    checks: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value[:len(CHECK_NAMES)]:
        if not isinstance(item, dict):
            continue
        name, elapsed, result = item.get("name"), item.get("latency_ms"), item.get("result")
        if not isinstance(name, str) or name not in CHECK_NAMES or name in seen:
            continue
        if type(elapsed) not in (float, int) or not 0 <= elapsed < float("inf"):
            continue
        if not isinstance(result, str) or result not in OUTCOMES:
            continue
        checks.append({"name": name, "latency_ms": elapsed, "result": result})
        seen.add(name)
    return checks


@dataclass
class CheckTiming:
    result: str = "error"


class ReadinessDiagnostics:
    def __init__(self) -> None:
        self._started: float | None = None
        try:
            self._started = time.perf_counter()
        except Exception:
            pass
        self._checks: list[dict[str, object]] = []
        self._emitted = False

    @contextmanager
    def check(self, name: str) -> Iterator[CheckTiming]:
        started = None
        try:
            started = time.perf_counter()
        except Exception:
            pass
        timing = CheckTiming()
        try:
            yield timing
        finally:
            # Recording must not replace a check's original value or exception.
            try:
                if started is not None:
                    elapsed = round((time.perf_counter() - started) * 1000, 3)
                    if name in CHECK_NAMES and len(self._checks) < len(CHECK_NAMES) and math.isfinite(elapsed):
                        self._checks.append({"name": name, "latency_ms": elapsed, "result": timing.result})
            except Exception:
                pass

    def emit(self, request_id: str | None, result: str) -> None:
        if self._emitted:
            return
        self._emitted = True
        try:
            if self._started is None:
                return
            logger.info(
                "readiness_diagnostics",
                extra={
                    "request_id": request_id,
                    "latency_ms": round((time.perf_counter() - self._started) * 1000, 3),
                    "result": result if result in OUTCOMES else "error",
                    "readiness_checks": safe_readiness_checks(self._checks),
                },
            )
        except Exception:
            # Do not mask a health result or log recursively when the sink fails.
            pass


class _HealthStatus(Protocol):
    healthy: bool


_Status = TypeVar("_Status", bound=_HealthStatus)


def run_check(
    recorder: ReadinessDiagnostics | None, name: str, callback: Callable[[], _Status],
) -> _Status:
    if recorder is None:
        return callback()
    with recorder.check(name) as timing:
        status = callback()
        timing.result = "healthy" if status.healthy else "unhealthy"
        return status
