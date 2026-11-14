"use client";

import { useState } from "react";
import { AlertTriangle, ArrowRight, X } from "lucide-react";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { useModalFocus } from "@/components/useModalFocus";
import type { useFeedback } from "@/components/FeedbackProvider";
import { getDocumentLifecycleImpact, updateDocumentLifecycle } from "@/lib/api";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { UiValidationError } from "@/lib/transportError";
import type { useDocumentList } from "@/lib/useDocumentList";
import { documentStatusLabel, liveDocumentFromSummary, type DocumentItem, type PendingStatusChange } from "./importDocumentModel";
import type { ImportPageDeps } from "./pageDeps";

type DocumentList = ReturnType<typeof useDocumentList>;
/** Page dependencies shared with the document lifecycle status actions. */
export type StatusChangeDeps = Pick<ImportPageDeps, "apiFetch" | "format" | "params" | "t"> & Pick<DocumentList, "setCreatedImports" | "setLiveDocuments"> & {
  canEditLifecycle: boolean;
  notify: ReturnType<typeof useFeedback>["notify"];
};
type StatusChangeViewDeps = Pick<ImportPageDeps, "t"> & { localize: (message: string) => string };

export type StatusChangeState = ReturnType<typeof useStatusChangeState>;

/** Document lifecycle status change state (split from the project import page, OPT424-038). */
export function useStatusChangeState() {
  const [committedStatuses, setCommittedStatuses] = useState<Record<string, string>>({});
  const [pendingStatusChange, setPendingStatusChange] = useState<PendingStatusChange | null>(null);
  const [statusSubmitting, setStatusSubmitting] = useState(false);
  const [statusError, setStatusError] = useState("");

  // D424-18: Esc, focus trap and focus return for the lifecycle warning.
  const statusDialogRef = useModalFocus(Boolean(pendingStatusChange), () => { if (!statusSubmitting) setPendingStatusChange(null); });
  return { committedStatuses, setCommittedStatuses, pendingStatusChange, setPendingStatusChange, statusSubmitting, setStatusSubmitting, statusError, setStatusError, statusDialogRef };
}

/** Document lifecycle status actions, created each render once page dependencies exist. */
export function createStatusChangeActions(state: StatusChangeState, deps: StatusChangeDeps) {
  const { apiFetch, format, params, t, canEditLifecycle, notify, setCreatedImports, setLiveDocuments } = deps;
  const { setCommittedStatuses, pendingStatusChange, setPendingStatusChange, statusSubmitting, setStatusSubmitting, setStatusError } = state;

  function impactSummaryProjects(referenceCount: number, activeVersionCount: number) {
    const summary = [];
    if (referenceCount > 0) summary.push(format("projectImportImpactReferences", { count: referenceCount }));
    if (activeVersionCount > 0) summary.push(format("projectImportImpactActiveVersions", { count: activeVersionCount }));
    return summary;
  }

  async function requestStatusChange(document: DocumentItem, requestedStatus: string, currentStatus: string) {
    if (requestedStatus === currentStatus) return;
    setStatusError("");
    if (requestedStatus === "inactive" || requestedStatus === "deleted") {
      const baseChange: PendingStatusChange = { documentId: document.id, documentTitle: document.title, from: currentStatus, to: requestedStatus, projects: document.impactedProjects, isLive: Boolean("isLive" in document && document.isLive), lockVersion: "lockVersion" in document ? document.lockVersion : undefined, requiresConfirmation: true };
      setPendingStatusChange(baseChange);
      if ("isLive" in document && document.isLive) {
        try {
          const impact = await getDocumentLifecycleImpact(apiFetch, params.id, document.id, requestedStatus);
          setPendingStatusChange((current) => current?.documentId === document.id && current.to === requestedStatus ? { ...current, projects: impactSummaryProjects(impact.impacted_reference_count, impact.impacted_active_version_count), requiresConfirmation: impact.requires_confirmation } : current);
        } catch (error) {
          setStatusError(operationalErrorMessage(error, t, format, "projectImportImpactLoadFailed"));
        }
      }
      return;
    }
    if ("isLive" in document && document.isLive) {
      if (!canEditLifecycle) {
        setStatusError(t("projectImportMissingLifecyclePermission"));
        return;
      }
      if (!("lockVersion" in document) || document.lockVersion === undefined) {
        setStatusError(t("projectImportMissingLockVersion"));
        return;
      }
      setStatusSubmitting(true);
      try {
        const updated = await updateDocumentLifecycle(apiFetch, params.id, document.id, { lock_version: document.lockVersion, status: requestedStatus, impact_confirmed: false, reason: "lifecycle update from project document list" });
        setLiveDocuments((current) => current.map((item) => item.id === document.id ? liveDocumentFromSummary(updated, t) : item));
        setCreatedImports((current) => current.map((item) => item.id === document.id ? liveDocumentFromSummary(updated, t) : item));
        setCommittedStatuses((current) => {
          const next = { ...current };
          delete next[document.id];
          return next;
        });
        if (currentStatus === "inactive" && requestedStatus === "active") {
          notify({ id: crypto.randomUUID(), scope: `project:${params.id}`, tone: "success", title: "projectImportReactivatedTitle", reason: "projectImportReactivatedMessage" });
        }
      } catch (error) {
        setStatusError(operationalErrorMessage(error, t, format, "projectImportStatusUpdateFailed"));
      } finally {
        setStatusSubmitting(false);
      }
      return;
    }
    setCommittedStatuses((current) => ({ ...current, [document.id]: requestedStatus }));
  }

  async function confirmStatusChange() {
    if (!canEditLifecycle || !pendingStatusChange || statusSubmitting) return;
    const change = pendingStatusChange;
    setStatusSubmitting(true);
    setStatusError("");
    if (change.isLive) {
      try {
        if (change.lockVersion === undefined) throw new UiValidationError("projectImportMissingLockVersion");
        const updated = await updateDocumentLifecycle(apiFetch, params.id, change.documentId, { lock_version: change.lockVersion, status: change.to, impact_confirmed: change.requiresConfirmation, reason: change.to === "deleted" ? "soft delete from project document list" : "lifecycle update from project document list" });
        if (change.to === "deleted" || updated.status === "deleted") {
          setLiveDocuments((current) => current.filter((item) => item.id !== change.documentId));
          setCreatedImports((current) => current.filter((item) => item.id !== change.documentId));
        } else {
          setLiveDocuments((current) => current.map((item) => item.id === change.documentId ? liveDocumentFromSummary(updated, t) : item));
          setCreatedImports((current) => current.map((item) => item.id === change.documentId ? liveDocumentFromSummary(updated, t) : item));
        }
        setCommittedStatuses((current) => {
          const next = { ...current };
          delete next[change.documentId];
          return next;
        });
        setPendingStatusChange(null);
      } catch (error) {
        setStatusError(error instanceof Error && !(`status` in error) ? t("projectImportMissingLockVersion") : operationalErrorMessage(error, t, format, "projectImportStatusUpdateFailed"));
      } finally {
        setStatusSubmitting(false);
      }
      return;
    }
    window.setTimeout(() => {
      if (change.to === "deleted") {
        setCreatedImports((current) => current.filter((item) => item.id !== change.documentId));
      } else {
        setCommittedStatuses((current) => ({ ...current, [change.documentId]: change.to }));
      }
      setStatusSubmitting(false);
      setPendingStatusChange(null);
    }, 300);
  }

  return { requestStatusChange, confirmStatusChange };
}

export type StatusChangeActions = ReturnType<typeof createStatusChangeActions>;

/** Document lifecycle impact dialog: JSX moved verbatim from the project import page (OPT424-038). */
export function createStatusChangeView(state: StatusChangeState, actions: StatusChangeActions, deps: StatusChangeViewDeps) {
  const { pendingStatusChange, setPendingStatusChange, statusSubmitting, statusError, statusDialogRef } = state;
  const { confirmStatusChange } = actions;

  function renderStatusChangeModal() {
    const { localize, t } = deps;
    return (
      <>
      {pendingStatusChange ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !statusSubmitting) setPendingStatusChange(null);
          }}
          role="presentation"
        >
          <section ref={statusDialogRef} tabIndex={-1} aria-labelledby="status-change-title" aria-modal="true" className="modal-panel warning-modal" role="alertdialog">
            <div className="modal-header">
              <div><p className="eyebrow">{t("projectImportImpactWarning")}</p><h2 id="status-change-title">{pendingStatusChange.to === "inactive" ? t("projectImportDisableDocument") : t("projectImportDeleteDocument")}</h2></div>
              <button aria-label={t("projectImportCloseLifecycleWarning")} className="icon-button" disabled={statusSubmitting} onClick={() => setPendingStatusChange(null)} type="button"><X size={18} /></button>
            </div>
	            <div className="warning-body"><AlertTriangle size={24} /><div><strong>{pendingStatusChange.documentTitle}</strong><small>{t("projectImportLifecycleWarningHelp")}</small></div></div>
	            {statusError ? <FeedbackMessage tone="error"> {localize(statusError)}</FeedbackMessage> : null}
	            <div className="status-change-preview">
              <span><small>{t("projectImportCurrentStatus")}</small><strong>{documentStatusLabel(pendingStatusChange.from, t)}</strong></span>
              <ArrowRight size={18} />
              <span><small>{t("projectImportPendingStatus")}</small><strong>{documentStatusLabel(pendingStatusChange.to, t)}</strong></span>
            </div>
            <div className="impacted-projects">
              {pendingStatusChange.projects.length ? pendingStatusChange.projects.map((project) => <span key={project}>{project}</span>) : <span>{t("projectImportNoReferenceProjects")}</span>}
            </div>
            <div className="modal-actions"><button className="action-button secondary" disabled={statusSubmitting} onClick={() => setPendingStatusChange(null)} type="button">{t("cancel")}</button><button className="action-button danger" disabled={statusSubmitting} onClick={confirmStatusChange} type="button">{statusSubmitting ? t("projectImportSubmitting") : t("projectImportConfirmContinue")}</button></div>
          </section>
        </div>
      ) : null}
      </>
    );
  }

  return { renderStatusChangeModal };
}
