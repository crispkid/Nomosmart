from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import ChatFeedbackEvent, IntegrationClient, Project, PublicApiRequestLog, User
from app.db.session import get_session_factory
from app.domain.integration_api_keys import generate_api_key
from app.domain.public_api_controls import end_user_identity_hash, enforce_rate_limit
from app.domain.public_api_retention import enforce_public_api_retention


def test_public_rate_limit_is_atomic_across_concurrent_clients() -> None:
    settings = get_settings()
    dimension = f"chg216-concurrent-{uuid4()}"

    def consume() -> str:
        try:
            enforce_rate_limit(settings, dimension=dimension, limit=20)
            return "accepted"
        except AppError as exc:
            if exc.code != "public_api_rate_limited":
                raise
            return "limited"

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _index: consume(), range(50)))
    assert results.count("accepted") == 20
    assert results.count("limited") == 30


def test_public_retention_redacts_and_tombstones_without_deleting_audit_counts() -> None:
    factory = get_session_factory()
    now = datetime.now(UTC)
    user_id, project_id, client_id, response_id, feedback_id = (uuid4() for _ in range(5))
    _token, token_hash, token_prefix = generate_api_key()
    settings = get_settings()
    with factory() as session:
        session.add(User(id=user_id, employee_id=f"Z{uuid4().hex[:9]}", keycloak_user_id=f"chg216-retention-{user_id}", email=f"chg216-retention-{user_id}@example.test", display_name="Retention User", auth_source="keycloak", is_active=True))
        session.flush()
        session.add(Project(id=project_id, name=f"chg216-retention-{project_id}", status="active", created_by=user_id))
        session.flush()
        session.add(IntegrationClient(id=client_id, name=f"chg216-retention-{client_id}", status="active", api_key_hash=token_hash, api_key_prefix=token_prefix, api_key_version=1, rate_limit_config={}, success_count=1, failure_count=0, created_by=user_id, updated_by=user_id, lock_version=1))
        session.flush()
        identity_hash = end_user_identity_hash(settings, "E-RETENTION")
        session.add(PublicApiRequestLog(id=response_id, integration_client_id=client_id, project_id=project_id, endpoint="/api/public/v1/projects/test/chat", response_mode="json", result="success", http_status=200, lifecycle_status="answered", end_user_employee_id="", end_user_identity_hash=identity_hash, question_encrypted="encrypted-question", answer_encrypted="encrypted-answer", citations_encrypted="encrypted-citations", end_user_metadata_encrypted="encrypted-user", citations=[], selected_document_ids=[], selected_document_version_ids=[], retrieval_strategy="hybrid", retrieval_status="answered", content_expires_at=now - timedelta(days=2), retention_expires_at=now - timedelta(days=1), legal_hold=False, metadata_={"encrypted_content": True}, created_at=now - timedelta(days=400)))
        session.flush()
        session.add(ChatFeedbackEvent(id=feedback_id, project_id=project_id, public_response_id=response_id, source="api", feedback_value="good", comment="sensitive comment", integration_client_id=client_id, end_user_identity_hash=identity_hash, end_user_metadata_encrypted="encrypted-feedback-user", created_at=now - timedelta(days=399)))
        session.commit()
        try:
            result = enforce_public_api_retention(session, now=now)
            assert result == {"redacted": 1, "tombstoned": 1}
            log = session.get(PublicApiRequestLog, response_id)
            feedback = session.get(ChatFeedbackEvent, feedback_id)
            assert log is not None and log.deleted_at == now and log.question_encrypted is None and log.metadata_ == {"retention_tombstone": True}
            assert feedback is not None and feedback.comment is None and feedback.end_user_identity_hash is None
            assert session.get(IntegrationClient, client_id).success_count == 1
        finally:
            session.query(ChatFeedbackEvent).filter(ChatFeedbackEvent.id == feedback_id).delete(synchronize_session=False)
            session.query(PublicApiRequestLog).filter(PublicApiRequestLog.id == response_id).delete(synchronize_session=False)
            session.query(IntegrationClient).filter(IntegrationClient.id == client_id).delete(synchronize_session=False)
            session.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
            session.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            session.commit()
