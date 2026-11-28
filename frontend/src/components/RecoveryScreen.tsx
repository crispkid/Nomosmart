"use client";

/* eslint-disable @next/next/no-html-link-for-pages -- Recovery links must also work after the Next router fails. */

import { useEffect } from "react";
import { AlertTriangle, ArrowLeft, FileQuestion, RefreshCw } from "lucide-react";
import { initializeLocale, isSupportedLocale, localeStorageKey, setLocalePreference, useI18n } from "@/lib/i18nClient";
import { BrandMark } from "./BrandMark";
import { LanguageToggle } from "./LanguageToggle";
import { BrowserTitle } from "@/lib/browserTitle";

export function RecoveryScreen({ kind, onRetry }: { kind: "notFound" | "region" | "global"; onRetry?: () => void }) {
  const { t } = useI18n();
  const title = t(kind === "notFound" ? "recoveryNotFoundTitle" : "recoveryErrorTitle");
  useEffect(() => {
    let saved: string | null = null;
    try { saved = window.localStorage.getItem(localeStorageKey); }
    catch { /* Optional storage may be unavailable during recovery. */ }
    const cookie = document.cookie.split(";").map(value => value.trim())
      .find(value => value.startsWith(`${localeStorageKey}=`))?.slice(localeStorageKey.length + 1) ?? null;
    if (!isSupportedLocale(saved) && isSupportedLocale(cookie)) setLocalePreference(cookie, false);
    else initializeLocale();
  }, []);

  function reload() {
    // A fatal callback must never reload a consumed authorization code.
    if (window.location.pathname === "/auth/callback") window.location.replace("/login");
    else window.location.reload();
  }

  // K004/K005 (CHG-495 S01): full-page card; a region error keeps its own retry.
  return <main className="recovery-page state-page"><BrowserTitle label={title} />
    <header className="state-page-brand"><BrandMark size={24} /><span>NomoSmart</span></header>
    <section aria-labelledby="recovery-title" className="recovery-card state-card">
      <span className={`state-card-icon ${kind === "notFound" ? "tone-neutral" : "tone-danger"}`}>{kind === "notFound" ? <FileQuestion aria-hidden="true" size={24} /> : <AlertTriangle aria-hidden="true" size={24} />}</span>
      <h1 id="recovery-title">{title}</h1>
      <p className="state-card-description" role={kind === "notFound" ? "status" : "alert"}>{t(kind === "notFound" ? "recoveryNotFoundHelp" : "recoveryErrorHelp")}</p>
      {kind === "global" ? <p className="recovery-reload-note">{t("recoveryReloadWarning")}</p> : null}
      <LanguageToggle />
      <div className="state-card-actions">
        {kind !== "notFound" ? <button className="action-button" onClick={kind === "global" ? reload : onRetry} type="button"><RefreshCw aria-hidden="true" size={16} />{t(kind === "global" ? "recoveryReload" : "recoveryRetryRegion")}</button> : null}
        <a className={`action-button${kind === "notFound" ? "" : " secondary"}`} href="/"><ArrowLeft aria-hidden="true" size={16} />{t("recoveryHome")}</a>
        <a className="action-button secondary" href="/login">{t("recoveryLogin")}</a>
      </div>
    </section>
  </main>;
}
