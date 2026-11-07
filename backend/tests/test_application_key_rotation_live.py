"""Real PostgreSQL/AES maintenance state tests, not Provider or login evidence.

The existing dedicated DB/owner/TLS lease is mandatory. No successful pipeline,
signed token, adapter response or old acceptance receipt is manufactured.
"""
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import make_url

from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import (
    AIModel, AuditLog, ChatFeedbackEvent, DataConnection, IdempotencyKey, IntegrationClient,
    IdentityReauthFlow, Project, PublicApiRequestLog, SessionExpiredFormDraft,
)
from app.deployment.application_key_rotation import ACTION, inspect_operation, preview, rotate
from chg305_support import live_db


def fingerprint(key, employee):
    return hmac.new(key, ("public-end-user:" + employee).encode(), hashlib.sha256).hexdigest()


def snapshot(db):
    with db["factory"]() as session:
        values = []
        for model, names in [
            (AIModel, ("api_key_encrypted",)), (DataConnection, ("credential_encrypted",)),
            (IdentityReauthFlow, ("pkce_verifier_encrypted",)), (SessionExpiredFormDraft, ("payload_encrypted",)),
            (PublicApiRequestLog, ("question_encrypted", "answer_encrypted", "citations_encrypted", "end_user_metadata_encrypted", "end_user_identity_hash")),
            (ChatFeedbackEvent, ("end_user_metadata_encrypted", "end_user_identity_hash")),
        ]:
            values.extend((model.__tablename__, str(row.id), name, hashlib.sha256(str(getattr(row, name)).encode()).hexdigest())
                          for row in session.scalars(select(model).order_by(model.id)) for name in names)
        values.extend(("idempotency_keys", str(row.id), "scope", hashlib.sha256((row.scope + row.key + str(row.expires_at)).encode()).hexdigest())
                      for row in session.scalars(select(IdempotencyKey).order_by(IdempotencyKey.id)))
        return values


@pytest.fixture
def rotation_inputs(live_db):
    db = live_db
    old, new = secrets.token_bytes(32), secrets.token_bytes(32)
    cipher = EnvelopeCipher(old)
    now = datetime.now(UTC)
    ids = {name: uuid4() for name in ("project", "client", "model1", "model2", "connection", "flow", "draft", "log", "feedback", "operation")}
    prefix = "chg370-app-key-" + uuid4().hex
    employee = prefix
    person = json.dumps({"employee_id": employee, "employee_name": "Cryptographic state input"})
    with db["factory"].begin() as session:
        session.add(Project(id=ids["project"], name=prefix, created_by=db["actor"]))
        session.add(IntegrationClient(id=ids["client"], name=prefix, api_key_hash=secrets.token_hex(32), api_key_prefix="state-input"))
        session.flush()
        session.add_all([
            AIModel(id=ids["model1"], name=prefix + "-uuid", model_type="Embedding", provider="Custom",
                    api_key_encrypted=cipher.encrypt("first credential input", context=f"ai-model:{ids['model1']}")),
            AIModel(id=ids["model2"], name=prefix + "-legacy", model_type="Chat", provider="Custom",
                    api_key_encrypted=cipher.encrypt("second credential input", context=f"ai-model:{prefix}-legacy")),
            DataConnection(id=ids["connection"], project_id=ids["project"], name=prefix, service_type="FTP", schedule_mode="manual",
                           credential_encrypted=cipher.encrypt("connection credential input", context=f"data-source:{ids['project']}:{prefix}")),
            IdentityReauthFlow(id=ids["flow"], user_id=db["actor"], subject=prefix, session_id=prefix, scope="maintenance-state",
                state_digest=secrets.token_hex(32), nonce_digest=secrets.token_hex(32),
                pkce_verifier_encrypted=cipher.encrypt("verifier input", context=f"oidc-reauth:{ids['flow']}"),
                issuer_url="https://state-input.example.invalid", jwks_url="https://state-input.example.invalid/jwks",
                client_id=prefix, redirect_uri="https://state-input.example.invalid/callback", return_path="/projects",
                created_at=now, expires_at=now + timedelta(minutes=5)),
            SessionExpiredFormDraft(id=ids["draft"], user_id=db["actor"], form_key=prefix, return_path="/projects",
                nonce_hash=secrets.token_hex(32), payload_encrypted=cipher.encrypt('{"field":"private draft input"}',
                context=f"session-draft:{db['actor']}:/projects:{prefix}"), created_at=now, expires_at=now + timedelta(minutes=5)),
            # Failed, non-generated log storage input; no model usage or answer success receipt.
            PublicApiRequestLog(id=ids["log"], integration_client_id=ids["client"], project_id=ids["project"],
                endpoint="maintenance-state", response_mode="json", result="failed", http_status=503,
                lifecycle_status="failed", end_user_employee_id="", end_user_identity_hash=fingerprint(old, employee),
                question_encrypted=cipher.encrypt('"question storage input"', context=f"public-response:{ids['log']}:question"),
                answer_encrypted=cipher.encrypt('"answer storage input; no Provider result"', context=f"public-response:{ids['log']}:answer"),
                citations_encrypted=cipher.encrypt('[]', context=f"public-response:{ids['log']}:citations"),
                end_user_metadata_encrypted=cipher.encrypt(person, context=f"public-response:{ids['log']}:end-user"), created_at=now),
            # Expired native SQL state input, not a claim that an HTTP TTL elapsed.
            IdempotencyKey(id=ids["operation"], scope=f"public-feedback:{ids['client']}:{ids['log']}", key=secrets.token_hex(32),
                request_hash=secrets.token_hex(32), status="failed", created_at=now - timedelta(hours=2), expires_at=now - timedelta(hours=1)),
        ])
        session.flush()
        operation = session.get(IdempotencyKey, ids["operation"])
        session.add(ChatFeedbackEvent(id=ids["feedback"], project_id=ids["project"], public_response_id=ids["log"], source="api",
            feedback_value="needs_revision", integration_client_id=ids["client"], end_user_identity_hash=fingerprint(old, employee),
            idempotency_key_hash=operation.key, end_user_metadata_encrypted=cipher.encrypt(person,
                context=f"public-response:{ids['log']}:feedback:{ids['operation']}:end-user"), created_at=now))
    args = dict(current=old, candidate=new, before="generation-one", after="generation-two",
                expected_database=db["engine"].url.database, auth_keys={}, max_records=5000)
    if os.environ.get("NOMOSMART_CURRENT_LIVE_CONTEXT"):
        from app.core.config import get_settings
        from current_live_support import PrivateContext
        settings = get_settings()
        # The owned copy retains real independent AUTH envelopes. The actual
        # preview verifies them, while rotating only these new APP test inputs.
        # Keep key material out of fixture representations and public receipts.
        args = PrivateContext(args)
        args["auth_keys"] = PrivateContext({
            settings.auth_encryption_key_id: settings.auth_encryption_key_bytes,
        })
    try:
        yield db, args, ids, employee
    finally:
        with db["factory"].begin() as session:
            for model, key in [(ChatFeedbackEvent, "feedback"), (PublicApiRequestLog, "log"), (IdempotencyKey, "operation"),
                (IdentityReauthFlow, "flow"), (SessionExpiredFormDraft, "draft"), (DataConnection, "connection"),
                (AIModel, "model1"), (AIModel, "model2"), (IntegrationClient, "client"), (Project, "project")]:
                session.execute(delete(model).where(model.id == ids[key]))


def test_preview_is_read_only_and_contains_no_secret_or_caller_metadata(rotation_inputs):
    db, args, ids, employee = rotation_inputs
    before = snapshot(db)
    result = preview(db["engine"], **args)
    assert result["status"] == "PREVIEW_ONLY" and result["encrypted_cells"] == 10
    assert result["identity_hashes"] == 2 and result["expired_public_replay_rows"] == 1
    assert snapshot(db) == before
    serialized = json.dumps(result)
    assert employee not in serialized and args["current"].hex() not in serialized and args["candidate"].hex() not in serialized


def test_reseal_duplicate_readback_and_reverse_preserve_plaintext(rotation_inputs):
    db, args, ids, employee = rotation_inputs
    before = preview(db["engine"], **args)
    operation = uuid4()
    result = rotate(db["engine"], **args, expected_digest=before["inventory_digest"], operation_id=operation, writers_quiesced=True)
    assert result["status"] == "COMMITTED_REQUIRES_CONSUMER_VERIFICATION"
    after = snapshot(db)
    assert rotate(db["engine"], **args, expected_digest=before["inventory_digest"], operation_id=operation,
                  writers_quiesced=True)["status"] == "ALREADY_COMMITTED_READBACK"
    assert snapshot(db) == after
    assert inspect_operation(db["engine"], expected_database=args["expected_database"], operation_id=operation)["status"].startswith("COMMITTED_READBACK")
    with db["factory"]() as session:
        assert session.get(IdempotencyKey, ids["operation"]) is None
        event = session.get(ChatFeedbackEvent, ids["feedback"])
        plaintext = EnvelopeCipher(args["candidate"]).decrypt(event.end_user_metadata_encrypted,
            context=f"public-response:{ids['log']}:feedback:{ids['feedback']}:end-user")
        assert json.loads(plaintext)["employee_id"] == employee
        assert event.end_user_identity_hash == fingerprint(args["candidate"], employee)
        assert session.scalar(select(AuditLog.id).where(AuditLog.action == ACTION, AuditLog.resource_id == operation))
    reverse = {**args, "current": args["candidate"], "candidate": args["current"], "before": args["after"], "after": args["before"]}
    inspected = preview(db["engine"], **reverse)
    assert inspected["encrypted_cells"] == 10 and inspected["expired_public_replay_rows"] == 0
    assert rotate(db["engine"], **reverse, expected_digest=inspected["inventory_digest"], operation_id=uuid4(),
                  writers_quiesced=True)["status"].startswith("COMMITTED")
    with db["factory"]() as session:
        assert EnvelopeCipher(args["current"]).decrypt(session.get(AIModel, ids["model1"]).api_key_encrypted,
            context=f"ai-model:{ids['model1']}") == "first credential input"
    with pytest.raises(AppError, match="maintenance could not"):
        preview(db["engine"], **reverse)


def test_unexpired_replay_blocks_without_writes(rotation_inputs):
    db, args, ids, _ = rotation_inputs
    with db["factory"].begin() as session:
        session.get(IdempotencyKey, ids["operation"]).expires_at = datetime.now(UTC) + timedelta(hours=1)
    before = snapshot(db)
    with pytest.raises(AppError) as error:
        preview(db["engine"], **args)
    assert error.value.code == "app_key_active_replay_exists" and snapshot(db) == before


def test_actual_model_and_connection_readers_use_the_new_generation(rotation_inputs):
    from pydantic import SecretStr
    from app.core.config import get_settings
    from app.domain.model_credentials import resolve_model_credential
    from app.domain.data_sync import _decrypted_credential
    db, args, ids, _ = rotation_inputs
    inspected = preview(db["engine"], **args)
    rotate(db["engine"], **args, expected_digest=inspected["inventory_digest"], operation_id=uuid4(), writers_quiesced=True)
    old = get_settings().model_copy(update={"app_env": "test", "app_encryption_key": SecretStr(args["current"].hex())})
    new = old.model_copy(update={"app_encryption_key": SecretStr(args["candidate"].hex())})
    with db["factory"]() as session:
        model = session.get(AIModel, ids["model1"])
        connection = session.get(DataConnection, ids["connection"])
        assert resolve_model_credential(new, model) == "first credential input"
        assert _decrypted_credential(new, connection) == "connection credential input"
        with pytest.raises(AppError):
            resolve_model_credential(old, model)
        with pytest.raises(AppError):
            _decrypted_credential(old, connection)


def test_missing_legacy_feedback_context_blocks_without_writes(rotation_inputs):
    db, args, ids, _ = rotation_inputs
    with db["factory"].begin() as session:
        session.execute(delete(IdempotencyKey).where(IdempotencyKey.id == ids["operation"]))
    before = snapshot(db)
    with pytest.raises(AppError) as error:
        preview(db["engine"], **args)
    assert error.value.code == "feedback_encryption_context_unavailable" and snapshot(db) == before


def test_preview_digest_drift_blocks_before_reseal(rotation_inputs):
    db, args, ids, _ = rotation_inputs
    before = preview(db["engine"], **args)
    with db["factory"].begin() as session:
        session.get(AIModel, ids["model1"]).api_key_encrypted = EnvelopeCipher(args["current"]).encrypt(
            "changed native input", context=f"ai-model:{ids['model1']}")
    changed = snapshot(db)
    with pytest.raises(AppError) as error:
        rotate(db["engine"], **args, expected_digest=before["inventory_digest"], operation_id=uuid4(), writers_quiesced=True)
    assert error.value.code == "app_key_inventory_changed" and snapshot(db) == changed


def test_unknown_encrypted_column_refuses_before_writes(rotation_inputs):
    db, args, _, _ = rotation_inputs
    table = "chg370_cipher_probe_" + uuid4().hex
    before = snapshot(db)
    with db["engine"].begin() as connection:
        connection.execute(text(f'CREATE TABLE "{table}" (id integer PRIMARY KEY, payload_encrypted text)'))
    try:
        with pytest.raises(AppError) as error:
            preview(db["engine"], **args)
        assert error.value.code == "app_key_unknown_encrypted_field" and snapshot(db) == before
    finally:
        with db["engine"].begin() as connection:
            connection.execute(text(f'DROP TABLE "{table}"'))  # Exact new native fault-control object only.


def test_actual_second_sql_update_failure_rolls_back_every_cell(rotation_inputs):
    db, args, ids, _ = rotation_inputs
    inspected = preview(db["engine"], **args)
    suffix = "app_rotation_" + uuid4().hex
    operation = uuid4()
    before = snapshot(db)
    with db["engine"].begin() as connection:
        connection.execute(text(f'CREATE SEQUENCE current_test_control."{suffix}"'))
        connection.execute(text(f'''CREATE FUNCTION current_test_control."{suffix}"() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.id IN ('{ids['model1']}'::uuid, '{ids['model2']}'::uuid)
                AND NEW.api_key_encrypted IS DISTINCT FROM OLD.api_key_encrypted
                AND nextval('current_test_control.{suffix}') >= 2 THEN
                RAISE EXCEPTION 'owned_app_rotation_atomic_control'; END IF; RETURN NEW; END $$'''))
        connection.execute(text(f'CREATE TRIGGER "{suffix}" BEFORE UPDATE ON ai_models FOR EACH ROW EXECUTE FUNCTION current_test_control."{suffix}"()'))
    try:
        with pytest.raises(DBAPIError):
            rotate(db["engine"], **args, expected_digest=inspected["inventory_digest"], operation_id=operation, writers_quiesced=True)
        with db["engine"].connect() as connection:
            assert connection.scalar(text(f'SELECT last_value FROM current_test_control."{suffix}"')) >= 2
        assert snapshot(db) == before
        assert inspect_operation(db["engine"], expected_database=args["expected_database"], operation_id=operation)["status"] == "NOT_COMMITTED_READBACK"
    finally:
        with db["engine"].begin() as connection:
            connection.execute(text(f'DROP TRIGGER "{suffix}" ON ai_models'))
            connection.execute(text(f'DROP FUNCTION current_test_control."{suffix}"()'))
            connection.execute(text(f'DROP SEQUENCE current_test_control."{suffix}"'))


def test_unrecoverable_identity_and_missing_quiescence_are_zero_write(rotation_inputs):
    db, args, ids, _ = rotation_inputs
    inspected = preview(db["engine"], **args)
    before = snapshot(db)
    with pytest.raises(AppError) as error:
        rotate(db["engine"], **args, expected_digest=inspected["inventory_digest"], operation_id=uuid4(), writers_quiesced=False)
    assert error.value.code == "app_key_maintenance_prerequisite_missing" and snapshot(db) == before
    with db["factory"].begin() as session:
        session.get(PublicApiRequestLog, ids["log"]).end_user_identity_hash = secrets.token_hex(32)
    controlled = snapshot(db)
    with pytest.raises(AppError) as error:
        preview(db["engine"], **args)
    assert error.value.code == "app_key_identity_unrecoverable" and snapshot(db) == controlled


def test_current_auth_envelopes_require_independent_verified_keys():
    from contextlib import ExitStack
    from app.core.config import get_settings
    from current_live_support import load_current_context, CurrentLive
    context = load_current_context()
    settings = get_settings()
    arguments = dict(current=settings.encryption_key_bytes, candidate=secrets.token_bytes(32),
                     before="current-owned", after="candidate-owned", expected_database=make_url(context['database_url']).database, max_records=5000)
    # This uses the actual current owned AUTH envelopes and public replay rows.
    # Preview locks/reads only; original environments are outside its authority.
    with ExitStack() as stack, CurrentLive(context, stack).database() as session:
        engine = session.get_bind()
        with pytest.raises(AppError) as error:
            preview(engine, **arguments, auth_keys={})
        assert error.value.code == "app_key_auth_independence_required"
        with pytest.raises(AppError) as error:
            preview(engine, **arguments, auth_keys={settings.auth_encryption_key_id: settings.auth_encryption_key_bytes})
        assert error.value.code == "app_key_active_replay_exists"


@pytest.mark.parametrize("oversized", [False, True])
def test_cli_private_input_refuses_before_database_configuration_without_echo(oversized):
    marker = secrets.token_hex(32)
    body = json.dumps({"unexpected": marker + ("x" * 16384 if oversized else "")}).encode()
    # DATABASE_URL is absent: a format error must happen before it is needed.
    environment = {"PATH": os.environ["PATH"], "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                   "PYTHONDONTWRITEBYTECODE": "1"}
    actual = subprocess.run([sys.executable, "-m", "app.deployment.application_key_rotation", "preview",
                             "--expected-database", "unused-input-guard"], input=body, capture_output=True,
                            env=environment, timeout=10)
    assert actual.returncode == 1 and not actual.stdout
    assert marker.encode() not in actual.stderr
    assert json.loads(actual.stderr)["code"] == "app_key_rotation_input_invalid"
