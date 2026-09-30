"""Authenticated local maintenance command; no public settings-write API.

Run with deployment bootstrap configuration already supplied. Private stdin JSON:
{"access_token": "...", "changes": {...}}. Never pass tokens on the command line.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import IdentitySetting
from app.db.session import get_session_factory
from app.domain.file_processing_settings import (ACTIVE_KEYS, DEPRECATED_KEYS, PlatformCapabilities, authorize_maintenance,
    initialize_policy, load_policy, policy_error, update_policy)
from app.security.auth import build_identity_jwt_validator, is_token_revoked
from app.services.audit import add_audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("read", "initialize", "update"))
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--deployment-id", type=UUID)
    parser.add_argument("--capabilities-file", type=Path,
                        help="Optional local deployment ceilings, not DB-policy overrides")
    args = parser.parse_args()
    actor = None
    factory = get_session_factory()
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise policy_error("file_processing_cli_input_limit", 422)
        payload = json.loads(raw)
        if type(payload) is not dict or set(payload) - {"access_token", "changes"}:
            raise policy_error("file_processing_cli_input_invalid", 422)
        token = payload.get("access_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 32768:
            raise policy_error("authentication_required", 401)
        cap_bytes = args.capabilities_file.read_bytes() if args.capabilities_file else b"{}"
        if len(cap_bytes) > 8192:
            raise policy_error("file_processing_capability_invalid")
        capabilities = PlatformCapabilities(json.loads(cap_bytes))
        settings = get_settings()
        with factory.begin() as session:
            identity = session.scalar(select(IdentitySetting).where(IdentitySetting.is_current.is_(True)))
            validator = build_identity_jwt_validator(settings, identity.configuration if identity else {})
            principal = validator.validate(token)
            if is_token_revoked(session, principal, token):
                raise policy_error("token_revoked", 401)
            actor = authorize_maintenance(session, principal, write=args.operation != "read")
            if args.operation == "initialize":
                if args.deployment_id is None or args.expected_revision != 0 or payload.get("changes"):
                    raise policy_error("file_processing_initialization_contract_invalid", 422)
                snapshot = initialize_policy(session, principal=principal, deployment_id=args.deployment_id,
                    legacy_timeout_seconds=settings.tesseract_timeout_seconds, legacy_max_pages=settings.tesseract_max_pages,
                    legacy_upload_mib=settings.max_upload_size_mb, capabilities=capabilities)
            elif args.operation == "update":
                snapshot = update_policy(session, principal=principal, expected_revision=args.expected_revision,
                    changes=payload.get("changes"), capabilities=capabilities)
            else:
                if payload.get("changes"):
                    raise policy_error("file_processing_cli_input_invalid", 422)
                snapshot = load_policy(session)
                capabilities.validate(snapshot.settings)
        print(json.dumps({"revision": snapshot.revision, "content_hash": snapshot.settings.content_hash,
                          "active_keys": sorted(ACTIVE_KEYS), "deprecated_read_only_keys": sorted(DEPRECATED_KEYS),
                          "values": snapshot.settings.model_dump(mode="json")}, sort_keys=True))
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, AppError) else "file_processing_maintenance_failed"
        # Failure audit is independent of the rolled-back settings transaction.
        if actor is not None:
            try:
                with factory.begin() as session:
                    add_audit(session, actor_user_id=actor, action="file_processing.policy.rejected",
                        resource_type="file_processing_policy", resource_id=None, result="denied", request_id=None,
                        summary={"safe_error_code": code, "operation": args.operation})
            except Exception:
                code = "file_processing_rejection_audit_unavailable"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
