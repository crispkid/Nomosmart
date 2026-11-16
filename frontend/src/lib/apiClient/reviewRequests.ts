// Approval, lifecycle, reference, graph, chat, report and notification requests (split from lib/api.ts, OPT424-038).
import { apiBaseUrl } from "@/lib/oidc";
import { MutationOutcomeUnknown, TransportError } from "@/lib/transportError";
import { apiJson, apiResponseError, type ApiError, type ApiFetch } from "./core";
import type { DocumentSummary, DocumentUpdateResponse } from "./documentTypes";
import type {
  ApprovalPendingPublishResponse, ApprovalRequestResponse, ApprovalTaskDetail, ApprovalTaskResponse,
  DocumentReferenceImportResponse, LifecycleImpactResponse, PublishResult, ReferenceSourceProjectResponse,
  SwitchActiveVersionPayload
} from "./reviewTypes";
import type {
  NotificationCountResponse, NotificationResponse, ProjectChatConversationDeleteResponse,
  ChatTurnContext, ConversationMode, ProjectChatConversationPage, ProjectChatConversationResponse, ProjectChatQueryResponse,
  ProjectChatRecordResponse, ProjectGraphResponse, ProjectServingStatusResponse, ReportFilterOptionsResponse,
  ReportSummaryResponse, ValidationRunResponse
} from "./servingTypes";

export type CursorPage<T> = { items: T[]; has_more: boolean; next_cursor: string | null };
export type ApprovalPendingPublishPage = CursorPage<ApprovalPendingPublishResponse> & { total: number };
export type ApprovalTab = "mine" | "pending" | "history" | "rejected";
export type ApprovalListFilters = {
  project_id?: string; submitter_id?: string; q?: string; stage?: string; result?: string;
  priority?: string; source_type?: string; date_from?: string; date_to?: string;
};
export function listApprovalFilterOptions(apiFetch: ApiFetch, filters: { kind: "project" | "submitter"; tab: ApprovalTab; project_id?: string; q?: string }, cursor?: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: "20" });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  if (cursor) params.set("cursor", cursor);
  return apiJson<CursorPage<{ id: string; label: string }>>(apiFetch, `/approvals/filter-options?${params}`, { signal });
}
function approvalPage<T>(apiFetch: ApiFetch, path: string, cursor?: string | null, result?: string, filters: ApprovalListFilters = {}, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: "20" });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  if (cursor) params.set("cursor", cursor);
  if (result) params.set("result", result);
  return apiJson<CursorPage<T>>(apiFetch, `${path}?${params}`, { signal });
}
export function listPendingApprovalsPage(apiFetch: ApiFetch, cursor?: string | null, filters: ApprovalListFilters = {}, signal?: AbortSignal) { return approvalPage<ApprovalTaskResponse>(apiFetch, "/approvals/pending", cursor, undefined, filters, signal); }
export function listApprovalHistoryPage(apiFetch: ApiFetch, cursor?: string | null, filters: ApprovalListFilters = {}, signal?: AbortSignal) { return approvalPage<ApprovalTaskResponse>(apiFetch, "/approvals/history", cursor, undefined, filters, signal); }
export function listRejectedApprovalsPage(apiFetch: ApiFetch, cursor?: string | null, filters: ApprovalListFilters = {}, signal?: AbortSignal) { return approvalPage<ApprovalTaskResponse>(apiFetch, "/approvals/history", cursor, "rejected", filters, signal); }
export function listMyApprovalSubmissionsPage(apiFetch: ApiFetch, cursor?: string | null, filters: ApprovalListFilters = {}, signal?: AbortSignal) { return approvalPage<ApprovalRequestResponse>(apiFetch, "/approvals/my-submissions", cursor, undefined, filters, signal); }
export async function listPendingApprovals(apiFetch: ApiFetch) { return (await listPendingApprovalsPage(apiFetch)).items; }
export function listPendingPublishApprovalsPage(apiFetch: ApiFetch, cursor?: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: "20" });
  if (cursor) params.set("cursor", cursor);
  return apiJson<ApprovalPendingPublishPage>(apiFetch, `/approvals/pending-publish/page?${params}`, { signal });
}
export async function getApprovalTask(apiFetch: ApiFetch, approvalTaskId: string, signal?: AbortSignal) { return apiJson<ApprovalTaskDetail>(apiFetch, `/approvals/${approvalTaskId}`, { signal }); }
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
export async function listProjectReferenceSources(apiFetch: ApiFetch, projectId: string, signal?: AbortSignal) {
  return apiJson<ReferenceSourceProjectResponse[]>(apiFetch, `/projects/${projectId}/reference-sources`, { signal });
}
export async function importProjectDocumentReferences(apiFetch: ApiFetch, projectId: string, payload: { mode: "reference" | "copy"; items: Array<{ source_document_id: string; source_version_id: string; old_version_confirmed?: boolean }> }) {
  return apiJson<DocumentReferenceImportResponse>(apiFetch, `/projects/${projectId}/document-references/import`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function updateDocumentReferenceVersion(apiFetch: ApiFetch, referenceId: string, payload: { source_version_id: string; old_version_confirmed?: boolean }) {
  return apiJson<DocumentUpdateResponse>(apiFetch, `/document-references/${referenceId}/update`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
}
export async function getProjectGraph(apiFetch: ApiFetch, projectId: string, nodeLimit = 120, signal?: AbortSignal) {
  return apiJson<ProjectGraphResponse>(apiFetch, `/projects/${projectId}/graph?node_limit=${nodeLimit}`, { signal });
}
export async function getProjectGraphNeighbors(apiFetch: ApiFetch, projectId: string, nodeId: string, nodeLimit = 80) {
  const params = new URLSearchParams({ node_id: nodeId, node_limit: String(nodeLimit) });
  return apiJson<ProjectGraphResponse>(apiFetch, `/projects/${projectId}/graph/neighbors?${params.toString()}`);
}
export async function getDocumentVersionGraph(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, nodeLimit = 120, signal?: AbortSignal) {
  return apiJson<ProjectGraphResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/graph?node_limit=${nodeLimit}`, { signal });
}
export async function getProjectServingStatus(apiFetch: ApiFetch, projectId: string, signal?: AbortSignal) {
  return apiJson<ProjectServingStatusResponse>(apiFetch, `/projects/${projectId}/serving-status`, { signal });
}
type ChatQueryPayload = { question: string; document_version_ids?: string[] | null; scope_mode: "published" | "document_staging"; top_k?: number; conversation_id?: string | null; conversation_title?: string | null; conversation_mode?: ConversationMode; previous_record_id?: string | null };
type OpenResponsesCitation = ProjectChatQueryResponse["citations"][number];
type OpenResponsesResource = {
  id: string;
  output?: { content?: { text?: string; annotations?: { "nomosmart:citation"?: OpenResponsesCitation }[] }[] }[];
  "nomosmart:answer_status"?: "answered" | "no_answer";
  "nomosmart:conversation"?: { id?: string; title?: string; mode?: ConversationMode };
  "nomosmart:context"?: ChatTurnContext;
  previous_response_id?: string | null;
  "nomosmart:manifest_version_ids"?: string[];
  "nomosmart:selected_document_version_ids"?: string[];
  "nomosmart:llm_model_id"?: string | null;
  "nomosmart:latency_ms"?: number | null;
  "nomosmart:prompt_version"?: string | null;
  "nomosmart:system_prompt"?: { source?: string | null; version_id?: string | null; content_hash?: string | null };
};

/** CHG-434: chat test asks through the Open Responses entry `POST /responses` and streams the answer. */
export async function queryProjectChat(apiFetch: ApiFetch, projectId: string, payload: ChatQueryPayload, onDelta?: (answer: string) => void): Promise<ProjectChatQueryResponse> {
  const scope: Record<string, unknown> = { mode: payload.scope_mode };
  if (payload.document_version_ids) scope.document_version_ids = payload.document_version_ids;
  const conversation: Record<string, string> = {};
  if (payload.conversation_id) conversation.id = payload.conversation_id;
  if (payload.conversation_title) conversation.title = payload.conversation_title;
  if (payload.conversation_mode) conversation.mode = payload.conversation_mode;
  const body: Record<string, unknown> = { model: `nomosmart:project/${projectId}`, input: payload.question, stream: true, "nomosmart:scope": scope };
  if (payload.top_k) body["nomosmart:top_k"] = payload.top_k;
  if (Object.keys(conversation).length) body["nomosmart:conversation"] = conversation;
  if (payload.previous_record_id) body.previous_response_id = `resp_${payload.previous_record_id}`;
  let response: Response;
  try { response = await apiFetch(`${apiBaseUrl()}/responses`, { method: "POST", cache: "no-store", headers: { "content-type": "application/json", accept: "text/event-stream" }, body: JSON.stringify(body) }); }
  catch (error) {
    if (error instanceof TransportError || (error instanceof Error && ["AbortError", "TimeoutError"].includes(error.name))) throw new MutationOutcomeUnknown();
    throw error;
  }
  if (!response.ok) throw await openResponsesError(response);
  if (!response.body) throw new MutationOutcomeUnknown();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const event = parseSseEvent(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
      if (!event) continue;
      if (event.type === "response.output_text.delta" && typeof event.delta === "string") {
        answer += event.delta;
        onDelta?.(answer);
      } else if (event.type === "error") {
        throw streamError(event.error as Record<string, unknown> | undefined, response.status);
      } else if (event.type === "response.completed") {
        return chatQueryResult(event.response as OpenResponsesResource);
      }
    }
    if (done) break;
  }
  throw new MutationOutcomeUnknown();
}

function parseSseEvent(block: string): Record<string, unknown> | null {
  const data = block.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
  if (!data || data === "[DONE]") return null;
  try { return JSON.parse(data) as Record<string, unknown>; } catch { return null; }
}

function streamError(error: Record<string, unknown> | undefined, status: number): ApiError {
  const result = new Error(String(error?.message || "Chat request failed")) as ApiError;
  result.status = status >= 400 ? status : 502;
  result.code = String(error?.code || "api_error");
  result.details = { param: error?.param ?? null };
  return result;
}

async function openResponsesError(response: Response): Promise<ApiError> {
  const body = await response.clone().json().catch(() => ({})) as { error?: Record<string, unknown>; "nomosmart:request_id"?: string };
  if (!body.error || typeof body.error !== "object") return apiResponseError(response);
  const error = streamError(body.error, response.status);
  error.requestId = body["nomosmart:request_id"];
  return error;
}

function chatQueryResult(resource: OpenResponsesResource): ProjectChatQueryResponse {
  const part = resource.output?.[0]?.content?.[0];
  const citations: OpenResponsesCitation[] = [];
  const seen = new Set<string>();
  for (const annotation of part?.annotations ?? []) {
    const citation = annotation["nomosmart:citation"];
    if (citation && !seen.has(citation.chunk_id)) { seen.add(citation.chunk_id); citations.push(citation); }
  }
  const prompt = resource["nomosmart:system_prompt"];
  return {
    chat_record_id: resource.id.replace(/^resp_/, ""),
    conversation_id: resource["nomosmart:conversation"]?.id ?? null,
    conversation_title: resource["nomosmart:conversation"]?.title ?? null,
    answer: part?.text ?? "",
    citations,
    manifest_version_ids: resource["nomosmart:manifest_version_ids"] ?? [],
    selected_version_ids: resource["nomosmart:selected_document_version_ids"] ?? [],
    status: resource["nomosmart:answer_status"],
    retrieval_strategy: "hybrid",
    prompt_version: resource["nomosmart:prompt_version"] ?? null,
    system_prompt_source: prompt?.source ?? null,
    system_prompt_version_id: prompt?.version_id ?? null,
    previous_response_id: resource.previous_response_id?.replace(/^resp_/, "") ?? null,
    conversation_mode: resource["nomosmart:conversation"]?.mode,
    context: resource["nomosmart:context"],
  };
}
export async function listProjectChatConversationPage(apiFetch: ApiFetch, projectId: string, options?: { scope_mode?: "published" | "document_staging"; document_version_id?: string; cursor?: string; signal?: AbortSignal }) {
  const params = new URLSearchParams();
  params.set("scope_mode", options?.scope_mode ?? "published");
  if (options?.document_version_id) params.set("document_version_id", options.document_version_id);
  if (options?.cursor) params.set("cursor", options.cursor);
  const query = params.toString();
  const page = await apiJson<ProjectChatConversationPage>(apiFetch, `/projects/${projectId}/chat/conversations${query ? `?${query}` : ""}`, { signal: options?.signal });
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
export async function getProjectChatValidationRun(apiFetch: ApiFetch, projectId: string, runId: string, signal?: AbortSignal) {
  return apiJson<ValidationRunResponse>(apiFetch, `/projects/${projectId}/chat/validation-runs/${runId}`, { signal });
}
export async function retryFailedProjectChatValidationItems(apiFetch: ApiFetch, projectId: string, runId: string) {
  return apiJson<ValidationRunResponse>(apiFetch, `/projects/${projectId}/chat/validation-runs/${runId}/retry-failed`, { method: "POST" });
}
type ModelUsageReportFilters = { modelType?: string; usagePurpose?: string; sourceChannel?: string; usageStatus?: string };
type ReportQueryParams = { topic: string; dateFrom?: string; dateTo?: string; scope?: string; projectId?: string | null; page?: number; pageSize?: number } & ModelUsageReportFilters;
export async function getReportFilterOptions(apiFetch: ApiFetch, scope = "owner_projects", signal?: AbortSignal) {
  return apiJson<ReportFilterOptionsResponse>(apiFetch, `/reports/filter-options?scope=${encodeURIComponent(scope)}`, { signal });
}
export async function getReportSummary(apiFetch: ApiFetch, params: ReportQueryParams, signal?: AbortSignal) {
  const query = reportQuery(params);
  return apiJson<ReportSummaryResponse>(apiFetch, `/reports/summary?${query}`, { signal });
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
type NotificationPage = { items: NotificationResponse[]; has_more: boolean; next_cursor: string | null };
export async function listNotificationPage(apiFetch: ApiFetch, filters: { resolved?: boolean; cursor?: string } = {}) {
  const query = new URLSearchParams();
  if (filters.resolved !== undefined) query.set("resolved", String(filters.resolved));
  if (filters.cursor) query.set("cursor", filters.cursor);
  return apiJson<NotificationPage>(apiFetch, `/notifications${query.size ? `?${query}` : ""}`);
}
export async function getNotificationUnreadCount(apiFetch: ApiFetch, signal?: AbortSignal) { return apiJson<NotificationCountResponse>(apiFetch, "/notifications/unread-count", { signal }); }
export async function markNotificationRead(apiFetch: ApiFetch, notificationId: string) { return apiJson<NotificationResponse>(apiFetch, `/notifications/${notificationId}/read`, { method: "POST" }); }
export async function markAllNotificationsRead(apiFetch: ApiFetch) { return apiJson<NotificationCountResponse>(apiFetch, "/notifications/read-all", { method: "POST" }); }
export async function resolveNotification(apiFetch: ApiFetch, notificationId: string) { return apiJson<NotificationResponse>(apiFetch, `/notifications/${notificationId}/resolve`, { method: "POST" }); }
