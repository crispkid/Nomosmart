"""Native safeguards using actual same-run model receipts, with no new calls.

The history view is limited to the retained real v3 producer. It does not
reconstruct missing historical quota journals or authorize an upstream request.
"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db.models import AIModelUsageEvent, PipelineRun
from app.db.session import get_session_factory
from current_live_support import load_current_context
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from scripts.current_e2e_governance_fixture import read_private
from scripts.ftp_generation_acceptance_environment import zero_model_review_allowed
from scripts.ftp_generation_acceptance_gateway import AdmissionError, LIMITS, Relay
from scripts.ftp_generation_acceptance_history import require_history_prefix


def _native413_accounting_projection(context):
    """Read real retained accounting; never reconstruct a missing wire journal."""
    from scripts.chg413_runtime import Scope
    from app.db.models import OCRDocumentReceipt
    authority=Scope()
    assert Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']) == authority.root/'current-live-context.json'
    # Original approved resource identities remain immutable, even though the
    # content and live PipelineRun were normally archived in412.
    repo=Path(__file__).resolve().parents[2]
    old_approval=json.loads((repo/'docs/CHG-412-APPROVAL.json').read_text())
    resource=old_approval['approved_references']['CHG-412-RESOURCE-PROPOSAL.json']
    raw=Path(resource['path']).read_bytes();assert sha256(raw).hexdigest()==resource['sha256']
    original=json.loads(raw)['owned_live_document']
    proof_path=authority.parent.root/'cleanup412/helm-runtime/full-readback-before-cleanup.json'
    before=sha256(proof_path.read_bytes()).hexdigest();proof=read_private(proof_path)
    recorded={row['id']:row for row in proof['original_accounting']}
    with get_session_factory()() as session:
        receipt=session.scalar(select(OCRDocumentReceipt).where(
            OCRDocumentReceipt.original_document_version_id==UUID(original['version_id'])))
        assert receipt is not None and receipt.status=='confirmed_completed'
        assert receipt.original_run_id==UUID(original['run_id']) and receipt.source_sha256==original['source_sha256']
        events=list(session.scalars(select(AIModelUsageEvent).where(
            AIModelUsageEvent.project_id==UUID(original['project_id'])).order_by(
                AIModelUsageEvent.created_at,AIModelUsageEvent.id)))
        assert len(events)==4 and receipt.usage_event_id in {e.id for e in events}
        assert sorted(e.model_type for e in events)==['Chat','Chat','Embedding','OCR']
        for event in events:
            assert event.attempted and event.status=='success' and event.source_channel=='pipeline'
            old=recorded[str(event.id)]
            for key in ('model_type','usage_purpose','status','attempted','input_tokens','output_tokens','total_tokens'):
                assert getattr(event,key)==old[key]
        rows=[{'sequence':i,'run_id':context['run_id'],'event_id':str(e.id),
               'kind':e.model_type,'purpose':e.usage_purpose,'state':'RESOLVED',
               'usage':dict(e.raw_usage or {}),'input_tokens':e.input_tokens,
               'output_tokens':e.output_tokens,'total_tokens':e.total_tokens}
              for i,e in enumerate(events,1)]
    return rows,proof_path,before


@pytest.fixture
def actual_history(tmp_path):
    context=load_current_context()
    if context['change_id']=='CHG-414':
        from chg418_current_accounting import actual_history414
        yield from actual_history414(context,tmp_path)
        return
    if context['change_id']=='CHG-413':
        rows,proof_path,proof_before=_native413_accounting_projection(context)
        path=tmp_path/'actual-producer-history.json'
        body=json.dumps({'requests':rows,'stopped':False},sort_keys=True).encode()
        path.write_bytes(body);path.chmod(0o600)
        yield context,rows,path,sha256(body).hexdigest()
        assert sha256(path.read_bytes()).hexdigest()==sha256(body).hexdigest()
        assert sha256(proof_path.read_bytes()).hexdigest()==proof_before
        return
    root=Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).parent.parent
    proof_path=root/'integration-switch-real-manifest/shared-draft-real-result.json'
    proof_before=sha256(proof_path.read_bytes()).hexdigest()
    proof=read_private(proof_path)
    assert proof['run_uuid']==context['run_id']
    data=proof['candidate']
    with get_session_factory()() as session:
        run=session.get(PipelineRun,UUID(data['pipeline_id']))
        assert run and run.document_version_id==UUID(data['version_id'])
        events=list(session.scalars(select(AIModelUsageEvent).where(
            AIModelUsageEvent.document_version_id==run.document_version_id,
            AIModelUsageEvent.id.in_([UUID(item) for item in proof['actual_success_model_events']])).order_by(
                AIModelUsageEvent.created_at,AIModelUsageEvent.id)))
        assert len(events)==3 and {str(e.id) for e in events}==set(proof['actual_success_model_events'])
        assert all(e.attempted and e.status=='success' for e in events)
        assert all(e.source_channel=='pipeline' and e.pipeline_run_id in {run.id,None} for e in events)
        assert all(e.pipeline_run_id==run.id for e in events if e.model_type=='Chat')
        rows=[{'sequence':i,'run_id':context['run_id'],'event_id':str(e.id),
            'kind':e.model_type,'purpose':e.usage_purpose,'state':'RESOLVED',
            'usage':dict(e.raw_usage or {}),'input_tokens':e.input_tokens,
            'output_tokens':e.output_tokens,'total_tokens':e.total_tokens}
            for i,e in enumerate(events,1)]
    path=tmp_path/'actual-producer-history.json'
    body=json.dumps({'requests':rows,'stopped':False},sort_keys=True).encode()
    path.write_bytes(body);path.chmod(0o600)
    yield context,rows,path,sha256(body).hexdigest()
    assert sha256(path.read_bytes()).hexdigest()==sha256(body).hexdigest()
    assert sha256(proof_path.read_bytes()).hexdigest()==proof_before


def native_relay(tmp_path):
    """A real zero-request native guard instance, with no usable credentials."""
    folder=tmp_path/'relay';folder.mkdir(mode=0o700)
    previous=folder/'zero-request-input.json'
    previous.write_text(json.dumps({'model_requests':[],'key_reads':0}));previous.chmod(0o600)
    packet={'run_id':'native-admission-only','deadline':time.time()+30,
        'previous_ledger_path':str(previous),'previous_ledger_sha256':sha256(previous.read_bytes()).hexdigest(),
        'models':[{'kind':kind,'id':kind,'model_name':kind,
            'upstream_base':'https://example.invalid/v1','api_key':''} for kind in LIMITS]}
    return Relay(packet,evidence_root=folder),packet,folder


def test_actual_current_usage_prefix_rejects_changed_usage_and_sequence(actual_history):
    context,rows,path,before=actual_history
    journal=json.loads(path.read_bytes())
    require_history_prefix(journal,rows,context['run_id'])
    for change in ('usage','sequence','foreign'):
        invalid=deepcopy(journal)
        if change=='usage':invalid['requests'][0]['input_tokens']=(invalid['requests'][0]['input_tokens'] or 0)+1
        elif change=='sequence':invalid['requests'][0]['sequence']=99
        else:invalid['requests'].append({**rows[-1],'sequence':len(rows)+1,'run_id':'foreign-native-input'})
        with pytest.raises(AssertionError):require_history_prefix(invalid,rows,context['run_id'])
        assert sha256(path.read_bytes()).hexdigest()==before


def test_actual_native_freeze_is_durable_and_refuses_rearming_or_keys(actual_history,tmp_path):
    _,_,actual,before=actual_history
    relay,packet,folder=native_relay(tmp_path)
    try:
        relay.arm('generation1');relay.freeze()
        frozen=relay.path.read_bytes()
        for phase in (None,'generation1','generation2'):
            with pytest.raises(AdmissionError,match='purpose_sequence_denied'):relay.arm(phase)
        with pytest.raises(AdmissionError,match='credential_activation_denied'):relay.load_credentials({})
        assert relay.path.read_bytes()==frozen
        assert json.loads(frozen)['requests']==[] and json.loads(frozen)['stopped'] is True
    finally:relay.journal_lock.close()
    reopened=Relay(packet,evidence_root=folder)
    try:
        with pytest.raises(AdmissionError,match='purpose_sequence_denied'):reopened.arm(None)
        assert reopened.data['stopped'] is True and reopened.data['requests']==[]
    finally:reopened.journal_lock.close()
    assert sha256(actual.read_bytes()).hexdigest()==before


def test_actual_current_zero_call_review_preserves_history_and_rejects_key_or_call_claim(actual_history):
    context,rows,path,before=actual_history
    report={'run_id':context['run_id'],'historical_model_requests':rows,
        'model_requests':len(rows),'run_model_requests':0,'run_original_model_key_reads':0}
    assert zero_model_review_allowed(report,path) is True
    for field in ('run_model_requests','run_original_model_key_reads'):
        invalid={**report,field:1}
        assert zero_model_review_allowed(invalid,path) is False
    assert sha256(path.read_bytes()).hexdigest()==before


def test_native_over_limit_input_is_rejected_before_keys_or_journal_write(actual_history,tmp_path):
    _,rows,actual,before=actual_history
    relay,_,_=native_relay(tmp_path)
    try:
        relay.arm('generation1')
        disk=relay.path.read_bytes()
        source=next(row for row in rows if row['kind']=='Embedding')
        # Deliberately invalid memory input; these are never extra requests or
        # entries in either actual history or the real on-disk guard journal.
        relay.data['requests']=[{**deepcopy(source),'sequence':i+1}
            for i in range(relay.total_limits['Embedding']+1)]
        with pytest.raises(AdmissionError,match='shared_request_allowance_exhausted'):
            relay.admit('Embedding',{'model':'Embedding','input':['Native rejection input']})
        assert relay.path.read_bytes()==disk
        assert all(model['api_key']=='' for model in relay.models.values())
    finally:relay.journal_lock.close()
    assert sha256(actual.read_bytes()).hexdigest()==before


def test_actual_prior_usage_counts_globally_without_resetting_new_purpose(actual_history,tmp_path):
    context,rows,actual,before=actual_history
    relay,_,_=native_relay(tmp_path)
    try:
        disk=relay.path.read_bytes()
        # Real prior events as native inputs to the counting predicate. No
        # copied journal becomes authority and no resolved request is written.
        relay.data['requests']=deepcopy(rows)
        relay.arm('generation1')
        if context['change_id']=='CHG-414':
            from collections import Counter
            actual_counts=Counter(row['kind']for row in rows)
            assert relay.request_counts('Chat')==(actual_counts['Chat'],0,0)
            assert relay.request_counts('Embedding')==(actual_counts['Embedding'],0,0)
        else:
            assert relay.request_counts('Chat')==(2,0,0)
            assert relay.request_counts('Embedding')==(1,0,0)
        #413 retains the native-PDF OCR accounting alongside the two Chat
        # and one Embedding events. The original three-event fixture has none.
        assert relay.request_counts('OCR')==((1 if context['change_id']=='CHG-413' else 0),0,0)
        assert relay.path.read_bytes()==disk
    finally:relay.journal_lock.close()
    assert sha256(actual.read_bytes()).hexdigest()==before
