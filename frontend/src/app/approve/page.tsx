"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Clock3, FileText, FolderKanban, History, Loader2, UserCheck, UserRound } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { AppShell, Panel, StatCard, StatusBadge } from "@/components/AppShell";
import { getApprovalSummary, listApprovalHistory, listMyApprovalSubmissions, listPendingApprovals, listPendingPublishApprovals, listRejectedApprovals, publishDocumentVersion, type ApprovalPendingPublishResponse, type ApprovalRequestResponse, type ApprovalSummary, type ApprovalTaskResponse } from "@/lib/api";
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
  const { apiFetch, authReady } = useAuth();
  const { locale, format, localize } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const [summary, setSummary] = useState<ApprovalSummary | null>(null);
  const [pending, setPending] = useState<ApprovalTaskResponse[]>([]);
  const [submissions, setSubmissions] = useState<ApprovalRequestResponse[]>([]);
  const [history, setHistory] = useState<ApprovalTaskResponse[]>([]);
  const [rejected, setRejected] = useState<ApprovalTaskResponse[]>([]);
  const [pendingPublish, setPendingPublish] = useState<ApprovalPendingPublishResponse[]>([]);
  const [activeTab, setActiveTab] = useState<"mine" | "pending" | "history" | "rejected">("pending");
  const [publishingVersionId, setPublishingVersionId] = useState<string | null>(null);
  const [publishResult, setPublishResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authReady) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [summaryRow, pendingRows, submissionRows, historyRows, rejectedRows, pendingPublishRows] = await Promise.all([
          getApprovalSummary(apiFetch),
          listPendingApprovals(apiFetch),
          listMyApprovalSubmissions(apiFetch),
          listApprovalHistory(apiFetch),
          listRejectedApprovals(apiFetch),
          listPendingPublishApprovals(apiFetch)
        ]);
        if (cancelled) return;
        setSummary(summaryRow);
        setPending(pendingRows);
        setSubmissions(submissionRows);
        setHistory(historyRows);
        setRejected(rejectedRows);
        setPendingPublish(pendingPublishRows);
      } catch (err) {
        if (!cancelled) setError(operationalErrorMessage(err, t, format, "approvalLoadFailed"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [apiFetch, authReady, format, t]);

  async function publishApprovedVersion(item: ApprovalPendingPublishResponse) {
    setPublishingVersionId(item.document_version_id);
    setError(null);
    setPublishResult(null);
    try {
      const result = await publishDocumentVersion(apiFetch, item.document_version_id, { lock_version: item.lock_version, impact_confirmed: true });
      setPendingPublish((current) => current.filter((row) => row.document_version_id !== item.document_version_id));
      setPublishResult(format("approvalPublishedGeneration", { generation: result.publication_generation }));
    } catch (err) {
      setError(operationalErrorMessage(err, t, format, "approvalPublishFailed"));
    } finally {
      setPublishingVersionId(null);
    }
  }

  return (
    <AppShell title={t("approval")}>
      <div className="page-grid approval-summary-grid">
        <StatCard label={t("approvalPendingMine")} value={String(summary?.pending_total ?? 0)} helper={format("approvalPendingHelper", { manager: summary?.pending_manager_review ?? 0, owner: summary?.pending_owner_review ?? 0 })} tone={summary?.pending_total ? "coral" : "sage"} />
        <StatCard label={t("approvalMySubmissions")} value={String(summary?.my_submissions ?? submissions.length)} helper={t("approvalMySubmissionsHelp")} />
        <StatCard label={t("approvalPublishControl")} value={String(pendingPublish.length)} helper={t("approvalPublishControlHelp")} tone="gold" />
      </div>

      {error ? <section className="empty-state" role="alert"><h2>{t("approvalLoadFailed")}</h2><p>{localize(error)}</p></section> : null}
      {publishResult ? <section className="approval-result approve"><CheckCircle2 size={17} /> {localize(publishResult)}</section> : null}

      <nav aria-label={t("approval")} className="tab-strip">
        <button aria-selected={activeTab === "mine"} className={activeTab === "mine" ? "active" : ""} onClick={() => setActiveTab("mine")} role="tab" type="button">{t("approvalMySubmissions")} <span>{submissions.length}</span></button>
        <button aria-selected={activeTab === "pending"} className={activeTab === "pending" ? "active" : ""} onClick={() => setActiveTab("pending")} role="tab" type="button">{t("approvalPendingMine")} <span>{pending.length}</span></button>
        <button aria-selected={activeTab === "history"} className={activeTab === "history" ? "active" : ""} onClick={() => setActiveTab("history")} role="tab" type="button">{t("approvalTabHistory")} <span>{history.length}</span></button>
        <button aria-selected={activeTab === "rejected"} className={activeTab === "rejected" ? "active" : ""} onClick={() => setActiveTab("rejected")} role="tab" type="button">{t("approvalTabRejected")} <span>{rejected.length}</span></button>
      </nav>

      <div className="approval-workspace-stack">
      {activeTab === "pending" ? (
      <Panel title={t("approvalPendingList")}>
        <div className="table-list approval-task-list">
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
          {!loading && pending.length === 0 ? <div className="empty-state compact"><CheckCircle2 size={24} /><p>{t("approvalNoPendingTasks")}</p></div> : null}
        </div>
      </Panel>
      ) : null}

      {activeTab === "mine" ? (
      <Panel title={t("approvalMySubmissionsPanel")}>
        <div className="table-list approval-submission-list">
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
          {!loading && submissions.length === 0 ? <div className="empty-state compact"><p>{t("approvalNoSubmissions")}</p></div> : null}
        </div>
      </Panel>
      ) : null}

      {activeTab === "mine" ? (
      <Panel title={t("approvalPendingPublishPanel")}>
        <div className="table-list approval-submission-list">
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
                  <button className="action-button secondary" disabled={publishingThisVersion} onClick={() => { void publishApprovedVersion(item); }} type="button">
                    {publishingThisVersion ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
                    {publishingThisVersion ? t("approvalPublishing") : t("publish")}
                  </button>
                </span>
              </div>
            );
          })}
          {!loading && pendingPublish.length === 0 ? <div className="empty-state compact"><CheckCircle2 size={24} /><p>{t("approvalNoPendingPublish")}</p></div> : null}
        </div>
      </Panel>
      ) : null}

      {activeTab === "history" || activeTab === "rejected" ? (
        <Panel title={activeTab === "history" ? t("approvalTabHistory") : t("approvalTabRejected")}>
          <div className="table-list approval-task-list">
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
                <span>{new Date(approval.completed_at ?? approval.submitted_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW")}</span>
                <StatusBadge status={approval.status} />
                <ArrowRight size={17} />
              </Link>
            ))}
            {!loading && (activeTab === "history" ? history : rejected).length === 0 ? <div className="empty-state compact"><p>{activeTab === "history" ? t("approvalNoHistory") : t("approvalNoRejected")}</p></div> : null}
          </div>
        </Panel>
      ) : null}

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
