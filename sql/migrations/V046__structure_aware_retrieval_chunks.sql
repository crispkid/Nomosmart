BEGIN;

ALTER TABLE chunks
    ADD COLUMN retrieval_text text,
    ADD COLUMN embedding_content_hash varchar(64),
    ADD COLUMN heading_path jsonb,
    ADD COLUMN heading_level integer,
    ADD COLUMN page_start integer,
    ADD COLUMN page_end integer,
    ADD COLUMN sequence integer,
    ADD COLUMN stable_chunk_key varchar(64);

ALTER TABLE chunks
    ADD CONSTRAINT ck_chunks_heading_path_array
        CHECK (heading_path IS NULL OR jsonb_typeof(heading_path) = 'array'),
    ADD CONSTRAINT ck_chunks_page_range
        CHECK (page_start IS NULL OR page_end IS NULL OR page_end >= page_start),
    ADD CONSTRAINT ck_chunks_sequence_positive
        CHECK (sequence IS NULL OR sequence > 0),
    ADD CONSTRAINT ck_chunks_embedding_content_hash_length
        CHECK (embedding_content_hash IS NULL OR length(embedding_content_hash) = 64),
    ADD CONSTRAINT ck_chunks_stable_chunk_key_length
        CHECK (stable_chunk_key IS NULL OR length(stable_chunk_key) = 64);

CREATE INDEX ix_chunks_version_stable_key
    ON chunks (document_version_id, stable_chunk_key)
    WHERE stable_chunk_key IS NOT NULL;

CREATE INDEX ix_chunks_version_sequence
    ON chunks (document_version_id, sequence)
    WHERE sequence IS NOT NULL;

COMMENT ON COLUMN chunks.content IS
    'Backward-compatible display_text used for UI, citations and bounded LLM context.';
COMMENT ON COLUMN chunks.markdown_content IS
    'Exact canonical Markdown fragment for structure-aware chunks; legacy rows may contain synthetic Markdown.';
COMMENT ON COLUMN chunks.retrieval_text IS
    'Normalized contextual text used for embedding, BM25 and hybrid retrieval.';
COMMENT ON COLUMN chunks.embedding_content_hash IS
    'Versioned preprocessing hash; final embedding fingerprint additionally binds model profile metadata.';

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg281.structure_aware_retrieval_chunks',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-281', 'migration', 'V046', 'data_reprocessed', false),
    now()
);

COMMIT;
