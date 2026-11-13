-- CHG-422 additive settings revisions and new-rejection retention; no historical expiry backfill.
BEGIN;
CREATE TABLE public.system_parameter_section_revisions (
 section varchar(16) PRIMARY KEY CHECK (section IN ('general','documents')),
 revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
 updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.system_parameter_section_revisions(section) VALUES ('general'),('documents');
CREATE TABLE public.staging_retention_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL REFERENCES public.projects(id),
 document_id uuid NOT NULL REFERENCES public.documents(id),
 document_version_id uuid NOT NULL UNIQUE REFERENCES public.document_versions(id),
 approval_request_id uuid NOT NULL REFERENCES public.approval_requests(id),
 rejected_at timestamptz NOT NULL,
 ttl_days integer NOT NULL CHECK (ttl_days BETWEEN 1 AND 3650),
 expires_at timestamptz NOT NULL,
 status varchar(32) NOT NULL DEFAULT 'scheduled',
 lease_token uuid, lease_expires_at timestamptz,
 attempt integer NOT NULL DEFAULT 0,
 checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
 error_code varchar(100), completed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_staging_retention_due ON public.staging_retention_jobs(status,expires_at);
GRANT SELECT,INSERT,UPDATE,DELETE ON public.system_parameter_section_revisions,public.staging_retention_jobs TO nomosmart;
COMMIT;
