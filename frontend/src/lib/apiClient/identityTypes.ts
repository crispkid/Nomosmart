// User, role, permission, directory, operations status, AI model and prompt types (split from lib/api.ts, OPT424-038).

export type UserRoleSummary = { id: string; name: string; sources: string[] };

export type UserSummary = {
  id: string;
  employee_id: string | null;
  keycloak_user_id: string | null;
  directory_source_id?: string | null;
  directory_object_id?: string | null;
  email: string | null;
  given_name: string | null;
  family_name: string | null;
  display_name: string;
  department: string | null;
  title: string | null;
  auth_source: string;
  is_active: boolean;
  knowledge_owner: boolean;
  roles?: UserRoleSummary[];
  system_notes: string | null;
  manager_delegate_user_id?: string | null;
  manager_delegate_start_at?: string | null;
  manager_delegate_end_at?: string | null;
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
export type CountedPage<T> = { items: T[]; total: number };
export type SystemListOptions = { q?: string; offset?: number; limit?: number; isActive?: boolean; signal?: AbortSignal };
export type DataSourceConnectionOptions = { credential_modes: ("secret_reference" | "inline")[]; default_timezone: string };
export type ExternalGroupResponse = { id: string; source: string; external_group_id: string; group_dn: string | null; group_name: string; path: string | null; identity_origin: "ldap" | "ad" | "keycloak_local"; is_active: boolean; last_synced_at: string | null; member_count: number; mapped_role_id: string | null };
export type ExternalGroupRoleMapping = { external_group_id: string; role_id: string };
export type RoleExternalGroupMappingResponse = { role_id: string; external_group_id: string | null; lock_version: number; derived_member_count: number };
export type IdentitySyncProviderResultResponse = { id: string; provider_id: string; provider_name: string; provider_vendor: string; requested_scope: "people" | "groups" | "people_and_groups"; status: string; user_sync_status: string; group_sync_status: string; users_added: number; users_updated: number; users_removed: number; users_failed: number; users_ignored: number; user_sync_ignored: boolean; error_code: string | null; started_at: string | null; heartbeat_at: string | null; completed_at: string | null };
export type IdentitySyncRunResponse = { id: string; source: string; status: string; trigger_type: string; requested_scope: "people" | "groups" | "people_and_groups"; phase: string; queued_at: string; started_at: string | null; heartbeat_at: string | null; completed_at: string | null; users_created: number; users_updated: number; users_disabled: number; groups_created: number; groups_updated: number; role_memberships_updated: number; error_message: string | null; error_code: string | null; attempt: number; provider_results: IdentitySyncProviderResultResponse[] };


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
