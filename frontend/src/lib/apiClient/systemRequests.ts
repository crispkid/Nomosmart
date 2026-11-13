// User, role, model, prompt, permission, parameter, status and identity requests (split from lib/api.ts, OPT424-038).
import { apiBaseUrl } from "@/lib/oidc";
import { apiJson, apiResponseError, type ApiFetch } from "./core";
import type {
  AIModelListPage, AIModelResponse, CountedPage, ExternalGroupResponse, ExternalGroupRoleMapping,
  IdentitySyncRunResponse, OperationsStatusResponse, PermissionMatrixResponse, RoleExternalGroupMappingResponse,
  RoleResponse, RoleUsersResponse, SystemListOptions, SystemPromptResponse, UserSummary
} from "./identityTypes";
import type {
  AIModelPayload, AIModelUpdatePayload, BreakGlassStatusResponse, SystemParameterApiValues,
  SystemParameterSectionResponse, SystemParametersPayload, SystemParametersUpdatePayload, SystemPromptPayload,
  SystemPromptVersionPayload, UploadConfigResponse
} from "./servingTypes";

async function arrayPage<T>(apiFetch: ApiFetch, path: string, signal?: AbortSignal): Promise<CountedPage<T>> {
  signal?.throwIfAborted();
  const response = await apiFetch(`${apiBaseUrl()}${path}`, { cache: "no-store", signal });
  if (!response.ok) throw await apiResponseError(response);
  const items = await response.json() as T[];
  const header = response.headers.get("X-Total-Count");
  const total = Number(header);
  if (!Array.isArray(items) || header === null || !/^\d+$/.test(header) || !Number.isSafeInteger(total)) throw new Error("pagination_metadata_invalid");
  return { items, total };
}
export async function collectOffsetPages<T extends { id: string }>(read: (offset: number) => Promise<CountedPage<T>>): Promise<T[]> {
  const rows = new Map<string, T>();
  let offset = 0;
  for (;;) {
    const page = await read(offset);
    const before = rows.size;
    page.items.forEach(row => rows.set(row.id, row));
    offset += page.items.length;
    if (offset >= page.total) {
      if (rows.size !== page.total) throw new Error("pagination_changed_reload");
      return [...rows.values()];
    }
    if (!page.items.length || rows.size === before) throw new Error("pagination_metadata_invalid");
  }
}
function systemListQuery(options: SystemListOptions) {
  const params = new URLSearchParams({ offset: String(options.offset ?? 0), limit: String(options.limit ?? 20) });
  if (options.q?.trim()) params.set("q", options.q.trim());
  if (options.isActive !== undefined) params.set("is_active", String(options.isActive));
  return params;
}
export async function listUsersPage(apiFetch: ApiFetch, options: SystemListOptions & { scope?: "system" | "project_members"; authSource?: string } = {}): Promise<CountedPage<UserSummary>> {
  const params = systemListQuery(options);
  params.set("scope", options.scope ?? "system");
  if (options.authSource) params.set("auth_source", options.authSource);
  return arrayPage(apiFetch, `/users?${params}`, options.signal);
}
export async function listRolesPage(apiFetch: ApiFetch, options: SystemListOptions = {}): Promise<CountedPage<RoleResponse>> { return arrayPage(apiFetch, `/roles?${systemListQuery(options)}`, options.signal); }
export async function getUser(apiFetch: ApiFetch, id: string) { return apiJson<UserSummary>(apiFetch, `/users/${id}`); }
export async function getRole(apiFetch: ApiFetch, id: string) { return apiJson<RoleResponse>(apiFetch, `/roles/${id}`); }
export async function listUsers(apiFetch: ApiFetch, scope: "system" | "project_members" = "system") { return collectOffsetPages(offset => listUsersPage(apiFetch, { scope, offset, limit: 200 })); }
export async function updateUser(apiFetch: ApiFetch, userId: string, payload: { manager_delegate_user_id?: string | null; manager_delegate_start_at?: string | null; manager_delegate_end_at?: string | null; knowledge_owner?: boolean | null; system_notes?: string | null }) { return apiJson<UserSummary>(apiFetch, `/users/${userId}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function updateUserStatus(apiFetch: ApiFetch, userId: string, isActive: boolean) { return apiJson<UserSummary>(apiFetch, `/users/${userId}/status`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ is_active: isActive }) }); }
export async function listRoles(apiFetch: ApiFetch) { return collectOffsetPages(offset => listRolesPage(apiFetch, { offset, limit: 200 })); }
export async function createRole(apiFetch: ApiFetch, payload: { name: string; description?: string | null }) { return apiJson<RoleResponse>(apiFetch, "/roles", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function updateRole(apiFetch: ApiFetch, roleId: string, payload: { lock_version: number; name?: string; description?: string | null; is_active?: boolean }) { return apiJson<RoleResponse>(apiFetch, `/roles/${roleId}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function deleteRole(apiFetch: ApiFetch, roleId: string, lockVersion: number, confirmationName: string) {
  const query = new URLSearchParams({ lock_version: String(lockVersion), confirmation_name: confirmationName });
  return apiJson<RoleResponse>(apiFetch, `/roles/${roleId}?${query.toString()}`, { method: "DELETE" });
}
export async function listModelsPage(apiFetch: ApiFetch, params: { modelType?: string; offset?: number; limit?: number; signal?: AbortSignal } = {}): Promise<AIModelListPage> {
  const query = new URLSearchParams();
  if (params.modelType) query.set("model_type", params.modelType);
  query.set("offset", String(params.offset ?? 0));
  query.set("limit", String(params.limit ?? 20));
  const response = await apiFetch(`${apiBaseUrl()}/models?${query.toString()}`, { cache: "no-store", signal: params.signal });
  if (!response.ok) {
    throw await apiResponseError(response);
  }
  const rows = await response.json() as AIModelResponse[];
  const totalHeader = response.headers.get("X-Total-Count");
  const parsedTotal = totalHeader === null ? Number.NaN : Number(totalHeader);
  return { rows, total: Number.isFinite(parsedTotal) ? parsedTotal : rows.length };
}
export async function listModels(apiFetch: ApiFetch, modelType?: string, signal?: AbortSignal) {
  const rows: AIModelResponse[] = [];
  const limit = 200;
  let offset = 0;
  while (true) {
    const page = await listModelsPage(apiFetch, { modelType, offset, limit, signal });
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
export async function getSystemParameters(apiFetch: ApiFetch, signal?: AbortSignal) {
  const value = await apiJson<SystemParametersPayload>(apiFetch, "/system/parameters", { signal });
  const keys: (keyof SystemParameterApiValues)[] = ["default_timezone", "session_expired_form_draft_ttl_minutes", "max_upload_size_mb", "staging_index_ttl_days", "ocr_request_max_output_tokens", "ocr_document_max_tokens"];
  if (!value.section_revisions || !["general", "documents"].every(section => /^[a-f0-9]{64}$/.test(value.section_revisions[section as "general" | "documents"]))
    || !value.parameter_defaults || !value.parameter_metadata || !Number.isInteger(value.deployment_max_upload_size_mb)
    || !keys.every(key => key === "default_timezone" ? typeof value[key] === "string" && typeof value.parameter_defaults[key] === "string" : Number.isInteger(value[key]) && Number.isInteger(value.parameter_defaults[key]))) {
    throw new Error("system_parameters_unavailable");
  }
  return value;
}
export async function getUploadConfig(apiFetch: ApiFetch, signal?: AbortSignal) { return apiJson<UploadConfigResponse>(apiFetch, "/system/upload-config", { signal }); }
export async function updateSystemParameters(apiFetch: ApiFetch, payload: SystemParametersUpdatePayload) { return apiJson<SystemParametersPayload>(apiFetch, "/system/parameters", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function getSystemStatus(apiFetch: ApiFetch) { return apiJson<OperationsStatusResponse>(apiFetch, "/system/status"); }



export async function getBreakGlassStatus(apiFetch: ApiFetch) { return apiJson<BreakGlassStatusResponse>(apiFetch, "/system/break-glass/status"); }





export async function queueIdentitySync(apiFetch: ApiFetch) { return apiJson<IdentitySyncRunResponse>(apiFetch, "/identity-sync/run", { method: "POST" }); }
export async function listIdentitySyncRuns(apiFetch: ApiFetch) { return (await apiJson<{ items: IdentitySyncRunResponse[]; has_more: boolean; next_cursor: string | null }>(apiFetch, "/identity-sync/runs")).items; }
export async function getIdentitySyncRun(apiFetch: ApiFetch, runId: string) { return apiJson<IdentitySyncRunResponse>(apiFetch, `/identity-sync/runs/${runId}`); }

export async function patchSystemParameters(apiFetch: ApiFetch, section: "general" | "documents", expected_revision: string, values: Partial<SystemParameterApiValues>) {
  return apiJson<SystemParameterSectionResponse>(apiFetch, "/system/parameters", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ section, expected_revision, values }) });
}
