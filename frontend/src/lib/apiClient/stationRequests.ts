// CHG-442 four-station extraction and chunk references (STAGE442-002/009/010, REF442-003).
import { apiJson, type ApiFetch } from "./core";
import type { ChunkReferenceItem, ChunkReferenceListResponse, KnowledgeDetailResponse } from "./reviewTypes";

const json = (method: string, body: unknown) => ({ method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const versionPath = (projectId: string, documentId: string, versionId: string) => `/projects/${projectId}/documents/${documentId}/versions/${versionId}`;

export async function confirmStation(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, station: number, lockVersion: number) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `${versionPath(projectId, documentId, versionId)}/stations/${station}/confirm`, json("POST", { lock_version: lockVersion }));
}
export async function reopenStation(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, station: number, lockVersion: number) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `${versionPath(projectId, documentId, versionId)}/stations/${station}/reopen`, json("POST", { lock_version: lockVersion }));
}
export async function createStationRevision(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, lockVersion: number) {
  return apiJson<KnowledgeDetailResponse>(apiFetch, `${versionPath(projectId, documentId, versionId)}/station-revision`, json("POST", { lock_version: lockVersion }));
}
export async function listChunkReferences(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, signal?: AbortSignal) {
  return apiJson<ChunkReferenceListResponse>(apiFetch, `${versionPath(projectId, documentId, versionId)}/chunk-references`, { signal });
}
export async function createChunkReference(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, payload: { chunk_id: string; raw_text: string; target_document_id?: string | null; external?: boolean }) {
  return apiJson<ChunkReferenceItem>(apiFetch, `${versionPath(projectId, documentId, versionId)}/chunk-references`, json("POST", payload));
}
export async function updateChunkReference(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, referenceId: string, payload: { lock_version: number; action: "assign" | "external" | "unresolve"; target_document_id?: string | null }) {
  return apiJson<ChunkReferenceItem>(apiFetch, `${versionPath(projectId, documentId, versionId)}/chunk-references/${referenceId}`, json("PATCH", payload));
}
export async function deleteChunkReference(apiFetch: ApiFetch, projectId: string, documentId: string, versionId: string, referenceId: string, lockVersion: number) {
  return apiJson<unknown>(apiFetch, `${versionPath(projectId, documentId, versionId)}/chunk-references/${referenceId}?lock_version=${lockVersion}`, { method: "DELETE" });
}
