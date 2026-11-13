// Shared API transport: permission helpers, JSON requests and error mapping (split from lib/api.ts, OPT424-038).
import { apiBaseUrl } from "@/lib/oidc";
import { MutationOutcomeUnknown, TransportError } from "@/lib/transportError";
import { feedbackFailureReporter } from "@/lib/feedback";

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
  mode?: "oidc" | "ldap" | "emergency";
  csrf_token?: string;
  idle_expires_at?: string;
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
  init.signal?.throwIfAborted();
  const mutation = !["GET", "HEAD", "OPTIONS"].includes((init.method ?? "GET").toUpperCase());
  const reportFailure = feedbackFailureReporter();
  let response: Response;
  try { response = await apiFetch(`${apiBaseUrl()}${path}`, { ...init, cache: "no-store" }); }
  catch (error) {
    if (mutation && (error instanceof TransportError || (error instanceof Error && ["AbortError", "TimeoutError"].includes(error.name)))) { reportFailure(true); throw new MutationOutcomeUnknown(); }
    throw error;
  }
  if (!response.ok) {
    const error = await apiResponseError(response);
    if (mutation && (error.code === "backend_proxy_unreachable" || (error.code === "api_error" && error.status >= 500))) { reportFailure(true); throw new MutationOutcomeUnknown(); }
    if (mutation) reportFailure(["model_usage_persistence_unconfirmed", "embedding_build_provider_result_unknown", "ocr_image_provider_result_unknown", "content_update_provider_result_unknown"].includes(error.code));
    throw error;
  }
  if (response.status === 204) return undefined as T;
  try { return await response.json() as T; }
  catch (error) { if (mutation) { reportFailure(true); throw new MutationOutcomeUnknown(); } throw error; }
}

export async function apiResponseError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => ({})) as { code?: string; message?: string; details?: unknown; request_id?: string };
  const error = new Error(body.message || `API request failed with ${response.status}`) as ApiError;
  error.status = response.status;
  error.code = body.code || "api_error";
  error.details = body.details;
  error.requestId = body.request_id;
  return error;
}
