"use client";

import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, MinusCircle, XCircle } from "lucide-react";
import type { OperationComponentStatus } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";

/** Shared system-management primitives (split from SystemManagementWorkspace, OPT424-038). */
type StateTone = "green" | "gold" | "gray" | "coral";

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

// CHG-495 M27: infrastructure services show a friendly name; the raw component name stays as small text.
const serviceNameKeys: Record<string, TranslationKey> = {
  postgresql: "systemServicePostgresql", redis: "systemServiceRedis", celery_broker: "systemServiceCeleryBroker",
  celery_result_backend: "systemServiceCeleryResultBackend", s3: "systemServiceS3", opensearch: "systemServiceOpensearch",
  neo4j: "systemServiceNeo4j", authentication: "systemServiceAuthentication", celery_worker: "systemServiceCeleryWorker",
  file_processing_policy: "systemServiceFileProcessingPolicy", "worker.celery": "systemServiceWorker",
  "queue.outbox": "systemServiceQueue", "retrieval.index": "systemServiceRetrieval"
};

/** Friendly name of a service, or null when the component is not a known service. */
export function serviceFriendlyName(name: string, t: (key: TranslationKey) => string): string | null {
  const key = serviceNameKeys[name];
  return key ? t(key) : null;
}

/** Friendly name with the raw component name underneath (M27). */
export function ServiceName({ name }: { name: string }) {
  const { t } = useI18n();
  const friendly = serviceFriendlyName(name, t);
  return friendly ? <span className="system-service-name"><strong>{friendly}</strong><small>{name}</small></span> : <span className="system-service-name"><strong>{name}</strong></span>;
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
