"""Actual PostgreSQL custody refusals; no generated-output or Provider claim."""
from datetime import UTC, datetime
from pathlib import Path
import tempfile
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import AIModel, Project
from current_native_support import native_database
from scripts.current_e2e_resources import CurrentSqlBatch, creation_proof, register_descendants
from scripts.e2e_run_resources import CleanupConflict, RunJournal, SqlResources, digest


@pytest.fixture
def custody_inputs():
    """Native root metadata only, precisely removed; never a generation result."""
    model_id, project_id = uuid4(), uuid4()
    with native_database() as engine, tempfile.TemporaryDirectory(prefix='chg370-custody-') as directory:
        root = Path(directory).resolve()
        try:
            resources = SqlResources(engine)
            with RunJournal(root / 'birth.json', create=True, bindings={'sql': resources.binding()}) as journal:
                resources.create(journal, [
                    AIModel(id=model_id, name='Native custody input ' + str(model_id), model_type='Embedding',
                            provider='custom', endpoint='https://never-called.invalid', config={}, is_active=False),
                    Project(id=project_id, name='Native custody input ' + str(project_id), status='active',
                            embedding_model_id=model_id),
                ])
                yield engine, root, journal, model_id, project_id
        finally:
            with Session(engine) as session:
                session.execute(delete(Project).where(Project.id == project_id))
                session.execute(delete(AIModel).where(AIModel.id == model_id))
                session.commit()


def custody(journal, model_id, project_id):
    # Intentionally untrusted metadata is an input to the refusal guards. It
    # never stands in for successful extraction or a genuine generation receipt.
    return {'run_id': journal.data['run_id'], 'source_sha256': journal.data['source_sha256'],
            'generation_intent_recorded': True, 'project_id': str(project_id),
            'model_ids': [str(model_id)], 'root_was_absent_before_creation': True,
            'preexisting_sql_identities': []}


def test_current_custody_refuses_root_that_predates_the_journal(custody_inputs):
    engine, root, original, model_id, project_id = custody_inputs
    with RunJournal(root / 'later.json', create=True) as later, Session(engine) as session:
        table = Project.__table__
        row = session.execute(select(table).where(table.c.id == project_id)).mappings().one()
        entry = later.intent('sql', {'table': 'projects', 'pk': {'id': str(project_id)}})
        # A malformed attempted adoption has real current row metadata. The
        # actual creation time must still reject it; no fake SQL client is used.
        later.created(entry, creation_proof(table, row))
        before = dict(row)
        with pytest.raises(CleanupConflict) as denied:
            register_descendants(later, session, custody(later, model_id, project_id))
        assert denied.value.code == 'current_e2e_root_predates_birth_journal'
        assert dict(session.execute(select(table).where(table.c.id == project_id)).mappings().one()) == before


def test_current_custody_refuses_replaced_creation_identity(custody_inputs):
    engine, _, journal, model_id, project_id = custody_inputs
    with Session(engine) as session:
        project = session.get(Project, project_id)
        original = project.created_at
        project.created_at = datetime.now(UTC)
        session.flush()
        try:
            with pytest.raises(CleanupConflict) as denied:
                register_descendants(journal, session, custody(journal, model_id, project_id))
            assert denied.value.code == 'current_e2e_root_replaced'
        finally:
            session.rollback()
        assert session.get(Project, project_id).created_at == original


def test_current_cleanup_refuses_user_table_before_deleting(custody_inputs):
    engine, _, _, _, project_id = custody_inputs
    entry = {'id': str(uuid4()), 'kind': 'sql', 'identity': {'table': 'users', 'pk': {'id': str(uuid4())}},
             'proof': {}, 'state': 'created'}
    with Session(engine) as session:
        before = session.get(Project, project_id).created_at
        with pytest.raises(CleanupConflict) as denied:
            CurrentSqlBatch(session, [entry]).preflight()
        assert denied.value.code == 'current_e2e_table_denied'
        assert session.get(Project, project_id).created_at == before


def test_current_cleanup_refuses_unowned_incoming_document(custody_inputs):
    """Real FK reflection must retain its refusal after metadata caching."""
    from app.db.models import Document

    engine, _, journal, _, project_id = custody_inputs
    document_id = uuid4()
    with Session(engine) as session:
        session.add(Document(id=document_id, project_id=project_id, document_code=uuid4().hex,
            title='Native unowned dependency input', source_type='upload', status='inactive'))
        session.commit()
    try:
        with Session(engine) as session:
            before = session.get(Project, project_id).created_at
            entries = [entry for entry in journal.data['resources'] if entry['kind'] == 'sql']
            with pytest.raises(CleanupConflict) as denied:
                CurrentSqlBatch(session, entries).preflight()
            assert denied.value.code == 'current_e2e_unowned_incoming_row'
            assert session.get(Document, document_id) is not None
            assert session.get(Project, project_id).created_at == before
    finally:
        with Session(engine) as session:
            session.execute(delete(Document).where(Document.id == document_id, Document.project_id == project_id))
            session.commit()
