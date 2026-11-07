"""Current real public feedback, reusing the owned genuinely answered request."""
import json
import os
from pathlib import Path
import secrets
import stat
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.encryption import EnvelopeCipher
from app.core.errors import AppError
from app.db.models import ChatFeedbackEvent
from app.domain.public_api_controls import decrypt_feedback_metadata
from current_live_support import current_live


def private_json(path, root):
    assert path.is_absolute() and path.resolve() == path and path.is_relative_to(root)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
        assert info.st_nlink == 1 and info.st_mode & 0o077 == 0 and info.st_size <= 262144
        return json.loads(os.read(descriptor, 262145))
    finally:
        os.close(descriptor)


@pytest.fixture
def reference(current_live):
    context = current_live.context
    root = Path(os.environ["NOMOSMART_CURRENT_LIVE_CONTEXT"]).parent
    scope = private_json(root / "current-feedback-reference.json", root)
    assert set(scope) == {"run_uuid", "response_id", "credential_response_file", "question_intent_file", "legacy_feedback_response_file"}
    assert scope["run_uuid"] == context["run_id"]
    return root, scope


def test_actual_new_feedback_has_durable_context_and_idempotent_replay(current_live, reference):
    root, scope = reference
    credential = private_json(Path(scope["credential_response_file"]), root)
    assert credential["http"] == 200
    api_key = credential["response"]["api_key"]
    caller = private_json(Path(scope["question_intent_file"]), root)["question"]["end_user"]
    key = "chg370-stable-feedback-" + str(uuid4())
    intent = root / ("feedback-event-context-" + str(uuid4()) + ".json")
    # Record this exact new operation before sending. A failed observer must not
    # produce another feedback event on a blind retry.
    descriptor = os.open(intent, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"response_id": scope["response_id"], "idempotency_key": key, "phase": "INTENT_BEFORE_REQUEST"}, stream)
    with httpx.Client(verify=current_live.context["ca_file"], trust_env=False, timeout=20,
                      headers={"X-Nomosmart-API-Key": api_key}) as api:
        path = current_live.context["backend_direct_url"].rstrip("/") + "/api/public/v1/chat/responses/" + scope["response_id"] + "/feedback"
        body = {"feedback": "good", "comment": "Current durable encryption context verification", "end_user": caller}
        response = api.post(path, headers={"Idempotency-Key": key}, json=body)
        assert response.status_code == 200
        result = response.json()
        intent.write_text(json.dumps({"response_id": scope["response_id"], "idempotency_key": key,
                                      "phase": "HTTP_OBSERVED", "http": response.status_code, "feedback_event_id": result["feedback_event_id"]}))
        with current_live.database() as session:
            event = session.get(ChatFeedbackEvent, UUID(result["feedback_event_id"]))
            assert event is not None and str(event.public_response_id) == scope["response_id"]
            context = f"public-response:{event.public_response_id}:feedback:{event.id}:end-user"
            plaintext = EnvelopeCipher(get_settings().encryption_key_bytes).decrypt(event.end_user_metadata_encrypted, context=context)
            assert json.loads(plaintext)["employee_id"] == caller["employee_id"]
            assert event.end_user_employee_id is None
            with pytest.raises(AppError):
                EnvelopeCipher(secrets.token_bytes(32)).decrypt(event.end_user_metadata_encrypted, context=context)
            with pytest.raises(AppError):
                EnvelopeCipher(get_settings().encryption_key_bytes).decrypt(event.end_user_metadata_encrypted, context=context + ":wrong")
        repeated = api.post(path, headers={"Idempotency-Key": key}, json=body)
        assert repeated.status_code == 200 and repeated.json() == result
        with current_live.database() as session:
            assert session.scalar(select(func.count()).select_from(ChatFeedbackEvent).where(
                ChatFeedbackEvent.id == UUID(result["feedback_event_id"]))) == 1


def test_real_legacy_feedback_remains_readable_through_exact_operation_scope(current_live, reference):
    root, scope = reference
    legacy = private_json(Path(scope["legacy_feedback_response_file"]), root)
    assert legacy["http"] == 200
    caller = private_json(Path(scope["question_intent_file"]), root)["question"]["end_user"]
    with current_live.database() as session:
        event = session.get(ChatFeedbackEvent, UUID(legacy["response"]["feedback_event_id"]))
        assert event is not None and str(event.public_response_id) == scope["response_id"]
        plaintext = decrypt_feedback_metadata(session, get_settings().encryption_key_bytes, event)
        assert json.loads(plaintext)["employee_id"] == caller["employee_id"]
