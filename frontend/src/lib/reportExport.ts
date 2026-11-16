export type ReportTopic =
  | "system_overview"
  | "project_ranking"
  | "project_reference_ranking"
  | "document_reference_ranking"
  | "owner_project_summary"
  | "document_pipeline_metrics"
  | "rag_quality_metrics"
  | "validation_run_metrics"
  | "model_usage_metrics"
  | "alert_metrics";

type CsvCell = string | number | boolean | null | undefined;
export type CsvRow = Record<string, CsvCell>;
type ReportCsvLocale = "zh" | "en";

export function buildReportFilename(topic: ReportTopic, dateFrom: string, dateTo: string) {
  return `nomosmart_${topic}_${dateFrom}_${dateTo}.csv`;
}

export function normalizeReportCsvLocale(language: string | null | undefined): ReportCsvLocale {
  return language?.toLowerCase().startsWith("en") ? "en" : "zh";
}

export function getReportHeaders(rows: CsvRow[], topic?: ReportTopic) {
  const topicHeaders = topic ? reportColumnHeaders[topic] : undefined;
  if (topicHeaders) return topicHeaders;
  return Array.from(rows.reduce((keys, row) => {
    Object.keys(row).forEach((key) => keys.add(key));
    return keys;
  }, new Set<string>()));
}

export function buildCsv(rows: CsvRow[], preferredHeaders?: string[], headerTitles?: string[]) {
  const headers = preferredHeaders && preferredHeaders.length > 0
    ? preferredHeaders
    : Array.from(rows.reduce((keys, row) => {
      Object.keys(row).forEach((key) => keys.add(key));
      return keys;
    }, new Set<string>()));
  const titles = headerTitles && headerTitles.length === headers.length ? headerTitles : headers;
  const lines = [
    titles.map((title) => escapeCsvCell(title)).join(","),
    ...rows.map((row) => headers.map((header) => escapeCsvCell(row[header])).join(","))
  ];
  return `\uFEFF${lines.join("\r\n")}\r\n`;
}

export function reportCountValue(row: CsvRow, key: "ocr_pages" | "ocr_images" | "input_tokens" | "output_tokens" | "total_tokens" | "embedding_tokens", labels: { unknown: string; notApplicable: string; partial: string }): CsvCell {
  const status = row[key === "ocr_pages" ? "page_count_status" : key === "ocr_images" ? "image_count_status" : "token_count_status"];
  if (status === "unknown") return labels.unknown;
  if (status === "not_applicable") return labels.notApplicable;
  if (status === "partial") return `${row[key] ?? ""} (${labels.partial})`;
  return row[key];
}

function escapeCsvCell(value: CsvCell) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll("\"", "\"\"")}"` : text;
}

const reportColumnHeaders: Record<ReportTopic, string[]> = {
  system_overview: ["metric_key", "metric_value", "date_from", "date_to"],
  project_ranking: ["rank", "project_name", "active_documents", "pipeline_runs", "qa_count", "validation_runs", "active_users_30d", "success_rate", "failure_rate"],
  project_reference_ranking: ["rank", "source_project", "reference_count", "target_project_count", "referenced_document_count", "new_references_30d", "pending_source_events", "quality_score"],
  document_reference_ranking: ["rank", "document_name", "source_project", "reference_count", "target_project_count", "active_version", "last_source_update", "pending_sync_count", "qa_hit_count", "human_correct_rate"],
  owner_project_summary: ["project_name", "active_documents", "pending_manager_review", "pending_owner_review", "approved_unpublished", "inbound_references", "outbound_references", "no_answer_rate", "validation_pass_rate", "open_alerts"],
  document_pipeline_metrics: ["project_name", "avg_pipeline_minutes", "p95_pipeline_minutes", "success_rate", "retry_count"],
  rag_quality_metrics: ["project_name", "qa_count", "no_answer_rate", "cited_answer_rate", "human_correct_rate"],
  validation_run_metrics: ["project_name", "validation_runs", "pass_rate", "failed_questions", "manual_review_count"],
  model_usage_metrics: ["model_type", "ai_model_name", "provider", "project_name", "usage_purpose", "source_channel", "call_count", "success_count", "failure_count", "input_tokens", "output_tokens", "total_tokens", "embedding_tokens", "token_count_status", "native_pdf_documents", "ocr_pages", "page_count_status", "ocr_images", "image_count_status", "vector_count", "chunk_count", "avg_latency_ms", "p95_latency_ms", "provider_reported_cost", "estimated_cost", "currency", "cost_source", "error_rate"],
  alert_metrics: ["level", "alert_type", "project_name", "count", "oldest_at"]
};


