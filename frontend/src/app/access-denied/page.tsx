"use client";

import { useI18n } from "@/lib/i18nClient";

export default function AccessDeniedRoute() {
  const { t } = useI18n();
  return <main className="auth-loading" role="status">{t("authCheckingSession")}</main>;
}
