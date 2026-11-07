"""Real PostgreSQL/native contracts; no Provider, fake response or auth claim.

The caller supplies a run-owned network-isolated PostgreSQL socket/ownership
row, or the canonical suite supplies its verified TLS service scope. Every
mutation is rolled back; source is loaded normally.
"""
from __future__ import annotations

import json
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import AIModel, AIModelUsageEvent, Document, DocumentVersion, OutboxEvent, PipelineRun, PipelineRunStep, Project
from app.domain.document_imports import start_document_extraction
from app.domain.document_layout import estimated_layout_block_height, paginate_layout_blocks
from app.domain.extraction_pipeline import AUTO_EXTRACTION_STEPS, REVIEW_AND_PUBLICATION_STEPS, _create_structure_chunks, _parse_document_payload
from app.domain.public_api_controls import encrypt_payload
from app.domain.markdown_structure import MarkdownStructureParser
from owned_service_scope import verify_owned_services


@pytest.fixture
def native_workspace(request):
    if os.environ.get('NOMOSMART_RETIREMENT_RUN'):
        run_id=UUID(os.environ['NOMOSMART_RETIREMENT_RUN'])
        url=os.environ['NOMOSMART_RETIREMENT_DATABASE_URL']
        assert 'host=/var/run/postgresql' in url and 'localhost' not in url
        engine=create_engine(url,hide_parameters=True)
        with engine.connect() as conn:
            assert conn.scalar(text('SELECT run_id FROM chg334_control')) == run_id
        settings=Settings(_env_file=None,app_env='development',database_url=url,app_encryption_key=os.urandom(32).hex(),embedding_capabilities_file=os.environ['NOMOSMART_RETIREMENT_CAPABILITIES'])
    else:
        # The complete canonical backend suite already supplies verified TLS
        # services. Reuse its actual ownership guard, never substitute a flag
        # or demand a change-specific database from every future suite.
        settings=get_settings()
        verify_owned_services(settings)
        engine=create_engine(settings.database_url.get_secret_value(),hide_parameters=True)
    with Session(engine,expire_on_commit=False) as session:
        # Other genuine isolated tests may already have unrelated outbox rows.
        # Verify the exact delta instead of assuming an empty shared database.
        session.info['outbox_before']=session.scalar(select(func.count()).select_from(OutboxEvent))
        session.info['pipeline_before']=session.scalar(select(func.count()).select_from(PipelineRun))
        if getattr(request.node, 'callspec', None) and request.node.callspec.params.get('scenario') == 'no_model':
            for row in session.scalars(select(AIModel).where(AIModel.model_type == 'OCR', AIModel.is_default.is_(True))):
                row.is_default = False
            session.flush()
        project=Project(name='Native maintenance control',status='active');session.add(project);session.flush()
        document=Document(project_id=project.id,document_code=uuid4().hex,title='Native source',source_type='file_upload');session.add(document);session.flush()
        version=DocumentVersion(project_id=project.id,document_id=document.id,version_major=1,extraction_revision=0,version_label='v1',status='draft',canonical_extension='.md',storage_bucket='owned-native-input',storage_key=uuid4().hex,chunk_strategy={});session.add(version);session.flush()
        try:yield session,settings,project,document,version
        finally:
            assert session.scalar(select(func.count()).select_from(AIModelUsageEvent).where(AIModelUsageEvent.project_id==project.id)) == 0
            session.rollback()
    engine.dispose()


def test_context_bound_public_payload_roundtrip_and_tamper_rejection():
    settings=Settings(_env_file=None,app_env='development',app_encryption_key=os.urandom(32).hex())
    identity=uuid4();value={'native':['exact',23]};encrypted=encrypt_payload(settings,identity,'answer',value)
    cipher=EnvelopeCipher(settings.encryption_key_bytes)
    assert json.loads(cipher.decrypt(encrypted,context=f'public-response:{identity}:answer')) == value
    for context in [f'public-response:{uuid4()}:answer',f'public-response:{identity}:citations']:
        with pytest.raises(AppError,match='Encrypted value'):cipher.decrypt(encrypted,context=context)
    with pytest.raises(AppError):cipher.decrypt('v0:'+encrypted.split(':',1)[1],context=f'public-response:{identity}:answer')


def test_formal_queue_persists_steps_and_outbox_without_dispatch(native_workspace):
    session,settings,project,document,version=native_workspace
    # OCRSIM-005: native Markdown queues without any OCR model or credential.
    # No worker is dispatched; this proves persistence, never provider success.
    run=start_document_extraction(session=session,settings=settings,project=project,document=document,version=version,actor_user_id=None,requested_ocr_model_id=None,force_ocr=False)
    assert run.status == version.status == 'queued'
    assert version.ocr_model_id is None
    assert version.chunk_strategy['ocr_snapshot']['input_mode'] == 'direct_text'
    steps=session.scalars(select(PipelineRunStep).where(PipelineRunStep.run_id==run.id)).all()
    assert {row.step_name for row in steps} == set(AUTO_EXTRACTION_STEPS+REVIEW_AND_PUBLICATION_STEPS)
    events=session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id==run.id)).all()
    assert len(events)==1 and events[0].status=='pending'
    assert events[0].payload['pipeline_run_id']==str(run.id)
    assert session.scalar(select(func.count()).select_from(PipelineRun))==session.info['pipeline_before']+1
    assert session.scalar(select(func.count()).select_from(PipelineRun).where(PipelineRun.project_id==project.id))==1
    with pytest.raises(AppError) as error:
        start_document_extraction(session=session,settings=settings,project=project,document=document,version=version,actor_user_id=None,requested_ocr_model_id=None,force_ocr=False)
    assert error.value.code=='document_version_not_ready'
    assert session.scalar(select(func.count()).select_from(OutboxEvent))==session.info['outbox_before']+1


@pytest.mark.parametrize('scenario,expected',[('legacy','unsupported_upload_type'),('no_model','ocr_model_required'),('credential','ocr_model_credential_required'),('missing_source','document_source_unavailable')])
def test_formal_queue_rejects_before_persistence(native_workspace,scenario,expected):
    session,settings,project,document,version=native_workspace
    requested=None
    if scenario=='legacy':version.canonical_extension='.doc'
    if scenario in {'no_model', 'credential'}:
        # PDF alone requires native model capability and a credential. Native
        # Markdown intentionally no longer reaches these retired assumptions.
        version.canonical_extension='.pdf'
    if scenario=='credential':
        from copy import deepcopy
        from app.domain.ocr_capabilities import normalize_native_capabilities
        # Reuse real configured capability metadata only. Never read a model
        # credential or manufacture a provider response to satisfy this guard.
        config=None
        for candidate in session.scalars(select(AIModel.config).where(AIModel.model_type=='OCR', AIModel.provider=='OpenAI')):
            try:normalize_native_capabilities(candidate)
            except AppError:continue
            config=deepcopy(candidate);break
        assert config is not None, 'A genuine native capability configuration is required'
        model=AIModel(name='Owned credential rejection',model_type='OCR',provider='OpenAI',is_active=True,is_default=False,config=config)
        session.add(model);session.flush();requested=model.id
        assert model.api_key_encrypted is None and model.api_key_secret_ref is None
    if scenario=='missing_source':version.storage_key=None
    with pytest.raises(AppError) as error:
        start_document_extraction(session=session,settings=settings,project=project,document=document,version=version,actor_user_id=None,requested_ocr_model_id=requested,force_ocr=False)
    assert error.value.code==expected
    assert session.scalar(select(func.count()).select_from(PipelineRun))==session.info['pipeline_before']
    assert session.scalar(select(func.count()).select_from(PipelineRun).where(PipelineRun.project_id==project.id))==0
    assert session.scalar(select(func.count()).select_from(OutboxEvent))==session.info['outbox_before']


def test_current_chunker_keeps_exact_unicode_source_and_complete_table(native_workspace):
    session,settings,project,document,version=native_workspace
    model=AIModel(name='Native capacity only',model_type='Embedding',provider='OpenAI',is_active=True,is_default=False,config={'model_name':'text-embedding-3-small','input_token_limit':8192,'tokenizer_encoding':'cl100k_base'});session.add(model);session.flush();project.embedding_model_id=model.id
    source='\nFirst 🚀\n\n\n  Second\n\n| Key | Value |\n| --- | --- |\n| Mode | Native |\n'
    chunks=_create_structure_chunks(session,settings,project,document,version,source)
    assert chunks
    assert version.chunk_strategy['chunker_version']=='structure-chunker-v3'
    table_chunks=[chunk for chunk in chunks if chunk.content_type=='table']
    assert len(table_chunks)==1
    table_chunk=table_chunks[0]
    parsed=[node for node in MarkdownStructureParser().parse(table_chunk.display_markdown).nodes if node.type=='table']
    assert len(parsed)==1
    assert parsed[0].metadata['headers']==['Key','Value']
    assert parsed[0].metadata['rows']==[['Mode','Native']]
    # CUTQUALITY-003: header is repeated readable context; body rows retain
    # their actual canonical ranges. It must never become invented body text.
    header=table_chunk.chunk_strategy['repeated_context']
    assert source[header['start_offset']:header['end_offset']].strip()=='| Key | Value |'
    assert table_chunk.chunk_strategy['row_start']==table_chunk.chunk_strategy['row_end']==1
    rows=table_chunk.chunk_strategy['row_source_ranges']
    assert len(rows)==1 and source[rows[0]['start_offset']:rows[0]['end_offset']].strip()=='| Mode | Native |'
    assert table_chunk.markdown_content.strip()=='| Mode | Native |' 
    for chunk in chunks:
        assert source[chunk.start_offset:chunk.end_offset]==chunk.markdown_content
        for mapping in chunk.source_mapping:
            assert mapping['mapping_status']=='resolved' and mapping['offset_unit']=='unicode_code_point'
            assert source[mapping['markdown_start_offset']:mapping['markdown_end_offset']]
    assert model.api_key_encrypted is None and model.api_key_secret_ref is None


def test_actual_parser_rejection_and_lossless_payload():
    settings=Settings(_env_file=None,app_env='development')
    source='  Native 🚀\n\nSecond  '
    parsed=_parse_document_payload(settings,DocumentVersion(canonical_extension='.md',chunk_strategy={'source_text':source}))
    assert parsed['text']==source.strip() and parsed['canonical_markdown']==source
    assert _parse_document_payload(settings,DocumentVersion(canonical_extension='.pdf',chunk_strategy={'force_ocr':True}))['text']==''
    # DOCFMT-002/004 replaced the retired per-parser extension errors.
    for extension,expected in [('.doc','unsupported_upload_type'),('.docx','unsupported_upload_type'),('.bin','unsupported_upload_type')]:
        with pytest.raises(AppError) as error:_parse_document_payload(settings,DocumentVersion(canonical_extension=extension,chunk_strategy={}))
        assert error.value.code==expected


def test_actual_domain_layout_capacity():
    assert estimated_layout_block_height({'type':'table','rows':[['A','B'],['1','2']]})>0
    assert estimated_layout_block_height({'type':'code','text':'a\nb'})>0
    assert len(paginate_layout_blocks([{'type':'paragraph','text':'x'*1200} for _ in range(20)]))>1
