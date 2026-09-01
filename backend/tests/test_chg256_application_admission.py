from __future__ import annotations

from hashlib import sha256
import asyncio
import json

import pytest

from app.core.errors import AppError
from app.core.errors import app_error_handler
from app.security.auth import IdentityPrincipal
from app.security.context import application_access_denied_audit_summary
from app.security.permissions import PermissionGrant, has_application_access, require_application_access
from starlette.requests import Request


@pytest.mark.parametrize(
    "allowed_field",
    ["can_view", "can_create", "can_edit", "can_delete", "can_execute"],
)
def test_chg256_any_positive_permission_admits(allowed_field: str) -> None:
    grant = PermissionGrant("Module", "Function", **{allowed_field: True})

    assert has_application_access([grant]) is True
    require_application_access((grant,))


@pytest.mark.parametrize(
    "grants",
    [
        [],
        [PermissionGrant("Module", "Function")],
        [PermissionGrant("One", "Read"), PermissionGrant("Two", "Write")],
    ],
)
def test_chg256_empty_or_all_false_permissions_are_denied(grants: list[PermissionGrant]) -> None:
    assert has_application_access(grants) is False

    with pytest.raises(AppError) as denied:
        require_application_access(grants)

    assert denied.value.status_code == 403
    assert denied.value.code == "application_access_denied"
    assert denied.value.message == "Application access has not been granted"
    assert denied.value.details == {}


def test_chg256_denial_uses_the_api_error_envelope() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/auth/me", "headers": []})
    request.state.request_id = "req-chg256"
    error = AppError(
        "application_access_denied",
        "Application access has not been granted",
        status_code=403,
    )

    response = asyncio.run(app_error_handler(request, error))

    assert response.status_code == 403
    assert json.loads(response.body) == {
        "code": "application_access_denied",
        "message": "Application access has not been granted",
        "details": {},
        "request_id": "req-chg256",
    }


def test_chg256_denial_audit_uses_irreversible_minimal_identity() -> None:
    principal = IdentityPrincipal(
        subject="user02-sensitive-subject",
        employee_id="EMP-02",
        email="user02@example.test",
        display_name="User 02",
        groups=("/ldap/hr",),
        session_id="sensitive-session-id",
        auth_time=0,
        issuer="https://identity.example.test/realms/nomosmart",
    )

    summary = application_access_denied_audit_summary(principal)

    assert summary == {
        "issuer": principal.issuer,
        "subject_fingerprint": sha256(principal.subject.encode("utf-8")).hexdigest(),
        "session_fingerprint": sha256(principal.session_id.encode("utf-8")).hexdigest(),
        "reason": "no_effective_permission",
    }
    serialized = repr(summary)
    assert principal.subject not in serialized
    assert principal.session_id not in serialized
    assert principal.email not in serialized
    assert principal.groups[0] not in serialized
