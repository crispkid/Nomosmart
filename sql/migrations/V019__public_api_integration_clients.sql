BEGIN;

CREATE TABLE IF NOT EXISTS integration_clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(255) NOT NULL,
    description text,
    status varchar(32) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'revoked')),
    api_key_hash varchar(64) NOT NULL UNIQUE,
    api_key_prefix varchar(24) NOT NULL,
    api_key_version integer NOT NULL DEFAULT 1,
    contact_name varchar(255),
    contact_email varchar(320),
    contact_department varchar(255),
    valid_from timestamptz,
    expires_at timestamptz,
    revoked_at timestamptz,
    revoked_by uuid REFERENCES users(id),
    revocation_reason text,
    rate_limit_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_used_at timestamptz,
    last_used_project_id uuid REFERENCES projects(id),
    success_count integer NOT NULL DEFAULT 0,
    failure_count integer NOT NULL DEFAULT 0,
    created_by uuid REFERENCES users(id),
    updated_by uuid REFERENCES users(id),
    lock_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_integration_clients_status ON integration_clients(status);

CREATE TABLE IF NOT EXISTS integration_client_project_scopes (
    client_id uuid NOT NULL REFERENCES integration_clients(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, project_id)
);

CREATE TABLE IF NOT EXISTS public_api_request_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_client_id uuid NOT NULL REFERENCES integration_clients(id),
    project_id uuid NOT NULL REFERENCES projects(id),
    request_id varchar(255),
    endpoint varchar(120) NOT NULL,
    response_mode varchar(32) NOT NULL,
    result varchar(32) NOT NULL,
    http_status integer NOT NULL,
    end_user_employee_id varchar(100) NOT NULL,
    end_user_employee_name varchar(255),
    end_user_department varchar(255),
    question text,
    answer text,
    citations jsonb NOT NULL DEFAULT '[]'::jsonb,
    selected_document_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    selected_document_version_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    retrieval_strategy varchar(32),
    retrieval_status varchar(32),
    llm_model_id uuid REFERENCES ai_models(id),
    prompt_version varchar(100),
    system_prompt_source varchar(32),
    system_prompt_version_id uuid REFERENCES system_prompt_versions(id),
    system_prompt_content_hash varchar(64),
    system_prompt_layers jsonb,
    token_usage jsonb,
    latency_ms integer,
    error_code varchar(100),
    error_message text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_public_api_request_logs_client_created ON public_api_request_logs(integration_client_id, created_at);
CREATE INDEX IF NOT EXISTS ix_public_api_request_logs_project_created ON public_api_request_logs(project_id, created_at);

CREATE TABLE IF NOT EXISTS chat_feedback_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    chat_record_id uuid REFERENCES chat_records(id) ON DELETE CASCADE,
    public_response_id uuid REFERENCES public_api_request_logs(id) ON DELETE CASCADE,
    source varchar(32) NOT NULL CHECK (source IN ('ui', 'api')),
    feedback_value varchar(32) NOT NULL,
    comment text,
    actor_user_id uuid REFERENCES users(id),
    integration_client_id uuid REFERENCES integration_clients(id),
    end_user_employee_id varchar(100),
    end_user_employee_name varchar(255),
    end_user_department varchar(255),
    request_id varchar(255),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_chat_feedback_events_chat_record_created ON chat_feedback_events(chat_record_id, created_at);
CREATE INDEX IF NOT EXISTS ix_chat_feedback_events_public_response_created ON chat_feedback_events(public_response_id, created_at);

COMMIT;
