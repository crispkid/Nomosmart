"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, Clock3, FileText } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { AppShell, PageGrid, Panel, StatCard, StatusBadge } from "@/components/AppShell";
import { getApprovalSummary, getReportSummary, listPendingApprovals, listProjects, type ApiError, type ApprovalSummary, type ApprovalTaskResponse, type ProjectResponse, type ReportSummaryResponse } from "@/lib/api";
import { countProjectsUpdatedToday, localCalendarDayKey } from "@/lib/homeMetrics";
import { useI18n } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";

function shortId(value: string) {
  return value.slice(0, 8);
}

export default function HomePage() {
  const { format, locale, t } = useI18n();
  const { apiFetch, authReady } = useAuth();
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [approvalSummary, setApprovalSummary] = useState<ApprovalSummary | null>(null);
  const [approvals, setApprovals] = useState<ApprovalTaskResponse[]>([]);
  const [reportSummary, setReportSummary] = useState<ReportSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [projectsMetricState, setProjectsMetricState] = useState<"loading" | "ready" | "error">("loading");
  const [approvalMetricState, setApprovalMetricState] = useState<"loading" | "ready" | "error">("loading");
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
    if (!authReady) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setLoading(true);
      setError(null);
      setProjectsMetricState("loading");
      setApprovalMetricState("loading");
    });
    Promise.all([
      listProjects(apiFetch).then((projectRows) => {
        if (!cancelled) {
          setProjects(projectRows);
          setProjectsMetricState("ready");
        }
        return projectRows;
      }).catch((caught: ApiError | Error) => {
        if (!cancelled) setProjectsMetricState("error");
        throw caught;
      }),
      getApprovalSummary(apiFetch).then((summary) => {
        if (!cancelled) {
          setApprovalSummary(summary);
          setApprovalMetricState("ready");
        }
        return summary;
      }).catch((caught: ApiError | Error) => {
        if (!cancelled) setApprovalMetricState("error");
        throw caught;
      }),
      listPendingApprovals(apiFetch),
      getReportSummary(apiFetch, { topic: "system_overview" }).catch(() => null)
    ]).then(([, , pendingRows, report]) => {
      if (cancelled) return;
      setApprovals(pendingRows);
      setReportSummary(report);
    }).catch((caught: ApiError | Error) => {
      if (!cancelled) setError(caught);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [apiFetch, authReady]);

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
        <StatCard label={t("activeProjects")} value={loading ? "…" : String(activeProjects)} helper={activeProjectsHelper} />
        <StatCard label={t("processing")} value={loading ? "…" : String(metrics.pipeline_running_count?.value ?? "—")} helper={t("homeProcessingHelper")} tone="gold" />
        <StatCard label={t("pendingApprovals")} value={loading ? "…" : String(approvalSummary?.pending_total ?? 0)} helper={pendingOwnerReviewHelper} tone="coral" />
        <StatCard label={t("successRate")} value={loading ? "…" : (metrics.success_rate?.value !== undefined ? `${Math.round(metrics.success_rate.value * 1000) / 10}%` : "—")} helper={t("homeSuccessRateHelper")} tone="sage" />
      </PageGrid>

      {error ? <section className="form-error" role="alert">{t("homeLoadFailed")}：{operationalErrorMessage(error, t, format)}</section> : null}

      <div className="content-grid two">
        <Panel title={t("homeActiveProjectsPanel")} action={<Link className="text-link" href="/projects">{t("homeViewKnowledgeProjects")} <ArrowRight size={16} /></Link>}>
          <div className="project-list compact-projects">
            {!loading && projects.length === 0 ? <div className="empty-state compact"><p>{t("homeNoFormalProjects")}</p></div> : null}
            {projects.slice(0, 3).map((project) => (
              <Link className="project-card" href={`/project/${project.id}/import`} key={project.id}>
                <div className="project-icon"><FileText size={20} /></div>
                <div className="project-info">
                  <strong>{project.name}</strong>
                  <small>{project.description || t("homeLiveProjectFallback")} · {project.status}</small>
                  <div className="project-metrics">
                    <span>{format("homeProjectLlm", { id: project.llm_model_id ? shortId(project.llm_model_id) : "—" })}</span>
                    <span>{format("homeProjectEmbedding", { id: project.embedding_model_id ? shortId(project.embedding_model_id) : "—" })}</span>
                    <span>{format("homeProjectLock", { version: project.lock_version })}</span>
                  </div>
                </div>
                <StatusBadge status={project.status} />
              </Link>
            ))}
          </div>
        </Panel>

        <Panel title={t("reviewQueue")} action={<Link className="text-link" href="/approve">{t("homeViewAll")} <ArrowRight size={16} /></Link>}>
          <div className="approval-list">
            {!loading && approvals.length === 0 ? <div className="empty-state compact"><CheckCircle2 size={24} /><p>{t("homeNoPendingApprovals")}</p></div> : null}
            {approvals.map((approval) => (
              <Link className="approval-row" href={`/approve/${approval.id}`} key={approval.id}>
                <div className="row-title">
                  {approval.review_stage === "owner_review" ? <CheckCircle2 size={18} /> : <Clock3 size={18} />}
                  <div>
                    <strong>{t("approvalDocument")} {shortId(approval.document_id)}</strong>
                    <small>{t("approvalVersion")} {shortId(approval.document_version_id)} · {new Date(approval.submitted_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW")}</small>
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
