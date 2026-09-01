from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.schemas import ProjectChatCitation, PublicApiChatResponse
from app.core.errors import AppError
from app.db.models import Chunk, Document, DocumentVersion, Project, User
from app.db.session import get_session_factory
from app.domain.chat_citations import citation_persistence_payload, hydrate_citation_groups, validate_citation_markers


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_marker_validation_preserves_valid_ordinals_and_rejects_out_of_range() -> None:
    validate_citation_markers("Grounded in [1], [3], and [5].", 5)
    validate_citation_markers("A valid answer without markers.", 0)

    with pytest.raises(AppError) as captured:
        validate_citation_markers("Invalid [0] and [6].", 5)

    assert captured.value.code == "provider_response_contract_invalid"
    assert captured.value.status_code == 502
    assert captured.value.details == {
        "citation_count": 5,
        "invalid_source_ordinals": [0, 6],
    }


def test_public_api_citation_shape_does_not_expose_internal_chunk_index() -> None:
    citation = ProjectChatCitation(
        document_id=uuid4(),
        document_version_id=uuid4(),
        chunk_id=uuid4(),
        chunk_index=37,
        title="Legacy title",
        excerpt="Canonical content",
    )
    response = PublicApiChatResponse(response_id=uuid4(), answer="Answer [1]", citations=[citation])

    assert "chunk_index" not in response.citations[0].model_dump()


def test_citation_persistence_payload_excludes_transient_display_bodies() -> None:
    citation = ProjectChatCitation(
        document_id=uuid4(),
        document_version_id=uuid4(),
        chunk_id=uuid4(),
        title="Authorized source",
        excerpt="Compact preview",
        generation_text="Generation body",
        raw_markdown="**Raw body**",
    )
    # CHG-283 adds display_markdown to the response model; model_copy keeps this
    # test compatible until the additive field is present in the shared schema.
    if "display_markdown" in ProjectChatCitation.model_fields:
        citation = citation.model_copy(update={"display_markdown": "**Display body**"})

    payload = citation_persistence_payload(citation)

    assert payload["excerpt"] == "Compact preview"
    assert "display_markdown" not in payload
    assert "generation_text" not in payload
    assert "raw_markdown" not in payload


def test_query_and_validation_paths_validate_before_persisting_success() -> None:
    serving = (BACKEND_ROOT / "app/api/routes/serving.py").read_text(encoding="utf-8")
    validation = (BACKEND_ROOT / "app/domain/validation_runner.py").read_text(encoding="utf-8")

    query_body = serving.split("def query_project_chat", 1)[1].split("@router.get", 1)[0]
    validation_body = validation.split("def _execute_item", 1)[1].split("def _score_answer", 1)[0]
    assert query_body.index("validate_citation_markers") < query_body.index("record = ChatRecord(")
    assert validation_body.index("validate_citation_markers") < validation_body.index("record = ChatRecord(")
    assert "token_usage=provider_result.token_usage if provider_result is not None else None" in query_body
    assert "token_usage=provider_result.token_usage if provider_result is not None else None" in validation_body
    assert "chunk_index=chunk.chunk_index" in serving


def test_real_postgresql_hydrates_legacy_citations_once_without_mutating_json() -> None:
    session_factory = get_session_factory()
    now = datetime.now(UTC)
    user_id = uuid4()
    project_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    chunk_id = uuid4()

    with session_factory() as session:
        user = User(
            id=user_id,
            employee_id=f"Z275{user_id.hex[:6]}",
            keycloak_user_id=f"chg275-{user_id}",
            email=f"chg275-{user_id}@example.test",
            display_name="CHG-275 Citation Tester",
            auth_source="keycloak",
            is_active=True,
        )
        project = Project(
            id=project_id,
            name=f"CHG-275 {project_id.hex[:12]}",
            status="active",
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        session.flush([user])
        session.add(project)
        session.flush([project])
        document = Document(
            id=document_id,
            project_id=project_id,
            document_code=f"CHG275-{document_id.hex[:10]}",
            title="Legacy repeated document title #36",
            source_type="upload",
            status="active",
            is_deleted=False,
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(document)
        session.flush([document])
        version = DocumentVersion(
            id=version_id,
            project_id=project_id,
            document_id=document_id,
            version_major=1,
            extraction_revision=0,
            version_label="v1.0",
            status="submission_ready",
            created_at=now,
            updated_at=now,
        )
        session.add(version)
        session.flush([version])
        content = "Canonical Chunk content for CHG-275"
        chunk = Chunk(
            id=chunk_id,
            project_id=project_id,
            document_id=document_id,
            document_version_id=version_id,
            chunk_index=37,
            title="Legacy repeated document title #36",
            content=content,
            markdown_content=content,
            content_type="text",
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_mapping=[],
            chunk_strategy={"source": "chg275-real-db"},
            status="active",
            is_manual_edited=False,
            created_at=now,
            updated_at=now,
        )
        session.add(chunk)
        session.flush([chunk])

        legacy = {
            "document_id": str(document_id),
            "document_version_id": str(version_id),
            "chunk_id": str(chunk_id),
            "title": "Legacy repeated document title #36",
            "excerpt": content,
        }
        mismatched = {**legacy, "document_version_id": str(uuid4())}
        statements: list[str] = []
        bind = session.get_bind()

        def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(bind, "before_cursor_execute", capture_statement)
        try:
            hydrated = hydrate_citation_groups(
                session,
                [[legacy], [mismatched]],
                project_id=project_id,
                allowed_version_ids={version_id},
            )
        finally:
            event.remove(bind, "before_cursor_execute", capture_statement)

        chunk_selects = [statement for statement in statements if "FROM chunks" in statement]
        assert len(chunk_selects) == 1
        assert hydrated[0][0]["chunk_index"] == 37
        assert "chunk_index" not in hydrated[1][0]
        assert "chunk_index" not in legacy
        assert hydrated[0][0]["title"] == legacy["title"]
        session.rollback()
