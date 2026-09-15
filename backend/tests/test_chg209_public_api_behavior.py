from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.api.routes import integration_clients, public_api
from app.api.schemas import (
    IntegrationClientCreatePayload,
    IntegrationClientLifecyclePayload,
    IntegrationClientProjectScopesPayload,
    IntegrationClientUpdatePayload,
    PublicApiChatPayload,
    PublicApiEndUser,
    PublicApiFeedbackPayload,
)
from app.core.errors import AppError
from app.core.config import get_settings
from app.db.models import AuditLog, ChatFeedbackEvent, IdempotencyKey, IntegrationClient, IntegrationClientProjectScope, Project, PublicApiRequestLog, User
from app.db.session import get_session_factory
from app.domain.integration_api_keys import api_key_hash, generate_api_key
from app.domain.public_api_controls import end_user_identity_hash, enforce_rate_limit
from app.security.auth import IdentityPrincipal
from app.security.context import IdentityContext
from app.security.permissions import MENU_MODULE, MENU_SYSTEM_MANAGEMENT, PermissionGrant


TEST_PREFIX = f"codex-chg209-{uuid4().hex[:8]}"


def _request(headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()],
        "client": ("127.0.0.1", 12345),
        "app": SimpleNamespace(state=SimpleNamespace(settings=get_settings())),
    }
    request = Request(scope)
    request.state.request_id = f"{TEST_PREFIX}-request"
    return request


def _context(user_id) -> IdentityContext:
    return IdentityContext(
        user_id=user_id,
        principal=IdentityPrincipal(
            subject=f"{TEST_PREFIX}-principal",
            employee_id="ZCHG209",
            email=f"{TEST_PREFIX}@example.test",
            display_name="CHG209 Tester",
            groups=(),
            session_id=None,
            auth_time=None,
        ),
        grants=(
            PermissionGrant(
                MENU_MODULE,
                MENU_SYSTEM_MANAGEMENT,
                can_view=True,
                can_create=True,
                can_edit=True,
                can_delete=True,
            ),
        ),
        visible_project_ids=frozenset(),
    )


@pytest.fixture()
def integration_workspace():
    session_factory = get_session_factory()
    user_id = uuid4()
    project_id = uuid4()
    client_id = uuid4()
    token, token_hash, token_prefix = generate_api_key()
    now = datetime.now(UTC)
    with session_factory() as session:
        user = User(
            id=user_id,
            employee_id=f"Z{uuid4().hex[:9]}",
            keycloak_user_id=f"{TEST_PREFIX}-{user_id}",
            email=f"{TEST_PREFIX}-{user_id}@example.test",
            display_name="CHG209 Integration Tester",
            auth_source="keycloak",
            is_active=True,
        )
        project = Project(
            id=project_id,
            name=f"{TEST_PREFIX} project",
            description="Public API test project",
            status="active",
            created_by=user_id,
        )
        client = IntegrationClient(
            id=client_id,
            name=f"{TEST_PREFIX} client",
            description="kept",
            status="active",
            api_key_hash=token_hash,
            api_key_prefix=token_prefix,
            api_key_version=1,
            contact_name="Original Contact",
            contact_email="original@example.test",
            contact_department="QA",
            valid_from=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=1),
            rate_limit_config={"requests_per_minute": 2},
            created_by=user_id,
            updated_by=user_id,
            lock_version=1,
        )
        session.add(user)
        session.flush()
        session.add(project)
        session.flush()
        session.add(client)
        session.flush()
        session.add(IntegrationClientProjectScope(client_id=client_id, project_id=project_id, created_by=user_id, created_at=now))
        session.commit()
    try:
        yield {
            "session_factory": session_factory,
            "user_id": user_id,
            "project_id": project_id,
            "client_id": client_id,
            "token": token,
            "token_hash": token_hash,
        }
    finally:
        with session_factory() as session:
            client_ids = list(session.scalars(select(IntegrationClient.id).where(IntegrationClient.created_by == user_id)))
            response_ids = list(session.scalars(select(PublicApiRequestLog.id).where(PublicApiRequestLog.integration_client_id.in_(client_ids or [client_id]))))
            session.query(ChatFeedbackEvent).filter(ChatFeedbackEvent.public_response_id.in_(response_ids or [uuid4()])).delete(synchronize_session=False)
            for cleanup_client_id in client_ids:
                session.query(PublicApiRequestLog).filter(PublicApiRequestLog.integration_client_id == cleanup_client_id).delete(synchronize_session=False)
                session.query(IntegrationClientProjectScope).filter(IntegrationClientProjectScope.client_id == cleanup_client_id).delete(synchronize_session=False)
            session.query(AuditLog).filter((AuditLog.actor_user_id == user_id) | (AuditLog.resource_id.in_(client_ids or [client_id]))).delete(synchronize_session=False)
            session.query(IntegrationClient).filter(IntegrationClient.id.in_(client_ids or [client_id])).delete(synchronize_session=False)
            session.query(IdempotencyKey).filter(IdempotencyKey.scope.like("public-%")).delete(synchronize_session=False)
            session.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
            session.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            session.commit()


def test_public_api_key_auth_accepts_bearer_and_rejects_inactive(integration_workspace) -> None:
    with integration_workspace["session_factory"]() as session:
        client = public_api.get_public_integration_client(_request({"authorization": f"Bearer {integration_workspace['token']}"}), session)
        assert client.id == integration_workspace["client_id"]

        with pytest.raises(AppError) as invalid:
            public_api.get_public_integration_client(_request({"authorization": "Bearer invalid"}), session)
        assert invalid.value.code == "invalid_api_key"

        client.status = "inactive"
        session.commit()
        with pytest.raises(AppError) as error:
            public_api.get_public_integration_client(_request({"x-nomosmart-api-key": integration_workspace["token"]}), session)
        assert error.value.code == "api_key_inactive"
        assert session.get(IntegrationClient, integration_workspace["client_id"]).failure_count == 1


def test_integration_client_management_routes_cover_lifecycle_and_usage(integration_workspace) -> None:
    context = _context(integration_workspace["user_id"])
    request = _request()
    with integration_workspace["session_factory"]() as session:
        created = integration_clients.create_integration_client(
            IntegrationClientCreatePayload(
                name="External CRM",
                description="  Public Q&A key  ",
                project_ids=[integration_workspace["project_id"]],
                contact_name=" API Owner ",
                contact_email="owner@example.test",
                contact_department="Compliance",
                requests_per_minute=15,
            ),
            request,
            context,
            session,
        )
        assert created.api_key.startswith("nms_")
        assert created.api_key_prefix == created.api_key[:16]
        assert created.project_ids == [integration_workspace["project_id"]]

        # Direct domain-flow invocation supplies explicit values. FastAPI's
        # Query defaults are resolved by HTTP, covered separately in CHG-295.
        listed = integration_clients.list_integration_clients(request=request, status=None, project_id=None,
            name=None, expiry=None, cursor=None, limit=50, context=context, session=session)
        assert any(item.id == created.id for item in listed.items)
        fetched = integration_clients.get_integration_client(created.id, context, session)
        assert fetched.requests_per_minute == 15

        scoped = integration_clients.replace_integration_client_project_scopes(
            created.id,
            IntegrationClientProjectScopesPayload(lock_version=fetched.lock_version, project_ids=[integration_workspace["project_id"]]),
            request,
            context,
            session,
        )
        rotated = integration_clients.rotate_integration_client_key(
            created.id,
            IntegrationClientLifecyclePayload(lock_version=scoped.lock_version, reason="scheduled rotation"),
            request,
            context,
            session,
        )
        assert rotated.api_key != created.api_key
        assert rotated.api_key_version == 2

        deactivated = integration_clients.deactivate_integration_client(
            created.id,
            IntegrationClientLifecyclePayload(lock_version=rotated.lock_version, reason="maintenance"),
            request,
            context,
            session,
        )
        assert deactivated.status == "inactive"
        activated = integration_clients.activate_integration_client(
            created.id,
            IntegrationClientLifecyclePayload(lock_version=deactivated.lock_version, reason="done"),
            request,
            context,
            session,
        )
        assert activated.status == "active"

        session.add(
            PublicApiRequestLog(
                id=uuid4(),
                integration_client_id=created.id,
                project_id=integration_workspace["project_id"],
                endpoint="/api/public/v1/projects/test/chat",
                response_mode="json",
                result="success",
                http_status=200,
                end_user_employee_id="E90001",
                question="seed",
                citations=[],
                selected_document_ids=[],
                selected_document_version_ids=[],
                retrieval_strategy="hybrid",
                retrieval_status="answered",
                metadata_={},
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
        usage = integration_clients.get_integration_client_usage_summary(created.id, context, session)
        assert usage.recent_requests[0].end_user_employee_id == "E90001"

        revoked = integration_clients.delete_integration_client(created.id, request, activated.lock_version, context, session)
        assert revoked.status == "revoked"


def test_integration_client_partial_update_keeps_omitted_fields(integration_workspace) -> None:
    with integration_workspace["session_factory"]() as session:
        response = integration_clients.update_integration_client(
            integration_workspace["client_id"],
            IntegrationClientUpdatePayload(lock_version=1, name=" Renamed API Client "),
            _request(),
            _context(integration_workspace["user_id"]),
            session,
        )
        assert response.name == "Renamed API Client"
        assert response.description == "kept"
        assert response.contact_name == "Original Contact"
        assert response.contact_email == "original@example.test"
        assert response.requests_per_minute == 2
        assert response.lock_version == 2


def test_integration_client_lifecycle_and_rotation_enforce_lock_and_revocation(integration_workspace) -> None:
    with integration_workspace["session_factory"]() as session:
        client = session.get(IntegrationClient, integration_workspace["client_id"])
        assert integration_clients._effective_status(client) == "active"
        with pytest.raises(AppError) as stale:
            integration_clients._assert_lock(client, 99)
        assert stale.value.code == "stale_lock_version"

        project_ids = integration_clients._validate_project_ids(session, [integration_workspace["project_id"], integration_workspace["project_id"]])
        assert project_ids == [integration_workspace["project_id"]]

        response = integration_clients.revoke_integration_client(
            integration_workspace["client_id"],
            SimpleNamespace(lock_version=1, reason="contract ended"),
            _request(),
            _context(integration_workspace["user_id"]),
            session,
        )
        assert response.status == "revoked"
        with pytest.raises(AppError) as reactivated:
            integration_clients.activate_integration_client(
                integration_workspace["client_id"],
                SimpleNamespace(lock_version=2, reason="undo"),
                _request(),
                _context(integration_workspace["user_id"]),
                session,
            )
        assert reactivated.value.code == "integration_client_revoked"


def test_public_scope_and_rate_limit_use_active_project_scope(integration_workspace) -> None:
    payload = PublicApiChatPayload(question="What is covered?", end_user=PublicApiEndUser(employee_id="E10001"), top_k=1)
    with integration_workspace["session_factory"]() as session:
        public_api._ensure_project_scope(session, integration_workspace["client_id"], integration_workspace["project_id"])
        with pytest.raises(AppError) as denied:
            public_api._ensure_project_scope(session, integration_workspace["client_id"], uuid4())
        assert denied.value.code == "integration_project_scope_denied"

        client = session.get(IntegrationClient, integration_workspace["client_id"])
        dimension = f"{TEST_PREFIX}:{uuid4()}"
        enforce_rate_limit(get_settings(), dimension=dimension, limit=2)
        enforce_rate_limit(get_settings(), dimension=dimension, limit=2)
        with pytest.raises(AppError) as limited:
            enforce_rate_limit(get_settings(), dimension=dimension, limit=2)
        assert limited.value.code == "public_api_rate_limited"

        public_api._record_public_error(
            session,
            _request(),
            client,
            integration_workspace["project_id"],
            payload,
            AppError("retrieval_scope_denied", "denied", status_code=403),
            response_mode="json",
        )
        assert session.get(IntegrationClient, integration_workspace["client_id"]).failure_count >= 1


def test_public_chat_error_logging_and_feedback_are_append_only(integration_workspace) -> None:
    payload = PublicApiChatPayload(question="What is published?", end_user=PublicApiEndUser(employee_id="E20001", employee_name="End User", department="Legal"), top_k=1)
    with integration_workspace["session_factory"]() as session:
        client = session.get(IntegrationClient, integration_workspace["client_id"])
        with pytest.raises(AppError) as no_manifest:
            public_api.public_project_chat(integration_workspace["project_id"], payload, _request(), f"{TEST_PREFIX}-chat-error", client, session)
        assert no_manifest.value.code == "active_manifest_required"
        failure_log = session.scalar(select(PublicApiRequestLog).where(PublicApiRequestLog.integration_client_id == client.id).order_by(PublicApiRequestLog.created_at.desc()))
        assert failure_log is not None
        assert failure_log.result == "failure"
        assert failure_log.end_user_employee_id == ""
        assert failure_log.end_user_identity_hash == end_user_identity_hash(get_settings(), "E20001")
        assert failure_log.question is None
        assert failure_log.question_encrypted

        success_log = PublicApiRequestLog(
            id=uuid4(),
            integration_client_id=client.id,
            project_id=integration_workspace["project_id"],
            endpoint="/api/public/v1/projects/test/chat",
            response_mode="json",
            result="success",
            http_status=200,
            end_user_employee_id="E20001",
            question="seed",
            answer="answer",
            citations=[],
            selected_document_ids=[],
            selected_document_version_ids=[],
            retrieval_strategy="hybrid",
            retrieval_status="answered",
            lifecycle_status="answered",
            end_user_identity_hash=end_user_identity_hash(get_settings(), "E20001"),
            metadata_={},
            created_at=datetime.now(UTC),
        )
        session.add(success_log)
        session.commit()
        feedback = public_api.create_public_feedback(
            success_log.id,
            PublicApiFeedbackPayload(feedback="good", comment=" helpful ", end_user=PublicApiEndUser(employee_id="E20001")),
            _request(),
            f"{TEST_PREFIX}-feedback",
            client,
            session,
        )
        assert feedback.response_id == success_log.id
        assert feedback.latest_feedback == "good"
        assert feedback.comment == "helpful"


def test_public_api_helpers_format_sse_and_key_hashes() -> None:
    token, token_hash, token_prefix = generate_api_key()
    assert api_key_hash(token) == token_hash
    assert token.startswith("nms_")
    assert token_prefix == token[:16]
    assert public_api._extract_api_key(_request({"authorization": f"Bearer {token}"})) == token
    assert public_api._extract_api_key(_request({"x-nomosmart-api-key": token})) == token
    with pytest.raises(AppError) as missing:
        public_api._extract_api_key(_request())
    assert missing.value.code == "api_key_required"
    event = public_api._sse_event("done", {"answer": "已完成"})
    assert event.startswith("event: done\n")
    assert '"已完成"' in event
