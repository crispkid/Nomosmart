"use client";

import { useI18n } from "./i18nClient";

export function resourcePageTitle(task: string, name?: string | null, version?: string | null) {
  const resource = [name?.trim(), version?.trim()].filter(Boolean).join(" · ");
  return resource ? `${resource}｜${task}` : task;
}

/** React owns the sole title node, including SSR and Next route transitions. */
export function BrowserTitle({ label }: { label: string }) {
  const { format } = useI18n();
  return <title>{label.trim() ? format("workspaceBrowserTitle", { page: label.trim() }) : "NomoSmart"}</title>;
}
