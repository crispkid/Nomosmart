BEGIN;

-- CHG-305 additive operational data only. No legacy file backfill or policy defaults:
-- the authenticated initializer imports effective deployment values explicitly.
CREATE TABLE file_processing_policies (
    id integer PRIMARY KEY CHECK (id = 1),
    deployment_id uuid NOT NULL UNIQUE,
    revision integer NOT NULL CHECK (revision > 0),
    content_hash varchar(64) NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE TABLE file_processing_policy_revisions (
    revision integer PRIMARY KEY CHECK (revision > 0),
    snapshot jsonb NOT NULL,
    content_hash varchar(64) NOT NULL,
    provenance jsonb NOT NULL,
    created_by uuid NOT NULL REFERENCES users(id),
    created_at timestamptz NOT NULL
);
CREATE TABLE file_processing_pools (
    kind varchar(16) PRIMARY KEY CHECK (kind IN ('document','parser'))
);
INSERT INTO file_processing_pools(kind) VALUES ('document'), ('parser');
CREATE TABLE file_processing_executions (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES pipeline_runs(id),
    document_version_id uuid NOT NULL REFERENCES document_versions(id),
    kind varchar(16) NOT NULL REFERENCES file_processing_pools(kind),
    parent_id uuid REFERENCES file_processing_executions(id),
    attempt integer NOT NULL CHECK (attempt > 0),
    generation uuid NOT NULL UNIQUE,
    deployment_id uuid NOT NULL,
    project_generation bigint NOT NULL,
    state varchar(32) NOT NULL,
    policy_revision integer NOT NULL REFERENCES file_processing_policy_revisions(revision),
    policy_snapshot jsonb NOT NULL,
    policy_hash varchar(64) NOT NULL,
    input_hash varchar(64) NOT NULL,
    workload_id varchar(255), workload_uid varchar(255), image_digest varchar(255), profile varchar(100),
    phase varchar(32) NOT NULL,
    progress_revision bigint NOT NULL DEFAULT 0 CHECK (progress_revision >= 0),
    completed_units integer NOT NULL DEFAULT 0 CHECK (completed_units >= 0),
    total_units integer CHECK (total_units >= completed_units),
    unit varchar(16), safe_error_code varchar(100),
    created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
    heartbeat_at timestamptz, deadline_at timestamptz, released_at timestamptz,
    stop_evidence jsonb, output_evidence jsonb,
    CONSTRAINT uq_file_execution_attempt UNIQUE (run_id, kind, attempt),
    CONSTRAINT ck_file_execution_parent CHECK (
      (kind = 'document' AND parent_id IS NULL) OR (kind = 'parser' AND parent_id IS NOT NULL)),
    CONSTRAINT ck_file_execution_release CHECK (
      (released_at IS NULL AND state IN ('reserved','starting','running','stopping','recovery_required')) OR
      (released_at IS NOT NULL AND state IN ('completed','failed','cancelled') AND stop_evidence IS NOT NULL))
);
CREATE UNIQUE INDEX uq_file_execution_active ON file_processing_executions(run_id, kind) WHERE released_at IS NULL;
CREATE INDEX ix_file_execution_occupancy ON file_processing_executions(kind, released_at);
COMMENT ON TABLE file_processing_executions IS
    'CHG-305 durable occupied slots; heartbeat expiry is not stop evidence. No destructive rollback.';
COMMENT ON TABLE file_processing_policy_revisions IS
    'CHG-305 immutable policy snapshots; current values reside in system_parameters.';

COMMIT;
