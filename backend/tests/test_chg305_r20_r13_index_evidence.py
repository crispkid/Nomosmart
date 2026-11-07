"""R13: real OpenSearch evidence, using genuine run-owned persisted vectors.

No Provider call here. A completed upload is an explicit prerequisite; each
mutation affects only a separate disposable test index, never the source.
"""
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine,select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Chunk, Document, DocumentVersion, Project
from app.db.session import get_session_factory
from app.domain.embeddings import load_staging_embeddings
from app.domain.extraction_pipeline import LiveOpenSearchStagingIndexAdapter, staging_index_name


@pytest.fixture
def corpus():
    settings = get_settings()
    assert settings.app_env == 'test'
    engine=None
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_live_support import load_current_context, load_current_native_context
        from owned_service_scope import verify_owned_services
        native413=json.loads(Path(os.environ['NOMOSMART_TEST_SCOPE']).read_bytes()).get('version')==413
        current=load_current_native_context() if native413 else load_current_context()
        if current.get('change_id')=='CHG-413':
            # These cases exercise the index adapter. Reuse verified immutable
            # provider vectors in own throwaway indexes, without creating a new
            # document/build or claiming a newly completed staging workflow.
            yield from _current413_existing_vector_corpus(settings,current)
            return
        assert current.get('staging'), 'BLOCKED: a current genuine embedding corpus and owned OpenSearch index are required'
        scope={**current['staging'],'run_id':current['run_id']}
        scoped=settings.model_copy(update={'database_url':SecretStr(current['database_url'])})
        assert str(verify_owned_services(scoped))==scope['run_id']
        engine=create_engine(current['database_url'],hide_parameters=True)
        session_context=Session(engine)
        control='current_test_control'
    else:
        if os.environ.get('NOMOSMART_TEST_SCOPE'):
            assert json.loads(Path(os.environ['NOMOSMART_TEST_SCOPE']).read_text()).get('version')!=11, 'current_owned_live_context_required'
        path = os.environ.get('NOMOSMART_R13_INDEX_EVIDENCE')
        if not path:
            pytest.skip('BLOCKED: R13 run-owned upload and real embedding evidence are required')
        scope = json.loads(Path(path).read_bytes())
        assert settings.opensearch_url.rstrip('/') == 'https://opensearch:9200'
        assert settings.opensearch_index_prefix == 'chg305-' + scope['run_id'][:8]
        session_context=get_session_factory()()
        control='chg305_test_control'
    try:
      with session_context as session:
        session.execute(text('SET TRANSACTION READ ONLY'))
        assert session.scalar(text('SELECT run_id FROM '+control+'.ownership')) == UUID(scope['run_id'])
        version = session.get(DocumentVersion, UUID(scope['version_id']))
        project = session.get(Project, version.project_id)
        document = session.get(Document, version.document_id)
        assert str(project.id) == scope['project_id']
        chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id,
            Chunk.status == 'active').order_by(Chunk.chunk_index)))
        batch = load_staging_embeddings(session, project=project, version=version, chunks=chunks)
        assert len(chunks) >= 2 and batch.build.status == 'staged' and batch.build.completed_at is not None
        source = dict(project=project,document=document,version=version,chunks=chunks,
            vectors=batch.vectors,profile=batch.profile)
        LiveOpenSearchStagingIndexAdapter(settings).verify_existing_chunks(**source)
        clone = settings.model_copy(update={'opensearch_index_prefix': settings.opensearch_index_prefix+'-r13-check'})
        adapter = LiveOpenSearchStagingIndexAdapter(clone)
        index = staging_index_name(clone.opensearch_index_prefix, project.id, version.id)
        base = clone.opensearch_url.rstrip('/')+'/'+index
        def request(method, suffix, payload=None):
            req = adapter._request_with_auth(method,base+suffix,
                json.dumps(payload).encode() if payload is not None else None,
                context=clone.opensearch_ssl_context,content_type='application/json')
            with urlopen(req,context=clone.opensearch_ssl_context,timeout=5) as response:
                return json.load(response)
        try:
            adapter.write_chunks(**source)
            request('POST','/_refresh')  # Setup only; product verifier remains read-only.
            yield adapter, source, request
        finally:
            adapter.delete_version(project_id=project.id,version_id=version.id)
            LiveOpenSearchStagingIndexAdapter(settings).verify_existing_chunks(**source)
    finally:
        if engine is not None:engine.dispose()


def test_real_mget_source_filter_and_order(corpus):
    adapter, source, request = corpus
    ids = [f"{source['version'].id}:{c.id}" for c in source['chunks']]
    before = request('POST','/_mget',{'ids':ids})
    adapter.verify_existing_chunks(**source)
    adapter.verify_existing_chunks(**dict(source,chunks=list(reversed(source['chunks'])),vectors=list(reversed(source['vectors']))))
    assert request('POST','/_mget',{'ids':ids}) == before
    with pytest.raises(HTTPError) as failure:
        request('POST','/_mget',{'ids':ids,'_source':['chunk_id']})
    assert failure.value.code == 400  # Confirm the original real-service failure.


@pytest.mark.parametrize('field',['index_scope','project_id','document_id','document_version_id',
    'chunk_id','chunk_index','retrieval_text','embedding_content_hash','embedding_vector',
    'embedding_profile_id','mapping_version'])
def test_rejects_each_real_persisted_field_mismatch(corpus,field):
    adapter, source, request = corpus
    ident=f"{source['version'].id}:{source['chunks'][0].id}"
    data=request('GET','/_doc/'+ident)['_source']
    if field=='embedding_vector':
        changed=list(data[field]);changed[0]+=0.125  # Deliberate corruption of a genuine vector.
    elif isinstance(data[field],int):changed=data[field]+1
    else:changed='wrong-'+str(data[field])
    request('POST','/_update/'+ident,{'doc':{field:changed}})
    request('POST','/_refresh')
    with pytest.raises(AppError) as failure:adapter.verify_existing_chunks(**source)
    assert failure.value.code=='vector_index_not_ready'


@pytest.mark.parametrize('same_count',[False,True])
def test_rejects_missing_id_even_when_total_matches(corpus,same_count):
    adapter, source, request = corpus
    ident=f"{source['version'].id}:{source['chunks'][0].id}"
    original=request('GET','/_doc/'+ident)['_source']
    request('DELETE','/_doc/'+ident)
    if same_count:request('PUT','/_doc/wrong-id',original)
    request('POST','/_refresh')
    with pytest.raises(AppError) as failure:adapter.verify_existing_chunks(**source)
    assert failure.value.code=='vector_index_not_ready'


def test_real_service_denial_stays_fail_closed(corpus):
    adapter, source, _ = corpus
    denied=LiveOpenSearchStagingIndexAdapter(adapter.settings.model_copy(update={
        'opensearch_password':SecretStr('deliberately-invalid-owned-test-password')}))
    with pytest.raises(AppError) as failure:denied.verify_existing_chunks(**source)
    assert failure.value.code=='vector_index_not_ready'
    assert isinstance(failure.value.__cause__,HTTPError) and failure.value.__cause__.code in (401,403)


def _current413_existing_vector_corpus(settings,current):
    from hashlib import sha256
    from uuid import uuid4
    import httpx
    from scripts.chg413_runtime import Scope
    from app.db.models import (ActiveVersionManifest,EmbeddingBuild,AIModel,
        AIModelUsageEvent,ApprovalRequest,PipelineRun,ReviewRecord,GraphSyncJob)
    from sqlalchemy.orm import load_only
    from scripts.current_e2e_governance_fixture import read_private
    from app.domain.embeddings import load_published_embeddings
    from app.domain.review_publish import LiveOpenSearchPublishedAdapter
    from owned_service_scope import verify_owned_services
    authority=Scope()
    assert current['run_id']==authority.op and str(verify_owned_services(settings))==authority.op
    assert current['native_metadata_only'] is True
    root=authority.root
    reference=read_private(root/'retained-publication.json')
    assert reference['run_uuid']==authority.op and reference['case']=='CHG-413-retained-publication-readback'
    proof_path=root/'root-item2/retained-publication-core-bound.json'
    assert reference['actual_readback']==str(proof_path)
    assert sha256(proof_path.read_bytes()).hexdigest()==reference['actual_readback_sha256']
    retained=read_private(proof_path)
    assert retained['run_uuid']==authority.op and retained['no_business_writes'] is True
    assert retained['new_provider_calls']==0 and retained['protected_core_database']==authority.db['core_database']
    genuine={key:retained[key] for key in ('project_id','document_id','version_id','pipeline_id')}

    nonce=uuid4().hex
    prefix=settings.opensearch_index_prefix+'r13-413-'+nonce
    created=[]
    with get_session_factory()() as session, httpx.Client(base_url=settings.opensearch_url,
        verify=settings.opensearch_httpx_verify,auth=(settings.opensearch_username.get_secret_value(),
        settings.opensearch_password.get_secret_value()),trust_env=False,follow_redirects=False,timeout=15) as client:
        session.execute(text('SET TRANSACTION READ ONLY'))
        assert session.scalar(text('SELECT current_database()'))=='nms413_00621cbd_current'
        assert str(session.scalar(text('SELECT run_id FROM current_test_control.ownership')))==authority.op
        version=session.get(DocumentVersion,UUID(genuine['version_id']))
        project=session.get(Project,UUID(genuine['project_id']));document=session.get(Document,UUID(genuine['document_id']))
        pipeline=session.get(PipelineRun,UUID(genuine['pipeline_id']))
        request_row=session.get(ApprovalRequest,UUID(retained['request_id']))
        assert version and project and document and pipeline and request_row
        for table,identity in [('projects',project.id),('documents',document.id),('document_versions',version.id)]:
            original=authority.sql("SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') FROM "+table+" t WHERE id='"+str(identity)+"';",database=authority.db['core_database']).decode().strip()
            assert original and retained['protected_core_rows'][table]==original
            actual=session.scalar(text("SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') FROM "+table+" t WHERE id=:id"),{'id':identity})
            assert actual==original
        assert project.status=='active' and document.project_id==project.id
        assert version.project_id==project.id and version.document_id==document.id
        assert version.status=='active' and version.published_at and version.lock_version==retained['published_lock']
        assert pipeline.document_version_id==version.id and pipeline.status=='completed'
        assert request_row.document_version_id==version.id and request_row.status=='published'
        usage=list(session.scalars(select(AIModelUsageEvent).where(AIModelUsageEvent.document_version_id==version.id,
            AIModelUsageEvent.id.in_([UUID(x) for x in retained['actual_success_model_events']]))))
        assert {str(x.id) for x in usage}==set(retained['actual_success_model_events'])
        assert all(x.attempted and x.status=='success' and x.source_channel=='pipeline' for x in usage)
        assert all(x.pipeline_run_id in {pipeline.id,None} for x in usage)
        assert all(x.pipeline_run_id==pipeline.id for x in usage if x.model_type=='Chat')
        assert {'Chat','Embedding'} <= {x.model_type for x in usage}
        assert {x.model_type for x in usage}==set(retained['model_types'])
        types=dict(session.execute(select(AIModel.id,AIModel.model_type).where(AIModel.id.in_({x.model_id for x in usage}))).all())
        assert all(types.get(x.model_id)==x.model_type for x in usage)
        reviews=list(session.scalars(select(ReviewRecord).where(ReviewRecord.document_version_id==version.id)))
        assert {x.review_stage for x in reviews if x.status=='approved'}=={'manager_review','owner_review'}
        assert len({x.reviewer_id for x in reviews})==2
        assert session.scalar(select(GraphSyncJob.id).where(GraphSyncJob.document_version_id==version.id,GraphSyncJob.status=='completed'))
        manifest=session.scalar(select(ActiveVersionManifest).where(ActiveVersionManifest.document_version_id==version.id))
        assert manifest and manifest.index_ready and str(manifest.embedding_build_id)==retained['selected_published_build_id']
        build=session.get(EmbeddingBuild,manifest.embedding_build_id)
        assert build and build.status=='published' and build.completed_at is not None
        chunks=list(session.scalars(select(Chunk).where(Chunk.document_version_id==version.id,
            Chunk.status=='active').order_by(Chunk.chunk_index,Chunk.id)))
        assert [str(x.id) for x in chunks]==retained['chunk_ids']
        # Seed the identity map only with genuine nonsecret model metadata.
        # Any unexpected credential access raises rather than loading a key.
        model=session.scalar(select(AIModel).options(load_only(AIModel.id,AIModel.name,
            AIModel.model_type,AIModel.config,AIModel.config_version,raiseload=True)).where(AIModel.id==build.model_id))
        assert model and model.model_type=='Embedding'
        batch=load_published_embeddings(session,project=project,version=version,chunks=chunks,build=build)
        assert len(chunks)>=2 and build.status=='published' and build.completed_at is not None
        assert batch.model is model and len(batch.vectors)==len(chunks)
        from app.domain.markdown_artifacts import resolve_markdown_artifact
        markdown=resolve_markdown_artifact(session,version,require_fingerprint=True)
        assert markdown.status=='available' and markdown.text
        body=markdown.text.encode()
        assert sha256(body).hexdigest()==retained['markdown_sha256'] and len(body)==retained['markdown_bytes']
        genuine['source_text']=markdown.text
        source=dict(project=project,document=document,version=version,chunks=chunks,
            vectors=batch.vectors,profile=batch.profile)
        published=LiveOpenSearchPublishedAdapter(settings)
        published.verify_published_build(document=document,version=version,chunks=chunks,batch=batch)
        proof_name='backend-item2/r13-index-adapter/'+nonce+'/resources.json'
        proof={'operation_uuid':authority.op,'source_document_version':str(version.id),
            'actual_selected_published_build':str(build.id),'actual_provider_vector_count':len(batch.vectors),
            'new_models_or_versions_or_pipeline_states':0,'fresh_staging_workflow_claimed':False,
            'new_provider_calls':0,'indexes':[]}
        authority.record(proof_name,proof)
        adapters=[]
        for label in ('source','check'):
            configured=settings.model_copy(update={'opensearch_index_prefix':prefix+'-'+label})
            update=uuid4()
            index=staging_index_name(configured.opensearch_index_prefix,project.id,version.id)+'-edit-'+update.hex
            assert index.startswith('nms411-00621cbd-')
            from app.domain.index_residue import OWNER_FORMAT
            owner={'format':OWNER_FORMAT,'index_name':index,'project_id':str(project.id),
                'document_id':str(document.id),'document_version_id':str(version.id),
                'update_id':str(update),'project_generation':project.work_generation,
                'expected_lock':version.lock_version,'target_revision':1,
                'target_sha256':sha256(genuine['source_text'].encode()).hexdigest()}
            adapter=LiveOpenSearchStagingIndexAdapter(configured,index_override=index,ownership=owner)
            adapters.append((adapter,index))
        def info(index):
            response=client.get('/'+index)
            if response.status_code==404:return None
            assert response.status_code==200 and set(response.json())=={index}
            value=response.json()[index]
            assert not value.get('aliases'), 'foreign index alias must be preserved'
            from app.domain.index_residue import OWNER_META
            return {'uuid':value['settings']['index']['uuid'],
                'owner':value.get('mappings',{}).get('_meta',{}).get(OWNER_META)}
        try:
            for adapter,index in adapters:
                assert info(index) is None, 'foreign existing index must not be overwritten'
                item={'name':index,'state':'INTENT_BEFORE_WRITE','absent_before_write':True,
                    'owner':adapter.ownership,'native_resource_intent_not_product_update':True}
                proof['indexes'].append(item);created.append((adapter,index,item));authority.record(proof_name,proof)
                adapter.write_chunks(**source)
                identity=info(index);assert identity and identity['owner']==adapter.ownership
                item.update(state='CREATED',uuid=identity['uuid'])
                authority.record(proof_name,proof)
            source_adapter,_=adapters[0];adapter,index=adapters[1]
            def request(method,suffix,payload=None):
                assert method in {'GET','POST','PUT','DELETE'} and suffix.startswith('/') and not suffix.startswith('//')
                req=adapter._request_with_auth(method,settings.opensearch_url.rstrip('/')+'/'+index+suffix,
                    json.dumps(payload).encode() if payload is not None else None,
                    context=settings.opensearch_ssl_context,content_type='application/json')
                with urlopen(req,context=settings.opensearch_ssl_context,timeout=10) as response:
                    return json.load(response)
            request('POST','/_refresh')
            yield adapter,source,request
            source_adapter.verify_existing_chunks(**source)
            published.verify_published_build(document=document,version=version,chunks=chunks,batch=batch)
        finally:
            for adapter,index,item in reversed(created):
                actual=info(index)
                if actual is not None:
                    assert actual['owner']==item['owner'], 'foreign owner metadata must be preserved'
                    if 'uuid' in item:
                        assert actual['uuid']==item['uuid'], 'replaced index must not be deleted'
                    else:
                        item.update(uuid=actual['uuid'],creation_result='OWN_OWNER_META_CONFIRMED_AFTER_PARTIAL_WRITE')
                        authority.record(proof_name,proof)
                    adapter.delete_version(project_id=project.id,version_id=version.id)
                    assert info(index) is None
                item.update(state='EXACT_CREATED_UUID_ABSENT')
                authority.record(proof_name,proof)
            proof['retained_source_SQL_and_published_index_not_written']=True
            authority.record(proof_name,proof)
