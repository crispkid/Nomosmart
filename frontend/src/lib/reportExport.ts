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

export type CsvCell = string | number | boolean | null | undefined;
export type CsvRow = Record<string, CsvCell>;
export type ReportCsvLocale = "zh" | "en";
type LocalizedHeader = { zh: string; en: string };

export const reportTopics: Array<{ id: ReportTopic; label: string }> = [
  { id: "system_overview", label: "全系統總覽" },
  { id: "project_ranking", label: "專案活躍度排行榜" },
  { id: "project_reference_ranking", label: "專案被引用排行榜" },
  { id: "document_reference_ranking", label: "文件被引用排行榜" },
  { id: "owner_project_summary", label: "Owner 專案統計" },
  { id: "document_pipeline_metrics", label: "文件與 Pipeline" },
  { id: "rag_quality_metrics", label: "問答品質" },
  { id: "validation_run_metrics", label: "批次驗證" },
  { id: "model_usage_metrics", label: "模型使用" },
  { id: "alert_metrics", label: "告警統計" }
];

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

export function getLocalizedReportHeaders(headers: string[], locale: ReportCsvLocale, topic?: ReportTopic) {
  return headers.map((header) => reportColumnLabels[topic ?? "system_overview"]?.[header]?.[locale] ?? defaultColumnLabels[header]?.[locale] ?? header);
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

export function buildLocalizedReportCsv(rows: CsvRow[], topic: ReportTopic, locale: ReportCsvLocale) {
  const headers = getReportHeaders(rows, topic);
  return buildCsv(rows, headers, getLocalizedReportHeaders(headers, locale, topic));
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
  model_usage_metrics: ["model_type", "ai_model_name", "provider", "project_name", "usage_purpose", "source_channel", "call_count", "success_count", "failure_count", "input_tokens", "output_tokens", "total_tokens", "embedding_tokens", "ocr_pages", "ocr_images", "vector_count", "chunk_count", "avg_latency_ms", "p95_latency_ms", "provider_reported_cost", "estimated_cost", "currency", "cost_source", "error_rate"],
  alert_metrics: ["level", "alert_type", "project_name", "count", "oldest_at"]
};

const defaultColumnLabels: Record<string, LocalizedHeader> = {
  active_documents: { zh: "活躍文件", en: "Active documents" },
  active_users_30d: { zh: "30 天活躍使用者", en: "Active users 30d" },
  active_version: { zh: "目前版本", en: "Active version" },
  alert_type: { zh: "告警類型", en: "Alert type" },
  approved_unpublished: { zh: "已核准未發布", en: "Approved unpublished" },
  avg_latency_ms: { zh: "平均延遲毫秒", en: "Average latency ms" },
  avg_pipeline_minutes: { zh: "平均 Pipeline 分鐘", en: "Average pipeline minutes" },
  cited_answer_rate: { zh: "有引用答案率", en: "Cited answer rate" },
  count: { zh: "數量", en: "Count" },
  date_from: { zh: "起始日期", en: "Date from" },
  date_to: { zh: "結束日期", en: "Date to" },
  document_name: { zh: "文件名稱", en: "Document name" },
  error_rate: { zh: "錯誤率", en: "Error rate" },
  estimated_cost_usd: { zh: "估算成本 USD", en: "Estimated cost USD" },
  failed_questions: { zh: "失敗題數", en: "Failed questions" },
  failure_rate: { zh: "失敗率", en: "Failure rate" },
  human_correct_rate: { zh: "人工正確率", en: "Human correct rate" },
  inbound_references: { zh: "被引用數", en: "Inbound references" },
  last_source_update: { zh: "最近來源更新", en: "Last source update" },
  level: { zh: "等級", en: "Level" },
  manual_review_count: { zh: "待人工檢視", en: "Manual review count" },
  metric_key: { zh: "指標代碼", en: "Metric key" },
  metric_value: { zh: "指標值", en: "Metric value" },
  ai_model_name: { zh: "模型名稱", en: "Model Name" },
  new_references_30d: { zh: "30 天新增引用", en: "New references 30d" },
  no_answer_rate: { zh: "無答案率", en: "No answer rate" },
  oldest_at: { zh: "最早時間", en: "Oldest at" },
  open_alerts: { zh: "未處理告警", en: "Open alerts" },
  outbound_references: { zh: "引用外部數", en: "Outbound references" },
  p95_pipeline_minutes: { zh: "P95 Pipeline 分鐘", en: "P95 pipeline minutes" },
  pass_rate: { zh: "通過率", en: "Pass rate" },
  pending_manager_review: { zh: "待主管審核", en: "Pending manager review" },
  pending_owner_review: { zh: "待 Owner 審核", en: "Pending owner review" },
  pending_source_events: { zh: "待處理來源事件", en: "Pending source events" },
  pending_sync_count: { zh: "待同步數", en: "Pending sync count" },
  pipeline_runs: { zh: "Pipeline 次數", en: "Pipeline runs" },
  project_name: { zh: "專案名稱", en: "Project name" },
  provider: { zh: "Provider", en: "Provider" },
  qa_count: { zh: "問答次數", en: "Q&A count" },
  qa_hit_count: { zh: "問答命中數", en: "Q&A hit count" },
  quality_score: { zh: "品質分數", en: "Quality score" },
  rank: { zh: "排名", en: "Rank" },
  reference_count: { zh: "引用次數", en: "Reference count" },
  referenced_document_count: { zh: "被引用文件數", en: "Referenced document count" },
  retry_count: { zh: "重試次數", en: "Retry count" },
  source_project: { zh: "來源專案", en: "Source project" },
  success_rate: { zh: "成功率", en: "Success rate" },
  target_project_count: { zh: "目標專案數", en: "Target project count" },
  token_count: { zh: "Token 數", en: "Token count" },
  validation_pass_rate: { zh: "驗證通過率", en: "Validation pass rate" },
  validation_runs: { zh: "驗證批次數", en: "Validation runs" }
};

const reportColumnLabels: Record<ReportTopic, Record<string, LocalizedHeader>> = {
  system_overview: defaultColumnLabels,
  project_ranking: defaultColumnLabels,
  project_reference_ranking: defaultColumnLabels,
  document_reference_ranking: defaultColumnLabels,
  owner_project_summary: defaultColumnLabels,
  document_pipeline_metrics: defaultColumnLabels,
  rag_quality_metrics: defaultColumnLabels,
  validation_run_metrics: defaultColumnLabels,
  model_usage_metrics: defaultColumnLabels,
  alert_metrics: defaultColumnLabels
};
