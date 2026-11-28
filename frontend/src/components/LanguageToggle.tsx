"use client";

import { supportedLocales, useI18n } from "@/lib/i18nClient";

/** CHG-495 M05: interface language as side-by-side buttons (sign-in, access denied and recovery screens). */
export function LanguageToggle({ className = "" }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();
  return <div className={`ws-segmented language-toggle ${className}`.trim()} role="group" aria-label={t("languageSwitcher")}>
    {supportedLocales.map(item => <button key={item.code} type="button" aria-pressed={locale === item.code} onClick={() => setLocale(item.code)}>{item.label}</button>)}
  </div>;
}
