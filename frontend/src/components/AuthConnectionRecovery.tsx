"use client";

import { RefreshCw } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";

export function AuthConnectionRecovery({ busy, failed, onRetry }: { busy: boolean; failed: boolean; onRetry: () => void }) {
  const { t } = useI18n();
  return <main className="auth-loading auth-connection-recovery">
    <section aria-labelledby="auth-recovery-title">
      <h1 id="auth-recovery-title">{t("authConnectionInterrupted")}</h1>
      <p>{t("authConnectionRecoveryHelp")}</p>
      <p role={failed ? "alert" : "status"} aria-live="polite">{busy ? t("authConnectionRetrying") : failed ? t("authConnectionRetryFailed") : t("authConnectionWaiting")}</p>
      <button className="action-button" type="button" disabled={busy} onClick={onRetry}><RefreshCw size={16} aria-hidden="true" />{t("authConnectionRetry")}</button>
    </section>
  </main>;
}
