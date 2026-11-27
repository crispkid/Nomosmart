"use client";

import { ApprovalFilters } from "@/components/ApprovalFilters";
import { approvalListFilters, emptyApprovalFilters, type ApprovalFilterValues } from "@/lib/approvalFilters";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import Link from "next/link";
import { ReadResourceStatus } from "@/components/ReadResourceStatus";
import { useReadResource } from "@/lib/useReadResource";
import { useCursorList } from "@/lib/useCursorList";
import { usePendingPublishList } from "@/lib/usePendingPublishList";
import { useCallback, useId, useMemo, useRef, useState, useSyncExternalStore, type MouseEvent } from "react";
import { tabIndexForKey } from "@/lib/workspaceNavigation";
import { ArrowRight, CheckCircle2, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { AppShell, StatCard, StatusToneBadge, ToneBadge } from "@/components/AppShell";
import { ApprovalPreview } from "@/components/approval/ApprovalPreview";
import { getApprovalSummary, listApprovalHistoryPage, listMyApprovalSubmissionsPage, listPendingApprovalsPage, listPendingPublishApprovalsPage, listRejectedApprovalsPage, publishDocumentVersion, type ApprovalPendingPublishResponse, type ApprovalTaskResponse } from "@/lib/api";
import { formatShortDateTime } from "@/lib/dateFormat";
import { t as translate, type Locale } from "@/lib/i18n";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { formatPersonName } from "@/lib/personName";
import { projectColorClass } from "@/lib/projectColor";

type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;
type WorkbenchTab = "pending" | "publish" | "mine" | "rejected" | "history";

function stageLabel(stage: string, t: Translate) {
  return stage === "owner_review" ? t("approvalStageOwnerReview") : t("approvalStageManagerReview");
}

function shortId(value: string) {
  return value.slice(0, 8);
}

type SubmitterDisplay = {
  submitter_given_name: string | null;
  submitter_family_name: string | null;
  submitter_name: string | null;
  submitter_email: string | null;
  submitter_id: string | null;
};

function displaySubmitterName(item: SubmitterDisplay, locale: Locale) {
  return formatPersonName({
    given_name: item.submitter_given_name,
    family_name: item.submitter_family_name,
    display_name: item.submitter_name
  }, locale) || item.submitter_email || (item.submitter_id ? shortId(item.submitter_id) : "-");
}

function displaySubmitterDetail(item: SubmitterDisplay, t: Translate) {
  if (item.submitter_name && item.submitter_email) return item.submitter_email;
  if (!item.submitter_id) return t("approvalSubmitterUnknown");
  return `${t("approvalSubmitter")} ${shortId(item.submitter_id)}`;
}

/** CHG-495: average wait in minutes, hours or days (one decimal); null when nothing was completed. */
function formatWait(seconds: number | null | undefined, format: Format) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 3600) return format("approvalDurationMinutes", { value: Math.max(1, Math.round(seconds / 60)) });
  if (seconds < 86400) return format("approvalDurationHours", { value: Math.round(seconds / 360) / 10 });
  return format("approvalDurationDays", { value: Math.round(seconds / 8640) / 10 });
}

// CHG-495 M21: list and summary side by side above 1280px; narrower screens open the detail page.
const wideQuery = "(min-width: 1281px)";
function subscribeWide(listener: () => void) {
  const query = window.matchMedia(wideQuery);
  query.addEventListener("change", listener);
  return () => query.removeEventListener("change", listener);
}
function useWideLayout() {
  return useSyncExternalStore(subscribeWide, () => window.matchMedia(wideQuery).matches, () => false);
}

export default function ApprovalPage() {
  const tabGroupId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const { apiFetch, authReady, operationGuards, currentUser } = useAuth();
  const { locale, format } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const wide = useWideLayout();
  const [filterState, setFilterState] = useState({ scope: operationGuards, values: emptyApprovalFilters });
  const filters = filterState.scope === operationGuards ? filterState.values : emptyApprovalFilters;
  const queries = useMemo(() => ({ pending: approvalListFilters(filters, "pending"), mine: approvalListFilters(filters, "mine"), history: approvalListFilters(filters, "history"), rejected: approvalListFilters(filters, "rejected") }), [filters]);
  const applyFilters = (values: ApprovalFilterValues) => setFilterState({ scope: operationGuards, values });
  const readSummary = useCallback(() => getApprovalSummary(apiFetch), [apiFetch]);
  const readPending = useCallback((cursor?: string | null, signal?: AbortSignal) => listPendingApprovalsPage(apiFetch, cursor, queries.pending, signal), [apiFetch, queries.pending]);
  const readMine = useCallback((cursor?: string | null, signal?: AbortSignal) => listMyApprovalSubmissionsPage(apiFetch, cursor, queries.mine, signal), [apiFetch, queries.mine]);
  const readHistory = useCallback((cursor?: string | null, signal?: AbortSignal) => listApprovalHistoryPage(apiFetch, cursor, queries.history, signal), [apiFetch, queries.history]);
  const readRejected = useCallback((cursor?: string | null, signal?: AbortSignal) => listRejectedApprovalsPage(apiFetch, cursor, queries.rejected, signal), [apiFetch, queries.rejected]);
  const readPublish = useCallback((cursor?: string | null, signal?: AbortSignal) => listPendingPublishApprovalsPage(apiFetch, cursor, signal), [apiFetch]);
  const summaryRead = useReadResource(readSummary, operationGuards, authReady);
  const publishRead = usePendingPublishList(readPublish, operationGuards, authReady);
  const pendingRead = useCursorList(readPending, operationGuards, authReady);
  const mineRead = useCursorList(readMine, operationGuards, authReady);
  const historyRead = useCursorList(readHistory, operationGuards, authReady);
  const rejectedRead = useCursorList(readRejected, operationGuards, authReady);
  const summary = summaryRead.data;
  const pending = pendingRead.items;
  const submissions = mineRead.items;
  const history = historyRead.items;
  const rejected = rejectedRead.items;
  const pendingPublish = publishRead.items;
  // CHG-495 M20: pending-for-me first; ready-to-publish is its own tab (same list and publish action as before).
  const [activeTab, setActiveTab] = useState<WorkbenchTab>("pending");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [publishing, setPublishing] = useState<{ scope: typeof operationGuards; versionId: string } | null>(null);
  const inFlightPublish = useRef<typeof publishing>(null);
  const publishingVersionId = publishing?.scope === operationGuards ? publishing.versionId : null;
  const [publication, setPublication] = useState<{ scope: typeof operationGuards; generation?: number; error?: unknown } | null>(null);
  const currentPublication = publication?.scope === operationGuards ? publication : null;
  const listTab = activeTab === "publish" ? null : activeTab;
  const activeRead = activeTab === "mine" ? mineRead : activeTab === "history" ? historyRead : activeTab === "rejected" ? rejectedRead : pendingRead;
  const taskItems: ApprovalTaskResponse[] = activeTab === "history" ? history : activeTab === "rejected" ? rejected : activeTab === "pending" ? pending : [];
  const previewTaskId = wide && taskItems.length ? (taskItems.some(item => item.id === selectedTaskId) ? selectedTaskId : taskItems[0].id) : null;
  const loadedLabel = (ready: boolean, count: number) => ready ? format("uiLoadedCount", { count }) : "—";
  const summaryValue = (value?: number) => summaryRead.status === "ready" ? String(value ?? 0) : summaryRead.status === "loading" ? "…" : "—";
  const summaryHelper = summaryRead.status === "ready" ? format("approvalPendingHelper", { manager: summary?.pending_manager_review ?? 0, owner: summary?.pending_owner_review ?? 0 }) : t(summaryRead.status === "loading" ? "uiReadLoading" : "uiReadUnavailable");
  const overdue = summaryRead.status === "ready" ? summary?.pending_overdue ?? 0 : 0;
  const listCount = (ready: boolean, hasMore: boolean, count: number) => ready && !hasMore ? count : null;
  const tabs: Array<{ id: WorkbenchTab; key: TranslationKey; count: number | null }> = [
    { id: "pending", key: "approvalPendingMine", count: summaryRead.status === "ready" ? summary?.pending_total ?? 0 : listCount(pendingRead.ready, pendingRead.hasMore, pending.length) },
    { id: "publish", key: "approvalTabPendingPublish", count: publishRead.ready ? publishRead.total : null },
    { id: "mine", key: "approvalMySubmissions", count: summaryRead.status === "ready" ? summary?.my_submissions ?? 0 : null },
    { id: "rejected", key: "approvalTabRejected", count: listCount(rejectedRead.ready, rejectedRead.hasMore, rejected.length) },
    { id: "history", key: "approvalTabHistory", count: listCount(historyRead.ready, historyRead.hasMore, history.length) }
  ];

  function selectTask(event: MouseEvent<HTMLAnchorElement>, taskId: string) {
    // Wide screens show the summary beside the list; modified clicks and narrow screens follow the link.
    if (!wide || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    setSelectedTaskId(taskId);
  }

  async function publishApprovedVersion(item: ApprovalPendingPublishResponse) {
    if (!publishRead.isCurrent() || inFlightPublish.current?.scope === operationGuards) return;
    const operation = { scope: operationGuards, versionId: item.document_version_id };
    inFlightPublish.current = operation;
    setPublishing(operation);
    setPublication(null);
    try {
      const result = await publishDocumentVersion(apiFetch, item.document_version_id, { lock_version: item.lock_version, impact_confirmed: true });
      if (!publishRead.isCurrent()) return;
      setPublication({ scope: operationGuards, generation: result.publication_generation });
      await publishRead.afterPublish(item.document_version_id);
    } catch (err) {
      if (publishRead.isCurrent()) setPublication({ scope: operationGuards, error: err });
    } finally {
      if (inFlightPublish.current === operation) inFlightPublish.current = null;
      if (publishRead.isCurrent()) setPublishing(null);
    }
  }

  const projectLine = (projectId: string, projectName: string | null) => <><span aria-hidden="true" className={`project-color-dot ${projectColorClass(projectId)}`} />{projectName ?? `${t("approvalProjectLabel")} ${shortId(projectId)}`}</>;
  const listTitle = activeTab === "pending" ? t("approvalPendingList") : activeTab === "mine" ? t("approvalMySubmissionsPanel") : activeTab === "history" ? t("approvalTabHistory") : t("approvalTabRejected");

  return (
    <AppShell title={t("approval")}>
      <div className="approval-workbench">
        <div className="approval-kpis">
          <StatCard label={t("approvalPendingMine")} value={summaryValue(summary?.pending_total)} helper={summaryHelper} note={overdue > 0 ? format("homePendingOverdue", { count: overdue, hours: summary?.pending_overdue_hours ?? 48 }) : undefined} tone={summary?.pending_total ? "coral" : "sage"} />
          <StatCard label={t("approvalMySubmissions")} value={summaryValue(summary?.my_submissions)} helper={t("approvalMySubmissionsHelp")} tone="neutral" />
          <StatCard label={t("approvalPublishControl")} value={publishRead.loading ? "…" : publishRead.total !== null ? String(publishRead.total) : "—"} helper={t(publishRead.stale ? "approvalPendingPublishStale" : "approvalPublishControlHelp")} tone="gold" />
          <StatCard label={t("approvalCompletedRecent")} value={summaryValue(summary?.completed_last_7_days)} helper={t("approvalCompletedRecentHelper")} tone="green" />
          <StatCard label={t("approvalAverageWait")} value={summaryRead.status === "ready" ? formatWait(summary?.average_wait_seconds, format) : summaryValue()} helper={summaryRead.status === "ready" && summary?.average_wait_seconds == null ? t("approvalAverageWaitNone") : t("approvalAverageWaitHelper")} tone="violet" />
        </div>
        <p className="form-helper approval-summary-scope">{t("approvalFilterSummaryScope")}</p>

        <ReadResourceStatus label={t("approval")} loading={summaryRead.status === "loading"} error={summaryRead.error} onRetry={summaryRead.reload} />
        {activeTab !== "publish" ? <ReadResourceStatus label={t("approvalPublishControl")} loading={false} error={publishRead.error} onRetry={publishRead.retry} /> : null}
        {currentPublication?.error ? <FeedbackMessage title={t("approvalPublishFailed")}>{operationalErrorMessage(currentPublication.error, t, format, "approvalPublishFailed")}</FeedbackMessage> : null}
        {currentPublication?.generation !== undefined ? <section className="approval-result approve" role="status"><CheckCircle2 size={17} /> {format("approvalPublishedGeneration", { generation: currentPublication.generation })}</section> : null}

        <div aria-label={t("approvalTabsLabel")} className="ws-tabs approval-tabs" role="tablist">
          {tabs.map((tab, index) => <button aria-controls={`${tabGroupId}-panel`} aria-selected={activeTab === tab.id} className="ws-tab" id={`${tabGroupId}-${tab.id}`} key={tab.id} onClick={() => setActiveTab(tab.id)} onKeyDown={event => {
            const next = tabIndexForKey(event.key, index, tabs.length);
            if (next === null) return;
            event.preventDefault(); setActiveTab(tabs[next].id); tabRefs.current[next]?.focus();
          }} ref={node => { tabRefs.current[index] = node; }} role="tab" tabIndex={activeTab === tab.id ? 0 : -1} type="button">{t(tab.key)}{tab.count !== null ? <span className="ws-tab-count">{tab.count}</span> : null}</button>)}
        </div>

        {listTab ? <ApprovalFilters applied={filters} onApply={applyFilters} tab={listTab} /> : <p className="form-helper approval-publish-scope">{t("approvalFilterPublishScope")}</p>}

        <div aria-labelledby={`${tabGroupId}-${activeTab}`} className="approval-workspace-stack" id={`${tabGroupId}-panel`} role="tabpanel" tabIndex={0}>
          {activeTab === "publish" ? (
            <section className="approval-list-card" aria-labelledby={`${tabGroupId}-publish-title`}>
              <header className="approval-list-header approval-publish-toolbar" aria-live="polite">
                <h2 id={`${tabGroupId}-publish-title`}>{t("approvalPendingPublishPanel")}</h2>
                <span>{publishRead.ready ? format(publishRead.total !== null ? "approvalPendingPublishCount" : "approvalPendingPublishUnknownTotal", { count: pendingPublish.length, total: publishRead.total ?? "—" }) : "—"}</span>
                <button aria-label={format("uiReadRetrySection", { section: t("approvalPendingPublishPanel") })} className="action-button secondary" disabled={publishRead.loading} onClick={() => { void publishRead.reload(); }} type="button"><RefreshCw aria-hidden="true" size={15} />{t("uiReadRetry")}</button>
              </header>
              {publishRead.stale ? <p className="form-helper approval-list-note" role="status">{t("approvalPendingPublishStale")}</p> : null}
              <ReadResourceStatus label={t("approvalPendingPublishPanel")} loading={publishRead.loading} error={publishRead.error} onRetry={publishRead.retry} />
              <div aria-label={t("approvalPendingPublishPanel")} className="table-list approval-submission-list" role="region" tabIndex={0}>
                {pendingPublish.map((item) => {
                  const publishingThisVersion = publishingVersionId === item.document_version_id;
                  return (
                    <div aria-busy={publishingThisVersion} className="table-row approval-submission-row approval-pending-publish-row" key={item.document_version_id}>
                      <div className="approval-row-main">
                        <strong>{item.document_title ?? `${t("approvalDocument")} ${shortId(item.document_id)}`}<span className="approval-version-label">{item.version_label ?? shortId(item.document_version_id)}</span></strong>
                        <small className="approval-row-line">
                          <span>{projectLine(item.project_id, item.project_name)}</span>
                          <span title={displaySubmitterDetail(item, t)}>{t("approvalSubmitter")} {displaySubmitterName(item, locale)}</span>
                          <span>{item.approved_at ? `${t("approvalWorkflowApproved")} ${formatShortDateTime(item.approved_at, locale)}` : t("approvalApprovedTimeUnknown")}</span>
                        </small>
                      </div>
                      <StatusToneBadge status={item.version_status} />
                      <span aria-live="polite" className="approval-decision-actions" role={publishingThisVersion ? "status" : undefined}>
                        {item.approval_task_id ? <Link className="text-link" href={`/approve/${item.approval_task_id}`}>{t("approvalOpenApprovalDetail")} <ArrowRight size={16} /></Link> : null}
                        <button className="action-button" disabled={publishingVersionId !== null} onClick={() => { void publishApprovedVersion(item); }} type="button">
                          {publishingThisVersion ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
                          {publishingThisVersion ? t("approvalPublishing") : t("publish")}
                        </button>
                      </span>
                    </div>
                  );
                })}
                {publishRead.ready && !publishRead.loading && !publishRead.error && !publishRead.stale && pendingPublish.length === 0 ? <div className="empty-state compact"><CheckCircle2 size={24} /><p>{t("approvalNoPendingPublish")}</p></div> : null}
              </div>
              {publishRead.ready && publishRead.hasMore && !publishRead.error ? <div className="approval-list-footer"><button aria-label={t("approvalPendingPublishLoadMore")} className="action-button secondary" disabled={publishRead.loading} onClick={() => { void publishRead.loadMore(); }} type="button">{publishRead.loading ? <Loader2 className="spin" size={16} /> : null}{t("uiLoadMore")}</button></div> : null}
            </section>
          ) : (
            <div className={previewTaskId ? "approval-split has-preview" : "approval-split"}>
              <section className="approval-list-card" aria-labelledby={`${tabGroupId}-list-title`}>
                <header className="approval-list-header read-resource-toolbar" aria-live="polite">
                  <h2 id={`${tabGroupId}-list-title`}>{listTitle}</h2>
                  <span>{loadedLabel(activeRead.ready, activeRead.items.length)}</span>
                  <button className="action-button secondary" disabled={activeRead.loading} onClick={() => { void activeRead.reload(); }} type="button"><RefreshCw aria-hidden="true" size={15} />{t("uiReadRetry")}</button>
                </header>
                <ReadResourceStatus loading={activeRead.loading} error={activeRead.error} onRetry={activeRead.ready ? activeRead.loadMore : activeRead.reload} />
                {activeTab === "mine" ? (
                  <div aria-label={t("approvalFilterResults")} className="table-list approval-submission-list" role="region" tabIndex={0}>
                    {submissions.map((submission) => (
                      <div className="table-row approval-submission-row" key={submission.id}>
                        <div className="approval-row-main">
                          <strong>{submission.document_title ?? `${t("approvalDocument")} ${shortId(submission.document_id)}`}<span className="approval-version-label">{submission.version_label ?? shortId(submission.document_version_id)}</span></strong>
                          <small className="approval-row-line">
                            <span>{projectLine(submission.project_id, submission.project_name)}</span>
                            <span>{t("approvalSubmission")} {shortId(submission.id)} · {formatShortDateTime(submission.submitted_at, locale)}</span>
                            <span>{submission.current_task_id ? format("approvalCurrentTask", { id: shortId(submission.current_task_id) }) : t("approvalWaitingPublishOrComplete")}</span>
                          </small>
                        </div>
                        <StatusToneBadge status={submission.status} />
                      </div>
                    ))}
                    {mineRead.ready && !mineRead.loading && submissions.length === 0 ? <div className="empty-state compact"><p>{t("approvalNoSubmissions")}</p></div> : null}
                  </div>
                ) : (
                  <div aria-label={t("approvalFilterResults")} className="table-list approval-task-list" role="region" tabIndex={0}>
                    {taskItems.map((approval) => {
                      const ownSubmission = Boolean(currentUser?.user_id) && approval.submitter_id === currentUser?.user_id;
                      return (
                        <Link aria-current={previewTaskId === approval.id ? "true" : undefined} className="table-row approval-task-row" href={`/approve/${approval.id}`} key={approval.id} onClick={event => selectTask(event, approval.id)}>
                          <div className="approval-row-main">
                            <strong>{approval.document_title ?? `${t("approvalDocument")} ${shortId(approval.document_id)}`}<span className="approval-version-label">{approval.version_label ?? shortId(approval.document_version_id)}</span></strong>
                            <small className="approval-row-line">
                              <span>{projectLine(approval.project_id, approval.project_name)}</span>
                              <span>{stageLabel(approval.review_stage, t)}</span>
                              <span title={displaySubmitterDetail(approval, t)}>{t("approvalSubmitter")} {displaySubmitterName(approval, locale)}</span>
                              <span>{formatShortDateTime(approval.submitted_at, locale)}</span>
                              {activeTab !== "pending" && approval.completed_at ? <span>{t("approvalFilterCompletedTime")} {formatShortDateTime(approval.completed_at, locale)}</span> : null}
                              {activeTab !== "pending" && approval.source_type ? <span>{approval.source_type}</span> : null}
                            </small>
                          </div>
                          <span className="approval-row-badges">
                            {ownSubmission && activeTab === "pending" ? <ToneBadge tone="violet">{t("approvalOwnSubmissionBadge")}</ToneBadge> : null}
                            <StatusToneBadge status={approval.status} />
                          </span>
                          <ChevronRight aria-hidden="true" className="approval-row-chevron" size={17} />
                        </Link>
                      );
                    })}
                    {activeRead.ready && !activeRead.loading && taskItems.length === 0 ? <div className="empty-state compact">{activeTab === "pending" ? <CheckCircle2 size={24} /> : null}<p>{activeTab === "pending" ? t("approvalNoPendingTasks") : activeTab === "history" ? t("approvalNoHistory") : t("approvalNoRejected")}</p></div> : null}
                  </div>
                )}
                {activeRead.ready && activeRead.hasMore ? <div className="approval-list-footer"><button className="action-button secondary" disabled={activeRead.loading} onClick={() => { void activeRead.loadMore(); }} type="button">{activeRead.loading ? <Loader2 className="spin" size={16} /> : null}{t("uiLoadMore")}</button></div> : null}
              </section>
              {previewTaskId ? <ApprovalPreview apiFetch={apiFetch} currentUserId={currentUser?.user_id ?? null} key={previewTaskId} taskId={previewTaskId} /> : null}
            </div>
          )}

          <details className="approval-rules" open>
            <summary><ChevronRight aria-hidden="true" className="approval-rules-chevron" size={16} />{format("approvalTodayRulesCount", { count: 3 })}</summary>
            <ul className="policy-strip">
              <li><CheckCircle2 aria-hidden="true" size={16} /> {t("approvalRuleNoDelegatedSigning")}</li>
              <li><CheckCircle2 aria-hidden="true" size={16} /> {t("approvalRuleOwnerOptimisticLock")}</li>
              <li><CheckCircle2 aria-hidden="true" size={16} /> {t("approvalRulePublishWritesLive")}</li>
            </ul>
          </details>
        </div>
      </div>
    </AppShell>
  );
}
