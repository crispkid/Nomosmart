"use client";

import { useCallback, useState } from "react";
import { RefreshCw, RotateCcw, UserRoundCog, X } from "lucide-react";
import { DataTable } from "@/components/DataTable";
import { DropdownSelect } from "@/components/DropdownSelect";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { Modal } from "@/components/Modal";
import { SettingsCard } from "@/components/SettingsCard";
import { useAuth } from "@/components/AuthProvider";
import { StateBadge } from "@/components/system/SystemUi";
import {
  listApprovalAdministrationTasks, listApprovalReviewerCandidates, reassignApprovalTask, returnApprovalTask,
  type ApprovalAdministrationPerson, type ApprovalAdministrationTask
} from "@/lib/api";
import { formatDateTime } from "@/lib/dateFormat";
import { useI18n } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { useReadResource } from "@/lib/useReadResource";

type Filter = "unattended" | "all" | "manager_review" | "owner_review";
type Action = { kind: "reassign" | "return"; task: ApprovalAdministrationTask };
const REASON_LIMIT = 500;

/** CHG-467 REVROUTE467-009..011: in-progress review tasks; reassign the manager stage or return a submission. */
export function ApprovalAdministrationPanel() {
  const { apiFetch, can } = useAuth();
  const { t, format, locale } = useI18n();
  const allowed = can("Approval", "ApprovalAdministration", "execute");
  const [filter, setFilter] = useState<Filter>("unattended");
  const [action, setAction] = useState<Action | null>(null);
  const [notice, setNotice] = useState("");
  const read = useCallback((signal: AbortSignal) => listApprovalAdministrationTasks(apiFetch, {
    unattended: filter === "unattended" ? true : undefined,
    reviewStage: filter === "manager_review" || filter === "owner_review" ? filter : undefined,
    limit: 200, signal
  }), [apiFetch, filter]);
  const tasks = useReadResource(read, `approval-administration:${filter}`, allowed, { keepData: true });
  if (!allowed) return null;

  const rows = tasks.data?.items ?? [];
  const stageLabel = (stage: string) => t(stage === "owner_review" ? "approvalAdministrationStageOwner" : "approvalAdministrationStageManager");
  return (
    <SettingsCard panel="administration" title={t("settingsApprovalAdministration")} description={t("approvalAdministrationHelp")}>
      <div className="system-toolbar compact approval-administration-toolbar">
        <label>
          <span>{t("approvalAdministrationFilter")}</span>
          <DropdownSelect aria-label={t("approvalAdministrationFilter")} value={filter} onChange={event => setFilter(event.target.value as Filter)}>
            <option value="unattended">{t("approvalAdministrationUnattended")}</option>
            <option value="all">{t("approvalAdministrationAll")}</option>
            <option value="manager_review">{t("approvalAdministrationStageManager")}</option>
            <option value="owner_review">{t("approvalAdministrationStageOwner")}</option>
          </DropdownSelect>
        </label>
        <button className="action-button secondary" onClick={() => tasks.reload()} type="button"><RefreshCw size={16} />{t("refresh")}</button>
      </div>
      {notice ? <FeedbackMessage tone="success">{notice}</FeedbackMessage> : null}
      {tasks.status === "error" ? <FeedbackMessage tone="error">{operationalErrorMessage(tasks.error, t, format, "approvalAdministrationLoadFailed")}</FeedbackMessage> : null}
      {tasks.status !== "loading" && !rows.length ? <p className="field-note">{t("approvalAdministrationEmpty")}</p> : null}
      {rows.length ? <DataTable rows={rows} rowKey={row => row.id} columns={[
        { key: "document", header: t("labelDocument"), cell: row => <><strong>{row.document_title}</strong><small>{row.project_name} · {row.version_label ?? "-"}</small></> },
        { key: "stage", header: t("approvalAdministrationStage"), className: "approval-administration-nowrap", cell: row => <><strong>{stageLabel(row.review_stage)}</strong>{row.review_route === "project_owner_fallback" ? <small>{t("submitReviewRouteWaived")}</small> : null}</> },
        { key: "reviewer", header: t("approvalAdministrationReviewer"), className: "approval-administration-nowrap", cell: row => row.unattended ? <StateBadge tone="coral">{t("approvalAdministrationUnattended")}</StateBadge> : row.assignee?.display_name ?? t("submitReviewAnyOwner") },
        { key: "submitter", header: t("approvalAdministrationSubmitter"), cell: row => <><strong>{row.submitter?.display_name ?? "-"}</strong><small>{formatDateTime(row.submitted_at, locale)}</small></> },
        { key: "actions", headerLabel: t("systemActionsColumn"), className: "approval-administration-nowrap", cell: row => <span className="system-row-actions">
          {row.review_stage === "manager_review" ? <button className="action-button secondary" onClick={() => { setNotice(""); setAction({ kind: "reassign", task: row }); }} type="button"><UserRoundCog size={15} />{t("approvalAdministrationReassign")}</button> : null}
          <button className="action-button danger" onClick={() => { setNotice(""); setAction({ kind: "return", task: row }); }} type="button"><RotateCcw size={15} />{t("approvalAdministrationReturn")}</button>
        </span> }
      ]} /> : null}
      {action ? <ApprovalAdministrationDialog action={action} onClose={() => setAction(null)} onDone={message => { setAction(null); setNotice(message); tasks.reload(); }} /> : null}
    </SettingsCard>
  );
}

function ApprovalAdministrationDialog({ action, onClose, onDone }: { action: Action; onClose: () => void; onDone: (message: string) => void }) {
  const { apiFetch } = useAuth();
  const { t, format } = useI18n();
  const [reason, setReason] = useState("");
  const [assignee, setAssignee] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const reassigning = action.kind === "reassign";
  const readCandidates = useCallback((signal: AbortSignal) => listApprovalReviewerCandidates(apiFetch, action.task.id, signal), [apiFetch, action.task.id]);
  const candidates = useReadResource<ApprovalAdministrationPerson[]>(readCandidates, `approval-candidates:${action.task.id}`, reassigning);

  async function submit() {
    if (!reason.trim()) { setError(t("approvalAdministrationReasonRequired")); return; }
    if (reassigning && !assignee) { setError(t("approvalAdministrationChooseReviewer")); return; }
    setSaving(true); setError("");
    try {
      if (reassigning) await reassignApprovalTask(apiFetch, action.task.id, { assignee_user_id: assignee, reason: reason.trim(), lock_version: action.task.lock_version });
      else await returnApprovalTask(apiFetch, action.task.id, { reason: reason.trim(), lock_version: action.task.lock_version });
      onDone(t(reassigning ? "approvalAdministrationReassigned" : "approvalAdministrationReturned"));
    } catch (failure) {
      setError(operationalErrorMessage(failure, t, format, "approvalAdministrationActionFailed"));
    } finally {
      setSaving(false);
    }
  }

  const close = () => { if (!saving) onClose(); };
  const titleId = "approval-administration-dialog-title";
  return (
    <Modal aria-labelledby={titleId} className="modal-panel modal-compact" onBackdropMouseDown={close} onEscape={close}>
      <div className="modal-header">
        <div><p className="eyebrow">{action.task.document_title}</p><h2 id={titleId}>{t(reassigning ? "approvalAdministrationReassign" : "approvalAdministrationReturn")}</h2></div>
        <button aria-label={t("close")} className="icon-button" disabled={saving} onClick={close} type="button"><X size={18} /></button>
      </div>
      <form onSubmit={event => { event.preventDefault(); void submit(); }}>
        <p className="field-note">{t(reassigning ? "approvalAdministrationReassignHelp" : "approvalAdministrationReturnHelp")}</p>
        {reassigning ? <label className="field-stack">
          <span>{t("approvalAdministrationNewReviewer")}</span>
          <DropdownSelect disabled={saving || candidates.status === "loading"} onChange={event => { setAssignee(event.target.value); setError(""); }} value={assignee}>
            <option value="">{candidates.status === "loading" ? t("notificationLoading") : t("approvalAdministrationChooseReviewer")}</option>
            {(candidates.data ?? []).map(person => <option key={person.id} value={person.id}>{person.display_name}</option>)}
          </DropdownSelect>
          {candidates.status === "ready" && !(candidates.data ?? []).length ? <small className="field-note">{t("approvalAdministrationNoCandidates")}</small> : null}
        </label> : null}
        <label className="field-stack">
          <span>{t("approvalAdministrationReason")}</span>
          <textarea disabled={saving} maxLength={REASON_LIMIT} onChange={event => { setReason(event.target.value); setError(""); }} rows={3} value={reason} />
        </label>
        {error ? <FeedbackMessage tone="error">{error}</FeedbackMessage> : null}
        <div className="modal-actions">
          <button className="action-button secondary" disabled={saving} onClick={close} type="button">{t("cancel")}</button>
          <button className={`action-button${reassigning ? "" : " danger"}`} disabled={saving} type="submit">{saving ? t("approvalAdministrationSaving") : t(reassigning ? "approvalAdministrationReassign" : "approvalAdministrationReturn")}</button>
        </div>
      </form>
    </Modal>
  );
}
