// Graph, serving, chat, validation, report, notification and system parameter types (split from lib/api.ts, OPT424-038).

export type ProjectGraphResponse = {
  project_id: string | null;
  nodes: { id: string; type: string; label: string; metadata: Record<string, unknown> }[];
  edges: { id: string; source: string; target: string; type: string; metadata?: Record<string, unknown> }[];
  truncated: boolean;
  node_limit: number;
};

export type ProjectServingStatusResponse = {
  project_id: string;
  readiness: "ready" | "empty" | "partial";
  active_document_count: number;
  ready_index_count: number;
  graph_ready_count: number;
  documents: {
    document_id: string;
    document_title: string;
    document_version_id: string;
    version_label: string;
    publication_generation: number;
    chunk_count: number;
    index_ready: boolean;
    graph_sync_status: string | null;
    graph_node_count: number | null;
    graph_edge_count: number | null;
  }[];
  /** Present only when cursor or limit is sent (OPT424-015, D424-15); null on the last page. */
  next_cursor?: string | null;
};

export type ProjectChatQueryResponse = {
  chat_record_id?: string | null;
  conversation_id?: string | null;
  conversation_title?: string | null;
  answer: string;
  citations: {
    document_id: string;
    document_version_id: string;
    chunk_id: string;
    chunk_index?: number | null;
    title: string | null;
    score: number | null;
    content?: string | null;
    display_markdown?: string | null;
    markdown_content?: string | null;
    excerpt?: string | null;
    content_type?: string | null;
    page?: number | null;
    source_mapping?: unknown[];
    index_name?: string | null;
  }[];
  manifest_version_ids: string[];
  selected_version_ids?: string[];
  status?: "answered" | "no_answer";
  retrieval_strategy?: "keyword" | "vector" | "hybrid";
  prompt_version?: string | null;
  system_prompt_source?: string | null;
  system_prompt_version_id?: string | null;
  system_prompt_content_hash?: string | null;
  system_prompt_layers?: Array<Record<string, unknown>> | null;
  llm_model_id?: string | null;
  token_usage?: Record<string, unknown> | null;
  latency_ms?: number | null;
};
export type ProjectChatCitation = ProjectChatQueryResponse["citations"][number];
export type ProjectChatRecordResponse = {
  id: string;
  conversation_id: string;
  conversation_title: string | null;
  scope_mode?: "published" | "document_staging" | null;
  selected_document_version_ids: string[];
  question: string;
  answer: string | null;
  citations: ProjectChatCitation[];
  evaluation: "correct" | "needs_revision" | "not_evaluated";
  revision_suggestion: string | null;
  llm_model_id: string | null;
  prompt_version: string | null;
  system_prompt_source?: string | null;
  system_prompt_version_id?: string | null;
  system_prompt_content_hash?: string | null;
  system_prompt_layers?: Array<Record<string, unknown>> | null;
  token_usage: Record<string, unknown> | null;
  latency_ms: number | null;
  asked_at: string;
  answered_at: string | null;
};
export type ProjectChatConversationResponse = {
  id: string;
  title: string;
  scope_mode?: "published" | "document_staging" | null;
  selected_document_version_ids: string[];
  message_count: number;
  updated_at: string;
  can_continue: boolean;
  created_by_user_id?: string | null;
  created_by_display_name?: string | null;
  is_mine?: boolean;
  can_delete?: boolean;
  can_evaluate?: boolean;
  can_export?: boolean;
  read_only_reason?: string | null;
  records: ProjectChatRecordResponse[];
};
export type ProjectChatConversationPage = {
  items: ProjectChatConversationResponse[];
  has_more: boolean; next_cursor: string | null;
};
export type ProjectChatConversationDeleteResponse = {
  conversation_id: string;
  deleted_count: number;
  deleted_at: string;
};
export type ValidationRunResponse = {
  id: string;
  project_id: string;
  uploaded_file_name: string | null;
  status: "queued" | "running" | "completed" | "partial_failed" | "failed" | "cancelled";
  run_scope: string;
  selected_document_ids: string[];
  execution_manifest: Record<string, unknown>;
  execution_manifest_hash: string;
  max_attempts: number;
  total_count: number;
  completed_count: number;
  failed_count: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  items: {
    id: string;
    parent_item_id: string | null;
    attempt: number;
    is_current: boolean;
    input_item_id: string;
    input_ordinal: number;
    input_content_hash: string;
    question: string;
    expected_answer: string | null;
    expected_keywords: string[] | null;
    selected_document_ids: string[];
    category: string | null;
    priority: string | null;
    answer: string | null;
    citations: ProjectChatCitation[];
    chat_record_id: string | null;
    status: "pending" | "running" | "passed" | "failed" | "needs_review" | "error" | "completed" | "skipped" | "cancelled";
    score: number | null;
    evaluation_reason: string | null;
    error_message: string | null;
    error_code: string | null;
    latency_ms: number | null;
    token_usage: Record<string, unknown> | null;
    system_prompt_source?: string | null;
    system_prompt_version_id?: string | null;
    system_prompt_content_hash?: string | null;
    system_prompt_layers?: Array<Record<string, unknown>> | null;
  }[];
};

export type ReportMetricCard = { key: string; label: string; value: number; unit: string | null };
export type ReportProjectRankingItem = { project_id: string; project_name: string; chat_count: number; validation_run_count: number; citation_count: number };
export type ReportSummaryResponse = {
  topic: string;
  date_from: string | null;
  date_to: string | null;
  project_id: string | null;
  scope: string;
  page: number;
  page_size: number;
  total_rows: number;
  total_pages: number;
  metrics: ReportMetricCard[];
  project_rankings: ReportProjectRankingItem[];
  columns: string[];
  rows: Record<string, string | number | boolean | null>[];
  status: "live" | "empty" | "partial";
  partial_reasons: string[];
};
export type ReportFilterOptionsResponse = {
  selected_scope: string;
  scopes: Array<{ value: string; project_count: number }>;
  projects: Array<{ id: string; name: string }>;
};

export type NotificationResponse = {
  id: string;
  recipient_user_id: string;
  project_id: string | null;
  notification_type: string;
  severity: string;
  title: string;
  message: string;
  action_type: string | null;
  action_payload: Record<string, unknown>;
  is_read: boolean;
  resolved_at: string | null;
  created_at: string;
  can_resolve_manual?: boolean;
  resolution_block_reason?: string | null;
};

export type NotificationCountResponse = {
  unread_count: number;
};

export type SystemParametersPayload = {
  max_upload_size_mb: number;
  default_timezone: string;
  staging_index_ttl_days: number;
  session_expired_form_draft_ttl_minutes: number;
  ocr_page_max_output_tokens: number;
  ocr_request_max_output_tokens: number;
  ocr_token_budget_policy: string;
  ocr_document_max_tokens: number;
  ocr_token_defaults: { ocr_page_max_output_tokens: number; ocr_request_max_output_tokens: number; ocr_document_max_tokens: number };
  ocr_token_settings_hash: string;
  section_revisions: Record<"general" | "documents", string>;
  parameter_defaults: SystemParameterApiValues;
  parameter_metadata: Record<string, { updated_at: string | null; updated_by: string | null }>;
  deployment_max_upload_size_mb: number;
};

export type SystemParameterApiValues = Pick<SystemParametersPayload, "max_upload_size_mb" | "default_timezone" | "staging_index_ttl_days" | "session_expired_form_draft_ttl_minutes" | "ocr_request_max_output_tokens" | "ocr_document_max_tokens">;
export type SystemParameterSectionResponse = { section: "general" | "documents"; revision: string; changed: boolean; values: Partial<SystemParameterApiValues>; defaults: Partial<SystemParameterApiValues>; parameter_metadata: SystemParametersPayload["parameter_metadata"] };

export type SystemParametersUpdatePayload = Pick<SystemParametersPayload, "max_upload_size_mb" | "default_timezone" | "staging_index_ttl_days" | "session_expired_form_draft_ttl_minutes"> & {
  ocr_page_max_output_tokens?: number;
  ocr_request_max_output_tokens?: number;
  ocr_document_max_tokens?: number;
  expected_ocr_token_settings_hash?: string;
  expected_section_revisions: Record<"general" | "documents", string>;
};

export type UploadConfigResponse = {
  max_upload_size_mb: number;
  deployment_max_upload_size_mb: number;
};

export type SessionDraftRestoreResponse = {
  draft_id: string;
  form_key: string;
  return_path: string;
  payload: Record<string, unknown>;
  expires_at: string;
};



export type BreakGlassStatusResponse = {
  username: string | null;
  status: "configured_disabled" | "not_configured" | "attention_required" | "unavailable";
  detail_code: string;
  configured: boolean;
  enabled: boolean | null;
  local_account: boolean | null;
  system_admin_mapped: boolean | null;
  credential_update_required: boolean | null;
  required_actions: string[];
  credential_source: string;
  runbook_evidence: string;
  alerting_evidence: string;
  lifecycle_control: string;
  checked_at: string;
};

export type AIModelPayload = {
  name: string;
  model_type?: string;
  provider: string;
  endpoint?: string | null;
  api_key?: string | null;
  api_key_secret_ref?: string | null;
  clear_credential?: boolean;
  credential_clear_confirmation?: string;
  is_active?: boolean;
  is_default?: boolean;
  config?: Record<string, unknown>;
};
export type AIModelUpdatePayload = Partial<AIModelPayload>;

export type SystemPromptPayload = {
  prompt_scope: "global" | "model";
  model_type: "Chat" | "Judge";
  model_id?: string | null;
  content?: string;
  is_active?: boolean;
  change_reason?: string | null;
};

export type SystemPromptVersionPayload = {
  content: string;
  is_active?: boolean;
  change_reason?: string | null;
};
