from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.api.schemas import ProjectChatCitation
from app.db.models import Chunk
from app.domain.chat_citations import (
    chunk_display_markdown,
    citation_persistence_payload,
    hydrate_citation_groups,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_display_projection_priority_never_uses_retrieval_text() -> None:
    chunk = Chunk(
        content="Display text",
        markdown_content="**Raw Markdown**",
        display_markdown="**Chunk display Markdown**",
        retrieval_text="RETRIEVAL-ONLY SENTINEL",
    )
    assert chunk_display_markdown(chunk) == "**Chunk display Markdown**"

    chunk.display_markdown = None
    assert chunk_display_markdown(chunk) == "**Raw Markdown**"

    chunk.display_markdown = "  \n"
    assert chunk_display_markdown(chunk) == "**Raw Markdown**"

    chunk.markdown_content = None
    assert chunk_display_markdown(chunk) == "Display text"
    assert chunk_display_markdown(chunk) != chunk.retrieval_text


def test_authorized_response_field_is_removed_from_persistence_payload() -> None:
    citation = ProjectChatCitation(
        document_id=uuid4(),
        document_version_id=uuid4(),
        chunk_id=uuid4(),
        excerpt="Compact preview",
        display_markdown="**Authorized full Markdown**",
        generation_text="LLM context",
        raw_markdown="**Exact raw source**",
    )

    assert citation.model_dump(mode="json")["display_markdown"] == "**Authorized full Markdown**"
    persisted = citation_persistence_payload(citation)
    assert persisted["excerpt"] == "Compact preview"
    assert "display_markdown" not in persisted
    assert "generation_text" not in persisted
    assert "raw_markdown" not in persisted


def test_empty_authorized_scope_fails_closed_for_legacy_transient_bodies() -> None:
    legacy = {
        "document_id": str(uuid4()),
        "document_version_id": str(uuid4()),
        "chunk_id": str(uuid4()),
        "excerpt": "Compact preview",
        "display_markdown": "must not leak",
        "generation_text": "must not leak",
        "raw_markdown": "must not leak",
        "markdown_content": "must not leak",
        "content": "must not leak",
        "retrieval_text": "must not leak",
        "unexpected": "must not leak",
    }

    with Session() as session:
        hydrated = hydrate_citation_groups(
            session,
            [[legacy]],
            project_id=uuid4(),
            allowed_version_ids=set(),
        )

    assert hydrated == [[{
        "document_id": legacy["document_id"],
        "document_version_id": legacy["document_version_id"],
        "chunk_id": legacy["chunk_id"],
        "excerpt": "Compact preview",
    }]]
    assert legacy["display_markdown"] == "must not leak"


def test_persistence_payload_is_an_explicit_compact_allowlist() -> None:
    persisted = citation_persistence_payload({
        "document_id": str(uuid4()),
        "document_version_id": str(uuid4()),
        "chunk_id": str(uuid4()),
        "excerpt": "Compact preview",
        "content": "must not persist",
        "markdown_content": "must not persist",
        "retrieval_text": "must not persist",
        "unexpected": "must not persist",
    })

    assert persisted["excerpt"] == "Compact preview"
    assert set(persisted) == {"document_id", "document_version_id", "chunk_id", "excerpt"}


def test_graph_hydration_uses_only_authorized_display_sources() -> None:
    source = (BACKEND_ROOT / "app/api/routes/serving.py").read_text(encoding="utf-8")
    body = source.split("def _hydrate_graph_chunk_content(", 1)[1].split("def _enrich_graph_tags(", 1)[0]

    assert "Chunk.project_id == project_id" in body
    assert "Chunk.document_version_id.in_(version_ids)" in body
    assert 'Chunk.status == "active"' in body
    assert "expected_versions.get(chunk_id) != version_id" in body
    assert "Chunk.markdown_content" in body
    assert "Chunk.display_markdown" in body
    assert '"retrieval_text"' in body
    assert "Chunk.retrieval_text" not in body


def test_new_approval_snapshot_carries_display_but_citation_artifacts_stay_compact() -> None:
    approvals = (BACKEND_ROOT / "app/api/routes/approvals.py").read_text(encoding="utf-8")
    evidence = (BACKEND_ROOT / "app/domain/submission_evidence.py").read_text(encoding="utf-8")

    assert 'display_markdown=item.get("display_markdown")' in approvals
    assert "display_markdown=chunk.display_markdown" in approvals
    assert '"display_markdown": chunk.display_markdown' in evidence
    assert evidence.count("citation_persistence_payload(citation)") >= 4
