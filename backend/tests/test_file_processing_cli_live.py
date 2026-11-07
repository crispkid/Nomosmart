"""R9 real JWT/JWKS and real CLI subprocess acceptance against run-owned PG."""
from datetime import UTC, datetime
import json
import os
import time
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.db.models import (AuditLog, FileProcessingPolicyRevision, RevokedAuthToken,
                           SystemParameter, User)
from app.domain.file_processing_settings import UNITS
from app.security.auth import token_digest, token_identity
CURRENT_PROTOCOL = bool(os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'))
if CURRENT_PROTOCOL:
    from current_legacy_cli_support import (
        current_cli_case as cli_db, current_live, maintenance,
        initialize_cas_and_audit, permissions_preserve_policy,
        expiry_revocation_and_external_credential, invalid_contracts_and_audit,
    )
else:
    from chg305_r9_support import cli, cli_db, initialize_cli, live_db, oidc, principal, snapshot


def test_real_cli_initialize_cas_read_and_audit(cli_db):
    if CURRENT_PROTOCOL:
        initialize_cas_and_audit(cli_db)
        return
    db = cli_db
    initial = initialize_cli(db)
    code, read = cli(db, 'read', name='view')
    assert code == 0 and read == initial
    changes = {'document_processing_max_concurrent': 1, 'pdf_parser_max_concurrent': 1}
    code, updated = cli(db, 'update', changes=changes, revision=1)
    assert code == 0 and updated['revision'] == 2 and updated['content_hash'] != initial['content_hash']
    assert cli(db, 'update', changes=changes, revision=2) == (0, updated)
    assert cli(db, 'initialize', revision=0) == (0, updated)
    assert cli(db, 'read') == (0, updated)
    with db['factory'].begin() as session:
        revisions = session.scalars(select(FileProcessingPolicyRevision).order_by(FileProcessingPolicyRevision.revision)).all()
        assert [row.revision for row in revisions] == [1, 2]
        assert revisions[-1].content_hash == updated['content_hash']
        parameters = {r.key: r.value for r in session.scalars(select(SystemParameter).where(SystemParameter.key.in_(UNITS)))}
        assert parameters == updated['values'] == revisions[-1].snapshot
        actor = session.scalar(select(User).where(User.keycloak_user_id == db['oidc'].users['edit']['subject']))
        audits = session.scalars(select(AuditLog).where(AuditLog.actor_user_id == actor.id,
            AuditLog.action == 'file_processing.policy.updated')).all()
        assert any(row.summary.get('revision') == 2 and row.summary.get('current') == updated['values'] for row in audits)


@pytest.mark.parametrize('name,operation,error', [
    ('view', 'update', 'permission_denied'), ('none', 'read', 'permission_denied'),
    ('disabled', 'read', 'user_disabled')])
def test_real_permissions_reject_without_policy_mutation(cli_db, name, operation, error):
    if CURRENT_PROTOCOL:
        permissions_preserve_policy(cli_db, name, operation, error)
        return
    initialize_cli(cli_db)
    before = snapshot(cli_db)
    code, result = cli(cli_db, operation, name=name, revision=1, changes={'pdf_parser_max_concurrent': 1})
    assert code == 1 and result == {'error': error}
    assert snapshot(cli_db) == before


def test_real_expiry_revocation_wrong_audience(cli_db):
    if CURRENT_PROTOCOL:
        expiry_revocation_and_external_credential(cli_db)
        return
    db = cli_db
    initialize_cli(db)
    before = snapshot(db)
    short = db['oidc'].token(client='r9-short')
    validated = principal(short)
    delay = validated.expires_at.timestamp() - time.time() + 0.2
    assert 0 < delay <= 5, 'short_lifetime_contract'
    time.sleep(delay)  # No clock manipulation; the real token naturally expires.
    assert cli(db, 'read', token=short) == (1, {'error': 'token_expired'})
    assert cli(db, 'read', token=db['oidc'].token(client='r9-wrong')) == (1, {'error': 'invalid_token'})
    token = db['oidc'].token()
    validated = principal(token)
    with db['factory'].begin() as session:
        session.add(RevokedAuthToken(id=uuid4(), token_identity=token_identity(validated, token),
            token_digest=token_digest(token), issuer=validated.issuer, subject=validated.subject,
            audience=validated.audience, token_id=validated.token_id, session_id=validated.session_id,
            issued_at=validated.issued_at, expires_at=validated.expires_at, revoked_at=datetime.now(UTC),
            reason='chg305_r9_synthetic_test', metadata_json={}))
    assert cli(db, 'read', token=token) == (1, {'error': 'token_revoked'})
    assert snapshot(db) == before


def test_cli_invalid_contracts_and_transaction_rollback(cli_db, tmp_path):
    if CURRENT_PROTOCOL:
        invalid_contracts_and_audit(cli_db, tmp_path)
        return
    db = cli_db
    initialize_cli(db)
    before = snapshot(db)
    cases = [
        ('update', {'revision': 0, 'changes': {'pdf_parser_max_concurrent': 1}}, 'file_processing_policy_conflict'),
        ('update', {'revision': 1, 'changes': {'unknown': 1}}, 'file_processing_update_invalid'),
        ('update', {'revision': 1, 'changes': {'pdf_parser_max_concurrent': True}}, 'file_processing_policy_invalid'),
        ('update', {'revision': 1, 'changes': {'pdf_parser_max_pages': 4}}, 'file_processing_capability_exceeded'),
        ('read', {'changes': {'pdf_parser_max_concurrent': 1}}, 'file_processing_cli_input_invalid'),
        ('initialize', {'revision': 1}, 'file_processing_initialization_contract_invalid'),
        ('initialize', {'revision': 0, 'deployment': False}, 'file_processing_initialization_contract_invalid'),
        ('read', {'raw': b'{}'}, 'authentication_required'),
        ('read', {'raw': b'[]'}, 'file_processing_cli_input_invalid'),
        ('read', {'raw': b'{"unexpected":true}'}, 'file_processing_cli_input_invalid'),
        ('read', {'raw': b'x' * 65537}, 'file_processing_cli_input_limit'),
        ('read', {'raw': b'{'}, 'file_processing_maintenance_failed'),
    ]
    with db['factory'].begin() as session:
        actor = session.scalar(select(User).where(User.keycloak_user_id == db['oidc'].users['edit']['subject']))
        audit_before = session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.actor_user_id == actor.id, AuditLog.action == 'file_processing.policy.rejected'))
    for operation, arguments, error in cases:
        assert cli(db, operation, **arguments) == (1, {'error': error})
        assert snapshot(db) == before
    with db['factory'].begin() as session:
        audit_after = session.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.actor_user_id == actor.id, AuditLog.action == 'file_processing.policy.rejected'))
        assert audit_after - audit_before == 7
