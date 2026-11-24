"use client";

import { useEffect, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { getProjectRetrievalSettings, type ApiFetch, type ProjectRetrievalSettings } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";

/** CHG-486 TOPKP486-003: per-question K and P. Empty fields use the system defaults shown beside them. */
export type RetrievalOverride = { topK: string; topP: string };
export const EMPTY_RETRIEVAL_OVERRIDE: RetrievalOverride = { topK: "", topP: "" };

export function parseRetrievalOverride(value: RetrievalOverride): { top_k?: number; top_p?: number; invalid: boolean } {
  const result: { top_k?: number; top_p?: number; invalid: boolean } = { invalid: false };
  if (value.topK.trim()) {
    const k = Number(value.topK);
    if (Number.isInteger(k) && k >= 1 && k <= 20) result.top_k = k; else result.invalid = true;
  }
  if (value.topP.trim()) {
    const p = Number(value.topP);
    if (Number.isFinite(p) && p >= 0.1 && p <= 1) result.top_p = p; else result.invalid = true;
  }
  return result;
}

export function ChatRetrievalSettings({ apiFetch, projectId, value, onChange, disabled, t, format }: {
  apiFetch: ApiFetch; projectId: string; value: RetrievalOverride; onChange: (value: RetrievalOverride) => void; disabled?: boolean;
  t: (key: TranslationKey) => string; format: (key: TranslationKey, values: Record<string, string | number>) => string;
}) {
  const [settings, setSettings] = useState<ProjectRetrievalSettings | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getProjectRetrievalSettings(apiFetch, projectId, controller.signal).then(setSettings).catch(() => setSettings(null));
    return () => controller.abort();
  }, [apiFetch, projectId]);
  const parsed = parseRetrievalOverride(value);
  const reranking = Boolean(settings?.rerank_enabled && settings?.rerank_available);
  const customized = Boolean(value.topK.trim() || value.topP.trim());
  return <details className="chat-retrieval-settings">
    <summary><SlidersHorizontal size={15} aria-hidden="true" />{t("chatAdvancedSettings")}{customized ? <span className="chat-retrieval-settings-badge">{t("chatAdvancedCustomized")}</span> : null}</summary>
    <div className="chat-retrieval-settings-grid">
      <label><span>{t("chatTopKLabel")}</span>
        <input type="number" min={1} max={20} step={1} inputMode="numeric" disabled={disabled} value={value.topK} placeholder={settings ? String(settings.retrieval_top_k) : ""}
               aria-invalid={Boolean(value.topK.trim()) && parsed.top_k === undefined} onChange={event => onChange({ ...value, topK: event.target.value })} />
        <small>{settings ? format("chatTopKHelp", { value: settings.retrieval_top_k }) : t("chatTopKHelpUnknown")}</small>
      </label>
      <label><span>{t("chatTopPLabel")}</span>
        <input type="number" min={0.1} max={1} step={0.05} inputMode="decimal" disabled={disabled} value={value.topP} placeholder={settings ? String(settings.retrieval_top_p) : ""}
               aria-invalid={Boolean(value.topP.trim()) && parsed.top_p === undefined} onChange={event => onChange({ ...value, topP: event.target.value })} />
        <small>{reranking ? format("chatTopPHelp", { value: settings!.retrieval_top_p }) : t("chatTopPInactive")}</small>
      </label>
    </div>
    {parsed.invalid ? <small className="settings-field-error" role="alert">{t("chatRetrievalInvalid")}</small> : null}
    {customized ? <button className="text-link" type="button" disabled={disabled} onClick={() => onChange(EMPTY_RETRIEVAL_OVERRIDE)}>{t("chatAdvancedReset")}</button> : null}
  </details>;
}
