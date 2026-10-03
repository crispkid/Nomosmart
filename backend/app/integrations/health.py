from __future__ import annotations

import socket
from dataclasses import dataclass
import json
from urllib.parse import urlparse

import httpx
from sqlalchemy import create_engine, text

from app.core.config import Settings, create_neo4j_driver
from app.core.readiness_diagnostics import ReadinessDiagnostics, run_check
from app.integrations.redis_ha import redis_client
from app.integrations.s3_storage import S3ObjectStorage
from app.services.identity_sync_jobs import identity_runtime_status


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    healthy: bool
    detail: str

    @property
    def status(self) -> str:
        return "healthy" if self.healthy else "unavailable"




def _redis_status(name: str, settings: Settings, url: str) -> DependencyStatus:
    client = None
    try:
        client = redis_client(settings, url=url, socket_timeout=2)
        if client.ping() is not True:
            return DependencyStatus(name, False, "sentinel_primary_not_ready")
        return DependencyStatus(name, True, "sentinel_primary_ready")
    except Exception:
        return DependencyStatus(name, False, "unavailable")
    finally:
        if client is not None:
            client.close()


def _s3_status(settings: Settings) -> DependencyStatus:
    try:
        status = S3ObjectStorage(settings).bucket_status(settings.s3_bucket)
        if status != "existing":
            return DependencyStatus("s3", False, "required_bucket_missing")
        return DependencyStatus("s3", True, "required_bucket_ready")
    except Exception:  # sanitized at this boundary
        return DependencyStatus("s3", False, "unavailable")


def _opensearch_status(settings: Settings) -> DependencyStatus:
    try:
        response = httpx.get(
            f"{settings.opensearch_url.rstrip('/')}/_cluster/health",
            auth=(
                settings.opensearch_username.get_secret_value(),
                settings.opensearch_password.get_secret_value(),
            ),
            timeout=2,
            verify=settings.opensearch_httpx_verify,
        )
        if response.status_code >= 400:
            return DependencyStatus("opensearch", False, "cluster_health_rejected")
        payload = response.json()
        status = payload.get("status") if isinstance(payload, dict) else None
        if status not in {"green", "yellow"}:
            return DependencyStatus("opensearch", False, "cluster_not_ready")
        return DependencyStatus("opensearch", True, "cluster_ready")
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return DependencyStatus("opensearch", False, "unavailable")


def _neo4j_status(settings: Settings) -> DependencyStatus:
    driver = None
    try:
        driver = create_neo4j_driver(settings, connection_timeout=2)
        driver.verify_connectivity()
        with driver.session(database=settings.neo4j_database) as session:
            record = session.run("RETURN 1 AS ready").single()
        if record is None or record.get("ready") != 1:
            return DependencyStatus("neo4j", False, "query_not_ready")
        return DependencyStatus("neo4j", True, "query_ready")
    except Exception:  # sanitized at this boundary
        return DependencyStatus("neo4j", False, "unavailable")
    finally:
        if driver is not None:
            driver.close()


def _keycloak_status(settings: Settings) -> DependencyStatus:
    try:
        response = httpx.get(settings.oidc_discovery_endpoint, timeout=2)
        if response.status_code != 200:
            return DependencyStatus("keycloak", False, "discovery_rejected")
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("issuer") or not payload.get("jwks_uri"):
            return DependencyStatus("keycloak", False, "discovery_invalid")
        return DependencyStatus("keycloak", True, "discovery_ready")
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return DependencyStatus("keycloak", False, "unavailable")


def _worker_status(settings: Settings) -> DependencyStatus:
    runtime = identity_runtime_status(settings)
    return DependencyStatus(
        "celery_worker",
        bool(runtime["worker_available"]),
        "heartbeat_current" if runtime["worker_available"] else "heartbeat_missing",
    )


def _postgresql_status(settings: Settings) -> DependencyStatus:
    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return DependencyStatus("postgresql", True, "reachable")
    except Exception:  # sanitized at this boundary
        return DependencyStatus("postgresql", False, "unreachable")
    finally:
        engine.dispose()


def check_dependencies(settings: Settings, *, recorder: ReadinessDiagnostics | None = None) -> list[DependencyStatus]:
    checks = (
        ("postgresql", lambda: _postgresql_status(settings)),
        ("redis", lambda: _redis_status("redis", settings, settings.redis_url.get_secret_value())),
        ("celery_broker", lambda: _redis_status("celery_broker", settings, settings.celery_broker_url.get_secret_value())),
        ("celery_result_backend", lambda: _redis_status("celery_result_backend", settings, settings.celery_result_backend.get_secret_value())),
        ("s3", lambda: _s3_status(settings)),
        ("opensearch", lambda: _opensearch_status(settings)),
        ("neo4j", lambda: _neo4j_status(settings)),
        ("keycloak", lambda: _keycloak_status(settings)),
        ("celery_worker", lambda: _worker_status(settings)),
    )
    return [run_check(recorder, name, callback) for name, callback in checks]
