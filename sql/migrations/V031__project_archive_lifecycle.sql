BEGIN;

ALTER TABLE projects
    ADD COLUMN archived_at timestamptz,
    ADD COLUMN archived_by uuid REFERENCES users(id);

UPDATE projects
SET status = 'active'
WHERE status = 'processing';

UPDATE projects AS project
SET archived_at = COALESCE(project.updated_at, now()),
    archived_by = COALESCE(
        project.created_by,
        (SELECT owner.user_id FROM project_owners AS owner WHERE owner.project_id = project.id ORDER BY owner.created_at LIMIT 1),
        (SELECT app_user.id FROM users AS app_user ORDER BY app_user.created_at LIMIT 1)
    )
WHERE project.status = 'archived';

ALTER TABLE projects
    DROP CONSTRAINT IF EXISTS projects_status_check;

ALTER TABLE projects
    ADD CONSTRAINT projects_status_check
    CHECK (status IN ('active', 'archived'));

ALTER TABLE projects
    ADD CONSTRAINT projects_archive_metadata_check
    CHECK (
        (status = 'active' AND archived_at IS NULL AND archived_by IS NULL)
        OR
        (status = 'archived' AND archived_at IS NOT NULL AND archived_by IS NOT NULL)
    );

CREATE INDEX ix_projects_status_name ON projects (status, name, id);

CREATE TABLE project_archive_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status varchar(32) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    requested_by uuid NOT NULL REFERENCES users(id),
    queued_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    heartbeat_at timestamptz,
    completed_at timestamptz,
    lease_token uuid,
    lease_expires_at timestamptz,
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    unfinished_version_count integer NOT NULL DEFAULT 0 CHECK (unfinished_version_count >= 0),
    deleted_version_count integer NOT NULL DEFAULT 0 CHECK (deleted_version_count >= 0),
    deleted_document_count integer NOT NULL DEFAULT 0 CHECK (deleted_document_count >= 0),
    deleted_s3_object_count integer NOT NULL DEFAULT 0 CHECK (deleted_s3_object_count >= 0),
    deleted_search_document_count integer NOT NULL DEFAULT 0 CHECK (deleted_search_document_count >= 0),
    deleted_graph_version_count integer NOT NULL DEFAULT 0 CHECK (deleted_graph_version_count >= 0),
    checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code varchar(100),
    error_message text
);

CREATE UNIQUE INDEX uq_project_archive_runs_open_project
    ON project_archive_runs (project_id)
    WHERE status IN ('queued', 'running');

CREATE INDEX ix_project_archive_runs_project_queued
    ON project_archive_runs (project_id, queued_at DESC, id DESC);

INSERT INTO audit_logs (action, resource_type, result, summary, created_at)
VALUES (
    'migration.chg239.project_archive_lifecycle',
    'system',
    'success',
    jsonb_build_object('change_id', 'CHG-239'),
    now()
);

COMMIT;
