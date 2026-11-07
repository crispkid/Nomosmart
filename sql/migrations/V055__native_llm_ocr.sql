BEGIN;
-- CHG-410 additive data only. Keep historical image receipts, models and ledgers.
CREATE TABLE public.ocr_document_receipts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES public.projects(id),
    document_id uuid NOT NULL REFERENCES public.documents(id),
    document_version_id uuid NOT NULL REFERENCES public.document_versions(id),
    run_id uuid NOT NULL REFERENCES public.pipeline_runs(id),
    step_id uuid NOT NULL REFERENCES public.pipeline_run_steps(id),
    model_id uuid NOT NULL REFERENCES public.ai_models(id),
    attempt_id uuid NOT NULL,
    retry_count integer NOT NULL,
    source_sha256 varchar(64) NOT NULL,
    request_sha256 varchar(64) NOT NULL,
    snapshot_sha256 varchar(64) NOT NULL,
    binding_sha256 varchar(64) NOT NULL,
    dispatch_binding jsonb NOT NULL,
    model_snapshot jsonb NOT NULL,
    policy_snapshot jsonb NOT NULL,
    counted_input_tokens bigint NOT NULL,
    request_output_limit bigint NOT NULL,
    status varchar(32) NOT NULL,
    promotion_state varchar(16) NOT NULL,
    attempted boolean,
    usage jsonb NOT NULL DEFAULT '{}',
    usage_event_id uuid REFERENCES public.ai_model_usage_events(id),
    provider_response_id varchar(255),
    response_artifact_uri text NOT NULL,
    response_sha256 varchar(64),
    output_artifact_uri text NOT NULL,
    output_sha256 varchar(64),
    output_bytes bigint,
    observation_sha256 varchar(64),
    error_code varchar(100),
    completed_at timestamptz,
    promoted_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT uq_ocr_document_step_attempt UNIQUE (step_id, attempt_id),
    CONSTRAINT uq_ocr_document_step_retry UNIQUE (step_id, retry_count),
    CONSTRAINT uq_ocr_document_usage_event UNIQUE (usage_event_id),
    CONSTRAINT ck_ocr_document_receipts_ocr_document_status CHECK (status IN ('intent','confirmed_completed','confirmed_rejected','confirmed_incomplete','unknown')),
    CONSTRAINT ck_ocr_document_receipts_ocr_document_promotion CHECK (promotion_state IN ('pending','promoted','discarded')),
    CONSTRAINT ck_ocr_document_receipts_ocr_document_limits CHECK (retry_count >= 0 AND counted_input_tokens > 0 AND request_output_limit > 0),
    CONSTRAINT ck_ocr_document_receipts_ocr_document_output_bytes CHECK (output_bytes IS NULL OR output_bytes >= 0),
    CONSTRAINT ck_ocr_document_receipts_ocr_document_promoted_complete CHECK (promotion_state <> 'promoted' OR status = 'confirmed_completed')
);
CREATE UNIQUE INDEX uq_ocr_document_active_version ON public.ocr_document_receipts(document_version_id)
    WHERE status IN ('intent', 'unknown');
CREATE INDEX ix_ocr_document_version_created ON public.ocr_document_receipts(document_version_id, created_at);
COMMENT ON TABLE public.ocr_document_receipts IS 'CHG-410: durable pre-dispatch intent; independent observed accounting; no automatic replay or destructive down migration.';
-- The existing document budget remains authoritative. No historical page value
-- is repurposed as a document request cap. Missing/invalid settings fail closed.
INSERT INTO public.system_parameters(key, value, default_value, value_type, unit, description)
SELECT 'ocr_request_max_output_tokens', to_jsonb(LEAST(128000::bigint, (value #>> '{}')::bigint)),
       to_jsonb(LEAST(128000::bigint, (default_value #>> '{}')::bigint)),
       'integer', 'output_tokens', 'Maximum OCR output tokens per native document request'
FROM public.system_parameters
WHERE key = 'ocr_document_max_tokens' AND value_type = 'integer' AND unit = 'output_tokens'
ON CONFLICT (key) DO NOTHING;
COMMIT;
