"use client";

import Link from "next/link";
import { ReadResourceStatus } from "@/components/ReadResourceStatus";
import { useReadResource } from "@/lib/useReadResource";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Clock3, FileText } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { AppShell, PageGrid, Panel, StatCard, StatusBadge } from "@/components/AppShell";
import { getApprovalSummary, getReportSummary, listPendingApprovals, listProjects } from "@/lib/api";
import { countProjectsUpdatedToday, localCalendarDayKey } from "@/lib/homeMetrics";
import { useI18n } from "@/lib/i18nClient";

function shortId(value: string) {
  return value.slice(0, 8);
}

export default function HomePage() {
  const { format, locale, t } = useI18n();
  const { apiFetch, authReady, operationGuards } = useAuth();
  const readProjects = useCallback(() => listProjects(apiFetch), [apiFetch]);
  const readSummary = useCallback(() => getApprovalSummary(apiFetch), [apiFetch]);
  const readApprovals = useCallback(() => listPendingApprovals(apiFetch), [apiFetch]);
  const readReport = useCallback(() => getReportSummary(apiFetch, { topic: "system_overview" }), [apiFetch]);
  const projectsRead = useReadResource(readProjects, operationGuards, authReady);
  const summaryRead = useReadResource(readSummary, operationGuards, authReady);
  const approvalsRead = useReadResource(readApprovals, operationGuards, authReady);
  const reportRead = useReadResource(readReport, operationGuards, authReady);
  const projects = useMemo(() => projectsRead.data ?? [], [projectsRead.data]);
  const approvalSummary = summaryRead.data;
  const approvals = approvalsRead.data ?? [];
  const reportSummary = reportRead.data;
  const projectsMetricState = projectsRead.status;
  const approvalMetricState = summaryRead.status;
  const [calendarDay, setCalendarDay] = useState(() => localCalendarDayKey(new Date()));
  const metrics = useMemo(() => Object.fromEntries((reportSummary?.metrics ?? []).map((item) => [item.key, item])), [reportSummary]);
  const activeProjects = projects.filter((project) => project.status === "active").length;
  const updatedTodayProjects = useMemo(() => {
    const [year, month, day] = calendarDay.split("-").map(Number);
    return countProjectsUpdatedToday(projects, new Date(year, month, day, 12));
  }, [calendarDay, projects]);

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

  return (
    <AppShell title={t("home")}>
      <PageGrid>
        <StatCard label={t("activeProjects")} value={projectsMetricState === "ready" ? String(activeProjects) : projectsMetricState === "loading" ? "…" : "—"} helper={activeProjectsHelper} />
        <StatCard label={t("processing")} value={reportRead.status === "loading" ? "…" : String(metrics.pipeline_running_count?.value ?? "—")} helper={reportRead.status === "error" ? t("uiReadUnavailable") : t("homeProcessingHelper")} tone="gold" />
        <StatCard label={t("pendingApprovals")} value={approvalMetricState === "ready" ? String(approvalSummary?.pending_total ?? 0) : approvalMetricState === "loading" ? "…" : "—"} helper={pendingOwnerReviewHelper} tone="coral" />
        <StatCard label={t("successRate")} value={reportRead.status === "loading" ? "…" : (metrics.success_rate?.value !== undefined ? `${Math.round(metrics.success_rate.value * 1000) / 10}%` : "—")} helper={reportRead.status === "error" ? t("uiReadUnavailable") : t("homeSuccessRateHelper")} tone="sage" />
      </PageGrid>

      <ReadResourceStatus label={t("pendingApprovals")} loading={summaryRead.status === "loading"} error={summaryRead.error} onRetry={summaryRead.reload} />
      <ReadResourceStatus label={t("reports")} loading={reportRead.status === "loading"} error={reportRead.error} onRetry={reportRead.reload} />

      <div className="content-grid two">
        <Panel title={t("homeActiveProjectsPanel")} action={<Link className="text-link" href="/projects">{t("homeViewKnowledgeProjects")} <ArrowRight size={16} /></Link>}>
          <ReadResourceStatus label={t("homeActiveProjectsPanel")} loading={projectsRead.status === "loading"} error={projectsRead.error} onRetry={projectsRead.reload} />
          <div className="project-list compact-projects">
            {projectsRead.status === "ready" && projects.length === 0 ? <div className="empty-state compact"><p>{t("homeNoFormalProjects")}</p></div> : null}
            {projects.slice(0, 3).map((project) => (
              <Link className="project-card" href={`/project/${project.id}/import`} key={project.id}>
                <div className="project-icon"><FileText size={20} /></div>
                <div className="project-info">
                  <strong>{project.name}</strong>
                  <small>{project.description || t("homeLiveProjectFallback")} · {project.status}</small>
                  <div className="project-metrics"><span>{project.last_activity_at ? format("homeProjectUpdated", { date: new Date(project.last_activity_at).toLocaleDateString(locale) }) : t("homeProjectNoRecentActivity")}</span></div>
                  <small className="home-project-tracking">{t("homeTrackingDetails")} · {format("homeProjectLlm", { id: project.llm_model_id ? shortId(project.llm_model_id) : "—" })} · {format("homeProjectEmbedding", { id: project.embedding_model_id ? shortId(project.embedding_model_id) : "—" })} · {format("homeProjectLock", { version: project.lock_version })}</small>
                </div>
                <StatusBadge status={project.status} />
              </Link>
            ))}
          </div>
        </Panel>

        <Panel title={t("reviewQueue")} action={<Link className="text-link" href="/approve">{t("homeViewAll")} <ArrowRight size={16} /></Link>}>
          <ReadResourceStatus label={t("reviewQueue")} loading={approvalsRead.status === "loading"} error={approvalsRead.error} onRetry={approvalsRead.reload} />
          <div className="approval-list">
            {approvalsRead.status === "ready" && approvals.length === 0 ? <div className="empty-state compact"><CheckCircle2 size={24} /><p>{t("homeNoPendingApprovals")}</p></div> : null}
            {approvals.map((approval) => (
              <Link className="approval-row" href={`/approve/${approval.id}`} key={approval.id}>
                <div className="row-title">
                  {approval.review_stage === "owner_review" ? <CheckCircle2 size={18} /> : <Clock3 size={18} />}
                  <div>
                    <strong>{approval.document_title?.trim() || `${t("approvalDocument")} ${shortId(approval.document_id)}`}</strong>
                    <small>{approval.project_name?.trim() || `${t("approvalProjectLabel")} ${shortId(approval.project_id)}`} · {approval.version_label?.trim() || `${t("approvalVersion")} ${shortId(approval.document_version_id)}`} · {new Date(approval.submitted_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW")}</small>
                  </div>
                </div>
                <StatusBadge status={approval.status} />
              </Link>
            ))}
          </div>
        </Panel>
      </div>

    </AppShell>
  );
}
