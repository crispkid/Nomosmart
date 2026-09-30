BEGIN;

ALTER TABLE graph_sync_jobs
    ADD COLUMN parent_job_id uuid REFERENCES graph_sync_jobs(id),
    ADD COLUMN requested_by_user_id uuid REFERENCES users(id),
    ADD COLUMN request_id varchar(255),
    ADD COLUMN attempt integer NOT NULL DEFAULT 0,
    ADD COLUMN error_code varchar(100),
    ADD COLUMN claim_token uuid,
    ADD COLUMN claimed_at timestamptz,
    ADD COLUMN lease_expires_at timestamptz;

CREATE INDEX ix_graph_sync_jobs_project_status_created
    ON graph_sync_jobs (project_id, status, created_at DESC, id);

CREATE INDEX ix_graph_sync_jobs_parent_attempt
    ON graph_sync_jobs (parent_job_id, created_at, id)
    WHERE parent_job_id IS NOT NULL;

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg247.graph_sync_durable_attempts',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-247', 'requirement_id', 'IDEMP-001'),
    now()
);

COMMIT;
