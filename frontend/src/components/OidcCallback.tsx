"use client";

import { useEffect } from "react";
import { useAuth } from "@/components/AuthProvider";
import { useI18n } from "@/lib/i18nClient";

export default function OidcCallback({ code, state, flowId }: { code: string; state: string; flowId: string }) {
  const { subscribeOidcCallback } = useAuth();
  const { t } = useI18n();
  useEffect(() => subscribeOidcCallback(code, state, flowId), [code, state, flowId, subscribeOidcCallback]);
  return <main className="auth-loading" role="status">{t("oidcCallbackLoading")}</main>;
}
