"""Actual bounded source, private scope and resource-policy refusal controls."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from uuid import UUID
import pytest
from app.core.config import get_settings
from backend_regression_environment import Regression
from backend_remaining_profile import profile
from owned_service_scope import verify_owned_services
from scripts.public_source_inventory import SourceBoundaryError


def test_current_assignment_is_complete_and_does_not_admit_local_ocr():
    root=Path(__file__).resolve().parents[2]
    rows=profile(root)
    assert len(rows)==len({row['module'] for row in rows})
    assert {row['module'] for row in rows}=={str(p.relative_to(root/'backend')) for p in (root/'backend/tests').glob('test_*.py')}
    pdf=next(row for row in rows if row['module'].endswith('test_chg305_r20_pdf_tools.py'))
    assert all('ocr' not in name.lower() for name in pdf['allow'])
    for name in ('test_chg291_v049_live_backup.py','test_chg301_revision38_backup.py','test_chg301_r7_archive_diagnostic.py'):
        row=next(row for row in rows if row['module']=='tests/'+name)
        assert row['cohort']=='blocked' and row['reason']=='POLICY_BLOCKED_NO_BACKUP'


def test_current_context_is_not_an_old_scope_approval():
    path=Path(os.environ['NOMOSMART_TEST_SCOPE']); original=path.read_bytes(); scope=json.loads(original)
    assert (scope['version'], scope['change_id']) in {(4, 'CHG-341'), (6, 'CHG-349'), (7, 'CHG-351'), (9, 'CHG-360'), (10, 'CHG-361'), (11, 'CHG-369'), (11, 'CHG-370'), (11,'CHG-382')}
    assert verify_owned_services(get_settings())==UUID(scope['run_id'])
    if scope['change_id']=='CHG-382':
        # Current V11 binds actual public bytes, not the retired profile field.
        changed_source={**scope['source']}
        changed_source['backend/app/core/config.py']='0'*64
        source_updates=[{'source':changed_source},
            {'public_inventory':{**scope['public_inventory'],'sha256':'0'*64}}]
    else:
        source_updates=[{'profile_sha256':'0'*64}]
    for updates in ({'version':3},{'version':2},*source_updates,{'plan_sha256':'0'*64},
                    {'deadline':(datetime.fromisoformat(scope['created_at'])+timedelta(hours={4:3,6:5,7:7,9:4,10:2,11:25}[scope['version']])).isoformat()}):
        try:
            path.write_text(json.dumps(scope|updates)); path.chmod(0o600)
            with pytest.raises((AssertionError,SourceBoundaryError)):verify_owned_services(get_settings())
        finally:path.write_bytes(original); path.chmod(0o600)


def test_new_environment_limits_cannot_use_old_complete_runner_or_unreviewed_service(tmp_path):
    run=Regression(tmp_path,change_id='CHG-341')
    try:
        assert run.report['limits']['containers']==12 and run.report['limits']['databases']==16
        with pytest.raises(AssertionError):run.run_suite()
        with pytest.raises(AssertionError):run.container('worker','invalid-unused-image','512m','.3')
        with pytest.raises(AssertionError):run.container('runner','invalid-unused-image','8192m','4')
        assert not run.containers and not run.report['commands']
    finally:run.cleanup()
    assert run.report['cleanup']['workspace_removed']
