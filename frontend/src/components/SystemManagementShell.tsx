"use client";

import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import { useI18n } from "@/lib/i18nClient";

export default function SystemManagementShell({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  return <AppShell title={t("system")}>{children}</AppShell>;
}
