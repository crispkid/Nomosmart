import { checkDocumentDuplicates, type ApiFetch, type DocumentDuplicateMatch } from "@/lib/api";

/** CHG-497 DUP497-002: the server checks at most this many content hashes per request. */
const HASHES_PER_REQUEST = 50;

/** Lowercase hex SHA-256 of a file's content, computed in the browser (D497-04). */
export async function contentSha256(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

/** The match for each file, in file order (null when the project has no same-content version). */
export function matchesForFiles(digests: readonly string[], matches: readonly DocumentDuplicateMatch[]): (DocumentDuplicateMatch | null)[] {
  const bySha = new Map(matches.map(match => [match.sha256, match]));
  return digests.map(digest => bySha.get(digest) ?? null);
}

/** A file is skipped when the project already has its content, unless the user chose to upload it anyway. */
export function skippedAsDuplicate(index: number, matches: readonly (DocumentDuplicateMatch | null)[] | null, uploadAnyway: readonly number[]): boolean {
  return Boolean(matches?.[index]) && !uploadAnyway.includes(index);
}

export async function checkUploadDuplicates(apiFetch: ApiFetch, projectId: string, files: readonly File[]): Promise<(DocumentDuplicateMatch | null)[]> {
  const digests = await Promise.all(files.map(contentSha256));
  const unique = Array.from(new Set(digests));
  const matches: DocumentDuplicateMatch[] = [];
  for (let start = 0; start < unique.length; start += HASHES_PER_REQUEST) {
    matches.push(...(await checkDocumentDuplicates(apiFetch, projectId, unique.slice(start, start + HASHES_PER_REQUEST))).matches);
  }
  return matchesForFiles(digests, matches);
}
