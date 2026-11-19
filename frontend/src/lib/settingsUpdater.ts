import type { TranslationKey } from "@/lib/i18n";

/** CHG-449 DISP449-002: who last changed a setting, without ever showing a user id. */
export function settingsUpdaterLabel(metadata: { updated_by: string | null; updated_by_name?: string | null } | undefined, t: (key: TranslationKey) => string): string {
  if (!metadata?.updated_by) return t("settingsUpdatedBySystem");
  return metadata.updated_by_name?.trim() || t("settingsUpdatedByUnknown");
}
