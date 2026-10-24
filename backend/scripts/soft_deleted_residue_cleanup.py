"""One explicit maintenance command; all input including tokens uses stdin.

Run with `python -m scripts.soft_deleted_residue_cleanup COMMAND`. Config is the
normal typed runtime config. No arguments can disable authentication or fencing.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import DocumentVersion, IdentitySetting
from app.db.session import get_session_factory
from app.domain.soft_deleted_residue_cleanup import KEY, Scope, digest, execute_cleanup, inspect_cleanup, plan_cleanup, verify_retirement
from app.security.auth import build_identity_jwt_validator, is_token_revoked
from app.security.context import resolve_identity_context
from app.security.permissions import require_application_access


def authenticate(session, settings, token):
    if not isinstance(token, str) or not token:
        raise AppError("authentication_required", "Bearer access token is required", status_code=401)
    current = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
    principal = build_identity_jwt_validator(settings, current.configuration if current else {}).validate(token)
    if is_token_revoked(session, principal, token):
        raise AppError("token_revoked", "Access token has been revoked", status_code=401)
    context = resolve_identity_context(session, principal)
    require_application_access(context.grants)
    return context


def command(name, payload):
    settings = get_settings()
    scope = Scope.parse(payload["scope"])
    with get_session_factory()() as session:
        context = authenticate(session, settings, payload.pop("access_token", None))
        if name == "inspect":
            result = inspect_cleanup(session, settings, scope, context)
            session.rollback()
            return {"manifest": result, "manifest_sha256": digest(result), "data_writes": 0}
        if name == "plan":
            return plan_cleanup(session, settings, scope, context, manifest=payload["manifest"],
                plan_sha256=payload["plan_sha256"], idempotency_key=UUID(payload["idempotency_key"]))
        if name == "execute":
            return execute_cleanup(session, settings, scope, context, run_id=UUID(payload["run_id"]),
                manifest_sha256=payload["manifest_sha256"], plan_sha256=payload["plan_sha256"])
        if name == "verify":
            version = session.get(DocumentVersion, scope.version_id)
            run = (version.chunk_strategy or {}).get(KEY) if version else None
            if not run or run["run_id"] != payload["run_id"]:
                raise AppError("soft_residue_run_not_found", "Maintenance run was not found", status_code=404)
            result = verify_retirement(session, settings, scope, context, run)
            session.rollback()
            return result
        raise AppError("soft_residue_unknown_command", "Unsupported maintenance command", status_code=422)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "plan", "execute", "verify"))
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        # Input is bounded and is never written to disk or included in errors.
        raw = sys.stdin.buffer.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError("bounded_input")
        payload = json.loads(raw)
        raw = b""
        result = command(args.command, payload)
        print(json.dumps({"status": "PASS", "result": result}, default=str))
        return 0
    except Exception as error:
        print(json.dumps({"status": "FAIL", "code": getattr(error, "code", "soft_residue_command_failed"),
            "error_type": type(error).__name__, "http_status": getattr(error, "status_code", None)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
