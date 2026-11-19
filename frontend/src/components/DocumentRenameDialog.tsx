"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { Modal } from "@/components/Modal";
import { renameDocument, type ApiFetch, type DocumentSummary } from "@/lib/api";
import { documentTitleProblem, duplicateTitleDetails, duplicateTitleMessage, MAX_DOCUMENT_TITLE_LENGTH } from "@/lib/documentNames";
import { useI18n } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";

type DocumentRenameDialogProps = {
  apiFetch: ApiFetch;
  projectId: string;
  documentId: string;
  title: string;
  /** Original extension shown after the name; it cannot be edited (REN442-001). */
  extension: string;
  lockVersion: number;
  onClose: () => void;
  onRenamed: (summary: DocumentSummary) => void;
};

/** CHG-442 REN442-001/004: edit a document name; duplicates name the other project and its owners. */
export function DocumentRenameDialog({ apiFetch, projectId, documentId, title, extension, lockVersion, onClose, onRenamed }: DocumentRenameDialogProps) {
  const { t, format } = useI18n();
  const [draft, setDraft] = useState(title);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    const problem = documentTitleProblem(draft);
    if (problem) {
      setError(t(problem));
      return;
    }
    setSaving(true);
    setError("");
    try {
      onRenamed(await renameDocument(apiFetch, projectId, documentId, { lock_version: lockVersion, title: draft.trim() }));
    } catch (failure) {
      const details = failure && typeof failure === "object" && "code" in failure && failure.code === "document_title_duplicate" ? duplicateTitleDetails((failure as { details?: unknown }).details) : null;
      setError(details ? duplicateTitleMessage(details, t, format) : operationalErrorMessage(failure, t, format, "documentRenameFailed"));
    } finally {
      setSaving(false);
    }
  }

  const close = () => { if (!saving) onClose(); };
  return (
    <Modal aria-labelledby="document-rename-title" className="modal-panel modal-compact" onBackdropMouseDown={close} onEscape={close}>
      <div className="modal-header">
        <div><p className="eyebrow">{title}</p><h2 id="document-rename-title">{t("documentRenameTitle")}</h2></div>
        <button aria-label={t("documentRenameClose")} className="icon-button" disabled={saving} onClick={close} type="button"><X size={18} /></button>
      </div>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <label className="field-stack">
          <span>{t("documentRenameLabel")}</span>
          <span className="document-rename-field">
            <input aria-describedby="document-rename-help" autoFocus disabled={saving} maxLength={MAX_DOCUMENT_TITLE_LENGTH} onChange={(event) => { setDraft(event.target.value); setError(""); }} value={draft} />
            {extension ? <span className="document-rename-extension" title={t("documentRenameExtension")}>{extension}</span> : null}
          </span>
        </label>
        <small className="field-note" id="document-rename-help">{t("documentRenameHelp")}</small>
        {error ? <FeedbackMessage tone="error">{error}</FeedbackMessage> : null}
        <div className="modal-actions">
          <button className="action-button secondary" disabled={saving} onClick={close} type="button">{t("cancel")}</button>
          <button className="action-button" disabled={saving} type="submit">{saving ? t("documentRenameSaving") : t("save")}</button>
        </div>
      </form>
    </Modal>
  );
}
