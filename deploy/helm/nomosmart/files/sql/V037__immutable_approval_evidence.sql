ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS evidence_revision varchar(64);

CREATE TABLE IF NOT EXISTS approval_evidence_manifests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_request_id uuid NOT NULL UNIQUE REFERENCES approval_requests(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid NOT NULL REFERENCES documents(id),
    document_version_id uuid NOT NULL REFERENCES document_versions(id),
    evidence_revision varchar(64) NOT NULL,
    manifest_hash varchar(64) NOT NULL UNIQUE,
    manifest jsonb NOT NULL,
    generated_at timestamptz NOT NULL,
    submitted_at timestamptz NOT NULL,
    created_by uuid NOT NULL REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS ix_approval_evidence_version_submitted
    ON approval_evidence_manifests(document_version_id, submitted_at);
