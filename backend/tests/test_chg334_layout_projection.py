"""Native projection contracts; no service/provider success is synthesized."""
from copy import deepcopy

import pytest

from app.api.routes import approvals, documents
from app.db.models import DocumentVersion
from app.domain.document_layout import build_document_layout, project_document_layout
from app.domain.markdown_structure import MarkdownStructureParser


@pytest.mark.parametrize("strategy,status,reason", [
    (None, "missing", "layout_artifact_missing"),
    ({}, "missing", "layout_artifact_missing"),
    ({"source_text": "   "}, "missing", "layout_artifact_missing"),
    ({"document_layout": {"status": "invalid"}}, "failed", "layout_invalid"),
    ({"document_layout": {"status": "available", "pages": []}}, "available", None),
])
def test_layout_status_and_route_aliases(strategy, status, reason):
    version = DocumentVersion(chunk_strategy=strategy)
    assert documents._document_layout is approvals._document_layout is project_document_layout
    result = project_document_layout(version)
    assert result.status == status
    assert result.reason_code == reason


def test_real_schema_preserves_source_text_projection():
    version = DocumentVersion(chunk_strategy={"source_text": "## Heading\n\nBody 🚀\n\n- One\n- Two"})
    result = project_document_layout(version)
    assert result.source == "uploaded_text_snapshot"
    page = result.pages[0]
    assert (page.page_number, page.width, page.height) == (1, 794, 1123)
    assert [(block.type, block.source_anchor) for block in page.blocks] == [("heading", "paragraph-1"), ("paragraph", "paragraph-2"), ("list", "paragraph-3")]
    assert page.blocks[0].level == 2
    assert page.blocks[1].text == "Body 🚀"
    assert page.blocks[2].items == ["One", "Two"]


def test_native_parser_hydration_is_lossless_and_does_not_mutate_saved_artifact():
    source = "# Heading\n\n**Evidence** and `code`\n\n1. One\n2. Two"
    artifact = build_document_layout(MarkdownStructureParser().parse(source))
    original = deepcopy(artifact)
    version = DocumentVersion(chunk_strategy={"document_layout": artifact})
    result = project_document_layout(version, source)
    assert result.status == "available"
    assert artifact == original
    assert any(block.type == "list" for page in result.pages for block in page.blocks)
    assert approvals._document_layout(version, source).model_dump() == documents._document_layout(version, source).model_dump()
