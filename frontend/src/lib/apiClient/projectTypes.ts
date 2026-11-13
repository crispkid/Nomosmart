// Project, integration client and project member types (split from lib/api.ts, OPT424-038).

export type ProjectResponse = {
  id: string;
  name: string;
  description: string | null;
  status: string;
  llm_model_id: string | null;
  embedding_model_id: string | null;
  ocr_model_id: string | null;
  model_configuration_state: "ready" | "incomplete";
  pdf_model_state: "configured" | "not_configured" | "invalid";
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
  pdfModelState?: "configured" | "not_configured" | "invalid";
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
  ocr_model_id: string | null;
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
