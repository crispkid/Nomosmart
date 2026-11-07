from __future__ import annotations

import json
import os
import socket
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REQUIRED_LIVE_ENV = (
    "DATABASE_URL",
    "BACKEND_LIVE_BASE_URL",
    "OIDC_ISSUER_URL",
    "OPENSEARCH_URL",
    "NEO4J_URI",
    "CELERY_BROKER_URL",
    "S3_ENDPOINT_URL",
)


def _host_port(url: str, default_port: int | None = None) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise AssertionError(f"{url!r} does not include a host")
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise AssertionError(f"{url!r} includes an invalid port") from exc
    if explicit_port is not None:
        return host, explicit_port
    if default_port is not None:
        return host, default_port
    scheme_port = {"http": 80, "https": 443}.get(parsed.scheme.lower())
    if scheme_port is None:
        raise AssertionError(f"{url!r} does not include a supported scheme or explicit port")
    return host, scheme_port


def _assert_tcp_reachable(name: str, url: str, default_port: int | None = None) -> None:
    host, port = _host_port(url, default_port)
    try:
        with socket.create_connection((host, port), timeout=3):
            return
    except OSError as exc:
        raise AssertionError(f"{name} is not reachable at {host}:{port}") from exc


def _assert_oidc_discovery(issuer_url: str) -> None:
    issuer = issuer_url.rstrip("/")
    parsed_issuer = urlparse(issuer)
    if parsed_issuer.scheme != "https" or not parsed_issuer.hostname:
        raise AssertionError("OIDC issuer must be an absolute HTTPS URL")

    discovery_url = f"{issuer}/.well-known/openid-configuration"
    request = Request(discovery_url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - configured TEST-002 endpoint
            status = response.status
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
            body = response.read(1024 * 1024)
    except Exception as exc:
        raise AssertionError("OIDC discovery failed strict TLS or transport validation") from exc

    if status != 200 or final_url != discovery_url or content_type != "application/json":
        raise AssertionError("OIDC discovery did not return direct HTTP 200 JSON")
    try:
        document = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise AssertionError("OIDC discovery did not return valid JSON") from exc
    if document.get("issuer", "").rstrip("/") != issuer:
        raise AssertionError("OIDC discovery issuer does not exactly match configuration")

    expected_origin = (parsed_issuer.scheme, parsed_issuer.netloc)
    expected_path_prefix = f"{parsed_issuer.path.rstrip('/')}/protocol/openid-connect/"
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        endpoint = urlparse(str(document.get(key) or ""))
        if (endpoint.scheme, endpoint.netloc) != expected_origin or not endpoint.path.startswith(expected_path_prefix):
            raise AssertionError(f"OIDC discovery {key} is outside the configured realm")


def _current_prerequisites():
    from sqlalchemy import select, text
    from app.core.config import get_settings
    from app.db.models import IdentitySetting
    from app.db.session import get_session_factory
    from app.security.auth_configuration import configuration
    from current_live_support import load_current_context

    settings = get_settings()
    current = load_current_context(settings)
    with get_session_factory()() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        setting = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
        assert setting is not None, "Current authentication configuration is required"
        assert configuration(setting).auth_mode == current["auth_mode"]
    values = {
        "PostgreSQL": (settings.database_url.get_secret_value().replace("postgresql+psycopg2://", "postgresql://"), 5432),
        "Backend API": (current["backend_url"], 443),
        "OpenSearch": (settings.opensearch_url, 9200),
        "Neo4j": (settings.neo4j_uri, 7687),
        "Redis/Celery broker": (settings.celery_broker_url, 6379),
        "S3/RustFS": (settings.s3_endpoint_url, 9000),
    }
    assert all(value for value, _ in values.values()), "Current service configuration is incomplete"
    return settings, current, setting, values


def test_live_backend_prerequisites_are_configured() -> None:
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        _current_prerequisites()
        return
    missing = [name for name in REQUIRED_LIVE_ENV if not os.environ.get(name)]
    assert not missing, f"Missing TEST-002 backend live environment variables: {', '.join(missing)}"


def test_live_backend_dependencies_are_reachable() -> None:
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        import ssl
        import httpx
        from app.security.oidc_protocol import metadata_for_settings

        settings, current, setting, values = _current_prerequisites()
        for name, (value, port) in values.items():
            _assert_tcp_reachable(name, value.get_secret_value() if hasattr(value, "get_secret_value") else value, port)
        with httpx.Client(verify=ssl.create_default_context(cafile=current["ca_file"]),
                          trust_env=False, follow_redirects=False, timeout=10) as client:
            response = client.get(current["backend_url"].rstrip("/") + current.get("api_prefix", "/api/v1") + "/auth/config")
            assert response.status_code == 200
            assert response.json()["mode"] == current["auth_mode"]
        if current["auth_mode"] == "oidc":
            # The real relying-party validator enforces configured endpoint
            # policy, TLS, issuer and PKCE without assuming provider URL paths.
            metadata_for_settings(settings, setting)
        return
    missing = [name for name in REQUIRED_LIVE_ENV if not os.environ.get(name)]
    assert not missing, f"Missing TEST-002 backend live environment variables: {', '.join(missing)}"
    values = {name: os.environ[name] for name in REQUIRED_LIVE_ENV}
    _assert_tcp_reachable("PostgreSQL", values["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://"), 5432)
    _assert_tcp_reachable("Backend API", values["BACKEND_LIVE_BASE_URL"], 8000)
    _assert_tcp_reachable("OIDC issuer", values["OIDC_ISSUER_URL"])
    _assert_oidc_discovery(values["OIDC_ISSUER_URL"])
    _assert_tcp_reachable("OpenSearch", values["OPENSEARCH_URL"], 9200)
    _assert_tcp_reachable("Neo4j", values["NEO4J_URI"], 7687)
    _assert_tcp_reachable("Redis/Celery broker", values["CELERY_BROKER_URL"], 6379)
    _assert_tcp_reachable("S3/RustFS", values["S3_ENDPOINT_URL"], 9000)
