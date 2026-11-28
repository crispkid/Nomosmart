import { listMyApprovalSubmissionsPage, type ApiFetch, type ApprovalRequestResponse } from "@/lib/api";

/**
 * CHG-496 HOME496-001: returned submissions that still need the submitter. A returned request stays
 * `rejected` after the document is revised and submitted again, so a returned submission is open only
 * while it is still the newest submission of its document (D496-04, option C).
 */
type Submission = { id: string; document_id: string };

/** The newest returned submission of each document, in list order (the list is newest first). */
export function returnedCandidates<T extends Submission>(rejected: readonly T[]): T[] {
  const seen = new Set<string>();
  return rejected.filter(item => !seen.has(item.document_id) && (seen.add(item.document_id), true));
}

/** Open when no newer submission of the same document exists. */
export function isOpenReturned(returned: Submission, newestOfDocument: Submission | undefined): boolean {
  return newestOfDocument?.id === returned.id;
}

/**
 * Reads the newest returned submissions (one page), then checks each document's newest submission
 * through the existing `document_id` filter, a few at a time, until `limit` open ones are found.
 */
export async function readOpenReturnedSubmissions(apiFetch: ApiFetch, limit: number, signal?: AbortSignal): Promise<ApprovalRequestResponse[]> {
  const rejected = await listMyApprovalSubmissionsPage(apiFetch, null, { result: "rejected" }, signal);
  const candidates = returnedCandidates(rejected.items);
  const open: ApprovalRequestResponse[] = [];
  for (let start = 0; start < candidates.length && open.length < limit; start += limit) {
    const batch = candidates.slice(start, start + limit);
    const newest = await Promise.all(batch.map(item => listMyApprovalSubmissionsPage(apiFetch, null, { document_id: item.document_id }, signal)));
    batch.forEach((item, index) => { if (isOpenReturned(item, newest[index].items[0])) open.push(item); });
  }
  return open.slice(0, limit);
}
