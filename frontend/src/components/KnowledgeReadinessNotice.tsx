"use client";

import { AlertTriangle, Loader2, RotateCcw } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";

export function KnowledgeReadinessNotice({ stopped, busy, canRetry, onRetry }: {
  stopped: boolean; busy: boolean; canRetry: boolean; onRetry: () => void;
}) {
  const { t } = useI18n();
  return <div className="review-banner warning" role="status" aria-live="polite">
    {stopped && !busy ? <AlertTriangle size={20} /> : <Loader2 className="spin" size={20} />}
    <span>{t(stopped && !busy ? "knowledgeReadinessUnconfirmed" : "knowledgeReadinessChecking")}</span>
    {stopped ? <button className="action-button secondary" disabled={!canRetry || busy} onClick={onRetry} type="button">
      <RotateCcw size={16} />{t("knowledgeReadinessRecheck")}
    </button> : null}
  </div>;
}
