from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_graph_endpoints_hydrate_only_after_visible_graph_selection() -> None:
    source = (ROOT / "backend/app/api/routes/serving.py").read_text(encoding="utf-8")

    assert "def _hydrate_graph_chunk_content(" in source
    assert "Chunk.id.in_(eligible_ids)" in source
    assert "Chunk.project_id == project_id" in source
    assert "Chunk.document_version_id.in_(version_ids)" in source
    assert 'Chunk.status == "active"' in source
    assert 'if key not in {"chunk_index", "content", "markdown_content", "display_markdown", "retrieval_text"}' in source
    assert "Chunk.markdown_content" in source
    assert "Chunk.display_markdown" in source
    assert "expected_versions.get(chunk_id) != version_id" in source
    assert "neighbor_graph = _neighbor_graph(graph, node_id, node_limit)" in source
    assert "_hydrate_graph_chunk_content(session, neighbor_graph, project.id, active_ids)" in source
    assert "path_graph = ProjectGraphResponse(" in source
    assert "_hydrate_graph_chunk_content(session, path_graph, project.id, active_ids)" in source


def test_graph_storage_contract_does_not_copy_content_to_neo4j() -> None:
    serving = (ROOT / "backend/app/api/routes/serving.py").read_text(encoding="utf-8")
    publishing = (ROOT / "backend/app/domain/review_publish.py").read_text(encoding="utf-8")

    neo4j_reader = serving.split("def _read_neo4j_project_graph", 1)[1]
    assert '"content": chunk.get("content")' not in neo4j_reader
    assert "content: chunk.content" not in publishing
    assert "c.content =" not in publishing
    assert "content = $content" not in publishing
