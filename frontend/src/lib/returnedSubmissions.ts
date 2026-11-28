/**
 * CHG-496 HOME496-001: returned submissions that still need the submitter. A returned request stays
 * `rejected` after the document is revised and submitted again, so only the newest submission of each
 * document counts. Items must be newest first (the my-submissions order).
 */
export function openReturnedSubmissions<T extends { document_id: string; status: string }>(items: readonly T[], limit: number): T[] {
  const seen = new Set<string>();
  const open: T[] = [];
  for (const item of items) {
    if (seen.has(item.document_id)) continue;
    seen.add(item.document_id);
    if (item.status === "rejected") open.push(item);
    if (open.length === limit) break;
  }
  return open;
}
