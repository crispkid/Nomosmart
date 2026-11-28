"use client";

import { ToneBadge } from "@/components/AppShell";
import { approvalDueState } from "@/lib/approvalDue";
import { formatShortDate } from "@/lib/dateFormat";
import { useI18n } from "@/lib/i18nClient";

/** CHG-497 DUE497-001: overdue (danger), due today (amber) or the due date. */
export function ApprovalDueBadge({ dueAt }: { dueAt?: string | null }) {
  const { locale, format, t } = useI18n();
  const state = approvalDueState(dueAt);
  if (!state || !dueAt) return null;
  if (state === "overdue") return <ToneBadge tone="danger">{t("approvalDueOverdue")}</ToneBadge>;
  if (state === "today") return <ToneBadge tone="amber">{t("approvalDueToday")}</ToneBadge>;
  return <span className="approval-due-date">{format("approvalDueOn", { date: formatShortDate(dueAt, locale) })}</span>;
}
