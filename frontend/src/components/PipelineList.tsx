import { AlertTriangle, CheckCircle2, Clock3, Database, RotateCcw } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";
import { ActionButton, StatusBadge } from "./AppShell";

type PipelineListRun = {
  id: string;
  document: string;
  version: string;
  source: string;
  status: keyof typeof icons;
  progress: number;
  currentStep: string;
  elapsed: string;
  eta: string;
  waitingRole?: string;
  steps: Array<readonly [string, string]>;
};

const icons = {
  completed: CheckCircle2,
  submission_ready: CheckCircle2,
  pending_manager_review: Clock3,
  pending_owner_review: Clock3,
  approved: CheckCircle2,
  publish_ready: CheckCircle2,
  publishing: Clock3,
  production_indexing: Database,
  graph_syncing: Clock3,
  published_active: CheckCircle2,
  running: Clock3,
  waiting_action: Clock3,
  failed: AlertTriangle,
  review_rejected: AlertTriangle,
  queued: Clock3,
  skipped: CheckCircle2
};

export function PipelineList({ runs = [] }: { runs?: PipelineListRun[] }) {
  const { t } = useI18n();
  if (!runs.length) {
    return <div className="empty-state compact"><p>{t("pipelineNoLiveRuns")}</p></div>;
  }
  return (
    <div className="pipeline-list">
      {runs.map((run) => {
        const Icon = icons[run.status];
        return (
          <article className="pipeline-row" key={run.id}>
            <div className="pipeline-main">
              <div className="row-title">
                <Icon size={18} />
                <div>
                  <strong>{run.document}</strong>
                  <small>{run.version} · {run.source}</small>
                </div>
              </div>
              <StatusBadge status={run.status} />
            </div>
            <div className="progress-line">
              <span style={{ width: `${run.progress}%` }} />
            </div>
            <div className="pipeline-meta">
              <span>{t("pipelineCurrentStep")}：{run.currentStep}</span>
              <span>{t("pipelineElapsed")}：{run.elapsed}</span>
              <span>{t("pipelineEta")}：{run.eta}</span>
              {run.waitingRole ? <span>{t("pipelineWaiting")}：{run.waitingRole}</span> : null}
            </div>
            <div className="step-grid">
              {run.steps.map(([label, status]) => (
                <span className={`step-pill step-${status}`} key={`${run.id}-${label}`}>
                  {label}
                </span>
              ))}
            </div>
            {run.status === "failed" ? (
              <div className="row-actions">
                <ActionButton variant="secondary"><RotateCcw size={16} /> {t("pipelineRetryFailedStep")}</ActionButton>
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}
