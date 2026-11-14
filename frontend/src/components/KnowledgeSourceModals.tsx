"use client";

import { isNativeOcrModel } from "@/lib/nativeOcrModels";
import { DropdownSelect } from "@/components/DropdownSelect";
import { FeedbackConfirm } from "./FeedbackConfirm";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { Modal } from "@/components/Modal";
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useUploadWaitState } from "@/lib/useUploadWaitState";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, ChevronRight, FileText, LoaderCircle, RotateCcw, ShieldCheck, Trash2, UploadCloud, X } from "lucide-react";
import type { AIModelResponse } from "@/lib/api";
import { ocrRetryBlocked, ocrRetryBlockReasonKey, ocrFailureTone } from "@/lib/ocrPresentation";
import { formatCount } from "@/lib/numberFormat";
import { OCRBudgetStatus } from "@/components/OCRBudgetStatus";
import { ChunkingIssueSummary } from "@/components/ChunkingIssueSummary";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { DEFAULT_MAX_UPLOAD_BYTES, UPLOAD_REASON_EMPTY, UPLOAD_REASON_READY, UPLOAD_REASON_TOO_LARGE, UPLOAD_REASON_UNSUPPORTED, documentExtension, formatFileSize, validateFileDescriptor } from "@/lib/knowledgeImport";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";
import { runtimeConfig } from "@/lib/runtimeConfig";
import { UploadProgressBar } from "@/components/UploadProgressBar";
import { confirmedPipelinePercent, confirmedUploadResults, UploadAttemptGuard, uploadOutcomeUnknown, uploadWaitNoticeMs, type UploadBatchResult } from "@/lib/uploadProgress";
import type { CreatedKnowledgeDocument } from "./knowledgeSource/knowledgeSourceTypes";

export { DEFAULT_MAX_UPLOAD_BYTES } from "@/lib/knowledgeImport";
export type { SourceState, PipelineStatus, ServiceSource, ReferenceSource, CreatedKnowledgeDocument } from "./knowledgeSource/knowledgeSourceTypes";
export { DataServiceModal, type DataServicePayload } from "./knowledgeSource/DataServiceModal";

type UploadResult = { name: string; ok: boolean; reason: string };
type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;
type UploadProgressStatus = "completed" | "running" | "waiting" | "failed";
type UploadProgressStep = { id: string; label: string; status: UploadProgressStatus; progress: number | null; detail?: string };

const CANONICAL_UPLOAD_PIPELINE_STEPS = [
  "upload_received",
  "parse_document",
  "ocr_extract",
  "split_paragraphs",
  "chunk_knowledge",
  "generate_markdown",
  "auto_tag",
  "build_embeddings",
  "build_staging_index",
  "build_graph_preview",
  "prepare_submission"
] as const;

export function validateUploadFile(file: File, maxBytes = DEFAULT_MAX_UPLOAD_BYTES): UploadResult {
  return validateFileDescriptor(file, maxBytes);
}

function localizeUploadReason(reason: string, t: Translate, format: Format, maxUploadMb: number) {
  if (reason === UPLOAD_REASON_UNSUPPORTED) return t("uploadReasonUnsupported");
  if (reason === UPLOAD_REASON_TOO_LARGE) return format("uploadReasonTooLargeDynamic", { size: formatCount(maxUploadMb) });
  if (reason === UPLOAD_REASON_EMPTY) return t("uploadReasonEmpty");
  if (reason === UPLOAD_REASON_READY) return t("uploadReady");
  if (reason.startsWith("server:")) return operationalCodeMessage(reason.slice(7), t, format, "apiGenericError");
  return reason;
}

function uploadPipelineStepLabel(stepName: string, t: Translate) {
  const labels: Record<string, TranslationKey> = {
    upload_received: "knowledgeDetailStepUploadReceived",
    file_scan: "knowledgeDetailStepFileScan",
    parse_document: "knowledgeDetailStepParseDocument",
    ocr_extract: "knowledgeDetailStepOcrExtract",
    split_paragraphs: "knowledgeDetailStepSplitParagraphs",
    chunk_knowledge: "knowledgeDetailStepChunkKnowledge",
    generate_markdown: "knowledgeDetailStepGenerateMarkdown",
    auto_tag: "knowledgeDetailStepAutoTag",
    build_embeddings: "knowledgeDetailStepBuildEmbeddings",
    build_staging_index: "knowledgeDetailStepBuildStagingIndex",
    build_graph_preview: "knowledgeDetailStepBuildGraphPreview",
    prepare_submission: "knowledgeDetailStepPrepareSubmission",
    manager_review: "knowledgeDetailStepManagerReview", owner_review: "knowledgeDetailStepOwnerReview",
    publish: "knowledgeDetailStepPublish", production_index: "knowledgeDetailStepProductionIndex", graph_sync: "knowledgeDetailStepGraphSync"
  };
  return labels[stepName] ? t(labels[stepName]) : stepName.replaceAll("_", " ");
}

function uploadStepStatusLabel(status: UploadProgressStatus | string, t: Translate) {
  const labels: Record<string, TranslationKey> = {
    completed: "projectImportStepStatusCompleted",
    running: "projectImportStepStatusRunning",
    waiting: "projectImportStepStatusWaiting",
    queued: "projectImportStepStatusQueued",
    pending: "projectImportStepStatusPending",
    failed: "projectImportStepStatusFailed",
    skipped: "projectImportStepStatusSkipped"
  };
  const key = labels[status];
  return key ? t(key) : status.replaceAll("_", " ");
}

function normalizeUploadStepStatus(status: string): UploadProgressStatus {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "running") return "running";
  return "waiting";
}

function uploadExtractionReady(document: CreatedKnowledgeDocument | undefined) {
  return document?.pipeline.status === "submission_ready";
}

function uploadFailedStep(document: CreatedKnowledgeDocument | undefined) {
  return document?.pipeline.steps?.find((step) => step.status === "failed") ?? null;
}

function uploadExtractionFailed(document: CreatedKnowledgeDocument | undefined) {
  return document?.pipeline.status === "failed" || Boolean(uploadFailedStep(document));
}

type UploadFilesModalProps = {
  canSubmit?: boolean;
  onObservationEnd?: () => void;
  initialFiles?: File[];
  maxUploadBytes?: number;
  ocrModels?: AIModelResponse[];
  onClose: () => void;
  onCreate: (documents: CreatedKnowledgeDocument[], autoExtractionId?: string) => void;
  onRetryPipeline?: (document: CreatedKnowledgeDocument, onProgressDocument?: (document: CreatedKnowledgeDocument) => void) => Promise<CreatedKnowledgeDocument>;
  onUploadFiles?: (files: File[], options: { ocrModelId: string | null; startExtraction: boolean }, onProgressDocuments?: (documents: CreatedKnowledgeDocument[]) => void) => Promise<UploadBatchResult<CreatedKnowledgeDocument>>;
};

export function UploadFilesModal({ canSubmit = true, onObservationEnd, initialFiles = [], maxUploadBytes = DEFAULT_MAX_UPLOAD_BYTES, ocrModels = [], onClose, onCreate, onRetryPipeline, onUploadFiles }: UploadFilesModalProps) {
  const { t, format, localize, locale } = useI18n();
  const [files, setFiles] = useState<File[]>(() => initialFiles);
  const [results, setResults] = useState<UploadResult[] | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [outcomeUnknown, setOutcomeUnknown] = useState(false);
  const attempts = useRef(new UploadAttemptGuard());
  const waitNoticeMs = uploadWaitNoticeMs(runtimeConfig().uploadWaitNoticeMs);
  const { canReturn, progressStalled, begin: beginWait, progress: noteProgress, finish: finishWait, reset: resetWait } = useUploadWaitState(waitNoticeMs);
  const [progressDetailsOpen, setProgressDetailsOpen] = useState(false);
  const [liveProgressDocuments, setLiveProgressDocuments] = useState<CreatedKnowledgeDocument[]>([]);
  const [discardOpen, setDiscardOpen] = useState(false);
  const nativeOcrModels = ocrModels.filter(isNativeOcrModel);
  const defaultOcr = nativeOcrModels.find((model) => model.is_default) ?? nativeOcrModels[0];
  const [ocrModelId, setOcrModelId] = useState<string | null>(() => defaultOcr?.id ?? null);
  const [submitError, setSubmitError] = useState("");
  const [retryingPipeline, setRetryingPipeline] = useState(false);
  const maxUploadMb = Math.max(1, Math.round(maxUploadBytes / 1024 / 1024));
  const validation = useMemo(() => files.map((file) => validateUploadFile(file, maxUploadBytes)), [files, maxUploadBytes]);
  const validCount = validation.filter((item) => item.ok).length;
  const hasUnsavedSelection = files.length > 0 && !results;
  const resolvedOcrModelId = nativeOcrModels.some((model) => model.id === ocrModelId) ? ocrModelId : defaultOcr?.id ?? null;
  const autoExtractCandidate = files.length === 1 && validCount === 1;
  const liveProgressDocument = liveProgressDocuments.find((document) => document.pipeline.steps?.length) ?? liveProgressDocuments[0];
  const failedAutoExtraction = autoExtractCandidate && uploadExtractionFailed(liveProgressDocument);
  const pendingAutoExtraction = autoExtractCandidate && Boolean(liveProgressDocument) && !uploadExtractionReady(liveProgressDocument) && !failedAutoExtraction && Boolean(results);
  const modalLocked = retryingPipeline || submitting || outcomeUnknown;
  const canLeaveWaiting = canReturn || outcomeUnknown || Boolean(liveProgressDocument?.pipeline.observationInterrupted);

  useEffect(() => {
    const guard = attempts.current;
    return () => { guard.invalidate(); finishWait(); onObservationEnd?.(); };
  }, [finishWait, onObservationEnd]);

  // D424-18: Esc keeps the original close rules; the hook adds focus trap and return.

  function leaveWaiting() {
    attempts.current.leave();
    finishWait();
    onClose();
  }

  function requestClose() {
    if (canLeaveWaiting) { leaveWaiting(); return; }
    if (modalLocked) return;
    if (hasUnsavedSelection) setDiscardOpen(true);
    else onClose();
  }

  function selectFiles(nextFiles: File[]) {
    if (modalLocked) return;
    setFiles(nextFiles);
    setResults(null);
    setSubmitError("");
    resetWait();
    setOutcomeUnknown(false);
    setLiveProgressDocuments([]);
    setProgressDetailsOpen(false);
    setRetryingPipeline(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    if (modalLocked) return;
    setDragging(false);
    selectFiles(Array.from(event.dataTransfer.files));
  }

  async function submit() {
    if (!canSubmit || !files.length || submitting || outcomeUnknown || !onUploadFiles || attempts.current.isPending()) return;
    const attempt = attempts.current.begin();
    beginWait(attempt);
    setSubmitting(true);
    setLiveProgressDocuments([]);
    setSubmitError("");
    const checked = files.map((file) => validateUploadFile(file, maxUploadBytes));
    const validFiles = files.filter((_, index) => checked[index].ok);
    const autoExtract = files.length === 1 && validFiles.length === 1;
    try {
      const batch = await onUploadFiles(validFiles, { ocrModelId: resolvedOcrModelId, startExtraction: autoExtract }, (documents) => {
        if (!attempts.current.canPresent(attempt)) return;
        noteProgress(attempt);
        setLiveProgressDocuments(documents);
      });
      if (!attempts.current.canPresent(attempt)) return;
      const documents = batch.documents;
      setResults(confirmedUploadResults(checked, batch.receipts));
      const autoExtractionId = autoExtract && uploadExtractionReady(documents[0]) ? documents[0]?.id : undefined;
      onCreate(documents, autoExtractionId);
      if (autoExtractionId) onClose();
    } catch (error) {
      if (!attempts.current.canPresent(attempt)) return;
      const unknown = uploadOutcomeUnknown(error);
      setOutcomeUnknown(unknown);
      setSubmitError(unknown ? t("uploadOutcomeUnknown") : operationalErrorMessage(error, t, format, "uploadRejected"));
    } finally {
      if (attempts.current.canPresent(attempt)) setSubmitting(false);
      attempts.current.finish(attempt);
      finishWait(attempt);
    }
  }

  async function retryFailedAutoExtraction() {
    if (!canSubmit || !liveProgressDocument || !onRetryPipeline || retryingPipeline || attempts.current.isPending()) return;
    const attempt = attempts.current.begin();
    beginWait(attempt);
    setRetryingPipeline(true);
    setSubmitError("");
    try {
      const document = await onRetryPipeline(liveProgressDocument, (progressDocument) => {
        if (attempts.current.canPresent(attempt)) { noteProgress(attempt); setLiveProgressDocuments([progressDocument]); }
      });
      if (!attempts.current.canPresent(attempt)) return;
      setLiveProgressDocuments([document]);
      onCreate([document], uploadExtractionReady(document) ? document.id : undefined);
      if (uploadExtractionReady(document)) onClose();
    } catch (error) {
      if (!attempts.current.canPresent(attempt)) return;
      if (uploadOutcomeUnknown(error)) setLiveProgressDocuments((documents) => documents.map((document) => ({ ...document, pipeline: { ...document.pipeline, observationInterrupted: true } })));
      setSubmitError(operationalErrorMessage(error, t, format, "knowledgeDetailRetryFailed"));
    } finally {
      if (attempts.current.canPresent(attempt)) { setRetryingPipeline(false); setSubmitting(false); }
      attempts.current.finish(attempt);
      finishWait(attempt);
    }
  }

  const showSubmitOverlay = submitting || retryingPipeline || failedAutoExtraction || pendingAutoExtraction || outcomeUnknown;
  const overlayFailed = failedAutoExtraction && !retryingPipeline;
  const failedStep = uploadFailedStep(liveProgressDocument);
  const livePipelineSteps = liveProgressDocument?.pipeline.steps ?? [];
  const localProgressSteps: UploadProgressStep[] = [
    { id: "validate", label: t("uploadLocalValidation"), status: "completed", progress: 100 },
    { id: "upload", label: t("uploadAwaitingConfirmation"), status: liveProgressDocument ? "completed" : "waiting", progress: liveProgressDocument ? 100 : null },
    { id: "create-document", label: t("uploadProgressCreateDocument"), status: liveProgressDocument?.id && liveProgressDocument.latestVersionId ? "completed" : "waiting", progress: liveProgressDocument?.latestVersionId ? 100 : null },
    { id: "create-pipeline", label: t("uploadProgressCreatePipeline"), status: liveProgressDocument?.pipeline.id ? "completed" : "waiting", progress: liveProgressDocument?.pipeline.id ? 100 : null }
  ];
  const waitingPipelineSteps: UploadProgressStep[] = autoExtractCandidate && !livePipelineSteps.length
    ? CANONICAL_UPLOAD_PIPELINE_STEPS.map((name) => ({ id: name, label: uploadPipelineStepLabel(name, t), status: "waiting", progress: 0, detail: t("uploadProgressWaitingLivePipeline") }))
    : [];
  const uploadProgressSteps: UploadProgressStep[] = livePipelineSteps.length
    ? livePipelineSteps.map((step) => ({
        id: step.name,
        label: uploadPipelineStepLabel(step.name, t),
        status: normalizeUploadStepStatus(step.status),
        progress: step.ocr?.input_mode === "native_pdf" && step.status !== "completed" ? null : Math.min(100, Math.max(0, Math.round(step.progress))),
        detail: step.error || step.artifactRef || format("projectImportRetryCount", { count: formatCount(step.retryCount, locale) })
      }))
    : [...localProgressSteps, ...waitingPipelineSteps];
  const uploadStatus = outcomeUnknown ? t("uploadOutcomeUnknown") : livePipelineSteps.length ? (liveProgressDocument?.pipeline.currentStep || t("uploadProgressWaitingLivePipeline")) : t(liveProgressDocument ? "uploadAcceptedAwaitingProgress" : "uploadAwaitingConfirmation");
  const nativePending = livePipelineSteps.some(step => step.ocr?.input_mode === "native_pdf" && step.status !== "completed");
  const uploadDisplayProgress = nativePending ? null : confirmedPipelinePercent(liveProgressDocument?.pipeline);
  const completedStepCount = uploadProgressSteps.filter((step) => step.status === "completed").length;

  return <Modal onEscape={() => requestClose()} onBackdropMouseDown={() => requestClose()} aria-busy={submitting || retryingPipeline} aria-labelledby="upload-files-title" className={`modal-panel source-modal optimized-source-modal${modalLocked ? " source-modal-locked" : ""}`}>
      <header className="source-modal-header"><div><p className="eyebrow">{t("uploadModalEyebrow")}</p><h2 id="upload-files-title">{t("uploadModalTitle")}</h2><small>{t("uploadModalHelp")}</small></div><button aria-label={t("uploadModalClose")} className="icon-button" disabled={modalLocked && !canLeaveWaiting} onClick={requestClose} type="button"><X size={18} /></button></header>
      <div className="source-modal-body">
        <div className="upload-rule-chips" aria-label={t("uploadRules")}><span><FileText size={14} /> {t("uploadSupportedFormats")}</span><span><ShieldCheck size={14} /> {format("uploadMaxSizeDynamic", { size: formatCount(maxUploadMb, locale) })}</span></div>
        {files.some((file) => documentExtension(file.name).toLowerCase() === "pdf") ? <section className="upload-ocr-panel">
          <label><span>{t("uploadOcrModel")}</span><DropdownSelect disabled={modalLocked || nativeOcrModels.length === 0} onChange={(event) => setOcrModelId(event.target.value || null)} value={resolvedOcrModelId ?? ""}><option value="">{nativeOcrModels.length ? t("uploadUseDefaultOcr") : t("uploadNoOcrModel")}</option>{nativeOcrModels.map((model) => <option key={model.id} value={model.id}>{model.name}{model.is_default ? t("uploadDefaultSuffix") : ""}</option>)}</DropdownSelect></label>
          <small>{t("uploadNativePdfHelp")}</small><small>{t("uploadNativePdfCostNotice")}</small>
        </section> : null}
        <label className={`source-file-drop source-file-drop-primary ${dragging ? "dragging" : ""}`} onDragEnter={() => { if (!modalLocked) setDragging(true); }} onDragLeave={() => setDragging(false)} onDragOver={(event) => event.preventDefault()} onDrop={handleDrop} tabIndex={modalLocked ? -1 : 0}>
          <span className="upload-drop-icon"><UploadCloud size={30} /></span><strong>{t("uploadDropTitle")}</strong><small>{t("uploadDropHelp")}</small><em>{t("uploadSelectFiles")}</em>
          <input accept=".pdf,.txt,.md,.markdown" disabled={modalLocked} multiple onChange={(event) => selectFiles(Array.from(event.target.files ?? []))} type="file" />
        </label>
        <div className={`upload-behavior-callout ${files.length > 1 ? "batch" : "single"}`}><span>{files.length > 1 ? <FileText size={18} /> : <ArrowRight size={18} />}</span><div><strong>{files.length > 1 ? t("uploadBatchTitle") : t("uploadSingleTitle")}</strong><small>{files.length > 1 ? t("uploadBatchHelp") : t("uploadSingleHelp")}</small></div></div>
        {files.length ? <section className="upload-files-section"><div className="upload-files-heading"><div><strong>{results ? t("uploadResults") : t("uploadSelectedFiles")}</strong><small>{format("uploadValidationSummary", { files: files.length, valid: validCount })}</small></div>{!results ? <button aria-label={format("uploadClearAllLabel", { count: files.length })} className="clear-all-files-button" disabled={modalLocked} onClick={() => selectFiles([])} type="button"><Trash2 size={16} /> {t("uploadClearAll")}</button> : null}</div><div className="upload-selection-list optimized-upload-list">{(results ?? validation).map((item, index) => { const file = files[index]; const extension = documentExtension(file.name).toUpperCase(); return <div className={item.ok ? "valid" : "invalid"} key={`${item.name}-${index}`}><span className="file-type-badge">{extension}</span><span className="upload-file-identity"><strong title={item.name}>{item.name}</strong><small>{formatFileSize(file.size)} · {localizeUploadReason(item.reason, t, format, maxUploadMb)}</small></span><span className="upload-file-status">{item.ok ? <><CheckCircle2 size={16} /> {results ? t("uploadAdded") : t("uploadReady")}</> : <><AlertTriangle size={16} /> {t("uploadFailed")}</>}</span></div>; })}</div></section> : null}
        {results ? <div aria-live="polite" className="upload-result-summary optimized-result-summary">{results.some((item) => !item.ok) ? <AlertTriangle size={20} /> : <CheckCircle2 size={20} />}<div><strong>{t("uploadResultTitle")}</strong><span>{format("uploadResultCounts", { success: results.filter((item) => item.ok).length, failed: results.filter((item) => !item.ok).length })}</span><small>{t("uploadResultHelp")}</small></div></div> : null}
        {submitError ? <div className="upload-result-summary upload-error-summary" role="alert"><AlertTriangle size={20} /><div><strong>{t("uploadIncomplete")}</strong><small>{localize(submitError)}</small></div></div> : null}
      </div>
<footer className="source-modal-footer"><small>{!results && files.length ? format("uploadWillProcess", { count: formatCount(validCount, locale) }) : results ? t("uploadResultsKept") : t("uploadNoFilesSelected")}</small><div><button className="action-button secondary" disabled={modalLocked && !canLeaveWaiting} onClick={requestClose} type="button">{canLeaveWaiting ? t("uploadCloseToProject") : results ? t("complete") : t("cancel")}</button>{!results ? <button className="action-button" disabled={!canSubmit || !files.length || validCount === 0 || modalLocked || !onUploadFiles} onClick={submit} type="button">{submitting ? <LoaderCircle className="spin" size={16} /> : <UploadCloud size={16} />} {files.length > 1 ? format("uploadValidFiles", { count: formatCount(validCount, locale) }) : t("uploadAndExtract")}</button> : null}</div></footer>
      {showSubmitOverlay ? <div aria-live="assertive" className={`upload-submit-overlay${overlayFailed ? " failed" : ""}`} role="status">
        <div className="upload-submit-card">
          <span className="upload-submit-icon">{overlayFailed ? <AlertTriangle size={26} /> : <LoaderCircle className="spin" size={26} />}</span>
          <div className="upload-submit-copy"><strong>{overlayFailed ? t("knowledgeDetailPipelineFailedTitle") : t("uploadProgressTitle")}</strong><small>{overlayFailed ? t("knowledgeDetailPipelineFailedHelp") : format("uploadProgressHelp", { count: formatCount(validCount, locale) })}</small></div>
          <UploadProgressBar label={localize(uploadStatus)} percent={uploadDisplayProgress} />
          {progressStalled ? <p className="upload-progress-notice">{t(liveProgressDocument ? "uploadProgressWaitLong" : "uploadWaitLong")}</p> : null}
          {liveProgressDocument?.pipeline.observationInterrupted ? <p className="upload-progress-notice" role="alert">{t("uploadProgressInterrupted")}</p> : null}
          {canLeaveWaiting ? <p className="upload-progress-notice">{t("uploadReturnDoesNotCancel")}</p> : null}
          {overlayFailed && (failedStep?.error || liveProgressDocument?.pipeline.error) ? <FeedbackMessage tone={ocrFailureTone({ error_code: failedStep?.errorCode ?? failedStep?.ocr?.error_code })}>{failedStep?.error || liveProgressDocument?.pipeline.error}</FeedbackMessage> : null}
          <OCRBudgetStatus step={livePipelineSteps.find(step => step.name === "ocr_extract")?.ocr} />
          <ChunkingIssueSummary issue={failedStep?.ocr?.chunking_issue} />
          {ocrRetryBlocked(failedStep?.ocr) ? <p className="upload-progress-notice">{t(ocrRetryBlockReasonKey(failedStep?.ocr) ?? "ocrImagePartialReview")}</p> : null}
          <button aria-expanded={progressDetailsOpen} className="upload-progress-detail-toggle" onClick={() => setProgressDetailsOpen((open) => !open)} type="button">
            {progressDetailsOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            <span>{progressDetailsOpen ? t("uploadProgressHideDetails") : t("uploadProgressShowDetails")}</span>
            {livePipelineSteps.length ? <small>{format("uploadProgressStepCount", { completed: formatCount(completedStepCount, locale), total: formatCount(uploadProgressSteps.length, locale) })}</small> : null}
          </button>
          {progressDetailsOpen ? (
            <div className="upload-progress-detail-panel">
              <ol className="upload-progress-step-list">
                {uploadProgressSteps.map((step) => (
                  <li className={`upload-progress-step step-${step.status}`} key={step.id}>
                    <span className="upload-progress-step-icon">
                      {step.status === "completed" ? <CheckCircle2 size={14} /> : step.status === "failed" ? <AlertTriangle size={14} /> : <LoaderCircle className={step.status === "running" ? "spin" : ""} size={14} />}
                    </span>
                    <span className="upload-progress-step-copy">
                      <strong>{step.label}</strong>
                      <small>{step.detail ? localize(step.detail) : uploadStepStatusLabel(step.status, t)}</small>
                    </span>
                    <span className={`upload-progress-step-state step-${step.status}`}>{uploadStepStatusLabel(step.status, t)}</span>
                    {step.progress !== null ? <span className="upload-progress-step-meter" aria-hidden="true"><i style={{ width: `${step.progress}%` }} /></span> : null}
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
          {overlayFailed ? (
            <div className="upload-progress-actions">
              {onRetryPipeline && failedStep && failedStep.retryCount < 3 && !ocrRetryBlocked(failedStep.ocr) && !liveProgressDocument?.pipeline.observationInterrupted ? (
                <button className="action-button secondary" disabled={!canSubmit || retryingPipeline} onClick={retryFailedAutoExtraction} type="button">
                  {retryingPipeline ? <LoaderCircle className="spin" size={16} /> : <RotateCcw size={16} />} {retryingPipeline ? t("knowledgeDetailRetryingStep") : t("knowledgeDetailRetryFailedStep")}
                </button>
              ) : failedStep && failedStep.retryCount >= 3 ? <small className="field-note">{t("knowledgeDetailRetryLimitReached")}</small> : null}
              <button className="action-button" onClick={leaveWaiting} type="button">{t("uploadCloseToProject")}</button>
            </div>
          ) : canLeaveWaiting || (pendingAutoExtraction && !submitting && !retryingPipeline) ? (
            <div className="upload-progress-actions">
              <button className="action-button secondary" onClick={leaveWaiting} type="button">{t("uploadCloseToProject")}</button>
            </div>
          ) : null}
        </div>
      </div> : null}
      {discardOpen ? <FeedbackConfirm title={t("uploadDiscardTitle")} cancelLabel={t("continueEditing")} confirmLabel={t("discardAndClose")} onCancel={() => setDiscardOpen(false)} onConfirm={onClose}>{t("uploadDiscardHelp")}</FeedbackConfirm> : null}
    </Modal>;
}
