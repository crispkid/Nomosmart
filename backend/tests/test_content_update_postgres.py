"""Native PostgreSQL component contracts; not OIDC/provider/E2E acceptance."""
import json
import hashlib
import os
from pathlib import Path
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (AIModel, User, Role, RoleUser, RolePermission, Project, ProjectMember, ProjectOwner, Document,
    DocumentVersion, DocumentContentState, DocumentContentUpdate, PipelineRun, Chunk, ChunkTag, Tag, DocumentVersionTag)
from app.domain.content_diff import text_digest
from app.domain.document_content_updates import can_edit_content, content_edit_mode, _prepare_chunks, _preserve_legacy_corrections
from app.domain.markdown_artifacts import resolve_markdown_artifact
from app.domain.extraction_pipeline import _create_structure_chunks, _attach_chunk_tag
from app.domain.graph_projection import build_graph_projection
from app.domain.chunk_representations import build_manual_chunk_representation


@pytest.fixture
def database_scope():
    if os.environ.get('NOMOSMART_CURRENT_LIVE_CONTEXT'):
        from current_native_support import native_database
        reference = os.environ.get('NOMOSMART_CURRENT_NATIVE_DATABASE_SCOPE')
        standard = str(Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).with_name('native-database-scope.json'))
        options = {'scope_reference418': reference} if reference and reference != standard else {}
        with native_database(**options) as engine, Session(engine, expire_on_commit=False) as session:
            try:
                yield session
            finally:
                session.rollback()
        return
    path=os.environ.get('NOMOSMART_CHG315_TEST_SCOPE')
    if not path:
        pytest.skip('BLOCKED: run-owned PostgreSQL scope is unavailable')
    scope_path=Path(path)
    assert not scope_path.is_symlink() and scope_path.stat().st_uid == os.getuid() and scope_path.stat().st_mode & 0o077 == 0
    scope=json.loads(scope_path.read_text())
    assert str(scope_path.parent).startswith('/private/tmp/nomosmart-chg315-') and scope['host']=='127.0.0.1'
    url=URL.create('postgresql+psycopg2',username=scope['username'],password=scope['password'],host=scope['host'],port=scope['port'],
        database='chg315_upgrade',query={'sslmode':'verify-full','sslrootcert':scope['ca']})
    engine=create_engine(url,hide_parameters=True)
    root=Path(__file__).resolve().parents[2]
    contract=json.loads((root/'deploy/migrations/release-contract.json').read_text())
    required=contract['required_version']
    target=contract['targets']['SQL']
    assert hashlib.sha256((root/'sql/migrations'/target['file']).read_bytes()).hexdigest() == target['sha256']
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()')) is True
        assert connection.scalar(text("SELECT max(version::int) FROM public.flyway_schema_history WHERE success")) == int(required)
        applied=connection.execute(text("SELECT script, checksum FROM public.flyway_schema_history WHERE version=:version AND success"),
            {'version':required}).one()
        assert tuple(applied) == (target['file'],target['checksum'])
    with Session(engine,expire_on_commit=False) as session:
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture
def workspace(database_scope):
    session=database_scope
    user=User(keycloak_user_id='chg315-'+uuid4().hex,display_name='CHG315 component actor')
    role=Role(name='chg315-'+uuid4().hex,is_active=True)
    project=Project(name='CHG315 native component',status='active')
    # A real database model/capacity input for native parsing only. No key,
    # Provider response, vector, completed build or readiness is supplied.
    model=AIModel(name='chg315-native-'+uuid4().hex,model_type='Embedding',provider='OpenAI',
        config={'model_name':'text-embedding-3-small'},is_active=True,config_version=1)
    session.add_all([user,role,project,model]);session.flush()
    project.embedding_model_id=model.id
    session.add_all([RoleUser(role_id=role.id,user_id=user.id),RolePermission(role_id=role.id,module_name='Menu',function_name='KnowledgeProjects',can_view=True),
        ProjectMember(project_id=project.id,user_id=user.id,project_role='editor',created_at=datetime.now(UTC))])
    document=Document(project_id=project.id,document_code=uuid4().hex,title='Component source',source_type='file_upload')
    session.add(document);session.flush()
    version=DocumentVersion(project_id=project.id,document_id=document.id,version_major=1,extraction_revision=0,version_label='v1.0',status='processing',chunk_strategy={})
    session.add(version);session.flush()
    return session,user,role,project,document,version


def test_real_migration_application_privileges(database_scope):
    assert database_scope.scalar(text("SELECT has_table_privilege(current_user,'public.document_content_states','SELECT,INSERT,UPDATE,DELETE')"))
    assert database_scope.scalar(text("SELECT has_table_privilege(current_user,'public.document_content_update_jobs','SELECT,INSERT,UPDATE,DELETE')"))


def test_governance_owner_does_not_promote_viewer(workspace):
    session,user,role,project,_,_=workspace
    member=session.get(ProjectMember,(project.id,user.id,'editor'))
    member.project_role='viewer'
    session.add(ProjectOwner(project_id=project.id,user_id=user.id,created_at=datetime.now(UTC)));session.flush()
    assert not can_edit_content(session,project.id,user.id)


def test_live_permission_and_disabled_user_changes(workspace):
    session,user,role,project,_,_=workspace
    assert can_edit_content(session,project.id,user.id)
    role.is_active=False;session.flush()
    assert not can_edit_content(session,project.id,user.id)
    role.is_active=True;user.is_active=False;session.flush()
    assert not can_edit_content(session,project.id,user.id)


def test_committed_canonical_hash_and_scope_are_checked(workspace):
    session,user,_,project,document,version=workspace
    value='修正後🙂全文'
    state=DocumentContentState(document_version_id=version.id,project_id=project.id,document_id=document.id,current_markdown=value,
        current_sha256=text_digest(value),content_revision=1,original_artifact={},updated_by=user.id,updated_at=datetime.now(UTC))
    session.add(state);session.flush()
    assert resolve_markdown_artifact(session,version,require_fingerprint=True).text == value
    state.current_sha256='0'*64;session.flush()
    assert resolve_markdown_artifact(session,version).status == 'invalid'


@pytest.mark.parametrize("pipeline_status", ["submission_ready", "completed"])
def test_extraction_terminal_status_enables_candidate_editing(workspace, pipeline_status):
    # Native database lifecycle inputs test the permission/state rule only;
    # no provider artifact or full extraction success receipt is fabricated.
    session,user,_,project,document,version=workspace
    version.status="submission_ready"
    session.add(PipelineRun(project_id=project.id,document_id=document.id,document_version_id=version.id,
        project_generation=project.work_generation,run_type="document_extraction",status=pipeline_status,
        progress_percent=100,created_at=datetime.now(UTC)))
    session.flush()
    assert content_edit_mode(session,project,version,can_edit_content(session,project.id,user.id)) == ("overwrite_candidate", None)
    assert content_edit_mode(session,project,version,False) == ("readonly", "project_editor_required")
    version.status="pending_manager_review";session.flush()
    assert content_edit_mode(session,project,version,True) == ("readonly", "content_edit_review_locked")


@pytest.mark.parametrize("pipeline_status", ["queued", "running", "failed"])
def test_unfinished_extraction_remains_readonly(workspace, pipeline_status):
    session,_,_,project,document,version=workspace
    version.status="submission_ready"
    session.add(PipelineRun(project_id=project.id,document_id=document.id,document_version_id=version.id,
        project_generation=project.work_generation,run_type="document_extraction",status=pipeline_status,
        progress_percent=20,created_at=datetime.now(UTC)))
    session.flush()
    assert content_edit_mode(session,project,version,True) == ("readonly", "content_edit_in_progress")


def test_graph_digest_changes_even_when_node_count_does_not(workspace):
    session,user,_,project,document,version=workspace
    state=DocumentContentState(document_version_id=version.id,project_id=project.id,document_id=document.id,current_markdown='對像',
        current_sha256=text_digest('對像'),content_revision=1,original_artifact={},updated_by=user.id,updated_at=datetime.now(UTC))
    session.add(state);session.flush()
    before=build_graph_projection(session,project,document,version,[])
    state.current_markdown='對象';state.current_sha256=text_digest('對象');state.content_revision=2;session.flush()
    after=build_graph_projection(session,project,document,version,[])
    assert len(before.graph['nodes']) == len(after.graph['nodes'])
    assert before.source_digest != after.source_digest
    assert after.binding()['content_binding']['canonical_sha256'] == state.current_sha256


def test_real_structure_preparation_keeps_manual_boundary(workspace):
    session,user,_,project,document,version=workspace
    old='# 規定\n\n手動範圍🙂\n\n原始段落。\n'
    new=old.replace('原始段落','修正段落')
    settings=Settings(_env_file=None,app_env='test')
    _create_structure_chunks(session,settings,project,document,version,old)
    start=old.index('手動範圍');end=start+len('手動範圍🙂')
    representation=build_manual_chunk_representation(raw_markdown=old[start:end],document_title=document.title,inherited_heading_path=['規定'])
    manual=Chunk(id=uuid4(),project_id=project.id,document_id=document.id,document_version_id=version.id,chunk_index=100,
        content=representation.display_text,markdown_content=old[start:end],display_markdown=representation.display_markdown,
        retrieval_text=representation.retrieval_text,embedding_content_hash=representation.embedding_content_hash,content_hash=representation.content_hash,
        heading_path=['規定'],heading_level=1,start_offset=start,end_offset=end,source_mapping=[],chunk_strategy=representation.processing_metadata,
        is_manual_edited=True,status='active',created_at=datetime.now(UTC),updated_at=datetime.now(UTC))
    session.add(manual)
    state=DocumentContentState(document_version_id=version.id,project_id=project.id,document_id=document.id,current_markdown=old,
        current_sha256=text_digest(old),content_revision=1,original_artifact={},updated_by=user.id,updated_at=datetime.now(UTC))
    session.add(state)
    # This is a running parser component input, never a fabricated completed
    # extraction, model result or ready receipt.
    pipeline=PipelineRun(project_id=project.id,document_id=document.id,document_version_id=version.id,project_generation=project.work_generation,
        run_type='content_structure_component',status='running',progress_percent=0,triggered_by=user.id,created_at=datetime.now(UTC))
    session.add(pipeline);session.flush()
    job=DocumentContentUpdate(project_id=project.id,document_id=document.id,document_version_id=version.id,source_version_id=version.id,
        pipeline_run_id=pipeline.id,actor_user_id=user.id,base_revision=1,target_revision=2,base_sha256=text_digest(old),target_sha256=text_digest(new),
        expected_lock=version.lock_version,project_generation=project.work_generation,pending_markdown=new,status='running',step_name='parse_structure',checkpoint={})
    session.add(job);session.flush()
    _prepare_chunks(session,settings,project,document,version,job)
    prepared=list(session.scalars(select(Chunk).where(Chunk.document_version_id==version.id,Chunk.status=='pending_content_update')))
    preserved=[chunk for chunk in prepared if chunk.is_manual_edited]
    assert len(preserved)==1 and preserved[0].markdown_content=='手動範圍🙂'
    assert preserved[0].start_offset==new.index('手動範圍')
    assert preserved[0].heading_path==['規定']
    assert preserved[0].chunk_strategy['content_update_source_chunk_id']==str(manual.id)
    assert state.current_markdown==old
    assert job.status=='running' and job.checkpoint['structure_prepared']


def test_review_lock_remains_readonly_without_models(workspace):
    session,_,_,project,_,version=workspace
    version.status='pending_manager_review';session.flush()
    assert content_edit_mode(session,project,version,True)==('readonly','content_edit_review_locked')


def test_legacy_manual_correction_is_kept_outside_user_edit(workspace):
    session,_,_,project,document,version=workspace
    session.get(AIModel,project.embedding_model_id).config={'model_name':'text-embedding-3-small','input_token_limit':32}
    settings=Settings(_env_file=None,app_env='test',target_chunk_tokens=16,max_chunk_tokens=32,min_chunk_tokens=1,chunk_overlap_tokens=4)
    old='# 第一節\n\n適用對像。\n\n# 第二節\n\n其他內容。\n'
    original=_create_structure_chunks(session,settings,project,document,version,old)[0]
    original.status='superseded';session.flush()
    fields={column.key:getattr(original,column.key) for column in Chunk.__table__.columns}
    fields.update(id=uuid4(),status='active',is_manual_edited=True,parent_chunk_id=original.id,
        markdown_content=original.markdown_content.replace('對像','對象'))
    corrected=Chunk(**fields);session.add(corrected);session.flush()
    merged,ranges=_preserve_legacy_corrections(session,version,old,old.replace('其他內容','已修改內容'))
    assert '對象' in merged and '已修改內容' in merged and '對像' not in merged
    assert ranges and merged[ranges[0]['start']:ranges[0]['end']]==corrected.markdown_content


def test_explicit_full_source_change_replaces_affected_legacy_text(workspace):
    session,_,_,project,document,version=workspace
    settings=Settings(_env_file=None,app_env='test')
    old='適用對像。\n'
    original=_create_structure_chunks(session,settings,project,document,version,old)[0]
    original.status='superseded';session.flush()
    fields={column.key:getattr(original,column.key) for column in Chunk.__table__.columns}
    fields.update(id=uuid4(),status='active',is_manual_edited=True,parent_chunk_id=original.id,markdown_content='適用對象。\n')
    session.add(Chunk(**fields));session.flush()
    merged,ranges=_preserve_legacy_corrections(session,version,old,'所有人均適用。\n')
    assert merged=='所有人均適用。\n' and ranges==[]


def test_corrected_source_reuse_is_explicitly_skipped_ocr(workspace):
    from app.domain.extraction_pipeline import _execute_step,LiveOpenSearchStagingIndexAdapter,LiveOnlyOCRAdapter
    session,user,_,project,document,version=workspace
    value='# 修正後全文\n\n正確內容🙂\n'
    session.add(DocumentContentState(document_version_id=version.id,project_id=project.id,document_id=document.id,current_markdown=value,
        current_sha256=text_digest(value),content_revision=2,original_artifact={},updated_by=user.id,updated_at=datetime.now(UTC)))
    pipeline=PipelineRun(project_id=project.id,document_id=document.id,document_version_id=version.id,project_generation=project.work_generation,
        run_type='source_reuse_component',status='running',progress_percent=0,created_at=datetime.now(UTC))
    session.add(pipeline);session.flush()
    settings=Settings(_env_file=None,app_env='test')
    # Actual adapters are present, not patched or replaced. The committed
    # canonical branch doesn't call either adapter or claim OCR success.
    staging,ocr=LiveOpenSearchStagingIndexAdapter(settings),LiveOnlyOCRAdapter()
    parsed=_execute_step(session,settings,staging,ocr,project,document,version,pipeline,'parse_document',{})
    result=_execute_step(session,settings,staging,ocr,project,document,version,pipeline,'ocr_extract',{'parse_document':parsed})
    assert parsed.payload['canonical_markdown']==value
    assert result.payload['skipped'] is True and result.payload['reason']=='corrected_source_reuse'
    assert result.payload['text']==value

# CHG-321 native control-plane tests. Real parser and PostgreSQL failures are
# used here; no successful Provider/build/ready receipt is supplied.
@pytest.fixture
def known_failed_update(workspace):
    from app.core.errors import AppError
    session,user,role,project,document,version=workspace
    model=session.get(AIModel,project.embedding_model_id)
    model.config={'model_name':'text-embedding-3-small','input_token_limit':32}
    old='# Committed\n\nShort source.\n'
    new='# Too long\n\n'+'overflow '*200+'.\n'
    settings=Settings(_env_file=None,app_env='test')
    session.add(DocumentContentState(document_version_id=version.id,project_id=project.id,document_id=document.id,
        current_markdown=old,current_sha256=text_digest(old),content_revision=3,original_artifact={},updated_by=user.id,updated_at=datetime.now(UTC)))
    pipeline=PipelineRun(project_id=project.id,document_id=document.id,document_version_id=version.id,
        project_generation=project.work_generation,run_type='document_content_update',status='running',progress_percent=0,
        created_at=datetime.now(UTC))
    session.add(pipeline);session.flush()
    job=DocumentContentUpdate(project_id=project.id,document_id=document.id,document_version_id=version.id,source_version_id=version.id,
        pipeline_run_id=pipeline.id,actor_user_id=user.id,base_revision=3,target_revision=4,base_sha256=text_digest(old),target_sha256=text_digest(new),
        expected_lock=version.lock_version,project_generation=project.work_generation,pending_markdown=new,status='running',step_name='parse_structure',checkpoint={})
    session.add(job);session.flush()
    with pytest.raises(AppError) as error:
        with session.begin_nested():
            _prepare_chunks(session,settings,project,document,version,job)
    assert error.value.code=='chunk_atomic_unit_too_large'
    job.status,job.error_code='failed',error.value.code
    pipeline.status='failed'
    job.checkpoint={'chunking_issue':error.value.details['chunking_issue']}
    session.flush()
    return workspace,job,settings,old


def recovery_payload(document, version, old, **overrides):
    from app.api.schemas import ContentUpdatePayload
    return ContentUpdatePayload(document_lock_version=document.lock_version,lock_version=version.lock_version,
        base_content_revision=3,base_canonical_sha256=text_digest(old),markdown=overrides.pop('markdown',old),**overrides)


def test_known_native_failure_reopens_editor_without_changing_committed_source(known_failed_update):
    from app.domain.document_content_updates import recoverable_failed_update
    workspace,job,_,old=known_failed_update
    session,user,_,project,_,version=workspace
    assert recoverable_failed_update(session,project,version).id==job.id
    assert content_edit_mode(session,project,version,True)==('overwrite_candidate',None)
    assert content_edit_mode(session,project,version,False)==('readonly','project_editor_required')
    assert session.get(DocumentContentState,version.id).current_markdown==old


@pytest.mark.parametrize('guard',['unknown','claim','lease','new_generation','stale_lock','published','review','hash'])
def test_failure_recovery_keeps_safety_guards(known_failed_update,guard):
    from app.domain.document_content_updates import recoverable_failed_update
    workspace,job,_,_=known_failed_update
    session,_,_,project,_,version=workspace
    if guard=='unknown': job.checkpoint={**job.checkpoint,'provider_inflight':'embedding'}
    if guard=='claim': job.claim_token=uuid4()
    if guard=='lease': job.lease_expires_at=datetime.now(UTC)
    if guard=='new_generation': project.work_generation+=1
    if guard=='stale_lock': version.lock_version+=1
    if guard=='published': version.published_at=datetime.now(UTC)
    if guard=='review': version.status='pending_manager_review'
    if guard=='hash': job.target_sha256='0'*64
    session.flush()
    assert recoverable_failed_update(session,project,version) is None


def test_cancel_removes_failed_full_text_preserves_failure_and_source(known_failed_update):
    from app.domain.document_content_updates import cancel_failed_update,effective_pipeline
    workspace,job,_,old=known_failed_update
    session,user,_,project,document,version=workspace
    result=cancel_failed_update(session,project,document,version,job,recovery_payload(document,version,old),user.id)
    session.flush()
    assert result['status']=='recovery_cancelled' and not result['changed']
    assert job.status=='cancelled' and job.pending_markdown is None
    assert job.error_code=='chunk_atomic_unit_too_large'
    assert session.get(DocumentContentState,version.id).current_markdown==old
    assert effective_pipeline(session,version.id) is None  # No invented success.
    assert version.status=='failed'


def test_corrected_save_allocates_unused_revision_atomically(known_failed_update):
    from app.domain.document_content_updates import queue_content_update
    workspace,job,settings,old=known_failed_update
    session,user,_,project,document,version=workspace
    result=queue_content_update(session,project,document,version,
        recovery_payload(document,version,old,markdown=old.replace('Short','Corrected'),recover_update_id=job.id),user.id,settings)
    session.flush()
    assert result['content_revision']==5 and result['changed']
    assert result['document_version_id']==str(version.id)
    assert job.status=='cancelled' and job.target_revision==4 and job.pending_markdown is None
    assert session.get(DocumentContentState,version.id).content_revision==3
    assert session.get(DocumentContentState,version.id).current_markdown==old
    assert session.scalar(select(DocumentContentUpdate).where(DocumentContentUpdate.id!=job.id,
        DocumentContentUpdate.document_version_id==version.id)).status=='queued'


def test_recovery_identity_required_and_noop_cancels_without_new_job(known_failed_update):
    from app.core.errors import AppError
    from app.domain.document_content_updates import queue_content_update
    workspace,job,settings,old=known_failed_update
    session,user,_,project,document,version=workspace
    with pytest.raises(AppError,match='exact failed'):
        queue_content_update(session,project,document,version,recovery_payload(document,version,old),user.id,settings)
    result=queue_content_update(session,project,document,version,
        recovery_payload(document,version,old,recover_update_id=job.id),user.id,settings)
    assert result['status']=='recovery_cancelled'
    assert len(session.scalars(select(DocumentContentUpdate).where(DocumentContentUpdate.document_version_id==version.id)).all())==1

@pytest.mark.parametrize('state',['active','inactive','pending_owner_review','approved','review_cancelled'])
def test_cleanup_never_enters_protected_lifecycle(workspace,state):
    from app.core.errors import AppError
    from app.domain.content_update_cleanup import require_unprotected_version
    session,_,_,_,_,version=workspace
    version.status=state;session.flush()
    with pytest.raises(AppError) as error: require_unprotected_version(session,version)
    assert error.value.code=='content_cleanup_protected'


@pytest.mark.parametrize('index_kind',['selected','wrong_project','foreign_index','bad_suffix'])
def test_index_cleanup_rejects_before_any_transport(workspace,index_kind):
    from app.core.errors import AppError
    from app.domain.content_update_cleanup import delete_retired_index
    from app.domain.extraction_pipeline import staging_index_name
    session,_,_,project,document,version=workspace
    settings=Settings(_env_file=None,app_env='test')
    base=staging_index_name(settings.opensearch_index_prefix,project.id,version.id)
    selected=base+'-edit-'+uuid4().hex
    names={'selected':selected,'wrong_project':staging_index_name(settings.opensearch_index_prefix,uuid4(),version.id),
           'foreign_index':'foreign-production-index','bad_suffix':base+'-edit-invalid'}
    with pytest.raises(AppError) as error:delete_retired_index(session,settings,project,document,version,names[index_kind],selected)
    assert error.value.code=='content_cleanup_protected'


def test_attempted_usage_prevents_edit_recovery(known_failed_update):
    from app.db.models import AIModelUsageEvent
    from app.domain.document_content_updates import recoverable_failed_update
    workspace,job,_,_=known_failed_update
    session,user,_,project,document,version=workspace
    session.add(AIModelUsageEvent(model_id=project.embedding_model_id,model_type='Embedding',provider='OpenAI',
        project_id=project.id,document_id=document.id,document_version_id=version.id,pipeline_run_id=job.pipeline_run_id,
        source_channel='pipeline',usage_purpose='embedding_build',status='failed',attempted=True,attempt_number=1,
        cost_source='unavailable',raw_usage={},metadata_={},created_at=datetime.now(UTC)))
    session.flush()
    assert recoverable_failed_update(session,project,version) is None


def test_cancel_unsuccessful_new_candidate_returns_its_source(known_failed_update):
    from app.domain.document_content_updates import cancel_failed_update
    from app.domain.document_imports import latest_versions
    workspace,job,_,old=known_failed_update
    session,user,_,project,document,version=workspace
    # Only native lifecycle inputs: no Provider or completed build is supplied.
    source=DocumentVersion(project_id=project.id,document_id=document.id,version_major=1,extraction_revision=0,
        version_label='v1.0',status='active',published_at=datetime.now(UTC),chunk_strategy={})
    version.extraction_revision=1;version.version_label='v1.1';session.add(source);session.flush()
    job.source_version_id=source.id;session.flush()
    result=cancel_failed_update(session,project,document,version,job,recovery_payload(document,version,old),user.id)
    session.flush()
    assert result['document_version_id']==str(source.id)
    assert version.status=='review_cancelled' and version.chunk_strategy['content_update_cancelled']
    assert session.get(DocumentContentState,version.id) is None
    assert latest_versions(session,project.id)[0][1].id==source.id


@pytest.mark.parametrize("kind", ["Chunk", "Tag", "TagAssignment", "TagCitation"])
def test_graph_residue_reference_policy_uses_actual_postgres(workspace, kind):
    from app.domain.graph_residue import protection_reason
    from app.db.models import ChatRecord
    from datetime import UTC, datetime
    session,user,role,project,document,version=workspace
    now=datetime.now(UTC)
    if kind=="Chunk":
        chunk=Chunk(project_id=project.id,document_id=document.id,document_version_id=version.id,
                    chunk_index=1,content="",content_hash=text_digest(""),status="superseded",source_mapping=[],
                    chunk_strategy={"source":"native_reference_control"},created_at=now,updated_at=now)
        session.add(chunk);session.flush()
        assert protection_reason(session,"Chunk",str(chunk.id),str(project.id))=="postgres_chunk_identity"
        return
    tag=Tag(project_id=project.id,name="Native residue reference "+uuid4().hex,created_at=now)
    session.add(tag);session.flush()
    if kind=="Tag":
        assert protection_reason(session,"Tag",str(tag.id),str(project.id)) is None
    elif kind=="TagAssignment":
        session.add(DocumentVersionTag(document_version_id=version.id,tag_id=tag.id,source="manual",created_by=user.id,created_at=now));session.flush()
        assert protection_reason(session,"Tag",str(tag.id),str(project.id))=="postgres_tag_assignment"
    else:
        # An unanswered native reference input, not a fabricated successful Chat.
        session.add(ChatRecord(project_id=project.id,document_version_id=version.id,conversation_id=uuid4(),
            question="Native retained reference control",answer=None,reference_docs=[{"tag_id":str(tag.id)}],
            created_by=user.id,asked_at=now,created_at=now));session.flush()
        assert protection_reason(session,"Tag",str(tag.id),str(project.id))=="retained_evidence_reference"


def test_graph_residue_rejects_wrong_identity_and_project(workspace):
    from app.domain.graph_residue import protection_reason
    from app.core.errors import AppError
    session,user,role,project,document,version=workspace
    tag=Tag(project_id=project.id,name="Native wrong scope "+uuid4().hex,created_at=datetime.now(UTC))
    session.add(tag);session.flush()
    for key,pid in [("invalid-id",str(project.id)),(None,str(project.id)),(123,str(project.id)),(str(tag.id),str(uuid4()))]:
        with pytest.raises(AppError) as error:protection_reason(session,"Tag",key,pid)
        assert error.value.code=="graph_identity_conflict"


def test_index_intent_is_committed_before_external_write_and_discovered(workspace):
    from app.domain.index_residue import known_index_names,persist_index_intent
    from app.domain.extraction_pipeline import staging_index_name
    from app.core.config import get_settings
    session,user,role,project,document,version=workspace
    assert known_index_names(session,version.id)==set()
    # This is an unsuccessful native lifecycle input, not a ready extraction.
    pipeline=PipelineRun(project_id=project.id,document_id=document.id,document_version_id=version.id,
        project_generation=project.work_generation,run_type="native_index_intent",status="failed",
        progress_percent=0,triggered_by=user.id,created_at=datetime.now(UTC))
    session.add(pipeline);session.flush()
    job=DocumentContentUpdate(project_id=project.id,document_id=document.id,document_version_id=version.id,
        source_version_id=version.id,pipeline_run_id=pipeline.id,actor_user_id=user.id,base_revision=1,target_revision=2,
        base_sha256=text_digest("native base"),target_sha256=text_digest("native target"),expected_lock=version.lock_version,
        project_generation=project.work_generation,status="failed",step_name="staging_index",checkpoint={"source":"native_failed_input"})
    session.add(job);session.flush();identity=job.id
    name=staging_index_name(get_settings().opensearch_index_prefix,project.id,version.id)+"-edit-"+identity.hex
    intent=persist_index_intent(session,job,project,version,name)
    session.rollback();session.expire_all()
    saved=session.get(DocumentContentUpdate,identity)
    assert saved.status=="failed" and saved.checkpoint["staging_index_intent"]==intent
    assert known_index_names(session,version.id)=={name}
    assert "staging_index" not in saved.checkpoint  # Intent alone is not success.
