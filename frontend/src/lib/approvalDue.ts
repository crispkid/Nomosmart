/** CHG-497 DUE497-001: how a pending task's due time reads to the user (local calendar day). */
export type DueState = "overdue" | "today" | "later";

export function approvalDueState(dueAt: string | null | undefined, now: Date = new Date()): DueState | null {
  if (!dueAt) return null;
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return null;
  if (due.getTime() <= now.getTime()) return "overdue";
  const sameDay = due.getFullYear() === now.getFullYear() && due.getMonth() === now.getMonth() && due.getDate() === now.getDate();
  return sameDay ? "today" : "later";
}
