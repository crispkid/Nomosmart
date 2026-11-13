// Approval, lifecycle, reference, graph, chat, report and notification requests (split from lib/api.ts, OPT424-038).
import { apiBaseUrl } from "@/lib/oidc";
import { apiJson, apiResponseError, type ApiFetch } from "./core";
import type { DocumentSummary, DocumentUpdateResponse } from "./documentTypes";
import type {
  ApprovalPendingPublishResponse, ApprovalRequestResponse, ApprovalTaskDetail, ApprovalTaskResponse,
  DocumentReferenceImportResponse, LifecycleImpactResponse, PublishResult, ReferenceSourceProjectResponse,
  SwitchActiveVersionPayload
} from "./reviewTypes";
import type {
  NotificationCountResponse, NotificationResponse, ProjectChatConversationDeleteResponse,
  ProjectChatConversationPage, ProjectChatConversationResponse, ProjectChatQueryResponse,
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
export function listApprovalFilterOptions(apiFetch: ApiFetch, filters: { kind: "project" | "submitter"; tab: ApprovalTab; project_id?: string; q?: string }, cursor?: string | null) {
  const params = new URLSearchParams({ limit: "20" });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  if (cursor) params.set("cursor", cursor);
  return apiJson<CursorPage<{ id: string; label: string }>>(apiFetch, `/approvals/filter-options?${params}`);
}
function approvalPage<T>(apiFetch: ApiFetch, path: string, cursor?: string | null, result?: string, filters: ApprovalListFilters = {}) {
  const params = new URLSearchParams({ limit: "20" });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  if (cursor) params.set("cursor", cursor);
  if (result) params.set("result", result);
  return apiJson<CursorPage<T>>(apiFetch, `${path}?${params}`);
}
export function listPendingApprovalsPage(apiFetch: ApiFetch, cursor?: string | null, filters: ApprovalListFilters = {}) { return approvalPage<ApprovalTaskResponse>(apiFetch, "/approvals/pending", cursor, undefined, filters); }
export function listApprovalHistoryPage(apiFetch: ApiFetch, cursor?: string | null, filters: ApprovalListFilters = {}) { return approvalPage<ApprovalTaskResponse>(apiFetch, "/approvals/history", cursor, undefined, filters); }
export function listRejectedApprovalsPage(apiFetch: ApiFetch, cursor?: string | null, filters: ApprovalListFilters = {}) { return approvalPage<ApprovalTaskResponse>(apiFetch, "/approvals/history", cursor, "rejected", filters); }
export function listMyApprovalSubmissionsPage(apiFetch: ApiFetch, cursor?: string | null, filters: ApprovalListFilters = {}) { return approvalPage<ApprovalRequestResponse>(apiFetch, "/approvals/my-submissions", cursor, undefined, filters); }
export async function listPendingApprovals(apiFetch: ApiFetch) { return (await listPendingApprovalsPage(apiFetch)).items; }
export async function listApprovalHistory(apiFetch: ApiFetch) { return (await listApprovalHistoryPage(apiFetch)).items; }
export async function listRejectedApprovals(apiFetch: ApiFetch) { return (await listRejectedApprovalsPage(apiFetch)).items; }
export async function listMyApprovalSubmissions(apiFetch: ApiFetch) { return (await listMyApprovalSubmissionsPage(apiFetch)).items; }
export async function listPendingPublishApprovals(apiFetch: ApiFetch) { return apiJson<ApprovalPendingPublishResponse[]>(apiFetch, "/approvals/pending-publish"); }
export function listPendingPublishApprovalsPage(apiFetch: ApiFetch, cursor?: string | null) {
  const params = new URLSearchParams({ limit: "20" });
  if (cursor) params.set("cursor", cursor);
  return apiJson<ApprovalPendingPublishPage>(apiFetch, `/approvals/pending-publish/page?${params}`);
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
export async function queryProjectChat(apiFetch: ApiFetch, projectId: string, payload: { question: string; document_version_ids?: string[] | null; scope_mode: "published" | "document_staging"; top_k?: number; conversation_id?: string | null; conversation_title?: string | null }) {
  return apiJson<ProjectChatQueryResponse>(apiFetch, `/projects/${projectId}/chat/query`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
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
export type NotificationPage = { items: NotificationResponse[]; has_more: boolean; next_cursor: string | null };
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
