from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_api_tables_and_models_are_traceable() -> None:
    models = read("backend/app/db/models.py")
    migration = read("sql/migrations/V019__public_api_integration_clients.sql")

    for name in (
        "class IntegrationClient",
        "class IntegrationClientProjectScope",
        "class PublicApiRequestLog",
        "class ChatFeedbackEvent",
    ):
        assert name in models

    for table in (
        "CREATE TABLE IF NOT EXISTS integration_clients",
        "CREATE TABLE IF NOT EXISTS integration_client_project_scopes",
        "CREATE TABLE IF NOT EXISTS public_api_request_logs",
        "CREATE TABLE IF NOT EXISTS chat_feedback_events",
    ):
        assert table in migration

    assert "api_key_hash" in models
    assert "api_key_hash" in migration
    assert "api_key_prefix" in migration
    assert "feedback_value" in migration


def test_integration_client_key_lifecycle_stores_hash_and_shows_plaintext_once() -> None:
    helper = read("backend/app/domain/integration_api_keys.py")
    route = read("backend/app/api/routes/integration_clients.py")

    assert "hashlib.sha256" in helper
    assert "secrets.token_urlsafe" in helper
    assert "api_key_hash=token_hash" in route
    assert "api_key=token" in route
    assert "client.api_key_hash = token_hash" in route
    assert "Revoked API keys cannot be reactivated" in route
    assert 'status IN (\'active\', \'inactive\', \'revoked\')' in read("sql/migrations/V019__public_api_integration_clients.sql")


def test_public_api_uses_manifest_scope_system_prompt_and_citation_logging() -> None:
    route = read("backend/app/api/routes/public_api.py")

    assert "get_public_integration_client" in route
    assert "authorization.lower().startswith(\"bearer \")" in route
    assert "x-nomosmart-api-key" in route
    assert "_active_retrieval_manifest_query(project_id)" in route
    assert "ActiveVersionManifest.document_id.in_" in route
    assert "_search_published_chunks" in route
    assert "_generate_citation_bound_answer" in route
    assert "system_prompt_layers=provider_result.system_prompt_layers" in route
    assert 'citations_encrypted=encrypt_payload' in route
    assert 'lifecycle_status="streaming"' in route
    assert 'Idempotency-Key' in route
    assert "PublicApiRequestLog(" in route
    assert "StreamingResponse" in route


def test_feedback_is_append_only_for_ui_and_public_api() -> None:
    serving = read("backend/app/api/routes/serving.py")
    public_route = read("backend/app/api/routes/public_api.py")

    assert "ChatFeedbackEvent(" in serving
    assert "source=\"ui\"" in serving
    assert "feedback_value=payload.evaluation" in serving
    assert "ChatFeedbackEvent(" in public_route
    assert "source=\"api\"" in public_route
    assert "feedback_value=payload.feedback" in public_route
