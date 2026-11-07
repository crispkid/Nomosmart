"""Real isolated identity/PG/S3/HTTP format acceptance. No inference or doubles."""
from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
from threading import Thread
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import (AIModel, AIModelUsageEvent, DataConnection, DataSyncRun, Document, DocumentVersion,
    FileProcessingExecution, FileProcessingTask, FileProcessingPolicy, OutboxEvent, PipelineRun, PipelineRunStep, Project, ProjectOwner,
    Role, RolePermission, RoleUser, User)
from app.db.session import get_session_factory
from app.domain.document_imports import (UploadedFilePayload, create_updated_file_version, start_document_extraction)
from app.domain.extraction_pipeline import execute_auto_extraction, initialize_pipeline_steps, retry_failed_step, _parse_document_payload
from app.domain.data_sync import execute_data_source_sync
from app.integrations.s3_storage import S3ObjectStorage
from app.main import create_app
from app.security.auth import JWTValidator
from docx_source_samples import docx_bytes
from owned_service_scope import verify_owned_services
from scripts.native_pdf_input import pdf_input


@pytest.fixture(scope='module')
def live():
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_document_formats_support import current_document_formats
        with current_document_formats() as current:
            yield current
        return
    settings=get_settings();run_id=verify_owned_services(settings)
    identities=json.loads(Path(os.environ['CHG342_IDENTITIES']).read_text())
    editor=identities['editor'];outsider=identities['outsider']
    principal=JWTValidator(settings).validate(editor['access_token'])
    with get_session_factory()() as db:
        user=db.scalar(select(User).where(User.keycloak_user_id==editor['subject']))
        other=db.scalar(select(User).where(User.keycloak_user_id==outsider['subject']))
        if user is None:
            user=User(keycloak_user_id=editor['subject'],display_name='Owned format editor',is_active=True)
            other=User(keycloak_user_id=outsider['subject'],display_name='Owned format outsider',is_active=True)
            db.add_all([user,other]);db.flush()
            role=Role(name='CHG342-'+str(run_id),is_active=True);db.add(role);db.flush()
            for name in ('KnowledgeProjects','SystemManagement'):
                db.add(RolePermission(role_id=role.id,module_name='Menu',function_name=name,can_view=True,can_create=True,can_edit=True))
            db.add_all([RoleUser(role_id=role.id,user_id=user.id,source='manual'),RoleUser(role_id=role.id,user_id=other.id,source='manual')])
            ocr=AIModel(name='Owned keyless OCR metadata',model_type='OCR',provider='Tesseract',is_active=True,is_default=True,config={})
            db.add(ocr);db.flush()
            project=Project(name='Owned formats',status='active',created_by=user.id,ocr_model_id=ocr.id)
            db.add(project);db.flush();db.add(ProjectOwner(project_id=project.id,user_id=user.id,created_at=datetime.now(UTC)));db.commit()
        else:
            # A repeat within this SAME owned run reuses its actual IdP grants;
            # no extra identities, model settings or manufactured outcomes.
            assert other is not None
            ocr=db.scalar(select(AIModel).where(AIModel.name=='Owned keyless OCR metadata'))
            project=db.scalar(select(Project).where(Project.created_by==user.id,Project.name=='Owned formats'))
            assert ocr is not None and project is not None
        ids=dict(user=user.id,project=project.id,ocr=ocr.id)
    client=TestClient(create_app(settings))
    yield dict(client=client,headers={'Authorization':'Bearer '+editor['access_token']},outsider={'Authorization':'Bearer '+outsider['access_token']},settings=settings,principal=principal,**ids)
    client.close()


def root(live):return '/api/v1/projects/'+str(live['project'])+'/documents'


def versions(db, project):return db.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.project_id==project))


def source_version(live, *, ext='.docx', status='ready_for_extraction'):
    """Historical source INPUT only, never a fabricated extraction/publish result."""
    body=docx_bytes();storage=S3ObjectStorage(live['settings'])
    with get_session_factory()() as db:
        d=Document(project_id=live['project'],document_code=uuid4().hex,title='Historical original',source_type='file_upload',created_by=live['user'])
        db.add(d);db.flush()
        v=DocumentVersion(project_id=d.project_id,document_id=d.id,version_major=1,extraction_revision=0,version_label='v1.0',status=status,
            original_file_name='historical'+ext,canonical_extension=ext,mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            content_sha256=sha256(body).hexdigest(),file_size=len(body),chunk_strategy={},lock_version=1)
        db.add(v);db.flush();key=f'projects/{d.project_id}/documents/{d.id}/versions/{v.id}/source/original{ext}'
        storage.put_object(bucket=live['settings'].s3_bucket,key=key,body=body,content_type=v.mime_type)
        v.storage_bucket=live['settings'].s3_bucket;v.storage_key=key;db.commit()
        return d.id,v.id,body


def test_actual_mixed_batch_preserves_valid_siblings_and_rejects_other_formats(live):
    files=[('files',('ok.PDF',pdf_input(),'application/pdf')),('files',('bad.docx',docx_bytes(),'application/octet-stream')),
        ('files',('ok.txt','中文'.encode(),'text/plain')),('files',('bad.csv',b'a,b\n1,2','text/csv')),
        ('files',('ok.MARKDOWN',b'# Owned markdown','text/markdown'))]
    with get_session_factory()() as db:
        before=versions(db,live['project']);before_pipelines=db.scalar(select(func.count()).select_from(PipelineRun).where(PipelineRun.project_id==live['project']))
    response=live['client'].post(root(live)+'/upload',headers={**live['headers'],'Idempotency-Key':str(uuid4())},files=files)
    assert response.status_code==200, ('http_status', response.status_code, response.json().get('code') if isinstance(response.json(),dict) else None)
    results=response.json()['results']
    assert [v['status'] for v in results]==['success','failed','success','failed','success'], [(v['status'],v['error_code']) for v in results]
    assert [v['index'] for v in results]==list(range(5))
    assert all(results[i]['error_code']=='unsupported_upload_type' for i in (1,3))
    assert all(not results[i]['started_extraction'] for i in (0,2,4))
    with get_session_factory()() as db:
        assert versions(db,live['project'])==before+3
        assert db.scalar(select(func.count()).select_from(PipelineRun).where(PipelineRun.project_id==live['project']))==before_pipelines
        for i in (0,2,4):
            v=db.get(DocumentVersion,UUID(results[i]['document']['latest_version']['id']))
            assert S3ObjectStorage(live['settings']).get_object(bucket=v.storage_bucket,key=v.storage_key).body==files[i][1][1]


def test_actual_authentication_and_project_scope_are_preserved(live):
    files={'files':('ok.txt',b'owned','text/plain')}
    assert live['client'].post(root(live)+'/upload',files=files).status_code==401
    assert live['client'].post(root(live)+'/upload',files=files,headers=live['outsider']).status_code==403


def test_actual_single_upload_queues_without_running_a_model(live):
    response=live['client'].post(root(live)+'/upload',headers={**live['headers'],'Idempotency-Key':str(uuid4())},files={'files':('queued.md',b'# queued only','text/markdown')})
    assert response.status_code==200, ('http_status', response.status_code, response.json().get('code') if isinstance(response.json(),dict) else None)
    item=response.json()['results'][0];assert item['status']=='success' and item['started_extraction']
    with get_session_factory()() as db:
        version=UUID(item['document']['latest_version']['id'])
        p=db.scalar(select(PipelineRun).where(PipelineRun.document_version_id==version))
        assert p.status=='queued'
        assert db.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_id==p.id,OutboxEvent.status=='pending'))
        assert db.scalar(select(func.count()).select_from(AIModelUsageEvent).where(AIModelUsageEvent.project_id==live['project']))==0


def test_actual_old_source_download_and_version_capabilities(live):
    did,vid,body=source_version(live)
    url=root(live)+f'/{did}/versions/{vid}/original-file'
    result=live['client'].get(url,headers=live['headers'])
    assert result.status_code==200 and result.content==body
    assert 'wordprocessingml.document' in result.headers['content-type']
    assert live['client'].get(url,headers=live['outsider']).status_code==403
    result=live['client'].get(root(live),headers=live['headers']);assert result.status_code==200
    envelope=result.json();items=envelope.get('items',[]) if isinstance(envelope,dict) else envelope
    row=next(v for v in items if v['id']==str(did))
    assert row['capabilities']['can_start_extraction'] is False
    assert row['capabilities']['can_reextract'] is False
    assert row['capabilities']['can_update_source'] is True


def test_actual_retired_source_start_retry_and_replacement_policy(live):
    did,vid,_=source_version(live)
    with get_session_factory()() as db:
        p=db.get(Project,live['project']);d=db.get(Document,did);v=db.get(DocumentVersion,vid)
        count=versions(db,p.id)
        with pytest.raises(AppError) as error:
            start_document_extraction(session=db,settings=live['settings'],project=p,document=d,version=v,actor_user_id=live['user'],requested_ocr_model_id=None,force_ocr=True)
        assert error.value.code=='unsupported_upload_type' and v.status=='ready_for_extraction'
        with pytest.raises(AppError) as error:
            create_updated_file_version(session=db,settings=live['settings'],storage=S3ObjectStorage(live['settings']),project=p,document=d,actor_user_id=live['user'],file=UploadedFilePayload('again.docx',None,docx_bytes()),requested_ocr_model_id=None,force_ocr=False)
        assert error.value.code=='unsupported_upload_type' and versions(db,p.id)==count
        pipeline=PipelineRun(project_id=p.id,document_id=d.id,document_version_id=v.id,run_type='document_extraction',status='queued',created_at=datetime.now(UTC))
        db.add(pipeline);db.flush();initialize_pipeline_steps(db,pipeline,ocr_model_id=None,ocr_name='',force_ocr=False);db.flush()
        execute_auto_extraction(session=db,settings=live['settings'],project=p,document=d,version=v,pipeline=pipeline)
        assert pipeline.status==v.status=='failed'
        step=db.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id==pipeline.id,PipelineRunStep.step_name==pipeline.current_step_name))
        assert step.status=='failed' and step.artifact_payload['error_code']=='unsupported_upload_type'
        with pytest.raises(AppError) as error:
            retry_failed_step(session=db,settings=live['settings'],project=p,document=d,version=v,pipeline=pipeline,step_name=step.step_name)
        assert error.value.code=='unsupported_upload_type' and step.retry_count==0
        assert versions(db,p.id)==count
        db.commit()


@pytest.mark.parametrize('name,body',[('source.json',b'{"owned":"JSON input"}'),('source.csv',b'name,value\none,two\n'),('retired.docx',docx_bytes())],ids=['json','csv','word'])
def test_actual_https_data_sync_preserves_api_json_csv_and_rejects_word(live,tmp_path,name,body):
    target=tmp_path/name;target.write_bytes(body)
    class QuietFiles(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    current=bool(os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'))
    source_host='127.0.0.1' if current else 'runner'
    bind=(source_host,18889) if current else ('0.0.0.0',0)
    server=ThreadingHTTPServer(bind,partial(QuietFiles,directory=str(tmp_path)))
    if current:
        from current_https_source_support import private_source_certificate
        cert,key=private_source_certificate()
    else:cert,key='/run/regression/ca.pem','/run/regression/key.pem'
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
    server.socket=tls.wrap_socket(server.socket,server_side=True);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        settings=live['settings'].model_copy(update={'http_source_allowed_hosts':source_host})
        with get_session_factory()() as db:
            d=Document(project_id=live['project'],document_code=uuid4().hex,title=name,source_type='http_api_service',created_by=live['user']);db.add(d);db.flush()
            c=DataConnection(project_id=live['project'],service_type='HTTP_API',name=uuid4().hex,schedule_mode='once',enabled=True,
                connection_metadata={'verify_tls':True,'auth_mode':'none'},source_identity={'url':f'https://{source_host}:{server.server_port}/{name}','file_name':name,'document_id':str(d.id)})
            db.add(c);db.flush();run=DataSyncRun(data_connection_id=c.id,document_id=d.id,status='queued',trigger_type='manual',created_at=datetime.now(UTC));db.add(run);db.flush()
            before=versions(db,live['project'])
            execute_data_source_sync(session=db,settings=settings,run_id=run.id)
            if name.endswith('.docx'):
                assert run.status=='failed' and run.error_code=='unsupported_upload_type', run.error_code
                assert versions(db,live['project'])==before
            else:
                assert run.status=='success',run.error_code
                v=db.get(DocumentVersion,run.document_version_id)
                assert v.status=='ready_for_extraction' and v.canonical_extension==target.suffix
                assert v.chunk_strategy['source_text_object']['sha256']==sha256(body).hexdigest()
                assert _parse_document_payload(settings,v)['canonical_markdown']==body.decode()
                assert S3ObjectStorage(settings).get_object(bucket=v.storage_bucket,key=v.storage_key).body==body
            assert db.scalar(select(func.count()).select_from(AIModelUsageEvent).where(AIModelUsageEvent.project_id==live['project']))==0
            db.commit()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);assert not thread.is_alive()


def test_actual_rejected_worker_task_releases_document_claim_without_parser(live):
    from app.domain.file_processing_settings import initialize_policy,PlatformCapabilities
    from app.domain.file_processing_dispatch import prepare_dispatch,claim_task,quiesce_task,finalize_task
    did,vid,_=source_version(live)
    with get_session_factory()() as db:
        if db.get(FileProcessingPolicy,1) is None:
            initialize_policy(db,principal=live['principal'],deployment_id=uuid4(),legacy_timeout_seconds=120,
                legacy_max_pages=200,legacy_upload_mib=100,capabilities=PlatformCapabilities({}));db.commit()
        p=db.get(Project,live['project']);d=db.get(Document,did);v=db.get(DocumentVersion,vid)
        pipeline=PipelineRun(project_id=p.id,document_id=d.id,document_version_id=v.id,project_generation=p.work_generation,
            run_type='document_extraction',status='queued',created_at=datetime.now(UTC))
        db.add(pipeline);db.flush();initialize_pipeline_steps(db,pipeline,ocr_model_id=None,ocr_name='',force_ocr=False);db.commit()
        dispatch=prepare_dispatch(db,run_id=pipeline.id,capabilities=PlatformCapabilities({}));db.commit()
        claim=claim_task(db,task_id=dispatch.task_id,generation=dispatch.generation,broker_task_id=dispatch.broker_task_id,worker_identity='chg342-owned-format');db.commit()
        assert claim is not None
        execute_auto_extraction(session=db,settings=live['settings'],project=p,document=d,version=v,pipeline=pipeline,durable=True,execution_claim=claim)
        assert pipeline.status==v.status=='failed'
        quiesce_task(db,claim,disposition='failed');db.commit()
        assert finalize_task(db,claim.task_id);db.commit()
        assert db.get(FileProcessingTask,claim.task_id).state=='finalized'
        assert db.get(FileProcessingExecution,claim.execution_id).released_at is not None
        assert db.scalar(select(func.count()).select_from(FileProcessingExecution).join(PipelineRun,FileProcessingExecution.run_id==PipelineRun.id).where(FileProcessingExecution.kind=='parser',PipelineRun.project_id==live['project']))==0
        assert db.scalar(select(func.count()).select_from(AIModelUsageEvent).where(AIModelUsageEvent.project_id==live['project']))==0


@pytest.mark.parametrize('mutation', ['version','change_id','purpose','deadline','source','plan_sha256','issuer','weak_tls','wrong_path','source_root'])
def test_actual_owned_scope_rejects_untrusted_inputs(live,mutation):
    from copy import deepcopy
    from datetime import timedelta
    from pydantic import SecretStr
    from sqlalchemy.engine import make_url
    from document_format_service_scope import verify_document_format_services
    path=Path(os.environ['NOMOSMART_TEST_SCOPE'])
    original=json.loads(path.read_text());scope=deepcopy(original);settings=live['settings']
    assert verify_document_format_services(settings,path,scope)==UUID(original['run_id'])
    # Positive precondition is the actual source-bound, TLS-owned database.
    assert verify_owned_services(settings)==UUID(original['run_id'])
    if mutation=='version':scope['version']=4
    elif mutation=='change_id':scope['change_id']='CHG-341'
    elif mutation=='purpose':scope['purpose']='untrusted-purpose'
    elif mutation=='deadline':scope['deadline']=(datetime.now(UTC)-timedelta(seconds=1)).isoformat()
    elif mutation=='source':scope['source']['backend/app/domain/uploads.py']='0'*64
    elif mutation=='plan_sha256':scope['plan_sha256']='0'*64
    elif mutation=='issuer':scope['issuer']='https://unowned.invalid/realms/other'
    elif mutation=='weak_tls':
        url=make_url(settings.database_url.get_secret_value()).update_query_dict({'sslmode':'prefer'})
        settings=settings.model_copy(update={'database_url':SecretStr(url.render_as_string(hide_password=False))})
    elif mutation=='wrong_path':path=Path('/tmp/unowned-scope.json')
    elif mutation=='source_root':scope['source_root']='/tmp/unowned-source'
    with pytest.raises(AssertionError):verify_document_format_services(settings,path,scope)


@pytest.fixture(autouse=True)
def current_zero_inference_guard(live, request):
    if not os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        yield
        return
    from current_document_formats_support import inference_fingerprints
    before=inference_fingerprints()
    try:yield
    finally:
        assert inference_fingerprints()==before, 'Current format checks must preserve every historical usage/parser row'
