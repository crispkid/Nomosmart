"use client";

import { BrowserTitle } from "@/lib/browserTitle";

import { BrandMark } from "./BrandMark";
import { FeedbackMessage } from "./FeedbackMessage";
import { LanguageToggle } from "./LanguageToggle";
import { useState } from "react";
import { LogOut, RefreshCw, ShieldX } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";

type ApplicationAccessDeniedProps = {
  userDisplayName: string;
  rechecking: boolean;
  recheckResult: "idle" | "denied" | "failed";
  onRecheck: () => Promise<void>;
  onLogout: () => Promise<void>;
};

/** K003 (CHG-495 S01): full-page card without the workspace navigation. */
export function ApplicationAccessDenied({
  userDisplayName,
  rechecking,
  recheckResult,
  onRecheck,
  onLogout,
}: ApplicationAccessDeniedProps) {
  const { t } = useI18n();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    await onLogout();
  }

  return (
    <main className="application-access-denied-page state-page"><BrowserTitle label={t("applicationAccessDeniedTitle")} />
      <header className="state-page-brand"><BrandMark size={24} /><span>NomoSmart</span></header>

      <section aria-labelledby="application-access-denied-title" className="application-access-denied-card state-card">
        <span className="state-card-icon tone-neutral"><ShieldX aria-hidden="true" size={24} /></span>
        <p className="state-card-eyebrow">{t("applicationAccessDeniedEyebrow")}</p>
        <h1 id="application-access-denied-title">{t("applicationAccessDeniedTitle")}</h1>
        <p className="state-card-description">{t("applicationAccessDeniedDescription")}</p>

        <div className="application-access-account">
          <span>{t("applicationAccessDeniedAccount")}</span>
          <strong>{userDisplayName}</strong>
        </div>

        <FeedbackMessage tone="warning" announce={recheckResult === "idle"}>{t("applicationAccessDeniedGuidance")}</FeedbackMessage>

        {recheckResult !== "idle" ? (
          <FeedbackMessage tone={recheckResult === "denied" ? "warning" : "error"}>
            {t(recheckResult === "denied" ? "applicationAccessDeniedStillDenied" : "applicationAccessDeniedRecheckFailed")}
          </FeedbackMessage>
        ) : null}

        <LanguageToggle />

        <div className="state-card-actions">
          <button className="action-button" disabled={rechecking || loggingOut} onClick={() => { void onRecheck(); }} type="button">
            <RefreshCw aria-hidden="true" className={rechecking ? "spin" : undefined} size={16} />
            {rechecking ? t("applicationAccessDeniedRechecking") : t("applicationAccessDeniedRecheck")}
          </button>
          <button className="action-button secondary" disabled={rechecking || loggingOut} onClick={() => { void handleLogout(); }} type="button">
            <LogOut aria-hidden="true" size={16} />
            {loggingOut ? t("loggingOut") : t("logout")}
          </button>
        </div>
      </section>
    </main>
  );
}
