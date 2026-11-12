"use client";

import { Check } from "lucide-react";
import type { OperationsStatusResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import { SettingsCard } from "../SettingsCard";
import { EmptyInlineState, StateBadge, metricPairs, operationStatusLabel, statusTone } from "./SystemUi";

/** Runtime, dependency, provider and recent-error status cards (OPT424-038). */
export function SystemStatusPanel({ status, ready }: { status: OperationsStatusResponse | null; ready: boolean }) {
  const { t, format } = useI18n();
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
        <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemComponent")}</th><th>{t("systemStatusColumn")}</th><th>{t("systemDetail")}</th><th>{t("systemChecked")}</th></tr></thead><tbody>{status.dependencies.map((component) => <tr key={component.name}><td><strong>{component.name}</strong></td><td><StateBadge tone={statusTone(component.status)}>{operationStatusLabel(component.status, t)}</StateBadge></td><td>{component.detail_code}</td><td>{component.checked_at.slice(0, 16).replace("T", " ")}</td></tr>)}</tbody></table></div>
      </SettingsCard>
      <SettingsCard panel="providers" title={t("systemAiProviders")}>
        <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemProviderRole")}</th><th>{t("systemStatusColumn")}</th><th>{t("systemDetail")}</th><th>{t("systemMetrics")}</th></tr></thead><tbody>{status.providers.map((component) => <tr key={component.name}><td><strong>{component.name}</strong></td><td><StateBadge tone={statusTone(component.status)}>{operationStatusLabel(component.status, t)}</StateBadge></td><td>{component.detail_code}</td><td>{metricPairs(component.metrics).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || "—"}</td></tr>)}</tbody></table></div>
      </SettingsCard>
      </div>
      <SettingsCard panel="errors" title={t("systemRecentErrors")}>
      {status.recent_errors.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemSourceColumn")}</th><th>{t("systemAction")}</th><th>{t("systemResult")}</th><th>{t("systemCode")}</th><th>{t("systemTime")}</th></tr></thead><tbody>{status.recent_errors.map((error) => <tr key={`${error.source}-${error.action}-${error.created_at}`}><td>{error.source}</td><td>{error.action}</td><td><StateBadge tone={statusTone(error.result === "success" ? "healthy" : "degraded")}>{operationStatusLabel(error.result, t)}</StateBadge></td><td>{error.detail_code}</td><td>{error.created_at.slice(0, 16).replace("T", " ")}</td></tr>)}</tbody></table></div> : <div className="empty-inline-state"><Check size={18} />{t("systemNoRecentErrors")}</div>}
      </SettingsCard>
    </> : ready ? <EmptyInlineState>{t("systemStatusUnavailable")}</EmptyInlineState> : null
  );
}
