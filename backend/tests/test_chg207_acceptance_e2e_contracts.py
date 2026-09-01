from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_live_acceptance_embedding_provider_is_supported_or_blocked() -> None:
    milestone7 = read("backend/scripts/milestone7_live_acceptance.py")
    milestone8b = read("backend/scripts/milestone8b_live_acceptance.py")

    assert 'provider="acceptance"' not in milestone7
    assert "SUPPORTED_LIVE_EMBEDDING_PROVIDERS" in milestone7
    assert '{"openai", "vllm", "custom"}' in milestone7
    assert "MILESTONE_LIVE_EMBEDDING_PROVIDER" in milestone7
    assert "MILESTONE_LIVE_EMBEDDING_API_KEY" in milestone7
    assert "LiveAcceptanceBlocked" in milestone7
    assert "_existing_supported_embedding_model" in milestone7
    assert "api_key_encrypted" in milestone7
    assert "_seed_publish_fixture(session, run_id, settings=settings)" in milestone8b


def test_project_serving_status_exposes_active_manifest_chunk_count() -> None:
    schemas = read("backend/app/api/schemas.py")
    serving = read("backend/app/api/routes/serving.py")
    api = read("frontend/src/lib/api.ts")
    project_chat = read("frontend/src/components/ProjectChatTest.tsx")

    assert "chunk_count: int = 0" in schemas
    assert "chunk_count: number;" in api
    assert "def _serving_manifest_chunk_count" in serving
    assert "session.get(EmbeddingBuild, manifest.embedding_build_id)" in serving
    assert "select(func.count(Chunk.id))" in serving
    assert "chunk_count=chunk_count" in serving
    assert "chunks: servingDocument?.chunk_count ?? 0" in project_chat
