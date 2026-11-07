"""Current uncovered REST boundaries with real SQL/TLS/cookie sessions only."""
from contextlib import ExitStack
from pathlib import Path
from hashlib import sha256
from uuid import UUID,uuid4
import json,os
import pytest
from sqlalchemy import select,delete,func
from app.db.models import AIModel,Project,ProjectMember,ProjectOwner,Document,DocumentVersion,DocumentReference,OutboxEvent,AIModelUsageEvent,IdentitySetting,AuthConnectionSecret
from current_live_support import CurrentLive,load_current_context
from current_pending_publish_support import fingerprint


def identity_snapshot(session):
    settings=session.execute(select(IdentitySetting.id,IdentitySetting.revision,IdentitySetting.state,IdentitySetting.configuration).order_by(IdentitySetting.id)).all()
    secrets=session.execute(select(AuthConnectionSecret.id,AuthConnectionSecret.setting_id,AuthConnectionSecret.purpose,AuthConnectionSecret.key_id,AuthConnectionSecret.envelope).order_by(AuthConnectionSecret.id)).all()
    return sha256(json.dumps({'settings':[list(x)for x in settings],'encrypted_secrets':[list(x)for x in secrets]},sort_keys=True,default=str).encode()).hexdigest()

@pytest.fixture(scope='module')
def boundaries():
    __tracebackhide__=True
    ctx=load_current_context();P=Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).parent
    if ctx.get('change_id')=='CHG-414':
        from current_artifact_output418 import directory
        P=directory(P,'boundaries')
    registry={'operation_uuid':'24c50237-b9ef-4dc7-b732-13e60933c5cf','data_run_uuid':ctx['run_id'],'phase':'BEFORE_INPUTS','projects':[],'requests':[],'model_or_directory_writes':0,'intended_name':'C388-24c50237-apigap-'+uuid4().hex}
    path=P/'six-api-boundary-input-owner-r1.json';assert not path.exists()
    def save():path.write_text(json.dumps(registry,ensure_ascii=False,indent=2,default=str))
    save()
    with ExitStack()as stack:
        live=CurrentLive(ctx,stack)
        with live.database()as session:
            original=fingerprint(session);settings_before=identity_snapshot(session);usage_before=session.scalar(select(func.count()).select_from(AIModelUsageEvent))
        def request(actor,method,path,status,**kwargs):
            __tracebackhide__=True
            response=live.actor(actor).request(method,path,**kwargs)
            if method=='POST'and path=='projects'and response.status_code==201:
                row=response.json();assert row['name']==registry['intended_name'];registry['projects'].append(row['id']);save()
            registry['requests'].append({'actor':actor,'method':method,'path':path,'actual_status':response.status_code});save()
            assert response.status_code==status,('unexpected_actual_API_boundary_response',method,path,response.status_code)
            return response
        if ctx.get('change_id')=='CHG-414':
            # Current empty-project input needs no OCR binding. Read actual
            # approved Chat/Embedding identities; do not impersonate old output.
            from scripts.chg414_runtime import ROOT,REPO
            chat=json.loads((ROOT/'amendments/chg416/chat-after.json').read_bytes())
            resource=json.loads((REPO/'docs/CHG-414-RESOURCE-PROPOSAL.json').read_bytes())
            model_ids={'llm_model_id':chat['model_id'],'embedding_model_id':resource['provider_budget']['model_metadata_read_only']['id'],'ocr_model_id':None}
            with live.database()as session:
                actual=session.execute(select(AIModel.id,AIModel.model_type,AIModel.is_active,AIModel.deleted_at).where(AIModel.id.in_([UUID(model_ids[k])for k in ['llm_model_id','embedding_model_id']]))).all()
                assert len(actual)==2 and all(x.is_active and x.deleted_at is None for x in actual)and {x.model_type for x in actual}=={'Chat','Embedding'}
            registry['current_empty_project_input_scope']='Actual approved models; OCR optional; no generation or published source reconstructed'
        else:
            # Existing genuine published project's public model IDs; no config/key/provider read or inference.
            reference=json.loads((P/'retained-publication.json').read_bytes());readback_path=Path(reference['actual_readback']);raw=readback_path.read_bytes();assert sha256(raw).hexdigest()==reference['actual_readback_sha256'];published=json.loads(raw);assert published['run_uuid']==ctx['run_id']
            with live.database()as session:
                models=session.execute(select(Project.llm_model_id,Project.embedding_model_id,Project.ocr_model_id).where(Project.id==UUID(published['project_id']))).one()
                model_ids=dict(zip(['llm_model_id','embedding_model_id','ocr_model_id'],map(str,models),strict=True));assert all(x is not None for x in models)
                actual=session.execute(select(AIModel.id,AIModel.model_type,AIModel.is_active,AIModel.deleted_at).where(AIModel.id.in_(models))).all();assert len(actual)==3 and all(x.is_active and x.deleted_at is None for x in actual)and{x.model_type for x in actual}=={'Chat','Embedding','OCR'}
        registry['existing_public_model_ids']=model_ids;save()
        try:
            target=request('owner','POST','projects',201,json={'name':registry['intended_name'],'description':'Owned empty metadata target; no import, extraction or model',**model_ids}).json()
            yield {'ctx':ctx,'live':live,'request':request,'target':target,'registry':registry,'save':save,'settings_before':settings_before}
        finally:
            try:
                with live.database()as session:
                    ids=[UUID(x)for x in registry['projects']];assert len(ids)<=1
                    if ids:
                        row=session.get(Project,ids[0]);assert row and row.name==registry['intended_name']and row.created_by==UUID(ctx['actors']['owner']['user_id'])
                        assert session.scalar(select(func.count()).select_from(Document).where(Document.project_id.in_(ids)))==0
                        assert session.scalar(select(func.count()).select_from(DocumentReference).where(DocumentReference.target_project_id.in_(ids)))==0
                        assert session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.project_id.in_(ids)))==0
                        session.execute(delete(ProjectMember).where(ProjectMember.project_id.in_(ids)));session.execute(delete(ProjectOwner).where(ProjectOwner.project_id.in_(ids)));session.execute(delete(Project).where(Project.id.in_(ids)));session.commit()
                    else:assert session.scalar(select(func.count()).select_from(Project).where(Project.name==registry['intended_name']))==0
                    assert identity_snapshot(session)==settings_before,'identity_configuration_or_encrypted_secrets_changed'
                    assert session.scalar(select(func.count()).select_from(AIModelUsageEvent))==usage_before,'unexpected_model_usage'
                    assert fingerprint(session)==original,'original_business_rows_changed'
                registry.update(phase='EXACT_OWNED_EMPTY_PROJECT_CLEANUP_COMPLETE',original_business_fingerprint_unchanged=True,identity_secrets_unchanged=True,actual_model_usage_delta=0);save()
            finally:
                logout={}
                for name,client in live.clients.items():
                    response=client.post('auth/logout');logout[name]=response.status_code;assert response.status_code==204
                registry.update(normal_logouts=logout);save()
            registry['phase']='COMPLETE';save()


def test_locked_identity_readback_is_metadata_only(boundaries):
    t=boundaries;q=t['request'];response=q('owner','GET','system/identity-settings',200);row=response.json()
    assert response.headers['cache-control']=='no-store'and row['state']=='validated_active_locked'and row['editable']is False
    assert row['configuration_source']=='database'and row['configuration']['auth_mode']=='ldap'
    assert row['secrets']['ldap_bind_password']=={'configured':True}
    assert all(set(x)=={'configured'}and isinstance(x['configured'],bool)for x in row['secrets'].values())
    providers=q('owner','GET','system/identity-settings/directory-providers',200).json();assert len(providers)==1 and providers[0]['id']==row['configuration']['directory']['source_id']
    with t['live'].database()as session:assert identity_snapshot(session)==t['settings_before']


def test_identity_write_requires_actual_fresh_proof(boundaries):
    t=boundaries;q=t['request'];setting=q('owner','GET','system/identity-settings',200).json();candidate=str(uuid4());source=setting['configuration']['directory']['source_id']
    q('owner','POST','system/identity-settings/reauth/start',422,json={'purpose':'unsupported'})
    q('owner','POST','system/identity-settings/reauth/complete',401)
    q('owner','POST','system/identity-settings/validate',423,json={'configuration':setting['configuration'],'expected_revision':setting['revision'],'secrets':{}})
    q('owner','PUT','system/identity-settings',423,json={'candidate_id':candidate,'expected_revision':setting['revision']})
    q('owner','POST','system/identity-settings/identity-bindings',423,json={'source_id':source,'issuer':'https://localhost/invalid-never-contacted','subject':'C388-invalid-locked','user_id':t['ctx']['actors']['owner']['user_id'],'directory_object_id':str(uuid4()),'expected_revision':setting['revision']})
    q('owner','GET','system/identity-settings/candidates/'+candidate,423)
    q('system_viewer','POST','system/identity-settings/lock',403)
    q('owner','POST','system/identity-settings/lock',204)
    with t['live'].database()as session:assert identity_snapshot(session)==t['settings_before']


def test_reference_catalog_only_exposes_real_eligible_sources(boundaries):
    t=boundaries;q=t['request'];pid=t['target']['id'];assert q('owner','GET','projects/'+pid+'/document-references',200).json()==[]
    rows=q('owner','GET','projects/'+pid+'/reference-sources',200).json();assert isinstance(rows,list)and all(p['id']!=pid and p['status']=='active'for p in rows)
    with t['live'].database()as session:
        for p in rows:
            source=session.get(Project,UUID(p['id']));assert source and source.status=='active'
            for d in p['documents']:
                doc=session.get(Document,UUID(d['id']));assert doc and not doc.is_deleted and str(doc.project_id)==p['id']
                for v in d['versions']:
                    version=session.get(DocumentVersion,UUID(v['id']));assert version and str(version.document_id)==d['id']and version.status in {'active','inactive'}and v['is_active']==(version.status=='active')


def test_reference_import_missing_inputs_are_atomic(boundaries):
    t=boundaries;q=t['request'];pid=t['target']['id'];item={'source_document_id':str(uuid4()),'source_version_id':str(uuid4()),'old_version_confirmed':False}
    q('owner','POST','projects/'+pid+'/document-references/import',422,json={'mode':'reference','items':[item,item]})
    q('owner','POST','projects/'+pid+'/document-references',404,json={'source_document_id':item['source_document_id'],'source_version_id':item['source_version_id']})
    result=q('owner','POST','projects/'+pid+'/document-references/import',201,json={'mode':'copy','items':[item]}).json();assert len(result['results'])==1 and result['results'][0]['status']=='failed'and result['results'][0]['error_code']=='source_document_not_found'
    q('owner','POST','projects/'+str(uuid4())+'/document-references',403,json={'source_document_id':item['source_document_id']})
    with t['live'].database()as session:
        assert session.scalar(select(func.count()).select_from(Document).where(Document.project_id==UUID(pid)))==0
        assert session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.project_id==UUID(pid)))==0


def test_missing_reference_governance_is_safe(boundaries):
    t=boundaries;q=t['request'];rid=str(uuid4());pid=t['target']['id']
    for path in ['document-references/'+rid+'/detach','document-references/'+rid+'/sync']:
        q('owner','POST',path,404)
    q('owner','POST','document-references/'+rid+'/update',404,json={'source_version_id':str(uuid4()),'old_version_confirmed':False})
    q('owner','POST','document-reference-events/'+str(uuid4())+'/resolve',404)
    q('owner','GET','document-reference-events/impacted-projects',404,params={'source_document_id':str(uuid4())})
    assert q('owner','GET','document-reference-events',200,params={'project_id':pid}).json()==[]


def test_compatibility_reads_keep_empty_project_scope(boundaries):
    q=boundaries['request'];pid=boundaries['target']['id']
    for path in ['review-records','validation-questions']:
        assert q('owner','GET',path,200,params={'project_id':pid}).json()==[]
    for path in ['pipeline-runs','graph-sync-jobs']:
        page=q('owner','GET',path,200,params={'project_id':pid}).json();assert page['items']==[] and page.get('has_more',False)is False
