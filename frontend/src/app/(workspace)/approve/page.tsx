"use client";

import { ApprovalFilters } from "@/components/ApprovalFilters";
import { approvalListFilters, emptyApprovalFilters, type ApprovalFilterValues } from "@/lib/approvalFilters";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import Link from "next/link";
import { ReadResourceStatus } from "@/components/ReadResourceStatus";
import { useReadResource } from "@/lib/useReadResource";
import { useCursorList } from "@/lib/useCursorList";
import { usePendingPublishList } from "@/lib/usePendingPublishList";
import { useCallback, useId, useMemo, useRef, useState } from "react";
import { tabIndexForKey } from "@/lib/workspaceNavigation";
import { ArrowRight, CheckCircle2, Clock3, FileText, FolderKanban, History, Loader2, UserCheck, UserRound } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { AppShell, Panel, StatCard, StatusBadge } from "@/components/AppShell";
import { getApprovalSummary, listApprovalHistoryPage, listMyApprovalSubmissionsPage, listPendingApprovalsPage, listPendingPublishApprovalsPage, listRejectedApprovalsPage, publishDocumentVersion, type ApprovalPendingPublishResponse } from "@/lib/api";
import { t as translate, type Locale } from "@/lib/i18n";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { formatPersonName } from "@/lib/personName";

type Translate = (key: TranslationKey) => string;

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

export default function ApprovalPage() {
  const tabGroupId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const { apiFetch, authReady, operationGuards } = useAuth();
  const { locale, format } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
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
  const [activeTab, setActiveTab] = useState<"mine" | "pending" | "history" | "rejected">("pending");
  const [publishing, setPublishing] = useState<{ scope: typeof operationGuards; versionId: string } | null>(null);
  const inFlightPublish = useRef<typeof publishing>(null);
  const publishingVersionId = publishing?.scope === operationGuards ? publishing.versionId : null;
  const [publication, setPublication] = useState<{ scope: typeof operationGuards; generation?: number; error?: unknown } | null>(null);
  const currentPublication = publication?.scope === operationGuards ? publication : null;
  const activeRead = activeTab === "mine" ? mineRead : activeTab === "history" ? historyRead : activeTab === "rejected" ? rejectedRead : pendingRead;
  const loadedLabel = (ready: boolean, count: number) => ready ? format("uiLoadedCount", { count }) : "—";
  const summaryValue = (value?: number) => summaryRead.status === "ready" ? String(value ?? 0) : summaryRead.status === "loading" ? "…" : "—";
  const summaryHelper = summaryRead.status === "ready" ? format("approvalPendingHelper", { manager: summary?.pending_manager_review ?? 0, owner: summary?.pending_owner_review ?? 0 }) : t(summaryRead.status === "loading" ? "uiReadLoading" : "uiReadUnavailable");

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

  return (
    <AppShell title={t("approval")}>
      <p className="form-helper">{t("approvalFilterSummaryScope")}</p>
      <div className="page-grid approval-summary-grid">
        <StatCard label={t("approvalPendingMine")} value={summaryValue(summary?.pending_total)} helper={summaryHelper} tone={summary?.pending_total ? "coral" : "sage"} />
        <StatCard label={t("approvalMySubmissions")} value={summaryValue(summary?.my_submissions)} helper={t("approvalMySubmissionsHelp")} />
        <StatCard label={t("approvalPublishControl")} value={publishRead.loading ? "…" : publishRead.total !== null ? String(publishRead.total) : "—"} helper={t(publishRead.stale ? "approvalPendingPublishStale" : "approvalPublishControlHelp")} tone="gold" />
      </div>

      <ReadResourceStatus label={t("approval")} loading={summaryRead.status === "loading"} error={summaryRead.error} onRetry={summaryRead.reload} />
      {activeTab !== "mine" ? <ReadResourceStatus label={t("approvalPublishControl")} loading={false} error={publishRead.error} onRetry={publishRead.retry} /> : null}
      {currentPublication?.error ? <FeedbackMessage title={t("approvalPublishFailed")}>{operationalErrorMessage(currentPublication.error, t, format, "approvalPublishFailed")}</FeedbackMessage> : null}
      {currentPublication?.generation !== undefined ? <section className="approval-result approve"><CheckCircle2 size={17} /> {format("approvalPublishedGeneration", { generation: currentPublication.generation })}</section> : null}

      <nav aria-label={t("approval")} className="tab-strip" role="tablist">
        {([
          { id: "mine", key: "approvalMySubmissions", read: mineRead },
          { id: "pending", key: "approvalPendingMine", read: pendingRead },
          { id: "history", key: "approvalTabHistory", read: historyRead },
          { id: "rejected", key: "approvalTabRejected", read: rejectedRead }
        ] as const).map((tab, index, tabs) => <button aria-controls={`${tabGroupId}-panel`} aria-selected={activeTab === tab.id} className={activeTab === tab.id ? "active" : ""} id={`${tabGroupId}-${tab.id}`} key={tab.id} onClick={() => setActiveTab(tab.id)} onKeyDown={event => {
          const next = tabIndexForKey(event.key, index, tabs.length);
          if (next === null) return;
          event.preventDefault(); setActiveTab(tabs[next].id); tabRefs.current[next]?.focus();
        }} ref={node => { tabRefs.current[index] = node; }} role="tab" tabIndex={activeTab === tab.id ? 0 : -1} type="button">{t(tab.key)} <span>{loadedLabel(tab.read.ready, tab.read.items.length)}</span></button>)}
      </nav>

      <ApprovalFilters applied={filters} onApply={applyFilters} tab={activeTab} />

      <div aria-labelledby={`${tabGroupId}-${activeTab}`} className="approval-workspace-stack" id={`${tabGroupId}-panel`} role="tabpanel" tabIndex={0}>
      <div className="read-resource-toolbar" aria-live="polite">
        <span>{loadedLabel(activeRead.ready, activeRead.items.length)}</span>
        <button className="action-button secondary" disabled={activeRead.loading} onClick={() => { void activeRead.reload(); }} type="button">{t("uiReadRetry")}</button>
      </div>
      <ReadResourceStatus loading={activeRead.loading} error={activeRead.error} onRetry={activeRead.ready ? activeRead.loadMore : activeRead.reload} />
      {activeTab === "pending" ? (
      <Panel title={t("approvalPendingList")}>
        <div aria-label={t("approvalFilterResults")} className="table-list approval-task-list" role="region" tabIndex={0}>
          {pending.map((approval) => (
            <Link className="table-row approval-task-row" href={`/approve/${approval.id}`} key={approval.id}>
              <div className="row-title approval-task-title">
                {approval.review_stage === "owner_review" ? <UserCheck size={18} /> : <Clock3 size={18} />}
                <div>
                  <small><FolderKanban size={13} /> {approval.project_name ?? `${t("approvalProjectLabel")} ${shortId(approval.project_id)}`}</small>
                  <strong>{approval.document_title ?? `${t("approvalDocument")} ${shortId(approval.document_id)}`}</strong>
                  <small><FileText size={13} /> {format("approvalTaskIdentity", { task: shortId(approval.id), version: approval.version_label ?? shortId(approval.document_version_id) })}</small>
                </div>
              </div>
              <span className="approval-row-meta"><UserRound size={14} /><span><small>{t("approvalSubmitter")}</small><strong>{displaySubmitterName(approval, locale)}</strong><em>{displaySubmitterDetail(approval, t)}</em></span></span>
              <span>{stageLabel(approval.review_stage, t)}</span>
              <span>{new Date(approval.submitted_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW")}</span>
              <StatusBadge status={approval.status} />
              <ArrowRight size={17} />
            </Link>
          ))}
          {pendingRead.ready && !pendingRead.loading && pending.length === 0 ? <div className="empty-state compact"><CheckCircle2 size={24} /><p>{t("approvalNoPendingTasks")}</p></div> : null}
        </div>
      </Panel>
      ) : null}

      {activeTab === "mine" ? (
      <Panel title={t("approvalMySubmissionsPanel")}>
        <div aria-label={t("approvalFilterResults")} className="table-list approval-submission-list" role="region" tabIndex={0}>
          {submissions.map((submission) => (
            <div className="table-row approval-submission-row" key={submission.id}>
              <div className="row-title">
                <History size={18} />
                <div>
                  <small>{submission.project_name ?? `${t("approvalProjectLabel")} ${shortId(submission.project_id)}`}</small>
                  <strong>{submission.document_title ?? `${t("approvalDocument")} ${shortId(submission.document_id)}`}</strong>
                  <small>{t("approvalVersion")} {submission.version_label ?? shortId(submission.document_version_id)} · {t("approvalSubmission")} {shortId(submission.id)}</small>
                </div>
              </div>
              <span>{submission.current_task_id ? format("approvalCurrentTask", { id: shortId(submission.current_task_id) }) : t("approvalWaitingPublishOrComplete")}</span>
              <span>{new Date(submission.submitted_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW")}</span>
              <StatusBadge status={submission.status} />
            </div>
          ))}
          {mineRead.ready && !mineRead.loading && submissions.length === 0 ? <div className="empty-state compact"><p>{t("approvalNoSubmissions")}</p></div> : null}
        </div>
      </Panel>
      ) : null}

      {activeTab === "mine" ? (
      <Panel title={t("approvalPendingPublishPanel")}>
        <p className="form-helper">{t("approvalFilterPublishScope")}</p>
        <div className="read-resource-toolbar approval-publish-toolbar" aria-live="polite">
          <span>{publishRead.ready ? format(publishRead.total !== null ? "approvalPendingPublishCount" : "approvalPendingPublishUnknownTotal", { count: pendingPublish.length, total: publishRead.total ?? "—" }) : "—"}</span>
          <button aria-label={format("uiReadRetrySection", { section: t("approvalPendingPublishPanel") })} className="action-button secondary" disabled={publishRead.loading} onClick={() => { void publishRead.reload(); }} type="button">{t("uiReadRetry")}</button>
        </div>
        {publishRead.stale ? <p className="form-helper" role="status">{t("approvalPendingPublishStale")}</p> : null}
        <ReadResourceStatus label={t("approvalPendingPublishPanel")} loading={publishRead.loading} error={publishRead.error} onRetry={publishRead.retry} />
        <div aria-label={t("approvalPendingPublishPanel")} className="table-list approval-submission-list" role="region" tabIndex={0}>
          {pendingPublish.map((item) => {
            const publishingThisVersion = publishingVersionId === item.document_version_id;
            return (
              <div aria-busy={publishingThisVersion} className="table-row approval-submission-row approval-pending-publish-row" key={item.document_version_id}>
                <div className="row-title">
                  <CheckCircle2 size={18} />
                  <div>
                    <small>{item.project_name ?? `${t("approvalProjectLabel")} ${shortId(item.project_id)}`}</small>
                    <strong>{item.document_title ?? `${t("approvalDocument")} ${shortId(item.document_id)}`}</strong>
                    <small>{t("approvalVersion")} {item.version_label ?? shortId(item.document_version_id)} · {t("approvalWaitingPublishOrComplete")}</small>
                  </div>
                </div>
                <span className="approval-row-meta"><UserRound size={14} /><span><small>{t("approvalSubmitter")}</small><strong>{displaySubmitterName(item, locale)}</strong><em>{displaySubmitterDetail(item, t)}</em></span></span>
                <span>{item.approved_at ? new Date(item.approved_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW") : t("approvalApprovedTimeUnknown")}</span>
                <StatusBadge status={item.version_status} />
                <span aria-live="polite" className="approval-decision-actions" role={publishingThisVersion ? "status" : undefined}>
                  {item.approval_task_id ? <Link className="text-link" href={`/approve/${item.approval_task_id}`}>{t("approvalOpenApprovalDetail")} <ArrowRight size={16} /></Link> : null}
                  <button className="action-button secondary" disabled={publishingVersionId !== null} onClick={() => { void publishApprovedVersion(item); }} type="button">
                    {publishingThisVersion ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
                    {publishingThisVersion ? t("approvalPublishing") : t("publish")}
                  </button>
                </span>
              </div>
            );
          })}
          {publishRead.ready && !publishRead.loading && !publishRead.error && !publishRead.stale && pendingPublish.length === 0 ? <div className="empty-state compact"><CheckCircle2 size={24} /><p>{t("approvalNoPendingPublish")}</p></div> : null}
        </div>
        {publishRead.ready && publishRead.hasMore && !publishRead.error ? <div className="read-resource-toolbar approval-publish-toolbar"><button aria-label={t("approvalPendingPublishLoadMore")} className="action-button secondary" disabled={publishRead.loading} onClick={() => { void publishRead.loadMore(); }} type="button">{publishRead.loading ? <Loader2 className="spin" size={16} /> : null}{t("uiLoadMore")}</button></div> : null}
      </Panel>
      ) : null}

      {activeTab === "history" || activeTab === "rejected" ? (
        <Panel title={activeTab === "history" ? t("approvalTabHistory") : t("approvalTabRejected")}>
          <div aria-label={t("approvalFilterResults")} className="table-list approval-task-list" role="region" tabIndex={0}>
            {(activeTab === "history" ? history : rejected).map((approval) => (
              <Link className="table-row approval-task-row" href={`/approve/${approval.id}`} key={approval.id}>
                <div className="row-title approval-task-title">
                  <History size={18} />
                  <div>
                    <small><FolderKanban size={13} /> {approval.project_name ?? `${t("approvalProjectLabel")} ${shortId(approval.project_id)}`}</small>
                    <strong>{approval.document_title ?? `${t("approvalDocument")} ${shortId(approval.document_id)}`}</strong>
                    <small><FileText size={13} /> {approval.version_label ?? shortId(approval.document_version_id)} · {approval.source_type ?? "-"}</small>
                  </div>
                </div>
                <span className="approval-row-meta"><UserRound size={14} /><span><small>{t("approvalSubmitter")}</small><strong>{displaySubmitterName(approval, locale)}</strong><em>{displaySubmitterDetail(approval, t)}</em></span></span>
                <span>{stageLabel(approval.review_stage, t)}</span>
                <span className="approval-row-dates"><span>{t("approvalFilterSubmittedTime")} {new Date(approval.submitted_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW")}</span>{approval.completed_at ? <small>{t("approvalFilterCompletedTime")} {new Date(approval.completed_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW")}</small> : null}</span>
                <StatusBadge status={approval.status} />
                <ArrowRight size={17} />
              </Link>
            ))}
            {activeRead.ready && !activeRead.loading && (activeTab === "history" ? history : rejected).length === 0 ? <div className="empty-state compact"><p>{activeTab === "history" ? t("approvalNoHistory") : t("approvalNoRejected")}</p></div> : null}
          </div>
        </Panel>
      ) : null}

      {activeRead.ready && activeRead.hasMore ? <div className="read-resource-toolbar"><button className="action-button secondary" disabled={activeRead.loading} onClick={() => { void activeRead.loadMore(); }} type="button">{activeRead.loading ? <Loader2 className="spin" size={16} /> : null}{t("uiLoadMore")}</button></div> : null}

      <Panel title={t("approvalTodayRules")}>
        <div className="policy-strip">
          <span><CheckCircle2 size={17} /> {t("approvalRuleNoDelegatedSigning")}</span>
          <span><CheckCircle2 size={17} /> {t("approvalRuleOwnerOptimisticLock")}</span>
          <span><CheckCircle2 size={17} /> {t("approvalRulePublishWritesLive")}</span>
        </div>
      </Panel>
      </div>
    </AppShell>
  );
}
