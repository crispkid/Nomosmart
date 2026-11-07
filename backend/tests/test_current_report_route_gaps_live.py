"""REPORT-008/009/010/011/014: true read-only HTTP and CSV, no model/input fabrication."""
from contextlib import ExitStack
from pathlib import Path
from datetime import datetime,timezone
import csv,io,json,math,os
from uuid import UUID
import pytest
from sqlalchemy import select
from app.db.models import Project,AuditLog,Role,RoleUser,RolePermission
from current_live_support import CurrentLive,load_current_context
from current_pending_publish_support import fingerprint

TOPICS=['system_overview','project_ranking','project_reference_ranking','document_reference_ranking','owner_project_summary','document_pipeline_metrics','rag_quality_metrics','validation_run_metrics','model_usage_metrics','alert_metrics']

@pytest.fixture(scope='module')
def reports():
    ctx=load_current_context();P=Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).parent
    current414=ctx.get('change_id')=='CHG-414'
    aliases={'owner':'owner','viewer':'viewer'}
    if current414:
        from scripts.chg414_runtime import Scope,ROOT
        authority=Scope()
        assert ctx['operation_uuid']==authority.op and ctx['run_id']==authority.parent_op and not ctx['native_metadata_only']
        assert os.environ.get('NOMOSMART_CHG414_API_PROFILE') is None and ctx.get('execution_profile')is None
        assert ctx['backend_url']==ctx['origin']=='https://localhost:18889'and ctx['api_prefix']=='/api/backend'
        P=ROOT/'backend/report-readonly13-r2'
        from current_artifact_output418 import directory
        P=directory(P,'reports');assert P.is_dir()and P.resolve()==P
        aliases['viewer']='project_viewer' # Actual existing positive menu user with no Reports grant.
    file=P/'report-readonly-owner.json';assert not file.exists()
    result={'operation_uuid':authority.op if current414 else '24c50237-b9ef-4dc7-b732-13e60933c5cf','requests':[],'business_writes':0,'model_calls':0,'phase':'BEFORE_READS',
            'actual_actor_labels':{label:{'actual_alias':alias,'user_id':ctx['actors'][alias]['user_id']}for label,alias in aliases.items()}}
    def save():file.write_text(json.dumps(result,indent=2,default=str))
    save()
    with ExitStack()as stack:
        live=CurrentLive(ctx,stack)
        with live.database()as session:
            before=fingerprint(session)
            if current414:
                grants={}
                for label,alias in aliases.items():
                    rows=session.execute(select(RolePermission.module_name,RolePermission.function_name,RolePermission.can_view)
                        .join(Role,Role.id==RolePermission.role_id).join(RoleUser,RoleUser.role_id==Role.id)
                        .where(RoleUser.user_id==UUID(ctx['actors'][alias]['user_id']),Role.is_active.is_(True),Role.deleted_at.is_(None))).all()
                    grants[label]={(r.module_name,r.function_name)for r in rows if r.can_view}
                assert {('Menu','Reports'),('Menu','SystemManagement'),('Report','ModelReport')}<=grants['owner']
                assert ('Menu','KnowledgeProjects')in grants['viewer']and('Menu','Reports')not in grants['viewer']
                # REPORT009/014 system scope is operational history over all stored
                # projects. Archived metadata/statistics are not archived content
                # access. Project has active|archived states and no deleted field.
                rows=session.execute(select(Project.id,Project.name,Project.status).where(Project.status.in_(['active','archived']))).all()
                projects={str(r.id):r.name for r in rows};counts={status:sum(r.status==status for r in rows)for status in ('active','archived')}
                result['system_scope_semantics']='REPORT009/014 full system historical aggregates; not active-only project picker or archived-content permission'
                result['actual_project_states']=counts;result['actual_view_grants']={label:sorted(map(list,values))for label,values in grants.items()}
            else:projects={str(p.id):p.name for p in session.scalars(select(Project))}
            assert len(projects)>20
            result['original_business_baseline']=before;result['real_project_count']=len(projects);save()
        clients={}
        try:
            for label,alias in aliases.items():clients[label]=live.actor(alias)
            def get(actor,path,status=200,**kwargs):
                __tracebackhide__=True
                assert path in {'reports/summary','reports/filter-options','reports/export.csv'}
                positive_csv=path=='reports/export.csv'and status==200
                if current414 and positive_csv:
                    assert actor=='owner'and kwargs.get('params')=={'topic':'project_ranking','scope':'system','locale':'en'}
                    assert not result.get('csv_request_intent')
                    result['csv_request_intent']={'actor':'owner','topic':'project_ranking','positive_export_request_number':1,'automatic_retry':False};save()
                r=clients[actor].get(path,**kwargs)
                result['requests'].append({'actor':actor,'actual_alias':aliases[actor],'path':path,'params':kwargs.get('params'),'status':r.status_code,'request_id':r.headers.get('x-request-id')});save()
                assert r.status_code==status,('actual_report_response',path,r.status_code)
                if current414 and positive_csv:
                    from hashlib import sha256
                    target=P/'project-ranking-complete-response.csv';assert not target.exists()
                    # httpx.get has actually consumed the bounded response stream;
                    # persist exact received bytes once, before the original parse.
                    with target.open('xb')as output:os.chmod(target,0o600);output.write(r.content);output.flush();os.fsync(output.fileno())
                    result['actual_csv_response_bytes']={'path':str(target),'sha256':sha256(target.read_bytes()).hexdigest(),'bytes':len(r.content),
                        'request_id':r.headers.get('x-request-id'),'export_id':r.headers.get('X-NomoSmart-Export-Id'),
                        'content_type':r.headers.get('Content-Type'),'received_once':True,'full_original_parse_and_audit_assertions_still_required':True};save()
                return r
            yield {'live':live,'get':get,'projects':projects,'result':result,'save':save,'ctx':ctx}
        finally:
            logout={name:client.post('auth/logout').status_code for name,client in clients.items()};result['actual_normal_logouts']=logout;save()
            with live.database()as session:assert fingerprint(session)==before,'report_business_data_changed'
            result.update(phase='READONLY_BASELINE_AND_LOGOUT_COMPLETE',all_original_business_fingerprints_equal=True);save();assert all(x==204 for x in logout.values())

@pytest.mark.parametrize('topic',TOPICS)
def test_each_real_report_topic_paged_contract(reports,topic):
    r=reports['get']('owner','reports/summary',params={'topic':topic,'scope':'system'}).json()
    assert r['topic']==topic and r['scope']=='system'and r['page']==1 and r['page_size']==20
    assert r['total_pages']==math.ceil(r['total_rows']/20)and len(r['rows'])==min(20,r['total_rows'])
    assert r['columns']and len(set(r['columns']))==len(r['columns'])and all(set(r['columns'])<=set(row)for row in r['rows'])
    assert r['status']==('live'if r['rows']else'empty')and r['partial_reasons']==[]
    if topic=='project_ranking':
        assert r['total_rows']==len(reports['projects'])and [x['rank']for x in r['rows']]==list(range(1,21))
        reports['result']['project_first_page_ids']=[x['project_id']for x in r['rows']];reports['save']()

def test_real_filter_options_pages_and_invalid_input_refusals(reports):
    q=reports['get'];opt=q('owner','reports/filter-options',params={'scope':'system'}).json()
    assert opt['selected_scope']=='system'and {str(p['id']):p['name']for p in opt['projects']}==reports['projects']
    assert {s['value']:s['project_count']for s in opt['scopes']}['system']==len(reports['projects'])
    page=q('owner','reports/summary',params={'topic':'project_ranking','scope':'system','page':2}).json()
    assert page['total_rows']==len(reports['projects'])and [r['rank']for r in page['rows']]==list(range(21,21+len(page['rows'])))
    assert not set(reports['result']['project_first_page_ids'])&{x['project_id']for x in page['rows']}
    for params in [{'topic':'unsupported'},{'date_from':'2030-01-02T00:00:00Z','date_to':'2030-01-01T00:00:00Z'},{'page_size':21},{'page':0},{'topic':'project_ranking','scope':'system','page':100000}]:q('owner','reports/summary',422,params=params)
    q('owner','reports/filter-options',422,params={'scope':'unsupported'})
    q('owner','reports/summary',403,params={'scope':'unsupported'})
    empty=q('owner','reports/summary',params={'topic':'model_usage_metrics','scope':'system','date_from':'2099-01-01T00:00:00Z','model_type':'embedding','usage_status':'succeeded'}).json()
    assert empty['status']=='empty'and empty['rows']==[]and empty['total_rows']==0 and empty['total_pages']==0

def test_report_menu_denial_applies_before_summary_options_and_export(reports):
    for path in ['reports/summary','reports/filter-options','reports/export.csv']:
        response=reports['get']('viewer',path,403,params={'scope':'system','topic':'model_usage_metrics'}if path!='reports/filter-options'else{'scope':'system'})
        assert 'text/csv'not in response.headers.get('Content-Type','')and 'X-NomoSmart-Export-Id'not in response.headers

def test_true_full_csv_export_and_audit_without_business_writes(reports):
    q=reports['get'];response=q('owner','reports/export.csv',params={'topic':'project_ranking','scope':'system','locale':'en'})
    assert response.content.startswith(b'\xef\xbb\xbf')and 'text/csv'in response.headers['Content-Type']
    assert response.headers['Cache-Control']=='no-store'and response.headers['X-Content-Type-Options']=='nosniff'
    assert 'nomosmart_project_ranking_all_all.csv'in response.headers['Content-Disposition']
    rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'),newline='')))
    assert rows[0]==['Rank','Project ID','Project Name','Documents','Active Documents','Pipeline Runs','Chat Queries','Validation Runs','Active Users 30d','Success Rate','Failure Rate']
    assert len(rows)-1==len(reports['projects'])>20 and {row[1]:row[2]for row in rows[1:]}==reports['projects']
    assert [int(row[0])for row in rows[1:]]==list(range(1,len(rows)))and all(len(row)==len(rows[0])for row in rows)
    export_id=str(UUID(response.headers['X-NomoSmart-Export-Id']));rid=response.headers['x-request-id']
    with reports['live'].database()as session:
        audits=list(session.scalars(select(AuditLog).where(AuditLog.request_id==rid,AuditLog.action.in_(['report.csv.export.started','report.csv.export.completed']))))
        assert {a.action for a in audits}=={'report.csv.export.started','report.csv.export.completed'}and len(audits)==2
        for audit in audits:assert audit.summary['export_id']==export_id and audit.summary['topic']=='project_ranking'and audit.actor_user_id==UUID(reports['ctx']['actors']['owner']['user_id'])
        completed=next(a for a in audits if a.action.endswith('.completed'));assert completed.result=='completed'and completed.summary['row_count']==len(reports['projects'])and completed.summary['error_code']is None
    reports['result']['actual_csv_export']={'export_id':export_id,'request_id':rid,'rows':len(rows)-1,'started_and_completed_real_audits':True};reports['save']()
