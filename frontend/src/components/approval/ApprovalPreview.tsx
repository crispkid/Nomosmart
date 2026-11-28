"use client";

import Link from "next/link";
import { useCallback, useId } from "react";
import { ChevronRight, Loader2 } from "lucide-react";
import { StatusToneBadge, ToneBadge } from "@/components/AppShell";
import { ReadResourceStatus } from "@/components/ReadResourceStatus";
import { ApprovalRoute, approvalPeople, approvalStageLabel } from "@/components/approval/ApprovalRoute";
import { ApprovalVersionChangesSection } from "@/components/approval/ApprovalVersionChanges";
import { getApprovalTask, type ApiFetch } from "@/lib/api";
import { formatShortDateTime } from "@/lib/dateFormat";
import { useI18n } from "@/lib/i18nClient";
import { projectColorClass } from "@/lib/projectColor";
import { useReadResource } from "@/lib/useReadResource";

/**
 * CHG-495 M21 (S14): on wide screens the selected approval shows beside the list. The full detail page
 * (`/approve/<taskId>`) keeps the evidence and the approve/return/publish controls.
 */
export function ApprovalPreview({ apiFetch, taskId, currentUserId }: { apiFetch: ApiFetch; taskId: string; currentUserId: string | null }) {
  const { locale, t, format } = useI18n();
  const titleId = useId();
  const read = useCallback((signal: AbortSignal) => getApprovalTask(apiFetch, taskId, signal), [apiFetch, taskId]);
  const detailRead = useReadResource(read, taskId, true);
  const detail = detailRead.data?.task.id === taskId ? detailRead.data : null;
  if (!detail) {
    return (
      <aside aria-busy={detailRead.status === "loading"} aria-label={t("approvalPreviewLabel")} className="approval-preview">
        {detailRead.status === "error" ? <ReadResourceStatus error={detailRead.error} label={t("approvalPreviewLabel")} loading={false} onRetry={detailRead.reload} />
          : <p className="approval-preview-empty" role="status"><Loader2 aria-hidden="true" className="spin" size={16} />{t("approvalLoadingTask")}</p>}
      </aside>
    );
  }
  const people = approvalPeople(detail, locale, t);
  const ownSubmission = Boolean(currentUserId) && detail.request.submitter_id === currentUserId;
  return (
    <aside aria-labelledby={titleId} className="approval-preview">
      <header className="approval-preview-header">
        <h2 id={titleId}>{detail.document.title}<span className="approval-version-label">{detail.version.version_label}</span></h2>
        <div className="approval-badges">
          <StatusToneBadge status={detail.task.status} />
          <ToneBadge tone="info">{approvalStageLabel(detail.task.review_stage, t)}</ToneBadge>
          <ToneBadge tone="neutral">{detail.request.priority === "High" ? t("approvalPriorityHigh") : t("approvalPriorityNormal")}</ToneBadge>
          {ownSubmission ? <ToneBadge tone="violet">{t("approvalOwnSubmissionBadge")}</ToneBadge> : null}
        </div>
        <p className="approval-preview-meta">
          <span aria-hidden="true" className={`project-color-dot ${projectColorClass(detail.task.project_id)}`} />
          {detail.task.project_name ?? t("approvalProjectLabel")} · {format("approvalSubmittedBy", { name: people.submitter, time: formatShortDateTime(detail.request.submitted_at, locale) })}
        </p>
      </header>
      <ApprovalRoute detail={detail} />
      <ApprovalVersionChangesSection apiFetch={apiFetch} approvalTaskId={taskId} />
      <footer className="approval-preview-footer">
        <Link className="action-button" href={`/approve/${taskId}`}>{t("approvalPreviewOpenDetail")}<ChevronRight aria-hidden="true" size={16} /></Link>
        <small>{ownSubmission ? t("approvalSelfReviewNote") : t("approvalPreviewDecisionHint")}</small>
      </footer>
    </aside>
  );
}
