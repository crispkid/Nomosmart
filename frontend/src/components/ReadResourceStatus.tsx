"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { FeedbackMessage } from "./FeedbackMessage";
import { useI18n } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";

export function ReadResourceStatus({ loading, error, onRetry, label }: { loading: boolean; error?: unknown; onRetry: () => unknown; label?: string }) {
  const { t, format } = useI18n();
  if (loading) return <p className="read-resource-status" role="status"><Loader2 className="spin" size={16} />{label ? `${label} · ` : ""}{t("uiReadLoading")}</p>;
  if (error) return <FeedbackMessage title={label ? `${label} · ${t("uiReadUnavailable")}` : t("uiReadUnavailable")} actions={<button aria-label={label ? format("uiReadRetrySection", { section: label }) : t("uiReadRetry")} className="action-button secondary" onClick={() => { onRetry(); }} type="button"><RefreshCw size={16} />{t("uiReadRetry")}</button>}>{operationalErrorMessage(error, t, format)}</FeedbackMessage>;
  return null;
}
