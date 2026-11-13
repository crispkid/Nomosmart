"use client";

import { DropdownSelect } from "@/components/DropdownSelect";

import { FeedbackMessage, FeedbackSeverityBadge } from "@/components/FeedbackMessage";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, BarChart3, CalendarDays, Download, FileText, Gauge, GitBranch, LoaderCircle, LockKeyhole, Search, ShieldCheck, Sparkles } from "lucide-react";
import { AppShell, ForbiddenState, Panel } from "@/components/AppShell";
import { useAuth } from "@/components/AuthProvider";
import { downloadReportCsv, getReportFilterOptions, getReportSummary, type ReportFilterOptionsResponse, type ReportSummaryResponse } from "@/lib/api";
import { Pagination } from "@/components/Pagination";
import { useReadResource } from "@/lib/useReadResource";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { reportCountValue } from "@/lib/reportExport";
import { formatReportCell } from "@/lib/reportFormatting";
import { reportDisplayValue, reportProjectLabel, reportSourceChannels, reportUsagePurposes } from "@/lib/reportDisplay";
import { buildReportFilename, normalizeReportCsvLocale, type CsvRow, type ReportTopic } from "@/lib/reportExport";

type ReportTab = "overview" | "projects" | "references" | "documents" | "quality" | "models" | "alerts";
type ReportFilters = {
  dateFrom: string;
  dateTo: string;
  scope: string;
  project: string;
  modelType: string;
  usagePurpose: string;
  sourceChannel: string;
  usageStatus: string;
};

const REPORT_PAGE_SIZE = 20;

const reportTabs: Array<{ id: ReportTab; label: TranslationKey; icon: typeof Gauge }> = [
  { id: "overview", label: "reportTabOverview", icon: Gauge },
  { id: "projects", label: "reportTabProjects", icon: BarChart3 },
  { id: "references", label: "reportTabReferences", icon: GitBranch },
  { id: "documents", label: "reportTabDocuments", icon: FileText },
  { id: "quality", label: "reportTabQuality", icon: Sparkles },
  { id: "models", label: "reportTabModels", icon: ShieldCheck },
  { id: "alerts", label: "reportTabAlerts", icon: AlertTriangle }
];

const tabTopics: Record<ReportTab, ReportTopic[]> = {
  overview: ["system_overview"],
  projects: ["project_ranking", "owner_project_summary"],
  references: ["project_reference_ranking", "document_reference_ranking"],
  documents: ["document_pipeline_metrics"],
  quality: ["rag_quality_metrics", "validation_run_metrics"],
  models: ["model_usage_metrics"],
  alerts: ["alert_metrics"]
};

export default function ReportsPage() {
  const { format, localize, t } = useI18n();
  const { apiFetch, authReady, can, operationGuards } = useAuth();
  const canViewReports = can("Menu", "Reports", "view");
  const initialFilters = useMemo(() => defaultFilters(), []);
  const [activeTab, setActiveTab] = useState<ReportTab>("overview");
  const [draftFilters, setDraftFilters] = useState<ReportFilters>(initialFilters);
  const [appliedFilters, setAppliedFilters] = useState<ReportFilters>(initialFilters);
  const [appliedOptions, setAppliedOptions] = useState<{ options: ReportFilterOptionsResponse; identity: typeof operationGuards } | null>(null);
  const [responses, setResponses] = useState<Partial<Record<ReportTopic, ReportSummaryResponse>>>({});
  const [topicLoading, setTopicLoading] = useState<Partial<Record<ReportTopic, boolean>>>({});
  const [topicErrors, setTopicErrors] = useState<Partial<Record<ReportTopic, string>>>({});
  const [queryLoading, setQueryLoading] = useState(false);
  const [exportingTopics, setExportingTopics] = useState<Set<ReportTopic>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const queryGeneration = useRef(0);
  const queryBatch = useRef(0);
  const topicGeneration = useRef<Partial<Record<ReportTopic, number>>>({});
  const topicRequests = useRef<Partial<Record<ReportTopic, AbortController>>>({});
  const initialized = useRef(false);
  const messages = useRef({ t, format });
  useEffect(() => { messages.current = { t, format }; }, [t, format]);
  const filtersDirty = !sameFilters(draftFilters, appliedFilters);
  const hasReportData = Object.keys(responses).length > 0;

  const reportParams = useCallback((topic: ReportTopic, filters: ReportFilters, page = 1) => ({
    topic,
    dateFrom: filters.dateFrom,
    dateTo: filters.dateTo,
    scope: filters.scope,
    projectId: isUuid(filters.project) ? filters.project : null,
    page,
    pageSize: REPORT_PAGE_SIZE,
    modelType: filters.modelType,
    usagePurpose: filters.usagePurpose,
    sourceChannel: filters.sourceChannel,
    usageStatus: filters.usageStatus
  }), []);

  // OPT424-035: filter options are a read resource for the selected scope and session identity.
  const optionsScope = draftFilters.scope;
  const readOptions = useCallback((signal: AbortSignal) => getReportFilterOptions(apiFetch, optionsScope, signal), [apiFetch, optionsScope]);
  const optionsRead = useReadResource<ReportFilterOptionsResponse>(readOptions, operationGuards, authReady && canViewReports, {
    onStart: () => setError(null),
    onError: (reason) => setError(operationalErrorMessage(reason, messages.current.t, messages.current.format)),
  });
  const filterOptions = optionsRead.data;
  const optionsBinding = filterOptions ? { options: filterOptions, identity: operationGuards } : null;

  // Each topic request is aborted when a newer request for the topic or a new applied query starts.
  const beginTopicRequest = useCallback((topic: ReportTopic) => {
    topicRequests.current[topic]?.abort();
    const controller = new AbortController();
    topicRequests.current[topic] = controller;
    return controller.signal;
  }, []);
  const abortTopicRequests = useCallback(() => {
    for (const controller of Object.values(topicRequests.current)) controller?.abort();
  }, []);

  const queryTab = useCallback(async (tab: ReportTab, filters: ReportFilters, replace: boolean) => {
    // A new applied condition invalidates every old page, including its finally.
    if (replace) {
      abortTopicRequests();
      queryGeneration.current += 1;
      setResponses({});
      setTopicErrors({});
      setTopicLoading({});
    }
    const generation = queryGeneration.current;
    const batch = ++queryBatch.current;
    const topics = tabTopics[tab];
    setQueryLoading(true);
    setError(null);
    await Promise.allSettled(topics.map(async (topic) => {
      const request = (topicGeneration.current[topic] ?? 0) + 1;
      topicGeneration.current[topic] = request;
      const current = () => generation === queryGeneration.current && request === topicGeneration.current[topic];
      setTopicErrors((value) => ({ ...value, [topic]: undefined }));
      setTopicLoading((value) => ({ ...value, [topic]: true }));
      try {
        const result = await getReportSummary(apiFetch, reportParams(topic, filters), beginTopicRequest(topic));
        if (current()) setResponses((value) => ({ ...value, [topic]: result }));
      } catch (reason) {
        if (!current()) return;
        setResponses((value) => { const next = { ...value }; delete next[topic]; return next; });
        setTopicErrors((value) => ({ ...value, [topic]: operationalErrorMessage(reason, messages.current.t, messages.current.format) }));
      } finally {
        if (current()) setTopicLoading((value) => ({ ...value, [topic]: false }));
      }
    }));
    if (generation === queryGeneration.current && batch === queryBatch.current) setQueryLoading(false);
  }, [abortTopicRequests, apiFetch, beginTopicRequest, reportParams]);

  useEffect(() => {
    if (!authReady || !canViewReports || initialized.current) return;
    initialized.current = true;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setDraftFilters(initialFilters);
      setAppliedFilters(initialFilters);
      setActiveTab("overview");
      void queryTab("overview", initialFilters, true);
    });
    return () => {
      cancelled = true;
      initialized.current = false;
      queryGeneration.current += 1;
      queryBatch.current += 1;
      abortTopicRequests();
    };
  }, [abortTopicRequests, authReady, canViewReports, initialFilters, operationGuards, queryTab]);

  function changeScope(scope: string) {
    setDraftFilters((current) => ({ ...current, scope, project: "all" }));
  }

  async function applyQuery() {
    if (queryLoading) return;
    if (!draftFilters.dateFrom || !draftFilters.dateTo || draftFilters.dateFrom > draftFilters.dateTo) {
      setError(t("reportInvalidDateRange"));
      return;
    }
    setAppliedOptions(filterOptions?.selected_scope === draftFilters.scope ? optionsBinding : null);
    setAppliedFilters(draftFilters);
    await queryTab(activeTab, draftFilters, true);
  }

  async function changeTab(tab: ReportTab) {
    setActiveTab(tab);
    const missingTopic = tabTopics[tab].some((topic) => !responses[topic]);
    if (missingTopic) await queryTab(tab, appliedFilters, false);
  }

  async function changePage(topic: ReportTopic, page: number) {
    const generation = queryGeneration.current;
    const request = (topicGeneration.current[topic] ?? 0) + 1;
    topicGeneration.current[topic] = request;
    const current = () => generation === queryGeneration.current && request === topicGeneration.current[topic];
    setTopicLoading((value) => ({ ...value, [topic]: true }));
    setTopicErrors((value) => ({ ...value, [topic]: undefined }));
    try {
      const result = await getReportSummary(apiFetch, reportParams(topic, appliedFilters, page), beginTopicRequest(topic));
      if (current()) setResponses((value) => ({ ...value, [topic]: result }));
    } catch (reason) {
      if (current()) setTopicErrors((value) => ({ ...value, [topic]: operationalErrorMessage(reason, t, format) }));
    } finally {
      if (current()) setTopicLoading((value) => ({ ...value, [topic]: false }));
    }
  }

  async function downloadTopic(topic: ReportTopic) {
    const generation = queryGeneration.current;
    const filters = appliedFilters;
    const locale = normalizeReportCsvLocale(document.documentElement.lang);
    setExportingTopics((current) => new Set(current).add(topic));
    setTopicErrors((current) => ({ ...current, [topic]: undefined }));
    const blob = await downloadReportCsv(apiFetch, { ...reportParams(topic, filters), locale, page: undefined, pageSize: undefined })
      .catch((reason: Error) => {
        if (generation === queryGeneration.current) setTopicErrors((current) => ({ ...current, [topic]: operationalErrorMessage(reason, t, format) }));
        return null;
      });
    setExportingTopics((current) => {
      const next = new Set(current);
      next.delete(topic);
      return next;
    });
    if (!blob || generation !== queryGeneration.current) return;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = buildReportFilename(topic, filters.dateFrom, filters.dateTo);
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  if (!canViewReports) {
    return <AppShell title={t("reports")}><ForbiddenState /></AppShell>;
  }

  const tableProps = (topic: ReportTopic) => ({
    response: responses[topic],
    loading: Boolean(topicLoading[topic]),
    error: topicErrors[topic],
    exporting: exportingTopics.has(topic),
    onPage: (page: number) => { void changePage(topic, page); },
    onExport: () => { void downloadTopic(topic); }
  });

  return (
    <AppShell title={t("reports")}>
      <section className="fixture-banner report-fixture-banner"><LockKeyhole size={17} /><div><strong>{hasReportData ? t("reportLiveData") : t("reportLiveLoading")}</strong><span>{hasReportData ? t("reportLiveDataHelp") : t("reportLiveLoadingHelp")}</span></div></section>
      {error ? <FeedbackMessage title={t("reportLoadFailed")}>{localize(error)}</FeedbackMessage> : null}

      <section className="report-filter-bar" aria-label={t("reportFilterLabel")}>
        <label><CalendarDays size={16} /><span>{t("reportDateFrom")}</span><input onChange={(event) => setDraftFilters((current) => ({ ...current, dateFrom: event.target.value }))} type="date" value={draftFilters.dateFrom} /></label>
        <label><CalendarDays size={16} /><span>{t("reportDateTo")}</span><input onChange={(event) => setDraftFilters((current) => ({ ...current, dateTo: event.target.value }))} type="date" value={draftFilters.dateTo} /></label>
        <label><span>{t("reportScope")}</span><DropdownSelect onChange={(event) => { changeScope(event.target.value); }} value={draftFilters.scope}>{(filterOptions?.scopes ?? [{ value: draftFilters.scope, project_count: 0 }]).map((option) => <option key={option.value} value={option.value}>{scopeLabel(option.value, t)} ({option.project_count})</option>)}</DropdownSelect></label>
        <label><span>{t("reportProject")}</span><DropdownSelect onChange={(event) => setDraftFilters((current) => ({ ...current, project: event.target.value }))} value={draftFilters.project}><option value="all">{t("reportAllAuthorizedProjects")}</option>{(filterOptions?.projects ?? []).map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}</DropdownSelect></label>
        <button className="action-button report-query-button" disabled={queryLoading} onClick={() => { void applyQuery(); }} type="button"><Search size={16} />{queryLoading ? t("reportQueryLoading") : t("reportQuery")}</button>
      </section>

      <div className={`report-query-state${filtersDirty ? " dirty" : ""}`} aria-live="polite">
        <span>{filtersDirty ? t("reportFiltersPending") : t("reportFiltersApplied")}</span>
        <small>{t("reportAppliedRange")}：{appliedFilters.dateFrom} – {appliedFilters.dateTo}</small>
      </div>

      <nav className="report-topic-tabs" aria-label={t("reportTopicTabs") }>
        {reportTabs.map((tab) => {
          const Icon = tab.icon;
          return <button className={activeTab === tab.id ? "active" : ""} key={tab.id} onClick={() => { void changeTab(tab.id); }} type="button"><Icon size={16} />{t(tab.label)}</button>;
        })}
      </nav>

      {queryLoading ? <div className="report-query-loading" role="status"><LoaderCircle className="spin" size={22} /><div><strong>{t("reportQueryLoading")}</strong><span>{t("reportQueryLoadingHelp")}</span></div></div> : null}

      {activeTab === "models" ? <ModelFilterBar filters={draftFilters} loading={queryLoading} onChange={setDraftFilters} onQuery={applyQuery} /> : null}

      <section className="report-results" aria-busy={queryLoading}>
        {activeTab === "overview" ? <OverviewPanel scope={appliedFilters.scope} project={appliedFilters.project} options={appliedOptions?.identity === operationGuards && appliedOptions.options.selected_scope === appliedFilters.scope ? appliedOptions.options : null} table={tableProps("system_overview")} /> : null}
        {activeTab === "projects" ? <ProjectRankingPanel ranking={tableProps("project_ranking")} owner={tableProps("owner_project_summary")} /> : null}
        {activeTab === "references" ? <ReferencePanel projects={tableProps("project_reference_ranking")} documents={tableProps("document_reference_ranking")} /> : null}
        {activeTab === "documents" ? <DocumentPanel table={tableProps("document_pipeline_metrics")} /> : null}
        {activeTab === "quality" ? <QualityPanel rag={tableProps("rag_quality_metrics")} validation={tableProps("validation_run_metrics")} /> : null}
        {activeTab === "models" ? <ModelPanel table={tableProps("model_usage_metrics")} /> : null}
        {activeTab === "alerts" ? <AlertPanel table={tableProps("alert_metrics")} /> : null}
      </section>
    </AppShell>
  );
}

type TableState = {
  response?: ReportSummaryResponse;
  loading: boolean;
  error?: string;
  exporting: boolean;
  onPage: (page: number) => void;
  onExport: () => void;
};

function OverviewPanel({ table, scope, project, options }: { table: TableState; scope: string; project: string; options: ReportFilterOptionsResponse | null }) {
  const { t } = useI18n();
  return <div className="content-grid two"><ReportPanel title={t("reportOperationsTrend")} badge={`${scopeLabel(scope, t)} · ${reportProjectLabel(project, table.error ? null : options, t)}`} table={table} columns={[["metric_key", t("reportColMetric")], ["metric_value", t("reportColValue")], ["date_from", t("reportColDateFrom")], ["date_to", t("reportColDateTo")]]} /><Panel title={t("reportVisibleScope")}><div className="report-scope-list"><article><strong>{t("reportRoleSystemAdmin")}</strong><span>{t("reportRoleSystemAdminHelp")}</span></article><article><strong>{t("reportRoleProjectOwner")}</strong><span>{t("reportRoleProjectOwnerHelp")}</span></article><article><strong>{t("reportRoleEditorViewer")}</strong><span>{t("reportRoleEditorViewerHelp")}</span></article><article><strong>{t("reportRoleReviewer")}</strong><span>{t("reportRoleReviewerHelp")}</span></article></div></Panel></div>;
}

function ProjectRankingPanel({ ranking, owner }: { ranking: TableState; owner: TableState }) {
  const { t } = useI18n();
  return <div className="content-grid"><ReportPanel title={t("reportProjectRanking")} table={ranking} columns={[["rank", t("reportColRank")], ["project_name", t("reportColProject")], ["active_documents", t("reportColActiveDocuments")], ["pipeline_runs", t("reportColPipelineRuns")], ["qa_count", t("reportColQa")], ["validation_runs", t("reportColValidation")], ["active_users_30d", t("reportColActiveUsers30d")], ["success_rate", t("reportColSuccessRate")]]} /><ReportPanel title={t("reportOwnerSummary")} table={owner} columns={[["project_name", t("reportColProject")], ["active_documents", t("reportColActiveDocuments")], ["pending_manager_review", t("reportColPendingManager")], ["pending_owner_review", t("reportColPendingOwner")], ["approved_unpublished", t("reportColApprovedUnpublished")], ["inbound_references", t("reportColReferenced")], ["outbound_references", t("reportColOutboundReferences")], ["open_alerts", t("reportColAlerts")]]} /></div>;
}

function ReferencePanel({ projects, documents }: { projects: TableState; documents: TableState }) {
  const { t } = useI18n();
  return <div className="content-grid"><ReportPanel title={t("reportProjectReferenceRanking")} table={projects} columns={[["rank", t("reportColRank")], ["source_project", t("reportColSourceProject")], ["reference_count", t("reportColReferenced")], ["target_project_count", t("reportColReferencingProjects")], ["referenced_document_count", t("reportColDocuments")], ["new_references_30d", t("reportColNew30d")], ["pending_source_events", t("reportColPending")], ["quality_score", t("reportColQualityScore")]]} /><ReportPanel title={t("reportDocumentReferenceRanking")} table={documents} columns={[["rank", t("reportColRank")], ["document_name", t("reportColSourceDocument")], ["source_project", t("reportColSourceProject")], ["reference_count", t("reportColReferenced")], ["target_project_count", t("reportColReferencingProjects")], ["active_version", t("reportColActiveVersion")], ["pending_sync_count", t("reportColPendingSync")], ["human_correct_rate", t("reportColCorrectRate")]]} /></div>;
}

function DocumentPanel({ table }: { table: TableState }) {
  const { t } = useI18n();
  return <div className="content-grid"><ReportPanel title={t("reportDocumentPipelineMetrics")} table={table} columns={[["project_name", t("reportColProject")], ["pipeline_runs", t("reportColPipelineRuns")], ["completed_runs", t("reportColCompleted")], ["failed_runs", t("reportColFailed")], ["retry_count", t("reportColRetry")], ["avg_pipeline_seconds", t("reportColAverageSeconds")], ["p95_pipeline_seconds", t("reportColP95Seconds")]]} /></div>;
}

function QualityPanel({ rag, validation }: { rag: TableState; validation: TableState }) {
  const { t } = useI18n();
  return <div className="content-grid two"><ReportPanel title={t("reportRagQuality")} table={rag} columns={[["project_name", t("reportColProject")], ["qa_count", t("reportColQaCount")], ["no_answer_rate", t("reportColNoAnswerRate")], ["cited_answer_rate", t("reportColCitedAnswerRate")], ["human_correct_rate", t("reportColHumanCorrectRate")]]} /><ReportPanel title={t("reportCsvBatchValidation")} table={validation} columns={[["project_name", t("reportColProject")], ["validation_runs", t("reportColBatchCount")], ["pass_rate", t("reportColPassRate")], ["failed_questions", t("reportColFailedQuestions")], ["manual_review_count", t("reportColManualReview")]]} /></div>;
}

function ModelPanel({ table }: { table: TableState }) {
  const { t } = useI18n();
  return <ReportPanel title={t("reportModelUsageCost")} table={table} columns={[["model_type", t("reportModelType")], ["ai_model_name", t("reportColModel")], ["provider", t("reportColProvider")], ["project_name", t("reportColProject")], ["usage_purpose", t("reportUsagePurpose")], ["call_count", t("reportColCalls")], ["success_count", t("reportColSuccess")], ["failure_count", t("reportColFailures")], ["native_pdf_documents", t("reportColNativePdfDocuments")], ["ocr_pages", t("reportColOcrPages")], ["ocr_images", t("reportColOcrImages")], ["input_tokens", t("reportColInputTokens")], ["output_tokens", t("reportColOutputTokens")], ["total_tokens", t("reportColTotalTokens")], ["estimated_cost", t("reportColEstimatedCost")], ["currency", t("reportColCurrency")], ["avg_latency_ms", t("reportColAverageLatencyMs")], ["error_rate", t("reportColErrorRate")]]} />;
}

function AlertPanel({ table }: { table: TableState }) {
  const { t } = useI18n();
  return <ReportPanel title={t("reportAlertsPanel")} table={table} columns={[["level", t("reportColLevel")], ["alert_type", t("reportColType")], ["project_name", t("reportColProject")], ["count", t("reportColCount")], ["oldest_at", t("reportColOldestAt")]]} />;
}

function ReportPanel({ title, table, columns, badge }: { title: string; table: TableState; columns: Array<[string, string]>; badge?: string }) {
  const { localize, t } = useI18n();
  const response = table.response;
  return <Panel title={title} action={<div className="report-panel-actions">{badge ? <span className="report-scope-pill">{badge}</span> : null}<button aria-busy={table.exporting} className="action-button secondary report-export-button" disabled={table.exporting || table.loading} onClick={table.onExport} type="button">{table.exporting ? <LoaderCircle aria-hidden="true" className="spin" size={16} /> : <Download aria-hidden="true" size={16} />}<span>{table.exporting ? t("reportDownloading") : t("reportDownloadCsv")}</span></button></div>}>
    {table.error ? <FeedbackMessage tone="error">{t("reportTableLoadFailed")}：{localize(table.error)}</FeedbackMessage> : null}
    {table.loading ? <div className="report-table-loading" role="status"><LoaderCircle className="spin" size={20} /><span>{t("reportTableLoading")}</span></div> : null}
    {!table.loading && response?.rows.length ? <ReportTable rows={response.rows as CsvRow[]} columns={columns} /> : null}
    {!table.loading && !response?.rows.length && !table.error ? <ReportEmptyState /> : null}
    {response ? <ReportPagination response={response} loading={table.loading} onPage={table.onPage} /> : null}
  </Panel>;
}

function ReportPagination({ response, loading, onPage }: { response: ReportSummaryResponse; loading: boolean; onPage: (page: number) => void }) {
  const { t } = useI18n();
  if (response.total_rows === 0) return null;
  return <Pagination canNext={!loading && response.page < response.total_pages} canPrevious={!loading && response.page > 1} className="report-pagination" nextLabel={t("reportNextPage")} onNext={() => onPage(response.page + 1)} onPrevious={() => onPage(response.page - 1)} previousLabel={t("reportPreviousPage")} summary={<>{t("reportPage")} {response.page} / {response.total_pages} · {t("reportRowsTotal")} {response.total_rows}</>} />;
}

function ModelFilterBar({ filters, loading, onChange, onQuery }: { filters: ReportFilters; loading: boolean; onChange: (filters: ReportFilters) => void; onQuery: () => Promise<void> }) {
  const { t } = useI18n();
  const update = (key: keyof ReportFilters, value: string) => onChange({ ...filters, [key]: value });
  return (
    <section className="report-filter-bar report-model-filter-bar" aria-label={t("reportModelFilterLabel")}>
      <label><span>{t("reportModelType")}</span><DropdownSelect onChange={(event) => update("modelType", event.target.value)} value={filters.modelType}><option value="">{t("reportFilterAll")}</option><option value="Chat">{t("labelChat")}</option><option>Embedding</option><option value="OCR">{t("labelPdfRecognition")}</option><option>Judge</option></DropdownSelect></label>
      <label><span>{t("reportUsagePurpose")}</span><DropdownSelect onChange={(event) => update("usagePurpose", event.target.value)} value={filters.usagePurpose}><option value="">{t("reportFilterAll")}</option>{reportUsagePurposes.map((value) => <option key={value} value={value}>{reportDisplayValue("usage_purpose", value, t)?.label}</option>)}</DropdownSelect></label>
      <label><span>{t("reportSourceChannel")}</span><DropdownSelect onChange={(event) => update("sourceChannel", event.target.value)} value={filters.sourceChannel}><option value="">{t("reportFilterAll")}</option>{reportSourceChannels.map((value) => <option key={value} value={value}>{reportDisplayValue("source_channel", value, t)?.label}</option>)}</DropdownSelect></label>
      <label><span>{t("reportUsageStatus")}</span><DropdownSelect onChange={(event) => update("usageStatus", event.target.value)} value={filters.usageStatus}><option value="">{t("reportFilterAll")}</option><option value="success">{t("reportUsageSuccess")}</option><option value="failed">{t("reportUsageFailed")}</option><option value="partial">{t("reportUsagePartial")}</option><option value="cancelled">{t("reportUsageCancelled")}</option></DropdownSelect></label>
      <button className="action-button report-query-button" disabled={loading} onClick={() => { void onQuery(); }} type="button"><Search size={16} />{loading ? t("reportQueryLoading") : t("reportQuery")}</button>
    </section>
  );
}

function ReportEmptyState() {
  const { t } = useI18n();
  return <div className="empty-state"><strong>{t("reportEmptyState")}</strong><span>{t("reportEmptyStateHelp")}</span></div>;
}

function ReportTable({ rows, columns }: { rows: CsvRow[]; columns: Array<[string, string]> }) {
  const { locale, t } = useI18n();
  return <div className="system-table-wrap report-table-wrap"><table className="system-table"><thead><tr>{columns.map(([key, label]) => <th className={reportIdentityClass(key)} key={key}>{label}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map(([key]) => <td className={reportIdentityClass(key)} key={key}>{(key === "ocr_pages" || key === "ocr_images" || key === "input_tokens" || key === "output_tokens" || key === "total_tokens" || key === "embedding_tokens") ? reportCountValue(row, key, { unknown: t("reportCountUnknown"), notApplicable: t("reportCountNotApplicable"), partial: t("reportCountPartial") }) : key === "level" ? <FeedbackSeverityBadge severity={String(row[key] ?? "info")} /> : (() => { const display = reportDisplayValue(key, row[key], t); return display ? <span className="report-coded-value"><span>{display.label}</span>{display.code ? <small>{display.code}</small> : null}</span> : formatReportCell(key, row[key], locale, t("reportCostNotProvided")); })()}</td>)}</tr>)}</tbody></table></div>;
}

function reportIdentityClass(key: string) {
  if (key === "model_type") return "report-sticky-identity report-sticky-model-type";
  if (key === "ai_model_name") return "report-sticky-identity report-sticky-model-name";
  return undefined;
}

function defaultFilters(): ReportFilters {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 29);
  const format = (date: Date) => [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")
  ].join("-");
  return { dateFrom: format(start), dateTo: format(end), scope: "owner_projects", project: "all", modelType: "", usagePurpose: "", sourceChannel: "", usageStatus: "" };
}

function sameFilters(left: ReportFilters, right: ReportFilters) {
  return Object.keys(left).every((key) => left[key as keyof ReportFilters] === right[key as keyof ReportFilters]);
}

function scopeLabel(scope: string, t: (key: TranslationKey) => string) {
  const value = reportDisplayValue("scope", scope, t);
  return value?.code ? `${value.label} (${value.code})` : value?.label ?? t("reportUnknownScope");
}

function isUuid(value: string) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}
