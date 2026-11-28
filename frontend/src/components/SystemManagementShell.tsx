"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import { useI18n } from "@/lib/i18nClient";

const SystemHeadingContext = createContext<(label: string | null) => void>(() => {});

/** CHG-495 WP2 (A1Settings): the page heading names the open settings section under a System Management breadcrumb. */
export function useSystemHeading(label: string | null) {
  const setHeading = useContext(SystemHeadingContext);
  useEffect(() => { setHeading(label); return () => setHeading(null); }, [label, setHeading]);
}

export default function SystemManagementShell({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [heading, setHeading] = useState<string | null>(null);
  return <SystemHeadingContext.Provider value={setHeading}>
    <AppShell title={heading ?? t("system")} browserTitle={t("system")} breadcrumb={heading ? [{ label: t("labelSystemManagement") }] : undefined}>{children}</AppShell>
  </SystemHeadingContext.Provider>;
}
