"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { initializeLocale, LocaleSnapshotContext, type Locale } from "@/lib/i18nClient";

export function LocaleProvider({ initialLocale, children }: { initialLocale: Locale; children: ReactNode }) {
  const initialized = useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    initializeLocale();
  }, []);
  return <LocaleSnapshotContext.Provider value={initialLocale}>{children}</LocaleSnapshotContext.Provider>;
}
