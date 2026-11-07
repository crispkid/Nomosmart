/** Count presentation only; callers retain raw numeric values for API/input. */
const formats = {
  zh: new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }),
  en: new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }),
};

export function formatCount(value: number, locale: "zh" | "en" = "zh"): string {
  return Number.isFinite(value) ? formats[locale].format(value) : "—";
}
