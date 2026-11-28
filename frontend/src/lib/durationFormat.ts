import type { TranslationKey } from "@/lib/i18n";

type Format = (key: TranslationKey, params: Record<string, string | number>) => string;

/** CHG-495: a wait time in minutes, hours or days (one decimal); "—" when nothing was completed. */
export function formatWaitDuration(seconds: number | null | undefined, format: Format) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 3600) return format("approvalDurationMinutes", { value: Math.max(1, Math.round(seconds / 60)) });
  if (seconds < 86400) return format("approvalDurationHours", { value: Math.round(seconds / 360) / 10 });
  return format("approvalDurationDays", { value: Math.round(seconds / 8640) / 10 });
}
