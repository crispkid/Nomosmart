"""R20: stepwise real policy/audit checks with the evidence-preserving V051 fixture."""
from copy import deepcopy

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import AuditLog, FileProcessingPolicyRevision
from app.domain.file_processing_settings import load_policy
from chg305_v051_support import isolated_case, live_db_v051
import test_document_execution_live as admission
import test_file_processing_settings_live as settings


def test_25_contenders_and_duplicate_start_v051(live_db_v051):
    admission.test_25_real_contenders_global_10_and_duplicate_start(live_db_v051)


def test_retired_policy_fields_and_atomic_audit_v051(live_db_v051):
    db = live_db_v051

    def snapshot():
        # Detached copies include IDs and all columns, not just record counts.
        with db['factory']() as session:
            revisions = session.scalars(select(FileProcessingPolicyRevision).order_by(
                FileProcessingPolicyRevision.revision)).all()
            audits = session.scalars(select(AuditLog).where(AuditLog.actor_user_id == db['actor'],
                AuditLog.action == 'file_processing.policy.updated',
                AuditLog.resource_type == 'file_processing_policy', AuditLog.resource_id.is_(None))
                .order_by(AuditLog.created_at, AuditLog.id)).all()
            def columns(row):
                return {column.key: deepcopy(getattr(row, column.key)) for column in row.__table__.columns}
            return load_policy(session), [columns(row) for row in revisions], [columns(row) for row in audits]

    original = settings.initialize(db)
    initial = snapshot()
    current, revisions, audits = initial
    assert current == original and current.revision == 1
    assert len(revisions) == len(audits) == 1
    initial_revision, initial_audit = revisions[0], audits[0]
    original_values = original.settings.model_dump(mode='json')
    assert initial_revision['revision'] == initial_audit['summary']['revision'] == 1
    assert initial_revision['snapshot'] == initial_audit['summary']['current'] == original_values
    assert initial_audit['summary']['previous'] == {}
    assert initial_audit['summary']['provenance'] == initial_revision['provenance']
    assert initial_revision['provenance']['operation'] == 'initialize_missing_only'
    assert initial_audit['result'] == 'success'

    for key in ('pdf_parser_cpu_millicores', 'pdf_parser_memory_mib'):
        with pytest.raises(AppError) as failure:
            settings.change(db, {key: getattr(original.settings, key) + 1})
        assert failure.value.code == 'file_processing_parameter_deprecated'
        assert snapshot() == initial
    assert settings.change(db, original_values) == original
    assert snapshot() == initial

    updated = settings.change(db, {'pdf_parser_scratch_mib': 1024})
    assert updated.settings.pdf_parser_scratch_mib > updated.settings.pdf_parser_memory_mib
    current, revisions, audits = snapshot()
    assert current == updated and current.revision == 2
    assert len(revisions) == len(audits) == 2
    assert revisions[0] == initial_revision
    audit_by_id = {row['id']: row for row in audits}
    assert audit_by_id.pop(initial_audit['id']) == initial_audit
    update_audit, = audit_by_id.values()
    update_revision = revisions[1]
    assert update_revision['revision'] == update_audit['summary']['revision'] == 2
    assert update_audit['result'] == 'success'
    assert update_audit['summary']['previous'] == original_values
    assert update_audit['summary']['current'] == update_revision['snapshot'] == updated.settings.model_dump(mode='json')
    assert update_audit['summary']['provenance'] == update_revision['provenance'] == {'operation': 'compare_and_swap'}
    assert update_revision['snapshot']['pdf_parser_scratch_mib'] != original_values['pdf_parser_scratch_mib']
    for key in ('pdf_parser_cpu_millicores', 'pdf_parser_memory_mib'):
        assert update_revision['snapshot'][key] == original_values[key]
