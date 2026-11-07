"""Real scope/files/database rejection and preserved missing-model semantics."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Chunk
from app.domain.extraction_pipeline import _create_structure_chunks
from backend_regression_environment import LABEL, Regression
from markdown_live_support import markdown_workspace
from owned_service_scope import verify_owned_services


def test_true_prerequisite_scope_matches_the_owned_database():
    path = Path(os.environ['NOMOSMART_TEST_SCOPE'])
    context = json.loads(path.read_bytes())
    assert verify_owned_services(get_settings()) == UUID(context['run_id'])


@pytest.mark.parametrize('damage', ['public', 'symlink', 'expired', 'purpose', 'source_drift', 'incomplete_source'])
def test_damaged_current_scope_is_rejected(damage):
    path = Path(os.environ['NOMOSMART_TEST_SCOPE'])
    original = path.read_bytes()
    scope = json.loads(original)
    assert (scope['version'], scope['change_id']) in {(3, 'CHG-340'), (4, 'CHG-341'), (6, 'CHG-349'), (7, 'CHG-351'), (9, 'CHG-360'), (10, 'CHG-361'), (11, 'CHG-369'), (11, 'CHG-370'), (11, 'CHG-382')}
    try:
        if damage == 'public':
            path.chmod(0o644)
        elif damage == 'symlink':
            target = path.with_name('invalid-symlink-target.json')
            target.write_bytes(original); target.chmod(0o600)
            path.unlink(); path.symlink_to(target)
        else:
            if damage == 'expired':
                now = datetime.now(UTC)
                scope.update(created_at=(now - timedelta(hours=2)).isoformat(), deadline=(now - timedelta(hours=1)).isoformat())
            elif damage == 'purpose':
                scope['purpose'] = 'unapproved-purpose'
            elif damage == 'source_drift':
                scope['source']['backend/app/core/config.py'] = '0' * 64
            elif damage == 'incomplete_source':
                scope['source'].pop('backend/app/core/config.py')
            path.write_text(json.dumps(scope))
        with pytest.raises(AssertionError):
            verify_owned_services(get_settings())
    finally:
        if path.is_symlink():
            path.unlink(); target.unlink()
        path.write_bytes(original); path.chmod(0o600)
    assert verify_owned_services(get_settings()) == UUID(scope['run_id'])


def test_wrong_database_ownership_is_rejected():
    settings = get_settings()
    expected = verify_owned_services(settings)
    replacement = uuid4()
    scope = json.loads(Path(os.environ['NOMOSMART_TEST_SCOPE']).read_bytes())
    control = {3: 'chg340_control', 4: 'chg341_control', 6: 'chg349_control', 7: 'chg351_control', 9: 'chg360_control', 10: 'chg361_control', 11: 'current_test_control'}[scope['version']]
    engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    try:
        with engine.begin() as connection:
            assert connection.execute(text('UPDATE ' + control + '.ownership SET run_id=:replacement WHERE run_id=:expected'),
                                      dict(replacement=replacement, expected=expected)).rowcount == 1
        with pytest.raises(AssertionError):
            verify_owned_services(settings)
    finally:
        with engine.begin() as connection:
            connection.execute(text('UPDATE ' + control + '.ownership SET run_id=:expected WHERE run_id=:replacement'),
                               dict(expected=expected, replacement=replacement))
        engine.dispose()
    assert verify_owned_services(settings) == expected


def test_shared_markdown_workspace_keeps_missing_model_rejection(markdown_workspace):
    session, project, document, version = markdown_workspace
    assert project.embedding_model_id is None and version.embedding_model_id is None
    with pytest.raises(AppError) as caught:
        _create_structure_chunks(session, get_settings(), project, document, version, '# Owned input\n\nA complete sentence.\n')
    assert caught.value.code == 'chunk_model_capacity_unavailable'
    assert session.scalars(select(Chunk).where(Chunk.document_version_id == version.id)).all() == []


def test_small_scope_cannot_invoke_the_legacy_full_environment(tmp_path):
    legacy = Regression(tmp_path / 'legacy')
    current = Regression(tmp_path / 'current', change_id='CHG-340')
    try:
        assert legacy.label == LABEL and legacy.report['limits']['containers'] == 16
        assert legacy.report['limits']['databases'] == 12 and legacy.name.startswith('nomosmart-chg339-')
        assert current.label == 'nomosmart.chg340.run_id' and current.report['limits']['containers'] == 2
        with pytest.raises(AssertionError):
            current.run_suite()
        with pytest.raises(AssertionError):
            current.container('keycloak', 'invalid-unused-image', '1536m', '.6')
        assert current.containers == [] and current.report['commands'] == []
    finally:
        legacy.cleanup(); current.cleanup()
    assert legacy.report['cleanup']['workspace_removed'] and current.report['cleanup']['workspace_removed']
