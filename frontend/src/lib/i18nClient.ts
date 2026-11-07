"use client";

import { createContext, useCallback, useContext, useSyncExternalStore } from "react";
import { formatTranslation, htmlLangForLocale, isSupportedLocale, localePreferenceKey, localizeKnownMessage, localizeKnownMessageOrNull, t as translate, type Locale, type TranslationKey } from "@/lib/i18n";

export { htmlLangForLocale, isSupportedLocale, supportedLocales, type Locale, type TranslationKey } from "@/lib/i18n";

export const localeStorageKey = localePreferenceKey;
export const LocaleSnapshotContext = createContext<Locale>("zh");

const localeListeners = new Set<() => void>();
let activeLocale: Locale | null = null;

export function localeFromDocument(): Locale {
  if (typeof document === "undefined") return "zh";
  return document.documentElement.lang.toLowerCase().startsWith("en") ? "en" : "zh";
}

export function readStoredLocale(): Locale {
  if (typeof window === "undefined") return "zh";
  try {
    const savedLocale = window.localStorage.getItem(localeStorageKey);
    if (isSupportedLocale(savedLocale)) return savedLocale;
  } catch { /* Preference storage is optional; authentication must remain usable. */ }
  return localeFromDocument();
}

function emitLocaleChange() {
  for (const listener of localeListeners) listener();
}

export function getCurrentLocale() {
  return activeLocale ?? localeFromDocument();
}

export function setLocalePreference(nextLocale: Locale, persist = true) {
  if (typeof window === "undefined" || !isSupportedLocale(nextLocale)) return;
  const changed = getCurrentLocale() !== nextLocale;
  activeLocale = nextLocale;
  document.documentElement.lang = htmlLangForLocale(nextLocale);
  if (persist) {
    try { window.localStorage.setItem(localeStorageKey, nextLocale); }
    catch { /* Keep the in-memory preference when persistence is unavailable. */ }
  }
  try {
    document.cookie = `${localePreferenceKey}=${nextLocale}; Path=/; Max-Age=31536000; SameSite=Lax${window.location.protocol === "https:" ? "; Secure" : ""}`;
  } catch { /* A blocked preference cookie must not break login. */ }
  if (changed) emitLocaleChange();
}

export function initializeLocale() {
  if (typeof window === "undefined") return "zh";
  const nextLocale = readStoredLocale();
  setLocalePreference(nextLocale, false);
  return nextLocale;
}

function subscribeLocale(listener: () => void) {
  localeListeners.add(listener);
  return () => localeListeners.delete(listener);
}

export function useI18n() {
  const initialLocale = useContext(LocaleSnapshotContext);
  const serverSnapshot = useCallback(() => initialLocale, [initialLocale]);
  const locale = useSyncExternalStore(subscribeLocale, getCurrentLocale, serverSnapshot);
  const t = useCallback(
    (key: TranslationKey, requestedLocale: Locale = locale) => translate(key, requestedLocale),
    [locale],
  );
  const format = useCallback(
    (key: TranslationKey, params: Record<string, string | number>) => formatTranslation(key, params, locale),
    [locale],
  );
  const localize = useCallback((message: string) => localizeKnownMessage(message, locale), [locale]);
  const localizeKnown = useCallback((message: string) => localizeKnownMessageOrNull(message, locale), [locale]);
  return {
    locale,
    setLocale: setLocalePreference,
    t,
    format,
    localize,
    localizeKnown,
  };
}
