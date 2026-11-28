"use client";

import { useId } from "react";
import { Check, Clock3, History, Minus, X } from "lucide-react";
import { statusLabel } from "@/components/AppShell";
import type { ApprovalTaskDetail } from "@/lib/api";
import { formatShortDateTime } from "@/lib/dateFormat";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { formatPersonName } from "@/lib/personName";
import { reviewWorkflow, type ReviewStepState } from "@/lib/reviewPresentation";

type Translate = (key: TranslationKey) => string;
type Person = { given_name?: string | null; family_name?: string | null; display_name?: string; email?: string };
type Actors = { manager?: Person | null; owners?: Person[] };

/** Submitter, manager and owner names for an approval, from the request and the evidence manifest. */
export function approvalPeople(detail: ApprovalTaskDetail, locale: "zh" | "en", t: Translate) {
  const actors = (detail.evidence_manifest as { actors?: Actors } | null)?.actors;
  const submitter = formatPersonName({ given_name: detail.request.submitter_given_name, family_name: detail.request.submitter_family_name, display_name: detail.request.submitter_name }, locale)
    || detail.request.submitter_email || detail.request.submitter_id.slice(0, 8);
  const manager = actors?.manager
    ? formatPersonName(actors.manager, locale) || actors.manager.email || detail.task.assignee_user_id?.slice(0, 8) || t("approvalOwnerGroup")
    : detail.task.assignee_user_id?.slice(0, 8) ?? t("approvalOwnerGroup");
  const owners = actors?.owners?.map((owner) => formatPersonName(owner, locale) || owner.email || t("approvalProjectOwners")) ?? [t("approvalProjectOwners")];
  return { submitter, manager, owners };
}

export function approvalStageLabel(stage: string, t: Translate) {
  return stage === "owner_review" ? t("approvalStageOwnerReview") : t("approvalStageManagerReview");
}

type RouteState = ReviewStepState | "skipped";

function stateText(state: RouteState, t: Translate) {
  if (state === "complete") return t("approvalWorkflowApproved");
  if (state === "rejected") return t("statusReviewRejected");
  if (state === "cancelled") return t("approvalWorkflowCancelled");
  if (state === "current") return t("approvalWorkflowPendingReview");
  if (state === "skipped") return t("approvalRouteManagerSkipped");
  return t("approvalWorkflowNotStarted");
}

function StepIcon({ state }: { state: RouteState }) {
  if (state === "complete") return <Check aria-hidden="true" size={14} />;
  if (state === "rejected" || state === "cancelled") return <X aria-hidden="true" size={14} />;
  if (state === "current") return <Clock3 aria-hidden="true" size={14} />;
  if (state === "skipped") return <Minus aria-hidden="true" size={14} />;
  return null;
}

/**
 * CHG-495 C1 (K201): the two-stage route of this request — submitted, stage 1 manager, stage 2 project
 * owner, publish — with the latest decision time and comment (return reasons included) of each stage.
 * The four extraction stations stay on the document page. `showRecords` adds every review record.
 */
export function ApprovalRoute({ detail, showRecords = false }: { detail: ApprovalTaskDetail; showRecords?: boolean }) {
  const { locale, t, format } = useI18n();
  const titleId = useId();
  const people = approvalPeople(detail, locale, t);
  const workflow = reviewWorkflow(detail);
  const submittedAt = detail.request.submitted_at;
  const latest = (stage: string) => [...detail.review_records]
    .filter((record) => record.review_stage === stage && (!submittedAt || Date.parse(record.created_at) >= Date.parse(submittedAt)))
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  const recordNote = (stage: string) => {
    const record = latest(stage);
    if (!record) return null;
    const time = formatShortDateTime(record.created_at, locale);
    return record.comment ? format("approvalRouteComment", { time, comment: record.comment }) : time;
  };
  const managerSkipped = detail.request.review_route === "project_owner_fallback" && !latest("manager_review");
  const steps: Array<{ key: string; label: string; person: string; state: RouteState; note: string | null }> = [
    { key: "submitted", label: t("approvalRouteSubmitted"), person: people.submitter, state: "complete", note: formatShortDateTime(submittedAt, locale) },
    { key: "manager", label: t("approvalRouteManagerStage"), person: people.manager, state: managerSkipped ? "skipped" : workflow.manager, note: recordNote("manager_review") },
    { key: "owner", label: t("approvalRouteOwnerStage"), person: people.owners.join("、"), state: workflow.owner, note: recordNote("owner_review") ?? (workflow.owner === "complete" ? null : t("approvalRouteAnyOwnerNote")) },
    {
      key: "publish", label: t("publish"), person: t("submitReviewAuthorizedRole"), state: workflow.publish,
      note: workflow.publish === "complete" ? t("statusPublishedActive") : workflow.publish === "current" ? t("statusPublishing") : t("approvalWorkflowPublishAfterApproval")
    }
  ];
  const records = detail.review_records;
  return (
    <section aria-labelledby={titleId} className="approval-side-card approval-route-card">
      <h3 id={titleId}><History aria-hidden="true" size={16} />{t("approvalRouteTitle")}</h3>
      <ol aria-label={t("approvalFlow")} className="approval-route">
        {steps.map((step) => <li className={`approval-route-step is-${step.state}`} key={step.key}>
          <span className="approval-route-marker"><StepIcon state={step.state} /></span>
          <div>
            <small>{step.label}</small>
            <strong>{step.person}</strong>
            <span className="approval-route-state">{step.key === "submitted" ? t("approvalWorkflowSubmitted") : step.key === "publish" ? step.note : stateText(step.state, t)}</span>
            {step.note && step.key !== "publish" ? <span className="approval-route-note">{step.note}</span> : null}
          </div>
        </li>)}
      </ol>
      {showRecords ? <details className="approval-route-records">
        <summary>{format("approvalRouteAllRecords", { count: records.length })}</summary>
        <ol className="approval-history">
          {records.length ? records.map((record) => <li key={record.id}>
            <strong>{approvalStageLabel(record.review_stage, t)} · {record.status === "approved" ? t("approvalWorkflowApproved") : record.status === "rejected" ? t("statusReviewRejected") : statusLabel(record.status, t)}</strong>
            <p>{record.reviewer_id.slice(0, 8)} · {formatShortDateTime(record.created_at, locale)} · {record.comment || t("approvalNoComment")}</p>
          </li>) : <li><strong>{t("approvalNoLiveReviewHistory")}</strong><p>{t("approvalNoLiveReviewHistoryHelp")}</p></li>}
        </ol>
      </details> : null}
    </section>
  );
}
