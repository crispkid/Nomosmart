"use client";

import { Check } from "lucide-react";
import { DataTable } from "@/components/DataTable";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import type { OperationsStatusResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import { SettingsCard } from "../SettingsCard";
import { EmptyInlineState, StateBadge, metricPairs, operationStatusLabel, statusTone } from "./SystemUi";

/** Runtime, dependency, provider and recent-error status cards (OPT424-038). */
export function SystemStatusPanel({ status, ready }: { status: OperationsStatusResponse | null; ready: boolean }) {
  const { t, format } = useI18n();
  // CHG-425 FIX425-009: explain how to recover when the CLI-initialized policy is missing or invalid.
  const policy = status?.dependencies.find((component) => component.name === "file_processing_policy");
  const policyNotReady = policy !== undefined && policy.status !== "healthy";
  return (
    status ? <>
      <SettingsCard panel="runtime" title={t("settingsRuntime")}><div className="system-status-grid">
      {[
        status.worker,
        status.queue,
        status.retrieval
      ].map((component) => <article className="system-status-card" key={component.name}><header><div><small>{component.name}</small><h3>{component.detail_code}</h3></div><StateBadge tone={statusTone(component.status)}>{operationStatusLabel(component.status, t)}</StateBadge></header><dl>{metricPairs(component.metrics).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl><small>{format("systemCheckedAt", { time: component.checked_at.slice(0, 16).replace("T", " ") })}</small></article>)}
      </div>
      </SettingsCard><div className="system-status-columns">
      <SettingsCard panel="dependencies" title={t("systemDependencies")}>
        <DataTable rows={status.dependencies} rowKey={component => component.name} columns={[
          { key: "component", header: t("systemComponent"), cell: component => <strong>{component.name}</strong> },
          { key: "status", header: t("systemStatusColumn"), cell: component => <StateBadge tone={statusTone(component.status)}>{operationStatusLabel(component.status, t)}</StateBadge> },
          { key: "detail", header: t("systemDetail"), cell: component => component.detail_code },
          { key: "checked", header: t("systemChecked"), cell: component => component.checked_at.slice(0, 16).replace("T", " ") },
        ]} />
        {policyNotReady ? <FeedbackMessage announce={false} title={t(policy.detail_code === "file_processing_policy_missing" ? "systemFileProcessingPolicyMissingTitle" : "systemFileProcessingPolicyInvalidTitle")} tone="warning">{t("systemFileProcessingPolicyGuidance")}</FeedbackMessage> : null}
      </SettingsCard>
      <SettingsCard panel="providers" title={t("systemAiProviders")}>
        <DataTable rows={status.providers} rowKey={component => component.name} columns={[
          { key: "provider", header: t("systemProviderRole"), cell: component => <strong>{component.name}</strong> },
          { key: "status", header: t("systemStatusColumn"), cell: component => <StateBadge tone={statusTone(component.status)}>{operationStatusLabel(component.status, t)}</StateBadge> },
          { key: "detail", header: t("systemDetail"), cell: component => component.detail_code },
          { key: "metrics", header: t("systemMetrics"), cell: component => metricPairs(component.metrics).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || "—" },
        ]} />
      </SettingsCard>
      </div>
      <SettingsCard panel="errors" title={t("systemRecentErrors")}>
      {status.recent_errors.length ? <DataTable rows={status.recent_errors} rowKey={error => `${error.source}-${error.action}-${error.created_at}`} columns={[
        { key: "source", header: t("systemSourceColumn"), cell: error => error.source },
        { key: "action", header: t("systemAction"), cell: error => error.action },
        { key: "result", header: t("systemResult"), cell: error => <StateBadge tone={statusTone(error.result === "success" ? "healthy" : "degraded")}>{operationStatusLabel(error.result, t)}</StateBadge> },
        { key: "code", header: t("systemCode"), cell: error => error.detail_code },
        { key: "time", header: t("systemTime"), cell: error => error.created_at.slice(0, 16).replace("T", " ") },
      ]} /> : <div className="empty-inline-state"><Check size={18} />{t("systemNoRecentErrors")}</div>}
      </SettingsCard>
    </> : ready ? <EmptyInlineState>{t("systemStatusUnavailable")}</EmptyInlineState> : null
  );
}
