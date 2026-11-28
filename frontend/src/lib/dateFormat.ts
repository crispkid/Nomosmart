/** Dates always follow the application locale, never the browser default (OPT424-034). */
type AppLocale = "en" | "zh";

function localeTag(locale: AppLocale): string {
  return locale === "en" ? "en-US" : "zh-TW";
}

export function formatShortDateTime(value: string | null | undefined, locale: AppLocale, empty = ""): string {
  if (!value) return empty;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(localeTag(locale), { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** CHG-495 M19: month and day only (station confirmation dates). */
export function formatShortDate(value: string | null | undefined, locale: AppLocale, empty = ""): string {
  if (!value) return empty;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(localeTag(locale), { month: "2-digit", day: "2-digit" });
}

export function formatTime(value: string | number | null | undefined, locale: AppLocale, empty = ""): string {
  if (value === null || value === undefined || value === "") return empty;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString(localeTag(locale), { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(value: string | null | undefined, locale: AppLocale, empty = ""): string {
  if (!value) return empty;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(localeTag(locale));
}
