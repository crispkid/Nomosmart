BEGIN;
CREATE TABLE public.document_content_states (
    document_version_id uuid PRIMARY KEY REFERENCES public.document_versions(id),
    project_id uuid NOT NULL REFERENCES public.projects(id),
    document_id uuid NOT NULL REFERENCES public.documents(id),
    current_markdown text NOT NULL,
    current_sha256 varchar(64) NOT NULL CHECK (current_sha256 ~ '^[0-9a-f]{64}$'),
    content_revision integer NOT NULL CHECK (content_revision > 0),
    original_artifact jsonb NOT NULL DEFAULT '{}',
    updated_by uuid REFERENCES public.users(id),
    updated_at timestamptz NOT NULL
);
CREATE TABLE public.document_content_update_jobs (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES public.projects(id),
    document_id uuid NOT NULL REFERENCES public.documents(id),
    document_version_id uuid NOT NULL REFERENCES public.document_versions(id),
    source_version_id uuid NOT NULL REFERENCES public.document_versions(id),
    pipeline_run_id uuid NOT NULL REFERENCES public.pipeline_runs(id),
    actor_user_id uuid NOT NULL REFERENCES public.users(id),
    request_id varchar(255),
    base_revision integer NOT NULL CHECK (base_revision > 0),
    target_revision integer NOT NULL CHECK (target_revision > base_revision),
    base_sha256 varchar(64) NOT NULL CHECK (base_sha256 ~ '^[0-9a-f]{64}$'),
    target_sha256 varchar(64) NOT NULL CHECK (target_sha256 ~ '^[0-9a-f]{64}$'),
    expected_lock integer NOT NULL CHECK (expected_lock > 0),
    project_generation bigint NOT NULL,
    pending_markdown text,
    status varchar(32) NOT NULL CHECK (status IN ('queued','running','ready','failed','blocked','chunks_required','cancelled')),
    step_name varchar(50) NOT NULL,
    error_code varchar(100),
    checkpoint jsonb NOT NULL DEFAULT '{}',
    claim_token uuid,
    lease_expires_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (document_version_id, target_revision)
);
CREATE UNIQUE INDEX uq_content_update_active ON public.document_content_update_jobs(document_version_id)
    WHERE status IN ('queued','running','failed','blocked');
CREATE INDEX ix_content_updates_scope ON public.document_content_update_jobs(project_id, document_id, document_version_id);
COMMENT ON TABLE public.document_content_states IS 'One committed corrected canonical source; original extraction evidence is immutable.';
COMMENT ON TABLE public.document_content_update_jobs IS 'Revision-fenced temporary content and durable step receipts; clear pending text on success.';
COMMIT;
