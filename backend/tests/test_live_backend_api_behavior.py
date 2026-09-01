from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(ROOT / "backend" / ".env")
os.environ.setdefault("BACKEND_LIVE_BASE_URL", "http://127.0.0.1:8000")


def _review_evidence(version_id: UUID) -> dict:
    manifest = {"schema": "nomosmart.approval-evidence.v1", "test_version_id": str(version_id)}
    revision = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "evidence_revision": revision,
        "evidence_manifest": manifest,
        "evidence_generated_at": datetime.now(UTC),
    }


def _service_token() -> str:
    issuer = os.environ["OIDC_ISSUER_URL"].rstrip("/")
    client_id = os.environ["KEYCLOAK_SYNC_CLIENT_ID"]
    client_secret = os.environ["KEYCLOAK_SYNC_CLIENT_SECRET"]
    response = httpx.post(
        f"{issuer}/protocol/openid-connect/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        timeout=10,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


SERVICE_TOKEN = _service_token()
SERVICE_CLAIMS = jwt.decode(SERVICE_TOKEN, options={"verify_signature": False})
SERVICE_AUDIENCE = SERVICE_CLAIMS.get("aud")
if isinstance(SERVICE_AUDIENCE, list):
    os.environ["OIDC_AUDIENCE"] = str(SERVICE_AUDIENCE[0])
else:
    os.environ["OIDC_AUDIENCE"] = str(SERVICE_AUDIENCE)

from app.api.routes import approvals as approval_routes, data_sources as data_source_routes, documents as document_routes, models as model_routes, projects as project_routes, serving as serving_routes, system as system_routes  # noqa: E402
from app.api.schemas import ApprovalChunkEvidence, DataSourceConnectionPayload, IdentitySettingsCandidate, ProjectChatCitation, ProjectGraphEdge, ProjectGraphNode  # noqa: E402
from app import worker  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.encryption import EnvelopeCipher  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.db.models import (  # noqa: E402
    AIModel,
    ActiveVersionManifest,
    ApprovalRequest,
    ApprovalTask,
    ChatRecord,
    Chunk,
    ChunkTag,
    DataConnection,
    DataSyncRun,
    Document,
    DocumentReference,
    DocumentReferenceEvent,
    DocumentVersion,
    DocumentVersionTag,
    EmbeddingBuild,
    EmbeddingBuildVector,
    EmbeddingProfile,
    ExternalGroup,
    ExternalGroupRoleMapping,
    ExternalGroupUser,
    FileScanRun,
    GraphSyncJob,
    IdentitySetting,
    IdentitySyncRun,
    IdentityUnlockGrant,
    Notification,
    OutboxEvent,
    PipelineRun,
    PipelineRunStep,
    Project,
    ProjectMember,
    ProjectOwner,
    ReviewRecord,
    RevokedAuthToken,
    Role,
    RolePermission,
    RoleUser,
    Tag,
    User,
    ValidationRun,
    ValidationRunItem,
)
from app.db.session import get_session_factory  # noqa: E402
from app.domain import ai_provider, chunk_artifacts, data_sync, embeddings, extraction_pipeline, identity_settings, review_publish, validation_runner  # noqa: E402
from app.domain.data_sync import compute_next_run_at, execute_data_source_sync, queue_due_scheduled_data_syncs  # noqa: E402
from app.domain.review_publish import LiveNeo4jGraphSyncAdapter, LiveOpenSearchPublishedAdapter  # noqa: E402
from app.integrations.keycloak import KeycloakAdminClient  # noqa: E402
from app.integrations.remote_sources import FTPRemoteSourceClient, FTPSRemoteSourceClient, HTTPRemoteSourceClient, SFTPRemoteSourceClient, _guard_http_url, _host_is_blocked  # noqa: E402
from app.integrations.s3_storage import S3ObjectStorage  # noqa: E402
from app.main import create_app  # noqa: E402
from app.security.auth import IdentityPrincipal, is_token_revoked  # noqa: E402
from app.security.permissions import MENU_KNOWLEDGE_PROJECTS, MENU_MODULE, MENU_REPORTS, MENU_SYSTEM_MANAGEMENT, PROJECT_ARCHIVE, PROJECT_MODULE  # noqa: E402
from app.services.identity_sync import normalize_snapshot, reconcile_snapshot  # noqa: E402
from app.services.logout import revoke_login_session  # noqa: E402


TEST_PREFIX = f"codex-live-{uuid4().hex[:10]}"
MENU_ROWS = (MENU_KNOWLEDGE_PROJECTS, MENU_REPORTS, MENU_SYSTEM_MANAGEMENT)


@pytest.fixture(scope="session")
def live_client():
    session_factory = get_session_factory()
    subject = str(SERVICE_CLAIMS["sub"])
    now_email = f"{TEST_PREFIX}@example.test"
    with session_factory() as session:
        user = session.scalar(select(User).where(User.keycloak_user_id == subject))
        if user is None:
            user = User(
                employee_id=f"Z{uuid4().hex[:9]}",
                keycloak_user_id=subject,
                email=now_email,
                display_name="Codex Live Coverage",
                department="QA",
                title="Live tester",
                auth_source="keycloak",
                is_active=True,
                knowledge_owner=True,
            )
            session.add(user)
            session.flush()
        else:
            user.email = user.email or now_email
            user.display_name = user.display_name or "Codex Live Coverage"
            user.is_active = True
            user.knowledge_owner = True
        role = Role(name=f"{TEST_PREFIX}-system-admin", description="Live coverage role", is_active=True, is_system=False)
        session.add(role)
        session.flush()
        for function_name in MENU_ROWS:
            session.add(
                RolePermission(
                    role_id=role.id,
                    module_name=MENU_MODULE,
                    function_name=function_name,
                    can_view=True,
                    can_create=True,
                    can_edit=True,
                    can_delete=True,
                )
            )
        session.add(RoleUser(role_id=role.id, user_id=user.id, source="manual"))
        session.commit()
        user_id = str(user.id)
        role_id = str(role.id)

    app = create_app()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    try:
        yield client, headers, user_id, role_id
    finally:
        with session_factory() as session:
            role = session.get(Role, role_id)
            if role is not None:
                session.delete(role)
            session.commit()


def _assert_ok(response, expected_status: int = 200) -> dict:
    assert response.status_code == expected_status, response.text
    return response.json()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _completed_pipeline_steps(run_id, *, version_id: UUID | None = None, markdown: str | None = None):
    now = datetime.now(UTC)
    names = [
        "upload_received",
        "file_scan",
        "parse_document",
        "ocr_extract",
        "split_paragraphs",
        "chunk_knowledge",
        "generate_markdown",
        "auto_tag",
        "build_embeddings",
        "build_staging_index",
        "build_graph_preview",
        "prepare_submission",
        "manager_review",
        "owner_review",
        "publish",
        "production_index",
        "graph_sync",
    ]
    steps = [
        PipelineRunStep(
            run_id=run_id,
            step_name=name,
            status="completed",
            progress_percent=100,
            progress_message=f"{name} completed",
            retry_count=0,
            started_at=now,
            completed_at=now,
        )
        for name in names
    ]
    if version_id is not None and markdown is not None:
        artifact_ref = f"artifact://document_versions/{version_id}/generate_markdown"
        generate_markdown = next(step for step in steps if step.step_name == "generate_markdown")
        generate_markdown.output_artifact_ref = artifact_ref
        generate_markdown.artifact_payload = {"markdown": markdown}
    return steps


def _seed_live_document_workspace(session_factory, user_id: str) -> dict[str, str]:
    user_uuid = UUID(user_id)
    now = datetime.now(UTC)
    seed_id = uuid4().hex[:8]
    with session_factory() as session:
        user = session.get(User, user_uuid)
        user.manager_user_id = user_uuid

        embedding_model = AIModel(
            name=f"{TEST_PREFIX}-{seed_id}-seed-embedding",
            model_type="Embedding",
            provider="custom",
            endpoint="http://127.0.0.1:65535/embedding",
            is_active=True,
            is_default=False,
            config={"model_name": "codex-live-embedding"},
            config_version=1,
        )
        chat_model = AIModel(
            name=f"{TEST_PREFIX}-{seed_id}-seed-chat",
            model_type="Chat",
            provider="ollama",
            endpoint="http://127.0.0.1:65535/chat",
            is_active=True,
            is_default=False,
            config={"model_name": "codex-live-chat"},
            config_version=1,
        )
        ocr_model = AIModel(
            name=f"{TEST_PREFIX}-{seed_id}-seed-ocr",
            model_type="OCR",
            provider="custom",
            endpoint="http://127.0.0.1:65535/ocr",
            is_active=True,
            is_default=False,
            config={"model_name": "codex-live-ocr"},
            config_version=1,
        )
        session.add_all([embedding_model, chat_model, ocr_model])
        session.flush()

        profile = EmbeddingProfile(
            model_id=embedding_model.id,
            model_version="codex-live-embedding-v1",
            vector_dimension=3,
            distance_method="cosine",
            chunk_strategy={"strategy": "live-coverage"},
            mapping_version=1,
        )
        session.add(profile)
        session.flush()

        project = Project(
            name=f"{TEST_PREFIX}-{seed_id}-knowledge-project",
            description="Live coverage knowledge project",
            status="active",
            llm_model_id=chat_model.id,
            embedding_model_id=embedding_model.id,
            ocr_model_id=ocr_model.id,
            created_by=user_uuid,
            lock_version=1,
            created_at=now,
            updated_at=now,
        )
        target_project = Project(
            name=f"{TEST_PREFIX}-{seed_id}-target-project",
            description="Live coverage reference target",
            status="active",
            llm_model_id=chat_model.id,
            embedding_model_id=embedding_model.id,
            ocr_model_id=ocr_model.id,
            created_by=user_uuid,
            lock_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add_all([project, target_project])
        session.flush()
        for item in (project, target_project):
            session.add(ProjectOwner(project_id=item.id, user_id=user_uuid, created_at=now))
            session.add(ProjectMember(project_id=item.id, user_id=user_uuid, project_role="owner", created_at=now))
            session.add(ProjectMember(project_id=item.id, user_id=user_uuid, project_role="editor", created_at=now))

        source_text = "Alpha architecture controls GPU isolation and API routing.\n\nBeta retrieval validates chunk tags and document tags."
        document = Document(
            project_id=project.id,
            document_code="DOC-LIVE-001",
            title=f"{TEST_PREFIX} Active Knowledge",
            source_type="upload",
            status="active",
            is_deleted=False,
            created_by=user_uuid,
            lock_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            project_id=project.id,
            document_id=document.id,
            version_major=1,
            extraction_revision=0,
            version_label="v1.0",
            status="active",
            original_file_name="live-coverage.md",
            canonical_extension=".md",
            mime_type="text/markdown",
            file_size=len(source_text.encode("utf-8")),
            content_sha256=_sha256(source_text),
            uploaded_at=now,
            original_snapshot_uri="memory://live-coverage.md",
            parser_version="pytest-live",
            ocr_model_id=ocr_model.id,
            ocr_config_version=ocr_model.config_version,
            chunk_strategy={
                "source_text": source_text,
                "markdown_text": source_text,
                "document_layout": {"status": "available", "source": "pytest", "pages": [{"page_number": 1, "blocks": [{"id": "body-1", "type": "paragraph", "source_anchor": "body-1", "text": source_text}]}]},
            },
            embedding_model_id=embedding_model.id,
            embedding_profile_id=profile.id,
            llm_model_id=chat_model.id,
            lock_version=1,
            processed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(version)
        session.flush()
        version.markdown_artifact_uri = f"artifact://document_versions/{version.id}/generate_markdown"

        chunk_one_content = "Alpha architecture controls GPU isolation and API routing."
        chunk_two_content = "Beta retrieval validates chunk tags and document tags."
        chunk_one = Chunk(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_index=1,
            title="Alpha architecture",
            content=chunk_one_content,
            markdown_content=chunk_one_content,
            content_type="text",
            content_hash=_sha256(chunk_one_content),
            start_offset=0,
            end_offset=len(chunk_one_content),
            source_mapping=[{"source_anchor": "body-1", "view_mode": "markdown", "start_offset": 0, "end_offset": len(chunk_one_content), "page": 1}],
            chunk_strategy={"source": "rule"},
            embedding_model_id=embedding_model.id,
            embedding_vector_ref="memory://vector-1",
            token_count=7,
            confidence_score=0.95,
            status="active",
            is_manual_edited=False,
            created_at=now,
            updated_at=now,
        )
        chunk_two = Chunk(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_index=2,
            title="Beta retrieval",
            content=chunk_two_content,
            markdown_content=chunk_two_content,
            content_type="text",
            content_hash=_sha256(chunk_two_content),
            start_offset=len(chunk_one_content) + 2,
            end_offset=len(source_text),
            source_mapping=[{"source_anchor": "body-1", "view_mode": "markdown", "start_offset": len(chunk_one_content) + 2, "end_offset": len(source_text), "page": 1}],
            chunk_strategy={"source": "rule"},
            embedding_model_id=embedding_model.id,
            embedding_vector_ref="memory://vector-2",
            token_count=8,
            confidence_score=0.94,
            status="active",
            is_manual_edited=False,
            created_at=now,
            updated_at=now,
        )
        session.add_all([chunk_one, chunk_two])
        session.flush()

        tag_document = Tag(project_id=project.id, name=f"{TEST_PREFIX}-architecture", created_at=now)
        tag_chunk = Tag(project_id=project.id, name=f"{TEST_PREFIX}-gpu", created_at=now)
        session.add_all([tag_document, tag_chunk])
        session.flush()
        session.add(DocumentVersionTag(document_version_id=version.id, tag_id=tag_document.id, source="manual", confidence_score=1, metadata_={"source": "pytest"}, created_by=user_uuid, created_at=now))
        session.add(ChunkTag(chunk_id=chunk_one.id, tag_id=tag_chunk.id, source="manual", confidence_score=1, metadata_={"source": "pytest"}, created_by=user_uuid, created_at=now))

        build = EmbeddingBuild(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            embedding_profile_id=profile.id,
            build_revision=1,
            status="completed",
            chunk_count=2,
            index_name=f"{TEST_PREFIX}-published",
            checksum=_sha256("published"),
            created_at=now,
            updated_at=now,
        )
        session.add(build)
        session.flush()
        manifest = ActiveVersionManifest(
            project_id=project.id,
            document_id=document.id,
            document_version_id=version.id,
            embedding_profile_id=profile.id,
            embedding_build_id=build.id,
            publication_generation=1,
            index_ready=True,
            lock_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(manifest)
        graph_job = GraphSyncJob(project_id=project.id, document_id=document.id, document_version_id=version.id, trigger_type="publish", status="completed", node_count=4, edge_count=3, created_at=now, completed_at=now)
        session.add(graph_job)

        pipeline = PipelineRun(project_id=project.id, document_id=document.id, document_version_id=version.id, run_type="document_extraction", status="completed", progress_percent=100, current_step_name="graph_sync", triggered_by=user_uuid, started_at=now, completed_at=now, created_at=now)
        session.add(pipeline)
        session.flush()
        session.add_all(_completed_pipeline_steps(pipeline.id, version_id=version.id, markdown=source_text))

        review_document = Document(project_id=project.id, document_code="DOC-LIVE-002", title=f"{TEST_PREFIX} Review Candidate", source_type="upload", status="inactive", is_deleted=False, created_by=user_uuid, lock_version=1, created_at=now, updated_at=now)
        session.add(review_document)
        session.flush()
        review_version = DocumentVersion(
            project_id=project.id,
            document_id=review_document.id,
            version_major=1,
            extraction_revision=0,
            version_label="v1.0",
            status="submission_ready",
            original_file_name="review-candidate.md",
            canonical_extension=".md",
            mime_type="text/markdown",
            file_size=48,
            content_sha256=_sha256("Review candidate source"),
            chunk_strategy={"source_text": "Review candidate source", "markdown_text": "Review candidate source"},
            embedding_model_id=embedding_model.id,
            embedding_profile_id=profile.id,
            llm_model_id=chat_model.id,
            lock_version=1,
            processed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(review_version)
        session.flush()
        review_version.markdown_artifact_uri = f"artifact://document_versions/{review_version.id}/generate_markdown"
        review_chunk = Chunk(project_id=project.id, document_id=review_document.id, document_version_id=review_version.id, chunk_index=1, title="Review chunk", content="Review candidate source", markdown_content="Review candidate source", content_type="text", content_hash=_sha256("Review candidate source"), start_offset=0, end_offset=23, source_mapping=[{"source_anchor": "review-1"}], chunk_strategy={"source": "rule"}, embedding_model_id=embedding_model.id, token_count=3, confidence_score=0.91, status="active", is_manual_edited=False, created_at=now, updated_at=now)
        session.add(review_chunk)
        review_pipeline = PipelineRun(project_id=project.id, document_id=review_document.id, document_version_id=review_version.id, run_type="document_extraction", status="completed", progress_percent=100, current_step_name="prepare_submission", triggered_by=user_uuid, started_at=now, completed_at=now, created_at=now)
        session.add(review_pipeline)
        session.flush()
        session.add_all(
            _completed_pipeline_steps(
                review_pipeline.id,
                version_id=review_version.id,
                markdown="Review candidate source",
            )
        )

        target_document = Document(project_id=target_project.id, document_code="DOC-LIVE-REF", title=f"{TEST_PREFIX} Referenced Copy", source_type="project_reference", status="inactive", is_deleted=False, created_by=user_uuid, lock_version=1, created_at=now, updated_at=now)
        session.add(target_document)
        session.flush()
        target_version = DocumentVersion(project_id=target_project.id, document_id=target_document.id, version_major=1, extraction_revision=0, version_label="v1.0", status="inactive", original_file_name="referenced-copy.md", canonical_extension=".md", mime_type="text/markdown", file_size=32, content_sha256=_sha256("referenced copy"), chunk_strategy={"source": "project_reference", "source_text": "referenced copy"}, embedding_model_id=embedding_model.id, embedding_profile_id=profile.id, llm_model_id=chat_model.id, source_document_id=document.id, source_version_id=version.id, lock_version=1, created_at=now, updated_at=now)
        session.add(target_version)
        session.flush()
        reference = DocumentReference(target_project_id=target_project.id, target_document_id=target_document.id, source_project_id=project.id, source_document_id=document.id, source_version_id=version.id, source_project_name_snapshot=project.name, source_document_name_snapshot=document.title, reference_mode="linked", status="active", created_by=user_uuid, last_synced_at=now, created_at=now, updated_at=now)
        session.add(reference)
        session.flush()
        reference_event = DocumentReferenceEvent(reference_id=reference.id, event_type="source_updated", source_project_id=project.id, source_document_id=document.id, old_source_version_id=None, new_source_version_id=version.id, message="Source updated during live coverage.", is_read=False, created_at=now)
        session.add(reference_event)

        conversation_id = uuid4()
        chat_record = ChatRecord(
            project_id=project.id,
            document_version_id=version.id,
            scope_mode="published",
            conversation_id=conversation_id,
            conversation_title="Live coverage conversation",
            selected_document_version_ids=[str(version.id)],
            question="What does Alpha cover?",
            answer="Alpha covers GPU isolation.",
            reference_docs=[{"document_id": str(document.id), "document_version_id": str(version.id), "chunk_id": str(chunk_one.id), "title": chunk_one.title, "score": 0.9, "excerpt": chunk_one.content, "content_type": "text"}],
            evaluation="not_evaluated",
            llm_model_id=chat_model.id,
            embedding_model_id=embedding_model.id,
            prompt_version="pytest",
            system_prompt_source="backend_default",
            system_prompt_layers=[],
            token_usage={"input": 10, "output": 5},
            latency_ms=12,
            created_by=user_uuid,
            asked_at=now,
            answered_at=now,
            created_at=now,
        )
        session.add(chat_record)
        staging_conversation_id = uuid4()
        staging_chat_record = ChatRecord(
            project_id=project.id,
            document_version_id=version.id,
            scope_mode="document_staging",
            conversation_id=staging_conversation_id,
            conversation_title="Live coverage document conversation",
            selected_document_version_ids=[str(version.id)],
            question="What does Beta cover?",
            answer="Beta covers retrieval validation.",
            reference_docs=[{"document_id": str(document.id), "document_version_id": str(version.id), "chunk_id": str(chunk_two.id), "title": chunk_two.title, "score": 0.88, "excerpt": chunk_two.content, "content_type": "text"}],
            evaluation="not_evaluated",
            llm_model_id=chat_model.id,
            embedding_model_id=embedding_model.id,
            prompt_version="pytest",
            system_prompt_source="backend_default",
            system_prompt_layers=[],
            token_usage={"input": 8, "output": 4},
            latency_ms=10,
            created_by=user_uuid,
            asked_at=now,
            answered_at=now,
            created_at=now,
        )
        session.add(staging_chat_record)

        notification = Notification(recipient_user_id=user_uuid, project_id=project.id, notification_type="live.coverage", severity="info", title="Live coverage notification", message="Notification for live API coverage", action_type="open_project", action_payload={"project_id": str(project.id)}, is_read=False, created_at=now)
        session.add(notification)
        session.commit()

        return {
            "project_id": str(project.id),
            "target_project_id": str(target_project.id),
            "document_id": str(document.id),
            "version_id": str(version.id),
            "chunk_id": str(chunk_one.id),
            "review_document_id": str(review_document.id),
            "review_version_id": str(review_version.id),
            "pipeline_id": str(pipeline.id),
            "conversation_id": str(conversation_id),
            "staging_conversation_id": str(staging_conversation_id),
            "chat_record_id": str(chat_record.id),
            "notification_id": str(notification.id),
            "reference_id": str(reference.id),
            "reference_event_id": str(reference_event.id),
            "source_text": source_text,
        }


def test_live_auth_health_and_error_envelope(live_client) -> None:
    client, headers, user_id, _role_id = live_client

    assert client.get("/").json()["message"] == "NomoSmart API"
    assert client.get("/api/v1/health").json() == {"status": "healthy"}
    ready = client.get("/api/v1/ready")
    assert ready.status_code in {200, 503}
    assert "status" in ready.json()
    oidc = _assert_ok(client.get("/api/v1/auth/oidc/config"))
    assert oidc["authorization_flow"] == "authorization_code_pkce"

    me = _assert_ok(client.get("/api/v1/auth/me", headers=headers))
    assert me["user_id"] == user_id
    assert any(item["module_name"] == MENU_MODULE for item in me["permissions"])

    unauth = client.get("/api/v1/users")
    assert unauth.status_code == 401
    assert unauth.json().get("detail") or unauth.json().get("code")
    missing = client.get("/api/v1/no-such-route", headers=headers)
    assert missing.status_code == 404
    assert missing.json().get("detail") or missing.json().get("code")


def test_live_role_user_project_model_and_prompt_flow(live_client) -> None:
    client, headers, user_id, _role_id = live_client

    users = _assert_ok(client.get("/api/v1/users", headers=headers))
    assert any(row["id"] == user_id for row in users)
    project_candidates = _assert_ok(client.get("/api/v1/users?scope=project_members", headers=headers))
    assert any(row["id"] == user_id for row in project_candidates)
    updated_user = _assert_ok(client.put(f"/api/v1/users/{user_id}", headers=headers, json={"knowledge_owner": True, "system_notes": TEST_PREFIX}))
    assert updated_user["knowledge_owner"] is True
    assert _assert_ok(client.patch(f"/api/v1/users/{user_id}/status", headers=headers, json={"is_active": True}))["is_active"] is True

    role_payload = {"name": f"{TEST_PREFIX}-editor", "description": "Created by live API test"}
    role = _assert_ok(client.post("/api/v1/roles", headers=headers, json=role_payload), 201)
    role_id = role["id"]
    role = _assert_ok(client.put(f"/api/v1/roles/{role_id}", headers=headers, json={"lock_version": role["lock_version"], "description": "Updated by live API test"}))
    permissions = _assert_ok(client.get(f"/api/v1/roles/{role_id}/permissions", headers=headers))
    replaced = _assert_ok(
        client.put(
            f"/api/v1/roles/{role_id}/permissions",
            headers=headers,
            json={
                "lock_version": permissions["lock_version"],
                "permissions": [
                    {"module_name": MENU_MODULE, "function_name": MENU_KNOWLEDGE_PROJECTS, "can_view": True, "can_create": False, "can_edit": False, "can_delete": False},
                    {"module_name": MENU_MODULE, "function_name": MENU_REPORTS, "can_view": True, "can_create": False, "can_edit": False, "can_delete": False},
                    {"module_name": MENU_MODULE, "function_name": MENU_SYSTEM_MANAGEMENT, "can_view": True, "can_create": False, "can_edit": False, "can_delete": False},
                    {"module_name": PROJECT_MODULE, "function_name": PROJECT_ARCHIVE, "can_view": False, "can_create": False, "can_edit": False, "can_delete": False, "can_execute": True},
                ],
            },
        )
    )
    assert any(permission["module_name"] == PROJECT_MODULE and permission["function_name"] == PROJECT_ARCHIVE and permission["can_execute"] for permission in replaced["permissions"])
    role_users = _assert_ok(client.put(f"/api/v1/roles/{role_id}/users", headers=headers, json={"lock_version": replaced["lock_version"], "user_ids": [user_id]}))
    assert role_users["users"][0]["user_id"] == user_id

    embedding = _assert_ok(
        client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "name": f"{TEST_PREFIX}-embedding",
                "model_type": "Embedding",
                "provider": "custom",
                "endpoint": "http://127.0.0.1:65535/embedding",
                "is_active": True,
                "config": {"model_name": "codex-embedding"},
            },
        ),
        201,
    )
    chat = _assert_ok(
        client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "name": f"{TEST_PREFIX}-chat",
                "model_type": "Chat",
                "provider": "custom",
                "endpoint": "http://127.0.0.1:65535/chat",
                "is_active": True,
                "config": {"model_name": "codex-chat", "paired_embedding_model_ids": [embedding["id"]]},
            },
        ),
        201,
    )
    ocr = _assert_ok(
        client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "name": f"{TEST_PREFIX}-ocr",
                "model_type": "OCR",
                "provider": "custom",
                "endpoint": "http://127.0.0.1:65535/ocr",
                "is_active": True,
                "config": {"model_name": "codex-ocr"},
            },
        ),
        201,
    )
    incompatible_embedding = _assert_ok(
        client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "name": f"{TEST_PREFIX}-incompatible-embedding",
                "model_type": "Embedding",
                "provider": "other-provider",
                "endpoint": "http://127.0.0.1:65535/incompatible-embedding",
                "is_active": True,
                "config": {"model_name": "codex-incompatible-embedding"},
            },
        ),
        201,
    )
    assert _assert_ok(client.get("/api/v1/models?model_type=Chat", headers=headers))
    tested = client.post(f"/api/v1/models/{chat['id']}/test", headers=headers)
    assert tested.status_code == 422
    assert tested.json()["code"] == "model_credential_required"
    defaulted = _assert_ok(client.post(f"/api/v1/models/{embedding['id']}/set-default", headers=headers))
    assert defaulted["is_default"] is True
    updated_model = _assert_ok(client.put(f"/api/v1/models/{chat['id']}", headers=headers, json={"endpoint": "http://127.0.0.1:65535/chat-v2", "config": {"model_name": "codex-chat-v2", "paired_embedding_model_ids": [embedding["id"]]}}))
    assert updated_model["config_version"] >= chat["config_version"]
    bad_model = client.post("/api/v1/models", headers=headers, json={"name": f"{TEST_PREFIX}-bad", "model_type": "Chat", "provider": "custom", "endpoint": "http://127.0.0.1:1", "config": {"api_key": "not allowed"}})
    assert bad_model.status_code == 422

    missing_models = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": f"{TEST_PREFIX}-missing-models", "members": []},
    )
    assert missing_models.status_code == 422
    assert missing_models.json()["code"] == "project_model_configuration_required"
    assert missing_models.json()["details"]["missing_model_types"] == ["chat", "ocr", "embedding"]

    missing_ocr = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"{TEST_PREFIX}-missing-ocr",
            "llm_model_id": chat["id"],
            "embedding_model_id": embedding["id"],
            "members": [],
        },
    )
    assert missing_ocr.status_code == 422
    assert missing_ocr.json()["code"] == "project_model_configuration_required"
    assert missing_ocr.json()["details"]["missing_model_types"] == ["ocr"]

    invalid_pair = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"{TEST_PREFIX}-invalid-pair",
            "llm_model_id": chat["id"],
            "embedding_model_id": incompatible_embedding["id"],
            "ocr_model_id": ocr["id"],
            "members": [],
        },
    )
    assert invalid_pair.status_code == 422
    assert invalid_pair.json()["code"] == "project_model_pair_required"

    wrong_type = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"{TEST_PREFIX}-wrong-model-type",
            "llm_model_id": ocr["id"],
            "embedding_model_id": embedding["id"],
            "ocr_model_id": ocr["id"],
            "members": [],
        },
    )
    assert wrong_type.status_code == 422
    assert wrong_type.json()["code"] == "project_model_configuration_required"
    assert wrong_type.json()["details"]["missing_model_types"] == ["chat"]

    incompatible_embedding = _assert_ok(client.put(f"/api/v1/models/{incompatible_embedding['id']}", headers=headers, json={"is_active": False}))
    inactive_model = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"{TEST_PREFIX}-inactive-model",
            "llm_model_id": chat["id"],
            "embedding_model_id": incompatible_embedding["id"],
            "ocr_model_id": ocr["id"],
            "members": [],
        },
    )
    assert inactive_model.status_code == 422
    assert inactive_model.json()["details"]["missing_model_types"] == ["embedding"]
    incompatible_embedding = _assert_ok(client.put(f"/api/v1/models/{incompatible_embedding['id']}", headers=headers, json={"is_active": True}))

    session_factory = get_session_factory()
    with session_factory() as session:
        failed_names = {
            f"{TEST_PREFIX}-missing-models",
            f"{TEST_PREFIX}-missing-ocr",
            f"{TEST_PREFIX}-invalid-pair",
            f"{TEST_PREFIX}-wrong-model-type",
            f"{TEST_PREFIX}-inactive-model",
        }
        assert session.scalar(select(Project.id).where(Project.name.in_(failed_names)).limit(1)) is None

    project = _assert_ok(
        client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "name": f"{TEST_PREFIX}-project",
                "description": "Live API project",
                "llm_model_id": chat["id"],
                "embedding_model_id": embedding["id"],
                "ocr_model_id": ocr["id"],
                "members": [],
            },
        ),
        201,
    )
    project_id = project["id"]
    assert isinstance(_assert_ok(client.get("/api/v1/projects?limit=200", headers=headers)), list)
    assert _assert_ok(client.get(f"/api/v1/projects/{project_id}", headers=headers))["id"] == project_id
    fetched_project = _assert_ok(client.get(f"/api/v1/projects/{project_id}", headers=headers))
    assert fetched_project["name"] == project["name"]
    members = _assert_ok(client.get(f"/api/v1/projects/{project_id}/members", headers=headers))
    assert any(member["user_id"] == user_id and "owner" in member["roles"] for member in members)
    stale_project = client.put(f"/api/v1/projects/{project_id}", headers=headers, json={"name": "stale", "lock_version": 999999})
    assert stale_project.status_code == 409
    project = _assert_ok(client.put(f"/api/v1/projects/{project_id}", headers=headers, json={"description": "Updated live API project", "lock_version": fetched_project["lock_version"]}))
    assert project["lock_version"] > fetched_project["lock_version"]
    cleared_model = client.put(f"/api/v1/projects/{project_id}", headers=headers, json={"llm_model_id": None, "lock_version": project["lock_version"]})
    assert cleared_model.status_code == 422
    assert cleared_model.json()["code"] == "project_model_configuration_required"
    assert _assert_ok(client.get(f"/api/v1/projects/{project_id}", headers=headers))["llm_model_id"] == chat["id"]

    prompt = _assert_ok(
        client.put(
            f"/api/v1/models/{chat['id']}/system-prompt",
            headers=headers,
            json={"content": "Use concise answers for live backend coverage.", "is_active": True},
        )
    )
    prompt_id = prompt["id"]
    assert _assert_ok(client.get(f"/api/v1/models/{chat['id']}/system-prompt", headers=headers))["id"] == prompt_id
    versions = _assert_ok(client.get(f"/api/v1/system-prompts/{prompt_id}/versions", headers=headers))
    assert versions
    prompt = _assert_ok(client.post(f"/api/v1/system-prompts/{prompt_id}/versions", headers=headers, json={"content": "Second version for live backend coverage.", "is_active": False}), 201)
    prompt = _assert_ok(client.post(f"/api/v1/system-prompts/{prompt_id}/activate", headers=headers, json={}))
    assert prompt["is_active"] is True
    prompt = _assert_ok(client.post(f"/api/v1/system-prompts/{prompt_id}/deactivate", headers=headers))
    assert prompt["is_active"] is False

    impact = _assert_ok(client.get(f"/api/v1/projects/{project_id}/archive-impact", headers=headers))
    legacy_archive = client.delete(f"/api/v1/projects/{project_id}?lock_version={project['lock_version']}", headers=headers)
    assert legacy_archive.status_code == 409
    assert legacy_archive.json()["code"] == "archive_confirmation_required"
    assert _assert_ok(client.post(f"/api/v1/projects/{project_id}/archive", headers=headers, json={"lock_version": impact["lock_version"], "confirmation_name": impact["project_name"]}))["status"] == "archived"
    deleted_chat = _assert_ok(client.request("DELETE", f"/api/v1/models/{chat['id']}", headers=headers, json={"confirmation_name": chat["name"], "config_version": updated_model["config_version"]}))
    assert deleted_chat["deleted_at"] is not None
    deleted_model = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"{TEST_PREFIX}-deleted-model",
            "llm_model_id": chat["id"],
            "embedding_model_id": incompatible_embedding["id"],
            "ocr_model_id": ocr["id"],
            "members": [],
        },
    )
    assert deleted_model.status_code == 422
    assert deleted_model.json()["details"]["missing_model_types"] == ["chat"]
    assert _assert_ok(client.put(f"/api/v1/models/{embedding['id']}", headers=headers, json={"is_active": False}))["is_active"] is False
    deleted_ocr = client.request("DELETE", f"/api/v1/models/{ocr['id']}", headers=headers, json={"confirmation_name": ocr["name"], "config_version": ocr["config_version"]})
    assert deleted_ocr.status_code in {200, 409}
    assert client.request(
        "DELETE",
        f"/api/v1/models/{incompatible_embedding['id']}",
        headers=headers,
        json={"confirmation_name": incompatible_embedding["name"], "config_version": incompatible_embedding["config_version"]},
    ).status_code in {200, 409}
    assert _assert_ok(client.delete(f"/api/v1/roles/{role_id}", headers=headers, params={"lock_version": role_users["lock_version"], "confirmation_name": role_payload["name"]}))["is_active"] is False


def test_live_local_role_ldap_group_one_to_one_mapping(live_client) -> None:
    client, headers, user_id, _role_id = live_client
    session_factory = get_session_factory()
    role_ids: list[UUID] = []
    group_ids: list[UUID] = []

    try:
        first_role = _assert_ok(client.post("/api/v1/roles", headers=headers, json={"name": f"{TEST_PREFIX}-ldap-role-a", "description": "CHG-233 mapping role A"}), 201)
        second_role = _assert_ok(client.post("/api/v1/roles", headers=headers, json={"name": f"{TEST_PREFIX}-ldap-role-b", "description": "CHG-233 mapping role B"}), 201)
        role_ids.extend((UUID(first_role["id"]), UUID(second_role["id"])))

        manual_membership = _assert_ok(
            client.put(
                f"/api/v1/roles/{first_role['id']}/users",
                headers=headers,
                json={"lock_version": first_role["lock_version"], "user_ids": [user_id]},
            )
        )
        first_role["lock_version"] = manual_membership["lock_version"]

        now = datetime.now(UTC)
        with session_factory() as session:
            ldap_a = ExternalGroup(source="keycloak", external_group_id=f"{TEST_PREFIX}-ldap-a", group_name="engineering", path="/ldap/engineering", identity_origin="ldap", is_active=True, last_synced_at=now)
            ldap_b = ExternalGroup(source="keycloak", external_group_id=f"{TEST_PREFIX}-ldap-b", group_name="legal", path="/ldap/legal", identity_origin="ldap", is_active=True, last_synced_at=now)
            local_group = ExternalGroup(source="keycloak", external_group_id=f"{TEST_PREFIX}-local", group_name="local-admin", path="/local-admin", identity_origin="keycloak_local", is_active=True, last_synced_at=now)
            session.add_all((ldap_a, ldap_b, local_group))
            session.flush()
            group_ids.extend((ldap_a.id, ldap_b.id, local_group.id))
            session.add_all(
                (
                    ExternalGroupUser(external_group_id=ldap_a.id, user_id=UUID(user_id), created_at=now),
                    ExternalGroupUser(external_group_id=ldap_b.id, user_id=UUID(user_id), created_at=now),
                )
            )
            session.commit()

        group_rows = _assert_ok(client.get("/api/v1/external-groups", headers=headers))
        test_groups = {row["external_group_id"]: row for row in group_rows if row["id"] in {str(group_id) for group_id in group_ids}}
        assert test_groups[f"{TEST_PREFIX}-ldap-a"]["identity_origin"] == "ldap"
        assert test_groups[f"{TEST_PREFIX}-ldap-a"]["member_count"] == 1
        assert test_groups[f"{TEST_PREFIX}-local"]["identity_origin"] == "keycloak_local"

        mapped = _assert_ok(
            client.put(
                f"/api/v1/roles/{first_role['id']}/external-group-mapping",
                headers=headers,
                json={"external_group_id": str(group_ids[0]), "lock_version": first_role["lock_version"]},
            )
        )
        assert mapped["derived_member_count"] == 1
        first_role["lock_version"] = mapped["lock_version"]
        role_users = _assert_ok(client.get(f"/api/v1/roles/{first_role['id']}/users", headers=headers))
        assert {(row["user_id"], row["source"]) for row in role_users["users"]} == {(user_id, "manual"), (user_id, "external_sync")}

        duplicate_group = client.put(
            f"/api/v1/roles/{second_role['id']}/external-group-mapping",
            headers=headers,
            json={"external_group_id": str(group_ids[0]), "lock_version": second_role["lock_version"]},
        )
        assert duplicate_group.status_code == 409
        assert duplicate_group.json()["code"] == "external_group_already_mapped"

        invalid_local_group = client.put(
            f"/api/v1/roles/{first_role['id']}/external-group-mapping",
            headers=headers,
            json={"external_group_id": str(group_ids[2]), "lock_version": first_role["lock_version"]},
        )
        assert invalid_local_group.status_code == 422
        assert invalid_local_group.json()["code"] == "invalid_ldap_group_mapping"

        stale_mapping = client.put(
            f"/api/v1/roles/{first_role['id']}/external-group-mapping",
            headers=headers,
            json={"external_group_id": str(group_ids[1]), "lock_version": first_role["lock_version"] - 1},
        )
        assert stale_mapping.status_code == 409
        assert stale_mapping.json()["code"] == "stale_role_version"

        remapped = _assert_ok(
            client.put(
                f"/api/v1/roles/{first_role['id']}/external-group-mapping",
                headers=headers,
                json={"external_group_id": str(group_ids[1]), "lock_version": first_role["lock_version"]},
            )
        )
        first_role["lock_version"] = remapped["lock_version"]
        mappings = _assert_ok(client.get("/api/v1/external-group-role-mappings", headers=headers))
        assert [row for row in mappings if row["role_id"] == first_role["id"]] == [{"external_group_id": str(group_ids[1]), "role_id": first_role["id"]}]

        unmapped = _assert_ok(
            client.put(
                f"/api/v1/roles/{first_role['id']}/external-group-mapping",
                headers=headers,
                json={"external_group_id": None, "lock_version": first_role["lock_version"]},
            )
        )
        assert unmapped["derived_member_count"] == 0
        first_role["lock_version"] = unmapped["lock_version"]
        role_users = _assert_ok(client.get(f"/api/v1/roles/{first_role['id']}/users", headers=headers))
        assert role_users["users"] == [{"user_id": user_id, "source": "manual"}]

        mapped_again = _assert_ok(
            client.put(
                f"/api/v1/roles/{first_role['id']}/external-group-mapping",
                headers=headers,
                json={"external_group_id": str(group_ids[0]), "lock_version": first_role["lock_version"]},
            )
        )
        first_role["lock_version"] = mapped_again["lock_version"]
        disabled = _assert_ok(client.put(f"/api/v1/roles/{first_role['id']}", headers=headers, json={"lock_version": first_role["lock_version"], "is_active": False}))
        assert disabled["is_active"] is False
        first_role["lock_version"] = disabled["lock_version"]
        mappings = _assert_ok(client.get("/api/v1/external-group-role-mappings", headers=headers))
        assert [row for row in mappings if row["role_id"] == first_role["id"]] == [{"external_group_id": str(group_ids[0]), "role_id": first_role["id"]}]
        disabled_users = _assert_ok(client.get(f"/api/v1/roles/{first_role['id']}/users", headers=headers))
        assert disabled_users["users"] == [{"user_id": user_id, "source": "manual"}]
        inactive_write = client.put(f"/api/v1/roles/{first_role['id']}/users", headers=headers, json={"lock_version": first_role["lock_version"], "user_ids": []})
        assert inactive_write.status_code == 409
        assert inactive_write.json()["code"] == "inactive_role_read_only"

        enabled = _assert_ok(client.put(f"/api/v1/roles/{first_role['id']}", headers=headers, json={"lock_version": first_role["lock_version"], "is_active": True}))
        assert enabled["is_active"] is True
        first_role["lock_version"] = enabled["lock_version"]
        enabled_users = _assert_ok(client.get(f"/api/v1/roles/{first_role['id']}/users", headers=headers))
        assert {(row["user_id"], row["source"]) for row in enabled_users["users"]} == {(user_id, "manual"), (user_id, "external_sync")}

        wrong_confirmation = client.delete(f"/api/v1/roles/{first_role['id']}", headers=headers, params={"lock_version": first_role["lock_version"], "confirmation_name": "wrong-name"})
        assert wrong_confirmation.status_code == 422
        assert wrong_confirmation.json()["code"] == "role_confirmation_mismatch"
        deleted = _assert_ok(client.delete(f"/api/v1/roles/{first_role['id']}", headers=headers, params={"lock_version": first_role["lock_version"], "confirmation_name": first_role["name"]}))
        assert deleted["is_active"] is False
        assert client.get(f"/api/v1/roles/{first_role['id']}/users", headers=headers).status_code == 404
        assert all(row["id"] != first_role["id"] for row in _assert_ok(client.get("/api/v1/roles?limit=200", headers=headers)))
        with session_factory() as session:
            tombstone = session.get(Role, UUID(first_role["id"]))
            assert tombstone is not None and tombstone.deleted_at is not None and tombstone.deleted_by == UUID(user_id)
            assert session.scalar(select(RoleUser).where(RoleUser.role_id == tombstone.id, RoleUser.user_id == UUID(user_id), RoleUser.source == "manual")) is not None
            assert session.scalar(select(ExternalGroupRoleMapping).where(ExternalGroupRoleMapping.role_id == tombstone.id)) is None

        recreated = _assert_ok(client.post("/api/v1/roles", headers=headers, json={"name": first_role["name"], "description": "Reused after CHG-237 soft delete"}), 201)
        assert recreated["id"] != first_role["id"]
        role_ids.append(UUID(recreated["id"]))

        reused = _assert_ok(
            client.put(
                f"/api/v1/roles/{second_role['id']}/external-group-mapping",
                headers=headers,
                json={"external_group_id": str(group_ids[0]), "lock_version": second_role["lock_version"]},
            )
        )
        assert reused["derived_member_count"] == 1
        _assert_ok(client.delete(f"/api/v1/roles/{second_role['id']}", headers=headers, params={"lock_version": reused["lock_version"], "confirmation_name": second_role["name"]}))

        assert client.put("/api/v1/external-group-role-mappings", headers=headers, json={"mappings": []}).status_code == 405

        system_role = next((row for row in _assert_ok(client.get("/api/v1/roles?limit=200", headers=headers)) if row["name"] == "system-admin"), None)
        assert system_role is not None
        protected_update = client.put(f"/api/v1/roles/{system_role['id']}", headers=headers, json={"lock_version": system_role["lock_version"], "name": f"{TEST_PREFIX}-renamed-system-admin"})
        assert protected_update.status_code == 409
        assert protected_update.json()["code"] == "system_role_protected"
        protected_delete = client.delete(f"/api/v1/roles/{system_role['id']}", headers=headers, params={"lock_version": system_role["lock_version"], "confirmation_name": system_role["name"]})
        assert protected_delete.status_code == 409
        assert protected_delete.json()["code"] == "system_role_protected"
    finally:
        with session_factory() as session:
            if role_ids:
                session.execute(delete(Role).where(Role.id.in_(role_ids)))
            if group_ids:
                session.execute(delete(ExternalGroup).where(ExternalGroup.id.in_(group_ids)))
            session.commit()


def test_live_system_reports_and_session_drafts(live_client) -> None:
    client, headers, user_id, _role_id = live_client

    parameters = _assert_ok(client.get("/api/v1/system/parameters", headers=headers))
    assert parameters["max_upload_size_mb"] >= 1
    upload = _assert_ok(client.get("/api/v1/system/upload-config", headers=headers))
    assert upload["max_upload_size_mb"] >= 1
    status = _assert_ok(client.get("/api/v1/system/status", headers=headers))
    assert isinstance(status.get("dependencies"), list)
    assert "status" in _assert_ok(client.get("/api/v1/system/break-glass/status", headers=headers))
    assert _assert_ok(client.put("/api/v1/system/parameters", headers=headers, json=parameters))["default_timezone"] == parameters["default_timezone"]

    report_topics = [
        "system_overview",
        "project_ranking",
        "project_reference_ranking",
        "document_reference_ranking",
        "owner_project_summary",
        "document_pipeline_metrics",
        "rag_quality_metrics",
        "validation_run_metrics",
        "model_usage_metrics",
        "alert_metrics",
    ]
    for topic in report_topics:
        summary = _assert_ok(client.get(f"/api/v1/reports/summary?topic={topic}&limit=20", headers=headers))
        assert summary["topic"] == topic
        assert summary["scope"] == "system"
        assert summary["columns"]
        csv_response = client.get(f"/api/v1/reports/export.csv?topic={topic}&locale=zh&limit=20", headers=headers)
        assert csv_response.status_code == 200
        assert csv_response.content.startswith(b"\xef\xbb\xbf")
    dated = _assert_ok(client.get("/api/v1/reports/summary?topic=project_ranking&date_from=2026-01-01T00:00:00Z&date_to=2026-12-31T23:59:59Z&limit=10", headers=headers))
    assert dated["date_from"].startswith("2026-01-01")
    bad_range = client.get("/api/v1/reports/summary?topic=project_ranking&date_from=2026-12-31T00:00:00Z&date_to=2026-01-01T00:00:00Z", headers=headers)
    assert bad_range.status_code == 422
    bad_topic = client.get("/api/v1/reports/summary?topic=not-a-topic", headers=headers)
    assert bad_topic.status_code == 422

    default_options = _assert_ok(client.get("/api/v1/reports/filter-options", headers=headers))
    assert default_options["selected_scope"] == "owner_projects"
    owner_options = _assert_ok(client.get("/api/v1/reports/filter-options?scope=owner_projects", headers=headers))
    assert owner_options["selected_scope"] == "owner_projects"
    assert {item["value"] for item in owner_options["scopes"]} >= {"owner_projects", "accessible", "reviewer", "system"}
    system_options = _assert_ok(client.get("/api/v1/reports/filter-options?scope=system", headers=headers))
    assert system_options["selected_scope"] == "system"
    assert client.get("/api/v1/reports/filter-options?scope=unsupported", headers=headers).status_code == 422

    session_factory = get_session_factory()
    report_project_ids: list[UUID] = []
    with session_factory() as session:
        now = datetime.now(UTC)
        for index in range(21):
            project = Project(name=f"{TEST_PREFIX}-report-{index:02d}", description="REPORT-011 pagination coverage", status="active", created_by=UUID(user_id))
            session.add(project)
            session.flush()
            report_project_ids.append(project.id)
            session.add(ProjectOwner(project_id=project.id, user_id=UUID(user_id), created_at=now))
        session.commit()
    try:
        first_page = _assert_ok(client.get("/api/v1/reports/summary?topic=owner_project_summary&scope=owner_projects&page=1&page_size=20", headers=headers))
        assert first_page["page"] == 1
        assert first_page["page_size"] == 20
        assert first_page["total_rows"] >= 21
        assert first_page["total_pages"] >= 2
        assert len(first_page["rows"]) == 20
        second_page = _assert_ok(client.get("/api/v1/reports/summary?topic=owner_project_summary&scope=owner_projects&page=2&page_size=20", headers=headers))
        assert second_page["page"] == 2
        assert {row["project_id"] for row in first_page["rows"]}.isdisjoint({row["project_id"] for row in second_page["rows"]})
        out_of_range = client.get(f"/api/v1/reports/summary?topic=owner_project_summary&scope=owner_projects&page={first_page['total_pages'] + 1}&page_size=20", headers=headers)
        assert out_of_range.status_code == 422
        fixed_page_size = client.get("/api/v1/reports/summary?topic=owner_project_summary&scope=owner_projects&page_size=10", headers=headers)
        assert fixed_page_size.status_code == 422
        complete_csv = client.get("/api/v1/reports/export.csv?topic=owner_project_summary&scope=owner_projects&locale=en", headers=headers)
        assert complete_csv.status_code == 200
        csv_rows = list(csv.reader(io.StringIO(complete_csv.content.decode("utf-8-sig"))))
        assert len(csv_rows) == first_page["total_rows"] + 1
    finally:
        with session_factory() as session:
            session.execute(delete(ProjectOwner).where(ProjectOwner.project_id.in_(report_project_ids)))
            session.execute(delete(Project).where(Project.id.in_(report_project_ids)))
            session.commit()

    nonce_one = f"{TEST_PREFIX}-nonce-0001"
    nonce_two = f"{TEST_PREFIX}-nonce-0002"
    nonce_three = f"{TEST_PREFIX}-nonce-0003"
    draft_payload = {"form_key": f"{TEST_PREFIX}-form", "return_path": "/projects", "nonce": nonce_one, "payload": {"field": "value", "count": 1}}
    draft = _assert_ok(client.post("/api/v1/auth/session-drafts", headers=headers, json=draft_payload), 200)
    restored = _assert_ok(client.post(f"/api/v1/auth/session-drafts/{draft['draft_id']}/restore", headers=headers, json={"return_path": "/projects", "nonce": nonce_one}))
    assert restored["payload"]["field"] == "value"
    draft2_payload = {"form_key": f"{TEST_PREFIX}-form-2", "return_path": "/projects", "nonce": nonce_two, "payload": {"field": "value"}}
    draft2 = _assert_ok(client.post("/api/v1/auth/session-drafts", headers=headers, json=draft2_payload), 200)
    assert _assert_ok(client.post(f"/api/v1/auth/session-drafts/{draft2['draft_id']}/discard", headers=headers, json={"return_path": "/projects", "nonce": nonce_two}))["status"] == "discarded"
    sensitive = client.post("/api/v1/auth/session-drafts", headers=headers, json={"form_key": "bad", "return_path": "/projects", "nonce": nonce_three, "payload": {"password": "secret"}})
    assert sensitive.status_code == 422

    assert "state" in _assert_ok(client.get("/api/v1/system/identity-settings", headers=headers))
    reauth = client.post("/api/v1/system/identity-settings/reauth/start", headers=headers)
    assert reauth.status_code == 401
    assert reauth.json()["code"] == "reauth_session_required"
    locked = client.put(
        "/api/v1/system/identity-settings",
        headers=headers,
        json={
            "deployment_mode": "appliance",
            "oidc_issuer_url": os.environ["OIDC_ISSUER_URL"],
            "oidc_client_id": os.environ["OIDC_CLIENT_ID"],
            "oidc_audience": os.environ["OIDC_AUDIENCE"],
            "sync_source": "keycloak",
            "sync_schedule": "0 2 * * *",
            "sync_timezone": "Asia/Taipei",
        },
    )
    assert locked.status_code in {422, 423}

    retired_paths = (
        "/api/v1/system-initialization",
        "/api/v1/system-initialization/status",
        "/api/v1/system-initialization/validate",
        "/api/v1/system-initialization/apply",
        "/api/v1/system-initialization/rollback",
        "/api/v1/system-initialization/unlock/start",
        "/api/v1/system-initialization/unlock/complete",
        "/api/v1/system-initialization/unlock",
        "/api/v1/system-initialization/lock",
    )
    with get_session_factory()() as session:
        legacy_before = (
            session.scalar(text("SELECT count(*) FROM system_initialization_state")),
            session.scalar(text("SELECT count(*) FROM system_initialization_steps")),
        )
    for path in retired_paths:
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            response = client.request(
                method,
                path,
                headers={**headers, "X-NomoSmart-Bootstrap-Token": "retired"},
                json={} if method != "GET" else None,
            )
            assert response.status_code == 404
    with get_session_factory()() as session:
        legacy_after = (
            session.scalar(text("SELECT count(*) FROM system_initialization_state")),
            session.scalar(text("SELECT count(*) FROM system_initialization_steps")),
        )
    assert legacy_after == legacy_before


def test_live_seeded_document_knowledge_serving_chat_and_notifications(live_client) -> None:
    client, headers, user_id, _role_id = live_client
    data = _seed_live_document_workspace(get_session_factory(), user_id)
    project_id = data["project_id"]
    document_id = data["document_id"]
    version_id = data["version_id"]
    chunk_id = data["chunk_id"]

    documents = _assert_ok(client.get(f"/api/v1/projects/{project_id}/documents", headers=headers))
    assert any(item["id"] == document_id for item in documents)
    knowledge = _assert_ok(client.get(f"/api/v1/projects/{project_id}/documents/{document_id}/knowledge", headers=headers))
    assert knowledge["document"]["id"] == document_id
    assert knowledge["source_mapping_available"] is True
    assert knowledge["markdown_artifact_status"] == "available"
    assert knowledge["markdown_artifact_reason_code"] is None
    assert knowledge["markdown_text"] == "Alpha architecture controls GPU isolation and API routing.\n\nBeta retrieval validates chunk tags and document tags."
    assert knowledge["document_tags"]
    assert knowledge["chunks"]

    pipeline = _assert_ok(client.get(f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/pipelines/{data['pipeline_id']}", headers=headers))
    assert pipeline["status"] == "completed"
    assert len(pipeline["steps"]) >= 10

    manual_denied = client.post(
        f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/manual",
        headers=headers,
        json={
            "content": "architecture controls GPU",
            "start_offset": 6,
            "end_offset": 31,
            "source_anchor": "body-1",
            "view_mode": "markdown",
            "lock_version": knowledge["version"]["lock_version"],
        },
    )
    assert manual_denied.status_code == 409
    assert manual_denied.json()["code"] == "document_version_not_editable"
    latest_chunk_id = chunk_id

    tagged_chunk = _assert_ok(
        client.post(
            f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/{latest_chunk_id}/tags",
            headers=headers,
            json={"tag_text": f"{TEST_PREFIX}-manual-chunk-tag"},
        )
    )
    new_chunk_tag = next(tag for chunk in tagged_chunk["chunks"] if chunk["id"] == latest_chunk_id for tag in chunk["tag_details"] if tag["tag_text"] == f"{TEST_PREFIX}-manual-chunk-tag")
    after_chunk_tag_delete = _assert_ok(client.delete(f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/{latest_chunk_id}/tags/{new_chunk_tag['tag_id']}", headers=headers))
    assert all(tag["tag_id"] != new_chunk_tag["tag_id"] for chunk in after_chunk_tag_delete["chunks"] for tag in chunk["tag_details"])

    tagged_document = _assert_ok(client.post(f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/tags", headers=headers, json={"tag_text": f"{TEST_PREFIX}-manual-document-tag"}))
    new_document_tag = next(tag for tag in tagged_document["document_tags"] if tag["tag_text"] == f"{TEST_PREFIX}-manual-document-tag")
    after_document_tag_delete = _assert_ok(client.delete(f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/tags/{new_document_tag['tag_id']}", headers=headers))
    assert all(tag["tag_id"] != new_document_tag["tag_id"] for tag in after_document_tag_delete["document_tags"])
    assert client.post(f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/{latest_chunk_id}/tags/auto", headers=headers, json={"max_tags": 3}).status_code in {200, 409, 502, 503}
    assert client.post(f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/tags/auto", headers=headers, json={"max_tags": 3}).status_code in {200, 409, 502, 503}

    inactive_impact = _assert_ok(client.get(f"/api/v1/projects/{project_id}/documents/{document_id}/lifecycle-impact?status=inactive", headers=headers))
    assert inactive_impact["requested_status"] == "inactive"
    document_lock = after_document_tag_delete["document"]["lock_version"]
    inactive_document = _assert_ok(client.patch(f"/api/v1/projects/{project_id}/documents/{document_id}/lifecycle", headers=headers, json={"status": "inactive", "lock_version": document_lock, "impact_confirmed": True, "reason": "live coverage"}))
    assert inactive_document["status"] == "inactive"
    active_document = _assert_ok(client.patch(f"/api/v1/projects/{project_id}/documents/{document_id}/lifecycle", headers=headers, json={"status": "active", "lock_version": inactive_document["lock_version"], "impact_confirmed": True, "reason": "live coverage"}))
    assert active_document["status"] == "active"

    serving = _assert_ok(client.get(f"/api/v1/projects/{project_id}/serving-status", headers=headers))
    assert serving["readiness"] == "ready"
    assert serving["active_document_count"] >= 1
    assert any(item.get("chunk_count", 0) >= 1 for item in serving["documents"])
    project_graph = _assert_ok(client.get(f"/api/v1/projects/{project_id}/graph?node_limit=80", headers=headers))
    assert any(node["id"] == project_id for node in project_graph["nodes"])
    assert {node["type"] for node in project_graph["nodes"]} >= {"Project", "Document", "DocumentVersion", "Chunk"}
    document_graph = _assert_ok(
        client.get(
            f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/graph?node_limit=80",
            headers=headers,
        )
    )
    assert {node["id"] for node in document_graph["nodes"]} >= {project_id, document_id, version_id}
    scoped_path = _assert_ok(
        client.get(
            f"/api/v1/projects/{project_id}/graph/paths?source_id={project_id}&target_id={version_id}&max_depth=4&node_limit=80",
            headers=headers,
        )
    )
    assert {node["id"] for node in scoped_path["nodes"]} >= {project_id, document_id, version_id}
    assert client.get("/api/v1/knowledge-graph?node_limit=500", headers=headers).status_code == 404
    assert client.get("/api/v1/knowledge-graph/neighbors?node_id=hidden&node_limit=40", headers=headers).status_code == 404
    assert client.get(
        f"/api/v1/knowledge-graph/paths?source_id={project_id}&target_id={version_id}",
        headers=headers,
    ).status_code == 404
    neighbor_seed_node_id = project_graph["nodes"][0]["id"]
    neighbors = _assert_ok(client.get(f"/api/v1/projects/{project_id}/graph/neighbors?node_id={neighbor_seed_node_id}&node_limit=40", headers=headers))
    assert isinstance(neighbors["nodes"], list)

    conversations = _assert_ok(client.get(f"/api/v1/projects/{project_id}/chat/conversations", headers=headers))
    assert any(item["id"] == data["conversation_id"] for item in conversations)
    conversation = _assert_ok(client.get(f"/api/v1/projects/{project_id}/chat/conversations/{data['conversation_id']}", headers=headers))
    assert conversation["records"][0]["id"] == data["chat_record_id"]
    feedback_required = client.post(f"/api/v1/projects/{project_id}/chat/records/{data['chat_record_id']}/feedback", headers=headers, json={"evaluation": "needs_revision"})
    assert feedback_required.status_code == 422
    feedback = _assert_ok(client.post(f"/api/v1/projects/{project_id}/chat/records/{data['chat_record_id']}/feedback", headers=headers, json={"evaluation": "needs_revision", "revision_suggestion": "Add more detail."}))
    assert feedback["evaluation"] == "needs_revision"
    deleted = _assert_ok(client.delete(f"/api/v1/projects/{project_id}/chat/conversations/{data['conversation_id']}", headers=headers))
    assert deleted["deleted_count"] == 1
    assert client.delete(f"/api/v1/projects/{project_id}/chat/conversations/{data['conversation_id']}", headers=headers).status_code == 409
    assert client.get(f"/api/v1/projects/{project_id}/chat/conversations?scope_mode=document_staging", headers=headers).status_code == 422
    assert client.post(f"/api/v1/projects/{project_id}/chat/query", headers=headers, json={"question": "invalid scope", "document_version_ids": [str(uuid4())]}).status_code == 403
    staging_history = client.get(f"/api/v1/projects/{project_id}/chat/conversations?scope_mode=document_staging&document_version_id={version_id}", headers=headers)
    assert staging_history.status_code == 409
    assert staging_history.json()["code"] == "chunk_artifacts_not_ready"
    staging_answer = client.post(
        f"/api/v1/projects/{project_id}/chat/query",
        headers=headers,
        json={"scope_mode": "document_staging", "question": "zzzzzzzzzz unmatched live coverage term", "document_version_ids": [version_id]},
    )
    assert staging_answer.status_code in {200, 409}

    validation = _assert_ok(
        client.post(
            f"/api/v1/projects/{project_id}/chat/validation-runs",
            headers=headers,
            json={
                "uploaded_file_name": "questions.csv",
                "scope_mode": "published",
                "selected_document_version_ids": [version_id],
                "questions": [{"question": "What does Alpha cover?", "expected_keywords": ["GPU"], "selected_document_ids": [version_id], "category": "coverage", "priority": "high"}],
            },
        ),
        201,
    )
    fetched_validation = _assert_ok(client.get(f"/api/v1/projects/{project_id}/chat/validation-runs/{validation['id']}", headers=headers))
    assert fetched_validation["total_count"] == 1
    assert client.post(f"/api/v1/projects/{project_id}/chat/validation-runs/{validation['id']}/retry-failed", headers=headers).status_code == 409

    notifications = _assert_ok(client.get("/api/v1/notifications", headers=headers))
    assert any(item["id"] == data["notification_id"] for item in notifications)
    unread = _assert_ok(client.get("/api/v1/notifications/unread-count", headers=headers))
    assert unread["unread_count"] >= 1
    read = _assert_ok(client.post(f"/api/v1/notifications/{data['notification_id']}/read", headers=headers))
    assert read["is_read"] is True
    resolved = _assert_ok(client.post(f"/api/v1/notifications/{data['notification_id']}/resolve", headers=headers))
    assert resolved["resolved_at"] is not None
    assert _assert_ok(client.post("/api/v1/notifications/read-all", headers=headers))["unread_count"] == 0

    source_payload = {
        "service_type": "HTTP_API",
        "name": f"{TEST_PREFIX}-http-source",
        "host": "",
        "port": 443,
        "username": "",
        "file_name": "remote.md",
        "schedule_mode": "once",
        "url": "https://example.test/remote.md",
        "auth_mode": "none",
    }
    tested = client.post(f"/api/v1/projects/{project_id}/data-sources/test-connection", headers=headers, json=source_payload)
    assert tested.status_code in {422, 503}
    assert tested.json()["code"] in {"http_source_dns_failed", "http_source_ssrf_blocked", "connection_failed", "connection_timeout"}
    bad_source = client.post(f"/api/v1/projects/{project_id}/data-sources/test-connection", headers=headers, json={**source_payload, "url": "ftp://example.test/remote.md"})
    assert bad_source.status_code == 422
    created_source = _assert_ok(client.post(f"/api/v1/projects/{project_id}/data-sources", headers=headers, json={**source_payload, "name": f"{TEST_PREFIX}-http-created"}), 201)
    data_source_id = created_source["data_source"]["id"]
    assert created_source["sync_run"]["status"] == "queued"
    assert client.post(f"/api/v1/projects/{project_id}/data-sources/{data_source_id}/sync", headers=headers).status_code == 409
    source_runs = _assert_ok(client.get(f"/api/v1/projects/{project_id}/data-sources/{data_source_id}/sync-runs", headers=headers))
    assert any(item["id"] == created_source["sync_run"]["id"] for item in source_runs)

    upload_text = "# Uploaded live coverage\n\nThis upload verifies S3 storage and extraction failure handling."
    settings = get_settings()
    S3ObjectStorage(settings).ensure_bucket(settings.s3_bucket)
    uploaded = _assert_ok(
        client.post(
            f"/api/v1/projects/{project_id}/documents/upload",
            headers={**headers, "Idempotency-Key": f"{TEST_PREFIX}-upload-live-coverage"},
            data={"start_extraction": "true", "force_ocr": "false"},
            files={"file": ("uploaded-live-coverage.md", upload_text.encode("utf-8"), "text/markdown")},
        ),
        200,
    )
    assert uploaded["success_count"] == 1
    assert uploaded["failed_count"] == 0
    assert uploaded["results"][0]["started_extraction"] is True
    uploaded_document = uploaded["results"][0]["document"]
    uploaded_document_id = uploaded_document["id"]
    uploaded_version_id = uploaded_document["latest_version"]["id"]
    with get_session_factory()() as session:
        scan = session.scalar(select(FileScanRun).where(FileScanRun.document_version_id == UUID(uploaded_version_id)))
        assert scan is None
        upload_pipeline = session.scalar(select(PipelineRun).where(PipelineRun.document_version_id == UUID(uploaded_version_id)).order_by(PipelineRun.created_at.desc()))
        assert upload_pipeline is not None
        upload_pipeline_id = str(upload_pipeline.id)
    upload_detail = _assert_ok(client.get(f"/api/v1/projects/{project_id}/documents/{uploaded_document_id}/versions/{uploaded_version_id}/pipelines/{upload_pipeline_id}", headers=headers))
    assert upload_detail["status"] in {"queued", "running", "failed", "submission_ready", "completed"}
    original_file = client.get(f"/api/v1/projects/{project_id}/documents/{uploaded_document_id}/versions/{uploaded_version_id}/original-file", headers=headers)
    assert original_file.status_code == 200
    assert original_file.content.startswith(b"# Uploaded live coverage")
    preview_file = client.get(f"/api/v1/projects/{project_id}/documents/{uploaded_document_id}/versions/{uploaded_version_id}/preview", headers=headers)
    assert preview_file.status_code == 200
    assert preview_file.content
    same_file = _assert_ok(
        client.post(
            f"/api/v1/projects/{project_id}/documents/{uploaded_document_id}/versions/update-file",
            headers=headers,
            files={"file": ("uploaded-live-coverage.md", upload_text.encode("utf-8"), "text/markdown")},
        )
    )
    assert same_file["no_change"] is True
    changed_file = client.post(
            f"/api/v1/projects/{project_id}/documents/{uploaded_document_id}/versions/update-file",
            headers=headers,
            data={"force_ocr": "false"},
            files={"file": ("uploaded-live-coverage.md", b"# Changed live coverage\n\nA new revision.", "text/markdown")},
        )
    assert changed_file.status_code == 409
    assert changed_file.json()["code"] == "document_update_working_version_exists"


def test_live_seeded_reference_and_approval_workflows(live_client) -> None:
    client, headers, user_id, _role_id = live_client
    data = _seed_live_document_workspace(get_session_factory(), user_id)
    project_id = data["project_id"]
    target_project_id = data["target_project_id"]
    document_id = data["document_id"]
    version_id = data["version_id"]

    sources = _assert_ok(client.get(f"/api/v1/projects/{target_project_id}/reference-sources", headers=headers))
    assert any(project["id"] == project_id for project in sources)
    references = _assert_ok(client.get(f"/api/v1/projects/{target_project_id}/document-references", headers=headers))
    assert any(item["id"] == data["reference_id"] for item in references)
    copy_import = _assert_ok(
        client.post(
            f"/api/v1/projects/{target_project_id}/document-references/import",
            headers=headers,
            json={"mode": "copy", "items": [{"source_document_id": document_id, "source_version_id": version_id, "old_version_confirmed": False}]},
        ),
        201,
    )
    assert copy_import["results"][0]["status"] == "created"
    assert copy_import["results"][0]["document"]["id"]
    duplicate = client.post(f"/api/v1/projects/{target_project_id}/document-references", headers=headers, json={"source_document_id": document_id, "source_version_id": version_id})
    assert duplicate.status_code == 409
    multi_reference = client.post(
        f"/api/v1/projects/{target_project_id}/document-references/import",
        headers=headers,
        json={"mode": "reference", "items": [{"source_document_id": document_id, "source_version_id": version_id}, {"source_document_id": document_id, "source_version_id": version_id}]},
    )
    assert multi_reference.status_code == 422
    impacted = _assert_ok(client.get(f"/api/v1/document-reference-events/impacted-projects?source_document_id={document_id}", headers=headers))
    assert impacted["projects"]
    events = _assert_ok(client.get(f"/api/v1/document-reference-events?project_id={target_project_id}", headers=headers))
    assert any(item["id"] == data["reference_event_id"] for item in events)
    resolved = _assert_ok(client.post(f"/api/v1/document-reference-events/{data['reference_event_id']}/resolve", headers=headers))
    assert resolved["is_read"] is True
    sync_event = _assert_ok(client.post(f"/api/v1/document-references/{data['reference_id']}/sync", headers=headers), 202)
    assert sync_event["event_type"] == "manual_sync_requested"
    same_reference_version = _assert_ok(client.post(f"/api/v1/document-references/{data['reference_id']}/update", headers=headers, json={"source_version_id": version_id}))
    assert same_reference_version["no_change"] is True
    with get_session_factory()() as session:
        source_document = session.get(Document, UUID(document_id))
        source_version = session.get(DocumentVersion, UUID(version_id))
        assert source_document is not None and source_version is not None
        now = datetime.now(UTC)
        new_source_text = "Gamma reference update validates linked document refresh."
        new_source_version = DocumentVersion(
            project_id=source_document.project_id,
            document_id=source_document.id,
            version_major=source_version.version_major + 1,
            extraction_revision=0,
            version_label="v2.0",
            status="active",
            original_file_name="reference-update.md",
            canonical_extension=".md",
            mime_type="text/markdown",
            file_size=len(new_source_text.encode("utf-8")),
            content_sha256=_sha256(new_source_text),
            chunk_strategy={"source_text": new_source_text, "markdown_text": new_source_text},
            embedding_model_id=source_version.embedding_model_id,
            embedding_profile_id=source_version.embedding_profile_id,
            llm_model_id=source_version.llm_model_id,
            lock_version=1,
            processed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(new_source_version)
        session.flush()
        session.add(
            Chunk(
                project_id=source_document.project_id,
                document_id=source_document.id,
                document_version_id=new_source_version.id,
                chunk_index=1,
                title="Gamma reference update",
                content=new_source_text,
                markdown_content=new_source_text,
                content_type="text",
                content_hash=_sha256(new_source_text),
                start_offset=0,
                end_offset=len(new_source_text),
                source_mapping=[{"source_anchor": "reference-update"}],
                chunk_strategy={"source": "rule"},
                embedding_model_id=source_version.embedding_model_id,
                token_count=7,
                confidence_score=0.93,
                status="active",
                is_manual_edited=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
        new_source_version_id = str(new_source_version.id)
    updated_reference = _assert_ok(client.post(f"/api/v1/document-references/{data['reference_id']}/update", headers=headers, json={"source_version_id": new_source_version_id}))
    assert updated_reference["no_change"] is False
    detached = _assert_ok(client.post(f"/api/v1/document-references/{data['reference_id']}/detach", headers=headers))
    assert detached["status"] == "detached"

    submission_evidence = _assert_ok(client.get(f"/api/v1/projects/{project_id}/documents/{data['review_document_id']}/versions/{data['review_version_id']}/submission-evidence", headers=headers))
    approval = _assert_ok(client.post(f"/api/v1/projects/{project_id}/documents/{data['review_document_id']}/versions/{data['review_version_id']}/submit-review", headers={**headers, "Idempotency-Key": f"{TEST_PREFIX}-submit-review"}, json={"owner_user_id": user_id, "evidence_revision": submission_evidence["evidence_revision"], "lock_version": submission_evidence["lock_version"]}), 201)
    assert approval["status"] == "pending_manager_review"
    summary = _assert_ok(client.get("/api/v1/approvals/summary", headers=headers))
    assert summary["pending_total"] >= 1
    pending = _assert_ok(client.get("/api/v1/approvals/pending", headers=headers))["items"]
    manager_task = next(item for item in pending if item["approval_request_id"] == approval["id"])
    detail = _assert_ok(client.get(f"/api/v1/approvals/{manager_task['id']}", headers=headers))
    assert detail["task"]["review_stage"] == "manager_review"
    assert detail["chunks"]
    stale_approval = client.post(f"/api/v1/approvals/{manager_task['id']}/approve", headers={**headers, "Idempotency-Key": f"{TEST_PREFIX}-stale"}, json={"lock_version": 999999, "comment": "stale"})
    assert stale_approval.status_code == 409
    manager_approved = _assert_ok(client.post(f"/api/v1/approvals/{manager_task['id']}/approve", headers={**headers, "Idempotency-Key": f"{TEST_PREFIX}-manager"}, json={"lock_version": manager_task["lock_version"], "comment": "manager approved"}))
    assert manager_approved["status"] == "approved"
    pending_after_manager = _assert_ok(client.get("/api/v1/approvals/pending", headers=headers))["items"]
    owner_task = next(item for item in pending_after_manager if item["approval_request_id"] == approval["id"] and item["review_stage"] == "owner_review")
    owner_approved = _assert_ok(client.post(f"/api/v1/approvals/{owner_task['id']}/approve", headers={**headers, "Idempotency-Key": f"{TEST_PREFIX}-owner"}, json={"lock_version": owner_task["lock_version"], "comment": "owner approved"}))
    assert owner_approved["status"] == "approved"
    my_submissions = _assert_ok(client.get("/api/v1/approvals/my-submissions", headers=headers))["items"]
    assert any(item["id"] == approval["id"] and item["status"] == "approved" for item in my_submissions)
    history = _assert_ok(client.get("/api/v1/approvals/history", headers=headers))["items"]
    assert any(item["approval_request_id"] == approval["id"] for item in history)
    pending_publish = _assert_ok(client.get("/api/v1/approvals/pending-publish", headers=headers))
    assert any(item["approval_request_id"] == approval["id"] for item in pending_publish)
    listed_requests = _assert_ok(client.get("/api/v1/approval-requests", headers=headers))
    assert any(item["id"] == approval["id"] for item in listed_requests)
    fetched_request = _assert_ok(client.get(f"/api/v1/approval-requests/{approval['id']}", headers=headers))
    assert fetched_request["status"] == "approved"


def test_live_external_services_and_domain_adapters(live_client) -> None:
    _client, _headers, user_id, _role_id = live_client
    settings = get_settings()
    session_factory = get_session_factory()

    realm = settings.oidc_issuer_url.rstrip("/").split("/")[-1]
    keycloak = KeycloakAdminClient(
        base_url=settings.keycloak_admin_api_url,
        realm=realm,
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
        timeout_seconds=10,
    )
    snapshot = keycloak.snapshot(page_size=50)
    assert len(snapshot.users) >= 1
    normalized_users, normalized_groups = normalize_snapshot(snapshot)
    assert len(normalized_users) == len(snapshot.users)
    assert len(normalized_groups) == len(snapshot.groups)
    assert keycloak.break_glass_status(f"{TEST_PREFIX}-missing-user").detail_code == "user_missing"

    with session_factory() as session:
        run = IdentitySyncRun(source="keycloak", status="failed", trigger_type="manual", started_at=datetime.now(UTC), attempt=1)
        session.add(run)
        session.flush()
        reconciled = reconcile_snapshot(session, run, snapshot, acquire_lock=False)
        assert reconciled.status == "succeeded"
        assert reconciled.users_created + reconciled.users_updated >= 1
        session.rollback()

    with session_factory() as session:
        run = IdentitySyncRun(source="keycloak", status="running", trigger_type="deployment", started_at=datetime.now(UTC), attempt=1)
        session.add(run)
        session.flush()
        with pytest.raises(AppError) as ldap_break_glass:
            reconcile_snapshot(session, run, snapshot, ldap_group_path="/ldap", break_glass_username="peter", acquire_lock=False)
        assert ldap_break_glass.value.code == "break_glass_membership_unavailable"
        session.rollback()

    data = _seed_live_document_workspace(session_factory, user_id)
    project_id = UUID(data["project_id"])
    document_id = UUID(data["document_id"])
    version_id = UUID(data["version_id"])

    with session_factory() as session:
        project = session.get(Project, project_id)
        document = session.get(Document, document_id)
        version = session.get(DocumentVersion, version_id)
        assert project is not None and document is not None and version is not None
        chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id).order_by(Chunk.chunk_index)))
        profile = session.get(EmbeddingProfile, version.embedding_profile_id)
        assert chunks and profile is not None

        published_adapter = LiveOpenSearchPublishedAdapter(settings)
        vectors = [[0.1, 0.2, 0.3] for _chunk in chunks]
        published = published_adapter.write_published_chunks(project_id=project.id, document=document, version=version, chunks=chunks, vectors=vectors, profile=profile)
        assert len(published.document_ids) == len(chunks)
        version.extraction_artifact_uri = f"opensearch://{published.index_name}"
        published_adapter.delete_staging_documents(version=version)

        graph_result = LiveNeo4jGraphSyncAdapter(settings).sync_active_version(project_id=project.id, document=document, version=version, chunks=chunks)
        assert graph_result.node_count == 2 + len(chunks)
        assert graph_result.edge_count == 1 + len(chunks)
        session.rollback()

    storage = S3ObjectStorage(settings)
    storage.ensure_bucket(settings.s3_bucket)
    remote_dir = f"{TEST_PREFIX}/{uuid4().hex}"
    remote_name = "remote-live-sync.md"
    remote_body = b"# Remote live sync\n\nS3 backed data source content."
    storage.put_object(bucket=settings.s3_bucket, key=f"{remote_dir}/{remote_name}", body=remote_body, content_type="text/markdown")
    with session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None
        now = datetime.now(UTC)
        document = Document(
            project_id=project.id,
            document_code=f"DATA-{uuid4().hex[:8]}",
            title=f"{TEST_PREFIX} S3 data source",
            source_type="s3_service",
            status="inactive",
            is_deleted=False,
            created_by=UUID(user_id),
            lock_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(document)
        session.flush()
        connection = DataConnection(
            project_id=project.id,
            service_type="S3",
            name=f"{TEST_PREFIX}-s3-sync",
            connection_metadata={
                "bucket": settings.s3_bucket,
                "endpoint_url": settings.s3_endpoint_url,
                "region": settings.s3_region,
                "verify_tls": settings.s3_verify_tls,
            },
            source_identity={
                "document_id": str(document.id),
                "remote_path": remote_dir,
                "file_name": remote_name,
                "remote_uri": f"s3://{settings.s3_bucket}/{remote_dir}/{remote_name}",
            },
            schedule_mode="cron",
            cron_expression="*/5 * * * *",
            timezone="Asia/Taipei",
            enabled=True,
            next_run_at=now,
            created_by=UUID(user_id),
            created_at=now,
            updated_at=now,
        )
        session.add(connection)
        session.flush()
        connection.credential_encrypted = EnvelopeCipher(settings.encryption_key_bytes).encrypt(
            json.dumps(
                {
                    "access_key": settings.s3_access_key_id.get_secret_value(),
                    "secret_key": settings.s3_secret_access_key.get_secret_value(),
                }
            ),
            context=f"data-source-connection:{connection.id}",
        )
        storage.ensure_bucket(settings.s3_bucket)
        first_run = DataSyncRun(data_connection_id=connection.id, document_id=document.id, trigger_type="manual", status="queued", remote_metadata={}, retry_count=0, created_at=now)
        session.add(first_run)
        session.flush()
        completed = execute_data_source_sync(session=session, settings=settings, run_id=first_run.id)
        assert completed is not None and completed.status == "success"
        assert completed.document_version_id is not None
        session.flush()
        scan = session.scalar(select(FileScanRun).where(FileScanRun.document_version_id == completed.document_version_id))
        assert scan is None
        second_run = DataSyncRun(data_connection_id=connection.id, document_id=document.id, trigger_type="manual", status="queued", remote_metadata={}, retry_count=0, created_at=datetime.now(UTC))
        session.add(second_run)
        session.flush()
        unchanged = execute_data_source_sync(session=session, settings=settings, run_id=second_run.id)
        assert unchanged is not None and unchanged.status == "unchanged"
        connection.next_run_at = datetime(2026, 1, 1, tzinfo=UTC)
        session.flush()
        queued = queue_due_scheduled_data_syncs(session, now=datetime.now(UTC))
        assert any(item.data_connection_id == connection.id for item in queued)
        assert any(item.status == "queued" and item.trigger_type == "scheduled" for item in queued)
        session.rollback()

    assert compute_next_run_at("*/15 * * * *", "Asia/Taipei", after=datetime(2026, 7, 10, 1, 0, tzinfo=UTC)).tzinfo is not None
    with pytest.raises(AppError) as cron_error:
        compute_next_run_at("* * *", "Asia/Taipei")
    assert cron_error.value.code == "data_source_cron_invalid"
    with pytest.raises(AppError) as local_http_error:
        HTTPRemoteSourceClient().get_object(url="http://127.0.0.1:8000/", timeout_seconds=1, max_bytes=10)
    assert local_http_error.value.code == "http_source_ssrf_blocked"

    citation = ProjectChatCitation(
        document_id=uuid4(),
        document_version_id=uuid4(),
        chunk_id=uuid4(),
        title="Live citation",
        score=0.91,
        excerpt="Alpha controls GPU isolation.",
        content_type="text",
    )
    empty_answer = ai_provider.generate_rag_answer(question="What is missing?", citations=[], model=None, settings=settings)
    assert empty_answer.answer
    with pytest.raises(AppError) as missing_model:
        ai_provider.generate_rag_answer(question="What?", citations=[citation], model=None, settings=settings)
    assert missing_model.value.code == "model_configuration_required"
    with pytest.raises(AppError) as empty_tag:
        ai_provider.generate_knowledge_tags(text="   ", model=AIModel(id=uuid4(), name="empty", model_type="Chat", provider="custom", is_active=True), settings=settings)
    assert empty_tag.value.code == "tagging_text_required"
    assert ai_provider._parse_tag_result('prefix ["GPU", "API", "GPU"] suffix') == ["GPU", "API"]
    assert ai_provider._parse_tag_result("[]", allow_empty=True) == []
    with pytest.raises(AppError) as invalid_tag_payload:
        ai_provider._parse_tag_result("no json")
    assert invalid_tag_payload.value.code == "tagging_response_invalid"

    provider_cases = [
        ("custom", "http://127.0.0.1:65535/v1", {"model_name": "codex-chat", "timeout_seconds": 1}),
        ("openai", "http://127.0.0.1:65535/v1/responses", {"model_name": "codex-responses", "api_mode": "responses", "timeout_seconds": 1}),
        ("ollama", "http://127.0.0.1:65535", {"model_name": "codex-ollama", "timeout_seconds": 1}),
        ("gemini", "http://127.0.0.1:65535/v1beta", {"model_name": "codex-gemini", "timeout_seconds": 1}),
        ("claude", "http://127.0.0.1:65535/v1", {"model_name": "codex-claude", "timeout_seconds": 1}),
    ]
    for provider, endpoint, config in provider_cases:
        model = AIModel(id=uuid4(), name=f"{TEST_PREFIX}-{provider}", model_type="Chat", provider=provider, endpoint=endpoint, is_active=True, config=config, config_version=1)
        with pytest.raises(AppError) as provider_error:
            ai_provider.generate_rag_answer(question="What does Alpha cover?", citations=[citation], model=model, settings=settings)
        assert provider_error.value.code == "model_provider_unavailable"

    unsupported = AIModel(id=uuid4(), name=f"{TEST_PREFIX}-unsupported", model_type="Chat", provider="unsupported", endpoint="http://127.0.0.1:65535", is_active=True, config={"model_name": "unsupported"}, config_version=1)
    with pytest.raises(AppError) as unsupported_error:
        ai_provider.evaluate_rag_answer(question="Q", answer="A", expected_answer=None, expected_keywords=[], citations=[citation], model=unsupported, settings=settings)
    assert unsupported_error.value.code == "model_provider_unsupported"
    assert ai_provider._openai_answer({"choices": [{"message": {"content": " OpenAI answer "}}]}) == "OpenAI answer"
    assert ai_provider._openai_responses_answer({"output": [{"content": [{"type": "output_text", "text": "Responses answer"}]}]}) == "Responses answer"
    assert ai_provider._ollama_answer({"message": {"content": "Ollama answer"}}) == "Ollama answer"
    assert ai_provider._gemini_answer({"candidates": [{"content": {"parts": [{"text": "Gemini answer"}]}}]}) == "Gemini answer"
    assert ai_provider._claude_answer({"content": [{"type": "text", "text": "Claude answer"}]}) == "Claude answer"
    judge = ai_provider._judge_result('{"score": 1.5, "reason": "grounded"}', {"total_tokens": 3}, ai_provider.backend_default_prompt("Judge"))
    assert judge.score == 1.0 and judge.reason == "grounded"
    with pytest.raises(AppError) as invalid_judge:
        ai_provider._judge_result("not json", None, ai_provider.backend_default_prompt("Judge"))
    assert invalid_judge.value.code == "judge_response_invalid"


def test_live_integration_adapter_embedding_and_switch_edges(live_client) -> None:
    _client, _headers, user_id, _role_id = live_client
    settings = get_settings()
    session_factory = get_session_factory()

    realm = settings.oidc_issuer_url.rstrip("/").split("/")[-1]
    keycloak = KeycloakAdminClient(
        base_url=settings.keycloak_admin_api_url,
        realm=realm,
        client_id=settings.keycloak_sync_client_id,
        client_secret=settings.keycloak_sync_client_secret.get_secret_value(),
        timeout_seconds=10,
    )
    assert isinstance(keycloak.list_users(), list)
    assert isinstance(keycloak.list_groups(), list)
    with pytest.raises(AppError) as missing_break_glass_secret:
        keycloak.ensure_break_glass_user(username=f"{TEST_PREFIX}-missing-break-glass")
    assert missing_break_glass_secret.value.code == "break_glass_initial_credential_required"
    assert keycloak._find_group([{"name": "System Admin", "path": "/system-admin"}], "/system-admin") is not None
    assert keycloak._find_group([{"name": "System Admin"}], "unknown") is None
    assert not hasattr(keycloak, "_mfa_evidence")

    with pytest.raises(AppError) as invalid_http_url:
        _guard_http_url("ftp://example.test/file.md")
    assert invalid_http_url.value.code == "http_source_url_invalid"
    assert _host_is_blocked("127.0.0.1") is True
    assert _host_is_blocked("8.8.8.8") is False
    for client in (FTPRemoteSourceClient(), FTPSRemoteSourceClient()):
        with pytest.raises(AppError) as remote_error:
            client.get_object(host="127.0.0.1", port=1, username="user", credential="password", remote_path="/", file_name="missing.md", timeout_seconds=1)
        assert remote_error.value.code == "connection_failed"
    with pytest.raises(AppError) as sftp_error:
        SFTPRemoteSourceClient().get_object(host="127.0.0.1", port=1, username="user", credential="password", remote_path="/", file_name="missing.md", timeout_seconds=1)
    assert sftp_error.value.code in {"connection_failed", "sftp_client_unavailable", "sftp_known_hosts_unavailable"}

    encrypted_model_id = uuid4()
    encrypted_key = EnvelopeCipher(settings.encryption_key_bytes).encrypt("live-embedding-key", context=f"ai-model:{encrypted_model_id}")
    encrypted_model = AIModel(id=encrypted_model_id, name=f"{TEST_PREFIX}-encrypted-embedding", model_type="Embedding", provider="custom", endpoint="http://127.0.0.1:65535/v1", is_active=True, api_key_encrypted=encrypted_key, config={"model_name": "encrypted-embedding"})
    assert embeddings._embedding_auth_headers(encrypted_model, settings)["Authorization"] == "Bearer live-embedding-key"
    bad_encrypted_model = AIModel(id=uuid4(), name=f"{TEST_PREFIX}-bad-encrypted-embedding", model_type="Embedding", provider="custom", endpoint="http://127.0.0.1:65535/v1", is_active=True, api_key_encrypted=encrypted_key, config={"model_name": "encrypted-embedding"})
    with pytest.raises(AppError) as encrypted_error:
        embeddings._embedding_auth_headers(bad_encrypted_model, settings)
    assert encrypted_error.value.code == "invalid_encrypted_value"
    secret_ref_model = AIModel(id=uuid4(), name=f"{TEST_PREFIX}-secret-ref-embedding", model_type="Embedding", provider="custom", endpoint="http://127.0.0.1:65535/v1", is_active=True, api_key_secret_ref="secret/embedding", config={"model_name": "secret-ref"})
    with pytest.raises(AppError) as secret_ref_error:
        embeddings._embedding_auth_headers(secret_ref_model, settings)
    assert secret_ref_error.value.code == "embedding_adapter_secret_ref_unresolved"
    assert embeddings.openai_embeddings_url("http://host/v1/chat/completions") == "http://host/v1/embeddings"
    assert embeddings._timeout({"timeout_seconds": "9999"}, default=60) == 300
    assert embeddings._verify_tls({"verify_tls": "no"}) is False
    assert embeddings._int("bad", default=7) == 7

    data = _seed_live_document_workspace(session_factory, user_id)
    with session_factory() as session:
        project = session.get(Project, UUID(data["project_id"]))
        document = session.get(Document, UUID(data["document_id"]))
        version = session.get(DocumentVersion, UUID(data["version_id"]))
        assert project is not None and document is not None and version is not None
        chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id).order_by(Chunk.chunk_index)))
        assert chunks
        with pytest.raises(AppError) as no_chunks:
            embeddings.embed_chunks(session, project=project, version=version, chunks=[], settings=settings)
        assert no_chunks.value.code == "embedding_chunks_required"
        original_text = chunks[0].content
        chunks[0].content = "   "
        chunks[0].markdown_content = "   "
        with pytest.raises(AppError) as blank_chunk:
            embeddings.embed_chunks(session, project=project, version=version, chunks=[chunks[0]], settings=settings)
        assert blank_chunk.value.code == "embedding_text_required"
        chunks[0].content = original_text
        chunks[0].markdown_content = original_text
        with pytest.raises(AppError) as blank_query:
            embeddings.embed_query(session, profile=session.get(EmbeddingProfile, version.embedding_profile_id), question="  ", settings=settings)
        assert blank_query.value.code == "query_text_required"
        model = session.get(AIModel, version.embedding_model_id)
        assert model is not None
        assert embeddings._profile_for_vectors(session, model, version, [[0.1, 0.2], [0.3, 0.4]]).vector_dimension == 2
        with pytest.raises(AppError) as invalid_dimension:
            embeddings._profile_for_vectors(session, model, version, [[0.1], [0.2, 0.3]])
        assert invalid_dimension.value.code == "embedding_dimension_invalid"

        now = datetime.now(UTC)
        switch_version = DocumentVersion(
            project_id=project.id,
            document_id=document.id,
            version_major=2,
            extraction_revision=0,
            version_label="v2.0",
            status="inactive",
            original_file_name="switch-version.md",
            canonical_extension=".md",
            mime_type="text/markdown",
            file_size=42,
            content_sha256=_sha256("Switch active version chunk"),
            chunk_strategy={"source_text": "Switch active version chunk"},
            embedding_model_id=version.embedding_model_id,
            embedding_profile_id=version.embedding_profile_id,
            llm_model_id=version.llm_model_id,
            lock_version=1,
            published_at=now,
            published_by=UUID(user_id),
            created_at=now,
            updated_at=now,
        )
        session.add(switch_version)
        session.flush()
        switch_chunk = Chunk(
            project_id=project.id,
            document_id=document.id,
            document_version_id=switch_version.id,
            chunk_index=1,
            title="Switch active version",
            content="Switch active version chunk",
            markdown_content="Switch active version chunk",
            content_type="text",
            content_hash=_sha256("Switch active version chunk"),
            start_offset=0,
            end_offset=27,
            source_mapping=[{"source_anchor": "switch"}],
            chunk_strategy={"source": "rule"},
            embedding_model_id=version.embedding_model_id,
            token_count=4,
            confidence_score=0.9,
            status="active",
            is_manual_edited=False,
            created_at=now,
            updated_at=now,
        )
        session.add(switch_chunk)
        session.flush()
        build = EmbeddingBuild(project_id=project.id, document_id=document.id, document_version_id=switch_version.id, embedding_profile_id=switch_version.embedding_profile_id, build_revision=1, status="published", chunk_count=1, index_name="live-switch-index", checksum=_sha256("switch"))
        session.add(build)
        session.flush()
        with pytest.raises(AppError) as switch_reason:
            review_publish.switch_active_version(session=session, actor_user_id=UUID(user_id), document=document, version=switch_version, lock_version=switch_version.lock_version, impact_confirmed=True, audit_reason=" ", request_id=f"{TEST_PREFIX}-blank-switch")
        assert switch_reason.value.code == "switch_reason_required"
        manifest, graph_job = review_publish.switch_active_version(session=session, actor_user_id=UUID(user_id), document=document, version=switch_version, lock_version=switch_version.lock_version, impact_confirmed=True, audit_reason="live switch coverage", request_id=f"{TEST_PREFIX}-switch-success")
        assert manifest.document_version_id == switch_version.id
        assert graph_job.status == "queued"
        assert session.scalar(select(OutboxEvent.id).where(OutboxEvent.aggregate_id == graph_job.id)) is not None
        session.rollback()

    with session_factory() as session:
        existing_identity_runs = set(session.scalars(select(IdentitySyncRun.id).where(IdentitySyncRun.status.in_(("queued", "running")))))
    try:
        worker.queue_scheduled_identity_sync()
        worker.queue_scheduled_data_source_sync()
        with session_factory.begin() as session:
            event = OutboxEvent(topic="validation.run.requested", aggregate_type="validation_run", aggregate_id=uuid4(), payload={"run_id": str(uuid4())}, status="pending", attempts=0, available_at=datetime.now(UTC), created_at=datetime.now(UTC))
            session.add(event)
        worker.dispatch_outbox()
    finally:
        with session_factory.begin() as session:
            created_runs = list(session.scalars(select(IdentitySyncRun).where(IdentitySyncRun.status.in_(("queued", "running")), IdentitySyncRun.id.not_in(existing_identity_runs))))
            for run in created_runs:
                run.status = "failed"
                run.completed_at = datetime.now(UTC)
                run.error_code = "test_cleanup"
                run.error_message = "Live test cleanup"


def test_live_extraction_validation_and_review_domain_behaviors(live_client) -> None:
    _client, _headers, user_id, _role_id = live_client
    settings = get_settings()
    session_factory = get_session_factory()
    data = _seed_live_document_workspace(session_factory, user_id)
    project_id = UUID(data["project_id"])
    document_id = UUID(data["document_id"])
    version_id = UUID(data["version_id"])

    with session_factory() as session:
        project = session.get(Project, project_id)
        document = session.get(Document, document_id)
        version = session.get(DocumentVersion, version_id)
        pipeline = extraction_pipeline.latest_pipeline_for_version(session, version_id)
        assert project is not None and document is not None and version is not None and pipeline is not None
        extraction_pipeline.ensure_no_active_pipeline(session, version.id)

        running_pipeline = PipelineRun(project_id=project.id, document_id=document.id, document_version_id=version.id, run_type="document_extraction", status="running", progress_percent=10, current_step_name="parse_document", triggered_by=UUID(user_id), started_at=datetime.now(UTC), created_at=datetime.now(UTC))
        session.add(running_pipeline)
        session.flush()
        with pytest.raises(AppError) as active_pipeline:
            extraction_pipeline.ensure_no_active_pipeline(session, version.id)
        assert active_pipeline.value.code == "pipeline_already_running"

        step_pipeline = PipelineRun(project_id=project.id, document_id=document.id, document_version_id=version.id, run_type="document_extraction", status="running", progress_percent=5, current_step_name="upload_received", triggered_by=UUID(user_id), started_at=datetime.now(UTC), created_at=datetime.now(UTC))
        session.add(step_pipeline)
        session.flush()
        extraction_pipeline.initialize_pipeline_steps(session, step_pipeline, ocr_model_id=version.ocr_model_id, ocr_name="Live OCR", force_ocr=False)
        session.flush()
        steps = extraction_pipeline._steps_for_run(session, step_pipeline.id)
        assert set(extraction_pipeline.AUTO_EXTRACTION_STEPS).issubset(steps)
        extraction_pipeline._reset_from_step(session, version.id, steps, "chunk_knowledge")
        assert steps["chunk_knowledge"].status == "pending"

        assert extraction_pipeline._parse_text(settings, version).startswith("Alpha architecture")
        assert extraction_pipeline._has_reliable_text_layer(version) is True
        paragraphs = extraction_pipeline._split_paragraphs("# Heading\n\n- one\n- two\n\n|A|B|\n|-|-|\n|1|2|\n\n" + ("long text. " * 120))
        layout = extraction_pipeline._document_layout_artifact(paragraphs)
        assert layout["status"] == "available"
        assert extraction_pipeline._estimated_layout_block_height({"type": "table", "rows": [["A", "B"], ["1", "2"]]}) > 0
        created_chunks = extraction_pipeline._create_chunks(session, project, document, version, ["First live chunk", "Second live chunk"])
        assert len(created_chunks) == 2
        tag_result = ai_provider.AIProviderResult(answer='["治理", "GPU"]', prompt_version="pytest")
        assert extraction_pipeline._result_tags(tag_result) == ["治理", "GPU"]
        metadata = extraction_pipeline._tag_metadata(tag_result, model=session.get(AIModel, project.llm_model_id), pipeline=pipeline, scope="chunk", chunk_id=created_chunks[0].id)
        extraction_pipeline._attach_chunk_tag(session, project.id, created_chunks[0].id, "治理", source="llm", actor_user_id=UUID(user_id), metadata=metadata)
        extraction_pipeline._attach_document_tag(session, project.id, version.id, "文件治理", source="llm", actor_user_id=UUID(user_id), metadata=metadata)
        preview = extraction_pipeline._graph_preview_artifact(session, project, document, version, created_chunks)
        assert preview["node_count"] >= 4

        live_ocr = extraction_pipeline.LiveOnlyOCRAdapter().extract_text(model=None, version=version, parsed_text="Reliable parsed text", force_ocr=False, reliable_text_layer=True)
        assert live_ocr.skipped is True
        with pytest.raises(AppError) as missing_ocr:
            extraction_pipeline.LiveOnlyOCRAdapter().extract_text(model=None, version=version, parsed_text="", force_ocr=True, reliable_text_layer=False)
        assert missing_ocr.value.code == "ocr_adapter_not_configured"
        unsupported_ocr_model = AIModel(id=uuid4(), name=f"{TEST_PREFIX}-unsupported-ocr", model_type="OCR", provider="unsupported", endpoint="http://127.0.0.1:65535/ocr", is_active=True, config={"model_name": "ocr"}, config_version=1)
        with pytest.raises(AppError) as unsupported_ocr:
            extraction_pipeline.UnsupportedOCRAdapter().extract_text(model=unsupported_ocr_model, version=version, parsed_text="", force_ocr=True, reliable_text_layer=False)
        assert unsupported_ocr.value.code == "ocr_provider_unsupported"
        generic_ocr_model = AIModel(id=uuid4(), name=f"{TEST_PREFIX}-generic-ocr", model_type="OCR", provider="generic_http", endpoint="http://127.0.0.1:65535/ocr", is_active=True, config={"model_name": "ocr", "timeout_seconds": 1, "retry_count": 0}, config_version=1)
        with pytest.raises(AppError) as generic_ocr_error:
            extraction_pipeline.GenericHTTPOCRAdapter().extract_text(model=generic_ocr_model, version=version, parsed_text="", force_ocr=True, reliable_text_layer=False)
        assert generic_ocr_error.value.code == "ocr_adapter_unavailable"
        openai_ocr_model = AIModel(id=uuid4(), name=f"{TEST_PREFIX}-openai-ocr", model_type="OCR", provider="openai", endpoint="http://127.0.0.1:65535/v1", is_active=True, config={"model_name": "ocr", "timeout_seconds": 1}, config_version=1)
        openai_skip = extraction_pipeline.OpenAIOCRAdapter(settings).extract_text(model=openai_ocr_model, version=version, parsed_text="Readable layer", force_ocr=False, reliable_text_layer=True)
        assert openai_skip.adapter_source == "reliable-text-layer"
        assert extraction_pipeline._openai_ocr_markdown({"output": [{"content": [{"text": "Markdown text"}]}]}) == "Markdown text"
        assert extraction_pipeline._valid_markdown_ocr_text("# Markdown") is True
        assert extraction_pipeline._valid_markdown_ocr_text('{"not":"markdown"}') is False
        assert extraction_pipeline._openai_responses_url("http://127.0.0.1:65535/v1") == "http://127.0.0.1:65535/v1/responses"
        assert extraction_pipeline._mime_type_for(version) == "application/octet-stream"

        profile = session.get(EmbeddingProfile, version.embedding_profile_id)
        assert profile is not None
        with pytest.raises(AppError) as query_embedding:
            embeddings.embed_query(session, profile=profile, question="What is Alpha?", settings=settings)
        assert query_embedding.value.code == "embedding_adapter_credential_required"
        assert embeddings.openai_embeddings_url("http://host/v1/responses") == "http://host/v1/embeddings"
        assert embeddings._openai_embedding_vectors({"data": [{"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]}) == [[0.1], [0.2]]
        with pytest.raises(AppError) as invalid_vectors:
            embeddings._openai_embedding_vectors({"data": [{"index": 0, "embedding": ["bad"]}]})
        assert invalid_vectors.value.code == "embedding_response_invalid"
        session.rollback()

    with session_factory() as session:
        validation_run_id = uuid4()
        project = session.get(Project, project_id)
        assert project is not None
        selected_ids = {version_id}
        max_attempts = 3
        execution_manifest = serving_routes._validation_execution_manifest(
            session,
            project=project,
            scope_mode="published",
            selected_ids=selected_ids,
            max_attempts=max_attempts,
        )
        run = ValidationRun(
            id=validation_run_id,
            project_id=project_id,
            project_generation=project.work_generation,
            uploaded_file_name="live-validation.csv",
            status="queued",
            run_scope="project_chat",
            selected_document_ids=[str(version_id)],
            execution_manifest=execution_manifest,
            execution_manifest_hash=serving_routes._canonical_json_hash(execution_manifest),
            max_attempts=max_attempts,
            total_count=1,
            completed_count=0,
            failed_count=0,
            created_by=UUID(user_id),
            created_at=datetime.now(UTC),
        )
        input_payload = {
            "question": "What does Alpha cover?",
            "expected_answer": "GPU isolation",
            "expected_keywords": ["GPU"],
            "selected_document_ids": [str(version_id)],
            "category": "coverage",
            "priority": "medium",
        }
        item = ValidationRunItem(
            run_id=run.id,
            input_item_id=uuid4(),
            input_ordinal=1,
            input_content_hash=serving_routes._canonical_json_hash(input_payload),
            question=input_payload["question"],
            expected_answer=input_payload["expected_answer"],
            expected_keywords=input_payload["expected_keywords"],
            selected_document_ids=input_payload["selected_document_ids"],
            category=input_payload["category"],
            priority=input_payload["priority"],
            reference_docs=[],
            status="pending",
            created_at=datetime.now(UTC),
        )
        session.add_all([run, item])
        session.commit()
        executed = validation_runner.execute_validation_run(session, run.id, max_items=1)
        assert executed.status in {"completed", "failed", "partial_failed"}
        stored_item = session.get(ValidationRunItem, item.id)
        assert stored_item is not None and stored_item.status in {"passed", "failed", "needs_review", "error"}

    data_for_reject = _seed_live_document_workspace(session_factory, user_id)
    with session_factory() as session:
        version = session.get(DocumentVersion, UUID(data_for_reject["review_version_id"]))
        assert version is not None
        request = review_publish.submit_review(session=session, actor_user_id=UUID(user_id), version=version, owner_user_id=UUID(user_id), request_id=f"{TEST_PREFIX}-reject", **_review_evidence(version.id))
        task = session.get(ApprovalTask, request.current_task_id)
        assert task is not None
        with pytest.raises(AppError) as blank_reject:
            review_publish.reject_task(session=session, actor_user_id=UUID(user_id), task=task, lock_version=task.lock_version, comment=" ", request_id=f"{TEST_PREFIX}-blank-reject")
        assert blank_reject.value.code == "rejection_reason_required"
        rejected = review_publish.reject_task(session=session, actor_user_id=UUID(user_id), task=task, lock_version=task.lock_version, comment="Needs revision", request_id=f"{TEST_PREFIX}-reject")
        assert rejected.status == "rejected"
        assert version.status == "review_rejected"
        with pytest.raises(AppError) as unpublished_switch:
            review_publish.switch_active_version(session=session, actor_user_id=UUID(user_id), document=session.get(Document, version.document_id), version=version, lock_version=version.lock_version, impact_confirmed=False, audit_reason="", request_id=f"{TEST_PREFIX}-switch")
        assert unpublished_switch.value.code == "impact_confirmation_required"
        session.rollback()


def _valid_identity_candidate() -> IdentitySettingsCandidate:
    issuer = os.environ["OIDC_ISSUER_URL"].rstrip("/")
    return IdentitySettingsCandidate(
        issuer_url=issuer,
        realm=issuer.rsplit("/", 1)[-1],
        client_id="nomosmart-frontend",
        audience=os.environ["OIDC_AUDIENCE"],
        discovery_url=f"{issuer}/.well-known/openid-configuration",
        jwks_url=f"{issuer}/protocol/openid-connect/certs",
        sync_schedule="0 2 * * *",
        timezone="Asia/Taipei",
    )


def test_live_configuration_identity_worker_and_sync_edges(live_client) -> None:
    client, headers, user_id, role_id = live_client
    settings = get_settings()
    session_factory = get_session_factory()

    current_identity = _assert_ok(client.get("/api/v1/system/identity-settings", headers=headers))
    assert "editable" in current_identity
    reauth = client.post("/api/v1/system/identity-settings/reauth/start", headers=headers)
    assert reauth.status_code == 401
    assert reauth.json()["code"] == "reauth_session_required"
    assert client.post("/api/v1/system/identity-settings/reauth/complete", headers=headers).status_code in {401, 403}
    assert _assert_ok(client.post("/api/v1/system/identity-settings/lock", headers=headers))["status"] == "validated_active_locked"
    identity_validation = _assert_ok(client.post("/api/v1/system/identity-settings/validate", headers=headers, json=_valid_identity_candidate().model_dump(mode="json")))
    assert identity_validation["valid"] is True
    assert client.put("/api/v1/system/identity-settings", headers=headers, json=_valid_identity_candidate().model_dump(mode="json")).status_code == 423

    sync_runs = _assert_ok(client.get("/api/v1/identity-sync/runs", headers=headers))
    assert isinstance(sync_runs, list)
    queued = client.post("/api/v1/identity-sync/run", headers=headers)
    assert queued.status_code in {202, 409, 503}
    if queued.status_code == 202:
        run_id = queued.json()["id"]
        assert _assert_ok(client.get(f"/api/v1/identity-sync/runs/{run_id}", headers=headers))["id"] == run_id
        with session_factory.begin() as session:
            run = session.get(IdentitySyncRun, UUID(run_id))
            assert run is not None
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.error_code = "test_cleanup"
            run.error_message = "Live test cleanup"
    elif queued.status_code == 503:
        assert queued.json()["code"] == "identity_sync_worker_unavailable"
    assert client.get(f"/api/v1/identity-sync/runs/{uuid4()}", headers=headers).status_code == 404
    assert isinstance(_assert_ok(client.get("/api/v1/external-groups", headers=headers)), list)
    assert client.put("/api/v1/external-group-role-mappings", headers=headers, json={"mappings": []}).status_code == 405

    now = datetime.now(UTC)
    with session_factory() as session:
        active_setting = IdentitySetting(revision=9999, state="validated_active_locked", configuration={"issuer_url": "http://127.0.0.1"}, secret_configured=False, is_current=False, is_last_known_good=True, validated_at=now, created_by=UUID(user_id))
        grant = IdentityUnlockGrant(user_id=UUID(user_id), session_id="session", scope="identity-settings", auth_time=now, expires_at=now + timedelta(minutes=10), created_at=now)
        session.add_all([active_setting, grant])
        session.flush()
        assert session.get(IdentitySetting, active_setting.id) is not None
        session.rollback()

    with pytest.raises(AppError) as bad_identity:
        identity_settings.validate_identity_candidate(IdentitySettingsCandidate(issuer_url="ftp://bad", realm="r", client_id="c", audience="a", discovery_url="bad", jwks_url="bad", sync_schedule="bad", timezone="No/SuchZone"), allow_http=False)
    assert bad_identity.value.code == "invalid_identity_settings"
    identity_settings.require_fresh_auth(int(datetime.now(UTC).timestamp()), "session")
    with pytest.raises(AppError) as stale_auth:
        identity_settings.require_fresh_auth(int((datetime.now(UTC) - timedelta(minutes=10)).timestamp()), "session")
    assert stale_auth.value.code == "fresh_authentication_required"

    assert data_sync.compute_next_run_at("*/5 * * * *", "Asia/Taipei", after=datetime(2026, 7, 10, 0, 0, tzinfo=UTC)) > datetime(2026, 7, 10, 0, 0, tzinfo=UTC)
    for expression, timezone in (("bad", "Asia/Taipei"), ("* * * * *", "No/SuchZone"), ("61 * * * *", "Asia/Taipei"), ("*/0 * * * *", "Asia/Taipei"), ("10-1 * * * *", "Asia/Taipei")):
        with pytest.raises(AppError):
            data_sync.compute_next_run_at(expression, timezone, after=datetime(2026, 7, 10, 0, 0, tzinfo=UTC))

    data = _seed_live_document_workspace(session_factory, user_id)
    with session_factory() as session:
        project_id = UUID(data["project_id"])
        document_id = UUID(data["document_id"])
        bad_connection = DataConnection(project_id=project_id, service_type="HTTP_API", name=f"{TEST_PREFIX}-bad-schedule", connection_metadata={}, source_identity={"document_id": str(document_id), "url": "http://127.0.0.1:65535/file.md", "file_name": "file.md"}, schedule_mode="cron", cron_expression="* * * * *", timezone="No/SuchZone", enabled=True, last_sync_status=None, next_run_at=datetime.now(UTC) - timedelta(minutes=1), created_by=UUID(user_id))
        future_connection = DataConnection(project_id=project_id, service_type="HTTP_API", name=f"{TEST_PREFIX}-future-schedule", connection_metadata={}, source_identity={"document_id": str(document_id), "url": "http://127.0.0.1:65535/file.md", "file_name": "file.md"}, schedule_mode="cron", cron_expression="0 0 1 1 *", timezone="Asia/Taipei", enabled=True, next_run_at=datetime(2099, 1, 1, tzinfo=UTC), created_by=UUID(user_id))
        session.add_all([bad_connection, future_connection])
        session.flush()
        queued_data_runs = data_sync.queue_due_scheduled_data_syncs(session, now=datetime.now(UTC))
        assert all(run.data_connection_id != bad_connection.id for run in queued_data_runs)
        assert all(run.data_connection_id != future_connection.id for run in queued_data_runs)
        assert bad_connection.last_sync_status == "failed"
        assert future_connection.next_run_at.year == 2099
        assert data_sync.execute_data_source_sync(session=session, settings=settings, run_id=uuid4()) is None
        assert data_sync._safe_header_name("X-Test_1") is True
        assert data_sync._safe_header_name("Bad Header") is False
        assert data_sync._remote_object_key(future_connection) == "http://127.0.0.1:65535/file.md"
        assert data_sync._remote_file_name(future_connection) == "file.md"
        bearer_connection = DataConnection(project_id=project_id, service_type="HTTP_API", name=f"{TEST_PREFIX}-bearer", connection_metadata={"auth_mode": "bearer"}, credential_secret_ref="secret/backend/data-source", source_identity={"url": "http://127.0.0.1:65535/file.md", "file_name": "file.md"}, schedule_mode="once", timezone="Asia/Taipei", enabled=True, created_by=UUID(user_id))
        with pytest.raises(AppError) as credential_error:
            data_sync._http_headers(settings, bearer_connection)
        assert credential_error.value.code == "credential_secret_ref_unavailable"
        invalid_header_connection = DataConnection(project_id=project_id, service_type="HTTP_API", name=f"{TEST_PREFIX}-header", connection_metadata={"auth_mode": "api_key_header", "api_key_header_name": "Bad Header!"}, source_identity={"url": "http://127.0.0.1:65535/file.md", "file_name": "file.md"}, schedule_mode="once", timezone="Asia/Taipei", enabled=True, created_by=UUID(user_id))
        with pytest.raises(AppError) as header_error:
            data_sync._http_headers(settings, invalid_header_connection)
        assert header_error.value.code == "http_source_header_invalid"
        session.rollback()

    worker.run_identity_sync(str(uuid4()))
    worker.run_data_source_sync(str(uuid4()))
    with pytest.raises(AppError):
        worker.run_project_chat_validation(str(uuid4()))


def test_live_pipeline_execution_and_publish_edge_behaviors(live_client) -> None:
    _client, _headers, user_id, _role_id = live_client
    settings = get_settings()
    session_factory = get_session_factory()
    data = _seed_live_document_workspace(session_factory, user_id)

    with session_factory() as session:
        project = session.get(Project, UUID(data["project_id"]))
        document = session.get(Document, UUID(data["document_id"]))
        version = session.get(DocumentVersion, UUID(data["version_id"]))
        assert project is not None and document is not None and version is not None
        version.status = "processing"
        version.chunk_strategy = {
            **(version.chunk_strategy or {}),
            "source_text": "# Live pipeline\n\nAlpha covers GPU isolation.\n\nBeta covers review governance.",
            "text_layer_status": "reliable",
        }
        session.add(FileScanRun(document_version_id=version.id, scanner_type="disabled", status="accepted", safe_result_code="scanner_disabled", started_at=datetime.now(UTC), completed_at=datetime.now(UTC), created_at=datetime.now(UTC)))
        pipeline = PipelineRun(project_id=project.id, document_id=document.id, document_version_id=version.id, run_type="document_extraction", status="running", progress_percent=0, current_step_name="upload_received", triggered_by=UUID(user_id), started_at=datetime.now(UTC), created_at=datetime.now(UTC))
        session.add(pipeline)
        session.flush()
        extraction_pipeline.initialize_pipeline_steps(session, pipeline, ocr_model_id=version.ocr_model_id, ocr_name="Live OCR", force_ocr=False)
        session.flush()
        result = extraction_pipeline.execute_auto_extraction(session=session, settings=settings, project=project, document=document, version=version, pipeline=pipeline)
        assert result.status == "failed"
        failed_step = session.scalar(select(PipelineRunStep).where(PipelineRunStep.run_id == pipeline.id, PipelineRunStep.step_name == result.current_step_name))
        assert failed_step is not None
        assert failed_step.error_message == result.error_message
        with pytest.raises(AppError) as not_failed_retry:
            extraction_pipeline.retry_failed_step(session=session, settings=settings, project=project, document=document, version=version, pipeline=pipeline, step_name="upload_received")
        assert not_failed_retry.value.code == "pipeline_step_not_failed"
        failed_step.retry_count = extraction_pipeline.MAX_STEP_RETRIES
        with pytest.raises(AppError) as retry_limit:
            extraction_pipeline.retry_failed_step(session=session, settings=settings, project=project, document=document, version=version, pipeline=pipeline, step_name=failed_step.step_name)
        assert retry_limit.value.code == "pipeline_retry_limit_exceeded"
        with pytest.raises(AppError) as bad_reset:
            extraction_pipeline._reset_from_step(session, version.id, extraction_pipeline._steps_for_run(session, pipeline.id), "manager_review")
        assert bad_reset.value.code == "pipeline_step_not_retryable"
        assert extraction_pipeline._step_message("ocr_extract", "OpenAI OCR", True).endswith("force OCR enabled")
        assert extraction_pipeline._safe_error(TimeoutError("slow")) == "Adapter endpoint is unavailable"
        assert extraction_pipeline._timeout({"timeout_seconds": "9999"}, default=60) == 300
        assert extraction_pipeline._verify_tls({"verify_tls": "off"}) is False
        session.rollback()

    data_for_publish = _seed_live_document_workspace(session_factory, user_id)
    with session_factory() as session:
        document = session.get(Document, UUID(data_for_publish["document_id"]))
        version = session.get(DocumentVersion, UUID(data_for_publish["version_id"]))
        assert document is not None and version is not None
        with pytest.raises(AppError) as stale_publish:
            review_publish.publish_version(session=session, actor_user_id=UUID(user_id), document=document, version=version, lock_version=version.lock_version + 1, request_id=f"{TEST_PREFIX}-publish-stale", search_adapter=LiveOpenSearchPublishedAdapter(settings), graph_adapter=LiveNeo4jGraphSyncAdapter(settings))
        assert stale_publish.value.code == "stale_document_version"
        version.status = "draft"
        with pytest.raises(AppError) as not_publishable:
            review_publish.publish_version(session=session, actor_user_id=UUID(user_id), document=document, version=version, lock_version=version.lock_version, request_id=f"{TEST_PREFIX}-publish-draft", search_adapter=LiveOpenSearchPublishedAdapter(settings), graph_adapter=LiveNeo4jGraphSyncAdapter(settings))
        assert not_publishable.value.code == "version_not_publishable"
        version.status = "approved"
        version.embedding_profile_id = None
        with pytest.raises(AppError) as missing_profile:
            review_publish.publish_version(session=session, actor_user_id=UUID(user_id), document=document, version=version, lock_version=version.lock_version, request_id=f"{TEST_PREFIX}-publish-profile", search_adapter=LiveOpenSearchPublishedAdapter(settings), graph_adapter=LiveNeo4jGraphSyncAdapter(settings))
        assert missing_profile.value.code == "embedding_profile_required"
        profile = session.scalar(select(EmbeddingProfile).where(EmbeddingProfile.model_id == version.embedding_model_id).limit(1))
        assert profile is not None
        version.embedding_profile_id = profile.id
        with pytest.raises(AppError) as live_publish_error:
            review_publish.publish_version(session=session, actor_user_id=UUID(user_id), document=document, version=version, lock_version=version.lock_version, request_id=f"{TEST_PREFIX}-publish-live", search_adapter=LiveOpenSearchPublishedAdapter(settings), graph_adapter=LiveNeo4jGraphSyncAdapter(settings))
        assert live_publish_error.value.code in {"canonical_embedding_build_required", "embedding_adapter_credential_required", "embedding_adapter_unavailable", "embedding_profile_mismatch"}
        assert review_publish.published_index_name(settings.opensearch_index_prefix, profile.id).startswith(settings.opensearch_index_prefix)
        assert review_publish.chunk_checksum(list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id)))) != ""
        with pytest.raises(AppError) as missing_project:
            review_publish._project(session, uuid4())
        assert missing_project.value.code == "project_not_found"
        session.rollback()


def test_live_route_helpers_cover_validation_edges() -> None:
    assert model_routes._normalize_provider(" vllm-openai ") == "vLLM"
    with pytest.raises(Exception):
        model_routes._normalize_provider("   ")
    with pytest.raises(Exception):
        model_routes._normalized_config(provider="OpenAI", model_type="Chat", endpoint=None, config={"model_name": "gpt", "nested": {"api_key": "bad"}}, has_credential=True)
    with pytest.raises(Exception):
        model_routes._normalized_config(provider="Custom", model_type="Chat", endpoint=None, config={}, has_credential=False)


def test_live_serving_and_document_response_helpers(live_client) -> None:
    _client, _headers, user_id, _role_id = live_client
    session_factory = get_session_factory()
    data = _seed_live_document_workspace(session_factory, user_id)
    project_id = UUID(data["project_id"])
    document_id = UUID(data["document_id"])
    version_id = UUID(data["version_id"])
    chunk_id = UUID(data["chunk_id"])

    assert serving_routes._query_terms("GPU API 治理 GPU") == ["gpu", "api", "治", "理"]
    assert serving_routes._safe_excerpt("  one\n two  ") == "one two"
    assert serving_routes._safe_excerpt("x" * 300, limit=12) == "xxxxxxxxxxxx…"
    assert serving_routes._safe_excerpt(None) is None
    assert serving_routes._first_source_page([{"page": "3"}, {"page": "bad"}]) == 3
    assert serving_routes._first_source_page([{"page": "bad"}, "skip"]) is None
    assert serving_routes._hit_id({"_id": 123}) == "123"
    assert serving_routes._hit_id({}) is None

    filters = serving_routes._scope_filters(project_id, [str(version_id)], "published")
    assert filters[0]["term"]["project_id"] == str(project_id)
    assert serving_routes._keyword_query_body(project_id, "Alpha", [str(version_id)], 4, "published")["size"] == 4
    vector_body = serving_routes._vector_query_body(project_id, [0.1, 0.2, 0.3], [str(version_id)], 5, "staging")
    assert vector_body["query"]["bool"]["must"][0]["knn"]["embedding_vector"]["k"] == 5

    graph_nodes: dict[str, ProjectGraphNode] = {}
    assert serving_routes._try_add_graph_node(graph_nodes, ProjectGraphNode(id="one", type="Project", label="One"), 1) is False
    assert serving_routes._try_add_graph_node(graph_nodes, ProjectGraphNode(id="one", type="Project", label="One"), 1) is False
    assert serving_routes._try_add_graph_node(graph_nodes, ProjectGraphNode(id="two", type="Document", label="Two"), 1) is True
    graph_edges: list[ProjectGraphEdge] = []
    edge_ids: set[str] = set()
    edge = ProjectGraphEdge(id="one:two", source="one", target="two", type="upload")
    serving_routes._append_graph_edge(graph_edges, edge_ids, edge)
    serving_routes._append_graph_edge(graph_edges, edge_ids, edge)
    assert len(graph_edges) == 1
    assert serving_routes._filter_graph_edges(graph_edges, {"one": graph_nodes["one"]}) == []
    assert serving_routes._source_anchor([{"anchor": "a1"}, {"source_anchor": "s1"}]) == "a1"
    assert serving_routes._source_anchor(["bad", {"source_anchor": ""}]) is None

    with session_factory() as session:
        project = session.get(Project, project_id)
        document = session.get(Document, document_id)
        version = session.get(DocumentVersion, version_id)
        chunk = session.get(Chunk, chunk_id)
        assert project is not None and document is not None and version is not None and chunk is not None

        manifests, manifest_ids, requested_ids = serving_routes._resolve_retrieval_scope(session, project.id, [version.id])
        assert manifests and manifest_ids == requested_ids == {version.id}
        with pytest.raises(AppError) as bad_retrieval_scope:
            serving_routes._resolve_retrieval_scope(session, project.id, [uuid4()])
        assert bad_retrieval_scope.value.code == "retrieval_scope_denied"
        with pytest.raises(AppError) as published_version_staging_scope:
            serving_routes._resolve_document_staging_scope(session, project.id, [version.id])
        assert published_version_staging_scope.value.code == "chunk_artifacts_not_ready"
        with pytest.raises(AppError) as missing_staging_scope:
            serving_routes._resolve_document_staging_scope(session, project.id, [])
        assert missing_staging_scope.value.code == "retrieval_scope_required"
        with pytest.raises(AppError) as bad_staging_scope:
            serving_routes._resolve_document_staging_scope(session, project.id, [uuid4()])
        assert bad_staging_scope.value.code == "retrieval_scope_denied"

        conversation = session.scalar(select(ChatRecord).where(ChatRecord.project_id == project.id, ChatRecord.scope_mode == "published").limit(1))
        assert conversation is not None
        serving_routes._ensure_conversation_can_continue(session, project.id, conversation.conversation_id, {version.id}, UUID(user_id), "published")
        with pytest.raises(AppError) as locked_conversation:
            serving_routes._ensure_conversation_can_continue(session, project.id, conversation.conversation_id, {uuid4()}, UUID(user_id), "published")
        assert locked_conversation.value.code == "conversation_scope_locked"

        assert serving_routes._select_chat_model(session, project).id == project.llm_model_id
        assert serving_routes._conversation_title("  " * 3) == "新對話"
        assert serving_routes._conversation_title("A" * 90) == "A" * 80
        assert serving_routes._uuid_set([str(version.id), "not-a-uuid"]) == {version.id}
        assert serving_routes._uuid_or_none("not-a-uuid") is None
        assert serving_routes._uuid_or_none(str(version.id)) == version.id
        active_ids = serving_routes._active_version_ids(session, project.id)
        assert version.id in active_ids

        local_graph = serving_routes._read_authorized_postgres_graph(session, frozenset({project.id}), 80)
        assert any(node.id == str(project.id) for node in local_graph.nodes)
        assert any(edge.source == str(project.id) for edge in local_graph.edges)
        truncated_graph = serving_routes._read_authorized_postgres_graph(session, frozenset({project.id}), 1)
        assert truncated_graph.truncated is True
        missing_neighbors = serving_routes._neighbor_graph(local_graph, "missing-node", 10)
        assert missing_neighbors.nodes == []
        neighbor_graph = serving_routes._neighbor_graph(local_graph, str(project.id), 1)
        assert neighbor_graph.nodes[0].id == str(project.id)
        assert neighbor_graph.truncated is True

        published_scopes = serving_routes._hybrid_index_scopes("nomosmart-test", project.id, [version], "published")
        assert published_scopes[0][1] == {version.id}
        staging_scopes = serving_routes._hybrid_index_scopes("nomosmart-test", project.id, [version], "staging")
        assert staging_scopes[0][1] == {version.id}
        with pytest.raises(AppError) as bad_scope:
            serving_routes._hybrid_index_scopes("nomosmart-test", project.id, [version], "bad")
        assert bad_scope.value.code == "retrieval_scope_invalid"

        summaries = serving_routes._conversation_summaries(session, project.id, [conversation], include_records=True)
        assert summaries[0].records[0].id == conversation.id
        response = serving_routes._chat_record_response(conversation)
        assert response.citations[0].chunk_id == chunk.id

        validation_run = ValidationRun(project_id=project.id, uploaded_file_name="helper.csv", status="running", run_scope="project_chat", selected_document_ids=[str(version.id), "bad"], total_count=1, completed_count=0, failed_count=0, created_by=UUID(user_id), created_at=datetime.now(UTC))
        session.add(validation_run)
        session.flush()
        session.add(
            ValidationRunItem(
                run_id=validation_run.id,
                question="What does Alpha cover?",
                expected_answer="GPU",
                expected_keywords=["GPU"],
                selected_document_ids=[str(version.id)],
                reference_docs=[response.citations[0].model_dump(mode="json")],
                status="needs_review",
                score=0.5,
                evaluation_reason="manual review",
                category="coverage",
                priority="low",
                created_at=datetime.now(UTC),
            )
        )
        session.flush()
        validation_response = serving_routes._validation_run_response(session, validation_run)
        assert validation_response.selected_document_ids == [version.id]
        assert validation_response.items[0].citations[0].chunk_id == chunk.id

        chunk_evidence = document_routes._chunk_evidence(session, chunk)
        assert chunk_evidence.id == chunk.id
        assert document_routes._source_text(version, [chunk_evidence]).startswith("Alpha architecture")
        markdownless_version = DocumentVersion(project_id=project.id, document_id=document.id, version_major=99, extraction_revision=0, version_label="v99.0", status="draft", chunk_strategy={}, lock_version=1)
        fallback_chunk = ApprovalChunkEvidence(
            id=uuid4(),
            chunk_index=1,
            title="Fallback",
            content="Fallback content",
            markdown_content=None,
            content_type="text",
            source_mapping=[],
            token_count=2,
            confidence_score=None,
        )
        assert document_routes._source_text(markdownless_version, [fallback_chunk]) == "Fallback content"

        summary = document_routes._project_document(session, document, version, None, visible_project_ids={project.id})
        assert summary.reference_source is None
        service_connection = DataConnection(
            project_id=project.id,
            service_type="HTTP_API",
            name=f"{TEST_PREFIX}-helper-service",
            connection_metadata={"url": "https://example.test"},
            source_identity={"document_id": str(document.id), "url": "https://example.test/base", "file_name": "helper.md"},
            schedule_mode="once",
            timezone="Asia/Taipei",
            enabled=True,
            created_by=UUID(user_id),
        )
        session.add(service_connection)
        session.flush()
        service_summary = document_routes._service_source_summary(session, document)
        assert service_summary is not None and service_summary.location.endswith("/helper.md")
        session.rollback()

    layout_from_text = document_routes._document_layout(DocumentVersion(chunk_strategy={"source_text": "# Heading\n\n- one\n- two\n\nplain"}))
    assert layout_from_text.pages[0].blocks[0].type == "heading"
    assert layout_from_text.pages[0].blocks[1].type == "list"
    invalid_layout = document_routes._document_layout(DocumentVersion(chunk_strategy={"document_layout": {"status": "available", "pages": "bad"}}))
    assert invalid_layout.status == "failed"
    missing_layout = document_routes._document_layout(DocumentVersion(chunk_strategy={}))
    assert missing_layout.status == "missing"
    assert document_routes._split_layout_text("a\n\n b ") == ["a", "b"]
    assert document_routes._layout_block_from_text(1, "plain").type == "paragraph"
    assert document_routes._mime_type(".pdf") == "application/pdf"
    assert document_routes._mime_type(".docx").endswith("wordprocessingml.document")
    assert document_routes._mime_type(".unknown") == "application/octet-stream"
    metadata_md = document_routes._original_file_metadata(project_id, document_id, DocumentVersion(id=version_id, original_file_name="a.md", canonical_extension=".md", mime_type="text/markdown", file_size=5, storage_bucket="b", storage_key="k"))
    assert metadata_md.viewer_type == "markdown"
    metadata_pdf = document_routes._original_file_metadata(project_id, document_id, DocumentVersion(id=version_id, original_file_name="a.pdf", canonical_extension=".pdf", mime_type="application/pdf", file_size=5))
    assert metadata_pdf.preview_error_code == "direct_pdf_viewer_disabled"
    assert document_routes._optional_uuid(str(version_id)) == version_id
    with pytest.raises(AppError) as invalid_uuid:
        document_routes._optional_uuid("bad")
    assert invalid_uuid.value.code == "invalid_ocr_model"
    with pytest.raises(AppError) as invalid_multipart:
        document_routes._parse_multipart(b"", "multipart/form-data")
    assert invalid_multipart.value.code == "invalid_multipart_request"
    multipart_body = (
        b"--abc\r\nContent-Disposition: form-data; name=\"force_ocr\"\r\n\r\ntrue\r\n"
        b"--abc\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.md\"\r\nContent-Type: text/markdown\r\n\r\n# A\r\n"
        b"--abc--\r\n"
    )
    parsed = document_routes._parse_multipart(multipart_body, "multipart/form-data; boundary=abc")
    assert parsed.fields["force_ocr"] == "true"
    assert parsed.files[0].filename == "a.md"
    assert document_routes._headers(b"Content-Type: text/plain\r\nBroken") == {"content-type": "text/plain"}
    response = document_routes._object_response(body=b"ok", content_type="text/plain", filename="a\nb.txt", disposition="inline")
    assert "filename*=" in response.headers["content-disposition"]
    metadata_docx = document_routes._original_file_metadata(project_id, document_id, DocumentVersion(id=version_id, original_file_name="a.docx", canonical_extension=".docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", file_size=5, storage_bucket="b", storage_key="k"))
    assert metadata_docx.viewer_type == "download_only"
    assert metadata_docx.preview_error_code == "direct_office_viewer_disabled"

    chunk = Chunk(
        id=uuid4(),
        project_id=project_id,
        document_id=document_id,
        document_version_id=version_id,
        chunk_index=3,
        title="**Chunk**",
        content="**Alpha** [link](https://example.test) `code`",
        markdown_content="## Title\n\n**Alpha** ![alt](https://example.test/a.png)",
        content_type="text",
        source_mapping=[{"source_anchor": "paragraph-12", "start_offset": 10, "end_offset": 50, "page": 2}],
        token_count=4,
        confidence_score=0.9,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert document_routes._chunk_offsets(chunk) == (10, 50)
    assert document_routes._same_source_anchor(chunk, "paragraph-12") is True
    assert document_routes._same_source_anchor(chunk, "original-document") is True
    assert "Title" in document_routes._manual_split_text(chunk)
    split = document_routes._split_chunk(chunk, 12, 20, "before", UUID(user_id))
    assert split.chunk_strategy["source"] == "manual_split"
    assert document_routes._source_anchor_rank("paragraph-12") == 12
    assert document_routes._source_anchor_rank("page-2") == 20000
    assert document_routes._chunk_source_sort_key(chunk)[0] == 12
    assert document_routes._step_order("upload_received") == 0
    assert document_routes._step_order("unknown") > 10
    assert document_routes._normalize_tag_text("  a   b  ") == "a b"
    with pytest.raises(AppError) as blank_tag:
        document_routes._normalize_tag_text("   ")
    assert blank_tag.value.code == "tag_text_blank"
    assert document_routes._result_tags(ai_provider.AIProviderResult(answer='["A", " ", "B"]', prompt_version="pytest")) == ["A", "B"]
    with pytest.raises(AppError) as non_list_tags:
        document_routes._result_tags(ai_provider.AIProviderResult(answer='{"tag":"A"}', prompt_version="pytest"))
    assert non_list_tags.value.code == "tagging_response_invalid"
    metadata = document_routes._tag_metadata(ai_provider.AIProviderResult(answer="[]", prompt_version="pv", token_usage={"total": 1}))
    assert metadata["prompt_version"] == "pv"


def test_live_extraction_ai_provider_and_publish_helper_edges(live_client) -> None:
    _client, _headers, user_id, _role_id = live_client
    settings = get_settings()
    session_factory = get_session_factory()
    data = _seed_live_document_workspace(session_factory, user_id)
    project_id = UUID(data["project_id"])
    document_id = UUID(data["document_id"])
    version_id = UUID(data["version_id"])

    citation = ProjectChatCitation(
        document_id=document_id,
        document_version_id=version_id,
        chunk_id=UUID(data["chunk_id"]),
        title="Alpha",
        excerpt="Alpha controls GPU isolation.",
        content_type="text",
    )
    tag_prompt = ai_provider._build_tagging_prompt("Alpha", 3, "System", allow_empty=True)
    assert "[]" in tag_prompt[1]["content"]
    assert ai_provider._parse_tag_result("[]", allow_empty=True) == []
    with pytest.raises(AppError) as empty_tags:
        ai_provider._parse_tag_result("[]")
    assert empty_tags.value.code == "tagging_response_empty"
    with pytest.raises(AppError) as empty_excerpt:
        ai_provider._build_citation_bound_prompt("Q", [ProjectChatCitation(document_id=document_id, document_version_id=version_id, chunk_id=uuid4(), excerpt="")], "System")
    assert empty_excerpt.value.code == "retrieval_excerpt_required"
    prompt = ai_provider._build_citation_bound_prompt("Q", [citation], "System")
    assert prompt[0]["role"] == "system" and "Alpha" in prompt[1]["content"]
    judge_prompt = ai_provider._build_judge_prompt(question="Q", answer="A", expected_answer="A", expected_keywords=["GPU"], citations=[citation], system_prompt="Judge")
    assert "Expected keywords: GPU" in judge_prompt[1]["content"]
    responses_model = AIModel(id=uuid4(), name="responses", model_type="Chat", provider="openai", endpoint="http://127.0.0.1:65535/v1/responses", config={"model_name": "gpt", "api_mode": "responses"})
    assert ai_provider._uses_openai_responses_api(responses_model) is True
    assert ai_provider._openai_responses_url("http://host/v1") == "http://host/v1/responses"
    assert ai_provider._openai_responses_url("") == "https://api.openai.com/v1/responses"
    with pytest.raises(AppError) as missing_chat_endpoint:
        ai_provider._invoke_openai_compatible(AIModel(id=uuid4(), name="m", model_type="Chat", provider="custom", config={"model_name": "m"}), prompt, settings)
    assert missing_chat_endpoint.value.code == "model_endpoint_required"
    with pytest.raises(AppError) as missing_ollama_endpoint:
        ai_provider._invoke_ollama(AIModel(id=uuid4(), name="m", model_type="Chat", provider="ollama", config={"model_name": "m"}), prompt, settings)
    assert missing_ollama_endpoint.value.code == "model_endpoint_required"
    with pytest.raises(AppError) as model_secret_ref:
        ai_provider._auth_headers(AIModel(id=uuid4(), name="m", model_type="Chat", provider="openai", api_key_secret_ref="secret/chat", config={"model_name": "m"}), settings)
    assert model_secret_ref.value.code == "model_secret_ref_unresolved"
    with pytest.raises(AppError) as missing_name:
        ai_provider._model_name(AIModel(id=uuid4(), name="   ", model_type="Chat", provider="custom", config={}))
    assert missing_name.value.code == "model_name_required"
    for parser in (ai_provider._openai_answer, ai_provider._openai_responses_answer, ai_provider._ollama_answer, ai_provider._gemini_answer, ai_provider._claude_answer):
        with pytest.raises(AppError) as invalid_answer:
            parser({})
        assert invalid_answer.value.code == "model_response_invalid"
    with pytest.raises(AppError) as invalid_judge_score:
        ai_provider._judge_result('{"score": "bad"}', None, ai_provider.backend_default_prompt("Judge"))
    assert invalid_judge_score.value.code == "judge_response_invalid"
    assert ai_provider._ollama_usage({"prompt_eval_count": 1, "eval_count": 2, "unused": 3}) == {"prompt_eval_count": 1, "eval_count": 2}
    assert ai_provider._gemini_usage({"usageMetadata": {"total": 1}}) == {"total": 1}
    assert ai_provider._gemini_usage({"usageMetadata": "bad"}) is None
    assert ai_provider._claude_usage({"usage": {"input_tokens": 1}}) == {"input_tokens": 1}
    assert ai_provider._claude_usage({"usage": "bad"}) is None
    assert ai_provider._string(" x ") == "x"
    assert ai_provider._int("bad", default=9) == 9
    assert ai_provider._float("bad", default=0.5) == 0.5
    assert ai_provider._timeout({"timeout_seconds": "999"}) == 300
    assert ai_provider._verify_tls({"verify_tls": False}) is False

    assert extraction_pipeline.staging_index_name("nomosmart", project_id, version_id).startswith("nomosmart-staging")
    assert extraction_pipeline._estimated_tokens("abcdefgh") == 2
    assert extraction_pipeline._artifact_ref(DocumentVersion(id=version_id), "parse_document").endswith("/parse_document")
    assert extraction_pipeline._string(" value ") == "value"
    assert extraction_pipeline._int("bad", default=4) == 4
    assert extraction_pipeline._float("bad", default=1.2) == 1.2
    assert extraction_pipeline._timeout({"timeout": "999"}, default=60) == 300
    assert extraction_pipeline._verify_tls({"verify_tls": "off"}) is False
    assert extraction_pipeline._mime_type_for(DocumentVersion(canonical_extension=".jpg")) == "image/jpeg"
    assert extraction_pipeline._mime_type_for(DocumentVersion(canonical_extension=".png")) == "image/png"
    assert extraction_pipeline._mime_type_for(DocumentVersion(canonical_extension=".webp")) == "image/webp"
    assert extraction_pipeline._mime_type_for(DocumentVersion(canonical_extension=".pdf")) == "application/pdf"
    assert extraction_pipeline._has_reliable_text_layer(DocumentVersion(canonical_extension=".pdf", chunk_strategy={"text_layer_status": "none"})) is False
    assert extraction_pipeline._has_reliable_text_layer(DocumentVersion(canonical_extension=".docx", chunk_strategy={})) is False
    assert extraction_pipeline._parse_text(settings, DocumentVersion(canonical_extension=".pdf", chunk_strategy={"force_ocr": True})) == ""
    assert extraction_pipeline._parse_text(settings, DocumentVersion(chunk_strategy={"parsed_text": " Parsed "})) == "Parsed"
    with pytest.raises(AppError) as missing_parser:
        extraction_pipeline._parse_text(settings, DocumentVersion(canonical_extension=".bin", chunk_strategy={}))
    assert missing_parser.value.code == "parser_adapter_not_configured"
    assert extraction_pipeline._split_paragraphs("") == [""]
    long_paragraph = "long text. " * 120
    layout = extraction_pipeline._document_layout_artifact(["# Title", "- one\n- two", "|A|B|\n|-|-|\n|1|2|", long_paragraph])
    assert len(layout["pages"]) >= 1
    assert extraction_pipeline._estimated_layout_block_height({"type": "code", "text": "a\nb"}) > 0
    assert len(extraction_pipeline._paginate_layout_blocks([{"type": "paragraph", "text": "x" * 1200} for _ in range(20)])) > 1
    assert extraction_pipeline._openai_ocr_markdown({"output_text": " Direct markdown "}) == "Direct markdown"
    with pytest.raises(AppError) as empty_ocr:
        extraction_pipeline._openai_ocr_markdown({"output": []})
    assert empty_ocr.value.code == "ocr_adapter_empty_result"
    assert extraction_pipeline._valid_markdown_ocr_text("[not-json") is True
    assert extraction_pipeline._valid_markdown_ocr_text("[]") is False
    assert extraction_pipeline._openai_responses_url("http://host/v1/responses") == "http://host/v1/responses"
    assert extraction_pipeline._openai_responses_url("http://host/v1") == "http://host/v1/responses"
    with pytest.raises(AppError) as blank_ocr_name:
        extraction_pipeline._model_name(AIModel(id=uuid4(), name=" ", model_type="OCR", provider="openai", config={}))
    assert blank_ocr_name.value.code == "ocr_model_name_required"
    assert extraction_pipeline._default_ocr_adapter(None, DocumentVersion()).__class__.__name__ == "LiveOnlyOCRAdapter"
    assert extraction_pipeline._default_ocr_adapter(None, DocumentVersion(ocr_model_id=None)).__class__.__name__ == "LiveOnlyOCRAdapter"

    with session_factory() as session:
        project = session.get(Project, project_id)
        document = session.get(Document, document_id)
        version = session.get(DocumentVersion, version_id)
        assert project is not None and document is not None and version is not None
        profile = session.get(EmbeddingProfile, version.embedding_profile_id)
        assert profile is not None
        chat_model = session.get(AIModel, project.llm_model_id)
        embedding_model = session.get(AIModel, version.embedding_model_id)
        assert chat_model is not None and embedding_model is not None

        assert extraction_pipeline._vector_index_mapping(profile)["mappings"]["properties"]["embedding_vector"]["dimension"] == profile.vector_dimension
        resolved_profile = extraction_pipeline._embedding_profile(session, embedding_model, version, profile.vector_dimension)
        assert resolved_profile.vector_dimension == profile.vector_dimension
        new_profile = extraction_pipeline._embedding_profile(session, embedding_model, version, profile.vector_dimension + 7)
        assert new_profile.vector_dimension == profile.vector_dimension + 7
        with pytest.raises(AppError) as embedding_auth:
            extraction_pipeline._embedding_auth_headers(embedding_model, settings)
        assert embedding_auth.value.code == "embedding_adapter_credential_required"
        encrypted_id = uuid4()
        encrypted_key = EnvelopeCipher(settings.encryption_key_bytes).encrypt("ocr-key", context=f"ai-model:{encrypted_id}")
        encrypted_ocr = AIModel(id=encrypted_id, name=f"{TEST_PREFIX}-ocr-encrypted", model_type="OCR", provider="openai", endpoint="http://127.0.0.1:65535/v1", api_key_encrypted=encrypted_key, config={"model_name": "ocr"})
        assert extraction_pipeline._openai_auth_headers(encrypted_ocr, settings)["Authorization"] == "Bearer ocr-key"
        with pytest.raises(AppError) as secret_ref_ocr:
            extraction_pipeline._openai_auth_headers(AIModel(id=uuid4(), name="ocr", model_type="OCR", provider="openai", api_key_secret_ref="secret/ocr", config={"model_name": "ocr"}), settings)
        assert secret_ref_ocr.value.code == "ocr_adapter_secret_ref_unresolved"
        with pytest.raises(AppError) as openai_embeddings_auth:
            extraction_pipeline._post_openai_embeddings(embedding_model, settings, ["Alpha"])
        assert openai_embeddings_auth.value.code == "embedding_adapter_credential_required"
        assert extraction_pipeline._openai_embeddings_url("http://host/v1/embeddings") == "http://host/v1/embeddings"
        with pytest.raises(AppError) as invalid_embedding_payload:
            extraction_pipeline._openai_embedding_vectors({"bad": []})
        assert invalid_embedding_payload.value.code == "embedding_response_invalid"
        assert extraction_pipeline._openai_embedding_vectors({"data": [{"index": 0, "embedding": [1, "2"]}]}) == [[1.0, 2.0]]

        payload = extraction_pipeline._openai_ocr_payload(
            encrypted_ocr,
            version,
            [("source.txt", "text/plain", b"file-bytes")],
            "parsed",
        )
        assert payload["input"][1]["content"][1]["file_data"].startswith("data:text/plain;base64,")
        with pytest.raises(AppError) as source_missing:
            extraction_pipeline._load_source_object(settings, DocumentVersion(id=uuid4(), storage_bucket=None, storage_key=None))
        assert source_missing.value.code == "ocr_source_file_missing"
        with pytest.raises(AppError) as openai_ocr_auth:
            extraction_pipeline._post_openai_ocr(AIModel(id=uuid4(), name="ocr", model_type="OCR", provider="openai", endpoint="http://127.0.0.1:65535/v1", config={"model_name": "ocr"}), settings, payload, timeout_seconds=1)
        assert openai_ocr_auth.value.code == "ocr_adapter_credential_required"
        with pytest.raises(AppError) as openai_source_missing:
            extraction_pipeline.OpenAIOCRAdapter(settings).extract_text(model=encrypted_ocr, version=DocumentVersion(id=uuid4(), original_file_name="a.pdf", canonical_extension=".pdf"), parsed_text="", force_ocr=True, reliable_text_layer=False)
        assert openai_source_missing.value.code == "ocr_source_file_missing"
        with pytest.raises(AppError) as generic_missing:
            extraction_pipeline.GenericHTTPOCRAdapter().extract_text(model=None, version=version, parsed_text="", force_ocr=True, reliable_text_layer=False)
        assert generic_missing.value.code == "ocr_adapter_not_configured"
        snapshot_model = AIModel(id=uuid4(), name="snapshot", model_type="OCR", provider="openai", endpoint="http://127.0.0.1", config={"languages": "zh-TW", "timeout_seconds": 700, "retry_count": 9})
        snapshot = extraction_pipeline._ocr_snapshot(snapshot_model, DocumentVersion(ocr_model_id=snapshot_model.id, ocr_config_version=3, chunk_strategy={"force_ocr_confirmed": True}), True)
        assert snapshot["languages"] == ["zh-TW"]
        assert snapshot["timeout_seconds"] == 600
        assert snapshot["retry_count"] == 5

        chunks = list(session.scalars(select(Chunk).where(Chunk.document_version_id == version.id).order_by(Chunk.chunk_index)))
        assert chunks
        with pytest.raises(AppError) as staging_count:
            extraction_pipeline.LiveOpenSearchStagingIndexAdapter(settings).write_chunks(project=project, document=document, version=version, chunks=chunks, vectors=[], profile=profile)
        assert staging_count.value.code == "embedding_result_count_mismatch"
        with pytest.raises(AppError) as staging_dimension:
            extraction_pipeline.LiveOpenSearchStagingIndexAdapter(settings)._write_live("unused", project, document, version, chunks[:1], [[0.1]], profile)
        assert staging_dimension.value.code == "embedding_profile_mismatch"
        assert extraction_pipeline._resolve_chat_tag_model(session, project).id == project.llm_model_id
        with pytest.raises(AppError) as extraction_blank_tag:
            extraction_pipeline._normalize_tag_text(" ")
        assert extraction_blank_tag.value.code == "tag_text_blank"
        assert extraction_pipeline._result_tags(ai_provider.AIProviderResult(answer="[]", prompt_version="pytest"), allow_empty=True) == []
        with pytest.raises(AppError) as empty_result_tags:
            extraction_pipeline._result_tags(ai_provider.AIProviderResult(answer="[]", prompt_version="pytest"))
        assert empty_result_tags.value.code == "tagging_response_invalid"
        tag_metadata = extraction_pipeline._tag_metadata(ai_provider.AIProviderResult(answer='["A"]', prompt_version="pv", token_usage={"total": 1}), model=chat_model, pipeline=session.get(PipelineRun, UUID(data["pipeline_id"])), scope="chunk", chunk_id=chunks[0].id)
        assert tag_metadata["tagging_scope"] == "chunk"
        extraction_pipeline._attach_chunk_tag(session, project.id, chunks[0].id, f"{TEST_PREFIX}-edge-tag", source="llm", actor_user_id=UUID(user_id), metadata=tag_metadata)
        session.flush()
        extraction_pipeline._attach_chunk_tag(session, project.id, chunks[0].id, f"{TEST_PREFIX}-edge-tag", source="manual", actor_user_id=UUID(user_id), metadata={"source": "manual"}, confidence_score=0.7)
        extraction_pipeline._attach_document_tag(session, project.id, version.id, f"{TEST_PREFIX}-edge-doc-tag", source="llm", actor_user_id=UUID(user_id), metadata=tag_metadata)
        session.flush()
        extraction_pipeline._attach_document_tag(session, project.id, version.id, f"{TEST_PREFIX}-edge-doc-tag", source="manual", actor_user_id=UUID(user_id), metadata={"source": "manual"}, confidence_score=0.8)
        extraction_pipeline._delete_rule_tag_links(session, version, chunks)
        preview = extraction_pipeline._graph_preview_artifact(session, project, document, version, chunks)
        assert preview["node_count"] >= 3

        published_adapter = review_publish.LiveOpenSearchPublishedAdapter(settings)
        with pytest.raises(AppError) as published_profile_required:
            published_adapter.write_published_chunks(project_id=project.id, document=document, version=DocumentVersion(id=uuid4(), embedding_profile_id=None), chunks=[])
        assert published_profile_required.value.code == "embedding_profile_required"
        with pytest.raises(AppError) as published_profile_mismatch:
            published_adapter.write_published_chunks(project_id=project.id, document=document, version=version, chunks=chunks, vectors=[], profile=profile)
        assert published_profile_mismatch.value.code == "embedding_profile_mismatch"
        assert review_publish._vector_index_mapping(profile)["mappings"]["properties"]["embedding_vector"]["dimension"] == profile.vector_dimension
        assert review_publish.published_index_name("nomosmart", profile.id).startswith("nomosmart-published-profile")
        checksum = review_publish.chunk_checksum(chunks)
        assert len(checksum) == 64
        build = review_publish._embedding_build(session, version, review_publish.PublishedIndexResult(index_name="edge-index", document_ids=[str(chunk.id) for chunk in chunks], checksum=checksum), len(chunks))
        assert build.status == "published"
        build = review_publish._embedding_build(session, version, review_publish.PublishedIndexResult(index_name="edge-index-2", document_ids=[str(chunk.id) for chunk in chunks], checksum=checksum), len(chunks))
        assert build.index_name == "edge-index-2"
        user = session.get(User, UUID(user_id))
        assert user is not None
        delegated = uuid4()
        user.manager_user_id = uuid4()
        user.manager_delegate_user_id = delegated
        user.manager_delegate_start_at = datetime.now(UTC) - timedelta(minutes=1)
        user.manager_delegate_end_at = datetime.now(UTC) + timedelta(minutes=1)
        assert review_publish._manager_or_delegate(user)[0] == delegated
        user.manager_delegate_end_at = datetime.now(UTC) - timedelta(minutes=1)
        assert review_publish._manager_or_delegate(user)[0] == user.manager_user_id
        pending_task = ApprovalTask(approval_request_id=uuid4(), project_id=project.id, document_id=document.id, document_version_id=version.id, submitter_id=UUID(user_id), review_stage=review_publish.MANAGER_REVIEW, status="pending", lock_version=2, submitted_at=datetime.now(UTC), created_at=datetime.now(UTC))
        review_publish._ensure_pending_task(pending_task, 2)
        with pytest.raises(AppError) as stale_task:
            review_publish._ensure_pending_task(pending_task, 1)
        assert stale_task.value.code == "stale_approval_task"
        pending_task.status = "approved"
        with pytest.raises(AppError) as not_pending:
            review_publish._ensure_pending_task(pending_task, 2)
        assert not_pending.value.code == "approval_task_not_pending"
        with pytest.raises(AppError) as missing_request:
            review_publish._approval_request(session, uuid4())
        assert missing_request.value.code == "approval_request_not_found"
        with pytest.raises(AppError) as missing_version:
            review_publish._version(session, uuid4())
        assert missing_version.value.code == "document_version_not_found"
        pipeline = session.get(PipelineRun, UUID(data["pipeline_id"]))
        assert pipeline is not None
        review_publish._mark_pipeline_waiting(session, version.id, review_publish.MANAGER_REVIEW, "manager")
        assert pipeline.status == "waiting_action"
        review_publish._mark_pipeline_rejected(session, version.id, review_publish.MANAGER_REVIEW, "Rejected")
        assert pipeline.status == "review_rejected"
        review_publish._start_pipeline_step(session, version.id, review_publish.PUBLISH_STAGE, "Publishing")
        assert pipeline.status == "running"
        review_publish._complete_pipeline_step(session, version.id, review_publish.PUBLISH_STAGE, "Published")
        review_publish._fail_pipeline_step(session, version.id, review_publish.GRAPH_SYNC_STAGE, "Graph failed")
        assert pipeline.status == "failed"
        review_publish._complete_pipeline_publication(session, version.id)
        assert pipeline.status == "completed"
        review_publish._notify(session, None, project.id, "none", "No recipient", "No notification", {})
        session.rollback()


def test_live_approval_project_and_data_source_route_edges(live_client) -> None:
    client, headers, user_id, _role_id = live_client
    session_factory = get_session_factory()
    data = _seed_live_document_workspace(session_factory, user_id)
    project_id = UUID(data["project_id"])
    document_id = UUID(data["document_id"])
    version_id = UUID(data["version_id"])

    assert project_routes._validate_roles(["owner", "editor"]) == {"owner", "editor"}
    with pytest.raises(AppError) as invalid_role:
        project_routes._validate_roles(["admin"])
    assert invalid_role.value.code == "invalid_project_role"
    with pytest.raises(AppError) as empty_role:
        project_routes._validate_roles([])
    assert empty_role.value.code == "invalid_project_role"

    bad_member = User(
        employee_id=f"Z{uuid4().hex[:9]}",
        keycloak_user_id=f"inactive-{uuid4()}",
        email=f"inactive-{uuid4().hex[:8]}@example.test",
        display_name="Inactive Live Edge",
        is_active=False,
        auth_source="keycloak",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with session_factory() as session:
        session.add(bad_member)
        session.flush()
        assert project_routes._users_with_knowledge_project_view(session, set()) == set()
        assert UUID(user_id) in project_routes._users_with_knowledge_project_view(session, {UUID(user_id)})
        with pytest.raises(AppError) as invalid_member:
            project_routes._validate_project_member_candidates(session, {bad_member.id})
        assert invalid_member.value.code == "invalid_project_member"
        with pytest.raises(AppError) as invalid_model:
            project_routes._resolve_model(session, uuid4(), "Chat")
        assert invalid_model.value.code == "invalid_project_model"
        missing_context = SimpleNamespace(user_id=UUID(user_id), visible_project_ids=frozenset({uuid4()}), grants=())
        with pytest.raises(AppError) as project_missing:
            project_routes._get_scoped_project(session, next(iter(missing_context.visible_project_ids)), missing_context)
        assert project_missing.value.code in {"permission_denied", "project_not_found"}
        session.rollback()

    project = _assert_ok(client.get(f"/api/v1/projects/{project_id}", headers=headers))
    remove_last_owner = client.delete(f"/api/v1/projects/{project_id}/members/{user_id}?lock_version={project['lock_version']}", headers=headers)
    assert remove_last_owner.status_code == 409
    demote_last_owner = client.put(f"/api/v1/projects/{project_id}/members/{user_id}", headers=headers, json={"roles": ["viewer"], "lock_version": project["lock_version"]})
    assert demote_last_owner.status_code == 409
    bad_member_payload = client.put(f"/api/v1/projects/{project_id}/members/{uuid4()}", headers=headers, json={"roles": ["viewer"], "lock_version": project["lock_version"]})
    assert bad_member_payload.status_code == 422

    def http_payload(**overrides) -> DataSourceConnectionPayload:
        values = {
            "service_type": "HTTP_API",
            "name": f"{TEST_PREFIX}-http-edge",
            "host": "",
            "port": 443,
            "username": "",
            "file_name": "edge.md",
            "schedule_mode": "once",
            "timezone": "Asia/Taipei",
            "url": "https://example.test/edge.md",
            "auth_mode": "none",
        }
        values.update(overrides)
        return DataSourceConnectionPayload(**values)

    valid_http = http_payload(headers={"X-Trace": "1"})
    data_source_routes._validate_data_source_payload(valid_http)
    assert data_source_routes._remote_uri(valid_http) == "https://example.test/edge.md"
    assert data_source_routes._connection_metadata(valid_http)["headers"] == {"X-Trace": "1"}
    assert data_source_routes._source_identity(valid_http, "https://example.test/edge.md", document_id)["url"] == "https://example.test/edge.md"
    assert data_source_routes._safe_payload_summary(valid_http)["headers_configured"] == 1
    assert data_source_routes._valid_five_field_cron("*/5 * * * *") is True
    assert data_source_routes._valid_five_field_cron("bad") is False
    for payload, expected_code in (
        (http_payload(url="ftp://example.test/edge.md"), "http_source_url_invalid"),
        (http_payload(auth_mode="api_key_header", api_key_header_name=None), "http_source_header_required"),
        (http_payload(headers={"Authorization": "secret"}), "http_source_header_invalid"),
        (DataSourceConnectionPayload(service_type="FTP", name="ftp", host="", port=21, username="user", credential="pw", file_name="edge.md"), "data_source_host_required"),
        (DataSourceConnectionPayload(service_type="S3", name="s3", host="", port=443, username="access", credential="secret", file_name="edge.md"), "data_source_bucket_required"),
        (DataSourceConnectionPayload(service_type="SFTP", name="sftp", host="example.test", port=22, username="", credential="secret", file_name="edge.md"), "data_source_username_required"),
        (DataSourceConnectionPayload(service_type="FTPS", name="ftps", host="example.test", port=21, username="user", file_name="edge.md"), "data_source_credential_required"),
        (http_payload(schedule_mode="cron", cron_expression="bad"), "data_source_cron_invalid"),
    ):
        with pytest.raises(AppError) as payload_error:
            data_source_routes._validate_data_source_payload(payload)
        assert payload_error.value.code == expected_code
    s3_payload = DataSourceConnectionPayload(service_type="S3", name="s3", host="", port=443, username="access", credential="secret", bucket="bucket", remote_path="/incoming", file_name="edge.md")
    assert data_source_routes._remote_uri(s3_payload) == "s3://bucket/incoming/edge.md"
    ftp_payload = DataSourceConnectionPayload(service_type="FTP", name="ftp", host="example.test", port=21, username="user", credential="secret", remote_path="/incoming", file_name="edge.md")
    assert data_source_routes._remote_uri(ftp_payload) == "ftp://example.test:21/incoming/edge.md"
    connection = DataConnection(
        id=uuid4(),
        project_id=project_id,
        service_type="HTTP_API",
        name="edge",
        connection_metadata=data_source_routes._connection_metadata(valid_http),
        source_identity=data_source_routes._source_identity(valid_http, data_source_routes._remote_uri(valid_http), document_id),
        schedule_mode="once",
        timezone="Asia/Taipei",
        enabled=True,
        last_sync_status="queued",
        lock_version=1,
        created_by=UUID(user_id),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert data_source_routes._data_source_response(connection).credential_configured is False

    with session_factory() as session:
        project = session.get(Project, project_id)
        document = session.get(Document, document_id)
        version = session.get(DocumentVersion, version_id)
        assert project is not None and document is not None and version is not None
        no_owner_user = User(
            employee_id=f"Z{uuid4().hex[:9]}",
            keycloak_user_id=f"no-owner-{uuid4()}",
            email=f"no-owner-{uuid4().hex[:8]}@example.test",
            display_name="No Owner Live Edge",
            is_active=True,
            auth_source="keycloak",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(no_owner_user)
        session.flush()
        context = SimpleNamespace(user_id=UUID(user_id), visible_project_ids=frozenset({project.id}), grants=())

        review_version = session.get(DocumentVersion, UUID(data["review_version_id"]))
        assert review_version is not None
        approval = review_publish.submit_review(session=session, actor_user_id=UUID(user_id), version=review_version, owner_user_id=UUID(user_id), request_id=f"{TEST_PREFIX}-route-edge", **_review_evidence(review_version.id))
        task = session.get(ApprovalTask, approval.current_task_id)
        assert task is not None
        pending_tasks = list(session.scalars(approval_routes._pending_query(session, context)))
        assert any(item.id == task.id for item in pending_tasks)
        task_response = approval_routes._approval_task_response(session, task)
        assert task_response.document_version_id == review_version.id
        request_response = approval_routes._approval_request_response(session, approval)
        assert request_response.id == approval.id
        pending_publish = approval_routes._pending_publish_response(review_version, session.get(Document, review_version.document_id), project, approval, session.get(User, UUID(user_id)), task.id)
        assert pending_publish.document_version_id == review_version.id
        assert approval_routes._scoped_task(session, task.id, context).id == task.id
        task.assignee_user_id = no_owner_user.id
        with pytest.raises(AppError) as assignee_required:
            approval_routes._scoped_task(session, task.id, context, for_decision=True)
        assert assignee_required.value.code == "approval_assignee_required"
        task.review_stage = "owner_review"
        with pytest.raises(AppError) as missing_owner:
            approval_routes._scoped_task(session, task.id, SimpleNamespace(user_id=no_owner_user.id, visible_project_ids=frozenset({project.id}), grants=()), for_decision=True)
        assert missing_owner.value.code == "project_owner_required"
        with pytest.raises(AppError) as missing_task:
            approval_routes._scoped_task(session, uuid4(), context)
        assert missing_task.value.code == "approval_task_not_found"

        assert approval_routes._begin_idempotent_operation(session=session, scope="edge-none", key=None, request_payload={}) == (None, None)
        replay, record = approval_routes._begin_idempotent_operation(session=session, scope="edge", key=f"{TEST_PREFIX}-key", request_payload={"a": 1})
        assert replay is None and record is not None
        with pytest.raises(AppError) as key_in_progress:
            approval_routes._begin_idempotent_operation(session=session, scope="edge", key=f"{TEST_PREFIX}-key", request_payload={"a": 1})
        assert key_in_progress.value.code == "idempotency_key_in_progress"
        approval_routes._complete_idempotent_operation(record, {"status": "ok"})
        replay, _existing = approval_routes._begin_idempotent_operation(session=session, scope="edge", key=f"{TEST_PREFIX}-key", request_payload={"a": 1})
        assert replay == {"status": "ok"}
        with pytest.raises(AppError):
            approval_routes._begin_idempotent_operation(session=session, scope="edge", key=f"{TEST_PREFIX}-key", request_payload={"a": 2})

        chunks = approval_routes._approval_chunk_evidence(session, version.id)
        assert chunks
        assert approval_routes._source_text(version, chunks).startswith("Alpha architecture")
        metadata = approval_routes._original_file_metadata(project.id, document.id, version)
        assert metadata.viewer_type in {"download_only", "markdown", "unsupported"}
        layout = approval_routes._document_layout(version)
        assert layout.status in {"available", "missing", "failed"}
        assert approval_routes._split_layout_text("a\n\nb") == ["a", "b"]
        assert approval_routes._layout_block_from_text(1, "# Heading").type == "heading"
        assert approval_routes._layout_block_from_text(2, "- one\n- two").type == "list"
        assert approval_routes._layout_block_from_text(3, "plain").type == "paragraph"
        assert approval_routes._chunk_tag_details(session, UUID(data["chunk_id"]))
        assert approval_routes._document_tag_details(session, version.id)
        assert approval_routes._document_summary(document, None).latest_version is None
        assert approval_routes._version_summary(version).id == version.id
        session.rollback()


def test_live_system_auth_validation_and_worker_behaviors(live_client) -> None:
    client, headers, user_id, _role_id = live_client
    session_factory = get_session_factory()
    settings = get_settings()
    data = _seed_live_document_workspace(session_factory, user_id)
    project_id = UUID(data["project_id"])

    current_parameters = _assert_ok(client.get("/api/v1/system/parameters", headers=headers))
    assert current_parameters["max_upload_size_mb"] >= 1
    assert current_parameters["default_timezone"]
    invalid_parameters = {**current_parameters, "session_expired_form_draft_ttl_minutes": 1}
    rejected_parameters = client.put("/api/v1/system/parameters", headers=headers, json=invalid_parameters)
    assert rejected_parameters.status_code == 422
    updated_parameters = _assert_ok(client.put("/api/v1/system/parameters", headers=headers, json=current_parameters))
    assert updated_parameters == current_parameters
    upload_config = _assert_ok(client.get("/api/v1/system/upload-config", headers=headers))
    assert upload_config["max_upload_size_mb"] == settings.max_upload_size_mb
    status_payload = _assert_ok(client.get("/api/v1/system/status", headers=headers))
    assert "dependencies" in status_payload
    break_glass = _assert_ok(client.get("/api/v1/system/break-glass/status", headers=headers))
    assert break_glass["status"] in {"configured_disabled", "not_configured", "attention_required", "unavailable"}
    assert system_routes._keycloak_realm(settings.oidc_issuer_url) == settings.oidc_issuer_url.rstrip("/").rsplit("/", 1)[-1]
    assert system_routes._break_glass_deployment_evidence(settings)[2] == "deployment_only"

    now = datetime.now(UTC)
    token = f"{TEST_PREFIX}-logout-{uuid4()}"
    principal = IdentityPrincipal(
        subject=str(SERVICE_CLAIMS["sub"]),
        employee_id=None,
        email=None,
        display_name=None,
        groups=(),
        session_id=f"{TEST_PREFIX}-session-{uuid4()}",
        auth_time=int(now.timestamp()),
        issuer=str(SERVICE_CLAIMS["iss"]),
        audience=str(os.environ["OIDC_AUDIENCE"]),
        token_id=f"{TEST_PREFIX}-token-{uuid4()}",
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=30),
    )
    with session_factory() as session:
        grant = IdentityUnlockGrant(
            user_id=UUID(user_id),
            session_id=str(principal.session_id),
            scope="identity-settings",
            auth_time=now,
            expires_at=now + timedelta(minutes=10),
            created_at=now,
        )
        session.add(grant)
        session.flush()
        revoked = revoke_login_session(session, principal=principal, token=token, request_id=f"{TEST_PREFIX}-logout")
        session.flush()
        assert revoked.revoked_by == UUID(user_id)
        assert revoked.metadata_json["has_jti"] is True
        session.refresh(grant)
        assert grant.revoked_at is not None
        assert is_token_revoked(session, principal, token) is True
        repeated = revoke_login_session(session, principal=principal, token=token, request_id=f"{TEST_PREFIX}-logout-replay")
        session.flush()
        assert repeated.id == revoked.id
        assert session.scalar(select(RevokedAuthToken).where(RevokedAuthToken.id == revoked.id)) is not None
        session.rollback()

    assert validation_runner._validation_status(score=None, reason="unscored") == "needs_review"
    assert validation_runner._validation_status(score=0.8, reason="ok") == "passed"
    assert validation_runner._validation_status(score=0.1, reason="low") == "failed"
    mixed_ids = validation_runner._uuid_set([data["version_id"], "not-a-uuid", UUID(data["review_version_id"])])
    assert UUID(data["version_id"]) in mixed_ids
    with session_factory() as session:
        statuses_to_expected = (
            (("passed", "error"), "partial_failed", 1, 1),
            (("error",), "failed", 0, 1),
            (("needs_review", "skipped"), "completed", 2, 0),
        )
        for statuses, expected_status, completed_count, failed_count in statuses_to_expected:
            run = ValidationRun(
                project_id=project_id,
                uploaded_file_name=f"{TEST_PREFIX}-counts.csv",
                status="running",
                run_scope="project_chat",
                selected_document_ids=[],
                total_count=len(statuses),
                completed_count=0,
                failed_count=0,
                created_by=UUID(user_id),
                created_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            for status in statuses:
                session.add(
                    ValidationRunItem(
                        run_id=run.id,
                        question=f"Live count {status}",
                        expected_answer=None,
                        expected_keywords=[],
                        selected_document_ids=[],
                        reference_docs=[],
                        status=status,
                        category="coverage",
                        priority="low",
                        created_at=datetime.now(UTC),
                    )
                )
            session.flush()
            validation_runner._refresh_run_counts(session, run)
            assert run.status == expected_status
            assert run.completed_count == completed_count
            assert run.failed_count == failed_count
        with pytest.raises(AppError) as missing_run:
            validation_runner.execute_validation_run(session, uuid4())
        assert missing_run.value.code == "validation_run_not_found"
        session.rollback()

    active_sync_id = uuid4()
    created_active_sync = False
    with session_factory() as session:
        existing_active = session.scalar(select(IdentitySyncRun).where(IdentitySyncRun.status.in_(("queued", "running"))))
        if existing_active is not None:
            active_sync_id = existing_active.id
        else:
            session.add(
                IdentitySyncRun(
                    id=active_sync_id,
                    source="keycloak",
                    trigger_type="scheduled",
                    status="running",
                    users_created=0,
                    users_updated=0,
                    users_disabled=0,
                    groups_created=0,
                    groups_updated=0,
                    role_memberships_updated=0,
                    attempt=0,
                )
            )
            session.commit()
            created_active_sync = True
    try:
        worker.queue_scheduled_identity_sync()
        worker.run_identity_sync(str(uuid4()))
    finally:
        if created_active_sync:
            with session_factory() as session:
                session.execute(delete(IdentitySyncRun).where(IdentitySyncRun.id == active_sync_id))
                session.commit()


def test_live_system_prompt_routes_with_versions_and_model_scope(live_client) -> None:
    client, headers, user_id, _role_id = live_client
    session_factory = get_session_factory()
    model_id = uuid4()
    upsert_model_id = uuid4()
    with session_factory() as session:
        session.add_all([
            AIModel(
                id=model_id,
                name=f"{TEST_PREFIX}-prompt-chat-{uuid4().hex[:8]}",
                model_type="Chat",
                provider="openai",
                endpoint="http://127.0.0.1:65535/v1/responses",
                is_active=True,
                is_default=False,
                config={"model_name": "live-prompt"},
                config_version=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
            AIModel(
                id=upsert_model_id,
                name=f"{TEST_PREFIX}-prompt-upsert-{uuid4().hex[:8]}",
                model_type="Chat",
                provider="openai",
                endpoint="http://127.0.0.1:65535/v1/responses",
                is_active=True,
                is_default=False,
                config={"model_name": "live-prompt-upsert"},
                config_version=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        ])
        session.commit()

    prompt_payload = {
        "prompt_scope": "model",
        "model_type": "Chat",
        "model_id": str(model_id),
        "content": f"{TEST_PREFIX} scoped chat prompt",
        "is_active": False,
        "change_reason": "live route coverage",
    }
    scoped_prompt = _assert_ok(client.post("/api/v1/system-prompts", headers=headers, json=prompt_payload), 201)
    assert scoped_prompt["prompt_scope"] == "model"
    duplicate = client.post("/api/v1/system-prompts", headers=headers, json={**prompt_payload, "content": f"{TEST_PREFIX} duplicate"})
    assert duplicate.status_code == 409
    blank_active = client.post(
        "/api/v1/system-prompts",
        headers=headers,
        json={"prompt_scope": "model", "model_type": "Chat", "model_id": str(upsert_model_id), "content": " ", "is_active": True},
    )
    assert blank_active.status_code == 422
    versions = _assert_ok(client.get(f"/api/v1/system-prompts/{scoped_prompt['id']}/versions", headers=headers))
    assert versions[0]["version_number"] == 1
    second_version = _assert_ok(
        client.post(
            f"/api/v1/system-prompts/{scoped_prompt['id']}/versions",
            headers=headers,
            json={"content": f"{TEST_PREFIX} second chat prompt", "is_active": True, "change_reason": "activate"},
        ),
        201,
    )
    assert second_version["current_version_number"] == 2
    deactivated = _assert_ok(client.post(f"/api/v1/system-prompts/{scoped_prompt['id']}/deactivate", headers=headers))
    assert deactivated["is_active"] is False
    activated = _assert_ok(client.post(f"/api/v1/system-prompts/{scoped_prompt['id']}/activate", headers=headers, json={"version_id": versions[0]["id"]}))
    assert activated["is_active"] is True
    listed = _assert_ok(client.get("/api/v1/system-prompts", headers=headers))
    assert any(item["id"] == scoped_prompt["id"] for item in listed)

    model_missing = client.get(f"/api/v1/models/{upsert_model_id}/system-prompt", headers=headers)
    assert model_missing.status_code == 404
    model_prompt = _assert_ok(
        client.put(
            f"/api/v1/models/{upsert_model_id}/system-prompt",
            headers=headers,
            json={"content": f"{TEST_PREFIX} model prompt", "is_active": True, "change_reason": "model scope"},
        )
    )
    assert model_prompt["model_id"] == str(upsert_model_id)
    fetched_model_prompt = _assert_ok(client.get(f"/api/v1/models/{upsert_model_id}/system-prompt", headers=headers))
    assert fetched_model_prompt["id"] == model_prompt["id"]
    updated_model_prompt = _assert_ok(
        client.put(
            f"/api/v1/models/{upsert_model_id}/system-prompt",
            headers=headers,
            json={"content": f"{TEST_PREFIX} model prompt v2", "is_active": False, "change_reason": "model update"},
        )
    )
    assert updated_model_prompt["current_version_number"] == 2
    assert updated_model_prompt["is_active"] is False
    missing_model = client.put(f"/api/v1/models/{uuid4()}/system-prompt", headers=headers, json={"content": "x", "is_active": True})
    assert missing_model.status_code == 404


def test_live_ai_model_routes_pairings_updates_and_lifecycle(live_client) -> None:
    client, headers, _user_id, _role_id = live_client
    session_factory = get_session_factory()

    listed_response = client.get("/api/v1/models?model_type=Chat&limit=10", headers=headers)
    listed = _assert_ok(listed_response)
    assert isinstance(listed, list)
    assert int(listed_response.headers["X-Total-Count"]) >= len(listed)
    assert client.get("/api/v1/models?model_type=chat", headers=headers).status_code == 422
    invalid_type = client.post(
        "/api/v1/models",
        headers=headers,
        json={"name": f"{TEST_PREFIX}-bad-type", "model_type": "Bad", "provider": "custom", "endpoint": "http://127.0.0.1:65535/model"},
    )
    assert invalid_type.status_code == 422
    secret_config = client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": f"{TEST_PREFIX}-secret-config",
            "model_type": "Embedding",
            "provider": "custom",
            "endpoint": "http://127.0.0.1:65535/model",
            "config": {"password": "use-api-key-field"},
        },
    )
    assert secret_config.status_code == 422

    embedding = _assert_ok(
        client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "name": f"{TEST_PREFIX}-route-emb-{uuid4().hex[:8]}",
                "model_type": "Embedding",
                "provider": "custom",
                "endpoint": "http://127.0.0.1:65535/embeddings",
                "config": {"vector_dimension": 8},
                "is_active": True,
                "is_default": False,
            },
        ),
        201,
    )
    bad_chat_pairing = client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "name": f"{TEST_PREFIX}-bad-chat-pairing",
            "model_type": "Chat",
            "provider": "custom",
            "endpoint": "http://127.0.0.1:65535/chat",
            "config": {"paired_embedding_model_ids": []},
        },
    )
    assert bad_chat_pairing.status_code == 422
    chat = _assert_ok(
        client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "name": f"{TEST_PREFIX}-route-chat-{uuid4().hex[:8]}",
                "model_type": "Chat",
                "provider": "custom",
                "endpoint": "http://127.0.0.1:65535/chat",
                "config": {"paired_embedding_model_ids": [embedding["id"], embedding["id"]]},
                "is_active": True,
                "is_default": False,
            },
        ),
        201,
    )
    assert chat["config"]["paired_embedding_model_ids"] == [embedding["id"]]
    updated = _assert_ok(
        client.put(
            f"/api/v1/models/{chat['id']}",
            headers=headers,
            json={
                "provider": "generic_http",
                "endpoint": "http://127.0.0.1:65535/chat-updated",
                "api_key": "test-api-key",
                "config": {"paired_embedding_model_ids": [embedding["id"]], "timeout_seconds": 30},
            },
        )
    )
    assert updated["provider"] == "Custom"
    assert updated["api_key_configured"] is True
    assert updated["config_version"] == chat["config_version"] + 1
    paired_embedding_delete = client.request(
        "DELETE",
        f"/api/v1/models/{embedding['id']}",
        headers=headers,
        json={"confirmation_name": embedding["name"], "config_version": embedding["config_version"]},
    )
    assert paired_embedding_delete.status_code == 409
    assert paired_embedding_delete.json()["details"]["dependencies"] == [{"type": "active_chat_pairing", "count": 1}]
    tested = client.post(f"/api/v1/models/{chat['id']}/test", headers=headers)
    assert tested.status_code == 503
    assert tested.json()["code"] == "model_connection_failed"
    missing_update = client.put(f"/api/v1/models/{uuid4()}", headers=headers, json={"name": f"{TEST_PREFIX}-missing"})
    assert missing_update.status_code == 404
    missing_test = client.post(f"/api/v1/models/{uuid4()}/test", headers=headers)
    assert missing_test.status_code == 404
    deactivated_chat = _assert_ok(client.put(f"/api/v1/models/{chat['id']}", headers=headers, json={"is_active": False}))
    assert deactivated_chat["is_active"] is False
    reactivated_chat = _assert_ok(client.put(f"/api/v1/models/{chat['id']}", headers=headers, json={"is_active": True}))
    assert reactivated_chat["is_active"] is True
    wrong_confirmation = client.request(
        "DELETE",
        f"/api/v1/models/{chat['id']}",
        headers=headers,
        json={"confirmation_name": f"{chat['name']}-wrong", "config_version": reactivated_chat["config_version"]},
    )
    assert wrong_confirmation.status_code == 422
    stale_delete = client.request(
        "DELETE",
        f"/api/v1/models/{chat['id']}",
        headers=headers,
        json={"confirmation_name": chat["name"], "config_version": chat["config_version"]},
    )
    assert stale_delete.status_code == 409
    deleted_chat = _assert_ok(
        client.request(
            "DELETE",
            f"/api/v1/models/{chat['id']}",
            headers=headers,
            json={"confirmation_name": chat["name"], "config_version": reactivated_chat["config_version"]},
        )
    )
    assert deleted_chat["deleted_at"] is not None
    assert deleted_chat["api_key_configured"] is False
    assert all(row["id"] != chat["id"] for row in _assert_ok(client.get("/api/v1/models?limit=200", headers=headers)))
    assert client.put(f"/api/v1/models/{chat['id']}", headers=headers, json={"is_active": True}).status_code == 404
    recreated_chat = _assert_ok(
        client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "name": chat["name"],
                "model_type": "Chat",
                "provider": "custom",
                "endpoint": "http://127.0.0.1:65535/chat-recreated",
                "config": {"paired_embedding_model_ids": [embedding["id"]]},
                "is_active": False,
            },
        ),
        201,
    )
    assert recreated_chat["id"] != chat["id"]
    deleted_embedding = _assert_ok(
        client.request(
            "DELETE",
            f"/api/v1/models/{embedding['id']}",
            headers=headers,
            json={"confirmation_name": embedding["name"], "config_version": embedding["config_version"]},
        )
    )
    assert deleted_embedding["deleted_at"] is not None
    refreshed_models = _assert_ok(client.get("/api/v1/models?limit=200", headers=headers))
    refreshed_recreated_chat = next(row for row in refreshed_models if row["id"] == recreated_chat["id"])
    assert refreshed_recreated_chat["config"]["paired_embedding_model_ids"] == []

    ocr = _assert_ok(
        client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "name": f"{TEST_PREFIX}-route-ocr-{uuid4().hex[:8]}",
                "model_type": "OCR",
                "provider": "custom",
                "endpoint": "http://127.0.0.1:65535/ocr",
                "config": {"timeout_seconds": 10},
                "is_active": True,
                "is_default": False,
            },
        ),
        201,
    )
    deleted_ocr = _assert_ok(client.request("DELETE", f"/api/v1/models/{ocr['id']}", headers=headers, json={"confirmation_name": ocr["name"], "config_version": ocr["config_version"]}))
    assert deleted_ocr["id"] == ocr["id"]
    assert deleted_ocr["deleted_at"] is not None
    missing_delete = client.request("DELETE", f"/api/v1/models/{uuid4()}", headers=headers, json={"confirmation_name": "missing", "config_version": 1})
    assert missing_delete.status_code == 404

    assert model_routes._normalized_config(provider="OpenAI", model_type="Embedding", endpoint=None, config={"model_name": "text-embedding-live"}, has_credential=True)["embedding_dimension"] is None
    assert model_routes._normalized_config(provider="Gemini", model_type="Chat", endpoint=None, config={"model_name": "gemini-live"}, has_credential=True)["api_version"] == "v1beta"
    assert model_routes._normalized_config(provider="Claude", model_type="Chat", endpoint="http://127.0.0.1:65535/claude", config={"model_name": "claude-live"}, has_credential=True)["anthropic_version"] == "2023-06-01"
    assert model_routes._normalized_config(provider="Ollama", model_type="Chat", endpoint="http://127.0.0.1:11434", config={"model_name": "llama"}, has_credential=False)["timeout_seconds"] == 120
    assert model_routes._normalized_config(provider="vLLM", model_type="Chat", endpoint="http://127.0.0.1:8001/v1", config={"model_name": "served"}, has_credential=False)["openai_compatible"] is True
    assert model_routes._normalized_config(provider="custom-vendor", model_type="Chat", endpoint="http://127.0.0.1:65535/vendor", config={}, has_credential=False)["endpoint"].endswith("/vendor")
    with pytest.raises(AppError) as missing_credential:
        model_routes._normalized_config(provider="OpenAI", model_type="Chat", endpoint=None, config={"model_name": "gpt-live"}, has_credential=False)
    assert missing_credential.value.code == "model_credential_required"
    with pytest.raises(AppError) as missing_provider_config:
        model_routes._normalized_config(provider="Gemini", model_type="Chat", endpoint=None, config={}, has_credential=True)
    assert missing_provider_config.value.code == "model_provider_config_required"
    with pytest.raises(AppError) as missing_custom_endpoint:
        model_routes._normalized_config(provider="Custom", model_type="Chat", endpoint=None, config={}, has_credential=False)
    assert missing_custom_endpoint.value.code == "model_endpoint_required"
    with pytest.raises(AppError) as nested_secret:
        model_routes._normalized_config(provider="Custom", model_type="Chat", endpoint="http://127.0.0.1:65535/custom", config={"headers": [{"api_key": "bad"}]}, has_credential=False)
    assert nested_secret.value.code == "model_config_secret_not_allowed"

    with session_factory() as session:
        assert "paired_embedding_model_ids" not in model_routes._normalize_model_pairings(session=session, model_type="Embedding", config={"paired_embedding_model_ids": [embedding["id"]]}, require_chat_pairing=False)
        assert model_routes._normalize_model_pairings(session=session, model_type="Chat", config={}, require_chat_pairing=False)["paired_embedding_model_ids"] == []
        with pytest.raises(AppError) as non_list_pairing:
            model_routes._normalize_model_pairings(session=session, model_type="Chat", config={"paired_embedding_model_ids": "bad"}, require_chat_pairing=True)
        assert non_list_pairing.value.code == "invalid_model_pairing"
        with pytest.raises(AppError) as bad_pairing_id:
            model_routes._normalize_model_pairings(session=session, model_type="Chat", config={"paired_embedding_model_ids": ["bad"]}, require_chat_pairing=True)
        assert bad_pairing_id.value.code == "invalid_model_pairing"
        with pytest.raises(AppError) as missing_pairing:
            model_routes._normalize_model_pairings(session=session, model_type="Chat", config={"paired_embedding_model_ids": [uuid4()]}, require_chat_pairing=True)
        assert missing_pairing.value.code == "invalid_model_pairing"


def test_live_project_update_member_success_and_archive_routes(live_client) -> None:
    client, headers, user_id, role_id = live_client
    session_factory = get_session_factory()
    data = _seed_live_document_workspace(session_factory, user_id)
    project_id = UUID(data["project_id"])
    with session_factory() as session:
        member = User(
            employee_id=f"Z{uuid4().hex[:9]}",
            keycloak_user_id=f"{TEST_PREFIX}-project-member-{uuid4()}",
            email=f"{TEST_PREFIX}-project-member-{uuid4().hex[:8]}@example.test",
            display_name="Project Route Member",
            is_active=True,
            auth_source="keycloak",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(member)
        session.flush()
        member_id = member.id
        session.add(RoleUser(role_id=UUID(role_id), user_id=member.id, source="manual", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
        session.commit()

    project = _assert_ok(client.get(f"/api/v1/projects/{project_id}", headers=headers))
    updated = _assert_ok(
        client.put(
            f"/api/v1/projects/{project_id}",
            headers=headers,
            json={"lock_version": project["lock_version"], "name": f"{TEST_PREFIX} updated project", "description": "updated by live route test"},
        )
    )
    assert updated["name"].endswith("updated project")
    stale_update = client.put(
        f"/api/v1/projects/{project_id}",
        headers=headers,
        json={"lock_version": project["lock_version"], "description": "stale"},
    )
    assert stale_update.status_code == 409
    members = _assert_ok(
        client.put(
            f"/api/v1/projects/{project_id}/members/{member_id}",
            headers=headers,
            json={"lock_version": updated["lock_version"], "roles": ["viewer", "editor"]},
        )
    )
    assert any(item["user_id"] == str(member_id) and set(item["roles"]) == {"viewer", "editor"} for item in members)
    after_member = _assert_ok(client.get(f"/api/v1/projects/{project_id}", headers=headers))
    removed = _assert_ok(client.delete(f"/api/v1/projects/{project_id}/members/{member_id}?lock_version={after_member['lock_version']}", headers=headers))
    assert removed["lock_version"] == after_member["lock_version"] + 1
    impact = _assert_ok(client.get(f"/api/v1/projects/{project_id}/archive-impact", headers=headers))
    archived = _assert_ok(client.post(f"/api/v1/projects/{project_id}/archive", headers=headers, json={"lock_version": impact["lock_version"], "confirmation_name": impact["project_name"]}))
    assert archived["status"] == "archived"


def test_live_compatibility_routes_execute_governed_workflows(live_client) -> None:
    client, headers, user_id, _role_id = live_client
    session_factory = get_session_factory()
    data = _seed_live_document_workspace(session_factory, user_id)
    now = datetime.now(UTC)
    project_id = UUID(data["project_id"])
    document_id = UUID(data["document_id"])
    version_id = UUID(data["version_id"])
    review_document_id = UUID(data["review_document_id"])
    review_version_id = UUID(data["review_version_id"])
    actor_id = UUID(user_id)

    with session_factory() as session:
        review = ReviewRecord(
            project_id=project_id,
            document_id=review_document_id,
            document_version_id=review_version_id,
            review_stage="manager",
            reviewer_id=actor_id,
            status="approved",
            comment="Compatibility route evidence",
            created_at=now,
        )
        validation_run = ValidationRun(
            project_id=project_id,
            uploaded_file_name=f"{TEST_PREFIX}-compatibility.csv",
            status="running",
            run_scope="published",
            selected_document_ids=[str(document_id)],
            total_count=1,
            completed_count=0,
            failed_count=0,
            created_by=actor_id,
            started_at=now,
            created_at=now,
        )
        session.add_all([review, validation_run])
        session.flush()
        validation_item = ValidationRunItem(
            run_id=validation_run.id,
            question="Compatibility validation question",
            expected_answer="Compatibility answer",
            expected_keywords=["compatibility"],
            selected_document_ids=[str(document_id)],
            reference_docs=[],
            status="running",
            created_at=now,
        )
        validation_event = OutboxEvent(
            topic="validation.run.requested",
            aggregate_type="validation_run",
            aggregate_id=validation_run.id,
            payload={"run_id": str(validation_run.id)},
            status="pending",
            attempts=0,
            available_at=now,
            created_at=now,
        )
        approval = ApprovalRequest(
            project_id=project_id,
            document_id=review_document_id,
            document_version_id=review_version_id,
            submitter_id=actor_id,
            owner_user_id=actor_id,
            status="pending_manager_review",
            submitted_at=now,
            created_at=now,
        )
        session.add_all([validation_item, validation_event, approval])
        session.flush()
        approval_task = ApprovalTask(
            approval_request_id=approval.id,
            project_id=project_id,
            document_id=review_document_id,
            document_version_id=review_version_id,
            submitter_id=actor_id,
            assignee_user_id=actor_id,
            review_stage="manager",
            status="pending",
            submitted_at=now,
            created_at=now,
        )
        session.add(approval_task)
        session.flush()
        approval.current_task_id = approval_task.id
        review_version = session.get(DocumentVersion, review_version_id)
        assert review_version is not None
        review_version.status = "pending_manager_review"
        graph_job_id = session.scalar(
            select(GraphSyncJob.id).where(
                GraphSyncJob.project_id == project_id,
                GraphSyncJob.document_id == document_id,
                GraphSyncJob.document_version_id == version_id,
            )
        )
        review_id = review.id
        validation_run_id = validation_run.id
        approval_id = approval.id
        session.commit()

    assert graph_job_id is not None
    embedding = _assert_ok(client.get(f"/api/v1/projects/{project_id}/embedding-settings", headers=headers))
    assert embedding["project_id"] == str(project_id)
    untested_update = client.put(
        f"/api/v1/projects/{project_id}/embedding-settings",
        headers=headers,
        json={"embedding_model_id": embedding["embedding_model_id"], "lock_version": embedding["lock_version"]},
    )
    assert untested_update.status_code == 409
    assert untested_update.json()["code"] == "embedding_model_connection_test_required"

    versions = _assert_ok(client.get(f"/api/v1/documents/{document_id}/versions?limit=10", headers=headers))
    assert any(row["id"] == str(version_id) for row in versions)
    pipelines = _assert_ok(client.get(f"/api/v1/pipeline-runs?project_id={project_id}&status=completed", headers=headers))
    assert any(row["id"] == data["pipeline_id"] for row in pipelines)
    reviews = _assert_ok(client.get(f"/api/v1/review-records?project_id={project_id}&document_id={review_document_id}", headers=headers))
    assert any(row["id"] == str(review_id) for row in reviews)

    created_question = _assert_ok(
        client.post(
            "/api/v1/validation-questions",
            headers=headers,
            json={
                "project_id": str(project_id),
                "question": "  Is the compatibility endpoint live?  ",
                "expected_answer": "Yes",
                "expected_keywords": ["live"],
                "category": "compatibility",
                "priority": "high",
            },
        ),
        201,
    )
    questions = _assert_ok(client.get(f"/api/v1/validation-questions?project_id={project_id}", headers=headers))
    assert any(row["id"] == created_question["id"] for row in questions)

    cancelled_validation = _assert_ok(client.post(f"/api/v1/validation-runs/{validation_run_id}/cancel", headers=headers))
    assert cancelled_validation["status"] == "cancelled"
    assert cancelled_validation["cancelled_item_count"] == 1
    cancelled_approval = _assert_ok(client.post(f"/api/v1/approval-requests/{approval_id}/cancel", headers=headers))
    assert cancelled_approval["status"] == "cancelled"

    jobs = _assert_ok(client.get(f"/api/v1/graph-sync-jobs?project_id={project_id}&status=completed", headers=headers))
    assert any(row["id"] == str(graph_job_id) for row in jobs)
    completed_retry = _assert_ok(client.post(f"/api/v1/graph-sync-jobs/{graph_job_id}/retry", headers=headers))
    assert completed_retry["status"] == "completed"
    path = _assert_ok(
        client.get(
            f"/api/v1/projects/{project_id}/graph/paths?source_id={project_id}&target_id={document_id}&max_depth=3&node_limit=500",
            headers=headers,
        )
    )
    assert {str(project_id), str(document_id)}.issubset({node["id"] for node in path["nodes"]})


def test_live_permanent_chunk_deletion_is_version_scoped_and_blocks_zero_chunk_next_stage(live_client) -> None:
    client, headers, user_id, _role_id = live_client
    data = _seed_live_document_workspace(get_session_factory(), user_id)
    project_id = UUID(data["project_id"])
    document_id = UUID(data["review_document_id"])
    version_id = UUID(data["review_version_id"])
    actor_id = UUID(user_id)
    now = datetime.now(UTC)

    with get_session_factory()() as session:
        version = session.get(DocumentVersion, version_id)
        first_chunk = session.scalar(select(Chunk).where(Chunk.document_version_id == version_id, Chunk.status == "active"))
        assert version is not None and first_chunk is not None and version.embedding_profile_id is not None
        second_content = "Candidate-only chunk scheduled for permanent deletion."
        second_chunk = Chunk(
            project_id=project_id, document_id=document_id, document_version_id=version_id, chunk_index=2,
            title="Deletion candidate", content=second_content, markdown_content=second_content, content_type="text",
            content_hash=_sha256(second_content), start_offset=24, end_offset=24 + len(second_content),
            source_mapping=[{"source_anchor": "review-2", "start_offset": 24, "end_offset": 24 + len(second_content)}],
            chunk_strategy={"source": "manual"}, token_count=8, confidence_score=1, status="active",
            is_manual_edited=True, edited_by=actor_id, created_at=now, updated_at=now,
        )
        session.add(second_chunk)
        session.flush()
        unique_tag = Tag(project_id=project_id, name=f"{TEST_PREFIX}-delete-orphan-{uuid4().hex[:6]}", created_at=now)
        shared_tag = Tag(project_id=project_id, name=f"{TEST_PREFIX}-delete-shared-{uuid4().hex[:6]}", created_at=now)
        session.add_all([unique_tag, shared_tag])
        session.flush()
        session.add_all([
            ChunkTag(chunk_id=second_chunk.id, tag_id=unique_tag.id, source="manual", metadata_={}, created_by=actor_id, created_at=now),
            ChunkTag(chunk_id=second_chunk.id, tag_id=shared_tag.id, source="manual", metadata_={}, created_by=actor_id, created_at=now),
            ChunkTag(chunk_id=first_chunk.id, tag_id=shared_tag.id, source="manual", metadata_={}, created_by=actor_id, created_at=now),
        ])
        build = EmbeddingBuild(
            project_id=project_id, document_id=document_id, document_version_id=version_id,
            embedding_profile_id=version.embedding_profile_id, build_revision=1, status="completed", chunk_count=2,
            checksum=_sha256("delete-build"), content_fingerprint=_sha256("delete-fingerprint"),
            vector_dimension=3, token_count=11, usage={}, completed_at=now, created_at=now, updated_at=now,
        )
        session.add(build)
        session.flush()
        vector = EmbeddingBuildVector(
            embedding_build_id=build.id, chunk_id=second_chunk.id, chunk_index=2, vector=[0.1, 0.2, 0.3],
            vector_checksum=_sha256(json.dumps([0.1, 0.2, 0.3], separators=(",", ":"))), token_count=8, created_at=now,
        )
        session.add(vector)
        target_chat = ChatRecord(
            project_id=project_id, document_version_id=version_id, scope_mode="document_staging", conversation_id=uuid4(),
            conversation_title="Delete evidence", selected_document_version_ids=[str(version_id)], question="Delete?", answer="Candidate",
            reference_docs=[{"document_id": str(document_id), "document_version_id": str(version_id), "chunk_id": str(second_chunk.id)}],
            evaluation="not_evaluated", system_prompt_layers=[], created_by=actor_id, asked_at=now, answered_at=now, created_at=now,
        )
        session.add(target_chat)
        session.flush()
        validation = ValidationRun(
            project_id=project_id, status="completed", run_scope="document_staging", document_version_id=version_id,
            selected_document_ids=[str(version_id)], total_count=1, completed_count=1, failed_count=0,
            created_by=actor_id, started_at=now, completed_at=now, created_at=now,
        )
        session.add(validation)
        session.flush()
        validation_item = ValidationRunItem(
            run_id=validation.id, question="Delete?", selected_document_ids=[str(version_id)], answer="Candidate",
            reference_docs=[{"chunk_id": str(second_chunk.id)}], chat_record_id=target_chat.id, status="completed", created_at=now,
        )
        session.add(validation_item)
        session.commit()
        second_chunk_id = second_chunk.id
        first_chunk_id = first_chunk.id
        unique_tag_id = unique_tag.id
        shared_tag_id = shared_tag.id
        vector_id = vector.id
        target_chat_id = target_chat.id
        validation_item_id = validation_item.id

    detail = _assert_ok(client.get(f"/api/v1/projects/{project_id}/documents/{document_id}/knowledge", headers=headers))
    deleted = _assert_ok(client.delete(
        f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/{second_chunk_id}?lock_version={detail['version']['lock_version']}",
        headers=headers,
    ))
    assert deleted["active_chunk_count"] == 1
    assert deleted["chunk_artifact_status"] == "queued"
    assert deleted["next_stage_allowed"] is False

    with get_session_factory()() as session:
        assert session.get(Chunk, second_chunk_id) is None
        assert session.get(EmbeddingBuildVector, vector_id) is None
        assert session.get(Tag, unique_tag_id) is None
        assert session.get(Tag, shared_tag_id) is not None
        assert session.get(Chunk, first_chunk_id) is not None
        assert session.get(ChatRecord, target_chat_id) is None
        assert session.get(ValidationRunItem, validation_item_id) is None
        assert session.scalar(select(OutboxEvent).where(OutboxEvent.topic == "chunk.artifacts.reconcile", OutboxEvent.aggregate_id == version_id)) is not None

    with get_session_factory()() as session:
        with pytest.raises(AppError):
            chunk_artifacts.execute_chunk_artifact_reconciliation(session, version_id, get_settings())
    with get_session_factory()() as session:
        failed_version = session.get(DocumentVersion, version_id)
        assert failed_version is not None
        assert failed_version.chunk_strategy["chunk_artifacts"]["status"] == "failed"

    repeated = client.delete(
        f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/{second_chunk_id}?lock_version={detail['version']['lock_version']}",
        headers=headers,
    )
    assert repeated.status_code == 404
    assert repeated.json()["code"] == "chunk_not_found"

    zero = _assert_ok(client.delete(
        f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/chunks/{first_chunk_id}?lock_version={deleted['version']['lock_version']}",
        headers=headers,
    ))
    assert zero["active_chunk_count"] == 0
    assert zero["chunk_artifact_status"] == "chunks_required"
    assert zero["next_stage_block_reason"] == "chunks_required"
    chat_denied = client.post(
        f"/api/v1/projects/{project_id}/chat/query", headers=headers,
        json={"scope_mode": "document_staging", "question": "Blocked", "document_version_ids": [str(version_id)]},
    )
    assert chat_denied.status_code == 409
    assert chat_denied.json()["code"] == "chunks_required"
    denied_evidence = _assert_ok(client.get(
        f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/submission-evidence",
        headers=headers,
    ))
    review_denied = client.post(
        f"/api/v1/projects/{project_id}/documents/{document_id}/versions/{version_id}/submit-review",
        headers={**headers, "Idempotency-Key": f"{TEST_PREFIX}-chunks-required"},
        json={"owner_user_id": user_id, "evidence_revision": denied_evidence["evidence_revision"], "lock_version": denied_evidence["lock_version"]},
    )
    assert review_denied.status_code == 409
    assert review_denied.json()["code"] == "submission_evidence_not_ready"
    with get_session_factory()() as session:
        chunk_artifacts.execute_chunk_artifact_reconciliation(session, version_id, get_settings())
    with get_session_factory()() as session:
        reconciled = session.get(DocumentVersion, version_id)
        assert reconciled is not None
        assert reconciled.extraction_artifact_uri is None
        assert reconciled.embedding_profile_id is None
        assert reconciled.chunk_strategy["chunk_artifacts"]["status"] == "chunks_required"
