BEGIN;

ALTER TABLE chunks
    ADD COLUMN lineage_id uuid,
    ADD COLUMN parent_chunk_id uuid REFERENCES chunks(id),
    ADD COLUMN revision integer NOT NULL DEFAULT 0,
    ADD COLUMN change_type varchar(32) NOT NULL DEFAULT 'generated',
    ADD COLUMN superseded_at timestamptz,
    ADD COLUMN superseded_by_id uuid REFERENCES chunks(id);

UPDATE chunks
SET lineage_id = id,
    change_type = CASE WHEN is_manual_edited THEN 'manual' ELSE 'generated' END
WHERE lineage_id IS NULL;

ALTER TABLE chunks
    ALTER COLUMN lineage_id SET NOT NULL,
    ALTER COLUMN lineage_id SET DEFAULT gen_random_uuid();

ALTER TABLE chunks
    DROP CONSTRAINT chunks_document_version_id_chunk_index_key;

CREATE UNIQUE INDEX uq_chunks_active_version_index
    ON chunks (document_version_id, chunk_index)
    WHERE status = 'active';

CREATE INDEX ix_chunks_lineage_revision
    ON chunks (lineage_id, revision DESC, created_at DESC, id);

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg247.chunk_edit_lineage',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-247', 'requirement_id', 'CHUNK-003'),
    now()
);

COMMIT;
