"use client";

import { FeedbackMessage } from "./FeedbackMessage";
import { useState } from "react";
import { Languages, LogOut, RefreshCw, ShieldX } from "lucide-react";
import { supportedLocales, useI18n } from "@/lib/i18nClient";

type ApplicationAccessDeniedProps = {
  userDisplayName: string;
  rechecking: boolean;
  recheckResult: "idle" | "denied" | "failed";
  onRecheck: () => Promise<void>;
  onLogout: () => Promise<void>;
};

export function ApplicationAccessDenied({
  userDisplayName,
  rechecking,
  recheckResult,
  onRecheck,
  onLogout,
}: ApplicationAccessDeniedProps) {
  const { locale, setLocale, t } = useI18n();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    await onLogout();
  }

  return (
    <main className="application-access-denied-page">
      <header className="application-access-denied-toolbar">
        <div className="brand">
          <span className="brand-mark">N</span>
          <span><strong>NomoSmart</strong><small>{t("brandEnterpriseKnowledgeOps")}</small></span>
        </div>
        <label className="application-access-language">
          <Languages aria-hidden="true" size={17} />
          <span className="sr-only">{t("languageSwitcher")}</span>
          <select
            aria-label={t("languageSwitcher")}
            onChange={(event) => setLocale(event.target.value === "en" ? "en" : "zh")}
            value={locale}
          >
            {supportedLocales.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
          </select>
        </label>
      </header>

      <section aria-labelledby="application-access-denied-title" className="application-access-denied-card">
        <span className="application-access-denied-icon"><ShieldX aria-hidden="true" size={30} /></span>
        <p className="eyebrow">{t("applicationAccessDeniedEyebrow")}</p>
        <h1 id="application-access-denied-title">{t("applicationAccessDeniedTitle")}</h1>
        <p className="application-access-denied-description">{t("applicationAccessDeniedDescription")}</p>

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

        <div className="application-access-actions">
          <button className="action-button" disabled={rechecking || loggingOut} onClick={() => { void onRecheck(); }} type="button">
            <RefreshCw aria-hidden="true" className={rechecking ? "spin" : undefined} size={17} />
            {rechecking ? t("applicationAccessDeniedRechecking") : t("applicationAccessDeniedRecheck")}
          </button>
          <button className="action-button secondary" disabled={rechecking || loggingOut} onClick={() => { void handleLogout(); }} type="button">
            <LogOut aria-hidden="true" size={17} />
            {loggingOut ? t("loggingOut") : t("logout")}
          </button>
        </div>
      </section>
    </main>
  );
}
