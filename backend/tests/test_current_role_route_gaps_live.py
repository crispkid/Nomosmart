"""ROLE-002/003 and MENU-001: real REST gaps, own rows, no auth/LDAP fakes."""
from contextlib import ExitStack
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID,uuid4
import json,os
import pytest
from sqlalchemy import select,delete,func
from app.db.models import Role,RolePermission,RoleUser,User,ExternalGroup,ExternalGroupRoleMapping,ExternalGroupUser,AuditLog
from app.security.permissions import MENU_MODULE,MENU_SYSTEM_MANAGEMENT,MENU_KNOWLEDGE_PROJECTS
from current_live_support import CurrentLive,load_current_context
from current_pending_publish_support import fingerprint

@pytest.fixture(scope='module')
def routes():
    __tracebackhide__=True
    ctx=load_current_context();P=Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).parent
    current414=ctx.get('change_id')=='CHG-414'
    if current414:
        from scripts.chg414_runtime import Scope,ROOT
        authority=Scope();assert ctx['operation_uuid']==authority.op and ctx['run_id']==authority.parent_op and not ctx['native_metadata_only']
        P=ROOT/'backend/role-route4-r2'
        from current_artifact_output418 import directory
        P=directory(P,'roles');assert P.is_dir() and P.resolve()==P
    registry={'operation_uuid':'24c50237-b9ef-4dc7-b732-13e60933c5cf','data_run_uuid':ctx['run_id'],'roles':[],'intended_names':[],'groups':[],'requests':[],'phase':'BEFORE_INPUTS','model_or_directory_writes':0};file=P/'role-route-input-owner.json';assert not file.exists()
    if current414:registry['operation_uuid']=authority.op
    def save():file.write_text(json.dumps(registry,ensure_ascii=False,indent=2,default=str))
    save()
    with ExitStack()as stack:
        live=CurrentLive(ctx,stack)
        if current414:
            from current_role_routes414_support import creator_input
            stack.enter_context(creator_input(live,ctx))
        with live.database()as session:
            before=fingerprint(session);registry['original_business_baseline']=before;save()
            protected=session.scalar(select(Role).where(Role.is_system.is_(True),Role.deleted_at.is_(None)))
            assert protected is not None
            system={'id':str(protected.id),'name':protected.name,'lock_version':protected.lock_version}
            for actor,profile in [('owner',(True,True,True,True)),('system_creator',(False,True,False,False)),('system_viewer',(True,False,False,False))]:
                rows=session.execute(select(RolePermission.can_view,RolePermission.can_create,RolePermission.can_edit,RolePermission.can_delete).join(Role,Role.id==RolePermission.role_id).join(RoleUser,RoleUser.role_id==Role.id).where(RoleUser.user_id==UUID(ctx['actors'][actor]['user_id']),Role.is_active.is_(True),Role.deleted_at.is_(None),RolePermission.module_name==MENU_MODULE,RolePermission.function_name==MENU_SYSTEM_MANAGEMENT)).all()
                assert tuple(any(r[i]for r in rows)for i in range(4))==profile,'actual_existing_actor_profile_required'
        def request(actor,method,path,status,**kwargs):
            __tracebackhide__=True
            if method=='POST'and path=='roles':
                intended=kwargs.get('json',{}).get('name');assert isinstance(intended,str)and intended.startswith('C388-24c50237-');registry['intended_names'].append(intended);save()
            response=live.actor(actor).request(method,path,**kwargs)
            if method=='POST'and path=='roles'and response.status_code==201:
                created=response.json();assert created['name']==intended and created['is_system']is False
                if created['id']not in registry['roles']:registry['roles'].append(created['id'])
                save()
            registry['requests'].append({'actor_label':actor,'method':method,'path':path,'status':response.status_code});save()
            assert response.status_code==status,('unexpected_actual_role_response',method,path,response.status_code)
            return response
        def create(actor='owner',name=None):
            name=name or 'C388-24c50237-role-'+uuid4().hex
            registry['intended_names'].append(name);save()
            value=request(actor,'POST','roles',201,json={'name':name,'description':'Owned current role-route verification'}).json();save();return value
        packet={'live':live,'request':request,'create':create,'registry':registry,'save':save,'ctx':ctx,'system':system}
        try:yield packet
        finally:
            logout={}
            for name,client in live.clients.items():
                try:logout[name]=client.post('auth/logout').status_code
                except Exception as error:logout[name]=type(error).__name__
            registry.update(phase='LOGOUT_ATTEMPTED_BEFORE_EXACT_ROW_CLEANUP',actual_normal_logouts=logout);save()
            with live.database()as session:
                roles=session.scalars(select(Role).where(Role.id.in_([UUID(x)for x in registry['roles']]))).all()
                assert len(roles)==len(set(registry['roles']))and all(x.name.startswith('C388-24c50237-')for x in roles)
                ids=[x.id for x in roles];audits=session.scalars(select(AuditLog).where(AuditLog.resource_type=='role',AuditLog.resource_id.in_(ids))).all();registry['retained_real_audits']=[{'id':str(a.id),'resource_id':str(a.resource_id),'action':a.action,'result':a.result}for a in audits]
                session.execute(delete(ExternalGroupRoleMapping).where(ExternalGroupRoleMapping.role_id.in_(ids)));session.execute(delete(RoleUser).where(RoleUser.role_id.in_(ids)));session.execute(delete(RolePermission).where(RolePermission.role_id.in_(ids)));session.execute(delete(Role).where(Role.id.in_(ids)))
                for gid in registry['groups']:
                    group=session.get(ExternalGroup,UUID(gid));assert group is not None and group.external_group_id.startswith('C388-24c50237-native-')
                    assert session.scalar(select(func.count()).select_from(ExternalGroupUser).where(ExternalGroupUser.external_group_id==group.id))==0;assert session.scalar(select(func.count()).select_from(ExternalGroupRoleMapping).where(ExternalGroupRoleMapping.external_group_id==group.id))==0;session.delete(group)
                session.commit();assert fingerprint(session)==before,'non_test_business_rows_changed'
            registry.update(phase='EXACT_INPUT_CLEANUP_COMPLETE',all_original_business_fingerprints_equal=True,actual_normal_logouts=logout,own_role_audit_rows_retained_as_protected_evidence=True);save();assert all(v==204 for v in logout.values())

def test_role_lifecycle_conflicts_and_soft_delete_preserve_history(routes):
    t=routes;q=t['request'];a=t['create']();b=t['create']()
    assert q('owner','GET','roles/'+a['id'],200).json()['id']==a['id']
    q('owner','POST','roles',409,json={'name':a['name']})
    listed=q('owner','GET','roles',200,params={'q':a['name'],'is_active':'true'});assert [x['id']for x in listed.json()]==[a['id']]and listed.headers['X-Total-Count']=='1'
    q('owner','PUT','roles/'+a['id'],422,json={'lock_version':a['lock_version']})
    q('owner','PUT','roles/'+a['id'],422,json={'lock_version':a['lock_version'],'is_active':False,'description':'must stay unchanged'})
    q('owner','PUT','roles/'+a['id'],422,json={'lock_version':a['lock_version'],'name':None})
    q('owner','PUT','roles/'+a['id'],409,json={'lock_version':a['lock_version'],'name':b['name']})
    changed=q('owner','PUT','roles/'+a['id'],200,json={'lock_version':a['lock_version'],'description':'changed through true REST'}).json();assert changed['lock_version']==a['lock_version']+1
    q('owner','PUT','roles/'+a['id'],409,json={'lock_version':a['lock_version'],'description':'stale'})
    disabled=q('owner','PUT','roles/'+a['id'],200,json={'lock_version':changed['lock_version'],'is_active':False}).json();assert disabled['is_active']is False
    q('owner','PUT','roles/'+a['id'],409,json={'lock_version':disabled['lock_version'],'is_active':False})
    q('owner','PUT','roles/'+a['id'],409,json={'lock_version':disabled['lock_version'],'description':'inactive write'})
    assert q('owner','GET','roles',200,params={'q':a['name'],'is_active':'false'}).json()[0]['id']==a['id']
    active=q('owner','PUT','roles/'+a['id'],200,json={'lock_version':disabled['lock_version'],'is_active':True}).json()
    q('owner','DELETE','roles/'+a['id'],422,params={'lock_version':active['lock_version'],'confirmation_name':'wrong'})
    q('owner','DELETE','roles/'+a['id'],409,params={'lock_version':a['lock_version'],'confirmation_name':a['name']})
    q('owner','DELETE','roles/'+a['id'],200,params={'lock_version':active['lock_version'],'confirmation_name':a['name']})
    q('owner','GET','roles/'+a['id'],404);assert q('owner','GET','roles',200,params={'q':a['name']}).json()==[]
    new=t['create'](name=a['name']);assert new['id']!=a['id']
    with t['live'].database()as session:
        old=session.get(Role,UUID(a['id']));assert old.deleted_at is not None and old.deleted_by==UUID(t['ctx']['actors']['owner']['user_id'])and old.is_active is False
    system=t['system'];q('owner','PUT','roles/'+system['id'],409,json={'lock_version':system['lock_version'],'is_active':False});q('owner','DELETE','roles/'+system['id'],409,params={'lock_version':system['lock_version'],'confirmation_name':system['name']})

def test_role_create_and_view_do_not_imply_edit_or_delete(routes):
    t=routes;q=t['request'];a=t['create']('system_creator')
    # VIEW gates reads; explicit CREATE independently authorizes the write.
    q('system_creator','GET','roles/'+a['id'],403)
    for method in ['PUT','DELETE']:
        options={'json':{'lock_version':a['lock_version'],'description':'denied'}}if method=='PUT'else{'params':{'lock_version':a['lock_version'],'confirmation_name':a['name']}}
        q('system_creator',method,'roles/'+a['id'],403,**options)
    view=t['create']();path='roles/'+view['id']
    permission=q('owner','PUT',path+'/permissions',200,json={'lock_version':view['lock_version'],'permissions':[{'module_name':MENU_MODULE,'function_name':MENU_SYSTEM_MANAGEMENT,'can_view':True}]}).json()
    q('owner','PUT',path+'/users',200,json={'lock_version':permission['lock_version'],'user_ids':[t['ctx']['actors']['system_creator']['user_id']]})
    # The real own VIEW role adds read access on the next request, no new login.
    for who in ['system_creator','system_viewer']:
        assert q(who,'GET','roles/'+a['id'],200).json()['id']==a['id']
        q(who,'PUT','roles/'+a['id'],403,json={'lock_version':a['lock_version'],'description':'denied'})
        q(who,'DELETE','roles/'+a['id'],403,params={'lock_version':a['lock_version'],'confirmation_name':a['name']})
    q('system_viewer','POST','roles',403,json={'name':'C388-24c50237-denied-'+uuid4().hex})
    missing=str(uuid4());q('owner','GET','roles/'+missing,404);q('owner','PUT','roles/'+missing,404,json={'lock_version':1,'description':'missing'});q('owner','DELETE','roles/'+missing,404,params={'lock_version':1,'confirmation_name':'missing'})
    assert q('owner','GET','roles/'+a['id'],200).json()['lock_version']==a['lock_version']

def test_role_matrix_and_manual_members_are_atomic_and_retained(routes):
    t=routes;q=t['request'];a=t['create']();path='roles/'+a['id'];empty=q('owner','GET',path+'/permissions',200).json();assert empty['permissions']==[]
    row={'module_name':MENU_MODULE,'function_name':MENU_KNOWLEDGE_PROJECTS,'can_view':True}
    q('owner','PUT',path+'/permissions',422,json={'lock_version':a['lock_version'],'permissions':[row,row]})
    q('owner','PUT',path+'/permissions',422,json={'lock_version':a['lock_version'],'permissions':[dict(row,function_name='unsupported')]})
    q('owner','PUT',path+'/permissions',422,json={'lock_version':a['lock_version'],'permissions':[dict(row,can_execute=True)]})
    matrix=q('owner','PUT',path+'/permissions',200,json={'lock_version':a['lock_version'],'permissions':[row]}).json();assert matrix['permissions'][0]['can_view']is True
    q('owner','PUT',path+'/permissions',409,json={'lock_version':a['lock_version'],'permissions':[]})
    matrix=q('owner','PUT',path+'/permissions',200,json={'lock_version':matrix['lock_version'],'permissions':[dict(row,can_view=False)]}).json()
    assert q('owner','GET',path+'/users',200).json()['users']==[]
    q('owner','PUT',path+'/users',422,json={'lock_version':matrix['lock_version'],'user_ids':[str(uuid4())]})
    uid=t['ctx']['actors']['system_viewer']['user_id'];members=q('owner','PUT',path+'/users',200,json={'lock_version':matrix['lock_version'],'user_ids':[uid,uid]}).json();assert members['users']==[{'user_id':uid,'source':'manual'}]
    q('owner','PUT',path+'/users',409,json={'lock_version':matrix['lock_version'],'user_ids':[]})
    disabled=q('owner','PUT',path,200,json={'lock_version':members['lock_version'],'is_active':False}).json()
    q('owner','PUT',path+'/permissions',409,json={'lock_version':disabled['lock_version'],'permissions':[]});q('owner','PUT',path+'/users',409,json={'lock_version':disabled['lock_version'],'user_ids':[]})
    q('owner','DELETE',path,200,params={'lock_version':disabled['lock_version'],'confirmation_name':a['name']})
    with t['live'].database()as session:
        assert session.get(Role,UUID(a['id'])).deleted_at is not None
        assert session.scalar(select(func.count()).select_from(RoleUser).where(RoleUser.role_id==UUID(a['id']),RoleUser.user_id==UUID(uid),RoleUser.source=='manual'))==1
        assert session.scalar(select(func.count()).select_from(RolePermission).where(RolePermission.role_id==UUID(a['id'])))==1
    q('owner','GET',path+'/permissions',404);q('owner','GET',path+'/users',404)

def test_zero_member_native_group_mapping_lifecycle_and_unique_claim(routes):
    t=routes;q=t['request'];a=t['create']();b=t['create']();gid=uuid4();marker='C388-24c50237-native-'+uuid4().hex;t['registry']['groups'].append(str(gid));t['save']()
    with t['live'].database()as session:
        group=ExternalGroup(id=gid,source='ldap',external_group_id=marker,group_name='C388 zero-member mapping input',identity_origin='ldap',is_active=True,last_synced_at=None);session.add(group);session.commit();assert session.scalar(select(func.count()).select_from(ExternalGroupUser).where(ExternalGroupUser.external_group_id==gid))==0
    # A real native metadata input, never a directory-sync success or login identity.
    q('owner','PUT','roles/'+a['id']+'/external-group-mapping',404,json={'lock_version':a['lock_version'],'external_group_id':str(uuid4())})
    mapped=q('owner','PUT','roles/'+a['id']+'/external-group-mapping',200,json={'lock_version':a['lock_version'],'external_group_id':str(gid)}).json();assert mapped['derived_member_count']==0 and mapped['external_group_id']==str(gid)
    q('owner','PUT','roles/'+b['id']+'/external-group-mapping',409,json={'lock_version':b['lock_version'],'external_group_id':str(gid)})
    q('owner','PUT','roles/'+a['id']+'/external-group-mapping',409,json={'lock_version':a['lock_version'],'external_group_id':None})
    disabled=q('owner','PUT','roles/'+a['id'],200,json={'lock_version':mapped['lock_version'],'is_active':False}).json();q('owner','PUT','roles/'+a['id']+'/external-group-mapping',409,json={'lock_version':disabled['lock_version'],'external_group_id':None})
    q('owner','PUT','roles/'+b['id']+'/external-group-mapping',409,json={'lock_version':b['lock_version'],'external_group_id':str(gid)})
    active=q('owner','PUT','roles/'+a['id'],200,json={'lock_version':disabled['lock_version'],'is_active':True}).json();unmapped=q('owner','PUT','roles/'+a['id']+'/external-group-mapping',200,json={'lock_version':active['lock_version'],'external_group_id':None}).json();assert unmapped['external_group_id']is None
    other=q('owner','PUT','roles/'+b['id']+'/external-group-mapping',200,json={'lock_version':b['lock_version'],'external_group_id':str(gid)}).json();q('owner','DELETE','roles/'+b['id'],200,params={'lock_version':other['lock_version'],'confirmation_name':b['name']})
    with t['live'].database()as session:
        assert session.get(ExternalGroup,gid).external_group_id==marker
        assert session.scalar(select(func.count()).select_from(ExternalGroupRoleMapping).where(ExternalGroupRoleMapping.external_group_id==gid))==0
        assert session.scalar(select(func.count()).select_from(ExternalGroupUser).where(ExternalGroupUser.external_group_id==gid))==0
