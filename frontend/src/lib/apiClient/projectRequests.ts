// Session, project, integration client, member, document and knowledge requests (split from lib/api.ts, OPT424-038).
import { apiBaseUrl } from "@/lib/oidc";
import { apiJson, apiResponseError, type ApiFetch, type CurrentUser } from "./core";
import type {
  DataSourceConnectionPayload, DataSourceConnectionTestResponse, DataSourceCreateResponse, DataSyncRunResponse,
  DocumentSummary, DocumentUpdateResponse, DocumentUploadResponse, PipelineRunDetail, PipelineSummary
} from "./documentTypes";
import type { DataSourceConnectionOptions } from "./identityTypes";
import type {
  IntegrationClientCreateResponse, IntegrationClientPage, IntegrationClientPayload, IntegrationClientResponse,
  ProjectArchiveImpactResponse, ProjectCreatePayload, ProjectListOptions, ProjectListPage,
  ProjectMemberCandidatePage, ProjectMemberResponse, ProjectMemberUpdatePayload, ProjectResponse
} from "./projectTypes";
import type { ApprovalRequestResponse, ApprovalSummary, KnowledgeDetailResponse, SubmissionEvidenceResponse } from "./reviewTypes";
import type { SessionDraftRestoreResponse } from "./servingTypes";
import { collectOffsetPages } from "./systemRequests";

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
  if (options.pdfModelState) params.set("pdf_model_state", options.pdfModelState);
  const response = await apiFetch(`${apiBaseUrl()}/projects?${params.toString()}`, { cache: "no-store", signal: options.signal });
  if (!response.ok) {
    throw await apiResponseError(response);
  }
  const items = await response.json() as ProjectResponse[];
  const header = response.headers.get("X-Total-Count");
  const total = Number(header);
  if (!Array.isArray(items) || header === null || !/^\d+$/.test(header) || !Number.isSafeInteger(total)) throw new Error("pagination_metadata_invalid");
  return { items, total };
}
export async function listProjects(apiFetch: ApiFetch, status: "active" | "archived" = "active") { return collectOffsetPages(offset => listProjectsPage(apiFetch, { status, offset, limit: 200 })); }
export async function getProject(apiFetch: ApiFetch, projectId: string) { return apiJson<ProjectResponse>(apiFetch, `/projects/${projectId}`); }
export async function createProject(apiFetch: ApiFetch, payload: ProjectCreatePayload) { return apiJson<ProjectResponse>(apiFetch, "/projects", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function getProjectArchiveImpact(apiFetch: ApiFetch, projectId: string) { return apiJson<ProjectArchiveImpactResponse>(apiFetch, `/projects/${projectId}/archive-impact`); }
export async function archiveProject(apiFetch: ApiFetch, projectId: string, payload: { lock_version: number; confirmation_name: string }) { return apiJson<ProjectResponse>(apiFetch, `/projects/${projectId}/archive`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) }); }
export async function retryProjectArchiveCleanup(apiFetch: ApiFetch, projectId: string) { return apiJson<ProjectResponse>(apiFetch, `/projects/${projectId}/archive-cleanup/retry`, { method: "POST" }); }
export async function listIntegrationClients(apiFetch: ApiFetch) {
  const items = new Map<string, IntegrationClientResponse>();
  const cursors = new Set<string>();
  let cursor: string | undefined;
  do {
    const page = await listIntegrationClientsPage(apiFetch, { cursor, limit: 100 });
    page.items.forEach(item => items.set(item.id, item));
    if (!page.has_more) return [...items.values()];
    if (!page.next_cursor || cursors.has(page.next_cursor)) throw new Error("pagination_metadata_invalid");
    cursors.add(page.next_cursor); cursor = page.next_cursor;
  } while (cursor);
  throw new Error("pagination_metadata_invalid");
}
export async function listIntegrationClientsPage(apiFetch: ApiFetch, options: { name?: string; cursor?: string; limit?: number; signal?: AbortSignal } = {}) {
  const params = new URLSearchParams({ limit: String(options.limit ?? 20) });
  if (options.name?.trim()) params.set("name", options.name.trim());
  if (options.cursor) params.set("cursor", options.cursor);
  return apiJson<IntegrationClientPage>(apiFetch, `/integration-clients?${params}`, { signal: options.signal });
}
export async function getIntegrationClient(apiFetch: ApiFetch, id: string) { return apiJson<IntegrationClientResponse>(apiFetch, `/integration-clients/${id}`); }
export async function getDataSourceConnectionOptions(apiFetch: ApiFetch, projectId: string) { return apiJson<DataSourceConnectionOptions>(apiFetch, `/projects/${projectId}/data-sources/connection-options`); }
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
export async function uploadProjectDocuments(apiFetch: ApiFetch, projectId: string, files: File[], options: { ocrModelId?: string | null; startExtraction?: boolean } = {}) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  if (options.ocrModelId) form.append("ocr_model_id", options.ocrModelId);
  if (options.startExtraction) form.append("start_extraction", "true");
  return apiJson<DocumentUploadResponse>(apiFetch, `/projects/${projectId}/documents/upload`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: form
  });
}
export async function updateProjectDocumentFile(apiFetch: ApiFetch, projectId: string, documentId: string, file: File, options: { ocrModelId?: string | null } = {}) {
  const form = new FormData();
  form.append("files", file);
  if (options.ocrModelId) form.append("ocr_model_id", options.ocrModelId);
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
export async function startDocumentExtraction(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, payload: { ocr_model_id?: string | null }) {
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
export async function getKnowledgeArtifactBlob(apiFetch: ApiFetch, path: string, signal?: AbortSignal) {
  const response = await apiFetch(`${apiBaseUrl()}${path}`, { cache: "no-store", signal });
  if (!response.ok) {
    throw await apiResponseError(response);
  }
  return response.blob();
}
export async function retryPipelineStep(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, pipelineId: string, stepName: string) {
  return apiJson<PipelineRunDetail>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/pipelines/${pipelineId}/retry`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ step_name: stepName }) });
}
export async function getDocumentVersionSubmissionEvidence(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, signal?: AbortSignal) {
  return apiJson<SubmissionEvidenceResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/submission-evidence`, { signal });
}
export async function submitDocumentVersionReview(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, payload: { evidence_revision: string; lock_version: number; owner_user_id?: string | null }) {
  return apiJson<ApprovalRequestResponse>(apiFetch, `/projects/${projectId}/documents/${documentId}/versions/${versionId}/submit-review`, { method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify(payload) });
}
export async function getApprovalSummary(apiFetch: ApiFetch) { return apiJson<ApprovalSummary>(apiFetch, "/approvals/summary"); }
