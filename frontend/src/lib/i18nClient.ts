"use client";

import { useCallback, useSyncExternalStore } from "react";
import { formatTranslation, htmlLangForLocale, isSupportedLocale, localizeKnownMessage, localizeKnownMessageOrNull, t as translate, type Locale, type TranslationKey } from "@/lib/i18n";

export { htmlLangForLocale, isSupportedLocale, supportedLocales, type Locale, type TranslationKey } from "@/lib/i18n";

export const localeStorageKey = "nomosmart_locale";

const localeListeners = new Set<() => void>();
let activeLocale: Locale = "zh";

export function localeFromDocument(): Locale {
  if (typeof document === "undefined") return "zh";
  return document.documentElement.lang.toLowerCase().startsWith("en") ? "en" : "zh";
}

export function readStoredLocale(): Locale {
  if (typeof window === "undefined") return activeLocale;
  const savedLocale = window.localStorage.getItem(localeStorageKey);
  return isSupportedLocale(savedLocale) ? savedLocale : localeFromDocument();
}

function emitLocaleChange() {
  for (const listener of localeListeners) listener();
}

export function getCurrentLocale() {
  return activeLocale;
}

export function setLocalePreference(nextLocale: Locale, persist = true) {
  activeLocale = nextLocale;
  if (typeof document !== "undefined") document.documentElement.lang = htmlLangForLocale(nextLocale);
  if (persist && typeof window !== "undefined") window.localStorage.setItem(localeStorageKey, nextLocale);
  emitLocaleChange();
}

export function initializeLocale() {
  if (typeof window === "undefined") return activeLocale;
  const nextLocale = readStoredLocale();
  setLocalePreference(nextLocale, false);
  return nextLocale;
}

function subscribeLocale(listener: () => void) {
  localeListeners.add(listener);
  return () => localeListeners.delete(listener);
}

export function useI18n() {
  const locale = useSyncExternalStore(subscribeLocale, getCurrentLocale, getCurrentLocale);
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
