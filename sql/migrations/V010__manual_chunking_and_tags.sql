ALTER TABLE chunk_tags
    ADD COLUMN IF NOT EXISTS source varchar(32) NOT NULL DEFAULT 'rule',
    ADD COLUMN IF NOT EXISTS confidence_score numeric(6,5),
    ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS created_by uuid REFERENCES users(id);

CREATE TABLE IF NOT EXISTS document_version_tags (
    document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    tag_id uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    source varchar(32) NOT NULL DEFAULT 'manual',
    confidence_score numeric(6,5),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_version_id, tag_id)
);
