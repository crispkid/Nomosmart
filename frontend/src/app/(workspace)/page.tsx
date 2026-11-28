"use client";

import Link from "next/link";
import { ReadResourceStatus } from "@/components/ReadResourceStatus";
import { useReadResource } from "@/lib/useReadResource";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Clock3, FolderOpen, Inbox, RotateCcw } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { AppShell, Panel, StatCard, StatusBadge } from "@/components/AppShell";
import { getApprovalSummary, getReportSummary, listMyApprovalSubmissionsPage, listPendingApprovals } from "@/lib/api";
import { localCalendarDayKey, readHomeProjectMetrics } from "@/lib/homeMetrics";
import { useI18n } from "@/lib/i18nClient";
import { projectColorClass } from "@/lib/projectColor";

function shortId(value: string) {
  return value.slice(0, 8);
}

/** M08: at most this many returned submissions are listed with the pending reviews. */
const returnedLimit = 5;

export default function HomePage() {
  const { format, locale, t } = useI18n();
  const { apiFetch, authReady, can, operationGuards } = useAuth();
  // The report summary needs the Reports menu permission; without it the report tiles are not shown
  // and the summary is not requested (CHG-495 M07).
  const canReadReports = can("Menu", "Reports", "view");
  const readSummary = useCallback(() => getApprovalSummary(apiFetch), [apiFetch]);
  const readApprovals = useCallback(() => listPendingApprovals(apiFetch), [apiFetch]);
  const readReturned = useCallback((signal: AbortSignal) => listMyApprovalSubmissionsPage(apiFetch, null, { result: "rejected" }, signal), [apiFetch]);
  const readReport = useCallback(() => getReportSummary(apiFetch, { topic: "system_overview" }), [apiFetch]);
  const summaryRead = useReadResource(readSummary, operationGuards, authReady);
  const approvalsRead = useReadResource(readApprovals, operationGuards, authReady);
  const returnedRead = useReadResource(readReturned, operationGuards, authReady);
  const reportRead = useReadResource(readReport, operationGuards, authReady && canReadReports);
  const approvalSummary = summaryRead.data;
  const approvals = approvalsRead.data ?? [];
  const returned = (returnedRead.data?.items ?? []).slice(0, returnedLimit);
  const reportSummary = reportRead.data;
  const approvalMetricState = summaryRead.status;
  const [calendarDay, setCalendarDay] = useState(() => localCalendarDayKey(new Date()));
  // OPT424-035: KPI counts come from paged reads, not from loading every project.
  const readProjects = useCallback((signal: AbortSignal) => {
    const [year, month, day] = calendarDay.split("-").map(Number);
    return readHomeProjectMetrics(apiFetch, new Date(year, month, day, 12), signal);
  }, [apiFetch, calendarDay]);
  const projectsRead = useReadResource(readProjects, operationGuards, authReady);
  const projects = useMemo(() => projectsRead.data?.recent ?? [], [projectsRead.data]);
  const projectsMetricState = projectsRead.status;
  const metrics = useMemo(() => Object.fromEntries((reportSummary?.metrics ?? []).map((item) => [item.key, item])), [reportSummary]);
  const activeProjects = projectsRead.data?.activeTotal ?? 0;
  const updatedTodayProjects = projectsRead.data?.updatedToday ?? 0;
  const numberLocale = locale === "en" ? "en-US" : "zh-TW";
  const count = (value: number | undefined) => value === undefined ? "—" : value.toLocaleString(numberLocale);
  const reportValue = (key: string) => reportRead.status === "loading" ? "…" : count(metrics[key]?.value);
  const reportHelper = (helper: string) => reportRead.status === "loading" ? t("homeKpiLoadingHelper") : reportRead.status === "error" ? t("uiReadUnavailable") : helper;

  const activeProjectsHelper = projectsMetricState === "loading"
    ? t("homeKpiLoadingHelper")
    : projectsMetricState === "error"
      ? t("homeKpiUnavailableHelper")
      : updatedTodayProjects === 0
        ? t("homeActiveProjectsHelperZero")
        : updatedTodayProjects === 1
          ? t("homeActiveProjectsHelperOne")
          : format("homeActiveProjectsHelperMany", { count: updatedTodayProjects });
  const pendingOwnerReviewHelper = approvalMetricState === "loading"
    ? t("homeKpiLoadingHelper")
    : approvalMetricState === "error"
      ? t("homeKpiUnavailableHelper")
      : (approvalSummary?.pending_owner_review ?? 0) === 0
        ? t("homePendingApprovalsHelperZero")
        : (approvalSummary?.pending_owner_review ?? 0) === 1
          ? t("homePendingApprovalsHelperOne")
          : format("homePendingApprovalsHelperMany", { count: approvalSummary?.pending_owner_review ?? 0 });
  const overdue = approvalMetricState === "ready" ? approvalSummary?.pending_overdue ?? 0 : 0;
  const overdueNote = overdue > 0 ? format("homePendingOverdue", { count: overdue, hours: approvalSummary?.pending_overdue_hours ?? 48 }) : undefined;
  const citedRate = metrics.recent_cited_chat_rate?.value;

  useEffect(() => {
    let timeout: number | undefined;
    const scheduleNextCalendarDay = () => {
      const now = new Date();
      const nextDay = new Date(now);
      nextDay.setHours(24, 0, 0, 0);
      timeout = window.setTimeout(() => {
        setCalendarDay(localCalendarDayKey(new Date()));
        scheduleNextCalendarDay();
      }, Math.max(1000, nextDay.getTime() - now.getTime()));
    };
    scheduleNextCalendarDay();
    return () => {
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, []);

  const pendingReady = approvalsRead.status === "ready" && returnedRead.status === "ready";

  return (
    <AppShell title={t("home")}>
      {/* M07 compromise: the four current KPIs stay; published documents and recent chats come from the WP4 summary. */}
      <section className={`home-kpis${canReadReports ? "" : " is-compact"}`} aria-label={t("homeKpiStrip")}>
        <StatCard label={t("activeProjects")} value={projectsMetricState === "ready" ? count(activeProjects) : projectsMetricState === "loading" ? "…" : "—"} helper={activeProjectsHelper} tone="neutral" />
        {canReadReports ? <StatCard label={t("homePublishedDocuments")} value={reportValue("published_document_count")} helper={reportHelper(format("homePublishedDocumentsHelper", { count: count(metrics.published_document_new_count?.value ?? 0) }))} /> : null}
        <StatCard label={t("pendingApprovals")} value={approvalMetricState === "ready" ? count(approvalSummary?.pending_total ?? 0) : approvalMetricState === "loading" ? "…" : "—"} helper={pendingOwnerReviewHelper} note={overdueNote} tone="gold" />
        {canReadReports ? <StatCard label={t("processing")} value={reportValue("pipeline_running_count")} helper={reportHelper(t("homeProcessingHelper"))} tone="sage" /> : null}
        {canReadReports ? <StatCard label={t("successRate")} value={reportRead.status === "loading" ? "…" : (metrics.success_rate?.value !== undefined ? `${Math.round(metrics.success_rate.value * 1000) / 10}%` : "—")} helper={reportHelper(t("homeSuccessRateHelper"))} /> : null}
        {canReadReports ? <StatCard label={t("homeRecentChats")} value={reportValue("recent_chat_count")} helper={reportHelper(citedRate !== undefined ? format("homeCitedChatRate", { rate: `${Math.round(citedRate * 100)}%` }) : t("homeNoRecentChats"))} tone="violet" /> : null}
      </section>

      <ReadResourceStatus label={t("pendingApprovals")} loading={summaryRead.status === "loading"} error={summaryRead.error} onRetry={summaryRead.reload} />
      {canReadReports ? <ReadResourceStatus label={t("reports")} loading={reportRead.status === "loading"} error={reportRead.error} onRetry={reportRead.reload} /> : null}

      <div className="home-panels">
        <Panel title={t("homeActiveProjectsPanel")} action={<Link className="text-link" href="/projects">{t("homeViewKnowledgeProjects")} <ArrowRight size={16} aria-hidden /></Link>}>
          <ReadResourceStatus label={t("homeActiveProjectsPanel")} loading={projectsRead.status === "loading"} error={projectsRead.error} onRetry={projectsRead.reload} />
          {projectsRead.status === "ready" && projects.length === 0 ? <div className="home-empty">
            <span className="home-empty-icon" aria-hidden><FolderOpen size={20} /></span>
            <strong>{t("homeEmptyProjectsTitle")}</strong>
            <p>{t("homeEmptyProjectsHelp")}</p>
            <Link className="action-button secondary" href="/projects">{t("homeGoToProjects")}</Link>
          </div> : null}
          {projects.length > 0 ? <ul className="home-list">
            {projects.slice(0, 3).map((project) => (
              <li key={project.id}>
                <Link className="home-row home-project-row" href={`/project/${project.id}/import`}>
                  <span className={`home-project-dot ${projectColorClass(project.id)}`} aria-hidden />
                  <span className="home-row-copy">
                    <strong>{project.name}</strong>
                    <small>{project.description || t("homeLiveProjectFallback")} · {project.last_activity_at ? format("homeProjectUpdated", { date: new Date(project.last_activity_at).toLocaleDateString(locale) }) : t("homeProjectNoRecentActivity")}</small>
                    <small className="home-project-tracking">{t("homeTrackingDetails")} · {format("homeProjectLlm", { id: project.llm_model_id ? shortId(project.llm_model_id) : "—" })} · {format("homeProjectEmbedding", { id: project.embedding_model_id ? shortId(project.embedding_model_id) : "—" })} · {format("homeProjectLock", { version: project.lock_version })}</small>
                  </span>
                  <StatusBadge status={project.status} />
                </Link>
              </li>
            ))}
          </ul> : null}
        </Panel>

        <Panel title={t("homePendingWorkPanel")} action={<Link className="text-link" href="/approve">{t("homeViewAll")} <ArrowRight size={16} aria-hidden /></Link>}>
          <ReadResourceStatus label={t("reviewQueue")} loading={approvalsRead.status === "loading"} error={approvalsRead.error} onRetry={approvalsRead.reload} />
          <ReadResourceStatus label={t("homeReturnedSubmissions")} loading={returnedRead.status === "loading"} error={returnedRead.error} onRetry={returnedRead.reload} />
          {pendingReady && approvals.length === 0 && returned.length === 0 ? <div className="home-empty">
            <span className="home-empty-icon" aria-hidden><Inbox size={20} /></span>
            <strong>{t("homeEmptyPendingTitle")}</strong>
            <p>{t("homeEmptyPendingHelp")}</p>
          </div> : null}
          {approvals.length > 0 || returned.length > 0 ? <ul className="home-list">
            {approvals.map((approval) => (
              <li key={approval.id}>
                <Link className="home-row home-approval-row" href={`/approve/${approval.id}`}>
                  <span className="home-row-icon tone-amber" aria-hidden>{approval.review_stage === "owner_review" ? <CheckCircle2 size={16} /> : <Clock3 size={16} />}</span>
                  <span className="home-row-copy">
                    <strong>{approval.document_title?.trim() || `${t("approvalDocument")} ${shortId(approval.document_id)}`}</strong>
                    <small>{approval.project_name?.trim() || `${t("approvalProjectLabel")} ${shortId(approval.project_id)}`} · {approval.version_label?.trim() || `${t("approvalVersion")} ${shortId(approval.document_version_id)}`} · {new Date(approval.submitted_at).toLocaleString(numberLocale)}</small>
                  </span>
                  <StatusBadge status={approval.status} />
                </Link>
              </li>
            ))}
            {returned.map((submission) => (
              <li key={submission.id}>
                <Link className="home-row home-returned-row" href={`/project/${submission.project_id}/knowledge/${submission.document_id}`}>
                  <span className="home-row-icon tone-danger" aria-hidden><RotateCcw size={16} /></span>
                  <span className="home-row-copy">
                    <strong>{submission.document_title?.trim() || `${t("approvalDocument")} ${shortId(submission.document_id)}`}</strong>
                    <small>{submission.project_name?.trim() || `${t("approvalProjectLabel")} ${shortId(submission.project_id)}`} · {submission.version_label?.trim() || `${t("approvalVersion")} ${shortId(submission.document_version_id)}`} · {format("homeReturnedSubmittedAt", { date: new Date(submission.submitted_at).toLocaleString(numberLocale) })}</small>
                  </span>
                  <StatusBadge status="review_rejected" />
                </Link>
              </li>
            ))}
          </ul> : null}
        </Panel>
      </div>

    </AppShell>
  );
}
