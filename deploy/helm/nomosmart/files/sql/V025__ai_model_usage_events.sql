CREATE TABLE ai_model_usage_events (
    id uuid PRIMARY KEY,
    model_id uuid NOT NULL REFERENCES ai_models(id),
    model_type varchar(32) NOT NULL,
    provider varchar(100) NOT NULL,
    project_id uuid REFERENCES projects(id),
    document_id uuid REFERENCES documents(id),
    document_version_id uuid REFERENCES document_versions(id),
    pipeline_run_id uuid REFERENCES pipeline_runs(id),
    pipeline_step_id uuid REFERENCES pipeline_run_steps(id),
    chat_record_id uuid REFERENCES chat_records(id),
    validation_run_id uuid REFERENCES validation_runs(id),
    validation_run_item_id uuid REFERENCES validation_run_items(id),
    public_api_request_log_id uuid REFERENCES public_api_request_logs(id),
    integration_client_id uuid REFERENCES integration_clients(id),
    actor_user_id uuid REFERENCES users(id),
    source_channel varchar(64) NOT NULL,
    usage_purpose varchar(64) NOT NULL,
    status varchar(32) NOT NULL,
    error_code varchar(100),
    attempted boolean NOT NULL DEFAULT true,
    attempt_number integer NOT NULL DEFAULT 1,
    correlation_id varchar(255),
    input_tokens bigint,
    output_tokens bigint,
    total_tokens bigint,
    embedding_tokens bigint,
    ocr_pages integer,
    ocr_images integer,
    vector_count integer,
    chunk_count integer,
    raw_usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    provider_reported_cost numeric(20, 8),
    estimated_cost numeric(20, 8),
    cost_currency varchar(3),
    cost_source varchar(32) NOT NULL DEFAULT 'unavailable',
    cost_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    latency_ms integer,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL,
    CONSTRAINT ai_model_usage_events_cost_source_check
        CHECK (cost_source IN ('provider_reported', 'estimated', 'unavailable')),
    CONSTRAINT ai_model_usage_events_provider_cost_check
        CHECK (provider_reported_cost IS NULL OR provider_reported_cost >= 0),
    CONSTRAINT ai_model_usage_events_estimated_cost_check
        CHECK (estimated_cost IS NULL OR estimated_cost >= 0),
    CONSTRAINT ai_model_usage_events_currency_check
        CHECK (cost_currency IS NULL OR cost_currency ~ '^[A-Z]{3}$'),
    CONSTRAINT ai_model_usage_events_attempt_check
        CHECK (attempt_number >= 1)
);

CREATE INDEX ix_ai_model_usage_events_created ON ai_model_usage_events (created_at);
CREATE INDEX ix_ai_model_usage_events_project_created ON ai_model_usage_events (project_id, created_at);
CREATE INDEX ix_ai_model_usage_events_model_created ON ai_model_usage_events (model_id, created_at);
CREATE INDEX ix_ai_model_usage_events_purpose_created ON ai_model_usage_events (usage_purpose, created_at);
CREATE INDEX ix_ai_model_usage_events_client_created ON ai_model_usage_events (integration_client_id, created_at);
