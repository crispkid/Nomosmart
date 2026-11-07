import type { Locale } from "@/lib/i18n";


type ReportCellValue = string | number | boolean | null | undefined;

const ratioFields = new Set([
  "cited_answer_rate",
  "error_rate",
  "failure_rate",
  "human_correct_rate",
  "needs_revision_rate",
  "no_answer_rate",
  "pass_rate",
  "success_rate",
  "validation_pass_rate"
]);

const moneyFields = new Set(["provider_reported_cost", "estimated_cost"]);
const latencyFields = new Set(["avg_latency_ms", "p95_latency_ms"]);

export function formatReportCell(
  key: string,
  value: ReportCellValue,
  locale: Locale,
  officialCostNotProvided: string,
) {
  if (value === null || value === undefined) {
    return key === "provider_reported_cost" ? officialCostNotProvided : "—";
  }
  if (typeof value !== "number") return value;
  if (!Number.isFinite(value)) return "—";

  const language = locale === "en" ? "en-US" : "zh-TW";
  if (ratioFields.has(key)) {
    return new Intl.NumberFormat(language, {
      style: "percent",
      maximumFractionDigits: 2,
    }).format(value);
  }
  if (moneyFields.has(key)) {
    return new Intl.NumberFormat(language, {
      maximumFractionDigits: 8,
      useGrouping: true,
    }).format(value);
  }
  if (latencyFields.has(key)) {
    return new Intl.NumberFormat(language, {
      maximumFractionDigits: 2,
      useGrouping: true,
    }).format(value);
  }
  return new Intl.NumberFormat(language, {
    maximumFractionDigits: 5,
    useGrouping: true,
  }).format(value);
}
