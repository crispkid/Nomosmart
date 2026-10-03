import { apiBaseUrl } from "@/lib/oidc";

export type PermissionAction = "view" | "create" | "edit" | "delete" | "execute";
export type PermissionGrant = {
  module_name: string;
  function_name: string;
  can_view: boolean;
  can_create: boolean;
  can_edit: boolean;
  can_delete: boolean;
  can_execute: boolean;
};

export type CurrentUser = {
  user_id: string;
  subject: string;
  employee_id: string | null;
  email: string | null;
  given_name: string | null;
  family_name: string | null;
  display_name: string | null;
  groups: string[];
  permissions: PermissionGrant[];
  visible_project_ids: string[];
};

export type ApiError = Error & { status: number; code: string; details?: unknown; requestId?: string };
export type ApiFetch = (input: string, init?: RequestInit) => Promise<Response>;

export function can(grants: PermissionGrant[], moduleName: string, functionName: string, action: PermissionAction): boolean {
  const key = `can_${action}` as const;
  return grants.some((grant) => grant.module_name === moduleName && grant.function_name === functionName && grant[key]);
}

export function canAnyView(grants: PermissionGrant[], moduleName: string): boolean {
  return grants.some((grant) => grant.module_name === moduleName && grant.can_view);
}

export async function apiJson<T>(apiFetch: ApiFetch, path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(`${apiBaseUrl()}${path}`, { ...init, cache: "no-store" });
  if (!response.ok) {
    throw await apiResponseError(response);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}

async function apiResponseError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => ({})) as { code?: string; message?: string; details?: unknown; request_id?: string };
  const error = new Error(body.message || `API request failed with ${response.status}`) as ApiError;
  error.status = response.status;
  error.code = body.code || "api_error";
  error.details = body.details;
  error.requestId = body.request_id;
  return error;
}

export type UserSummary = {
  id: string;
  employee_id: string | null;
  keycloak_user_id: string;
  email: string | null;
  given_name: string | null;
  family_name: string | null;
  display_name: string;
  department: string | null;
  title: string | null;
  auth_source: string;
  is_active: boolean;
  knowledge_owner: boolean;
  system_notes: string | null;
  last_synced_at: string | null;
};

export type RoleResponse = {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  is_system: boolean;
  lock_version: number;
};

export type PermissionValue = {
  module_name: string;
  function_name: string;
  can_view: boolean;
  can_create: boolean;
  can_edit: boolean;
  can_delete: boolean;
  can_execute: boolean;
};

export type PermissionMatrixResponse = { lock_version: number; permissions: PermissionValue[] };
export type RoleUsersResponse = { lock_version: number; users: { user_id: string; source: string }[] };
export type ExternalGroupResponse = { id: string; source: string; external_group_id: string; group_dn: string | null; group_name: string; path: string | null; identity_origin: "ldap" | "ad" | "keycloak_local"; is_active: boolean; last_synced_at: string | null; member_count: number; mapped_role_id: string | null };
export type ExternalGroupRoleMapping = { external_group_id: string; role_id: string };
export type RoleExternalGroupMappingResponse = { role_id: string; external_group_id: string | null; lock_version: number; derived_member_count: number };
export type IdentitySyncProviderResultResponse = { id: string; provider_id: string; provider_name: string; provider_vendor: string; requested_scope: "people" | "groups" | "people_and_groups"; status: string; user_sync_status: string; group_sync_status: string; users_added: number; users_updated: number; users_removed: number; users_failed: number; users_ignored: number; user_sync_ignored: boolean; error_code: string | null; started_at: string | null; heartbeat_at: string | null; completed_at: string | null };
export type IdentitySyncRunResponse = { id: string; source: string; status: string; trigger_type: string; requested_scope: "people" | "groups" | "people_and_groups"; phase: string; queued_at: string; started_at: string | null; heartbeat_at: string | null; completed_at: string | null; users_created: number; users_updated: number; users_disabled: number; groups_created: number; groups_updated: number; role_memberships_updated: number; error_message: string | null; error_code: string | null; attempt: number; provider_results: IdentitySyncProviderResultResponse[] };
export type DirectoryProviderResponse = { id: string; name: string; vendor: string; enabled: boolean; custom_user_search_filter: string; config_hash: string; checked_at: string };

export type OperationComponentStatus = {
  name: string;
  status: "healthy" | "degraded" | "unavailable" | string;
  detail_code: string;
  checked_at: string;
  metrics: Record<string, string | number | boolean | null>;
};

export type OperationRecentError = {
  source: string;
  action: string;
  result: string;
  detail_code: string;
  created_at: string;
};

export type OperationsStatusResponse = {
  status: "healthy" | "degraded" | "unavailable" | string;
  generated_at: string;
  dependencies: OperationComponentStatus[];
  providers: OperationComponentStatus[];
  worker: OperationComponentStatus;
  queue: OperationComponentStatus;
  retrieval: OperationComponentStatus;
  recent_errors: OperationRecentError[];
};

export type AIModelResponse = {
  id: string;
  name: string;
  model_type: "Chat" | "Embedding" | "OCR" | "Judge" | string;
  provider: string;
  endpoint: string | null;
  api_key_configured: boolean;
  api_key_secret_ref: string | null;
  is_active: boolean;
  is_default: boolean;
  config: Record<string, unknown>;
  config_version: number;
  last_test_status: string | null;
  last_tested_at: string | null;
  last_test_fingerprint: string | null;
  last_test_latency_ms: number | null;
  last_test_detail_code: string | null;
  last_test_actor_id: string | null;
  deleted_at: string | null;
  deleted_by: string | null;
};

export type AIModelListPage = {
  rows: AIModelResponse[];
  total: number;
};

export type SystemPromptVersionResponse = {
  id: string;
  prompt_id: string;
  version_number: number;
  content: string;
  content_hash: string;
  is_active: boolean;
  change_reason: string | null;
  created_by: string | null;
  created_at: string;
};

export type SystemPromptResponse = {
  id: string;
  prompt_scope: "global" | "model";
  model_type: "Chat" | "Judge";
  model_id: string | null;
  is_active: boolean;
  current_version_id: string | null;
  current_version_number: number | null;
  content: string;
  content_length: number;
  content_hash: string | null;
  lock_version: number;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
  versions: SystemPromptVersionResponse[];
};

export type ProjectResponse = {
  id: string;
  name: string;
  description: string | null;
  status: string;
  llm_model_id: string | null;
  embedding_model_id: string | null;
  ocr_model_id: string | null;
  lock_version: number;
  archived_at: string | null;
  archived_by: string | null;
  archive_cleanup_status: "queued" | "running" | "completed" | "failed" | null;
  is_owner: boolean;
  current_user_project_roles: ("owner" | "editor" | "viewer")[];
  document_count: number;
  published_version_count: number;
  last_activity_at: string | null;
  capabilities: ProjectCapabilities;
};

export type ProjectCapabilities = {
  can_publish?: boolean;
  can_upload: boolean;
  can_update_source: boolean;
  can_start_extraction: boolean;
  can_reextract: boolean;
  can_edit_chunks: boolean;
  can_create_reference: boolean;
  can_sync_source: boolean;
  can_view_graph: boolean;
  can_submit_review: boolean;
  can_manage_lifecycle: boolean;
  can_archive_project?: boolean;
  can_retry_archive_cleanup?: boolean;
};

export type ProjectListOptions = {
  status?: "active" | "archived";
  q?: string;
  roles?: ("owner" | "editor" | "viewer")[];
  modelState?: "complete" | "incomplete";
  sort?: "updated_desc" | "updated_asc" | "name_asc" | "name_desc";
  offset?: number;
  limit?: number;
  signal?: AbortSignal;
};

export type ProjectListPage = { items: ProjectResponse[]; total: number };

export type ProjectArchiveImpactResponse = {
  project_id: string;
  project_name: string;
  lock_version: number;
  completed_document_count: number;
  completed_version_count: number;
  unfinished_version_count: number;
  unfinished_document_count: number;
  deleted_document_count: number;
  unfinished_file_count: number;
  unfinished_pipeline_count: number;
  unfinished_sync_count: number;
  unfinished_validation_count: number;
  unfinished_approval_count: number;
  unfinished_staging_index_count: number;
  unfinished_embedding_build_count: number;
  unfinished_graph_count: number;
};

export type IntegrationClientResponse = {
  id: string;
  name: string;
  description: string | null;
  status: string;
  effective_status: string;
  api_key_prefix: string;
  api_key_version: number;
  contact_name: string | null;
  contact_email: string | null;
  contact_department: string | null;
  valid_from: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  revocation_reason: string | null;
  requests_per_minute: number | null;
  project_ids: string[];
  last_used_at: string | null;
  last_used_project_id: string | null;
  success_count: number;
  failure_count: number;
  lock_version: number;
  created_at: string;
  updated_at: string;
};

export type IntegrationClientCreateResponse = IntegrationClientResponse & { api_key: string };
export type IntegrationClientPage = { items: IntegrationClientResponse[]; has_more: boolean; next_cursor: string | null };
export type IntegrationClientPayload = {
  name: string;
  description?: string | null;
  project_ids: string[];
  contact_name?: string | null;
  contact_email?: string | null;
  contact_department?: string | null;
  valid_from?: string | null;
  expires_at?: string | null;
  requests_per_minute?: number | null;
};

export type ProjectCreatePayload = {
  name: string;
  description?: string | null;
  llm_model_id: string;
  embedding_model_id: string;
  ocr_model_id: string;
  members?: { user_id: string; roles: string[] }[];
};

export type ProjectMemberResponse = {
  user_id: string;
  given_name: string | null;
  family_name: string | null;
  display_name: string;
  email: string | null;
  roles: string[];
};

export type ProjectMemberCandidate = {
  id: string;
  employee_id: string | null;
  email: string | null;
  given_name: string | null;
  family_name: string | null;
  display_name: string;
  is_active: boolean;
};

export type ProjectMemberCandidatePage = {
  items: ProjectMemberCandidate[];
  total: number;
  offset: number;
  limit: number;
  ineligible_match_count: number;
};

export type ProjectMemberUpdatePayload = {
  roles: string[];
  lock_version: number;
};

export type PipelineExecution = {
  phase: string;
  attempt: number;
  progress_revision: number;
  updated_at: string;
  heartbeat_at: string | null;
  completed_units: number;
  total_units: number | null;
  unit: "pages" | "steps" | null;
  safe_error_code: string | null;
  poll_interval_seconds: number;
  background_poll_interval_seconds: number;
};

export type PipelineSummary = {
  id: string | null;
  status: string;
  progress_percent: number;
  current_step_name: string | null;
  error_message: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  execution?: PipelineExecution | null;
};

export type PipelineStepSummary = {
  id: string;
  step_name: string;
  status: string;
  progress_percent: number;
  progress_message: string | null;
  retry_count: number;
  output_artifact_ref: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
};

export type PipelineRunDetail = PipelineSummary & {
  project_id: string;
  document_id: string | null;
  document_version_id: string | null;
  run_type: string;
  started_at: string | null;
  steps: PipelineStepSummary[];
};

export type DocumentVersionSummary = {
  active_chunk_count?: number | null;
  created_by?: string | null;
  created_by_name?: string | null;
  id: string;
  version_label: string;
  status: string;
  original_file_name: string | null;
  canonical_extension: string | null;
  mime_type: string | null;
  file_size: number | null;
  storage_bucket: string | null;
  storage_key: string | null;
  ocr_model_id: string | null;
  ocr_config_version: number | null;
  lock_version: number;
  created_at: string;
  updated_at: string;
};

export type DocumentSummary = {
  created_by_name?: string | null;
  id: string;
  project_id: string;
  document_code: string;
  title: string;
  source_type: string;
  status: string;
  created_by: string | null;
  lock_version: number;
  created_at: string;
  updated_at: string;
  latest_version: DocumentVersionSummary | null;
  versions?: DocumentVersionSummary[];
  latest_pipeline: PipelineSummary | null;
  service_source?: DocumentServiceSourceSummary | null;
  reference_source?: DocumentReferenceSourceSummary | null;
  capabilities: ProjectCapabilities;
};

export type DocumentServiceSourceSummary = {
  data_source_id: string;
  service_type: string;
  location: string;
  schedule_mode: string;
  cron_expression: string | null;
  timezone: string | null;
};

export type DocumentReferenceSourceSummary = {
  reference_id: string | null;
  source_project_id: string;
  source_document_id: string;
  source_version_id: string;
  project_name: string;
  document_name: string;
  snapshot_version: string;
  latest_active_version: string | null;
  has_access: boolean;
  status: string;
  detected_at: string | null;
  pending_event_count: number;
};

export type DocumentUploadResult = {
  index: number;
  filename: string;
  status: "success" | "failed";
  document: DocumentSummary | null;
  started_extraction: boolean;
  error_code: string | null;
  message: string | null;
};

export type DocumentUploadResponse = {
  request_id: string;
  success_count: number;
  failed_count: number;
  results: DocumentUploadResult[];
};

export type DocumentUpdateResponse = {
  document: DocumentSummary;
  latest_pipeline: PipelineSummary | null;
  no_change: boolean;
  message: string | null;
};

export type DataSourceConnectionPayload = {
  service_type: "FTP" | "FTPS" | "SFTP" | "S3" | "HTTP_API";
  name: string;
  host: string;
  port: number;
  username: string;
  credential?: string | null;
  credential_secret_ref?: string | null;
  bucket?: string | null;
  region?: string | null;
  remote_path: string;
  file_name: string;
  schedule_mode: "once" | "cron";
  cron_expression?: string | null;
  timezone: string;
  verify_tls?: boolean;
  verify_host_key?: boolean;
  url?: string | null;
  headers?: Record<string, string>;
  auth_mode?: "none" | "bearer" | "api_key_header";
  api_key_header_name?: string | null;
  timeout_seconds?: number;
  max_bytes?: number | null;
};

export type DataSourceConnectionTestResponse = {
  status: "success" | "configuration_valid" | "unavailable" | "failed";
  detail_code: string;
  message: string;
  credential_configured: boolean;
  fingerprint: string | null;
  latency_ms: number | null;
  tested_at: string | null;
};

export type DataSourceResponse = {
  id: string;
  project_id: string;
  service_type: string;
  name: string;
  connection_metadata: Record<string, unknown>;
  source_identity: Record<string, unknown>;
  schedule_mode: string;
  cron_expression: string | null;
  timezone: string;
  enabled: boolean;
  last_sync_status: string | null;
  last_synced_at: string | null;
  next_run_at: string | null;
  lock_version: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  credential_configured: boolean;
  last_test_status: string | null;
  last_tested_at: string | null;
  last_test_fingerprint: string | null;
  last_test_latency_ms: number | null;
  last_test_detail_code: string | null;
  last_test_actor_id: string | null;
};

export type DataSyncRunResponse = {
  id: string;
  data_connection_id: string;
  document_id: string;
  trigger_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  content_fingerprint: string | null;
  remote_metadata: Record<string, unknown>;
  document_version_id: string | null;
  error_code: string | null;
  error_summary: string | null;
  retry_count: number;
  created_at: string;
};

export type DataSourceCreateResponse = {
  data_source: DataSourceResponse;
  document: DocumentSummary;
  sync_run: DataSyncRunResponse;
};

export type ApprovalTaskResponse = {
  id: string;
  approval_request_id: string;
  project_id: string;
  project_name: string | null;
  document_id: string;
  document_title: string | null;
  document_version_id: string;
  version_label: string | null;
  submitter_id: string;
  submitter_given_name: string | null;
  submitter_family_name: string | null;
  submitter_name: string | null;
  submitter_email: string | null;
  priority: string;
  source_type: string | null;
  assignee_user_id: string | null;
  review_stage: string;
  status: string;
  lock_version: number;
  submitted_at: string;
  completed_at: string | null;
  created_at: string;
};

export type ApprovalRequestResponse = {
  id: string;
  project_id: string;
  project_name: string | null;
  document_id: string;
  document_title: string | null;
  document_version_id: string;
  version_label: string | null;
  submitter_id: string;
  submitter_given_name: string | null;
  submitter_family_name: string | null;
  submitter_name: string | null;
  submitter_email: string | null;
  owner_user_id: string | null;
  evidence_revision: string | null;
  priority: string;
  source_type: string | null;
  status: string;
  current_task_id: string | null;
  submitted_at: string;
  approved_at: string | null;
  published_at: string | null;
  cancelled_at: string | null;
  created_at: string;
};

export type ApprovalPendingPublishResponse = {
  approval_request_id: string | null;
  approval_task_id: string | null;
  project_id: string;
  project_name: string | null;
  document_id: string;
  document_title: string | null;
  document_version_id: string;
  version_label: string | null;
  version_status: string;
  lock_version: number;
  submitter_id: string | null;
  submitter_given_name: string | null;
  submitter_family_name: string | null;
  submitter_name: string | null;
  submitter_email: string | null;
  approved_at: string | null;
};

export type ReviewRecordResponse = {
  id: string;
  review_stage: string;
  reviewer_id: string;
  delegated_from_user_id: string | null;
  status: string;
  comment: string | null;
  created_at: string;
};

export type ApprovalChunkEvidence = {
  id: string;
  chunk_index: number;
  title: string | null;
  content: string;
  display_markdown: string | null;
  markdown_content: string | null;
  content_type: string;
  source_mapping: unknown[];
  token_count: number | null;
  confidence_score: number | null;
  lineage_id: string;
  parent_chunk_id: string | null;
  revision: number;
  change_type: string;
  tags: string[];
  tag_details: KnowledgeTagResponse[];
};

export type KnowledgeTagResponse = {
  tag_id: string;
  tag_text: string;
  source: string;
  confidence_score: number | null;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
};

export type ApprovalChatEvidence = {
  id: string;
  conversation_id: string;
  conversation_title: string | null;
  scope_mode: string | null;
  document_version_id: string | null;
  selected_document_version_ids: string[];
  question: string;
  answer: string | null;
  reference_docs: ProjectChatCitation[];
  evaluation: string;
  revision_suggestion: string | null;
  created_by: string;
  asked_at: string;
  answered_at: string | null;
};

export type ApprovalTaskDetail = {
  task: ApprovalTaskResponse;
  request: ApprovalRequestResponse;
  document: DocumentSummary;
  version: DocumentVersionSummary;
  latest_version_id: string;
  evidence_stale: boolean;
  read_only: boolean;
  read_only_reason: string | null;
  evidence_revision: string | null;
  evidence_generated_at: string | null;
  evidence_verifiable: boolean;
  evidence_manifest: Record<string, unknown> | null;
  original_file: OriginalFileViewerMetadata | null;
  document_layout: DocumentLayoutArtifact | null;
  source_text: string | null;
  markdown_text: string | null;
  markdown_artifact_status: "available" | "processing" | "missing" | "failed" | "invalid";
  markdown_artifact_reason_code: string | null;
  source_mapping_available: boolean;
  markdown_available_count: number;
  missing_markdown_count: number;
  document_tags: KnowledgeTagResponse[];
  review_records: ReviewRecordResponse[];
  chunks: ApprovalChunkEvidence[];
  chat_records: ApprovalChatEvidence[];
};

export type KnowledgeDetailResponse = {
  chat_access?: { mode: "staging" | "published" | "history_only" | "unavailable"; document_version_id: string; query_enabled: boolean; reason_code: string | null } | null;
  document: DocumentSummary;
  version: DocumentVersionSummary;
  pipeline: PipelineRunDetail | null;
  original_file: OriginalFileViewerMetadata | null;
  document_layout: DocumentLayoutArtifact | null;
  source_text: string | null;
  markdown_text: string | null;
  markdown_artifact_status: "available" | "processing" | "missing" | "failed" | "invalid";
  markdown_artifact_reason_code: string | null;
  source_mapping_available: boolean;
  markdown_available_count: number;
  missing_markdown_count: number;
  manual_edit_enabled: boolean;
  manual_edit_reason: string | null;
  tag_edit_reason?: string | null;
  active_chunk_count: number;
  chunk_artifact_status: "ready" | "queued" | "running" | "failed" | "chunks_required";
  next_stage_allowed: boolean;
  next_stage_block_reason: string | null;
  document_tags: KnowledgeTagResponse[];
  chunks: ApprovalChunkEvidence[];
};

export type SubmissionEvidenceActor = {
  user_id: string;
  given_name: string | null;
  family_name: string | null;
  display_name: string;
  email: string | null;
  department: string | null;
  title: string | null;
};

export type SubmissionEvidenceResponse = {
  detail: KnowledgeDetailResponse;
  evidence_revision: string;
  lock_version: number;
  generated_at: string;
  next_stage_allowed: boolean;
  block_reasons: string[];
  can_submit_review: boolean;
  creator: SubmissionEvidenceActor | null;
  manager: SubmissionEvidenceActor | null;
  owners: SubmissionEvidenceActor[];
  models: Record<string, { id: string; name: string; type: string; provider: string; config_version: number }>;
  content_type_counts: Record<string, number>;
  chunk_count: number;
  tag_count: number;
  average_confidence: number | null;
  graph: { status?: string; source?: string; node_count?: number; edge_count?: number; chunk_count?: number };
  chat_records: ApprovalChatEvidence[];
  validation_runs: Array<Record<string, unknown>>;
};

export type DocumentLayoutArtifact = {
  status: "available" | "partial" | "missing" | "failed";
  reason_code: string | null;
  source: string | null;
  layout_version?: string | null;
  pagination?: Record<string, unknown>;
  warnings?: Array<Record<string, unknown>>;
  pages: DocumentLayoutPage[];
};

export type DocumentLayoutPage = {
  page_number: number;
  width: number | null;
  height: number | null;
  blocks: DocumentLayoutBlock[];
};

export type DocumentLayoutBlock = {
  id: string;
  type: "heading" | "paragraph" | "list" | "table" | "image" | "caption" | "code" | "blockquote" | "horizontal_rule" | "unknown";
  source_anchor: string | null;
  text: string | null;
  inline_markdown?: string | null;
  level: number | null;
  items: string[];
  list_ordered?: boolean | null;
  list_start?: number | null;
  list_items?: DocumentLayoutListItem[];
  table_header?: string[];
  table_header_markdown?: string[];
  rows: string[][];
  rows_markdown?: string[][];
  caption: string | null;
  caption_markdown?: string | null;
  image_source?: string | null;
  code_language?: string | null;
  confidence: number | null;
  bbox: { x: number | null; y: number | null; width: number | null; height: number | null } | null;
  continuation_of?: string | null;
  continuation_index?: number | null;
  continuation_count?: number | null;
  source_start_offset?: number | null;
  source_end_offset?: number | null;
  continuation_text_start?: number | null;
  continuation_text_end?: number | null;
};

export type DocumentLayoutListItem = {
  text: string;
  inline_markdown?: string | null;
  value?: number | null;
  children?: DocumentLayoutListItem[];
  child_lists?: Array<{
    ordered: boolean;
    start: number;
    items: DocumentLayoutListItem[];
  }>;
  continuation?: boolean;
};

export type OriginalFileViewerMetadata = {
  original_file_name: string | null;
  extension: string | null;
  mime_type: string | null;
  file_size: number | null;
  viewer_type: "download_only" | "markdown" | "unsupported";
  preview_status: "available" | "pending" | "unavailable" | "failed";
  preview_error_code: string | null;
  original_url: string | null;
  preview_url: string | null;
  download_url: string | null;
  markdown_source_mode: "rendered_original_raw_markdown" | "pipeline_markdown";
};

export type ApprovalSummary = {
  pending_total: number;
  pending_manager_review: number;
  pending_owner_review: number;
  my_submissions: number;
};

export type PublishResult = {
  document_version_id: string;
  status: string;
  active_manifest_id: string;
  publication_generation: number;
  opensearch_index: string;
  graph_sync_job_id: string;
};

export type SwitchActiveVersionPayload = {
  lock_version: number;
  impact_confirmed: boolean;
  audit_reason: string;
};

export type LifecycleImpactResponse = {
  document_id: string;
  requested_status: string;
  impacted_reference_count: number;
  impacted_active_version_count: number;
  requires_confirmation: boolean;
};

export type DocumentReferenceResponse = {
  id: string;
  target_project_id: string;
  target_document_id: string;
  source_project_id: string;
  source_document_id: string;
  source_version_id: string;
  source_project_name_snapshot: string;
  source_document_name_snapshot: string;
  reference_mode: string;
  status: string;
  created_by: string | null;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ReferenceSourceVersionResponse = {
  id: string;
  version_label: string;
  status: string;
  is_active: boolean;
  created_at: string;
};

export type ReferenceExistingTargetResponse = {
  target_document_id: string;
  target_title: string;
  source_version_label: string;
};

export type ReferenceSourceDocumentResponse = {
  id: string;
  title: string;
  owner: string | null;
  versions: ReferenceSourceVersionResponse[];
  duplicate: ReferenceExistingTargetResponse | null;
};

export type ReferenceSourceProjectResponse = {
  id: string;
  name: string;
  status: string;
  documents: ReferenceSourceDocumentResponse[];
};

export type DocumentReferenceImportResponse = {
  results: Array<{
    status: "created" | "skipped" | "failed";
    document: DocumentSummary | null;
    reference: DocumentReferenceResponse | null;
    error_code: string | null;
    message: string | null;
  }>;
};

export type DocumentReferenceEventResponse = {
  id: string;
  reference_id: string;
  event_type: string;
  source_project_id: string;
  source_document_id: string;
  old_source_version_id: string | null;
  new_source_version_id: string | null;
  message: string;
  is_read: boolean;
  resolved_at: string | null;
  created_at: string;
};

export type ImpactedReferenceProjectsResponse = {
  source_document_id: string;
  projects: { target_project_id: string; reference_count: number }[];
};

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
};

export type NotificationCountResponse = {
  unread_count: number;
};

export type SystemParametersPayload = {
  max_upload_size_mb: number;
  default_timezone: string;
  staging_index_ttl_days: number;
  session_expired_form_draft_ttl_minutes: number;
};

export type UploadConfigResponse = {
  max_upload_size_mb: number;
};

export type SessionDraftCreateResponse = {
  draft_id: string;
  form_key: string;
  return_path: string;
  expires_at: string;
  field_count: number;
};

export type SessionDraftRestoreResponse = {
  draft_id: string;
  form_key: string;
  return_path: string;
  payload: Record<string, unknown>;
  expires_at: string;
};

export type IdentitySettingsResponse = {
  revision: number | null;
  state: string;
  configuration: Record<string, unknown>;
  secret_configured: boolean;
  editable: boolean;
  configuration_source: "deployment" | "database";
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

export type IdentitySettingsCandidate = {
  issuer_url: string;
  realm: string;
  client_id: string;
  audience: string;
  discovery_url: string;
  jwks_url: string;
  enabled?: boolean;
  sync_enabled?: boolean;
  sync_scope?: "people" | "groups" | "people_and_groups";
  sync_schedule?: string;
  timezone?: string;
};

export async function getCurrentUser(apiFetch: ApiFetch) { return apiJson<CurrentUser>(apiFetch, "/auth/me"); }
export async function restoreSessionDraft(apiFetch: ApiFetch, draftId: string, payload: { return_path: string; nonce: string }) { return apiJson<SessionDraftRestoreResponse>(apiFetch, `/auth/session-drafts/${draftId}/restore`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function discardSessionDraft(apiFetch: ApiFetch, draftId: string, payload: { return_path: string; nonce: string }) { return apiJson<{ status: string }>(apiFetch, `/auth/session-drafts/${draftId}/discard`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function listProjectsPage(apiFetch: ApiFetch, options: ProjectListOptions = {}): Promise<ProjectListPage> {
  const params = new URLSearchParams({
    status: options.status ?? "active",
    sort: options.sort ?? "updated_desc",
    offset: String(options.offset ?? 0),
    limit: String(options.limit ?? 12)
  });
  if (options.q?.trim()) params.set("q", options.q.trim());
  for (const role of options.roles ?? []) params.append("role", role);
  if (options.modelState) params.set("model_state", options.modelState);
  const response = await apiFetch(`${apiBaseUrl()}/projects?${params.toString()}`, { cache: "no-store", signal: options.signal });
  if (!response.ok) {
    throw await apiResponseError(response);
  }
  const items = await response.json() as ProjectResponse[];
  const parsedTotal = Number(response.headers.get("X-Total-Count"));
  return { items, total: Number.isFinite(parsedTotal) ? parsedTotal : items.length };
}
export async function listProjects(apiFetch: ApiFetch, status: "active" | "archived" = "active") { return (await listProjectsPage(apiFetch, { status, limit: 200 })).items; }
export async function getProject(apiFetch: ApiFetch, projectId: string) { return apiJson<ProjectResponse>(apiFetch, `/projects/${projectId}`); }
export async function createProject(apiFetch: ApiFetch, payload: ProjectCreatePayload) { return apiJson<ProjectResponse>(apiFetch, "/projects", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function getProjectArchiveImpact(apiFetch: ApiFetch, projectId: string) { return apiJson<ProjectArchiveImpactResponse>(apiFetch, `/projects/${projectId}/archive-impact`); }
export async function archiveProject(apiFetch: ApiFetch, projectId: string, payload: { lock_version: number; confirmation_name: string }) { return apiJson<ProjectResponse>(apiFetch, `/projects/${projectId}/archive`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function retryProjectArchiveCleanup(apiFetch: ApiFetch, projectId: string) { return apiJson<ProjectResponse>(apiFetch, `/projects/${projectId}/archive-cleanup/retry`, { method: "POST" }); }
export async function listIntegrationClients(apiFetch: ApiFetch) {
  return (await apiJson<IntegrationClientPage>(apiFetch, "/integration-clients?limit=100")).items;
}
export async function createIntegrationClient(apiFetch: ApiFetch, payload: IntegrationClientPayload) { return apiJson<IntegrationClientCreateResponse>(apiFetch, "/integration-clients", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function updateIntegrationClient(apiFetch: ApiFetch, clientId: string, payload: Partial<IntegrationClientPayload> & { lock_version: number }) { return apiJson<IntegrationClientResponse>(apiFetch, `/integration-clients/${clientId}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function replaceIntegrationClientProjectScopes(apiFetch: ApiFetch, clientId: string, payload: { lock_version: number; project_ids: string[] }) { return apiJson<IntegrationClientResponse>(apiFetch, `/integration-clients/${clientId}/project-scopes`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function rotateIntegrationClientKey(apiFetch: ApiFetch, clientId: string, payload: { lock_version: number; reason?: string | null }) { return apiJson<IntegrationClientCreateResponse>(apiFetch, `/integration-clients/${clientId}/keys/rotate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function activateIntegrationClient(apiFetch: ApiFetch, clientId: string, payload: { lock_version: number; reason?: string | null }) { return apiJson<IntegrationClientResponse>(apiFetch, `/integration-clients/${clientId}/activate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function deactivateIntegrationClient(apiFetch: ApiFetch, clientId: string, payload: { lock_version: number; reason?: string | null }) { return apiJson<IntegrationClientResponse>(apiFetch, `/integration-clients/${clientId}/deactivate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function revokeIntegrationClient(apiFetch: ApiFetch, clientId: string, payload: { lock_version: number; reason?: string | null }) { return apiJson<IntegrationClientResponse>(apiFetch, `/integration-clients/${clientId}/revoke`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function listProjectMembers(apiFetch: ApiFetch, projectId: string) { return apiJson<ProjectMemberResponse[]>(apiFetch, `/projects/${projectId}/members`); }
export async function searchProjectMemberCandidates(apiFetch: ApiFetch, projectId: string, query: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ q: query.trim(), offset: "0", limit: "20" });
  return apiJson<ProjectMemberCandidatePage>(apiFetch, `/projects/${projectId}/member-candidates?${params.toString()}`, { signal });
}
export async function replaceProjectMember(apiFetch: ApiFetch, projectId: string, userId: string, payload: ProjectMemberUpdatePayload) {
  return apiJson<ProjectMemberResponse[]>(apiFetch, `/projects/${projectId}/members/${userId}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function removeProjectMember(apiFetch: ApiFetch, projectId: string, userId: string, lockVersion: number) {
  return apiJson<ProjectResponse>(apiFetch, `/projects/${projectId}/members/${userId}?lock_version=${lockVersion}`, { method: "DELETE" });
}
export async function listProjectDocuments(apiFetch: ApiFetch, projectId: string, signal?: AbortSignal) { return apiJson<DocumentSummary[]>(apiFetch, `/projects/${projectId}/documents`, { signal }); }
export async function uploadProjectDocuments(apiFetch: ApiFetch, projectId: string, files: File[], options: { ocrModelId?: string | null; forceOcr?: boolean; startExtraction?: boolean } = {}) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  if (options.ocrModelId) form.append("ocr_model_id", options.ocrModelId);
  if (options.forceOcr) form.append("force_ocr", "true");
  if (options.startExtraction) form.append("start_extraction", "true");
  return apiJson<DocumentUploadResponse>(apiFetch, `/projects/${projectId}/documents/upload`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: form
  });
}
export async function updateProjectDocumentFile(apiFetch: ApiFetch, projectId: string, documentId: string, file: File, options: { ocrModelId?: string | null; forceOcr?: boolean } = {}) {
  const form = new FormData();
  form.append("files", file);
  if (options.ocrModelId) form.append("ocr_model_id", options.ocrModelId);
  if (options.forceOcr) form.append("force_ocr", "true");
  return apiJson<DocumentUpdateResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/update-file`, { method: "POST", body: form });
}
export async function testDataSourceConnection(apiFetch: ApiFetch, projectId: string, payload: DataSourceConnectionPayload) {
  return apiJson<DataSourceConnectionTestResponse>(apiFetch, `/projects/${projectId}/data-sources/test-connection`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function createDataSource(apiFetch: ApiFetch, projectId: string, payload: DataSourceConnectionPayload) {
  return apiJson<DataSourceCreateResponse>(apiFetch, `/projects/${projectId}/data-sources`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function queueDataSourceSync(apiFetch: ApiFetch, projectId: string, dataSourceId: string) {
  return apiJson<DataSyncRunResponse>(apiFetch, `/projects/${projectId}/data-sources/${dataSourceId}/sync`, { method: "POST" });
}
export async function listDataSourceSyncRuns(apiFetch: ApiFetch, projectId: string, dataSourceId: string) {
  return apiJson<DataSyncRunResponse[]>(apiFetch, `/projects/${projectId}/data-sources/${dataSourceId}/sync-runs`);
}
export async function startDocumentExtraction(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, payload: { ocr_model_id?: string | null; force_ocr?: boolean }) {
  return apiJson<{ document: DocumentSummary; pipeline: PipelineSummary }>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/extract`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function getPipelineDetail(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, pipelineId: string, signal?: AbortSignal) {
  return apiJson<PipelineRunDetail>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/pipelines/${pipelineId}`, { signal });
}
export async function getKnowledgeDetail(apiFetch: ApiFetch, projectId: string, documentId: string, signal?: AbortSignal) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/knowledge`, { signal });
}
export async function createManualChunk(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, payload: { content: string; view_mode: "original" | "markdown"; source_anchor: string; start_offset: number; end_offset: number; offset_unit: "unicode_code_point"; offset_scope: "canonical_markdown" | "source_anchor"; lock_version: number }) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/chunks/manual`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function deleteKnowledgeChunk(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, chunkId: string, lockVersion: number) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/chunks/${chunkId}?lock_version=${lockVersion}`, { method: "DELETE" });
}
export async function addChunkTag(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, chunkId: string, tagText: string) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/chunks/${chunkId}/tags`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ tag_text: tagText }) });
}
export async function deleteChunkTag(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, chunkId: string, tagId: string) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/chunks/${chunkId}/tags/${tagId}`, { method: "DELETE" });
}
export async function autoTagChunk(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, chunkId: string) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/chunks/${chunkId}/tags/auto`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ max_tags: 5 }) });
}
export async function addDocumentTag(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, tagText: string) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/tags`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ tag_text: tagText }) });
}
export async function deleteDocumentTag(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, tagId: string) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/tags/${tagId}`, { method: "DELETE" });
}
export async function autoTagDocument(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/tags/auto`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ max_tags: 5 }) });
}
export async function getKnowledgeArtifactBlob(apiFetch: ApiFetch, path: string) {
  const response = await apiFetch(`${apiBaseUrl()}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw await apiResponseError(response);
  }
  return response.blob();
}
export async function retryPipelineStep(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, pipelineId: string, stepName: string) {
  return apiJson<PipelineRunDetail>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/pipelines/${pipelineId}/retry`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ step_name: stepName }) });
}
export async function getDocumentVersionSubmissionEvidence(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string) {
  return apiJson<SubmissionEvidenceResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/submission-evidence`);
}
export async function submitDocumentVersionReview(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, payload: { evidence_revision: string; lock_version: number; owner_user_id?: string | null }) {
  return apiJson<ApprovalRequestResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/submit-review`, { method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(payload) });
}
export async function getApprovalSummary(apiFetch: ApiFetch) { return apiJson<ApprovalSummary>(apiFetch, "/approvals/summary"); }
export async function listPendingApprovals(apiFetch: ApiFetch) { return (await apiJson<{ items: ApprovalTaskResponse[]; has_more: boolean; next_cursor: string | null }>(apiFetch, "/approvals/pending")).items; }
export async function listApprovalHistory(apiFetch: ApiFetch) { return (await apiJson<{ items: ApprovalTaskResponse[]; has_more: boolean; next_cursor: string | null }>(apiFetch, "/approvals/history")).items; }
export async function listRejectedApprovals(apiFetch: ApiFetch) { return (await apiJson<{ items: ApprovalTaskResponse[]; has_more: boolean; next_cursor: string | null }>(apiFetch, "/approvals/history?result=rejected")).items; }
export async function listMyApprovalSubmissions(apiFetch: ApiFetch) { return (await apiJson<{ items: ApprovalRequestResponse[]; has_more: boolean; next_cursor: string | null }>(apiFetch, "/approvals/my-submissions")).items; }
export async function listPendingPublishApprovals(apiFetch: ApiFetch) { return apiJson<ApprovalPendingPublishResponse[]>(apiFetch, "/approvals/pending-publish"); }
export async function getApprovalTask(apiFetch: ApiFetch, approvalTaskId: string) { return apiJson<ApprovalTaskDetail>(apiFetch, `/approvals/${approvalTaskId}`); }
export async function approveApprovalTask(apiFetch: ApiFetch, approvalTaskId: string, payload: { lock_version: number; comment?: string | null }) {
  return apiJson<ApprovalTaskResponse>(apiFetch, `/approvals/${approvalTaskId}/approve`, { method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(payload) });
}
export async function rejectApprovalTask(apiFetch: ApiFetch, approvalTaskId: string, payload: { lock_version: number; comment: string }) {
  return apiJson<ApprovalTaskResponse>(apiFetch, `/approvals/${approvalTaskId}/reject`, { method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(payload) });
}
export async function publishDocumentVersion(apiFetch: ApiFetch, versionId: string, payload: { lock_version: number; impact_confirmed?: boolean }) {
  return apiJson<PublishResult>(apiFetch, `/document-versions/${versionId}/publish`, { method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(payload) });
}
export async function switchActiveDocumentVersion(apiFetch: ApiFetch, versionId: string, payload: SwitchActiveVersionPayload) {
  return apiJson<PublishResult>(apiFetch, `/document-versions/${versionId}/switch-active`, { method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(payload) });
}
export async function getDocumentLifecycleImpact(apiFetch: ApiFetch, projectId: string, documentId: string, status: string) {
  return apiJson<LifecycleImpactResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/lifecycle-impact?status=${encodeURIComponent(status)}`);
}
export async function updateDocumentLifecycle(apiFetch: ApiFetch, projectId: string, documentId: string, payload: { lock_version: number; status: string; impact_confirmed?: boolean; reason?: string | null }) {
  return apiJson<DocumentSummary>(apiFetch, `/projects/${projectId}/documents/${documentId}/lifecycle`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function listProjectReferenceSources(apiFetch: ApiFetch, projectId: string) {
  return apiJson<ReferenceSourceProjectResponse[]>(apiFetch, `/projects/${projectId}/reference-sources`);
}
export async function importProjectDocumentReferences(apiFetch: ApiFetch, projectId: string, payload: { mode: "reference" | "copy"; items: Array<{ source_document_id: string; source_version_id: string; old_version_confirmed?: boolean }> }) {
  return apiJson<DocumentReferenceImportResponse>(apiFetch, `/projects/${projectId}/document-references/import`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function updateDocumentReferenceVersion(apiFetch: ApiFetch, referenceId: string, payload: { source_version_id: string; old_version_confirmed?: boolean }) {
  return apiJson<DocumentUpdateResponse>(apiFetch, `/document-references/${referenceId}/update`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function getProjectGraph(apiFetch: ApiFetch, projectId: string, nodeLimit = 120) {
  return apiJson<ProjectGraphResponse>(apiFetch, `/projects/${projectId}/graph?node_limit=${nodeLimit}`);
}
export async function getProjectGraphNeighbors(apiFetch: ApiFetch, projectId: string, nodeId: string, nodeLimit = 80) {
  const params = new URLSearchParams({ node_id: nodeId, node_limit: String(nodeLimit) });
  return apiJson<ProjectGraphResponse>(apiFetch, `/projects/${projectId}/graph/neighbors?${params.toString()}`);
}
export async function getDocumentVersionGraph(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, nodeLimit = 120) {
  return apiJson<ProjectGraphResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/graph?node_limit=${nodeLimit}`);
}
export async function getProjectServingStatus(apiFetch: ApiFetch, projectId: string) {
  return apiJson<ProjectServingStatusResponse>(apiFetch, `/projects/${projectId}/serving-status`);
}
export async function queryProjectChat(apiFetch: ApiFetch, projectId: string, payload: { question: string; document_version_ids?: string[] | null; scope_mode: "published" | "document_staging"; top_k?: number; conversation_id?: string | null; conversation_title?: string | null }) {
  return apiJson<ProjectChatQueryResponse>(apiFetch, `/projects/${projectId}/chat/query`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function listProjectChatConversationPage(apiFetch: ApiFetch, projectId: string, options?: { scope_mode?: "published" | "document_staging"; document_version_id?: string; cursor?: string }) {
  const params = new URLSearchParams();
  params.set("scope_mode", options?.scope_mode ?? "published");
  if (options?.document_version_id) params.set("document_version_id", options.document_version_id);
  if (options?.cursor) params.set("cursor", options.cursor);
  const query = params.toString();
  const page = await apiJson<ProjectChatConversationPage>(apiFetch, `/projects/${projectId}/chat/conversations${query ? `?${query}` : ""}`);
  return page;
}
export async function getProjectChatConversation(apiFetch: ApiFetch, projectId: string, conversationId: string, options?: { scope_mode?: "published" | "document_staging"; document_version_id?: string }) {
  const params = new URLSearchParams();
  params.set("scope_mode", options?.scope_mode ?? "published");
  if (options?.document_version_id) params.set("document_version_id", options.document_version_id);
  const query = params.toString();
  return apiJson<ProjectChatConversationResponse>(apiFetch, `/projects/${projectId}/chat/conversations/${conversationId}${query ? `?${query}` : ""}`);
}
export async function downloadProjectChatConversationCsv(apiFetch: ApiFetch, projectId: string, conversationId: string, options?: { scope_mode?: "published" | "document_staging"; document_version_id?: string }) {
  const params = new URLSearchParams();
  params.set("scope_mode", options?.scope_mode ?? "published");
  if (options?.document_version_id) params.set("document_version_id", options.document_version_id);
  const response = await apiFetch(`${apiBaseUrl()}/projects/${projectId}/chat/conversations/${conversationId}/export.csv?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw await apiResponseError(response);
  return response.blob();
}
export async function deleteProjectChatConversation(apiFetch: ApiFetch, projectId: string, conversationId: string, options?: { scope_mode?: "published" | "document_staging"; document_version_id?: string }) {
  const params = new URLSearchParams({ scope_mode: options?.scope_mode ?? "published" });
  if (options?.document_version_id) params.set("document_version_id", options.document_version_id);
  return apiJson<ProjectChatConversationDeleteResponse>(apiFetch, `/projects/${projectId}/chat/conversations/${conversationId}?${params.toString()}`, { method: "DELETE" });
}
export async function updateProjectChatFeedback(apiFetch: ApiFetch, projectId: string, recordId: string, payload: { evaluation: "correct" | "needs_revision" | "not_evaluated"; revision_suggestion?: string | null }) {
  return apiJson<ProjectChatRecordResponse>(apiFetch, `/projects/${projectId}/chat/records/${recordId}/feedback`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function createProjectChatValidationRun(apiFetch: ApiFetch, projectId: string, payload: { uploaded_file_name?: string | null; scope_mode: "published" | "document_staging"; selected_document_version_ids?: string[] | null; questions: { input_item_id?: string | null; question: string; expected_answer?: string | null; expected_keywords?: string[]; selected_document_ids?: string[] | null; category?: string | null; priority?: string | null }[] }) {
  return apiJson<ValidationRunResponse>(apiFetch, `/projects/${projectId}/chat/validation-runs`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function getProjectChatValidationRun(apiFetch: ApiFetch, projectId: string, runId: string) {
  return apiJson<ValidationRunResponse>(apiFetch, `/projects/${projectId}/chat/validation-runs/${runId}`);
}
export async function retryFailedProjectChatValidationItems(apiFetch: ApiFetch, projectId: string, runId: string) {
  return apiJson<ValidationRunResponse>(apiFetch, `/projects/${projectId}/chat/validation-runs/${runId}/retry-failed`, { method: "POST" });
}
export type ModelUsageReportFilters = { modelType?: string; usagePurpose?: string; sourceChannel?: string; usageStatus?: string };
export type ReportQueryParams = { topic: string; dateFrom?: string; dateTo?: string; scope?: string; projectId?: string | null; page?: number; pageSize?: number } & ModelUsageReportFilters;
export async function getReportFilterOptions(apiFetch: ApiFetch, scope = "owner_projects") {
  return apiJson<ReportFilterOptionsResponse>(apiFetch, `/reports/filter-options?scope=${encodeURIComponent(scope)}`);
}
export async function getReportSummary(apiFetch: ApiFetch, params: ReportQueryParams) {
  const query = reportQuery(params);
  return apiJson<ReportSummaryResponse>(apiFetch, `/reports/summary?${query}`);
}
export async function downloadReportCsv(apiFetch: ApiFetch, params: ReportQueryParams & { locale?: string }) {
  const query = reportQuery(params);
  const response = await apiFetch(`${apiBaseUrl()}/reports/export.csv?${query}`, { cache: "no-store" });
  if (!response.ok) {
    throw await apiResponseError(response);
  }
  return await response.blob();
}
function reportQuery(params: ReportQueryParams & { locale?: string }) {
  const query = new URLSearchParams({ topic: params.topic });
  if (params.dateFrom) query.set("date_from", `${params.dateFrom}T00:00:00`);
  if (params.dateTo) query.set("date_to", `${params.dateTo}T23:59:59`);
  if (params.projectId && params.projectId !== "all") query.set("project_id", params.projectId);
  if (params.scope) query.set("scope", params.scope);
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.locale) query.set("locale", params.locale);
  if (params.modelType) query.set("model_type", params.modelType);
  if (params.usagePurpose) query.set("usage_purpose", params.usagePurpose);
  if (params.sourceChannel) query.set("source_channel", params.sourceChannel);
  if (params.usageStatus) query.set("usage_status", params.usageStatus);
  return query.toString();
}
export async function listNotifications(apiFetch: ApiFetch) { return (await apiJson<{ items: NotificationResponse[]; has_more: boolean; next_cursor: string | null }>(apiFetch, "/notifications")).items; }
export async function getNotificationUnreadCount(apiFetch: ApiFetch) { return apiJson<NotificationCountResponse>(apiFetch, "/notifications/unread-count"); }
export async function markNotificationRead(apiFetch: ApiFetch, notificationId: string) { return apiJson<NotificationResponse>(apiFetch, `/notifications/${notificationId}/read`, { method: "POST" }); }
export async function markAllNotificationsRead(apiFetch: ApiFetch) { return apiJson<NotificationCountResponse>(apiFetch, "/notifications/read-all", { method: "POST" }); }
export async function resolveNotification(apiFetch: ApiFetch, notificationId: string) { return apiJson<NotificationResponse>(apiFetch, `/notifications/${notificationId}/resolve`, { method: "POST" }); }
export async function listUsers(apiFetch: ApiFetch, scope: "system" | "project_members" = "system") { return apiJson<UserSummary[]>(apiFetch, scope === "system" ? "/users" : `/users?scope=${scope}`); }
export async function updateUser(apiFetch: ApiFetch, userId: string, payload: { manager_delegate_user_id?: string | null; manager_delegate_start_at?: string | null; manager_delegate_end_at?: string | null; knowledge_owner?: boolean | null; system_notes?: string | null }) { return apiJson<UserSummary>(apiFetch, `/users/${userId}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function updateUserStatus(apiFetch: ApiFetch, userId: string, isActive: boolean) { return apiJson<UserSummary>(apiFetch, `/users/${userId}/status`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ is_active: isActive }) }); }
export async function listRoles(apiFetch: ApiFetch) { return apiJson<RoleResponse[]>(apiFetch, "/roles"); }
export async function createRole(apiFetch: ApiFetch, payload: { name: string; description?: string | null }) { return apiJson<RoleResponse>(apiFetch, "/roles", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function updateRole(apiFetch: ApiFetch, roleId: string, payload: { lock_version: number; name?: string; description?: string | null; is_active?: boolean }) { return apiJson<RoleResponse>(apiFetch, `/roles/${roleId}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function deleteRole(apiFetch: ApiFetch, roleId: string, lockVersion: number, confirmationName: string) {
  const query = new URLSearchParams({ lock_version: String(lockVersion), confirmation_name: confirmationName });
  return apiJson<RoleResponse>(apiFetch, `/roles/${roleId}?${query.toString()}`, { method: "DELETE" });
}
export async function listModelsPage(apiFetch: ApiFetch, params: { modelType?: string; offset?: number; limit?: number } = {}): Promise<AIModelListPage> {
  const query = new URLSearchParams();
  if (params.modelType) query.set("model_type", params.modelType);
  query.set("offset", String(params.offset ?? 0));
  query.set("limit", String(params.limit ?? 20));
  const response = await apiFetch(`${apiBaseUrl()}/models?${query.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw await apiResponseError(response);
  }
  const rows = await response.json() as AIModelResponse[];
  const totalHeader = response.headers.get("X-Total-Count");
  const parsedTotal = totalHeader === null ? Number.NaN : Number(totalHeader);
  return { rows, total: Number.isFinite(parsedTotal) ? parsedTotal : rows.length };
}
export async function listModels(apiFetch: ApiFetch, modelType?: string) {
  const rows: AIModelResponse[] = [];
  const limit = 200;
  let offset = 0;
  while (true) {
    const page = await listModelsPage(apiFetch, { modelType, offset, limit });
    rows.push(...page.rows);
    offset += page.rows.length;
    if (page.rows.length === 0 || offset >= page.total || page.rows.length < limit) return rows;
  }
}
export async function createModel(apiFetch: ApiFetch, payload: AIModelPayload & { model_type: string }) { return apiJson<AIModelResponse>(apiFetch, "/models", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function updateModel(apiFetch: ApiFetch, modelId: string, payload: AIModelUpdatePayload) { return apiJson<AIModelResponse>(apiFetch, `/models/${modelId}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function deleteModel(apiFetch: ApiFetch, modelId: string, payload: { confirmation_name: string; config_version: number }) { return apiJson<AIModelResponse>(apiFetch, `/models/${modelId}`, { method: "DELETE", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function setDefaultModel(apiFetch: ApiFetch, modelId: string) { return apiJson<AIModelResponse>(apiFetch, `/models/${modelId}/set-default`, { method: "POST" }); }
export async function testModel(apiFetch: ApiFetch, modelId: string) { return apiJson<AIModelResponse>(apiFetch, `/models/${modelId}/test`, { method: "POST" }); }
export async function listSystemPrompts(apiFetch: ApiFetch) { return apiJson<SystemPromptResponse[]>(apiFetch, "/system-prompts"); }
export async function createSystemPrompt(apiFetch: ApiFetch, payload: SystemPromptPayload) { return apiJson<SystemPromptResponse>(apiFetch, "/system-prompts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function addSystemPromptVersion(apiFetch: ApiFetch, promptId: string, payload: SystemPromptVersionPayload) { return apiJson<SystemPromptResponse>(apiFetch, `/system-prompts/${promptId}/versions`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function activateSystemPrompt(apiFetch: ApiFetch, promptId: string, versionId?: string | null) { return apiJson<SystemPromptResponse>(apiFetch, `/system-prompts/${promptId}/activate`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ version_id: versionId ?? null }) }); }
export async function deactivateSystemPrompt(apiFetch: ApiFetch, promptId: string) { return apiJson<SystemPromptResponse>(apiFetch, `/system-prompts/${promptId}/deactivate`, { method: "POST" }); }
export async function getPermissions(apiFetch: ApiFetch, roleId: string) { return apiJson<PermissionMatrixResponse>(apiFetch, `/roles/${roleId}/permissions`); }
export async function replacePermissions(apiFetch: ApiFetch, roleId: string, payload: PermissionMatrixResponse) { return apiJson<PermissionMatrixResponse>(apiFetch, `/roles/${roleId}/permissions`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function getRoleUsers(apiFetch: ApiFetch, roleId: string) { return apiJson<RoleUsersResponse>(apiFetch, `/roles/${roleId}/users`); }
export async function replaceRoleUsers(apiFetch: ApiFetch, roleId: string, payload: { lock_version: number; user_ids: string[] }) { return apiJson<RoleUsersResponse>(apiFetch, `/roles/${roleId}/users`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function listExternalGroups(apiFetch: ApiFetch) { return apiJson<ExternalGroupResponse[]>(apiFetch, "/external-groups"); }
export async function listExternalGroupMappings(apiFetch: ApiFetch) { return apiJson<ExternalGroupRoleMapping[]>(apiFetch, "/external-group-role-mappings"); }
export async function setRoleExternalGroupMapping(apiFetch: ApiFetch, roleId: string, payload: { external_group_id: string | null; lock_version: number }) { return apiJson<RoleExternalGroupMappingResponse>(apiFetch, `/roles/${roleId}/external-group-mapping`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function getSystemParameters(apiFetch: ApiFetch) { return apiJson<SystemParametersPayload>(apiFetch, "/system/parameters"); }
export async function getUploadConfig(apiFetch: ApiFetch) { return apiJson<UploadConfigResponse>(apiFetch, "/system/upload-config"); }
export async function updateSystemParameters(apiFetch: ApiFetch, payload: SystemParametersPayload) { return apiJson<SystemParametersPayload>(apiFetch, "/system/parameters", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function getSystemStatus(apiFetch: ApiFetch) { return apiJson<OperationsStatusResponse>(apiFetch, "/system/status"); }
export async function getIdentitySettings(apiFetch: ApiFetch) { return apiJson<IdentitySettingsResponse>(apiFetch, "/system/identity-settings"); }
export async function listDirectoryProviders(apiFetch: ApiFetch) { return apiJson<DirectoryProviderResponse[]>(apiFetch, "/system/identity-settings/directory-providers"); }
export async function updateDirectoryProviderFilter(apiFetch: ApiFetch, providerId: string, payload: { custom_user_search_filter: string; config_hash: string }) { return apiJson<DirectoryProviderResponse>(apiFetch, `/system/identity-settings/directory-providers/${encodeURIComponent(providerId)}/filter`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function getBreakGlassStatus(apiFetch: ApiFetch) { return apiJson<BreakGlassStatusResponse>(apiFetch, "/system/break-glass/status"); }
export async function startIdentityReauth(apiFetch: ApiFetch) { return apiJson<{ authorization_url: string }>(apiFetch, "/system/identity-settings/reauth/start", { method: "POST" }); }
export async function completeIdentityReauth(apiFetch: ApiFetch) { return apiJson<{ status: string; expires_at: string }>(apiFetch, "/system/identity-settings/reauth/complete", { method: "POST" }); }
export async function lockIdentitySettings(apiFetch: ApiFetch) { return apiJson<{ status: string }>(apiFetch, "/system/identity-settings/lock", { method: "POST" }); }
export async function validateIdentitySettingsCandidate(apiFetch: ApiFetch, payload: IdentitySettingsCandidate) { return apiJson<{ valid: boolean; configuration: Record<string, unknown> }>(apiFetch, "/system/identity-settings/validate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function activateIdentitySettings(apiFetch: ApiFetch, payload: IdentitySettingsCandidate) { return apiJson<IdentitySettingsResponse>(apiFetch, "/system/identity-settings", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function queueIdentitySync(apiFetch: ApiFetch) { return apiJson<IdentitySyncRunResponse>(apiFetch, "/identity-sync/run", { method: "POST" }); }
export async function listIdentitySyncRuns(apiFetch: ApiFetch) { return (await apiJson<{ items: IdentitySyncRunResponse[]; has_more: boolean; next_cursor: string | null }>(apiFetch, "/identity-sync/runs")).items; }
export async function getIdentitySyncRun(apiFetch: ApiFetch, runId: string) { return apiJson<IdentitySyncRunResponse>(apiFetch, `/identity-sync/runs/${runId}`); }
