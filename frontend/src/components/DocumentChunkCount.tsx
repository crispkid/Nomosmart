"use client";

import { useI18n } from "@/lib/i18nClient";

export function DocumentChunkCount({ state, count, canRetry, onRetry }: {
  state: "known" | "pending" | "failed"; count: number | null; canRetry: boolean; onRetry: () => void;
}) {
  const { t, format } = useI18n();
  return <span>{state === "known"
    ? count === null ? t("documentChunkCountUnknown") : format("projectImportChunkCount", { count })
    : <><span role="status">{t(state === "pending" ? "documentChunkCountUpdating" : "documentChunkCountFailed")}</span>{state === "failed" ? <button className="action-button secondary" type="button" disabled={!canRetry} onClick={onRetry}>{t("documentChunkCountRetry")}</button> : null}</>}</span>;
}
