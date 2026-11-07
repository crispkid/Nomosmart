"""Offline APP envelope rotation; never imports the HTTP application.

Operator custody and quiescence approval are prerequisites. Credentials arrive
through bounded stdin and the existing DATABASE_URL, never command arguments.
Preview does not authorize an original-environment operation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID

from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, load_only

from app.core.encryption import EnvelopeCipher
from app.core.contracts import AuditAction
from app.core.errors import AppError
from app.db.models import (
    AIModel, AuditLog, ChatFeedbackEvent, DataConnection, IdempotencyKey,
    IdentityReauthFlow, PublicApiRequestLog, SessionExpiredFormDraft,
)
from app.domain.public_api_controls import decrypt_feedback_metadata
from app.services.audit import add_audit


ACTION = AuditAction.APP_ENCRYPTION_ROTATE.value
MAX_RECORDS = 50_000
_GENERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")
_PUBLIC_SCOPES = ("public-chat:", "public-feedback:")
_FIELDS = {
    AIModel: ("id", "name", "api_key_encrypted"),
    DataConnection: ("id", "project_id", "name", "credential_encrypted"),
    IdentityReauthFlow: ("id", "pkce_verifier_encrypted"),
    SessionExpiredFormDraft: ("id", "user_id", "return_path", "form_key", "payload_encrypted"),
    PublicApiRequestLog: (
        "id", "question_encrypted", "answer_encrypted", "citations_encrypted",
        "end_user_metadata_encrypted", "end_user_identity_hash", "end_user_employee_id",
    ),
    ChatFeedbackEvent: (
        "id", "public_response_id", "integration_client_id", "idempotency_key_hash",
        "end_user_metadata_encrypted", "end_user_identity_hash", "end_user_employee_id",
    ),
}
_ENCRYPTED = {
    (model.__tablename__, name) for model, fields in _FIELDS.items()
    for name in fields if name.endswith("_encrypted")
} | {("auth_connection_secrets", "envelope"), ("auth_login_flows", "verifier_ciphertext"),
     ("auth_sessions", "upstream_ciphertext")}


def refusal(code: str) -> AppError:
    return AppError(code, "Application encryption maintenance could not be verified", status_code=409)


def _keys(current: bytes, candidate: bytes, before: str, after: str) -> None:
    if (len(current) != 32 or len(candidate) != 32 or current == bytes(32)
            or candidate == bytes(32) or hmac.compare_digest(current, candidate)
            or not _GENERATION.fullmatch(before) or not _GENERATION.fullmatch(after)
            or before == after):
        raise refusal("app_key_rotation_input_invalid")


def _fingerprint(key: bytes, employee_id: str) -> str:
    return hmac.new(key, ("public-end-user:" + employee_id.strip()).encode(), hashlib.sha256).hexdigest()


@dataclass
class Cell:
    row: object = field(repr=False)
    column: str
    plaintext: str = field(repr=False)
    context: str = field(repr=False)


@dataclass
class RotationPlan:
    cells: list[Cell] = field(default_factory=list, repr=False)
    identities: list[tuple[object, str]] = field(default_factory=list, repr=False)
    expired_public_operations: list[UUID] = field(default_factory=list, repr=False)
    digest: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    source_digest: str = ""

    def summary(self) -> dict:
        return {"inventory_digest": self.digest, "tool_source_digest": self.source_digest, "encrypted_cells": len(self.cells),
                "identity_hashes": len(self.identities), "fields": self.counts,
                "expired_public_replay_rows": len(self.expired_public_operations)}


def _schema(session: Session) -> set[str]:
    catalog = inspect(session.connection())
    tables = set(catalog.get_table_names(schema="public"))
    required = {model.__tablename__ for model in _FIELDS} | {"idempotency_keys", "audit_logs"}
    if not required <= tables:
        raise refusal("app_key_schema_incompatible")
    for table in tables:
        for column in catalog.get_columns(table, schema="public"):
            name = column["name"]
            if (name.endswith(("_encrypted", "_ciphertext")) or name == "envelope") and (table, name) not in _ENCRYPTED:
                raise refusal("app_key_unknown_encrypted_field")
    return tables


def _source_identity() -> str:
    root = Path(__file__).resolve().parents[1]
    names = ("deployment/application_key_rotation.py", "core/encryption.py", "core/contracts.py",
             "domain/public_api_controls.py", "db/models.py")
    content = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _bind_database(session: Session, expected: str) -> None:
    if not expected or session.scalar(text("SELECT current_database()")) != expected:
        raise refusal("app_key_database_mismatch")
    session.execute(text("SET LOCAL lock_timeout = '5s'"))
    session.execute(text("SET LOCAL statement_timeout = '30s'"))
    session.execute(text("SELECT pg_advisory_xact_lock(370, 6)"))


def _auth_independence(session: Session, tables: set[str], keys: dict[str, bytes], current: bytes, candidate: bytes,
                       inventory, budget: int) -> int:
    if "auth_sessions" in tables:
        # Reserved storage has no supported decryption context. Even an empty
        # non-NULL value must block maintenance rather than silently omit it.
        if session.scalar(text('SELECT EXISTS (SELECT 1 FROM auth_sessions WHERE upstream_ciphertext IS NOT NULL)')):
            raise refusal("app_key_unhandled_auth_ciphertext")
        inventory.update(b'["auth_sessions","upstream_ciphertext","all_null"]')
    used = 0
    for table, column in (("auth_connection_secrets", "envelope"), ("auth_login_flows", "verifier_ciphertext")):
        if table not in tables:
            continue
        # Identifiers are closed constants. No dynamic operator SQL is accepted.
        fields = 'id, key_id, envelope, setting_id, purpose' if table == "auth_connection_secrets" else 'id, key_id, verifier_ciphertext'
        rows = session.execute(text(f'SELECT {fields} FROM "{table}" ORDER BY id LIMIT :bound'), {"bound": budget + 1}).mappings()
        for row in rows:
            used += 1
            if used > budget:
                raise refusal("app_key_inventory_limit")
            key = keys.get(row["key_id"])
            if key is None or len(key) != 32 or key in (current, candidate):
                raise refusal("app_key_auth_independence_required")
            if table == "auth_login_flows":
                context = f"auth-flow:{row['id']}"
            else:
                from app.db.models import IdentitySetting
                from app.security.auth_configuration import secret_context
                setting = session.get(IdentitySetting, row["setting_id"])
                if setting is None:
                    raise refusal("app_key_auth_independence_required")
                context = secret_context(setting, row["purpose"])
            EnvelopeCipher(key).decrypt(row[column], context=context)
            inventory.update(json.dumps([table, str(row["id"]), row["key_id"], row[column]], separators=(",", ":")).encode())
    return used


def _plan(session: Session, *, current: bytes, candidate: bytes, before: str, after: str,
          expected_database: str, auth_keys: dict[str, bytes], max_records: int) -> RotationPlan:
    _keys(current, candidate, before, after)
    if type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS:
        raise refusal("app_key_inventory_limit")
    _bind_database(session, expected_database)
    tables = _schema(session)
    affected = {model.__tablename__ for model in _FIELDS} | {"idempotency_keys", "audit_logs"}
    affected |= tables & {"auth_connection_secrets", "auth_login_flows", "auth_sessions", "identity_settings"}
    for table in sorted(affected):
        session.execute(text(f'LOCK TABLE "{table}" IN SHARE ROW EXCLUSIVE MODE'))
    inventory = hashlib.sha256()
    source_digest = _source_identity()
    inventory.update(json.dumps([source_digest, expected_database, before, after, hashlib.sha256(current).hexdigest(),
                                 hashlib.sha256(candidate).hexdigest()], separators=(",", ":")).encode())
    budget = max_records
    budget -= _auth_independence(session, tables, auth_keys, current, candidate, inventory, budget)
    result = RotationPlan(source_digest=source_digest)
    now = session.scalar(text("SELECT clock_timestamp()"))
    public_operations = session.execute(select(IdempotencyKey.id, IdempotencyKey.scope, IdempotencyKey.key,
        IdempotencyKey.expires_at).where(IdempotencyKey.scope.like("public-%")).order_by(IdempotencyKey.id).limit(budget + 1)).all()
    if len(public_operations) > budget:
        raise refusal("app_key_inventory_limit")
    budget -= len(public_operations)
    for operation in public_operations:
        if not operation.scope.startswith(_PUBLIC_SCOPES):
            raise refusal("app_key_replay_scope_unknown")
        if operation.expires_at > now:
            raise refusal("app_key_active_replay_exists")
        result.expired_public_operations.append(operation.id)
        inventory.update(json.dumps(list(operation), default=str, separators=(",", ":")).encode())
    cipher = EnvelopeCipher(current)
    counts = Counter()
    for model, fields in _FIELDS.items():
        attributes = [getattr(model, name) for name in fields]
        rows = list(session.scalars(select(model).options(load_only(*attributes)).order_by(model.id).limit(budget + 1)))
        if len(rows) > budget:
            raise refusal("app_key_inventory_limit")
        budget -= len(rows)
        for row in rows:
            inventory.update(json.dumps([model.__tablename__, {name: getattr(row, name) for name in fields}],
                                        default=str, sort_keys=True, separators=(",", ":")).encode())
            metadata = None
            for column in fields:
                if not column.endswith("_encrypted") or not getattr(row, column):
                    continue
                if model is AIModel:
                    contexts = [f"ai-model:{row.id}", f"ai-model:{row.name}"]
                elif model is DataConnection:
                    contexts = [f"data-source-connection:{row.id}", f"data-source:{row.project_id}:{row.name}"]
                elif model is IdentityReauthFlow:
                    contexts = [f"oidc-reauth:{row.id}"]
                elif model is SessionExpiredFormDraft:
                    contexts = [f"session-draft:{row.user_id}:{row.return_path}:{row.form_key}"]
                elif model is ChatFeedbackEvent:
                    contexts = [f"public-response:{row.public_response_id}:feedback:{row.id}:end-user"]
                else:
                    suffix = {"question_encrypted": "question", "answer_encrypted": "answer",
                              "citations_encrypted": "citations", "end_user_metadata_encrypted": "end-user"}[column]
                    contexts = [f"public-response:{row.id}:{suffix}"]
                if model is ChatFeedbackEvent:
                    plaintext = decrypt_feedback_metadata(session, current, row)
                else:
                    plaintext = None
                    for context in contexts:
                        try:
                            plaintext = cipher.decrypt(getattr(row, column), context=context)
                            break
                        except AppError as exc:
                            if exc.code != "invalid_encrypted_value":
                                raise
                    if plaintext is None:
                        raise refusal("app_key_ciphertext_unrecoverable")
                result.cells.append(Cell(row, column, plaintext, contexts[0]))
                counts[model.__tablename__ + "." + column] += 1
                if column == "end_user_metadata_encrypted":
                    metadata = json.loads(plaintext)
            if model in {PublicApiRequestLog, ChatFeedbackEvent} and row.end_user_identity_hash:
                employee = metadata.get("employee_id") if isinstance(metadata, dict) else row.end_user_employee_id
                if (not isinstance(employee, str) or not employee.strip()
                        or not hmac.compare_digest(row.end_user_identity_hash, _fingerprint(current, employee))):
                    raise refusal("app_key_identity_unrecoverable")
                result.identities.append((row, employee))
    if len(result.cells) > max_records:
        raise refusal("app_key_inventory_limit")
    result.digest = inventory.hexdigest()
    result.counts = dict(counts)
    return result


def preview(engine, **arguments) -> dict:
    with Session(engine) as session, session.begin():
        result = _plan(session, **arguments)
        return {"status": "PREVIEW_ONLY", **result.summary()}


def rotate(engine, *, expected_digest: str, operation_id: UUID, writers_quiesced: bool, **arguments) -> dict:
    if writers_quiesced is not True or not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        raise refusal("app_key_maintenance_prerequisite_missing")
    current, candidate = arguments["current"], arguments["candidate"]
    _keys(current, candidate, arguments["before"], arguments["after"])
    commitment = hashlib.sha256(candidate).hexdigest()
    with Session(engine) as session:
        transaction = session.begin()
        try:
            _bind_database(session, arguments["expected_database"])
            prior = list(session.scalars(select(AuditLog).where(AuditLog.action == ACTION, AuditLog.resource_id == operation_id)))
            if prior:
                if (len(prior) != 1 or prior[0].summary.get("inventory_digest") != expected_digest
                        or prior[0].summary.get("candidate_commitment") != commitment
                        or prior[0].summary.get("to_generation") != arguments["after"]):
                    raise refusal("app_key_operation_conflict")
                transaction.rollback()
                return {"status": "ALREADY_COMMITTED_READBACK", "operation_id": str(operation_id)}
            plan = _plan(session, **arguments)
            if not hmac.compare_digest(plan.digest, expected_digest):
                raise refusal("app_key_inventory_changed")
            cipher = EnvelopeCipher(candidate)
            for cell in plan.cells:
                setattr(cell.row, cell.column, cipher.encrypt(cell.plaintext, context=cell.context))
                # Each actual SQL update remains in this one transaction.
                session.flush()
                session.refresh(cell.row, attribute_names=[cell.column])
                envelope = getattr(cell.row, cell.column)
                if cipher.decrypt(envelope, context=cell.context) != cell.plaintext:
                    raise refusal("app_key_postwrite_verification_failed")
                try:
                    EnvelopeCipher(current).decrypt(envelope, context=cell.context)
                except AppError as exc:
                    if exc.code != "invalid_encrypted_value":
                        raise
                else:
                    raise refusal("app_key_previous_generation_still_valid")
            for row, employee in plan.identities:
                row.end_user_identity_hash = _fingerprint(candidate, employee)
            session.flush()
            for row, employee in plan.identities:
                session.refresh(row, attribute_names=["end_user_identity_hash"])
                if not hmac.compare_digest(row.end_user_identity_hash, _fingerprint(candidate, employee)):
                    raise refusal("app_key_postwrite_verification_failed")
            if plan.expired_public_operations:
                session.execute(delete(IdempotencyKey).where(IdempotencyKey.id.in_(plan.expired_public_operations),
                    IdempotencyKey.expires_at <= datetime.now(UTC)))
            summary = {**plan.summary(), "database": arguments["expected_database"],
                       "from_generation": arguments["before"], "to_generation": arguments["after"],
                       "candidate_commitment": commitment}
            add_audit(session, actor_user_id=None, action=ACTION, resource_type="application_encryption",
                      resource_id=operation_id, result="success", request_id=str(operation_id), summary=summary)
            session.flush()
            try:
                transaction.commit()
            except DBAPIError as exc:
                raise refusal("app_key_commit_outcome_unknown") from exc
            return {"status": "COMMITTED_REQUIRES_CONSUMER_VERIFICATION", "operation_id": str(operation_id), **plan.summary()}
        except Exception:
            session.rollback()
            raise


def inspect_operation(engine, *, expected_database: str, operation_id: UUID) -> dict:
    """Read an uncertain commit only after the previous maintenance lock ends."""
    with Session(engine) as session, session.begin():
        _bind_database(session, expected_database)
        rows = list(session.scalars(select(AuditLog).where(AuditLog.action == ACTION, AuditLog.resource_id == operation_id)))
        if len(rows) > 1:
            raise refusal("app_key_operation_conflict")
        if not rows:
            return {"status": "NOT_COMMITTED_READBACK", "operation_id": str(operation_id)}
        fields = ("inventory_digest", "tool_source_digest", "encrypted_cells", "identity_hashes", "fields", "expired_public_replay_rows")
        return {"status": "COMMITTED_READBACK_REQUIRES_CONSUMER_VERIFICATION", "operation_id": str(operation_id),
                **{name: rows[0].summary[name] for name in fields}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "apply", "inspect"))
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--writers-quiesced", action="store_true")
    args = parser.parse_args()
    engine = None
    try:
        raw = sys.stdin.buffer.read(16_385)
        if len(raw) > 16_384:
            raise refusal("app_key_rotation_input_invalid")
        payload = json.loads(raw)
        if args.command == "inspect":
            if not isinstance(payload, dict) or set(payload) != {"operation_id"}:
                raise refusal("app_key_rotation_input_invalid")
            engine = create_engine(os.environ["DATABASE_URL"], hide_parameters=True, connect_args={"connect_timeout": 5})
            print(json.dumps(inspect_operation(engine, expected_database=args.expected_database,
                                               operation_id=UUID(payload["operation_id"])), sort_keys=True))
            return 0
        required = {"current", "candidate", "before", "after", "auth_keys"}
        allowed = required | {"expected_digest", "operation_id"}
        if not isinstance(payload, dict) or not required <= payload.keys() or not set(payload) <= allowed:
            raise refusal("app_key_rotation_input_invalid")
        keys = {name: bytes.fromhex(payload[name]) for name in ("current", "candidate")}
        auth_keys = {name: bytes.fromhex(value) for name, value in payload["auth_keys"].items()}
        arguments = {**keys, "before": payload["before"], "after": payload["after"],
                     "auth_keys": auth_keys, "expected_database": args.expected_database, "max_records": MAX_RECORDS}
        engine = create_engine(os.environ["DATABASE_URL"], hide_parameters=True, connect_args={"connect_timeout": 5})
        if args.command == "preview":
            result = preview(engine, **arguments)
        else:
            result = rotate(engine, **arguments, expected_digest=payload["expected_digest"],
                            operation_id=UUID(payload["operation_id"]), writers_quiesced=args.writers_quiesced)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        unknown = isinstance(exc, AppError) and exc.code == "app_key_commit_outcome_unknown"
        print(json.dumps({"status": "OUTCOME_UNKNOWN_READBACK_REQUIRED" if unknown else "REFUSED_OR_FAILED", "code": exc.code if isinstance(exc, AppError)
                          else "app_key_rotation_failed"}), file=sys.stderr)
        return 2 if unknown else 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
