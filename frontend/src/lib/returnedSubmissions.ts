import { listMyApprovalSubmissionsPage, type ApiFetch, type ApprovalRequestResponse } from "@/lib/api";

/**
 * CHG-496 HOME496-001: returned submissions that still need the submitter. A returned request stays
 * `rejected` after the document is revised and submitted again, so a returned submission is open only
 * while it is still the newest submission of its document (D496-04, option C).
 */
type Submission = { id: string; document_id: string };

/**
 * The newest returned submission of each document, in list order (the list is newest first). Pass the
 * same `seen` set for every page so a document found on an earlier page is not checked again.
 */
export function returnedCandidates<T extends Submission>(rejected: readonly T[], seen: Set<string> = new Set()): T[] {
  return rejected.filter(item => !seen.has(item.document_id) && (seen.add(item.document_id), true));
}

/** Returned-list pages read at most (20 each), so a long history cannot flood the home page. */
export const returnedPageLimit = 5;

/** Open when no newer submission of the same document exists. */
export function isOpenReturned(returned: Submission, newestOfDocument: Submission | undefined): boolean {
  return newestOfDocument?.id === returned.id;
}

/**
 * Reads the returned submissions page by page (cursor), checks each document's newest submission
 * through the existing `document_id` filter a few at a time, and stops when `limit` open ones are
 * found, the list ends, or `returnedPageLimit` pages were read (D496-04 options C and A).
 */
export async function readOpenReturnedSubmissions(apiFetch: ApiFetch, limit: number, signal?: AbortSignal): Promise<ApprovalRequestResponse[]> {
  const seen = new Set<string>();
  const open: ApprovalRequestResponse[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < returnedPageLimit && open.length < limit; page += 1) {
    const rejected = await listMyApprovalSubmissionsPage(apiFetch, cursor, { result: "rejected" }, signal);
    const candidates = returnedCandidates(rejected.items, seen);
    for (let start = 0; start < candidates.length && open.length < limit; start += limit) {
      const batch = candidates.slice(start, start + limit);
      const newest = await Promise.all(batch.map(item => listMyApprovalSubmissionsPage(apiFetch, null, { document_id: item.document_id }, signal)));
      batch.forEach((item, index) => { if (isOpenReturned(item, newest[index].items[0])) open.push(item); });
    }
    if (!rejected.has_more || !rejected.next_cursor) break;
    cursor = rejected.next_cursor;
  }
  return open.slice(0, limit);
}
