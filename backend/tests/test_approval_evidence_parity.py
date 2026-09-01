from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_approval_detail_exposes_readonly_knowledge_evidence() -> None:
    schemas = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    route = (ROOT / "backend" / "app" / "api" / "routes" / "approvals.py").read_text(encoding="utf-8")

    for field in [
        'original_file: "OriginalFileViewerMetadata | None" = None',
        'document_layout: "DocumentLayoutArtifact | None" = None',
        "source_text: str | None = None",
        "markdown_text: str | None = None",
        'markdown_artifact_status: Literal["available", "processing", "missing", "failed", "invalid"]',
        "markdown_artifact_reason_code: str | None = None",
        "source_mapping_available: bool = False",
        "markdown_available_count: int = 0",
        "missing_markdown_count: int = 0",
        "document_tags: list[KnowledgeTagResponse]",
    ]:
        assert field in schemas

    for helper in [
        "_original_file_metadata(document.project_id, document.id, version)",
        "_document_layout(version)",
        "_source_text(version, chunks)",
        "resolve_markdown_artifact(session, version)",
        "markdown_text=markdown_artifact.text",
        "_document_tag_details(session, version.id)",
        "Chunk.status == \"active\"",
        "tag_details = _chunk_tag_details(session, chunk.id)",
    ]:
        assert helper in route


def test_approval_detail_does_not_fabricate_original_from_chunk_text() -> None:
    route = (ROOT / "backend" / "app" / "api" / "routes" / "approvals.py").read_text(encoding="utf-8")
    source_text_helper = route.split("def _source_text", 1)[1].split("def _markdown_text", 1)[0]

    assert "source_text = strategy.get(\"source_text\")" in source_text_helper
    assert "join(chunk.content" not in source_text_helper
