"use client";

import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, MinusCircle, XCircle } from "lucide-react";
import type { OperationComponentStatus } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";

/** Shared system-management primitives (split from SystemManagementWorkspace, OPT424-038). */
export type StateTone = "green" | "gold" | "gray" | "coral";

const stateBadgeIcons = { green: CheckCircle2, gold: AlertTriangle, gray: MinusCircle, coral: XCircle } as const;

/** Tone is always paired with text and an icon, never color alone. */
export function StateBadge({ children, tone = "green" }: { children: ReactNode; tone?: StateTone }) {
  const Icon = stateBadgeIcons[tone];
  return <span className={`system-state system-state-${tone}`}><Icon aria-hidden="true" size={12} />{children}</span>;
}

export function statusTone(status: string): StateTone {
  if (status === "healthy") return "green";
  if (status === "degraded") return "gold";
  if (status === "unavailable") return "coral";
  return "gray";
}

export function operationStatusLabel(status: string, t: (key: TranslationKey) => string): string {
  if (status === "healthy") return t("systemOpHealthy");
  if (status === "degraded") return t("systemOpDegraded");
  if (status === "unavailable") return t("systemOpUnavailable");
  if (status === "success") return t("systemSuccess");
  if (status === "failed") return t("systemFailed");
  if (status === "stale") return t("systemConnectionStale");
  return status;
}

export function metricPairs(metrics: OperationComponentStatus["metrics"]) {
  return Object.entries(metrics).filter(([, value]) => value !== null && value !== undefined).slice(0, 4);
}

export function SectionHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="system-section-header"><div><h2>{title}</h2><p>{description}</p></div>{action}</div>;
}

export function EmptyInlineState({ children }: { children?: ReactNode }) {
  const { t } = useI18n();
  return <div className="empty-inline-state"><Info size={18} />{children ?? t("systemNoLiveData")}</div>;
}
