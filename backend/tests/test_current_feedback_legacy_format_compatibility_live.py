"""Approved exact D3 counterpart, actual genuine feedback and one rolled-back transaction."""
from pathlib import Path
from hashlib import sha256
from uuid import UUID,uuid4
import json,os
import pytest
from sqlalchemy import select,text
from app.core.config import get_settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import ChatFeedbackEvent,IdempotencyKey
from app.domain.public_api_controls import decrypt_feedback_metadata,storage_scope
from current_live_support import current_live

def test_current_genuine_feedback_legacy_operation_format_rollback(current_live):
    root=Path(__file__).resolve().parents[2];a=json.loads((root/'docs/CHG-388-CONTINUATION-APPROVAL.json').read_bytes());assert a['gate_4']=='APPROVED'and a['human_answers']['D3'].startswith('核准 D3');assert sha256((root/'docs/CHG-388-CONTINUATION-DECISIONS.md').read_bytes()).hexdigest()==a['approved_markdown_sha256'];P=Path(os.environ['NOMOSMART_CURRENT_LIVE_CONTEXT']).parent;binding=json.loads((P/'genuine-feedback-format-reference.json').read_bytes());actual=json.loads((P/'actual-new-feedback-observation.json').read_bytes());assert actual['phase']=='HTTP_OBSERVED'and actual['http']==200 and actual['feedback_event_id']==binding['event_id'];caller=json.loads((P/'actual-feedback-question-intent.json').read_bytes())['question']['end_user'];key=get_settings().encryption_key_bytes
    with current_live.database()as s:
        event=s.get(ChatFeedbackEvent,UUID(binding['event_id']));assert event is not None and str(event.public_response_id)==binding['response_id'];op=s.scalar(select(IdempotencyKey).where(IdempotencyKey.scope==storage_scope(f'public-feedback:{event.integration_client_id}:{event.public_response_id}'),IdempotencyKey.key==event.idempotency_key_hash));assert op is not None;event_id,op_id=event.id,op.id;original_cipher=event.end_user_metadata_encrypted;original_scope=op.scope;plaintext=decrypt_feedback_metadata(s,key,event);assert json.loads(plaintext)['employee_id']==caller['employee_id'];prefix=f'public-response:{event.public_response_id}:feedback:'
        try:
            legacy=EnvelopeCipher(key).encrypt(plaintext,context=f'{prefix}{op.id}:end-user');event.end_user_metadata_encrypted=legacy;s.flush();assert decrypt_feedback_metadata(s,key,event)==plaintext
            event.end_user_metadata_encrypted=EnvelopeCipher(key).encrypt(plaintext,context=f'{prefix}{uuid4()}:end-user');s.flush()
            with pytest.raises(AppError)as e:decrypt_feedback_metadata(s,key,event)
            assert e.value.code=='invalid_encrypted_value';event.end_user_metadata_encrypted=legacy;op.scope=storage_scope(f'public-feedback:{uuid4()}:{event.public_response_id}');s.flush()
            with pytest.raises(AppError)as e:decrypt_feedback_metadata(s,key,event)
            assert e.value.code=='feedback_encryption_context_unavailable'
        finally:s.rollback()
        s.expire_all();after=s.get(ChatFeedbackEvent,event_id);afterop=s.get(IdempotencyKey,op_id);assert after.end_user_metadata_encrypted==original_cipher and afterop.scope==original_scope;assert decrypt_feedback_metadata(s,key,after)==plaintext;s.rollback()
    (P/'legacy-format-compatibility-result.json').write_text(json.dumps({'operation_uuid':a['operation_uuid'],'original_case':'backend/tests/test_current_feedback_encryption_live.py::test_real_legacy_feedback_remains_readable_through_exact_operation_scope','original_historical_HTTP_receipt_or_method_PASS':False,'actual_genuine_new_feedback_HTTP200_reused':True,'one_uncommitted_SQL_transaction':True,'actual_legacy_operation_AAD_read_PASS':True,'wrong_operation_AAD_and_scope_refused':True,'original_ciphertext_sha256_restored':sha256(original_cipher.encode()).hexdigest(),'actual_SQL_rollback_and_re_read':True,'new_HTTP_feedback_or_models':0,'full_suite_or_coverage_or_release_PASS':False},indent=2))
