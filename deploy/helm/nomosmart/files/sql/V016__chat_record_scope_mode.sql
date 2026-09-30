ALTER TABLE chat_records
    ADD COLUMN IF NOT EXISTS scope_mode varchar(32);

CREATE INDEX IF NOT EXISTS idx_chat_records_scope_history
    ON chat_records (project_id, created_by, scope_mode, conversation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_chat_records_document_scope
    ON chat_records (project_id, document_version_id, scope_mode, asked_at);
