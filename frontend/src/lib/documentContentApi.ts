import { apiJson, type ApiFetch, type OriginalFileViewerMetadata } from "./api";

export type ContentEditorSource = {
  project_id: string; document_id: string; document_version_id: string;
  document_title: string; version_label: string; document_lock_version: number; lock_version: number;
  content_revision: number; markdown: string; canonical_sha256: string;
  original_source_sha256: string | null; edit_mode: "readonly" | "overwrite_candidate" | "create_revision";
  reason_code: string | null; max_utf8_bytes: number; original_file: OriginalFileViewerMetadata | null;
  selection_ranges: { start: number; end: number; content_revision: number; offset_unit: "unicode_code_point" }[];
  selection_reason: string | null;
  failed_update?: { update_id: string; target_sha256: string; reason_code: string; pending_markdown: string; can_cancel: boolean } | null;
};
export type ContentUpdateResult = {
  changed: boolean; document_version_id: string; version_label: string; lock_version: number;
  content_revision: number; update_id: string | null; status: string;
};
export type ContentUpdateStatus = {
  update_id: string; document_version_id: string; status: "queued" | "running" | "failed" | "blocked" | "ready" | "chunks_required" | "cancelled";
  step_name: string; content_revision: number; canonical_sha256: string; error_code: string | null; retry_allowed: boolean;
  chunking_issue?: import("./api").ChunkingIssue | null;
  promoted?: boolean;
  cleanup?: { status: "pending" | "running" | "completed"; retired_chunks?: number; retired_builds?: number } | null;
};
const base = (project: string, document: string, version: string) => `/projects/${project}/documents/${document}/versions/${version}`;
export function getContentEditor(api: ApiFetch, project: string, document: string, version: string, chunk?: string, signal?: AbortSignal) {
  return apiJson<ContentEditorSource>(api, `${base(project, document, version)}/content-editor${chunk ? `?chunk_id=${encodeURIComponent(chunk)}` : ""}`, { signal });
}
export function saveContent(api: ApiFetch, source: ContentEditorSource, markdown: string, key: string) {
  return apiJson<ContentUpdateResult>(api, `${base(source.project_id, source.document_id, source.document_version_id)}/content-updates`, {
    method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify({ document_lock_version: source.document_lock_version, lock_version: source.lock_version,
      base_content_revision: source.content_revision, base_canonical_sha256: source.canonical_sha256, markdown,
      ...(source.failed_update ? { recover_update_id: source.failed_update.update_id } : {}) })
  });
}
export function cancelFailedContent(api: ApiFetch, source: ContentEditorSource, key: string) {
  return apiJson<ContentUpdateResult>(api, `${base(source.project_id, source.document_id, source.document_version_id)}/content-updates/${source.failed_update!.update_id}/cancel`, {
    method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify({ document_lock_version: source.document_lock_version, lock_version: source.lock_version,
      base_content_revision: source.content_revision, base_canonical_sha256: source.canonical_sha256 })
  });
}
export function retryContent(api: ApiFetch, project: string, document: string, version: string, update: string, lock: number) {
  return apiJson<ContentUpdateStatus>(api, `${base(project, document, version)}/content-updates/${update}/retry`, {
    method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ lock_version: lock })
  });
}
