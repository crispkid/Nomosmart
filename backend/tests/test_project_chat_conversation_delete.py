from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_project_chat_conversation_delete_is_soft_delete_contract() -> None:
    models = (ROOT / "backend" / "app" / "db" / "models.py").read_text(encoding="utf-8")
    schemas = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    serving = (ROOT / "backend" / "app" / "api" / "routes" / "serving.py").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "V015__chat_conversation_soft_delete.sql").read_text(encoding="utf-8")

    assert "deleted_at: Mapped[datetime | None]" in models
    assert "deleted_by: Mapped[UUID | None]" in models
    assert "ADD COLUMN IF NOT EXISTS deleted_at" in migration
    assert "ADD COLUMN IF NOT EXISTS deleted_by" in migration
    assert "class ProjectChatConversationDeleteResponse" in schemas
    assert '@router.delete("/projects/{project_id}/chat/conversations/{conversation_id}"' in serving
    assert "ChatRecord.deleted_at.is_(None)" in serving
    assert "record.deleted_at = deleted_at" in serving
    assert "record.deleted_by = context.user_id" in serving
    assert "project_chat.conversation.delete" in serving
    assert "delete(ChatRecord)" not in serving
