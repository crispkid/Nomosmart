BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id varchar(10) UNIQUE CHECK (employee_id IS NULL OR employee_id ~ '^Z.{0,9}$'),
    keycloak_user_id varchar(255) NOT NULL UNIQUE,
    ldap_dn text,
    email varchar(320),
    display_name varchar(255) NOT NULL,
    department varchar(255),
    title varchar(255),
    auth_source varchar(32) NOT NULL DEFAULT 'keycloak',
    manager_user_id uuid REFERENCES users(id),
    manager_delegate_user_id uuid REFERENCES users(id),
    manager_delegate_start_at timestamptz,
    manager_delegate_end_at timestamptz,
    is_active boolean NOT NULL DEFAULT true,
    last_synced_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_users_email ON users(email);

CREATE TABLE roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(100) NOT NULL UNIQUE,
    description text,
    is_active boolean NOT NULL DEFAULT true,
    is_system boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE role_users (
    role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source varchar(32) NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (role_id, user_id)
);

CREATE TABLE role_permissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    module_name varchar(100) NOT NULL,
    function_name varchar(100) NOT NULL,
    can_view boolean NOT NULL DEFAULT false,
    can_create boolean NOT NULL DEFAULT false,
    can_edit boolean NOT NULL DEFAULT false,
    can_delete boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (role_id, module_name, function_name)
);

CREATE TABLE external_groups (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source varchar(32) NOT NULL,
    external_group_id varchar(255) NOT NULL,
    group_dn text,
    group_name varchar(255) NOT NULL,
    path text,
    is_active boolean NOT NULL DEFAULT true,
    last_synced_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, external_group_id)
);

CREATE TABLE external_group_role_mappings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_group_id uuid NOT NULL REFERENCES external_groups(id) ON DELETE CASCADE,
    role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (external_group_id, role_id)
);

CREATE TABLE identity_sync_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source varchar(32) NOT NULL,
    status varchar(32) NOT NULL,
    started_at timestamptz,
    completed_at timestamptz,
    users_created integer NOT NULL DEFAULT 0,
    users_updated integer NOT NULL DEFAULT 0,
    users_disabled integer NOT NULL DEFAULT 0,
    groups_created integer NOT NULL DEFAULT 0,
    groups_updated integer NOT NULL DEFAULT 0,
    role_memberships_updated integer NOT NULL DEFAULT 0,
    error_message text
);

CREATE TABLE identity_settings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    revision integer NOT NULL,
    state varchar(64) NOT NULL CHECK (state IN ('draft_unvalidated','validated_active_locked','temporarily_unlocked')),
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    secret_configured boolean NOT NULL DEFAULT false,
    is_current boolean NOT NULL DEFAULT false,
    is_last_known_good boolean NOT NULL DEFAULT false,
    validated_at timestamptz,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (revision)
);
CREATE UNIQUE INDEX uq_identity_settings_current ON identity_settings(is_current) WHERE is_current;

CREATE TABLE identity_unlock_grants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    session_id varchar(255) NOT NULL,
    scope varchar(100) NOT NULL,
    auth_time timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_identity_unlock_active ON identity_unlock_grants(user_id, session_id, expires_at) WHERE revoked_at IS NULL;

CREATE TABLE system_parameters (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key varchar(100) NOT NULL UNIQUE,
    value jsonb NOT NULL,
    default_value jsonb NOT NULL,
    value_type varchar(32) NOT NULL,
    unit varchar(32),
    description text NOT NULL,
    updated_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_models (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(255) NOT NULL,
    model_type varchar(32) NOT NULL CHECK (model_type IN ('OCR','Embedding','Chat','Judge')),
    provider varchar(100) NOT NULL,
    endpoint text,
    api_key_encrypted text,
    api_key_secret_ref text,
    is_active boolean NOT NULL DEFAULT true,
    is_default boolean NOT NULL DEFAULT false,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    config_version integer NOT NULL DEFAULT 1,
    last_test_status varchar(32),
    last_tested_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, model_type)
);
CREATE UNIQUE INDEX uq_ai_models_default_type ON ai_models(model_type) WHERE is_active AND is_default;

CREATE TABLE embedding_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id uuid NOT NULL REFERENCES ai_models(id),
    model_version varchar(100) NOT NULL,
    vector_dimension integer NOT NULL CHECK (vector_dimension > 0),
    distance_method varchar(32) NOT NULL,
    chunk_strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
    mapping_version integer NOT NULL CHECK (mapping_version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_id, model_version, vector_dimension, distance_method, mapping_version)
);

CREATE TABLE projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(255) NOT NULL,
    description text,
    status varchar(32) NOT NULL DEFAULT 'active' CHECK (status IN ('active','processing','archived')),
    llm_model_id uuid REFERENCES ai_models(id),
    embedding_model_id uuid REFERENCES ai_models(id),
    created_by uuid REFERENCES users(id),
    lock_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE project_members (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_role varchar(32) NOT NULL CHECK (project_role IN ('owner','maintainer','contributor','viewer')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, user_id, project_role)
);

CREATE TABLE project_owners (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, user_id)
);

CREATE TABLE data_connections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    service_type varchar(32) NOT NULL,
    name varchar(255) NOT NULL,
    connection_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    credential_encrypted text,
    credential_secret_ref text,
    source_identity jsonb NOT NULL DEFAULT '{}'::jsonb,
    schedule_mode varchar(32) NOT NULL,
    cron_expression varchar(255),
    timezone varchar(100) NOT NULL DEFAULT 'Asia/Taipei',
    enabled boolean NOT NULL DEFAULT true,
    last_sync_status varchar(32),
    last_synced_at timestamptz,
    next_run_at timestamptz,
    lock_version integer NOT NULL DEFAULT 1,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_code varchar(100) NOT NULL,
    title varchar(500) NOT NULL,
    description text,
    source_type varchar(50) NOT NULL,
    source_name varchar(255),
    source_uri text,
    source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    status varchar(32) NOT NULL DEFAULT 'inactive' CHECK (status IN ('active','inactive','deleted')),
    is_deleted boolean NOT NULL DEFAULT false,
    deleted_at timestamptz,
    deleted_by uuid REFERENCES users(id),
    inactive_reason varchar(255),
    created_by uuid REFERENCES users(id),
    owner_user_id uuid REFERENCES users(id),
    last_updated_by uuid REFERENCES users(id),
    lock_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_imported_at timestamptz,
    UNIQUE (project_id, document_code)
);

CREATE TABLE document_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES documents(id),
    project_id uuid NOT NULL REFERENCES projects(id),
    version_major integer NOT NULL CHECK (version_major > 0),
    extraction_revision integer NOT NULL CHECK (extraction_revision >= 0),
    version_label varchar(50) NOT NULL,
    original_file_name varchar(255),
    canonical_extension varchar(16),
    mime_type varchar(255),
    file_size bigint CHECK (file_size IS NULL OR file_size >= 0),
    content_sha256 varchar(64),
    storage_name_salt varchar(128),
    storage_name_hash varchar(64),
    storage_bucket varchar(255),
    storage_key text,
    storage_etag varchar(255),
    uploaded_at timestamptz,
    original_snapshot_uri text,
    markdown_artifact_uri text,
    extraction_artifact_uri text,
    parser_version varchar(100),
    ocr_model_id uuid REFERENCES ai_models(id),
    ocr_config_version integer,
    chunk_strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
    chunk_size integer,
    chunk_overlap integer,
    embedding_model_id uuid REFERENCES ai_models(id),
    embedding_profile_id uuid REFERENCES embedding_profiles(id),
    llm_model_id uuid REFERENCES ai_models(id),
    status varchar(50) NOT NULL,
    published_at timestamptz,
    published_by uuid REFERENCES users(id),
    inactive_reason varchar(255),
    source_document_id uuid REFERENCES documents(id),
    source_version_id uuid REFERENCES document_versions(id),
    source_snapshot_created_at timestamptz,
    lock_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_major, extraction_revision)
);
CREATE INDEX ix_document_versions_status ON document_versions(project_id, status);

CREATE TABLE file_scan_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    scanner_type varchar(50) NOT NULL,
    status varchar(32) NOT NULL CHECK (status IN ('quarantine','scanning','accepted','rejected','failed','disabled')),
    safe_result_code varchar(100),
    safe_error_summary text,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE embedding_builds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid NOT NULL REFERENCES documents(id),
    document_version_id uuid NOT NULL REFERENCES document_versions(id),
    embedding_profile_id uuid NOT NULL REFERENCES embedding_profiles(id),
    build_revision integer NOT NULL DEFAULT 1,
    status varchar(32) NOT NULL,
    chunk_count integer NOT NULL DEFAULT 0,
    index_name varchar(255),
    checksum varchar(64),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, embedding_profile_id, build_revision)
);

CREATE TABLE active_version_manifests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid NOT NULL UNIQUE REFERENCES documents(id),
    document_version_id uuid NOT NULL REFERENCES document_versions(id),
    embedding_profile_id uuid NOT NULL REFERENCES embedding_profiles(id),
    embedding_build_id uuid NOT NULL REFERENCES embedding_builds(id),
    publication_generation bigint NOT NULL CHECK (publication_generation > 0),
    index_ready boolean NOT NULL DEFAULT false,
    lock_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_references (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    target_project_id uuid NOT NULL REFERENCES projects(id),
    target_document_id uuid NOT NULL REFERENCES documents(id),
    source_project_id uuid NOT NULL REFERENCES projects(id),
    source_document_id uuid NOT NULL REFERENCES documents(id),
    source_version_id uuid NOT NULL REFERENCES document_versions(id),
    source_project_name_snapshot varchar(255) NOT NULL,
    source_document_name_snapshot varchar(500) NOT NULL,
    reference_mode varchar(32) NOT NULL DEFAULT 'linked',
    status varchar(32) NOT NULL DEFAULT 'active',
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_synced_at timestamptz,
    UNIQUE (target_project_id, source_project_id, source_document_id)
);

CREATE TABLE document_reference_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reference_id uuid NOT NULL REFERENCES document_references(id),
    event_type varchar(50) NOT NULL,
    source_project_id uuid NOT NULL REFERENCES projects(id),
    source_document_id uuid NOT NULL REFERENCES documents(id),
    old_source_version_id uuid REFERENCES document_versions(id),
    new_source_version_id uuid REFERENCES document_versions(id),
    message text NOT NULL,
    is_read boolean NOT NULL DEFAULT false,
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE data_sync_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_connection_id uuid NOT NULL REFERENCES data_connections(id),
    document_id uuid NOT NULL REFERENCES documents(id),
    trigger_type varchar(32) NOT NULL,
    status varchar(32) NOT NULL,
    started_at timestamptz,
    completed_at timestamptz,
    content_fingerprint varchar(64),
    remote_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    document_version_id uuid REFERENCES document_versions(id),
    error_code varchar(100),
    error_summary text,
    retry_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pipeline_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid REFERENCES documents(id),
    document_version_id uuid REFERENCES document_versions(id),
    run_type varchar(50) NOT NULL,
    status varchar(32) NOT NULL,
    progress_percent numeric(5,2) NOT NULL DEFAULT 0,
    current_step_name varchar(100),
    current_waiting_role varchar(100),
    current_action_url text,
    estimated_remaining_seconds integer,
    triggered_by uuid REFERENCES users(id),
    started_at timestamptz,
    completed_at timestamptz,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pipeline_run_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    step_name varchar(100) NOT NULL,
    status varchar(32) NOT NULL,
    progress_percent numeric(5,2) NOT NULL DEFAULT 0,
    progress_message text,
    waiting_role varchar(100),
    action_url text,
    retry_count integer NOT NULL DEFAULT 0,
    input_artifact_ref text,
    output_artifact_ref text,
    model_id uuid REFERENCES ai_models(id),
    started_at timestamptz,
    completed_at timestamptz,
    error_message text,
    UNIQUE (run_id, step_name)
);

CREATE TABLE approval_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid NOT NULL REFERENCES documents(id),
    document_version_id uuid NOT NULL REFERENCES document_versions(id),
    submitter_id uuid NOT NULL REFERENCES users(id),
    owner_user_id uuid REFERENCES users(id),
    status varchar(50) NOT NULL,
    current_task_id uuid,
    submitted_at timestamptz NOT NULL,
    approved_at timestamptz,
    published_at timestamptz,
    cancelled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE approval_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_request_id uuid NOT NULL REFERENCES approval_requests(id),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid NOT NULL REFERENCES documents(id),
    document_version_id uuid NOT NULL REFERENCES document_versions(id),
    submitter_id uuid NOT NULL REFERENCES users(id),
    owner_user_id uuid REFERENCES users(id),
    assignee_user_id uuid REFERENCES users(id),
    original_manager_user_id uuid REFERENCES users(id),
    review_stage varchar(32) NOT NULL,
    status varchar(32) NOT NULL,
    lock_version integer NOT NULL DEFAULT 1,
    priority varchar(32),
    due_at timestamptz,
    submitted_at timestamptz NOT NULL,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE approval_requests ADD CONSTRAINT fk_approval_current_task FOREIGN KEY (current_task_id) REFERENCES approval_tasks(id);
CREATE UNIQUE INDEX uq_active_approval_version ON approval_requests(document_version_id) WHERE status IN ('pending_manager_review','pending_owner_review','approved');

CREATE TABLE review_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid NOT NULL REFERENCES documents(id),
    document_version_id uuid NOT NULL REFERENCES document_versions(id),
    review_stage varchar(32) NOT NULL,
    reviewer_id uuid NOT NULL REFERENCES users(id),
    delegated_from_user_id uuid REFERENCES users(id),
    status varchar(32) NOT NULL,
    comment text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid NOT NULL REFERENCES documents(id),
    document_version_id uuid NOT NULL REFERENCES document_versions(id),
    chunk_index integer NOT NULL,
    title varchar(500),
    content text NOT NULL,
    markdown_content text,
    content_type varchar(32) NOT NULL DEFAULT 'text',
    content_hash varchar(64) NOT NULL,
    language varchar(32),
    page_no integer,
    section_path text,
    start_offset integer,
    end_offset integer,
    source_paragraph_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_ranges jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_mapping jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_page_ranges jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_table_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_image_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    chunk_strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding_model_id uuid REFERENCES ai_models(id),
    embedding_vector_ref text,
    token_count integer,
    confidence_score numeric(6,5),
    status varchar(32) NOT NULL DEFAULT 'active',
    is_manual_edited boolean NOT NULL DEFAULT false,
    edited_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_version_id, chunk_index)
);

CREATE TABLE tags (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    name varchar(255) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

CREATE TABLE chunk_tags (
    chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    tag_id uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, tag_id)
);

CREATE TABLE chat_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_version_id uuid REFERENCES document_versions(id),
    conversation_id uuid NOT NULL,
    conversation_title varchar(500),
    selected_document_version_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    question text NOT NULL,
    answer text,
    reference_docs jsonb NOT NULL DEFAULT '[]'::jsonb,
    evaluation varchar(32) NOT NULL DEFAULT 'not_evaluated',
    revision_suggestion text,
    llm_model_id uuid REFERENCES ai_models(id),
    embedding_model_id uuid REFERENCES ai_models(id),
    prompt_version varchar(100),
    token_usage jsonb,
    latency_ms integer,
    created_by uuid NOT NULL REFERENCES users(id),
    asked_at timestamptz NOT NULL,
    answered_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE validation_questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    question text NOT NULL,
    expected_answer text,
    expected_keywords jsonb,
    category varchar(100),
    priority varchar(32),
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE validation_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    uploaded_file_name varchar(255),
    status varchar(32) NOT NULL,
    run_scope varchar(32) NOT NULL,
    approval_task_id uuid REFERENCES approval_tasks(id),
    document_version_id uuid REFERENCES document_versions(id),
    embedding_model varchar(255),
    llm_model varchar(255),
    selected_document_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    total_count integer NOT NULL DEFAULT 0,
    completed_count integer NOT NULL DEFAULT 0,
    failed_count integer NOT NULL DEFAULT 0,
    created_by uuid NOT NULL REFERENCES users(id),
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE validation_run_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES validation_runs(id) ON DELETE CASCADE,
    question text NOT NULL,
    expected_answer text,
    expected_keywords jsonb,
    selected_document_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    answer text,
    reference_docs jsonb NOT NULL DEFAULT '[]'::jsonb,
    chat_record_id uuid REFERENCES chat_records(id),
    status varchar(32) NOT NULL,
    score numeric(8,5),
    evaluation_reason text,
    error_message text,
    latency_ms integer,
    token_usage jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_user_id uuid NOT NULL REFERENCES users(id),
    project_id uuid REFERENCES projects(id),
    notification_type varchar(100) NOT NULL,
    severity varchar(32) NOT NULL,
    title varchar(500) NOT NULL,
    message text NOT NULL,
    action_type varchar(32),
    action_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_read boolean NOT NULL DEFAULT false,
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE graph_sync_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id),
    document_id uuid NOT NULL REFERENCES documents(id),
    document_version_id uuid NOT NULL REFERENCES document_versions(id),
    trigger_type varchar(50) NOT NULL,
    status varchar(32) NOT NULL,
    node_count integer NOT NULL DEFAULT 0,
    edge_count integer NOT NULL DEFAULT 0,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id uuid REFERENCES users(id),
    action varchar(150) NOT NULL,
    resource_type varchar(100) NOT NULL,
    resource_id uuid,
    result varchar(32) NOT NULL,
    request_id varchar(255),
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_logs_cursor ON audit_logs(created_at DESC, id DESC);

CREATE TABLE idempotency_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scope varchar(100) NOT NULL,
    key varchar(255) NOT NULL,
    request_hash varchar(64) NOT NULL,
    status varchar(32) NOT NULL,
    response_status integer,
    response_summary jsonb,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (scope, key)
);

CREATE TABLE outbox_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    topic varchar(150) NOT NULL,
    aggregate_type varchar(100) NOT NULL,
    aggregate_id uuid NOT NULL,
    payload jsonb NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    last_error text
);
CREATE INDEX ix_outbox_pending ON outbox_events(status, available_at) WHERE status = 'pending';

INSERT INTO roles (name, description, is_system) VALUES
    ('system-admin', 'System administration', true),
    ('project-owner', 'Project governance and publication', true),
    ('knowledge-editor', 'Knowledge import and maintenance', true),
    ('reviewer', 'Authorized review operations', true);

INSERT INTO system_parameters (key, value, default_value, value_type, unit, description) VALUES
    ('max_upload_size_mb', '100'::jsonb, '100'::jsonb, 'integer', 'MB', 'Maximum size of one uploaded document'),
    ('default_timezone', '"Asia/Taipei"'::jsonb, '"Asia/Taipei"'::jsonb, 'iana_timezone', NULL, 'Default IANA timezone'),
    ('staging_index_ttl_days', '7'::jsonb, '7'::jsonb, 'integer', 'days', 'Retention for rejected staging index data');

COMMIT;
