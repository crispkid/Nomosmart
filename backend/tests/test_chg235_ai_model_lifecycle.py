from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_chg235_migration_uses_tombstones_and_partial_uniqueness() -> None:
    migration = read("sql/migrations/V029__ai_model_soft_delete.sql")
    assert "ADD COLUMN deleted_at timestamptz" in migration
    assert "ADD COLUMN deleted_by uuid REFERENCES users(id)" in migration
    assert "DROP CONSTRAINT ai_models_name_model_type_key" in migration
    assert "CREATE UNIQUE INDEX uq_ai_models_active_name_type" in migration
    assert "WHERE deleted_at IS NULL" in migration
    assert "DELETE FROM ai_models" not in migration


def test_chg235_list_contract_preserves_array_and_filtered_total() -> None:
    route = read("backend/app/api/routes/models.py")
    assert '@router.get("", response_model=list[AIModelResponse])' in route
    assert 'response.headers["X-Total-Count"] = str(total)' in route
    assert "AIModel.deleted_at.is_(None)" in route
    assert ".order_by(AIModel.model_type, AIModel.name, AIModel.id)" in route
    assert 'raise AppError("invalid_model_type"' in route


def test_chg235_delete_is_separate_from_disable_and_redacts_credentials() -> None:
    route = read("backend/app/api/routes/models.py")
    assert "payload: AIModelDeleteRequest" in route
    assert ".with_for_update()" in route
    assert "model.deleted_at = datetime.now(UTC)" in route
    assert "model.deleted_by = context.user_id" in route
    assert "model.api_key_encrypted = None" in route
    assert "model.api_key_secret_ref = None" in route
    assert "session.delete(model)" not in route
    assert 'action="ai_model.delete"' in route
    assert 'details={"dependencies": dependencies}' in route
    assert 'changes["is_default"] = False' in route


def test_chg235_normal_runtime_selectors_reject_tombstones() -> None:
    for path in (
        "backend/app/domain/project_access.py",
        "backend/app/domain/document_imports.py",
        "backend/app/domain/embeddings.py",
        "backend/app/domain/validation_runner.py",
        "backend/app/api/routes/serving.py",
        "backend/app/api/routes/system_prompts.py",
    ):
        assert "deleted_at" in read(path), f"{path} must exclude deleted models from new work"


def test_live_cleanup_removes_model_usage_before_referenced_pipeline_rows() -> None:
    cleanup = read("backend/scripts/cleanup_test_data.py")
    usage_delete = cleanup.index("        AIModelUsageEvent,", cleanup.index("def _delete_scope"))
    pipeline_step_delete = cleanup.index("_delete(deleted, session, PipelineRunStep", usage_delete)
    assert usage_delete < pipeline_step_delete
    assert 'counts["ai_model_usage_events"]' in cleanup
