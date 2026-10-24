"use client";

import { RotateCcw } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";
import { FeedbackMessage } from "./FeedbackMessage";

export function KnowledgeReadinessNotice({ stopped, busy, canRetry, onRetry }: {
  stopped: boolean; busy: boolean; canRetry: boolean; onRetry: () => void;
}) {
  const { t } = useI18n();
  return <FeedbackMessage tone={stopped && !busy ? "warning" : "info"} title={t(stopped && !busy ? "knowledgeReadinessUnconfirmed" : "knowledgeReadinessChecking")} actions={stopped ? <button className="action-button secondary" disabled={!canRetry || busy} onClick={onRetry} type="button">
      <RotateCcw size={16} />{t("knowledgeReadinessRecheck")}
    </button> : undefined} />;
}
