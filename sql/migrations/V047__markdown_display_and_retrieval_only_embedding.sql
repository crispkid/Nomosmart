BEGIN;

ALTER TABLE chunks
    ADD COLUMN display_markdown text;

COMMENT ON COLUMN chunks.display_markdown IS
    'Deterministic Chunk-specific Markdown display projection; never an embedding or BM25 input.';

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg283.markdown_display_and_retrieval_only_embedding',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-283', 'migration', 'V047', 'data_reprocessed', false),
    now()
);

COMMIT;
