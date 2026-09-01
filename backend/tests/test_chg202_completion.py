from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_upload_goes_directly_to_canonical_storage_without_scanner_chain() -> None:
    config = read("backend/app/core/config.py")
    imports = read("backend/app/domain/document_imports.py")
    pipeline = read("backend/app/domain/extraction_pipeline.py")
    worker = read("backend/app/worker.py")
    system = read("backend/app/api/routes/system.py")

    assert 'AliasChoices("NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB", "MAX_UPLOAD_SIZE_MB")' in config
    assert not (ROOT / "backend/app/domain/scanner.py").exists()
    assert not (ROOT / "backend/app/domain/scan_worker.py").exists()
    assert 'topic="file.scan.requested"' not in imports
    assert "s3_quarantine_bucket" not in imports
    assert 'status="ready_for_extraction"' in imports
    assert "queue_document_extraction(" in imports
    assert "file.scan.requested" not in worker
    assert "assert_scan_allows_extraction" not in pipeline
    assert '@router.get("/upload-config", response_model=UploadConfigResponse)' in system


def test_project_graph_serving_uses_formal_five_node_model() -> None:
    serving = read("backend/app/api/routes/serving.py")
    graph = read("frontend/src/components/ProjectGraphPreview.tsx")
    project_graph_source = serving

    assert 'type="Project"' in project_graph_source
    assert 'type="Document"' in project_graph_source
    assert 'type="Chunk"' in project_graph_source
    assert 'type="Tag"' in project_graph_source
    assert 'type="DocumentVersion"' in project_graph_source
    assert '"PROJECT_HAS_DOCUMENT"' in project_graph_source
    assert '"DOCUMENT_HAS_VERSION"' in project_graph_source
    assert '"VERSION_HAS_CHUNK"' in project_graph_source
    assert '"CHUNK_HAS_TAG"' in project_graph_source
    assert '"VERSION_HAS_TAG"' in project_graph_source
    assert '"document_version_ids"' in project_graph_source
    assert "def _uuid_or_none" in serving
    assert 'filter((node) => !node.type.toLowerCase().includes("version"))' in graph
    assert "projectDocumentSources" in graph
    assert "versionToDocument" in graph


def test_graph_surfaces_are_project_scoped_and_unscoped_routes_are_absent() -> None:
    serving = read("backend/app/api/routes/serving.py")
    graph = read("frontend/src/components/ProjectGraphPreview.tsx")
    api = read("frontend/src/lib/api.ts")
    explorer = read("frontend/src/components/GraphExplorer.tsx")

    assert '@router.get("/knowledge-graph"' not in serving
    assert '@router.get("/knowledge-graph/neighbors"' not in serving
    assert '@router.get("/knowledge-graph/paths"' not in serving
    assert '@router.get("/projects/{project_id}/graph", response_model=ProjectGraphResponse)' in serving
    assert '@router.get("/projects/{project_id}/graph/neighbors", response_model=ProjectGraphResponse)' in serving
    assert '@router.get("/projects/{project_id}/graph/paths", response_model=ProjectGraphResponse)' in serving
    assert '"/projects/{project_id}/documents/{document_id}/versions/{version_id}/graph"' in serving
    assert "graph = _project_graph_without_chunk_content(" in serving
    assert "return _hydrate_graph_chunk_content(session, graph, project.id, active_ids)" in serving
    assert "_get_scoped_project(session, project_id, context)" in serving
    assert "def _neighbor_graph" in serving
    assert "_filter_graph_edges" in serving
    assert "node_limit: int = Query(default=80, ge=10, le=200)" in serving

    assert "getProjectGraphNeighbors" in graph
    assert "getKnowledgeGraphNeighbors" not in graph
    assert "mergeProjectGraphs" in graph
    assert "onNodeSelect={expandNeighborGraph}" in graph
    assert "getKnowledgeGraph" not in api
    assert "`/knowledge-graph" not in api
    assert "`/projects/${projectId}/graph/neighbors?" in api
    assert "`/projects/${projectId}/graph/paths?" in api
    assert "`/projects/${projectId}/documents/${documentId}/versions/${versionId}/graph?" in api
    assert "onNodeSelect?.(node.id)" in explorer
