"use client";

import { useEffect, useMemo, useState, type DragEvent } from "react";
import { AlertTriangle, ArrowLeft, ArrowRight, CalendarClock, Check, CheckCircle2, ChevronDown, ChevronRight, Cloud, FileText, FolderSync, KeyRound, LoaderCircle, LockKeyhole, RotateCcw, Server, ShieldCheck, Trash2, UploadCloud, X } from "lucide-react";
import type { AIModelResponse } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { ALLOWED_DOCUMENT_EXTENSIONS, DEFAULT_MAX_UPLOAD_BYTES, UPLOAD_REASON_EMPTY, UPLOAD_REASON_READY, UPLOAD_REASON_TOO_LARGE, UPLOAD_REASON_UNSUPPORTED, buildFriendlyCron, documentExtension, formatFileSize, validateFileDescriptor, validateFiveFieldCron } from "@/lib/knowledgeImport";
import { operationalErrorMessage } from "@/lib/operationalMessages";

export { DEFAULT_MAX_UPLOAD_BYTES } from "@/lib/knowledgeImport";

export type SourceState = "pipeline" | "ready_for_extraction" | "syncing" | "sync_failed";
export type PipelineStatus =
  | "queued"
  | "running"
  | "submission_ready"
  | "pending_manager_review"
  | "pending_owner_review"
  | "approved"
  | "publish_ready"
  | "publishing"
  | "production_indexing"
  | "graph_syncing"
  | "published_active"
  | "waiting_action"
  | "completed"
  | "failed"
  | "skipped";

export type ServiceSource = {
  serviceType: "FTP" | "FTPS" | "SFTP" | "S3" | "HTTP_API";
  location: string;
  scheduleMode: "once" | "cron";
  cronExpression?: string;
  timezone: string;
  nextRun?: string;
};

export type ReferenceSource = {
  referenceId?: string | null;
  sourceProjectId?: string;
  sourceDocumentId?: string;
  sourceVersionId?: string;
  projectName: string;
  documentName: string;
  snapshotVersion: string;
  latestActiveVersion: string;
  hasAccess: boolean;
  status?: string;
  detectedAt: string;
  pendingEventCount?: number;
};

export type CreatedKnowledgeDocument = {
  id: string;
  latestVersionId?: string;
  isLive?: boolean;
  lockVersion?: number;
  dataSourceId?: string;
  title: string;
  version: string;
  owner: string;
  documentStatus: string;
  versionStatus: string;
  extractionSuccessful: boolean;
  sourceType: string;
  sourceState: SourceState;
  serviceSource?: ServiceSource;
  referenceSource?: ReferenceSource;
  chunks: number;
  updatedAt: string;
  impactedProjects: string[];
  versions: Array<{ id: string; label: string; status: string; createdAt: string; author: string; lockVersion?: number }>;
  pipeline: {
    id?: string | null;
    status: PipelineStatus;
    progress: number;
    currentStep: string;
    waitingRole: string;
    elapsed: string;
    eta: string;
    error: string;
    steps?: Array<{ name: string; status: string; progress: number; retryCount: number; artifactRef?: string | null; error?: string | null }>;
  };
};

type UploadResult = { name: string; ok: boolean; reason: string };
type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;
type UploadProgressStatus = "completed" | "running" | "waiting" | "failed";
type UploadProgressStep = { id: string; label: string; status: UploadProgressStatus; progress: number; detail?: string };

const CANONICAL_UPLOAD_PIPELINE_STEPS = [
  "upload_received",
  "file_scan",
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
  if (reason === UPLOAD_REASON_TOO_LARGE) return format("uploadReasonTooLargeDynamic", { size: maxUploadMb });
  if (reason === UPLOAD_REASON_EMPTY) return t("uploadReasonEmpty");
  if (reason === UPLOAD_REASON_READY) return t("uploadReady");
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
    prepare_submission: "knowledgeDetailStepPrepareSubmission"
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

function localUploadProgressSteps(progress: number, t: Translate): UploadProgressStep[] {
  const thresholds: Array<{ id: string; label: TranslationKey; target: number }> = [
    { id: "validate", label: "uploadProgressValidating", target: 24 },
    { id: "upload", label: "uploadProgressUploading", target: 48 },
    { id: "create-document", label: "uploadProgressCreateDocument", target: 66 },
    { id: "create-pipeline", label: "uploadProgressCreatePipeline", target: 82 },
    { id: "finalize", label: "uploadProgressFinalizing", target: 96 }
  ];
  return thresholds.map((step, index) => {
    const previous = thresholds[index - 1]?.target ?? 0;
    const status: UploadProgressStatus = progress >= step.target ? "completed" : progress >= previous ? "running" : "waiting";
    const bounded = status === "completed" ? 100 : status === "running" ? Math.max(8, Math.round(((progress - previous) / Math.max(1, step.target - previous)) * 100)) : 0;
    return { id: step.id, label: t(step.label), status, progress: Math.min(100, Math.max(0, bounded)) };
  });
}

function createUploadDocument(file: File, autoExtract: boolean, index: number, t: Translate): CreatedKnowledgeDocument {
  const id = `upload-${Date.now()}-${index}`;
  return {
    id,
    title: file.name,
    version: "v1.0",
    owner: "Peter Wang",
    documentStatus: "inactive",
    versionStatus: autoExtract ? "processing" : "draft",
    extractionSuccessful: false,
    sourceType: "File upload",
    sourceState: autoExtract ? "pipeline" : "ready_for_extraction",
    chunks: 0,
    updatedAt: t("uploadDemoNow"),
    impactedProjects: [],
    versions: [{ id: "v1.0", label: "v1.0", status: autoExtract ? "processing" : "draft", createdAt: t("uploadDemoNow"), author: "Peter Wang" }],
    pipeline: autoExtract
      ? { status: "running", progress: 4, currentStep: t("uploadStepReceived"), waitingRole: "", elapsed: "00m 03s", eta: t("uploadEtaLong"), error: "" }
      : { status: "running", progress: 0, currentStep: t("uploadStepWaitManualExtraction"), waitingRole: "", elapsed: "", eta: "", error: "" }
  };
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
  initialFiles?: File[];
  maxUploadBytes?: number;
  ocrModels?: AIModelResponse[];
  onClose: () => void;
  onCreate: (documents: CreatedKnowledgeDocument[], autoExtractionId?: string) => void;
  onRetryPipeline?: (document: CreatedKnowledgeDocument, onProgressDocument?: (document: CreatedKnowledgeDocument) => void) => Promise<CreatedKnowledgeDocument>;
  onUploadFiles?: (files: File[], options: { ocrModelId: string | null; forceOcr: boolean; startExtraction: boolean }, onProgressDocuments?: (documents: CreatedKnowledgeDocument[]) => void) => Promise<CreatedKnowledgeDocument[]>;
};

export function UploadFilesModal({ initialFiles = [], maxUploadBytes = DEFAULT_MAX_UPLOAD_BYTES, ocrModels = [], onClose, onCreate, onRetryPipeline, onUploadFiles }: UploadFilesModalProps) {
  const { t, format, localize } = useI18n();
  const [files, setFiles] = useState<File[]>(() => initialFiles);
  const [results, setResults] = useState<UploadResult[] | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [progressDetailsOpen, setProgressDetailsOpen] = useState(false);
  const [liveProgressDocuments, setLiveProgressDocuments] = useState<CreatedKnowledgeDocument[]>([]);
  const [discardOpen, setDiscardOpen] = useState(false);
  const defaultOcr = ocrModels.find((model) => model.is_default) ?? ocrModels[0];
  const [ocrModelId, setOcrModelId] = useState<string | null>(() => defaultOcr?.id ?? null);
  const [forceOcr, setForceOcr] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [retryingPipeline, setRetryingPipeline] = useState(false);
  const maxUploadMb = Math.max(1, Math.round(maxUploadBytes / 1024 / 1024));
  const validation = useMemo(() => files.map((file) => validateUploadFile(file, maxUploadBytes)), [files, maxUploadBytes]);
  const validCount = validation.filter((item) => item.ok).length;
  const hasUnsavedSelection = files.length > 0 && !results;
  const resolvedOcrModelId = ocrModelId ?? defaultOcr?.id ?? null;
  const autoExtractCandidate = files.length === 1 && validCount === 1;
  const liveProgressDocument = liveProgressDocuments.find((document) => document.pipeline.steps?.length) ?? liveProgressDocuments[0];
  const failedAutoExtraction = autoExtractCandidate && uploadExtractionFailed(liveProgressDocument);
  const pendingAutoExtraction = autoExtractCandidate && Boolean(liveProgressDocument) && !uploadExtractionReady(liveProgressDocument) && !failedAutoExtraction && Boolean(results);
  const modalLocked = retryingPipeline || (submitting && !failedAutoExtraction);

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key !== "Escape" || modalLocked) return;
      if (hasUnsavedSelection) setDiscardOpen(true);
      else onClose();
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [hasUnsavedSelection, modalLocked, onClose]);

  useEffect(() => {
    if (!submitting) return;
    const timer = window.setInterval(() => {
      setUploadProgress((progress) => Math.min(92, progress + (progress < 45 ? 7 : progress < 75 ? 4 : 2)));
    }, 420);
    return () => window.clearInterval(timer);
  }, [submitting]);

  function requestClose() {
    if (modalLocked) return;
    if (hasUnsavedSelection) setDiscardOpen(true);
    else onClose();
  }

  function selectFiles(nextFiles: File[]) {
    if (modalLocked) return;
    setFiles(nextFiles);
    setResults(null);
    setSubmitError("");
    setUploadProgress(0);
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
    if (!files.length || submitting) return;
    setSubmitting(true);
    setUploadProgress(12);
    setLiveProgressDocuments([]);
    setSubmitError("");
    const checked = files.map((file) => validateUploadFile(file, maxUploadBytes));
    setUploadProgress(24);
    const validFiles = files.filter((_, index) => checked[index].ok);
    const autoExtract = files.length === 1 && validFiles.length === 1;
    try {
      setUploadProgress(48);
      const documents = onUploadFiles
        ? await onUploadFiles(validFiles, { ocrModelId: resolvedOcrModelId, forceOcr, startExtraction: autoExtract }, setLiveProgressDocuments)
        : validFiles.map((file, index) => createUploadDocument(file, autoExtract, index, t));
      setUploadProgress(96);
      const autoExtractionId = autoExtract && uploadExtractionReady(documents[0]) ? documents[0]?.id : undefined;
      onCreate(documents, autoExtractionId);
      setResults(checked);
      if (autoExtractionId) onClose();
      else setSubmitting(false);
    } catch (error) {
      setSubmitError(operationalErrorMessage(error, t, format, "uploadErrorFallback"));
      setUploadProgress(0);
      setSubmitting(false);
    }
  }

  async function retryFailedAutoExtraction() {
    if (!liveProgressDocument || !onRetryPipeline || retryingPipeline) return;
    setRetryingPipeline(true);
    setSubmitError("");
    try {
      const document = await onRetryPipeline(liveProgressDocument, (progressDocument) => setLiveProgressDocuments([progressDocument]));
      setLiveProgressDocuments([document]);
      onCreate([document], uploadExtractionReady(document) ? document.id : undefined);
      if (uploadExtractionReady(document)) onClose();
    } catch (error) {
      setSubmitError(operationalErrorMessage(error, t, format, "knowledgeDetailRetryFailed"));
    } finally {
      setRetryingPipeline(false);
      setSubmitting(false);
    }
  }

  const showSubmitOverlay = submitting || retryingPipeline || failedAutoExtraction || pendingAutoExtraction;
  const overlayFailed = failedAutoExtraction && !retryingPipeline;
  const failedStep = uploadFailedStep(liveProgressDocument);
  const livePipelineSteps = liveProgressDocument?.pipeline.steps ?? [];
  const localProgressSteps = localUploadProgressSteps(uploadProgress, t);
  const waitingPipelineSteps: UploadProgressStep[] = autoExtractCandidate && !livePipelineSteps.length
    ? CANONICAL_UPLOAD_PIPELINE_STEPS.map((name) => ({ id: name, label: uploadPipelineStepLabel(name, t), status: "waiting", progress: 0, detail: t("uploadProgressWaitingLivePipeline") }))
    : [];
  const uploadProgressSteps: UploadProgressStep[] = livePipelineSteps.length
    ? livePipelineSteps.map((step) => ({
        id: step.name,
        label: uploadPipelineStepLabel(step.name, t),
        status: normalizeUploadStepStatus(step.status),
        progress: Math.min(100, Math.max(0, Math.round(step.progress))),
        detail: step.error ? t("apiGenericError") : step.artifactRef || format("projectImportRetryCount", { count: step.retryCount })
      }))
    : [...localProgressSteps, ...waitingPipelineSteps];
  const activeLocalStep = localProgressSteps.find((step) => step.status === "running") ?? localProgressSteps.find((step) => step.status === "waiting") ?? localProgressSteps[localProgressSteps.length - 1];
  const uploadStatus = livePipelineSteps.length ? (liveProgressDocument?.pipeline.currentStep || t("uploadProgressWaitingLivePipeline")) : activeLocalStep?.label ?? t("uploadProgressFinalizing");
  const uploadDisplayProgress = livePipelineSteps.length ? Math.min(100, Math.max(0, Math.round(liveProgressDocument?.pipeline.progress ?? uploadProgress))) : uploadProgress;
  const completedStepCount = uploadProgressSteps.filter((step) => step.status === "completed").length;

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) requestClose(); }} role="presentation">
    <section aria-busy={submitting || retryingPipeline} aria-labelledby="upload-files-title" aria-modal="true" className={`modal-panel source-modal optimized-source-modal${modalLocked ? " source-modal-locked" : ""}`} role="dialog">
      <header className="source-modal-header"><div><p className="eyebrow">{t("uploadModalEyebrow")}</p><h2 id="upload-files-title">{t("uploadModalTitle")}</h2><small>{t("uploadModalHelp")}</small></div><button aria-label={t("uploadModalClose")} className="icon-button" disabled={modalLocked} onClick={requestClose} type="button"><X size={18} /></button></header>
      <div className="source-modal-body">
        <div className="upload-rule-chips" aria-label={t("uploadRules")}><span><FileText size={14} /> PDF · DOCX · TXT · MD</span><span><ShieldCheck size={14} /> {format("uploadMaxSizeDynamic", { size: maxUploadMb })}</span></div>
        <section className="upload-ocr-panel">
          <label><span>{t("uploadOcrModel")}</span><select disabled={modalLocked || ocrModels.length === 0} onChange={(event) => setOcrModelId(event.target.value || null)} value={resolvedOcrModelId ?? ""}><option value="">{ocrModels.length ? t("uploadUseDefaultOcr") : t("uploadNoOcrModel")}</option>{ocrModels.filter((model) => model.is_active).map((model) => <option key={model.id} value={model.id}>{model.name}{model.is_default ? t("uploadDefaultSuffix") : ""}</option>)}</select></label>
          <label className="service-check-field"><input checked={forceOcr} disabled={modalLocked} onChange={(event) => setForceOcr(event.target.checked)} type="checkbox" /><span>{t("uploadForceOcr")}</span></label>
          {forceOcr ? <div className="upload-force-ocr-warning"><AlertTriangle size={16} /><span>{t("uploadForceOcrWarning")}</span></div> : null}
        </section>
        <label className={`source-file-drop source-file-drop-primary ${dragging ? "dragging" : ""}`} onDragEnter={() => { if (!modalLocked) setDragging(true); }} onDragLeave={() => setDragging(false)} onDragOver={(event) => event.preventDefault()} onDrop={handleDrop} tabIndex={modalLocked ? -1 : 0}>
          <span className="upload-drop-icon"><UploadCloud size={30} /></span><strong>{t("uploadDropTitle")}</strong><small>{t("uploadDropHelp")}</small><em>{t("uploadSelectFiles")}</em>
          <input accept=".pdf,.docx,.txt,.md,.markdown" disabled={modalLocked} multiple onChange={(event) => selectFiles(Array.from(event.target.files ?? []))} type="file" />
        </label>
        <div className={`upload-behavior-callout ${files.length > 1 ? "batch" : "single"}`}><span>{files.length > 1 ? <FileText size={18} /> : <ArrowRight size={18} />}</span><div><strong>{files.length > 1 ? t("uploadBatchTitle") : t("uploadSingleTitle")}</strong><small>{files.length > 1 ? t("uploadBatchHelp") : t("uploadSingleHelp")}</small></div></div>
        {files.length ? <section className="upload-files-section"><div className="upload-files-heading"><div><strong>{results ? t("uploadResults") : t("uploadSelectedFiles")}</strong><small>{format("uploadValidationSummary", { files: files.length, valid: validCount })}</small></div>{!results ? <button aria-label={format("uploadClearAllLabel", { count: files.length })} className="clear-all-files-button" disabled={modalLocked} onClick={() => selectFiles([])} type="button"><Trash2 size={16} /> {t("uploadClearAll")}</button> : null}</div><div className="upload-selection-list optimized-upload-list">{validation.map((item, index) => { const file = files[index]; const extension = documentExtension(file.name).toUpperCase(); return <div className={item.ok ? "valid" : "invalid"} key={`${item.name}-${index}`}><span className="file-type-badge">{extension}</span><span className="upload-file-identity"><strong title={item.name}>{item.name}</strong><small>{formatFileSize(file.size)} · {localizeUploadReason(item.reason, t, format, maxUploadMb)}</small></span><span className="upload-file-status">{item.ok ? <><CheckCircle2 size={16} /> {results ? t("uploadAdded") : t("uploadReady")}</> : <><AlertTriangle size={16} /> {t("uploadFailed")}</>}</span></div>; })}</div></section> : null}
        {results ? <div aria-live="polite" className="upload-result-summary optimized-result-summary"><CheckCircle2 size={20} /><div><strong>{t("uploadResultTitle")}</strong><span>{format("uploadResultCounts", { success: results.filter((item) => item.ok).length, failed: results.filter((item) => !item.ok).length })}</span><small>{t("uploadResultHelp")}</small></div></div> : null}
        {submitError ? <div className="upload-result-summary upload-error-summary" role="alert"><AlertTriangle size={20} /><div><strong>{t("uploadIncomplete")}</strong><small>{localize(submitError)}</small></div></div> : null}
      </div>
      <footer className="source-modal-footer"><small>{!results && files.length ? format("uploadWillProcess", { count: validCount }) : results ? t("uploadResultsKept") : t("uploadNoFilesSelected")}</small><div><button className="action-button secondary" disabled={modalLocked} onClick={requestClose} type="button">{results ? t("complete") : t("cancel")}</button>{!results ? <button className="action-button" disabled={!files.length || validCount === 0 || modalLocked} onClick={submit} type="button">{submitting ? <LoaderCircle className="spin" size={16} /> : <UploadCloud size={16} />} {files.length > 1 ? format("uploadValidFiles", { count: validCount }) : t("uploadAndExtract")}</button> : null}</div></footer>
      {showSubmitOverlay ? <div aria-live="assertive" className={`upload-submit-overlay${overlayFailed ? " failed" : ""}`} role="status">
        <div className="upload-submit-card">
          <span className="upload-submit-icon">{overlayFailed ? <AlertTriangle size={26} /> : <LoaderCircle className="spin" size={26} />}</span>
          <div className="upload-submit-copy"><strong>{overlayFailed ? t("knowledgeDetailPipelineFailedTitle") : t("uploadProgressTitle")}</strong><small>{overlayFailed ? t("knowledgeDetailPipelineFailedHelp") : format("uploadProgressHelp", { count: validCount })}</small></div>
          <div className="upload-progress-track" aria-label={localize(uploadStatus)} aria-valuemax={100} aria-valuemin={0} aria-valuenow={Math.round(uploadDisplayProgress)} role="progressbar"><span style={{ width: `${uploadDisplayProgress}%` }} /></div>
          <div className="upload-progress-meta"><span>{localize(uploadStatus)}</span><strong>{Math.round(uploadDisplayProgress)}%</strong></div>
          {overlayFailed && (failedStep?.error || liveProgressDocument?.pipeline.error) ? <p className="upload-progress-error-message">{t("apiGenericError")}</p> : null}
          <button aria-expanded={progressDetailsOpen} className="upload-progress-detail-toggle" onClick={() => setProgressDetailsOpen((open) => !open)} type="button">
            {progressDetailsOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            <span>{progressDetailsOpen ? t("uploadProgressHideDetails") : t("uploadProgressShowDetails")}</span>
            <small>{format("uploadProgressStepCount", { completed: completedStepCount, total: uploadProgressSteps.length })}</small>
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
                    <span className="upload-progress-step-meter" aria-hidden="true"><i style={{ width: `${step.progress}%` }} /></span>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
          {overlayFailed ? (
            <div className="upload-progress-actions">
              {onRetryPipeline && failedStep && failedStep.retryCount < 3 ? (
                <button className="action-button secondary" disabled={retryingPipeline} onClick={retryFailedAutoExtraction} type="button">
                  {retryingPipeline ? <LoaderCircle className="spin" size={16} /> : <RotateCcw size={16} />} {retryingPipeline ? t("knowledgeDetailRetryingStep") : t("knowledgeDetailRetryFailedStep")}
                </button>
              ) : failedStep && failedStep.retryCount >= 3 ? <small className="field-note">{t("knowledgeDetailRetryLimitReached")}</small> : null}
              <button className="action-button" onClick={onClose} type="button">{t("uploadCloseToProject")}</button>
            </div>
          ) : pendingAutoExtraction && !submitting && !retryingPipeline ? (
            <div className="upload-progress-actions">
              <button className="action-button secondary" onClick={onClose} type="button">{t("uploadCloseToProject")}</button>
            </div>
          ) : null}
        </div>
      </div> : null}
      {discardOpen ? <div className="inline-confirm-backdrop"><div className="inline-confirm" role="alertdialog"><AlertTriangle size={22} /><div><strong>{t("uploadDiscardTitle")}</strong><small>{t("uploadDiscardHelp")}</small></div><div><button className="action-button secondary" onClick={() => setDiscardOpen(false)} type="button">{t("continueEditing")}</button><button className="action-button danger" onClick={onClose} type="button">{t("discardAndClose")}</button></div></div></div> : null}
    </section>
  </div>;
}

type ServiceType = ServiceSource["serviceType"];
type ScheduleMode = ServiceSource["scheduleMode"];

export type DataServicePayload = {
  service_type: ServiceType;
  name: string;
  host: string;
  port: number;
  username: string;
  credential: string | null;
  bucket?: string | null;
  region?: string | null;
  remote_path: string;
  file_name: string;
  schedule_mode: ScheduleMode;
  cron_expression?: string | null;
  timezone: string;
  verify_tls: boolean;
  verify_host_key: boolean;
  url?: string | null;
  headers?: Record<string, string>;
  auth_mode?: "none" | "bearer" | "api_key_header";
  api_key_header_name?: string | null;
  timeout_seconds?: number;
  max_bytes?: number | null;
};

export function DataServiceModal({
  onClose,
  onCreate,
  onCreateDataSource,
  onTestConnection
}: {
  onClose: () => void;
  onCreate: (document: CreatedKnowledgeDocument) => void;
  onCreateDataSource?: (payload: DataServicePayload) => Promise<CreatedKnowledgeDocument>;
  onTestConnection?: (payload: DataServicePayload) => Promise<void>;
}) {
  const { t, format, localize } = useI18n();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [serviceType, setServiceType] = useState<ServiceType>("S3");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("443");
  const [username, setUsername] = useState("");
  const [credential, setCredential] = useState("");
  const [url, setUrl] = useState("");
  const [authMode, setAuthMode] = useState<"none" | "bearer" | "api_key_header">("none");
  const [apiKeyHeaderName, setApiKeyHeaderName] = useState("X-API-Key");
  const [headersText, setHeadersText] = useState("");
  const [bucket, setBucket] = useState("");
  const [region, setRegion] = useState("");
  const [path, setPath] = useState("");
  const [fileName, setFileName] = useState("");
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>("once");
  const [cronMode, setCronMode] = useState<"friendly" | "advanced">("friendly");
  const [frequency, setFrequency] = useState("daily");
  const [interval, setInterval] = useState("1");
  const [hour, setHour] = useState("02");
  const [minute, setMinute] = useState("00");
  const [weekday, setWeekday] = useState("1");
  const [advancedCron, setAdvancedCron] = useState("0 2 * * *");
  const [timezone, setTimezone] = useState("Asia/Taipei");
  const [testState, setTestState] = useState<"idle" | "testing" | "success" | "failed">("idle");
  const [testMessage, setTestMessage] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);

  const friendlyCron = buildFriendlyCron(frequency as "minutes" | "hourly" | "daily" | "weekly", Number(hour), Number(minute), Number(weekday), Number(interval));
  const cronExpression = cronMode === "advanced" ? advancedCron.trim() : friendlyCron ?? "";
  const cronValid = validateFiveFieldCron(cronExpression);
  const extensionValid = ALLOWED_DOCUMENT_EXTENSIONS.includes(documentExtension(fileName) as (typeof ALLOWED_DOCUMENT_EXTENSIONS)[number]);
  const parsedHeaders = useMemo(() => {
    if (!headersText.trim()) return {};
    try {
      const parsed = JSON.parse(headersText);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, string> : {};
    } catch {
      return {};
    }
  }, [headersText]);
  const connectionReady = serviceType === "HTTP_API" ? Boolean(url && (authMode === "none" || credential) && (authMode !== "api_key_header" || apiKeyHeaderName)) : Boolean(host && username && credential && (serviceType !== "S3" || bucket));
  const sourceValid = Boolean(fileName) && extensionValid && (serviceType === "HTTP_API" || Boolean(path)) && (scheduleMode === "once" || (cronValid && timezone));
  const formValid = connectionReady && testState === "success" && sourceValid;
  const dirty = Boolean(host || username || credential || bucket || path || fileName || step > 1);

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key !== "Escape" || submitting) return;
      if (dirty) setDiscardOpen(true);
      else onClose();
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [dirty, onClose, submitting]);

  function requestClose() {
    if (submitting) return;
    if (dirty) setDiscardOpen(true);
    else onClose();
  }

  function dataSourcePayload(): DataServicePayload {
    return {
      service_type: serviceType,
      name: fileName || `${serviceType} data source`,
      host,
      port: Number(port),
      username,
      credential: credential || null,
      bucket: serviceType === "S3" ? bucket : null,
      region: serviceType === "S3" ? region || null : null,
      remote_path: path,
      file_name: fileName,
      schedule_mode: scheduleMode,
      cron_expression: scheduleMode === "cron" ? cronExpression : null,
      timezone,
      verify_tls: serviceType === "FTPS" || serviceType === "S3",
      verify_host_key: serviceType === "SFTP",
      url: serviceType === "HTTP_API" ? url : null,
      headers: serviceType === "HTTP_API" ? parsedHeaders : {},
      auth_mode: serviceType === "HTTP_API" ? authMode : "none",
      api_key_header_name: serviceType === "HTTP_API" && authMode === "api_key_header" ? apiKeyHeaderName : null,
      timeout_seconds: serviceType === "HTTP_API" ? 30 : undefined,
      max_bytes: null
    };
  }

  function invalidateConnection() { setTestState("idle"); setTestMessage(""); }

  function switchService(next: ServiceType) {
    setServiceType(next);
    setPort(next === "S3" || next === "FTPS" || next === "HTTP_API" ? "443" : next === "FTP" ? "21" : "22");
    invalidateConnection();
  }

  async function testConnection() {
    if (!connectionReady || testState === "testing") return;
    setTestState("testing");
    setTestMessage("");
    try {
      if (onTestConnection) await onTestConnection(dataSourcePayload());
      else await new Promise((resolve) => window.setTimeout(resolve, 450));
      setTestState("success");
    } catch (error) {
      setTestMessage(operationalErrorMessage(error, t, format, "serviceConnectionFailedHelp"));
      setTestState("failed");
    }
  }

  async function submit() {
    if (!formValid || submitting) return;
    setSubmitting(true);
    setSubmitError("");
    const location = serviceType === "HTTP_API" ? url : serviceType === "S3" ? `${bucket}/${path.replace(/^\/+|\/+$/g, "")}/${fileName}` : `${host}:${port}/${path.replace(/^\/+|\/+$/g, "")}/${fileName}`;
    const id = `service-${Date.now()}`;
    try {
      const document = onCreateDataSource ? await onCreateDataSource(dataSourcePayload()) : {
        id,
        title: fileName,
        version: "v1.0",
        owner: "Peter Wang",
        documentStatus: "inactive",
        versionStatus: "draft",
        extractionSuccessful: false,
        sourceType: `${serviceType} service`,
        sourceState: "syncing" as const,
        serviceSource: { serviceType, location, scheduleMode, cronExpression: scheduleMode === "cron" ? cronExpression : undefined, timezone },
        chunks: 0,
        updatedAt: t("serviceDemoNow"),
        impactedProjects: [],
        versions: [],
        pipeline: { status: "running" as PipelineStatus, progress: 0, currentStep: t("serviceStepInitialSync"), waitingRole: "", elapsed: "00m 01s", eta: t("serviceEtaRemote"), error: "" }
      };
      onCreate(document);
      onClose();
    } catch (error) {
      setSubmitError(operationalErrorMessage(error, t, format, "uploadErrorFallback"));
      setSubmitting(false);
    }
  }

  const stepLabels = [t("serviceStepConnection"), t("serviceStepFileSync"), t("serviceStepReviewCreate")];
  const stepOneValid = connectionReady && testState === "success";
  const stepTwoValid = sourceValid;
  const connectionTitle = testState === "testing" ? t("serviceTestingConnection") : testState === "success" ? t("serviceConnectionSuccess") : testState === "failed" ? t("serviceConnectionFailed") : t("serviceConnectionIdle");
  const connectionHelp = testMessage ? localize(testMessage) : testState === "success" ? t("serviceConnectionSuccessHelp") : testState === "failed" ? t("serviceConnectionFailedHelp") : t("serviceConnectionIdleHelp");
  const cronPreviewHelp = frequency === "weekly" && cronMode === "friendly" ? t("serviceWeeklyPreview") : frequency === "minutes" ? format("serviceMinutesPreview", { interval }) : frequency === "hourly" ? format("serviceHourlyPreview", { interval }) : t("serviceDailyPreview");
  const footerHelp = step === 1 ? !connectionReady ? t("serviceFooterNeedConnection") : testState !== "success" ? t("serviceFooterNeedTest") : t("serviceFooterConnectionReady") : step === 2 ? !sourceValid ? t("serviceFooterNeedSource") : t("serviceFooterSourceReady") : t("serviceFooterReviewReady");

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) requestClose(); }} role="presentation">
    <section aria-labelledby="data-service-title" aria-modal="true" className="modal-panel source-modal data-service-modal optimized-source-modal" role="dialog">
      <header className="source-modal-header"><div><p className="eyebrow">{t("serviceEyebrow")}</p><h2 id="data-service-title">{t("serviceTitle")}</h2><small>{t("serviceHelp")}</small></div><button aria-label={t("serviceClose")} className="icon-button" disabled={submitting} onClick={requestClose} type="button"><X size={18} /></button></header>
      <div className="service-progress-shell"><ol aria-label={t("serviceStepsAria")} className="service-stepper">{stepLabels.map((label, index) => { const number = index + 1; const complete = number < step; const current = number === step; return <li aria-current={current ? "step" : undefined} className={complete ? "complete" : current ? "current" : "upcoming"} key={label}><span className="step-marker">{complete ? <Check size={16} /> : number}</span><div className="step-copy"><small>{format("serviceStepNumber", { number })}</small><strong>{label}</strong></div></li>; })}</ol><span aria-label={format("serviceProtocolAria", { type: serviceType, port })} className="service-protocol-pill">{serviceType} · {port}</span></div>
      <div className="source-modal-body wizard-body">
        {step === 1 ? <section className="wizard-step-panel"><div className="wizard-section-heading"><div><strong>{t("serviceSelectTypeTitle")}</strong><small>{t("serviceSelectTypeHelp")}</small></div></div><div className="service-type-tabs service-type-cards" role="tablist">{(["S3", "FTP", "FTPS", "SFTP", "HTTP_API"] as ServiceType[]).map((type, index) => <button aria-selected={serviceType === type} autoFocus={index === 0} className={serviceType === type ? "active" : ""} key={type} onClick={() => switchService(type)} role="tab" type="button">{type === "S3" || type === "HTTP_API" ? <Cloud size={20} /> : <Server size={20} />}<span><strong>{type}</strong><small>{type === "S3" ? t("serviceObjectStorage") : type === "HTTP_API" ? t("serviceHttpGet") : type === "FTP" ? t("serviceStandardTransfer") : t("serviceSecureTransfer")}</small></span>{serviceType === type ? <CheckCircle2 size={16} /> : null}</button>)}</div><div className="service-form-grid compact-service-form">{serviceType === "HTTP_API" ? <><label><span>{t("serviceHttpGetUrl")}</span><input onChange={(event) => { setUrl(event.target.value); invalidateConnection(); }} placeholder="https://api.example.com/document.json" value={url} /></label><label><span>{t("serviceAuthMode")}</span><select onChange={(event) => { setAuthMode(event.target.value as "none" | "bearer" | "api_key_header"); invalidateConnection(); }} value={authMode}><option value="none">{t("serviceAuthNone")}</option><option value="bearer">{t("serviceAuthBearer")}</option><option value="api_key_header">{t("serviceAuthApiKeyHeader")}</option></select></label>{authMode === "api_key_header" ? <label><span>{t("serviceApiKeyHeader")}</span><input onChange={(event) => { setApiKeyHeaderName(event.target.value); invalidateConnection(); }} value={apiKeyHeaderName} /></label> : null}{authMode !== "none" ? <label><span>{t("serviceCredentialReference")}</span><input autoComplete="new-password" onChange={(event) => { setCredential(event.target.value); invalidateConnection(); }} type="password" value={credential} /></label> : null}<label><span>{t("serviceHeadersJson")}</span><textarea onChange={(event) => { setHeadersText(event.target.value); invalidateConnection(); }} placeholder={'{"Accept":"application/json"}'} value={headersText} /></label><label className="service-check-field"><input defaultChecked type="checkbox" /><span>{t("serviceVerifyTls")}</span></label></> : <><label><span>{serviceType === "S3" ? t("serviceS3Endpoint") : t("serviceHost")}</span><input onChange={(event) => { setHost(event.target.value); invalidateConnection(); }} placeholder={serviceType === "S3" ? "https://s3.example.com" : "files.example.com"} value={host} /></label><label><span>{t("labelPort")}</span><input inputMode="numeric" onChange={(event) => { setPort(event.target.value); invalidateConnection(); }} value={port} /></label>{serviceType === "S3" ? <><label><span>{t("labelBucket")}</span><input onChange={(event) => { setBucket(event.target.value); invalidateConnection(); }} placeholder="knowledge-source" value={bucket} /></label><label><span>{t("serviceRegionOptional")}</span><input onChange={(event) => { setRegion(event.target.value); invalidateConnection(); }} placeholder="ap-northeast-1" value={region} /></label></> : null}{serviceType === "FTPS" ? <label><span>{t("serviceFtpsSecurityMode")}</span><select defaultValue="explicit" onChange={invalidateConnection}><option value="explicit">Explicit TLS</option><option value="implicit">Implicit TLS</option></select></label> : null}<label><span>{t("labelUsernameAccessKey")}</span><input autoComplete="username" onChange={(event) => { setUsername(event.target.value); invalidateConnection(); }} value={username} /></label><label><span>{serviceType === "SFTP" ? t("servicePasswordPrivateKeyReference") : t("serviceCredentialReference")}</span><input autoComplete="new-password" onChange={(event) => { setCredential(event.target.value); invalidateConnection(); }} type="password" value={credential} /></label>{serviceType === "SFTP" ? <label className="service-check-field"><input defaultChecked type="checkbox" /><span>{t("serviceVerifySsh")}</span></label> : null}{serviceType === "FTPS" || serviceType === "S3" ? <label className="service-check-field"><input defaultChecked type="checkbox" /><span>{t("serviceVerifyTls")}</span></label> : null}</>}</div><div className={`connection-test-card ${testState}`}><span>{testState === "testing" ? <LoaderCircle className="spin" size={20} /> : testState === "success" ? <CheckCircle2 size={20} /> : testState === "failed" ? <AlertTriangle size={20} /> : <KeyRound size={20} />}</span><div><strong>{connectionTitle}</strong><small>{connectionHelp}</small></div><button className="action-button secondary" disabled={!connectionReady || testState === "testing"} onClick={testConnection} type="button">{testState === "success" || testState === "failed" ? t("serviceRetest") : t("serviceTestConnection")}</button></div></section> : null}
        {step === 2 ? <section className="wizard-step-panel"><div className="wizard-section-heading"><div><strong>{t("serviceRemoteFileTitle")}</strong><small>{t("serviceRemoteFileHelp")}</small></div><span className="service-context-pill">{serviceType} · {host}</span></div><div className="service-form-grid"><label><span>{t("serviceRemotePath")}</span><input autoFocus onChange={(event) => setPath(event.target.value)} placeholder="policies/2026" value={path} /></label><label><span>{t("serviceSingleFileName")}</span><input aria-invalid={Boolean(fileName) && !extensionValid} onChange={(event) => setFileName(event.target.value)} placeholder="policy.pdf" value={fileName} />{fileName && !extensionValid ? <small className="field-error">{t("serviceInvalidExtension")}</small> : null}</label></div><fieldset className="schedule-fieldset optimized-schedule"><legend><CalendarClock size={17} /> {t("serviceSyncMode")}</legend><div className="schedule-mode-options schedule-choice-cards"><label className={scheduleMode === "once" ? "active" : ""}><input checked={scheduleMode === "once"} name="schedule" onChange={() => setScheduleMode("once")} type="radio" /><span><strong>{t("serviceOnce")}</strong><small>{t("serviceOnceHelp")}</small></span></label><label className={scheduleMode === "cron" ? "active" : ""}><input checked={scheduleMode === "cron"} name="schedule" onChange={() => setScheduleMode("cron")} type="radio" /><span><strong>{t("serviceCron")}</strong><small>{t("serviceCronHelp")}</small></span></label></div>{scheduleMode === "cron" ? <div className="cron-builder"><div className="cron-mode-tabs"><button className={cronMode === "friendly" ? "active" : ""} onClick={() => setCronMode("friendly")} type="button">{t("serviceFriendly")}</button><button className={cronMode === "advanced" ? "active" : ""} onClick={() => setCronMode("advanced")} type="button">{t("serviceAdvancedCron")}</button></div>{cronMode === "friendly" ? <div className="friendly-cron-fields"><label><span>{t("serviceFrequency")}</span><select onChange={(event) => setFrequency(event.target.value)} value={frequency}><option value="minutes">{t("serviceEveryMinutes")}</option><option value="hourly">{t("serviceEveryHours")}</option><option value="daily">{t("serviceDaily")}</option><option value="weekly">{t("serviceWeekly")}</option></select></label>{frequency === "minutes" || frequency === "hourly" ? <label><span>{t("serviceInterval")}</span><input max={frequency === "minutes" ? 59 : 23} min="1" onChange={(event) => setInterval(event.target.value)} type="number" value={interval} /></label> : null}{frequency === "weekly" ? <label><span>{t("serviceWeekday")}</span><select onChange={(event) => setWeekday(event.target.value)} value={weekday}><option value="1">{t("serviceMonday")}</option><option value="2">{t("serviceTuesday")}</option><option value="3">{t("serviceWednesday")}</option><option value="4">{t("serviceThursday")}</option><option value="5">{t("serviceFriday")}</option><option value="6">{t("serviceSaturday")}</option><option value="0">{t("serviceSunday")}</option></select></label> : null}{frequency !== "minutes" ? <label><span>{frequency === "hourly" ? t("serviceHourlyMinute") : t("serviceTime")}</span>{frequency === "hourly" ? <input max="59" min="0" onChange={(event) => setMinute(event.target.value)} type="number" value={minute} /> : <span className="time-inputs"><input aria-label={t("serviceHourAria")} max="23" min="0" onChange={(event) => setHour(event.target.value)} type="number" value={hour} /><b>:</b><input aria-label={t("serviceMinuteAria")} max="59" min="0" onChange={(event) => setMinute(event.target.value)} type="number" value={minute} /></span>}</label> : null}</div> : <label className="advanced-cron-field"><span>{t("serviceFiveFieldCron")}</span><input aria-invalid={!cronValid} onChange={(event) => setAdvancedCron(event.target.value)} value={advancedCron} />{!cronValid ? <small className="field-error">{t("serviceInvalidCron")}</small> : null}</label>}<label className="timezone-field"><span>{t("serviceTimezone")}</span><select onChange={(event) => setTimezone(event.target.value)} value={timezone}><option>Asia/Taipei</option><option>Asia/Tokyo</option><option>America/New_York</option><option>Europe/London</option></select></label><div className="cron-preview"><FolderSync size={17} /><span><strong>{cronExpression || t("serviceCronIncomplete")}</strong><small>{cronPreviewHelp} · {timezone} · {t("serviceNextRun")}</small></span></div></div> : null}</fieldset></section> : null}
        {step === 3 ? <section className="wizard-step-panel"><div className="wizard-section-heading"><div><strong>{t("serviceReviewTitle")}</strong><small>{t("serviceReviewHelp")}</small></div><span className="review-safe-badge"><LockKeyhole size={14} /> {t("serviceSecretHidden")}</span></div><div className="service-review-grid"><div><small>{t("serviceConnection")}</small><strong>{serviceType}</strong><span>{host}:{port}</span>{serviceType === "S3" ? <span>{bucket}{region ? ` · ${region}` : ""}</span> : null}</div><div><small>{t("serviceSourceFile")}</small><strong>{fileName}</strong><span>{path}</span><span>{t("serviceSingleFileSync")}</span></div><div><small>{t("serviceSchedule")}</small><strong>{scheduleMode === "once" ? t("serviceOnce") : t("serviceCron")}</strong><span>{scheduleMode === "cron" ? cronExpression : t("serviceRunOnceNow")}</span><span>{timezone}{scheduleMode === "cron" ? ` · ${t("serviceNextRun")}` : ""}</span></div></div><div className="service-create-explainer"><FolderSync size={22} /><div><strong>{t("serviceCreateExplainerTitle")}</strong><ol><li>{t("serviceCreateStepDocument")}</li><li>{t("serviceCreateStepSync")}</li><li>{t("serviceCreateStepExtraction")}</li></ol></div></div>{submitError ? <div className="upload-result-summary upload-error-summary" role="alert"><AlertTriangle size={20} /><div><strong>{t("uploadIncomplete")}</strong><small>{localize(submitError)}</small></div></div> : null}</section> : null}
      </div>
      <footer className="source-modal-footer wizard-footer"><small>{footerHelp}</small><div><button className="action-button secondary" disabled={submitting} onClick={requestClose} type="button">{t("cancel")}</button>{step > 1 ? <button className="action-button secondary" disabled={submitting} onClick={() => setStep((step - 1) as 1 | 2)} type="button"><ArrowLeft size={16} /> {t("previousStep")}</button> : null}{step < 3 ? <button className="action-button" disabled={step === 1 ? !stepOneValid : !stepTwoValid} onClick={() => setStep((step + 1) as 2 | 3)} type="button">{t("nextStep")} <ArrowRight size={16} /></button> : <button className="action-button" disabled={!formValid || submitting} onClick={submit} type="button">{submitting ? <LoaderCircle className="spin" size={16} /> : <FolderSync size={16} />} {t("serviceCreate")}</button>}</div></footer>
      {discardOpen ? <div className="inline-confirm-backdrop"><div className="inline-confirm" role="alertdialog"><AlertTriangle size={22} /><div><strong>{t("serviceDiscardTitle")}</strong><small>{t("serviceDiscardHelp")}</small></div><div><button className="action-button secondary" onClick={() => setDiscardOpen(false)} type="button">{t("continueEditing")}</button><button className="action-button danger" onClick={onClose} type="button">{t("discardAndClose")}</button></div></div></div> : null}
    </section>
  </div>;
}
