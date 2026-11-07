import type { ApprovalListFilters, ApprovalTab } from "./api";

export type ApprovalFilterOption = { id: string; label: string };
export type ApprovalFilterValues = {
  project: ApprovalFilterOption | null; submitter: ApprovalFilterOption | null;
  query: string; stage: string; result: string; from: string; to: string;
  priority: string; source: string;
};
export const emptyApprovalFilters: ApprovalFilterValues = {
  project: null, submitter: null, query: "", stage: "", result: "", from: "", to: "", priority: "", source: ""
};

/** Local calendar boundaries, including DST, with PostgreSQL's full final microsecond. */
export function approvalDateBoundary(day: string, end = false): string | undefined {
  if (!day) return undefined;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) throw new Error("approvalFilterDateInvalid");
  const date = new Date(`${day}T00:00:00`);
  const [year, month, value] = day.split("-").map(Number);
  if (!Number.isFinite(date.getTime()) || date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== value) throw new Error("approvalFilterDateInvalid");
  if (!end) return date.toISOString();
  date.setDate(date.getDate() + 1);
  return new Date(date.getTime() - 1).toISOString().replace(".999Z", ".999999Z");
}

export function approvalListFilters(values: ApprovalFilterValues, tab: ApprovalTab): ApprovalListFilters {
  if (values.from && values.to && values.from > values.to) throw new Error("approvalFilterDateInvalid");
  return {
    project_id: values.project?.id,
    submitter_id: tab === "mine" ? undefined : values.submitter?.id,
    q: values.query.trim() || undefined, stage: values.stage || undefined,
    result: tab === "pending" ? undefined : tab === "rejected" ? "rejected" : values.result || undefined,
    date_from: approvalDateBoundary(values.from), date_to: approvalDateBoundary(values.to, true),
    priority: values.priority.trim() || undefined, source_type: values.source.trim() || undefined
  };
}
