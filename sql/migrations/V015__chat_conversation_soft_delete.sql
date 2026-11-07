ALTER TABLE chat_records
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
    ADD COLUMN IF NOT EXISTS deleted_by uuid NULL REFERENCES users(id);

CREATE INDEX IF NOT EXISTS idx_chat_records_visible_conversation
    ON chat_records(project_id, created_by, conversation_id, created_at DESC)
    WHERE deleted_at IS NULL;
