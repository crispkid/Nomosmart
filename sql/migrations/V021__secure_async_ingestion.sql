ALTER TABLE file_scan_runs
    ADD COLUMN quarantine_bucket varchar(255),
    ADD COLUMN quarantine_key text,
    ADD COLUMN accepted_bucket varchar(255),
    ADD COLUMN accepted_key text,
    ADD COLUMN content_type varchar(255),
    ADD COLUMN content_sha256 varchar(64),
    ADD COLUMN attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN available_at timestamptz,
    ADD COLUMN claim_token uuid,
    ADD COLUMN claimed_at timestamptz,
    ADD COLUMN lease_expires_at timestamptz,
    ADD COLUMN quarantine_deleted_at timestamptz;

CREATE INDEX ix_file_scan_runs_available
    ON file_scan_runs (status, available_at);

ALTER TABLE outbox_events
    ADD COLUMN claim_token uuid,
    ADD COLUMN claimed_at timestamptz,
    ADD COLUMN lease_expires_at timestamptz,
    ADD COLUMN task_id varchar(255);

CREATE UNIQUE INDEX uq_outbox_secure_ingestion_topic_aggregate
    ON outbox_events (topic, aggregate_id)
    WHERE topic IN ('file.scan.requested', 'document.extraction.requested');

CREATE INDEX ix_outbox_dispatch_available
    ON outbox_events (status, available_at, lease_expires_at);

ALTER TABLE pipeline_run_steps
    ADD COLUMN claim_token uuid,
    ADD COLUMN claimed_at timestamptz,
    ADD COLUMN lease_expires_at timestamptz,
    ADD COLUMN artifact_fingerprint varchar(64),
    ADD COLUMN artifact_payload jsonb;

ALTER TABLE embedding_builds
    ADD COLUMN content_fingerprint varchar(64),
    ADD COLUMN model_id uuid REFERENCES ai_models(id),
    ADD COLUMN vector_dimension integer,
    ADD COLUMN token_count integer NOT NULL DEFAULT 0,
    ADD COLUMN usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN completed_at timestamptz;

CREATE UNIQUE INDEX uq_embedding_builds_canonical
    ON embedding_builds (document_version_id, embedding_profile_id, content_fingerprint)
    WHERE content_fingerprint IS NOT NULL;

CREATE TABLE embedding_build_vectors (
    id uuid PRIMARY KEY,
    embedding_build_id uuid NOT NULL REFERENCES embedding_builds(id) ON DELETE CASCADE,
    chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    vector jsonb NOT NULL,
    vector_checksum varchar(64) NOT NULL,
    token_count integer NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT uq_embedding_build_vectors_build_chunk UNIQUE (embedding_build_id, chunk_id),
    CONSTRAINT uq_embedding_build_vectors_build_index UNIQUE (embedding_build_id, chunk_index)
);

CREATE INDEX ix_embedding_build_vectors_build
    ON embedding_build_vectors (embedding_build_id, chunk_index);
