"use client";

import { DropdownSelect } from "@/components/DropdownSelect";

/* eslint-disable @next/next/no-html-link-for-pages -- Recovery links must also work after the Next router fails. */

import { useEffect } from "react";
import { ArrowLeft, Languages, RefreshCw, ShieldAlert } from "lucide-react";
import { initializeLocale, isSupportedLocale, localeStorageKey, setLocalePreference, supportedLocales, useI18n } from "@/lib/i18nClient";
import { BrowserTitle } from "@/lib/browserTitle";

export function RecoveryScreen({ kind, onRetry }: { kind: "notFound" | "region" | "global"; onRetry?: () => void }) {
  const { locale, setLocale, t } = useI18n();
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

  return <main className="recovery-page"><BrowserTitle label={title} />
    <section aria-labelledby="recovery-title" className="recovery-card">
      <header className="recovery-toolbar"><strong>NomoSmart</strong><label className="application-access-language">
        <Languages aria-hidden="true" size={17} /><span className="sr-only">{t("languageSwitcher")}</span>
        <DropdownSelect aria-label={t("languageSwitcher")} onChange={event => setLocale(event.target.value === "en" ? "en" : "zh")} value={locale}>
          {supportedLocales.map(item => <option key={item.code} value={item.code}>{item.label}</option>)}
        </DropdownSelect>
      </label></header>
      <ShieldAlert aria-hidden="true" className="recovery-icon" size={32} />
      <h1 id="recovery-title">{title}</h1>
      <p role={kind === "notFound" ? "status" : "alert"}>{t(kind === "notFound" ? "recoveryNotFoundHelp" : "recoveryErrorHelp")}</p>
      {kind === "global" ? <p className="recovery-reload-note">{t("recoveryReloadWarning")}</p> : null}
      <div className="recovery-actions">
        {kind !== "notFound" ? <button className="action-button" onClick={kind === "global" ? reload : onRetry} type="button"><RefreshCw aria-hidden="true" size={17} />{t(kind === "global" ? "recoveryReload" : "recoveryRetryRegion")}</button> : null}
        <a className="action-button secondary" href="/"><ArrowLeft aria-hidden="true" size={17} />{t("recoveryHome")}</a>
        <a className="text-link" href="/login">{t("recoveryLogin")}</a>
      </div>
    </section>
  </main>;
}
