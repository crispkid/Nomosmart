"use client";

import type { ChangeEvent, DragEvent } from "react";
import { CheckCircle2, FileDown, FileText, Upload, Wrench, X } from "lucide-react";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { useModalFocus } from "@/components/useModalFocus";
import type { ValidationRunResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import type { CsvValidationQuestion } from "./projectChatModel";

type ProjectChatBatchUploadDialogProps = {
  activeValidationRun: ValidationRunResponse | null;
  batchCompletedCount: number | null;
  canRetryFailedValidation: boolean;
  confirmBatchUpload: () => Promise<void>;
  downloadQuestionTemplate: () => void;
  dropUploadFile: (event: DragEvent<HTMLLabelElement>) => void;
  retryFailedValidationItems: () => Promise<void>;
  scopeIds: string[];
  selectUploadFile: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  setUploadDragging: (value: boolean) => void;
  setUploadOpen: (value: boolean) => void;
  uploadDialogRef: ReturnType<typeof useModalFocus>;
  uploadDragging: boolean;
  uploadError: string;
  uploadFileName: string;
  uploadQuestions: CsvValidationQuestion[];
  validationFinished: boolean;
};

/** CSV batch validation upload dialog (OPT424-038). */
export function ProjectChatBatchUploadDialog({ activeValidationRun, batchCompletedCount, canRetryFailedValidation, confirmBatchUpload, downloadQuestionTemplate, dropUploadFile, retryFailedValidationItems, scopeIds, selectUploadFile, setUploadDragging, setUploadOpen, uploadDialogRef, uploadDragging, uploadError, uploadFileName, uploadQuestions, validationFinished }: ProjectChatBatchUploadDialogProps) {
  const { t, format, localize } = useI18n();
  return (
    <div className="modal-backdrop" role="presentation">
      <section ref={uploadDialogRef} tabIndex={-1} aria-labelledby="project-batch-upload-title" aria-modal="true" className="modal-panel chat-small-modal batch-chat-modal" role="dialog">
        <div className="modal-header">
          <div><p className="eyebrow">{t("batchValidation")}</p><h2 id="project-batch-upload-title">{t("uploadTestConversations")}</h2></div>
          <button aria-label={t("close")} className="icon-button" onClick={() => setUploadOpen(false)} type="button"><X size={18} /></button>
        </div>
    
        {activeValidationRun ? <div className="batch-file-status"><Wrench size={17} /><span><strong>{format("documentChatValidationRun", { id: activeValidationRun.status })}</strong><small>{format("projectChatValidationRunProgress", { completed: activeValidationRun.completed_count + activeValidationRun.failed_count, total: activeValidationRun.total_count })}</small></span></div> : null}
        {validationFinished ? (
          <div className="batch-upload-complete"><CheckCircle2 size={24} /><div><strong>{t("batchCompleted")}</strong><span>{format("projectChatBatchCompletedHelp", { count: batchCompletedCount ?? uploadQuestions.length })}</span></div></div>
        ) : (
          <div className="batch-upload-body">
            <div className="batch-template-row">
              <div><strong>{t("csvTemplate")}</strong><small>question, expected_answer, expected_keywords, selected_document_ids, category, priority</small></div>
              <button className="action-button secondary" onClick={downloadQuestionTemplate} type="button"><FileDown size={16} /> {t("downloadTemplate")}</button>
            </div>
            <label
              className={`csv-upload-field${uploadDragging ? " is-dragging" : ""}`}
              onDragEnter={(event) => { event.preventDefault(); setUploadDragging(true); }}
              onDragLeave={(event) => { event.preventDefault(); setUploadDragging(false); }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={dropUploadFile}
            >
              <Upload size={24} />
              <span><strong>{t("selectCsvFile")}</strong><small>{t("projectChatCsvUploadHelp")}</small></span>
              <input accept=".csv,text/csv" onChange={selectUploadFile} type="file" />
            </label>
            {uploadFileName ? <div className="batch-file-status"><FileText size={17} /><span><strong>{uploadFileName}</strong><small>{uploadError ? localize(uploadError) : format("projectChatValidQuestionCount", { questions: uploadQuestions.length, documents: scopeIds.length })}</small></span></div> : null}
            {uploadError ? <FeedbackMessage tone="error">{localize(uploadError)}</FeedbackMessage> : null}
            {uploadQuestions.length ? <ol className="batch-question-preview">{uploadQuestions.slice(0, 3).map((value, index) => <li key={`${value.question}-${index}`}>{value.question}</li>)}{uploadQuestions.length > 3 ? <li>{format("projectChatMoreQuestions", { count: uploadQuestions.length - 3 })}</li> : null}</ol> : null}
          </div>
        )}
        <div className="modal-actions">
          <button className="action-button secondary" onClick={() => setUploadOpen(false)} type="button">{validationFinished ? t("close") : t("cancel")}</button>
          {canRetryFailedValidation ? <button className="action-button secondary" onClick={() => { void retryFailedValidationItems(); }} type="button">{t("projectChatRetryFailedQuestions")}</button> : null}
          {!activeValidationRun && !validationFinished ? <button className="action-button" disabled={!uploadQuestions.length || Boolean(uploadError)} onClick={confirmBatchUpload} type="button">{t("confirmUpload")}</button> : null}
        </div>
      </section>
    </div>
  );
}
