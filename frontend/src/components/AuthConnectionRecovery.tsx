"use client";

import { BrowserTitle } from "@/lib/browserTitle";

import { BrandMark } from "./BrandMark";
import { FeedbackMessage } from "./FeedbackMessage";
import { RefreshCw, WifiOff } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";

/** K002 (CHG-495 S01): full-page card while the sign-in state cannot be confirmed. */
export function AuthConnectionRecovery({ busy, failed, onRetry }: { busy: boolean; failed: boolean; onRetry: () => void }) {
  const { t } = useI18n();
  return <main className="auth-connection-recovery state-page"><BrowserTitle label={t("authConnectionInterrupted")} />
    <header className="state-page-brand"><BrandMark size={24} /><span>NomoSmart</span></header>
    <section aria-labelledby="auth-recovery-title" className="state-card">
      <span className="state-card-icon tone-amber"><WifiOff aria-hidden="true" size={24} /></span>
      <h1 id="auth-recovery-title">{t("authConnectionInterrupted")}</h1>
      <p className="state-card-description">{t("authConnectionRecoveryHelp")}</p>
      <FeedbackMessage tone={failed ? "error" : "info"}>{busy ? t("authConnectionRetrying") : failed ? t("authConnectionRetryFailed") : t("authConnectionWaiting")}</FeedbackMessage>
      <div className="state-card-actions">
        <button className="action-button" type="button" disabled={busy} onClick={onRetry}><RefreshCw size={16} aria-hidden="true" />{t("authConnectionRetry")}</button>
      </div>
    </section>
  </main>;
}
