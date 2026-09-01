from __future__ import annotations

from pathlib import Path

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
    values = _example_values()

    assert values["OIDC_ISSUER_URL"] == "https://nomosmart.local/identity/realms/nomosmart"
    assert values["KEYCLOAK_ADMIN_API_URL"] == "https://nomosmart.local/identity"
    assert values["OIDC_DISCOVERY_URL"] == ""
    assert values["OIDC_JWKS_URL"] == ""
    assert values["SSL_CERT_FILE"] == "<absolute-path-to-nomosmart-edge-ca.crt>"


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
