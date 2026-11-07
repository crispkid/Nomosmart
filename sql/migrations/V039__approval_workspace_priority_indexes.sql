ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS priority varchar(32) NOT NULL DEFAULT 'normal';

CREATE INDEX IF NOT EXISTS ix_approval_requests_submitter_submitted
    ON approval_requests(submitter_id, submitted_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_approval_requests_status_submitted
    ON approval_requests(status, submitted_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_approval_tasks_assignee_status_submitted
    ON approval_tasks(assignee_user_id, status, submitted_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_approval_tasks_project_status_submitted
    ON approval_tasks(project_id, status, submitted_at DESC, id DESC);
