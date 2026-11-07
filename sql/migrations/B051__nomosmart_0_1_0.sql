-- NomoSmart 0.1.0 baseline: final schema through V051.
-- Fresh databases only; keep V001-V051 unchanged for existing deployments.
-- Generated from isolated PostgreSQL 18.4; no deployed data is included.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;
COMMENT ON SCHEMA public IS 'standard public schema';
SET default_tablespace = '';
SET default_table_access_method = heap;
CREATE TABLE public.active_version_manifests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    embedding_profile_id uuid NOT NULL,
    embedding_build_id uuid NOT NULL,
    publication_generation bigint NOT NULL,
    index_ready boolean DEFAULT false NOT NULL,
    lock_version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT active_version_manifests_publication_generation_check CHECK ((publication_generation > 0))
);
CREATE TABLE public.ai_model_usage_events (
    id uuid NOT NULL,
    model_id uuid NOT NULL,
    model_type character varying(32) NOT NULL,
    provider character varying(100) NOT NULL,
    project_id uuid,
    document_id uuid,
    document_version_id uuid,
    pipeline_run_id uuid,
    pipeline_step_id uuid,
    chat_record_id uuid,
    validation_run_id uuid,
    validation_run_item_id uuid,
    public_api_request_log_id uuid,
    integration_client_id uuid,
    actor_user_id uuid,
    source_channel character varying(64) NOT NULL,
    usage_purpose character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    error_code character varying(100),
    attempted boolean DEFAULT true NOT NULL,
    attempt_number integer DEFAULT 1 NOT NULL,
    correlation_id character varying(255),
    input_tokens bigint,
    output_tokens bigint,
    total_tokens bigint,
    embedding_tokens bigint,
    ocr_pages integer,
    ocr_images integer,
    vector_count integer,
    chunk_count integer,
    raw_usage jsonb DEFAULT '{}'::jsonb NOT NULL,
    provider_reported_cost numeric(20,8),
    estimated_cost numeric(20,8),
    cost_currency character varying(3),
    cost_source character varying(32) DEFAULT 'unavailable'::character varying NOT NULL,
    cost_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    latency_ms integer,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ai_model_usage_events_attempt_check CHECK ((attempt_number >= 1)),
    CONSTRAINT ai_model_usage_events_cost_source_check CHECK (((cost_source)::text = ANY ((ARRAY['provider_reported'::character varying, 'estimated'::character varying, 'unavailable'::character varying])::text[]))),
    CONSTRAINT ai_model_usage_events_currency_check CHECK (((cost_currency IS NULL) OR ((cost_currency)::text ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT ai_model_usage_events_estimated_cost_check CHECK (((estimated_cost IS NULL) OR (estimated_cost >= (0)::numeric))),
    CONSTRAINT ai_model_usage_events_provider_cost_check CHECK (((provider_reported_cost IS NULL) OR (provider_reported_cost >= (0)::numeric)))
);
CREATE TABLE public.ai_models (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    model_type character varying(32) NOT NULL,
    provider character varying(100) NOT NULL,
    endpoint text,
    api_key_encrypted text,
    api_key_secret_ref text,
    is_active boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    config_version integer DEFAULT 1 NOT NULL,
    last_test_status character varying(32),
    last_tested_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_test_fingerprint character varying(64),
    last_test_latency_ms integer,
    last_test_detail_code character varying(100),
    last_test_actor_id uuid,
    deleted_at timestamp with time zone,
    deleted_by uuid,
    CONSTRAINT ai_models_model_type_check CHECK (((model_type)::text = ANY ((ARRAY['OCR'::character varying, 'Embedding'::character varying, 'Chat'::character varying, 'Judge'::character varying])::text[])))
);
CREATE TABLE public.approval_evidence_manifests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    approval_request_id uuid NOT NULL,
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    evidence_revision character varying(64) NOT NULL,
    manifest_hash character varying(64) NOT NULL,
    manifest jsonb NOT NULL,
    generated_at timestamp with time zone NOT NULL,
    submitted_at timestamp with time zone NOT NULL,
    created_by uuid NOT NULL
);
CREATE TABLE public.approval_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    submitter_id uuid NOT NULL,
    owner_user_id uuid,
    status character varying(50) NOT NULL,
    current_task_id uuid,
    submitted_at timestamp with time zone NOT NULL,
    approved_at timestamp with time zone,
    published_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    evidence_revision character varying(64),
    priority character varying(32) DEFAULT 'normal'::character varying NOT NULL
);
CREATE TABLE public.approval_tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    approval_request_id uuid NOT NULL,
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    submitter_id uuid NOT NULL,
    owner_user_id uuid,
    assignee_user_id uuid,
    original_manager_user_id uuid,
    review_stage character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    lock_version integer DEFAULT 1 NOT NULL,
    priority character varying(32),
    due_at timestamp with time zone,
    submitted_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.audit_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    actor_user_id uuid,
    action character varying(150) NOT NULL,
    resource_type character varying(100) NOT NULL,
    resource_id uuid,
    result character varying(32) NOT NULL,
    request_id character varying(255),
    summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.chat_feedback_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    chat_record_id uuid,
    public_response_id uuid,
    source character varying(32) NOT NULL,
    feedback_value character varying(32) NOT NULL,
    comment text,
    actor_user_id uuid,
    integration_client_id uuid,
    end_user_employee_id character varying(100),
    end_user_employee_name character varying(255),
    end_user_department character varying(255),
    request_id character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    end_user_identity_hash character varying(64),
    end_user_metadata_encrypted text,
    idempotency_key_hash character varying(64),
    CONSTRAINT chat_feedback_events_source_check CHECK (((source)::text = ANY ((ARRAY['ui'::character varying, 'api'::character varying])::text[])))
);
CREATE TABLE public.chat_records (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    document_version_id uuid,
    conversation_id uuid NOT NULL,
    conversation_title character varying(500),
    selected_document_version_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    question text NOT NULL,
    answer text,
    reference_docs jsonb DEFAULT '[]'::jsonb NOT NULL,
    evaluation character varying(32) DEFAULT 'not_evaluated'::character varying NOT NULL,
    revision_suggestion text,
    llm_model_id uuid,
    embedding_model_id uuid,
    prompt_version character varying(100),
    token_usage jsonb,
    latency_ms integer,
    created_by uuid NOT NULL,
    asked_at timestamp with time zone NOT NULL,
    answered_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    system_prompt_source character varying(32),
    system_prompt_version_id uuid,
    system_prompt_content_hash character varying(64),
    system_prompt_layers jsonb,
    deleted_at timestamp with time zone,
    deleted_by uuid,
    scope_mode character varying(32)
);
CREATE TABLE public.chunk_tags (
    chunk_id uuid NOT NULL,
    tag_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source character varying(32) DEFAULT 'llm'::character varying NOT NULL,
    confidence_score numeric(6,5),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by uuid
);
CREATE TABLE public.chunks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    title character varying(500),
    content text NOT NULL,
    markdown_content text,
    content_type character varying(32) DEFAULT 'text'::character varying NOT NULL,
    content_hash character varying(64) NOT NULL,
    language character varying(32),
    page_no integer,
    section_path text,
    start_offset integer,
    end_offset integer,
    source_paragraph_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_ranges jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_mapping jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_page_ranges jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_table_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    source_image_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    chunk_strategy jsonb DEFAULT '{}'::jsonb NOT NULL,
    embedding_model_id uuid,
    embedding_vector_ref text,
    token_count integer,
    confidence_score numeric(6,5),
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    is_manual_edited boolean DEFAULT false NOT NULL,
    edited_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    lineage_id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_chunk_id uuid,
    revision integer DEFAULT 0 NOT NULL,
    change_type character varying(32) DEFAULT 'generated'::character varying NOT NULL,
    superseded_at timestamp with time zone,
    superseded_by_id uuid,
    retrieval_text text,
    embedding_content_hash character varying(64),
    heading_path jsonb,
    heading_level integer,
    page_start integer,
    page_end integer,
    sequence integer,
    stable_chunk_key character varying(64),
    display_markdown text,
    CONSTRAINT ck_chunks_embedding_content_hash_length CHECK (((embedding_content_hash IS NULL) OR (length((embedding_content_hash)::text) = 64))),
    CONSTRAINT ck_chunks_heading_path_array CHECK (((heading_path IS NULL) OR (jsonb_typeof(heading_path) = 'array'::text))),
    CONSTRAINT ck_chunks_page_range CHECK (((page_start IS NULL) OR (page_end IS NULL) OR (page_end >= page_start))),
    CONSTRAINT ck_chunks_sequence_positive CHECK (((sequence IS NULL) OR (sequence > 0))),
    CONSTRAINT ck_chunks_stable_chunk_key_length CHECK (((stable_chunk_key IS NULL) OR (length((stable_chunk_key)::text) = 64)))
);
COMMENT ON COLUMN public.chunks.content IS 'Backward-compatible display_text used for UI, citations and bounded LLM context.';
COMMENT ON COLUMN public.chunks.markdown_content IS 'Exact canonical Markdown fragment for structure-aware chunks; legacy rows may contain synthetic Markdown.';
COMMENT ON COLUMN public.chunks.retrieval_text IS 'Normalized contextual text used for embedding, BM25 and hybrid retrieval.';
COMMENT ON COLUMN public.chunks.embedding_content_hash IS 'Versioned preprocessing hash; final embedding fingerprint additionally binds model profile metadata.';
COMMENT ON COLUMN public.chunks.display_markdown IS 'Deterministic Chunk-specific Markdown display projection; never an embedding or BM25 input.';
CREATE TABLE public.data_connections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    service_type character varying(32) NOT NULL,
    name character varying(255) NOT NULL,
    connection_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    credential_encrypted text,
    credential_secret_ref text,
    source_identity jsonb DEFAULT '{}'::jsonb NOT NULL,
    schedule_mode character varying(32) NOT NULL,
    cron_expression character varying(255),
    timezone character varying(100) DEFAULT 'Asia/Taipei'::character varying NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    last_sync_status character varying(32),
    last_synced_at timestamp with time zone,
    next_run_at timestamp with time zone,
    lock_version integer DEFAULT 1 NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_test_status character varying(32),
    last_tested_at timestamp with time zone,
    last_test_fingerprint character varying(64),
    last_test_latency_ms integer,
    last_test_detail_code character varying(100),
    last_test_actor_id uuid
);
CREATE TABLE public.data_sync_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    data_connection_id uuid NOT NULL,
    document_id uuid NOT NULL,
    trigger_type character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    content_fingerprint character varying(64),
    remote_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    document_version_id uuid,
    error_code character varying(100),
    error_summary text,
    retry_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    project_generation bigint DEFAULT 1 NOT NULL
);
CREATE TABLE public.deployment_bootstrap_evidence (
    release_id character varying(255) NOT NULL,
    contract_version integer NOT NULL,
    check_names jsonb NOT NULL,
    completed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT deployment_bootstrap_evidence_check_names_check CHECK ((jsonb_typeof(check_names) = 'array'::text)),
    CONSTRAINT deployment_bootstrap_evidence_contract_version_check CHECK ((contract_version > 0))
);
COMMENT ON TABLE public.deployment_bootstrap_evidence IS 'Secret-free evidence that a deployment release completed the non-HTTP bootstrap contract.';
CREATE TABLE public.document_reference_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    reference_id uuid NOT NULL,
    event_type character varying(50) NOT NULL,
    source_project_id uuid NOT NULL,
    source_document_id uuid NOT NULL,
    old_source_version_id uuid,
    new_source_version_id uuid,
    message text NOT NULL,
    is_read boolean DEFAULT false NOT NULL,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.document_references (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    target_project_id uuid NOT NULL,
    target_document_id uuid NOT NULL,
    source_project_id uuid NOT NULL,
    source_document_id uuid NOT NULL,
    source_version_id uuid NOT NULL,
    source_project_name_snapshot character varying(255) NOT NULL,
    source_document_name_snapshot character varying(500) NOT NULL,
    reference_mode character varying(32) DEFAULT 'linked'::character varying NOT NULL,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_synced_at timestamp with time zone
);
CREATE TABLE public.document_version_tags (
    document_version_id uuid NOT NULL,
    tag_id uuid NOT NULL,
    source character varying(32) DEFAULT 'manual'::character varying NOT NULL,
    confidence_score numeric(6,5),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.document_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    project_id uuid NOT NULL,
    version_major integer NOT NULL,
    extraction_revision integer NOT NULL,
    version_label character varying(50) NOT NULL,
    original_file_name character varying(255),
    canonical_extension character varying(16),
    mime_type character varying(255),
    file_size bigint,
    content_sha256 character varying(64),
    storage_name_salt character varying(128),
    storage_name_hash character varying(64),
    storage_bucket character varying(255),
    storage_key text,
    storage_etag character varying(255),
    uploaded_at timestamp with time zone,
    original_snapshot_uri text,
    markdown_artifact_uri text,
    extraction_artifact_uri text,
    parser_version character varying(100),
    ocr_model_id uuid,
    ocr_config_version integer,
    chunk_strategy jsonb DEFAULT '{}'::jsonb NOT NULL,
    chunk_size integer,
    chunk_overlap integer,
    embedding_model_id uuid,
    embedding_profile_id uuid,
    llm_model_id uuid,
    status character varying(50) NOT NULL,
    published_at timestamp with time zone,
    published_by uuid,
    inactive_reason character varying(255),
    source_document_id uuid,
    source_version_id uuid,
    source_snapshot_created_at timestamp with time zone,
    lock_version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    processed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT document_versions_extraction_revision_check CHECK ((extraction_revision >= 0)),
    CONSTRAINT document_versions_file_size_check CHECK (((file_size IS NULL) OR (file_size >= 0))),
    CONSTRAINT document_versions_version_major_check CHECK ((version_major > 0))
);
CREATE TABLE public.documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    document_code character varying(100) NOT NULL,
    title character varying(500) NOT NULL,
    description text,
    source_type character varying(50) NOT NULL,
    source_name character varying(255),
    source_uri text,
    source_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(32) DEFAULT 'inactive'::character varying NOT NULL,
    is_deleted boolean DEFAULT false NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by uuid,
    inactive_reason character varying(255),
    created_by uuid,
    owner_user_id uuid,
    last_updated_by uuid,
    lock_version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_imported_at timestamp with time zone,
    CONSTRAINT documents_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'inactive'::character varying, 'deleted'::character varying])::text[])))
);
CREATE TABLE public.embedding_build_vectors (
    id uuid NOT NULL,
    embedding_build_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    vector jsonb NOT NULL,
    vector_checksum character varying(64) NOT NULL,
    token_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);
CREATE TABLE public.embedding_builds (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    embedding_profile_id uuid NOT NULL,
    build_revision integer DEFAULT 1 NOT NULL,
    status character varying(32) NOT NULL,
    chunk_count integer DEFAULT 0 NOT NULL,
    index_name character varying(255),
    checksum character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    content_fingerprint character varying(64),
    model_id uuid,
    vector_dimension integer,
    token_count integer DEFAULT 0 NOT NULL,
    usage jsonb DEFAULT '{}'::jsonb NOT NULL,
    completed_at timestamp with time zone
);
CREATE TABLE public.embedding_profiles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    model_id uuid NOT NULL,
    model_version character varying(100) NOT NULL,
    vector_dimension integer NOT NULL,
    distance_method character varying(32) NOT NULL,
    chunk_strategy jsonb DEFAULT '{}'::jsonb NOT NULL,
    mapping_version integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT embedding_profiles_mapping_version_check CHECK ((mapping_version > 0)),
    CONSTRAINT embedding_profiles_vector_dimension_check CHECK ((vector_dimension > 0))
);
CREATE TABLE public.external_group_role_mappings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    external_group_id uuid NOT NULL,
    role_id uuid NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.external_group_users (
    external_group_id uuid NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.external_groups (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source character varying(32) NOT NULL,
    external_group_id character varying(255) NOT NULL,
    group_dn text,
    group_name character varying(255) NOT NULL,
    path text,
    is_active boolean DEFAULT true NOT NULL,
    last_synced_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    identity_origin character varying(32) DEFAULT 'keycloak_local'::character varying NOT NULL,
    CONSTRAINT external_groups_identity_origin_check CHECK (((identity_origin)::text = ANY ((ARRAY['ldap'::character varying, 'ad'::character varying, 'keycloak_local'::character varying])::text[])))
);
CREATE TABLE public.file_processing_executions (
    id uuid NOT NULL,
    run_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    kind character varying(16) NOT NULL,
    parent_id uuid,
    attempt integer NOT NULL,
    generation uuid NOT NULL,
    deployment_id uuid NOT NULL,
    project_generation bigint NOT NULL,
    state character varying(32) NOT NULL,
    policy_revision integer NOT NULL,
    policy_snapshot jsonb NOT NULL,
    policy_hash character varying(64) NOT NULL,
    input_hash character varying(64) NOT NULL,
    workload_id character varying(255),
    workload_uid character varying(255),
    image_digest character varying(255),
    profile character varying(100),
    phase character varying(32) NOT NULL,
    progress_revision bigint DEFAULT 0 NOT NULL,
    completed_units integer DEFAULT 0 NOT NULL,
    total_units integer,
    unit character varying(16),
    safe_error_code character varying(100),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    heartbeat_at timestamp with time zone,
    deadline_at timestamp with time zone,
    released_at timestamp with time zone,
    stop_evidence jsonb,
    output_evidence jsonb,
    CONSTRAINT ck_file_execution_parent CHECK (((((kind)::text = 'document'::text) AND (parent_id IS NULL)) OR (((kind)::text = 'parser'::text) AND (parent_id IS NOT NULL)))),
    CONSTRAINT ck_file_execution_release CHECK ((((released_at IS NULL) AND ((state)::text = ANY ((ARRAY['reserved'::character varying, 'starting'::character varying, 'running'::character varying, 'stopping'::character varying, 'recovery_required'::character varying])::text[]))) OR ((released_at IS NOT NULL) AND ((state)::text = ANY ((ARRAY['completed'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[])) AND (stop_evidence IS NOT NULL)))),
    CONSTRAINT file_processing_executions_attempt_check CHECK ((attempt > 0)),
    CONSTRAINT file_processing_executions_check CHECK ((total_units >= completed_units)),
    CONSTRAINT file_processing_executions_completed_units_check CHECK ((completed_units >= 0)),
    CONSTRAINT file_processing_executions_progress_revision_check CHECK ((progress_revision >= 0))
);
COMMENT ON TABLE public.file_processing_executions IS 'CHG-305 durable occupied slots; heartbeat expiry is not stop evidence. No destructive rollback.';
CREATE TABLE public.file_processing_policies (
    id integer NOT NULL,
    deployment_id uuid NOT NULL,
    revision integer NOT NULL,
    content_hash character varying(64) NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT file_processing_policies_id_check CHECK ((id = 1)),
    CONSTRAINT file_processing_policies_revision_check CHECK ((revision > 0))
);
CREATE TABLE public.file_processing_policy_revisions (
    revision integer NOT NULL,
    snapshot jsonb NOT NULL,
    content_hash character varying(64) NOT NULL,
    provenance jsonb NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT file_processing_policy_revisions_revision_check CHECK ((revision > 0))
);
COMMENT ON TABLE public.file_processing_policy_revisions IS 'CHG-305 immutable policy snapshots; current values reside in system_parameters.';
CREATE TABLE public.file_processing_pools (
    kind character varying(16) NOT NULL,
    CONSTRAINT file_processing_pools_kind_check CHECK (((kind)::text = ANY ((ARRAY['document'::character varying, 'parser'::character varying])::text[])))
);
CREATE TABLE public.file_processing_tasks (
    id uuid NOT NULL,
    execution_id uuid NOT NULL,
    generation uuid NOT NULL,
    broker_task_id uuid NOT NULL,
    claim_token uuid,
    state character varying(24) NOT NULL,
    disposition character varying(16),
    worker_identity character varying(255),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    heartbeat_at timestamp with time zone,
    finished_at timestamp with time zone,
    completion_receipt jsonb,
    CONSTRAINT ck_file_task_claim CHECK ((((state)::text = 'prepared'::text) OR (claim_token IS NOT NULL))),
    CONSTRAINT ck_file_task_completion CHECK ((((state)::text <> ALL ((ARRAY['quiescent'::character varying, 'finalized'::character varying])::text[])) OR ((disposition IS NOT NULL) AND (completion_receipt IS NOT NULL)))),
    CONSTRAINT ck_file_task_final CHECK ((((state)::text = 'finalized'::text) = (finished_at IS NOT NULL))),
    CONSTRAINT file_processing_tasks_disposition_check CHECK (((disposition)::text = ANY ((ARRAY['completed'::character varying, 'failed'::character varying, 'cancelled'::character varying, 'yield'::character varying])::text[]))),
    CONSTRAINT file_processing_tasks_state_check CHECK (((state)::text = ANY ((ARRAY['prepared'::character varying, 'claimed'::character varying, 'quiescent'::character varying, 'finalized'::character varying, 'recovery_required'::character varying])::text[])))
);
COMMENT ON TABLE public.file_processing_tasks IS 'CHG-305 task-specific completion; an expired heartbeat is never authority to recycle a document slot.';
CREATE TABLE public.file_scan_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_version_id uuid NOT NULL,
    scanner_type character varying(50) NOT NULL,
    status character varying(32) NOT NULL,
    safe_result_code character varying(100),
    safe_error_summary text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    quarantine_bucket character varying(255),
    quarantine_key text,
    accepted_bucket character varying(255),
    accepted_key text,
    content_type character varying(255),
    content_sha256 character varying(64),
    attempts integer DEFAULT 0 NOT NULL,
    available_at timestamp with time zone,
    claim_token uuid,
    claimed_at timestamp with time zone,
    lease_expires_at timestamp with time zone,
    quarantine_deleted_at timestamp with time zone,
    project_generation bigint DEFAULT 1 NOT NULL,
    CONSTRAINT file_scan_runs_status_check CHECK (((status)::text = ANY ((ARRAY['quarantine'::character varying, 'scanning'::character varying, 'accepted'::character varying, 'rejected'::character varying, 'failed'::character varying, 'disabled'::character varying])::text[])))
);
CREATE TABLE public.graph_sync_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    trigger_type character varying(50) NOT NULL,
    status character varying(32) NOT NULL,
    node_count integer DEFAULT 0 NOT NULL,
    edge_count integer DEFAULT 0 NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    parent_job_id uuid,
    requested_by_user_id uuid,
    request_id character varying(255),
    attempt integer DEFAULT 0 NOT NULL,
    error_code character varying(100),
    claim_token uuid,
    claimed_at timestamp with time zone,
    lease_expires_at timestamp with time zone,
    project_generation bigint DEFAULT 1 NOT NULL
);
CREATE TABLE public.idempotency_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scope character varying(100) NOT NULL,
    key character varying(255) NOT NULL,
    request_hash character varying(64) NOT NULL,
    status character varying(32) NOT NULL,
    response_status integer,
    response_summary jsonb,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);
CREATE TABLE public.identity_reauth_flows (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    subject character varying(255) NOT NULL,
    session_id character varying(255) NOT NULL,
    scope character varying(100) NOT NULL,
    state_digest character varying(64) NOT NULL,
    nonce_digest character varying(64) NOT NULL,
    pkce_verifier_encrypted text NOT NULL,
    issuer_url character varying(500) NOT NULL,
    jwks_url character varying(500) NOT NULL,
    client_id character varying(255) NOT NULL,
    redirect_uri character varying(1000) NOT NULL,
    return_path character varying(1000) NOT NULL,
    completion_token_digest character varying(64),
    authenticated_subject character varying(255),
    authenticated_session_id character varying(255),
    authenticated_auth_time timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    authenticated_at timestamp with time zone,
    consumed_at timestamp with time zone,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.identity_settings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    revision integer NOT NULL,
    state character varying(64) NOT NULL,
    configuration jsonb DEFAULT '{}'::jsonb NOT NULL,
    secret_configured boolean DEFAULT false NOT NULL,
    is_current boolean DEFAULT false NOT NULL,
    is_last_known_good boolean DEFAULT false NOT NULL,
    validated_at timestamp with time zone,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT identity_settings_state_check CHECK (((state)::text = ANY ((ARRAY['draft_unvalidated'::character varying, 'validated_active_locked'::character varying, 'temporarily_unlocked'::character varying])::text[])))
);
CREATE TABLE public.identity_sync_provider_results (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    run_id uuid NOT NULL,
    provider_id character varying(255) NOT NULL,
    provider_name character varying(255) NOT NULL,
    provider_vendor character varying(64) NOT NULL,
    requested_scope character varying(32) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    user_sync_status character varying(32) DEFAULT 'not_requested'::character varying NOT NULL,
    group_sync_status character varying(32) DEFAULT 'not_requested'::character varying NOT NULL,
    users_added integer DEFAULT 0 NOT NULL,
    users_updated integer DEFAULT 0 NOT NULL,
    users_removed integer DEFAULT 0 NOT NULL,
    users_failed integer DEFAULT 0 NOT NULL,
    users_ignored integer DEFAULT 0 NOT NULL,
    error_code character varying(100),
    started_at timestamp with time zone,
    heartbeat_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    user_sync_ignored boolean DEFAULT false NOT NULL,
    CONSTRAINT identity_sync_provider_results_counters_check CHECK (((users_added >= 0) AND (users_updated >= 0) AND (users_removed >= 0) AND (users_failed >= 0) AND (users_ignored >= 0))),
    CONSTRAINT identity_sync_provider_results_group_status_check CHECK (((group_sync_status)::text = ANY ((ARRAY['not_requested'::character varying, 'pending'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'skipped'::character varying])::text[]))),
    CONSTRAINT identity_sync_provider_results_scope_check CHECK (((requested_scope)::text = ANY ((ARRAY['people'::character varying, 'groups'::character varying, 'people_and_groups'::character varying])::text[]))),
    CONSTRAINT identity_sync_provider_results_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'skipped'::character varying])::text[]))),
    CONSTRAINT identity_sync_provider_results_user_status_check CHECK (((user_sync_status)::text = ANY ((ARRAY['not_requested'::character varying, 'pending'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'skipped'::character varying])::text[])))
);
COMMENT ON COLUMN public.identity_sync_provider_results.users_ignored IS 'Deprecated compatibility counter; always zero. Use user_sync_ignored.';
COMMENT ON COLUMN public.identity_sync_provider_results.user_sync_ignored IS 'Keycloak 26 SynchronizationResultRepresentation ignored boolean.';
CREATE TABLE public.identity_sync_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    users_created integer DEFAULT 0 NOT NULL,
    users_updated integer DEFAULT 0 NOT NULL,
    users_disabled integer DEFAULT 0 NOT NULL,
    groups_created integer DEFAULT 0 NOT NULL,
    groups_updated integer DEFAULT 0 NOT NULL,
    role_memberships_updated integer DEFAULT 0 NOT NULL,
    error_message text,
    trigger_type character varying(32) DEFAULT 'manual'::character varying NOT NULL,
    error_code character varying(100),
    attempt integer DEFAULT 0 NOT NULL,
    queued_at timestamp with time zone DEFAULT now() NOT NULL,
    heartbeat_at timestamp with time zone,
    lease_token uuid,
    requested_scope character varying(32) DEFAULT 'people_and_groups'::character varying NOT NULL,
    phase character varying(32) DEFAULT 'queued'::character varying NOT NULL,
    CONSTRAINT identity_sync_runs_phase_check CHECK (((phase)::text = ANY ((ARRAY['queued'::character varying, 'provider_discovery'::character varying, 'provider_user_sync'::character varying, 'provider_group_sync'::character varying, 'snapshot_fetch'::character varying, 'reconciliation'::character varying, 'completed'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT identity_sync_runs_requested_scope_check CHECK (((requested_scope)::text = ANY ((ARRAY['people'::character varying, 'groups'::character varying, 'people_and_groups'::character varying])::text[])))
);
CREATE TABLE public.identity_unlock_grants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    session_id character varying(255) NOT NULL,
    scope character varying(100) NOT NULL,
    auth_time timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.integration_client_project_scopes (
    client_id uuid NOT NULL,
    project_id uuid NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.integration_clients (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    api_key_hash character varying(64) NOT NULL,
    api_key_prefix character varying(24) NOT NULL,
    api_key_version integer DEFAULT 1 NOT NULL,
    contact_name character varying(255),
    contact_email character varying(320),
    contact_department character varying(255),
    valid_from timestamp with time zone,
    expires_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revoked_by uuid,
    revocation_reason text,
    rate_limit_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_used_at timestamp with time zone,
    last_used_project_id uuid,
    success_count integer DEFAULT 0 NOT NULL,
    failure_count integer DEFAULT 0 NOT NULL,
    created_by uuid,
    updated_by uuid,
    lock_version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT integration_clients_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'inactive'::character varying, 'revoked'::character varying])::text[])))
);
CREATE TABLE public.notification_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid,
    event_type character varying(100) NOT NULL,
    business_key character varying(255) NOT NULL,
    dedupe_key character varying(64) NOT NULL,
    recipient_user_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    terminal boolean DEFAULT false NOT NULL,
    status character varying(32) DEFAULT 'queued'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    error_code character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);
CREATE TABLE public.notifications (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    recipient_user_id uuid NOT NULL,
    project_id uuid,
    notification_type character varying(100) NOT NULL,
    severity character varying(32) NOT NULL,
    title character varying(500) NOT NULL,
    message text NOT NULL,
    action_type character varying(32),
    action_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_read boolean DEFAULT false NOT NULL,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source_event_id uuid,
    business_key character varying(255),
    resolved_reason character varying(100)
);
CREATE TABLE public.outbox_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    topic character varying(150) NOT NULL,
    aggregate_type character varying(100) NOT NULL,
    aggregate_id uuid NOT NULL,
    payload jsonb NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    available_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    processed_at timestamp with time zone,
    last_error text,
    claim_token uuid,
    claimed_at timestamp with time zone,
    lease_expires_at timestamp with time zone,
    task_id character varying(255),
    project_id uuid,
    project_generation bigint
);
CREATE TABLE public.pipeline_run_steps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    run_id uuid NOT NULL,
    step_name character varying(100) NOT NULL,
    status character varying(32) NOT NULL,
    progress_percent numeric(5,2) DEFAULT 0 NOT NULL,
    progress_message text,
    waiting_role character varying(100),
    action_url text,
    retry_count integer DEFAULT 0 NOT NULL,
    input_artifact_ref text,
    output_artifact_ref text,
    model_id uuid,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    error_message text,
    claim_token uuid,
    claimed_at timestamp with time zone,
    lease_expires_at timestamp with time zone,
    artifact_fingerprint character varying(64),
    artifact_payload jsonb
);
CREATE TABLE public.pipeline_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    document_id uuid,
    document_version_id uuid,
    run_type character varying(50) NOT NULL,
    status character varying(32) NOT NULL,
    progress_percent numeric(5,2) DEFAULT 0 NOT NULL,
    current_step_name character varying(100),
    current_waiting_role character varying(100),
    current_action_url text,
    estimated_remaining_seconds integer,
    triggered_by uuid,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    project_generation bigint DEFAULT 1 NOT NULL
);
CREATE TABLE public.project_archive_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    status character varying(32) DEFAULT 'queued'::character varying NOT NULL,
    requested_by uuid NOT NULL,
    queued_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    heartbeat_at timestamp with time zone,
    completed_at timestamp with time zone,
    lease_token uuid,
    lease_expires_at timestamp with time zone,
    attempt integer DEFAULT 0 NOT NULL,
    unfinished_version_count integer DEFAULT 0 NOT NULL,
    deleted_version_count integer DEFAULT 0 NOT NULL,
    deleted_document_count integer DEFAULT 0 NOT NULL,
    deleted_s3_object_count integer DEFAULT 0 NOT NULL,
    deleted_search_document_count integer DEFAULT 0 NOT NULL,
    deleted_graph_version_count integer DEFAULT 0 NOT NULL,
    checkpoint jsonb DEFAULT '{}'::jsonb NOT NULL,
    error_code character varying(100),
    error_message text,
    project_generation bigint DEFAULT 1 NOT NULL,
    CONSTRAINT project_archive_runs_attempt_check CHECK ((attempt >= 0)),
    CONSTRAINT project_archive_runs_deleted_document_count_check CHECK ((deleted_document_count >= 0)),
    CONSTRAINT project_archive_runs_deleted_graph_version_count_check CHECK ((deleted_graph_version_count >= 0)),
    CONSTRAINT project_archive_runs_deleted_s3_object_count_check CHECK ((deleted_s3_object_count >= 0)),
    CONSTRAINT project_archive_runs_deleted_search_document_count_check CHECK ((deleted_search_document_count >= 0)),
    CONSTRAINT project_archive_runs_deleted_version_count_check CHECK ((deleted_version_count >= 0)),
    CONSTRAINT project_archive_runs_status_check CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT project_archive_runs_unfinished_version_count_check CHECK ((unfinished_version_count >= 0))
);
CREATE TABLE public.project_members (
    project_id uuid NOT NULL,
    user_id uuid NOT NULL,
    project_role character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT project_members_project_role_check CHECK (((project_role)::text = ANY ((ARRAY['owner'::character varying, 'editor'::character varying, 'viewer'::character varying])::text[])))
);
CREATE TABLE public.project_owners (
    project_id uuid NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.projects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    status character varying(32) DEFAULT 'active'::character varying NOT NULL,
    llm_model_id uuid,
    embedding_model_id uuid,
    created_by uuid,
    lock_version integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    ocr_model_id uuid,
    archived_at timestamp with time zone,
    archived_by uuid,
    work_generation bigint DEFAULT 1 NOT NULL,
    CONSTRAINT projects_archive_metadata_check CHECK (((((status)::text = 'active'::text) AND (archived_at IS NULL) AND (archived_by IS NULL)) OR (((status)::text = 'archived'::text) AND (archived_at IS NOT NULL) AND (archived_by IS NOT NULL)))),
    CONSTRAINT projects_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'archived'::character varying])::text[])))
);
CREATE TABLE public.public_api_request_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    integration_client_id uuid NOT NULL,
    project_id uuid NOT NULL,
    request_id character varying(255),
    endpoint character varying(120) NOT NULL,
    response_mode character varying(32) NOT NULL,
    result character varying(32) NOT NULL,
    http_status integer NOT NULL,
    end_user_employee_id character varying(100) NOT NULL,
    end_user_employee_name character varying(255),
    end_user_department character varying(255),
    question text,
    answer text,
    citations jsonb DEFAULT '[]'::jsonb NOT NULL,
    selected_document_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    selected_document_version_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    retrieval_strategy character varying(32),
    retrieval_status character varying(32),
    llm_model_id uuid,
    prompt_version character varying(100),
    system_prompt_source character varying(32),
    system_prompt_version_id uuid,
    system_prompt_content_hash character varying(64),
    system_prompt_layers jsonb,
    token_usage jsonb,
    latency_ms integer,
    error_code character varying(100),
    error_message text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    lifecycle_status character varying(32) DEFAULT 'answered'::character varying NOT NULL,
    request_hash character varying(64),
    idempotency_key_hash character varying(64),
    end_user_identity_hash character varying(64),
    question_encrypted text,
    answer_encrypted text,
    citations_encrypted text,
    end_user_metadata_encrypted text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    content_expires_at timestamp with time zone,
    retention_expires_at timestamp with time zone,
    legal_hold boolean DEFAULT false NOT NULL,
    redacted_at timestamp with time zone,
    deleted_at timestamp with time zone
);
CREATE TABLE public.review_records (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    document_id uuid NOT NULL,
    document_version_id uuid NOT NULL,
    review_stage character varying(32) NOT NULL,
    reviewer_id uuid NOT NULL,
    delegated_from_user_id uuid,
    status character varying(32) NOT NULL,
    comment text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.revoked_auth_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    token_identity character varying(64) NOT NULL,
    token_digest character varying(64) NOT NULL,
    issuer character varying(500) NOT NULL,
    subject character varying(255) NOT NULL,
    audience character varying(500) NOT NULL,
    token_id character varying(255),
    session_id character varying(255),
    issued_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone NOT NULL,
    revoked_by uuid,
    reason character varying(64) NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL
);
CREATE TABLE public.role_permissions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    role_id uuid NOT NULL,
    module_name character varying(100) NOT NULL,
    function_name character varying(100) NOT NULL,
    can_view boolean DEFAULT false NOT NULL,
    can_create boolean DEFAULT false NOT NULL,
    can_edit boolean DEFAULT false NOT NULL,
    can_delete boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    can_execute boolean DEFAULT false NOT NULL
);
CREATE TABLE public.role_users (
    role_id uuid NOT NULL,
    user_id uuid NOT NULL,
    source character varying(32) DEFAULT 'manual'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT role_users_source_check CHECK (((source)::text = ANY ((ARRAY['manual'::character varying, 'external_sync'::character varying, 'break_glass'::character varying])::text[])))
);
CREATE TABLE public.roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    is_system boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    lock_version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by uuid,
    CONSTRAINT roles_deleted_inactive_check CHECK (((deleted_at IS NULL) OR (is_active = false)))
);
CREATE TABLE public.session_expired_form_drafts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    form_key character varying(120) NOT NULL,
    return_path text NOT NULL,
    nonce_hash character varying(64) NOT NULL,
    payload_encrypted text NOT NULL,
    field_count integer DEFAULT 0 NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    restored_at timestamp with time zone,
    discarded_at timestamp with time zone
);
CREATE TABLE public.system_initialization_state (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    deployment_mode character varying(32) DEFAULT 'appliance'::character varying NOT NULL,
    status character varying(64) DEFAULT 'not_started'::character varying NOT NULL,
    lock_state character varying(64) DEFAULT 'first_run_open'::character varying NOT NULL,
    current_revision integer DEFAULT 0 NOT NULL,
    last_known_good_revision integer,
    candidate_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    readiness_summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    completed_at timestamp with time zone,
    locked_at timestamp with time zone,
    unlocked_by uuid,
    unlock_expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_known_good_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_known_good_readiness jsonb DEFAULT '{}'::jsonb NOT NULL
);
CREATE TABLE public.system_initialization_steps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    initialization_state_id uuid NOT NULL,
    step_key character varying(100) NOT NULL,
    status character varying(32) NOT NULL,
    detail_code character varying(100) NOT NULL,
    safe_summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    audit_log_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.system_parameters (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    key character varying(100) NOT NULL,
    value jsonb NOT NULL,
    default_value jsonb NOT NULL,
    value_type character varying(32) NOT NULL,
    unit character varying(32),
    description text NOT NULL,
    updated_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.system_prompt_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    prompt_id uuid NOT NULL,
    version_number integer NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    content_hash character varying(64) NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    change_reason text,
    created_by uuid,
    request_id character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT system_prompt_versions_content_length_check CHECK ((char_length(content) <= 8000))
);
CREATE TABLE public.system_prompts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    prompt_scope character varying(16) NOT NULL,
    model_type character varying(32) NOT NULL,
    model_id uuid,
    is_active boolean DEFAULT false NOT NULL,
    current_version_id uuid,
    lock_version integer DEFAULT 1 NOT NULL,
    created_by uuid,
    updated_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT system_prompts_model_type_check CHECK (((model_type)::text = ANY ((ARRAY['Chat'::character varying, 'Judge'::character varying])::text[]))),
    CONSTRAINT system_prompts_scope_check CHECK (((prompt_scope)::text = ANY ((ARRAY['global'::character varying, 'model'::character varying])::text[]))),
    CONSTRAINT system_prompts_scope_model_check CHECK (((((prompt_scope)::text = 'global'::text) AND (model_id IS NULL)) OR (((prompt_scope)::text = 'model'::text) AND (model_id IS NOT NULL))))
);
CREATE TABLE public.tags (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    employee_id character varying(10),
    keycloak_user_id character varying(255) NOT NULL,
    ldap_dn text,
    email character varying(320),
    display_name character varying(255) NOT NULL,
    department character varying(255),
    title character varying(255),
    auth_source character varying(32) DEFAULT 'keycloak'::character varying NOT NULL,
    manager_user_id uuid,
    manager_delegate_user_id uuid,
    manager_delegate_start_at timestamp with time zone,
    manager_delegate_end_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    last_synced_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    knowledge_owner boolean DEFAULT false NOT NULL,
    system_notes text,
    given_name character varying(255),
    family_name character varying(255),
    CONSTRAINT users_employee_id_check CHECK (((employee_id IS NULL) OR ((employee_id)::text ~ '^Z.{0,9}$'::text)))
);
COMMENT ON COLUMN public.users.given_name IS 'Keycloak firstName synchronized as the locale-neutral given name.';
COMMENT ON COLUMN public.users.family_name IS 'Keycloak lastName synchronized as the locale-neutral family name.';
CREATE TABLE public.validation_questions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    question text NOT NULL,
    expected_answer text,
    expected_keywords jsonb,
    category character varying(100),
    priority character varying(32),
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.validation_run_items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    run_id uuid NOT NULL,
    question text NOT NULL,
    expected_answer text,
    expected_keywords jsonb,
    selected_document_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    answer text,
    reference_docs jsonb DEFAULT '[]'::jsonb NOT NULL,
    chat_record_id uuid,
    status character varying(32) NOT NULL,
    score numeric(8,5),
    evaluation_reason text,
    error_message text,
    latency_ms integer,
    token_usage jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    system_prompt_source character varying(32),
    system_prompt_version_id uuid,
    system_prompt_content_hash character varying(64),
    system_prompt_layers jsonb,
    category character varying(100),
    priority character varying(32),
    parent_item_id uuid,
    attempt integer DEFAULT 1 NOT NULL,
    is_current boolean DEFAULT true NOT NULL,
    error_code character varying(100),
    input_item_id uuid NOT NULL,
    input_ordinal integer NOT NULL,
    input_content_hash character varying(64) NOT NULL
);
CREATE TABLE public.validation_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    uploaded_file_name character varying(255),
    status character varying(32) NOT NULL,
    run_scope character varying(32) NOT NULL,
    approval_task_id uuid,
    document_version_id uuid,
    embedding_model character varying(255),
    llm_model character varying(255),
    selected_document_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    total_count integer DEFAULT 0 NOT NULL,
    completed_count integer DEFAULT 0 NOT NULL,
    failed_count integer DEFAULT 0 NOT NULL,
    created_by uuid NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    project_generation bigint DEFAULT 1 NOT NULL,
    execution_manifest jsonb NOT NULL,
    execution_manifest_hash character varying(64) NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    CONSTRAINT validation_runs_max_attempts_check CHECK (((max_attempts >= 1) AND (max_attempts <= 10)))
);
ALTER TABLE ONLY public.active_version_manifests
    ADD CONSTRAINT active_version_manifests_document_id_key UNIQUE (document_id);
ALTER TABLE ONLY public.active_version_manifests
    ADD CONSTRAINT active_version_manifests_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.ai_models
    ADD CONSTRAINT ai_models_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.approval_evidence_manifests
    ADD CONSTRAINT approval_evidence_manifests_approval_request_id_key UNIQUE (approval_request_id);
ALTER TABLE ONLY public.approval_evidence_manifests
    ADD CONSTRAINT approval_evidence_manifests_manifest_hash_key UNIQUE (manifest_hash);
ALTER TABLE ONLY public.approval_evidence_manifests
    ADD CONSTRAINT approval_evidence_manifests_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.approval_tasks
    ADD CONSTRAINT approval_tasks_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.chat_feedback_events
    ADD CONSTRAINT chat_feedback_events_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.chat_records
    ADD CONSTRAINT chat_records_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.chunk_tags
    ADD CONSTRAINT chunk_tags_pkey PRIMARY KEY (chunk_id, tag_id);
ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.data_connections
    ADD CONSTRAINT data_connections_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.data_sync_runs
    ADD CONSTRAINT data_sync_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.deployment_bootstrap_evidence
    ADD CONSTRAINT deployment_bootstrap_evidence_pkey PRIMARY KEY (release_id);
ALTER TABLE ONLY public.document_reference_events
    ADD CONSTRAINT document_reference_events_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.document_references
    ADD CONSTRAINT document_references_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.document_references
    ADD CONSTRAINT document_references_target_project_id_source_project_id_sou_key UNIQUE (target_project_id, source_project_id, source_document_id);
ALTER TABLE ONLY public.document_version_tags
    ADD CONSTRAINT document_version_tags_pkey PRIMARY KEY (document_version_id, tag_id);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_document_id_version_major_extraction_revi_key UNIQUE (document_id, version_major, extraction_revision);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_project_id_document_code_key UNIQUE (project_id, document_code);
ALTER TABLE ONLY public.embedding_build_vectors
    ADD CONSTRAINT embedding_build_vectors_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.embedding_builds
    ADD CONSTRAINT embedding_builds_document_version_id_embedding_profile_id_b_key UNIQUE (document_version_id, embedding_profile_id, build_revision);
ALTER TABLE ONLY public.embedding_builds
    ADD CONSTRAINT embedding_builds_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.embedding_profiles
    ADD CONSTRAINT embedding_profiles_model_id_model_version_vector_dimension__key UNIQUE (model_id, model_version, vector_dimension, distance_method, mapping_version);
ALTER TABLE ONLY public.embedding_profiles
    ADD CONSTRAINT embedding_profiles_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.external_group_role_mappings
    ADD CONSTRAINT external_group_role_mappings_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.external_group_users
    ADD CONSTRAINT external_group_users_pkey PRIMARY KEY (external_group_id, user_id);
ALTER TABLE ONLY public.external_groups
    ADD CONSTRAINT external_groups_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.external_groups
    ADD CONSTRAINT external_groups_source_external_group_id_key UNIQUE (source, external_group_id);
ALTER TABLE ONLY public.file_processing_executions
    ADD CONSTRAINT file_processing_executions_generation_key UNIQUE (generation);
ALTER TABLE ONLY public.file_processing_executions
    ADD CONSTRAINT file_processing_executions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.file_processing_policies
    ADD CONSTRAINT file_processing_policies_deployment_id_key UNIQUE (deployment_id);
ALTER TABLE ONLY public.file_processing_policies
    ADD CONSTRAINT file_processing_policies_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.file_processing_policy_revisions
    ADD CONSTRAINT file_processing_policy_revisions_pkey PRIMARY KEY (revision);
ALTER TABLE ONLY public.file_processing_pools
    ADD CONSTRAINT file_processing_pools_pkey PRIMARY KEY (kind);
ALTER TABLE ONLY public.file_processing_tasks
    ADD CONSTRAINT file_processing_tasks_broker_task_id_key UNIQUE (broker_task_id);
ALTER TABLE ONLY public.file_processing_tasks
    ADD CONSTRAINT file_processing_tasks_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.file_scan_runs
    ADD CONSTRAINT file_scan_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.graph_sync_jobs
    ADD CONSTRAINT graph_sync_jobs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.idempotency_keys
    ADD CONSTRAINT idempotency_keys_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.idempotency_keys
    ADD CONSTRAINT idempotency_keys_scope_key_key UNIQUE (scope, key);
ALTER TABLE ONLY public.identity_reauth_flows
    ADD CONSTRAINT identity_reauth_flows_completion_token_digest_key UNIQUE (completion_token_digest);
ALTER TABLE ONLY public.identity_reauth_flows
    ADD CONSTRAINT identity_reauth_flows_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.identity_reauth_flows
    ADD CONSTRAINT identity_reauth_flows_state_digest_key UNIQUE (state_digest);
ALTER TABLE ONLY public.identity_settings
    ADD CONSTRAINT identity_settings_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.identity_settings
    ADD CONSTRAINT identity_settings_revision_key UNIQUE (revision);
ALTER TABLE ONLY public.identity_sync_provider_results
    ADD CONSTRAINT identity_sync_provider_results_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.identity_sync_runs
    ADD CONSTRAINT identity_sync_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.identity_unlock_grants
    ADD CONSTRAINT identity_unlock_grants_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.integration_client_project_scopes
    ADD CONSTRAINT integration_client_project_scopes_pkey PRIMARY KEY (client_id, project_id);
ALTER TABLE ONLY public.integration_clients
    ADD CONSTRAINT integration_clients_api_key_hash_key UNIQUE (api_key_hash);
ALTER TABLE ONLY public.integration_clients
    ADD CONSTRAINT integration_clients_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.notification_events
    ADD CONSTRAINT notification_events_dedupe_key_key UNIQUE (dedupe_key);
ALTER TABLE ONLY public.notification_events
    ADD CONSTRAINT notification_events_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT outbox_events_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.pipeline_run_steps
    ADD CONSTRAINT pipeline_run_steps_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.pipeline_run_steps
    ADD CONSTRAINT pipeline_run_steps_run_id_step_name_key UNIQUE (run_id, step_name);
ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.project_archive_runs
    ADD CONSTRAINT project_archive_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_pkey PRIMARY KEY (project_id, user_id, project_role);
ALTER TABLE ONLY public.project_owners
    ADD CONSTRAINT project_owners_pkey PRIMARY KEY (project_id, user_id);
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.public_api_request_logs
    ADD CONSTRAINT public_api_request_logs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.revoked_auth_tokens
    ADD CONSTRAINT revoked_auth_tokens_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.revoked_auth_tokens
    ADD CONSTRAINT revoked_auth_tokens_token_identity_key UNIQUE (token_identity);
ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_module_name_function_name_key UNIQUE (role_id, module_name, function_name);
ALTER TABLE ONLY public.role_users
    ADD CONSTRAINT role_users_pkey PRIMARY KEY (role_id, user_id, source);
ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.session_expired_form_drafts
    ADD CONSTRAINT session_expired_form_drafts_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.system_initialization_state
    ADD CONSTRAINT system_initialization_state_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.system_initialization_steps
    ADD CONSTRAINT system_initialization_steps_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.system_parameters
    ADD CONSTRAINT system_parameters_key_key UNIQUE (key);
ALTER TABLE ONLY public.system_parameters
    ADD CONSTRAINT system_parameters_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.system_prompt_versions
    ADD CONSTRAINT system_prompt_versions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.system_prompts
    ADD CONSTRAINT system_prompts_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_project_id_name_key UNIQUE (project_id, name);
ALTER TABLE ONLY public.embedding_build_vectors
    ADD CONSTRAINT uq_embedding_build_vectors_build_chunk UNIQUE (embedding_build_id, chunk_id);
ALTER TABLE ONLY public.embedding_build_vectors
    ADD CONSTRAINT uq_embedding_build_vectors_build_index UNIQUE (embedding_build_id, chunk_index);
ALTER TABLE ONLY public.external_group_role_mappings
    ADD CONSTRAINT uq_external_group_role_mappings_external_group UNIQUE (external_group_id);
ALTER TABLE ONLY public.external_group_role_mappings
    ADD CONSTRAINT uq_external_group_role_mappings_role UNIQUE (role_id);
ALTER TABLE ONLY public.file_processing_executions
    ADD CONSTRAINT uq_file_execution_attempt UNIQUE (run_id, kind, attempt);
ALTER TABLE ONLY public.identity_sync_provider_results
    ADD CONSTRAINT uq_identity_sync_provider_results_run_provider UNIQUE (run_id, provider_id);
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT uq_notifications_source_event_recipient UNIQUE (source_event_id, recipient_user_id);
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT uq_project_members_project_user UNIQUE (project_id, user_id);
COMMENT ON CONSTRAINT uq_project_members_project_user ON public.project_members IS 'CHG-291: a user has exactly one Owner, Editor, or Viewer role per project';
ALTER TABLE ONLY public.system_prompt_versions
    ADD CONSTRAINT uq_system_prompt_versions_number UNIQUE (prompt_id, version_number);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_employee_id_key UNIQUE (employee_id);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_keycloak_user_id_key UNIQUE (keycloak_user_id);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.validation_questions
    ADD CONSTRAINT validation_questions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.validation_run_items
    ADD CONSTRAINT validation_run_items_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.validation_runs
    ADD CONSTRAINT validation_runs_pkey PRIMARY KEY (id);
CREATE INDEX idx_chat_records_document_scope ON public.chat_records USING btree (project_id, document_version_id, scope_mode, asked_at);
CREATE INDEX idx_chat_records_scope_history ON public.chat_records USING btree (project_id, created_by, scope_mode, conversation_id, created_at);
CREATE INDEX idx_chat_records_visible_conversation ON public.chat_records USING btree (project_id, created_by, conversation_id, created_at DESC) WHERE (deleted_at IS NULL);
CREATE INDEX ix_ai_model_usage_events_client_created ON public.ai_model_usage_events USING btree (integration_client_id, created_at);
CREATE INDEX ix_ai_model_usage_events_created ON public.ai_model_usage_events USING btree (created_at);
CREATE INDEX ix_ai_model_usage_events_model_created ON public.ai_model_usage_events USING btree (model_id, created_at);
CREATE INDEX ix_ai_model_usage_events_project_created ON public.ai_model_usage_events USING btree (project_id, created_at);
CREATE INDEX ix_ai_model_usage_events_purpose_created ON public.ai_model_usage_events USING btree (usage_purpose, created_at);
CREATE INDEX ix_ai_models_last_test_status ON public.ai_models USING btree (last_test_status);
CREATE INDEX ix_ai_models_live_type_name ON public.ai_models USING btree (model_type, name, id) WHERE (deleted_at IS NULL);
CREATE INDEX ix_approval_evidence_version_submitted ON public.approval_evidence_manifests USING btree (document_version_id, submitted_at);
CREATE INDEX ix_approval_requests_status_submitted ON public.approval_requests USING btree (status, submitted_at DESC, id DESC);
CREATE INDEX ix_approval_requests_submitter_submitted ON public.approval_requests USING btree (submitter_id, submitted_at DESC, id DESC);
CREATE INDEX ix_approval_tasks_assignee_status_submitted ON public.approval_tasks USING btree (assignee_user_id, status, submitted_at DESC, id DESC);
CREATE INDEX ix_approval_tasks_project_status_submitted ON public.approval_tasks USING btree (project_id, status, submitted_at DESC, id DESC);
CREATE INDEX ix_audit_logs_cursor ON public.audit_logs USING btree (created_at DESC, id DESC);
CREATE INDEX ix_chat_feedback_events_chat_record_created ON public.chat_feedback_events USING btree (chat_record_id, created_at);
CREATE INDEX ix_chat_feedback_events_idempotency ON public.chat_feedback_events USING btree (integration_client_id, idempotency_key_hash);
CREATE INDEX ix_chat_feedback_events_public_response_created ON public.chat_feedback_events USING btree (public_response_id, created_at);
CREATE INDEX ix_chunks_lineage_revision ON public.chunks USING btree (lineage_id, revision DESC, created_at DESC, id);
CREATE INDEX ix_chunks_version_sequence ON public.chunks USING btree (document_version_id, sequence) WHERE (sequence IS NOT NULL);
CREATE INDEX ix_chunks_version_stable_key ON public.chunks USING btree (document_version_id, stable_chunk_key) WHERE (stable_chunk_key IS NOT NULL);
CREATE INDEX ix_data_connections_last_test_status ON public.data_connections USING btree (last_test_status);
CREATE INDEX ix_document_versions_project_published ON public.document_versions USING btree (project_id, updated_at DESC, id) WHERE (published_at IS NOT NULL);
CREATE INDEX ix_document_versions_status ON public.document_versions USING btree (project_id, status);
CREATE INDEX ix_documents_project_visible ON public.documents USING btree (project_id, updated_at DESC, id) WHERE (is_deleted = false);
CREATE INDEX ix_embedding_build_vectors_build ON public.embedding_build_vectors USING btree (embedding_build_id, chunk_index);
CREATE INDEX ix_file_execution_occupancy ON public.file_processing_executions USING btree (kind, released_at);
CREATE INDEX ix_file_scan_runs_available ON public.file_scan_runs USING btree (status, available_at);
CREATE INDEX ix_file_task_state ON public.file_processing_tasks USING btree (state, updated_at);
CREATE INDEX ix_graph_sync_jobs_parent_attempt ON public.graph_sync_jobs USING btree (parent_job_id, created_at, id) WHERE (parent_job_id IS NOT NULL);
CREATE INDEX ix_graph_sync_jobs_project_status_created ON public.graph_sync_jobs USING btree (project_id, status, created_at DESC, id);
CREATE INDEX ix_identity_reauth_flows_expires_at ON public.identity_reauth_flows USING btree (expires_at);
CREATE INDEX ix_identity_reauth_flows_user_session_scope ON public.identity_reauth_flows USING btree (user_id, session_id, scope);
CREATE INDEX ix_identity_sync_provider_results_run_created ON public.identity_sync_provider_results USING btree (run_id, created_at, provider_id);
CREATE INDEX ix_identity_sync_runs_status_queued_at ON public.identity_sync_runs USING btree (status, queued_at DESC);
CREATE INDEX ix_identity_unlock_active ON public.identity_unlock_grants USING btree (user_id, session_id, expires_at) WHERE (revoked_at IS NULL);
CREATE INDEX ix_integration_clients_status ON public.integration_clients USING btree (status);
CREATE INDEX ix_notification_events_status_created ON public.notification_events USING btree (status, created_at, id);
CREATE INDEX ix_notifications_business_recipient_open ON public.notifications USING btree (business_key, recipient_user_id, resolved_at);
CREATE INDEX ix_outbox_dispatch_available ON public.outbox_events USING btree (status, available_at, lease_expires_at);
CREATE INDEX ix_outbox_events_project_generation_status ON public.outbox_events USING btree (project_id, project_generation, status, available_at, id);
CREATE INDEX ix_outbox_pending ON public.outbox_events USING btree (status, available_at) WHERE ((status)::text = 'pending'::text);
CREATE INDEX ix_project_archive_runs_project_queued ON public.project_archive_runs USING btree (project_id, queued_at DESC, id DESC);
CREATE INDEX ix_project_members_user_role_project ON public.project_members USING btree (user_id, project_role, project_id);
CREATE INDEX ix_projects_ocr_model_id ON public.projects USING btree (ocr_model_id);
CREATE INDEX ix_projects_status_name ON public.projects USING btree (status, name, id);
CREATE INDEX ix_projects_status_updated ON public.projects USING btree (status, updated_at DESC, id);
CREATE INDEX ix_public_api_request_logs_client_created ON public.public_api_request_logs USING btree (integration_client_id, created_at);
CREATE INDEX ix_public_api_request_logs_idempotency ON public.public_api_request_logs USING btree (integration_client_id, idempotency_key_hash);
CREATE INDEX ix_public_api_request_logs_lifecycle ON public.public_api_request_logs USING btree (lifecycle_status, created_at);
CREATE INDEX ix_public_api_request_logs_project_created ON public.public_api_request_logs USING btree (project_id, created_at);
CREATE INDEX ix_public_api_request_logs_retention ON public.public_api_request_logs USING btree (legal_hold, content_expires_at, retention_expires_at);
CREATE INDEX ix_revoked_auth_tokens_expires_at ON public.revoked_auth_tokens USING btree (expires_at);
CREATE INDEX ix_revoked_auth_tokens_subject_session ON public.revoked_auth_tokens USING btree (subject, session_id);
CREATE INDEX ix_roles_undeleted_name_id ON public.roles USING btree (name, id) WHERE (deleted_at IS NULL);
CREATE INDEX ix_session_expired_form_drafts_expires_at ON public.session_expired_form_drafts USING btree (expires_at);
CREATE INDEX ix_session_expired_form_drafts_user_status ON public.session_expired_form_drafts USING btree (user_id, status);
CREATE INDEX ix_system_initialization_steps_state_created ON public.system_initialization_steps USING btree (initialization_state_id, created_at);
CREATE INDEX ix_users_email ON public.users USING btree (email);
CREATE INDEX ix_validation_items_parent_attempt ON public.validation_run_items USING btree (parent_item_id, attempt);
CREATE INDEX ix_validation_items_run_current_created ON public.validation_run_items USING btree (run_id, is_current, created_at, id);
CREATE INDEX ix_validation_items_run_ordinal ON public.validation_run_items USING btree (run_id, input_ordinal, attempt, id);
CREATE UNIQUE INDEX uq_active_approval_version ON public.approval_requests USING btree (document_version_id) WHERE ((status)::text = ANY ((ARRAY['pending_manager_review'::character varying, 'pending_owner_review'::character varying, 'approved'::character varying])::text[]));
CREATE UNIQUE INDEX uq_ai_models_active_name_type ON public.ai_models USING btree (name, model_type) WHERE (deleted_at IS NULL);
CREATE UNIQUE INDEX uq_ai_models_default_type ON public.ai_models USING btree (model_type) WHERE (is_active AND is_default AND (deleted_at IS NULL));
CREATE UNIQUE INDEX uq_chunks_active_version_index ON public.chunks USING btree (document_version_id, chunk_index) WHERE ((status)::text = 'active'::text);
CREATE UNIQUE INDEX uq_embedding_builds_canonical ON public.embedding_builds USING btree (document_version_id, embedding_profile_id, content_fingerprint) WHERE (content_fingerprint IS NOT NULL);
CREATE UNIQUE INDEX uq_file_execution_active ON public.file_processing_executions USING btree (run_id, kind) WHERE (released_at IS NULL);
CREATE UNIQUE INDEX uq_file_task_active ON public.file_processing_tasks USING btree (execution_id) WHERE (finished_at IS NULL);
CREATE UNIQUE INDEX uq_identity_settings_current ON public.identity_settings USING btree (is_current) WHERE is_current;
CREATE UNIQUE INDEX uq_identity_sync_runs_single_active ON public.identity_sync_runs USING btree ((true)) WHERE ((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying])::text[]));
CREATE UNIQUE INDEX uq_outbox_secure_ingestion_topic_aggregate ON public.outbox_events USING btree (topic, aggregate_id) WHERE ((topic)::text = ANY ((ARRAY['file.scan.requested'::character varying, 'document.extraction.requested'::character varying])::text[]));
CREATE UNIQUE INDEX uq_project_archive_runs_open_project ON public.project_archive_runs USING btree (project_id) WHERE ((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying])::text[]));
CREATE UNIQUE INDEX uq_roles_undeleted_name ON public.roles USING btree (name) WHERE (deleted_at IS NULL);
CREATE UNIQUE INDEX uq_system_initialization_singleton ON public.system_initialization_state USING btree ((true));
CREATE UNIQUE INDEX uq_system_prompts_global_type ON public.system_prompts USING btree (model_type) WHERE ((prompt_scope)::text = 'global'::text);
CREATE UNIQUE INDEX uq_system_prompts_model_id ON public.system_prompts USING btree (model_id) WHERE ((prompt_scope)::text = 'model'::text);
CREATE UNIQUE INDEX uq_validation_items_run_input_attempt ON public.validation_run_items USING btree (run_id, input_item_id, attempt);
CREATE UNIQUE INDEX uq_validation_items_run_ordinal_attempt ON public.validation_run_items USING btree (run_id, input_ordinal, attempt);
ALTER TABLE ONLY public.active_version_manifests
    ADD CONSTRAINT active_version_manifests_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.active_version_manifests
    ADD CONSTRAINT active_version_manifests_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.active_version_manifests
    ADD CONSTRAINT active_version_manifests_embedding_build_id_fkey FOREIGN KEY (embedding_build_id) REFERENCES public.embedding_builds(id);
ALTER TABLE ONLY public.active_version_manifests
    ADD CONSTRAINT active_version_manifests_embedding_profile_id_fkey FOREIGN KEY (embedding_profile_id) REFERENCES public.embedding_profiles(id);
ALTER TABLE ONLY public.active_version_manifests
    ADD CONSTRAINT active_version_manifests_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_chat_record_id_fkey FOREIGN KEY (chat_record_id) REFERENCES public.chat_records(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_integration_client_id_fkey FOREIGN KEY (integration_client_id) REFERENCES public.integration_clients(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_pipeline_run_id_fkey FOREIGN KEY (pipeline_run_id) REFERENCES public.pipeline_runs(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_pipeline_step_id_fkey FOREIGN KEY (pipeline_step_id) REFERENCES public.pipeline_run_steps(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_public_api_request_log_id_fkey FOREIGN KEY (public_api_request_log_id) REFERENCES public.public_api_request_logs(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_validation_run_id_fkey FOREIGN KEY (validation_run_id) REFERENCES public.validation_runs(id);
ALTER TABLE ONLY public.ai_model_usage_events
    ADD CONSTRAINT ai_model_usage_events_validation_run_item_id_fkey FOREIGN KEY (validation_run_item_id) REFERENCES public.validation_run_items(id);
ALTER TABLE ONLY public.ai_models
    ADD CONSTRAINT ai_models_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.ai_models
    ADD CONSTRAINT ai_models_last_test_actor_id_fkey FOREIGN KEY (last_test_actor_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.approval_evidence_manifests
    ADD CONSTRAINT approval_evidence_manifests_approval_request_id_fkey FOREIGN KEY (approval_request_id) REFERENCES public.approval_requests(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.approval_evidence_manifests
    ADD CONSTRAINT approval_evidence_manifests_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.approval_evidence_manifests
    ADD CONSTRAINT approval_evidence_manifests_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.approval_evidence_manifests
    ADD CONSTRAINT approval_evidence_manifests_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.approval_evidence_manifests
    ADD CONSTRAINT approval_evidence_manifests_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT approval_requests_submitter_id_fkey FOREIGN KEY (submitter_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.approval_tasks
    ADD CONSTRAINT approval_tasks_approval_request_id_fkey FOREIGN KEY (approval_request_id) REFERENCES public.approval_requests(id);
ALTER TABLE ONLY public.approval_tasks
    ADD CONSTRAINT approval_tasks_assignee_user_id_fkey FOREIGN KEY (assignee_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.approval_tasks
    ADD CONSTRAINT approval_tasks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.approval_tasks
    ADD CONSTRAINT approval_tasks_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.approval_tasks
    ADD CONSTRAINT approval_tasks_original_manager_user_id_fkey FOREIGN KEY (original_manager_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.approval_tasks
    ADD CONSTRAINT approval_tasks_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.approval_tasks
    ADD CONSTRAINT approval_tasks_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.approval_tasks
    ADD CONSTRAINT approval_tasks_submitter_id_fkey FOREIGN KEY (submitter_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.chat_feedback_events
    ADD CONSTRAINT chat_feedback_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.chat_feedback_events
    ADD CONSTRAINT chat_feedback_events_chat_record_id_fkey FOREIGN KEY (chat_record_id) REFERENCES public.chat_records(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.chat_feedback_events
    ADD CONSTRAINT chat_feedback_events_integration_client_id_fkey FOREIGN KEY (integration_client_id) REFERENCES public.integration_clients(id);
ALTER TABLE ONLY public.chat_feedback_events
    ADD CONSTRAINT chat_feedback_events_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.chat_feedback_events
    ADD CONSTRAINT chat_feedback_events_public_response_id_fkey FOREIGN KEY (public_response_id) REFERENCES public.public_api_request_logs(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.chat_records
    ADD CONSTRAINT chat_records_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.chat_records
    ADD CONSTRAINT chat_records_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.chat_records
    ADD CONSTRAINT chat_records_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.chat_records
    ADD CONSTRAINT chat_records_embedding_model_id_fkey FOREIGN KEY (embedding_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.chat_records
    ADD CONSTRAINT chat_records_llm_model_id_fkey FOREIGN KEY (llm_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.chat_records
    ADD CONSTRAINT chat_records_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.chat_records
    ADD CONSTRAINT chat_records_system_prompt_version_id_fkey FOREIGN KEY (system_prompt_version_id) REFERENCES public.system_prompt_versions(id);
ALTER TABLE ONLY public.chunk_tags
    ADD CONSTRAINT chunk_tags_chunk_id_fkey FOREIGN KEY (chunk_id) REFERENCES public.chunks(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.chunk_tags
    ADD CONSTRAINT chunk_tags_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.chunk_tags
    ADD CONSTRAINT chunk_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_edited_by_fkey FOREIGN KEY (edited_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_embedding_model_id_fkey FOREIGN KEY (embedding_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_parent_chunk_id_fkey FOREIGN KEY (parent_chunk_id) REFERENCES public.chunks(id);
ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_superseded_by_id_fkey FOREIGN KEY (superseded_by_id) REFERENCES public.chunks(id);
ALTER TABLE ONLY public.data_connections
    ADD CONSTRAINT data_connections_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.data_connections
    ADD CONSTRAINT data_connections_last_test_actor_id_fkey FOREIGN KEY (last_test_actor_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.data_connections
    ADD CONSTRAINT data_connections_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.data_sync_runs
    ADD CONSTRAINT data_sync_runs_data_connection_id_fkey FOREIGN KEY (data_connection_id) REFERENCES public.data_connections(id);
ALTER TABLE ONLY public.data_sync_runs
    ADD CONSTRAINT data_sync_runs_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.data_sync_runs
    ADD CONSTRAINT data_sync_runs_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.document_reference_events
    ADD CONSTRAINT document_reference_events_new_source_version_id_fkey FOREIGN KEY (new_source_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.document_reference_events
    ADD CONSTRAINT document_reference_events_old_source_version_id_fkey FOREIGN KEY (old_source_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.document_reference_events
    ADD CONSTRAINT document_reference_events_reference_id_fkey FOREIGN KEY (reference_id) REFERENCES public.document_references(id);
ALTER TABLE ONLY public.document_reference_events
    ADD CONSTRAINT document_reference_events_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.document_reference_events
    ADD CONSTRAINT document_reference_events_source_project_id_fkey FOREIGN KEY (source_project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.document_references
    ADD CONSTRAINT document_references_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.document_references
    ADD CONSTRAINT document_references_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.document_references
    ADD CONSTRAINT document_references_source_project_id_fkey FOREIGN KEY (source_project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.document_references
    ADD CONSTRAINT document_references_source_version_id_fkey FOREIGN KEY (source_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.document_references
    ADD CONSTRAINT document_references_target_document_id_fkey FOREIGN KEY (target_document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.document_references
    ADD CONSTRAINT document_references_target_project_id_fkey FOREIGN KEY (target_project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.document_version_tags
    ADD CONSTRAINT document_version_tags_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.document_version_tags
    ADD CONSTRAINT document_version_tags_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.document_version_tags
    ADD CONSTRAINT document_version_tags_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_embedding_model_id_fkey FOREIGN KEY (embedding_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_embedding_profile_id_fkey FOREIGN KEY (embedding_profile_id) REFERENCES public.embedding_profiles(id);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_llm_model_id_fkey FOREIGN KEY (llm_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_ocr_model_id_fkey FOREIGN KEY (ocr_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_published_by_fkey FOREIGN KEY (published_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_source_version_id_fkey FOREIGN KEY (source_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_last_updated_by_fkey FOREIGN KEY (last_updated_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.embedding_build_vectors
    ADD CONSTRAINT embedding_build_vectors_chunk_id_fkey FOREIGN KEY (chunk_id) REFERENCES public.chunks(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.embedding_build_vectors
    ADD CONSTRAINT embedding_build_vectors_embedding_build_id_fkey FOREIGN KEY (embedding_build_id) REFERENCES public.embedding_builds(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.embedding_builds
    ADD CONSTRAINT embedding_builds_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.embedding_builds
    ADD CONSTRAINT embedding_builds_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.embedding_builds
    ADD CONSTRAINT embedding_builds_embedding_profile_id_fkey FOREIGN KEY (embedding_profile_id) REFERENCES public.embedding_profiles(id);
ALTER TABLE ONLY public.embedding_builds
    ADD CONSTRAINT embedding_builds_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.embedding_builds
    ADD CONSTRAINT embedding_builds_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.embedding_profiles
    ADD CONSTRAINT embedding_profiles_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.external_group_role_mappings
    ADD CONSTRAINT external_group_role_mappings_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.external_group_role_mappings
    ADD CONSTRAINT external_group_role_mappings_external_group_id_fkey FOREIGN KEY (external_group_id) REFERENCES public.external_groups(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.external_group_role_mappings
    ADD CONSTRAINT external_group_role_mappings_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.external_group_users
    ADD CONSTRAINT external_group_users_external_group_id_fkey FOREIGN KEY (external_group_id) REFERENCES public.external_groups(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.external_group_users
    ADD CONSTRAINT external_group_users_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.file_processing_executions
    ADD CONSTRAINT file_processing_executions_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.file_processing_executions
    ADD CONSTRAINT file_processing_executions_kind_fkey FOREIGN KEY (kind) REFERENCES public.file_processing_pools(kind);
ALTER TABLE ONLY public.file_processing_executions
    ADD CONSTRAINT file_processing_executions_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.file_processing_executions(id);
ALTER TABLE ONLY public.file_processing_executions
    ADD CONSTRAINT file_processing_executions_policy_revision_fkey FOREIGN KEY (policy_revision) REFERENCES public.file_processing_policy_revisions(revision);
ALTER TABLE ONLY public.file_processing_executions
    ADD CONSTRAINT file_processing_executions_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.pipeline_runs(id);
ALTER TABLE ONLY public.file_processing_policy_revisions
    ADD CONSTRAINT file_processing_policy_revisions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.file_processing_tasks
    ADD CONSTRAINT file_processing_tasks_execution_id_fkey FOREIGN KEY (execution_id) REFERENCES public.file_processing_executions(id);
ALTER TABLE ONLY public.file_processing_tasks
    ADD CONSTRAINT file_processing_tasks_generation_fkey FOREIGN KEY (generation) REFERENCES public.file_processing_executions(generation);
ALTER TABLE ONLY public.file_scan_runs
    ADD CONSTRAINT file_scan_runs_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT fk_approval_current_task FOREIGN KEY (current_task_id) REFERENCES public.approval_tasks(id);
ALTER TABLE ONLY public.system_prompts
    ADD CONSTRAINT fk_system_prompts_current_version FOREIGN KEY (current_version_id) REFERENCES public.system_prompt_versions(id);
ALTER TABLE ONLY public.graph_sync_jobs
    ADD CONSTRAINT graph_sync_jobs_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.graph_sync_jobs
    ADD CONSTRAINT graph_sync_jobs_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.graph_sync_jobs
    ADD CONSTRAINT graph_sync_jobs_parent_job_id_fkey FOREIGN KEY (parent_job_id) REFERENCES public.graph_sync_jobs(id);
ALTER TABLE ONLY public.graph_sync_jobs
    ADD CONSTRAINT graph_sync_jobs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.graph_sync_jobs
    ADD CONSTRAINT graph_sync_jobs_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.identity_reauth_flows
    ADD CONSTRAINT identity_reauth_flows_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.identity_settings
    ADD CONSTRAINT identity_settings_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.identity_sync_provider_results
    ADD CONSTRAINT identity_sync_provider_results_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.identity_sync_runs(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.identity_unlock_grants
    ADD CONSTRAINT identity_unlock_grants_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.integration_client_project_scopes
    ADD CONSTRAINT integration_client_project_scopes_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.integration_clients(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.integration_client_project_scopes
    ADD CONSTRAINT integration_client_project_scopes_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.integration_client_project_scopes
    ADD CONSTRAINT integration_client_project_scopes_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.integration_clients
    ADD CONSTRAINT integration_clients_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.integration_clients
    ADD CONSTRAINT integration_clients_last_used_project_id_fkey FOREIGN KEY (last_used_project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.integration_clients
    ADD CONSTRAINT integration_clients_revoked_by_fkey FOREIGN KEY (revoked_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.integration_clients
    ADD CONSTRAINT integration_clients_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.notification_events
    ADD CONSTRAINT notification_events_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_recipient_user_id_fkey FOREIGN KEY (recipient_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_source_event_id_fkey FOREIGN KEY (source_event_id) REFERENCES public.notification_events(id);
ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT outbox_events_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.pipeline_run_steps
    ADD CONSTRAINT pipeline_run_steps_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.pipeline_run_steps
    ADD CONSTRAINT pipeline_run_steps_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.pipeline_runs(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_triggered_by_fkey FOREIGN KEY (triggered_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.project_archive_runs
    ADD CONSTRAINT project_archive_runs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.project_archive_runs
    ADD CONSTRAINT project_archive_runs_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.project_owners
    ADD CONSTRAINT project_owners_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.project_owners
    ADD CONSTRAINT project_owners_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_archived_by_fkey FOREIGN KEY (archived_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_embedding_model_id_fkey FOREIGN KEY (embedding_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_llm_model_id_fkey FOREIGN KEY (llm_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_ocr_model_id_fkey FOREIGN KEY (ocr_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.public_api_request_logs
    ADD CONSTRAINT public_api_request_logs_integration_client_id_fkey FOREIGN KEY (integration_client_id) REFERENCES public.integration_clients(id);
ALTER TABLE ONLY public.public_api_request_logs
    ADD CONSTRAINT public_api_request_logs_llm_model_id_fkey FOREIGN KEY (llm_model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.public_api_request_logs
    ADD CONSTRAINT public_api_request_logs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.public_api_request_logs
    ADD CONSTRAINT public_api_request_logs_system_prompt_version_id_fkey FOREIGN KEY (system_prompt_version_id) REFERENCES public.system_prompt_versions(id);
ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_delegated_from_user_id_fkey FOREIGN KEY (delegated_from_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id);
ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.review_records
    ADD CONSTRAINT review_records_reviewer_id_fkey FOREIGN KEY (reviewer_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.revoked_auth_tokens
    ADD CONSTRAINT revoked_auth_tokens_revoked_by_fkey FOREIGN KEY (revoked_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.role_permissions
    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.role_users
    ADD CONSTRAINT role_users_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.role_users
    ADD CONSTRAINT role_users_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_deleted_by_fkey FOREIGN KEY (deleted_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.session_expired_form_drafts
    ADD CONSTRAINT session_expired_form_drafts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.system_initialization_state
    ADD CONSTRAINT system_initialization_state_unlocked_by_fkey FOREIGN KEY (unlocked_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.system_initialization_steps
    ADD CONSTRAINT system_initialization_steps_audit_log_id_fkey FOREIGN KEY (audit_log_id) REFERENCES public.audit_logs(id);
ALTER TABLE ONLY public.system_initialization_steps
    ADD CONSTRAINT system_initialization_steps_initialization_state_id_fkey FOREIGN KEY (initialization_state_id) REFERENCES public.system_initialization_state(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.system_parameters
    ADD CONSTRAINT system_parameters_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.system_prompt_versions
    ADD CONSTRAINT system_prompt_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.system_prompt_versions
    ADD CONSTRAINT system_prompt_versions_prompt_id_fkey FOREIGN KEY (prompt_id) REFERENCES public.system_prompts(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.system_prompts
    ADD CONSTRAINT system_prompts_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.system_prompts
    ADD CONSTRAINT system_prompts_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.ai_models(id);
ALTER TABLE ONLY public.system_prompts
    ADD CONSTRAINT system_prompts_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_manager_delegate_user_id_fkey FOREIGN KEY (manager_delegate_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_manager_user_id_fkey FOREIGN KEY (manager_user_id) REFERENCES public.users(id);
ALTER TABLE ONLY public.validation_questions
    ADD CONSTRAINT validation_questions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.validation_questions
    ADD CONSTRAINT validation_questions_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
ALTER TABLE ONLY public.validation_run_items
    ADD CONSTRAINT validation_run_items_chat_record_id_fkey FOREIGN KEY (chat_record_id) REFERENCES public.chat_records(id);
ALTER TABLE ONLY public.validation_run_items
    ADD CONSTRAINT validation_run_items_parent_item_id_fkey FOREIGN KEY (parent_item_id) REFERENCES public.validation_run_items(id);
ALTER TABLE ONLY public.validation_run_items
    ADD CONSTRAINT validation_run_items_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.validation_runs(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.validation_run_items
    ADD CONSTRAINT validation_run_items_system_prompt_version_id_fkey FOREIGN KEY (system_prompt_version_id) REFERENCES public.system_prompt_versions(id);
ALTER TABLE ONLY public.validation_runs
    ADD CONSTRAINT validation_runs_approval_task_id_fkey FOREIGN KEY (approval_task_id) REFERENCES public.approval_tasks(id);
ALTER TABLE ONLY public.validation_runs
    ADD CONSTRAINT validation_runs_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
ALTER TABLE ONLY public.validation_runs
    ADD CONSTRAINT validation_runs_document_version_id_fkey FOREIGN KEY (document_version_id) REFERENCES public.document_versions(id);
ALTER TABLE ONLY public.validation_runs
    ADD CONSTRAINT validation_runs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nomosmart') THEN
        RAISE EXCEPTION 'required CloudNativePG application role nomosmart is missing';
    END IF;
END
$$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE nomosmart TO nomosmart;
GRANT USAGE ON SCHEMA public TO nomosmart;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nomosmart;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO nomosmart;
ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nomosmart;
ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO nomosmart;

-- Initial roles, permissions and non-secret settings.
INSERT INTO public.roles (name, description, is_active, is_system, lock_version) VALUES ('knowledge-project-user', 'View knowledge projects and receive project-scoped roles', true, false, 1);
INSERT INTO public.roles (name, description, is_active, is_system, lock_version) VALUES ('system-admin', 'System administration', true, true, 1);
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Menu', 'KnowledgeProjects', true, false, false, false, false FROM public.roles WHERE name = 'knowledge-project-user';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Chat', 'ChatVerification', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Chat', 'ValidationQuestion', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Chat', 'ValidationRun', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Document', 'DocumentActivation', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Document', 'DocumentImport', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Document', 'DocumentReview', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Document', 'DocumentVersion', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Knowledge', 'ChunkEditing', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Knowledge', 'KnowledgeExtraction', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Knowledge', 'KnowledgeGraph', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Knowledge', 'TagManagement', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Menu', 'KnowledgeProjects', true, true, false, false, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Menu', 'Reports', true, false, false, false, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Menu', 'SystemManagement', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Notification', 'NotificationCenter', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Project', 'EmbeddingSettings', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Project', 'ProjectArchive', false, false, false, false, true FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Project', 'ProjectList', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Project', 'ProjectMembers', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Project', 'ProjectSettings', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Report', 'ModelReport', true, false, false, false, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Review', 'ApprovalDetail', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'Review', 'ApprovalWorkspace', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'System', 'AIModelSettings', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'System', 'PermissionSettings', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'System', 'RoleManagement', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'System', 'SystemLogs', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.role_permissions (role_id, module_name, function_name, can_view, can_create, can_edit, can_delete, can_execute) SELECT id, 'System', 'UserManagement', true, true, true, true, false FROM public.roles WHERE name = 'system-admin';
INSERT INTO public.system_parameters (key, value, default_value, value_type, unit, description) VALUES ('default_timezone', '"Asia/Taipei"'::jsonb, '"Asia/Taipei"'::jsonb, 'iana_timezone', NULL, 'Default IANA timezone');
INSERT INTO public.system_parameters (key, value, default_value, value_type, unit, description) VALUES ('max_upload_size_mb', '100'::jsonb, '100'::jsonb, 'integer', 'MB', 'Maximum size of one uploaded document');
INSERT INTO public.system_parameters (key, value, default_value, value_type, unit, description) VALUES ('session_expired_form_draft_ttl_minutes', '30'::jsonb, '30'::jsonb, 'integer', 'minutes', 'Retention for encrypted session-expired form drafts');
INSERT INTO public.system_parameters (key, value, default_value, value_type, unit, description) VALUES ('staging_index_ttl_days', '7'::jsonb, '7'::jsonb, 'integer', 'days', 'Retention for rejected staging index data');
INSERT INTO public.file_processing_pools(kind) VALUES ('document');
INSERT INTO public.file_processing_pools(kind) VALUES ('parser');
INSERT INTO public.audit_logs(action, resource_type, result, summary) VALUES ('migration.nomosmart_0_1_0.baseline', 'system', 'success', '{"baseline":"B051","release":"0.1.0"}'::jsonb);
