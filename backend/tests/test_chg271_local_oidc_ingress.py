from __future__ import annotations

from pathlib import Path
import json
from urllib.parse import urlparse

import pytest

from test_live_prerequisites import _host_port


ROOT = Path(__file__).resolve().parents[2]


def _example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / "backend" / ".env.example").read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_chg271_safe_example_uses_existing_https_keycloak_ingress() -> None:
    # Keep the original case identity; PROTAUTH-011 supersedes the bundled
    # provider URL with an explicit, protocol-oriented bootstrap configuration.
    from app.security.auth_configuration import ProtocolConfiguration
    values = _example_values()
    assert not any(name.startswith("KEYCLOAK_") for name in values)
    for name in ("OIDC_ISSUER_URL", "OIDC_DISCOVERY_URL", "OIDC_JWKS_URL"):
        assert not values.get(name)
    assert values["AUTH_BOOTSTRAP_CONFIGURATION"] == "<absolute-path-to-non-secret-bootstrap-json>"
    assert values["SSL_CERT_FILE"] == "<absolute-path-to-required-ca-bundle.crt>"
    example = json.loads((ROOT / "deploy/docker/auth-bootstrap.oidc.example.json").read_text())
    config = ProtocolConfiguration.model_validate(example["configuration"])
    assert config.auth_mode == "oidc" and config.oidc is not None
    issuer = urlparse(config.oidc.issuer)
    assert issuer.scheme == "https" and issuer.hostname == "login.example.invalid"
    assert issuer.hostname in values["AUTH_ENDPOINT_ALLOWED_HOSTS"].split(",")
    assert config.directory.endpoints == ["ldaps://directory.example.invalid:636"]


@pytest.mark.parametrize(
    ("url", "expected"),
    (
        ("https://nomosmart.local/identity/realms/nomosmart", ("nomosmart.local", 443)),
        ("http://127.0.0.1/path", ("127.0.0.1", 80)),
        ("https://identity.example.test:9443/realms/example", ("identity.example.test", 9443)),
    ),
)
def test_chg271_host_port_uses_scheme_or_explicit_port(url: str, expected: tuple[str, int]) -> None:
    assert _host_port(url) == expected


def test_chg271_service_specific_default_remains_available() -> None:
    assert _host_port("postgresql://database.example.test/nomosmart", 5432) == (
        "database.example.test",
        5432,
    )


@pytest.mark.parametrize("url", ("/relative/path", "ftp://identity.example.test/path", "https://identity.example.test:invalid/path"))
def test_chg271_invalid_host_scheme_or_port_fails_closed(url: str) -> None:
    with pytest.raises(AssertionError):
        _host_port(url)
