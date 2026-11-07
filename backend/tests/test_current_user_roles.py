"""ROOTFIX-002: genuine database projection and authenticated TLS API controls."""
from uuid import UUID

from sqlalchemy import event, select
from app.api.routes.users import _user_summaries
from app.db.models import User
from app.security.auth import IdentityPrincipal
from app.security.context import resolve_identity_context
from current_live_support import current_live as _common_current_live
import pytest


@pytest.fixture(scope="module")
def current_live(_common_current_live):
    from chg418_user_role_inputs import projection_input
    with projection_input(_common_current_live) as live:
        yield live


def test_effective_roles_are_batched_merged_and_owner_flags_stay_separate(current_live):
    data=current_live.context['role_projection']
    with current_live.database() as session:
        actor=session.get(User,UUID(current_live.context['actors']['system_viewer']['user_id']))
        context=resolve_identity_context(session,IdentityPrincipal(subject=str(actor.id),user_id=actor.id,
            employee_id=None,email=None,display_name=None,groups=(),session_id=None,auth_time=None))
        people=list(session.scalars(select(User).where(User.id.in_([UUID(data['user_id']),UUID(data['empty_user_id'])]))))
        observed=[]
        def statement(_connection,_cursor,sql,_parameters,_context,_many):
            observed.append(sql)
        engine=session.get_bind()
        event.listen(engine,'before_cursor_execute',statement)
        try:values={str(row.id):row for row in _user_summaries(session,people,context)}
        finally:event.remove(engine,'before_cursor_execute',statement)
        assert len(observed)==1,'role projection must issue one batch query'
        roles=[role.model_dump(mode='json') for role in values[data['user_id']].roles]
        assert roles==data['expected_roles']
        assert values[data['empty_user_id']].roles==[]
        assert values[data['user_id']].knowledge_owner is True
        assert all(role['id'] not in data['excluded_role_ids'] for role in roles)


def test_system_list_detail_update_and_status_return_consistent_roles(current_live):
    data=current_live.context['role_projection'];user_id=data['user_id']
    viewer=current_live.actor('system_viewer');editor=current_live.actor('system_editor')
    listing=viewer.get('users',params={'q':user_id})
    assert listing.status_code==200 and listing.headers['X-Total-Count']=='1'
    assert listing.json()[0]['roles']==data['expected_roles']
    detail=viewer.get('users/'+user_id)
    assert detail.status_code==200 and detail.json()['roles']==data['expected_roles']
    assert viewer.put('users/'+user_id,json={'system_notes':'read-only must be denied'}).status_code==403
    saved=editor.put('users/'+user_id,json={'system_notes':'CHG369 owned projection verification'})
    assert saved.status_code==200 and saved.json()['roles']==data['expected_roles']
    try:
        disabled=editor.patch('users/'+user_id+'/status',json={'is_active':False})
        assert disabled.status_code==200 and disabled.json()['is_active'] is False
        assert disabled.json()['roles']==data['expected_roles']
    finally:
        restored=editor.patch('users/'+user_id+'/status',json={'is_active':True})
        assert restored.status_code==200 and restored.json()['is_active'] is True
        assert restored.json()['roles']==data['expected_roles']


def test_project_members_and_edit_only_responses_cannot_disclose_system_roles(current_live):
    data=current_live.context['role_projection'];user_id=data['user_id']
    project=current_live.actor('project_viewer');editonly=current_live.actor('system_edit_only')
    response=project.get('users',params={'scope':'project_members','q':user_id})
    assert response.status_code==200 and response.json()
    assert all(row['roles']==[] for row in response.json())
    assert project.get('users/'+user_id).status_code==403
    assert editonly.get('users/'+user_id).status_code==403
    saved=editonly.put('users/'+user_id,json={'system_notes':'CHG369 edit-only verification'})
    assert saved.status_code==200 and saved.json()['roles']==[]
    # Its successful edit does not grant any additional read permission.
    assert editonly.get('users').status_code==403
