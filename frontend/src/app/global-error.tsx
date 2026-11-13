"use client";

import "./globals.css";
import { RecoveryScreen } from "@/components/RecoveryScreen";
import { htmlLangForLocale, useI18n } from "@/lib/i18nClient";

export default function GlobalError() {
  const { locale } = useI18n();
  return <html lang={htmlLangForLocale(locale)}><body><RecoveryScreen kind="global" /></body></html>;
}
