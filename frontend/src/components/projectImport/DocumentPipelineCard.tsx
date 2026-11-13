"use client";

import Link from "next/link";
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, FilePlus2, FolderSync, Layers3, ListRestart, Loader2, RotateCcw, ShieldCheck } from "lucide-react";
import { StatusBadge } from "@/components/AppShell";
import { ChunkingIssueSummary } from "@/components/ChunkingIssueSummary";
import { DocumentChunkCount } from "@/components/DocumentChunkCount";
import { DropdownSelect } from "@/components/DropdownSelect";
import { FeedbackField, FeedbackMessage } from "@/components/FeedbackMessage";
import { FileProcessingStatus } from "@/components/FileProcessingStatus";
import type { CreatedKnowledgeDocument } from "@/components/KnowledgeSourceModals";
import { OCRBudgetStatus } from "@/components/OCRBudgetStatus";
import { PipelineElapsed } from "@/components/PipelineElapsed";
import { cleanupIsUnconfirmed, fileObservationMode } from "@/lib/manualExtraction";
import { formatCount } from "@/lib/numberFormat";
import { ocrFailureTone, ocrRetryBlockReasonKey } from "@/lib/ocrPresentation";
import { pipelineStepLabel } from "@/lib/pipelineSteps";
import type { useTerminalChunkCounts } from "@/lib/useTerminalChunkCounts";
import { extractionLabel, getReferenceSource, getSourceState, isReviewLockedVersionStatus, isWorkingVersion, normalizeVersion, pipelineStepProgress, pipelineStepStatusKind, pipelineStepStatusLabel, pipelineStepStats, publishStageAction, type DocumentItem, type PendingStatusChange } from "./importDocumentModel";
import type { ImportPageDeps } from "./pageDeps";

type DocumentPipelineCardProps = Pick<ImportPageDeps, "format" | "locale" | "t"> & {
  document: DocumentItem;
  localize: (message: string) => string;
  projectId: string;
  projectAccess: "loading" | "granted" | "denied" | "error";
  canStartExtraction: boolean;
  canEditLifecycle: boolean;
  terminalCounts: ReturnType<typeof useTerminalChunkCounts>;
  elapsedNow: number;
  elapsedEnabled: boolean;
  committedStatuses: Record<string, string>;
  pendingStatusChange: PendingStatusChange | null;
  statusSubmitting: boolean;
  manualStartPending: Record<string, boolean>;
  manualStartNotices: Record<string, { versionId?: string; unknown: boolean; message: string }>;
  pipelineDetailLoading: Record<string, boolean>;
  pipelineRetryNotices: Record<string, { pipelineId: string; message: string }>;
  startManualExtraction: (documentId: string) => Promise<void>;
  retryLivePipelineStep: (document: CreatedKnowledgeDocument, stepName?: string | null) => Promise<void>;
  requestStatusChange: (document: DocumentItem, requestedStatus: string, currentStatus: string) => Promise<void>;
  setVersionDocumentId: (documentId: string | null) => void;
};

/** One document card in the project import document list: JSX moved verbatim from the page (OPT424-038). */
export function DocumentPipelineCard(props: DocumentPipelineCardProps) {
  const { document, t, format, locale, localize, projectId, projectAccess, canStartExtraction, canEditLifecycle, terminalCounts, elapsedNow, elapsedEnabled, committedStatuses, pendingStatusChange, statusSubmitting, manualStartPending, manualStartNotices, pipelineDetailLoading, pipelineRetryNotices, startManualExtraction, retryLivePipelineStep, requestStatusChange, setVersionDocumentId } = props;
    const sourceState = getSourceState(document);
    const pipeline = document.pipeline;
    const displayedVersion = sourceState === "syncing" && document.versions.length === 0 ? t("projectImportVersionPending") : normalizeVersion(document.version);
    const displayedVersionStatus = document.versionStatus;
    const reviewLocked = isReviewLockedVersionStatus(displayedVersionStatus);
    const waitingForAction = pipeline.status === "waiting_action";
    const cardSteps = "steps" in document.pipeline ? document.pipeline.steps : undefined;
    const stepStats = cardSteps?.length ? pipelineStepStats(cardSteps) : null;
    const failedStep = cardSteps?.find((step) => step.status === "failed");
    const retryLimitReached = (failedStep?.retryCount ?? 0) >= 3;
    const retryBlockedReason = retryLimitReached ? null : ocrRetryBlockReasonKey(failedStep?.ocr);
    const retryDescriptionId = `pipeline-retry-reason-${document.id}`;
    const retryNotice = pipelineRetryNotices[document.id]?.pipelineId === pipeline.id ? pipelineRetryNotices[document.id]?.message : undefined;
    const committedStatus = committedStatuses[document.id] ?? document.documentStatus;
    const effectiveStatus = committedStatus === "deleted" ? "deleted" : waitingForAction ? "inactive" : committedStatus;
    const activeVersion = document.versions.find((version) => version.status === "active")?.label;
    const workingVersion = document.versions.find((version) => isWorkingVersion(version.status))?.label;
    const referenceSource = getReferenceSource(document);
    const stageAction = publishStageAction(pipeline.status, projectId, document.id, t);
    const startNotice = manualStartNotices[document.id]?.versionId === document.latestVersionId ? manualStartNotices[document.id] : undefined;
    const startDisabled = reviewLocked || !canStartExtraction || !document.isLive || !document.latestVersionId
      || document.documentStatus === "deleted" || manualStartPending[document.id] || startNotice?.unknown;
  return (
    <article className="document-pipeline-card">
      <div className="document-pipeline-head">
        <div className="row-title">
          <FilePlus2 size={18} />
          <div>
            <strong>{document.title}</strong>
            <small>{displayedVersion} · {document.sourceType} · {t("projectImportOwner")} {document.owner} · {t("projectImportUpdated")} {document.updatedAt}</small>
            <span className="document-version-roles">
              {activeVersion ? <em className="version-role-active"><CheckCircle2 size={12} /> {t("statusActive")}：{activeVersion}</em> : null}
              {workingVersion && workingVersion !== activeVersion ? <em className="version-role-working"><Clock3 size={12} /> {t("projectImportWorkingVersion")}：{workingVersion}</em> : null}
            </span>
            {referenceSource ? <span className="reference-project-name"><Layers3 size={13} /> {t("projectImportReferenceSource")}：{referenceSource.projectName}</span> : null}
            {referenceSource?.pendingEventCount ? (
              <span className="reference-update-note"><AlertTriangle size={13} /> {format("projectImportReferencePendingEvents", { count: referenceSource.pendingEventCount })}</span>
            ) : referenceSource && referenceSource.latestActiveVersion !== referenceSource.snapshotVersion ? (
              <span className="reference-update-note"><AlertTriangle size={13} /> {format("projectImportReferenceUpdateNote", { version: referenceSource.latestActiveVersion })}</span>
            ) : null}
          </div>
        </div>
        <div className="document-actions">
          {sourceState === "syncing" ? (
            <span className="source-action-disabled"><FolderSync size={16} /> {t("projectImportSyncing")}</span>
          ) : sourceState === "ready_for_extraction" && reviewLocked ? (
            <span className="source-action-disabled"><ShieldCheck size={16} /> {t("projectImportReviewExtractionLocked")}</span>
          ) : sourceState === "ready_for_extraction" ? (
            <button className="text-link" disabled={Boolean(startDisabled)} onClick={() => startManualExtraction(document.id)} type="button">
              {t("knowledgeExtraction")} <ArrowRight size={16} />
            </button>
          ) : (
            <Link className="text-link" href={`/project/${projectId}/knowledge/${document.id}`}>
              {t("knowledgeExtraction")} <ArrowRight size={16} />
            </Link>
          )}
        </div>
      </div>

      <div className="document-pipeline-body">
        {startNotice ? <p className="upload-progress-notice" role="alert">{localize(startNotice.message)}</p> : null}
        {manualStartPending[document.id] ? <p className="upload-progress-notice" role="status">{t("projectImportExtractionStarting")}</p> : null}
        {sourceState === "syncing" || sourceState === "ready_for_extraction" ? (
          <div className={`source-state-card ${sourceState}`}>
            {sourceState === "syncing" ? <FolderSync size={18} /> : <Clock3 size={18} />}
            <div>
              <strong>{sourceState === "syncing" ? t("projectImportSyncingTitle") : t("projectImportReadyExtractionTitle")}</strong>
              <small>{reviewLocked ? t("projectImportReviewExtractionLockedHelp") : sourceState === "syncing" ? t("projectImportSyncingHelp") : t("projectImportReadyExtractionCardHelp")}</small>
              {"serviceSource" in document && document.serviceSource ? <span>{document.serviceSource.location} · {document.serviceSource.scheduleMode === "cron" ? `${document.serviceSource.cronExpression} / ${document.serviceSource.timezone}` : t("projectImportOneTimeSync")}</span> : null}
            </div>
	                    <div className="source-state-actions">
	                      <button className="action-button secondary" onClick={() => setVersionDocumentId(document.id)} type="button"><ListRestart size={16} /> {t("projectImportVersionManagement")}</button>
	                      {sourceState === "ready_for_extraction" ? <button className="action-button" disabled={Boolean(startDisabled)} onClick={() => startManualExtraction(document.id)} title={reviewLocked ? t("projectImportReviewExtractionLockedHelp") : undefined} type="button"><ArrowRight size={16} /> {t("projectImportStartExtraction")}</button> : null}
	                      <button className="action-button danger" disabled={!canEditLifecycle || pendingStatusChange?.documentId === document.id || statusSubmitting} onClick={() => { void requestStatusChange(document, "deleted", committedStatuses[document.id] ?? document.documentStatus); }} title={!canEditLifecycle ? t("projectImportMissingLifecyclePermission") : undefined} type="button"><AlertTriangle size={16} /> {t("delete")}</button>
	                    </div>
          </div>
        ) : <>
        <div className="pipeline-summary">
          <DocumentChunkCount state={terminalCounts.state(document)} count={document.chunks} canRetry={projectAccess === "granted"} onRetry={() => terminalCounts.retry(document)} />
          <span>{t("pipelineCurrentStep")}：{localize(pipeline.currentStep)}</span>
          <FileProcessingStatus execution={pipeline.execution} queued={pipeline.status === "queued"}
            cleanupUnconfirmed={cleanupIsUnconfirmed(document)} />
          <PipelineElapsed pipeline={pipeline} now={elapsedNow} enabled={elapsedEnabled} locale={locale} />
          {!pipeline.execution ? <span>{t("pipelineEta")}：{localize(pipeline.eta)}</span> : null}
          {pipeline.waitingRole ? <span>{t("pipelineWaiting")}：{localize(pipeline.waitingRole)}</span> : null}
        </div>
        <div className="progress-line document-progress">
          <span style={{ width: `${pipeline.progress}%` }} />
        </div>
        <div className="document-pipeline-footer">
          <div className="document-pipeline-status">
            <StatusBadge status={pipeline.status} />
            {pipeline.status === "completed"
              && pipeline.progress === 100
              && document.documentStatus === "active"
              && displayedVersionStatus === "active" ? (
                <span className="pipeline-active-state"><CheckCircle2 size={14} /> {t("statusActive")}</span>
              ) : null}
          </div>
          <span>{pipeline.progress}%</span>
          {pipeline.observationInterrupted ? (
            <FeedbackMessage tone="error"> {t("uploadProgressInterrupted")}</FeedbackMessage>
          ) : pipeline.error ? (
            <FeedbackMessage tone={ocrFailureTone({ error_code: pipeline.steps?.find(step => step.status === "failed")?.errorCode })}> {localize(pipeline.error)}</FeedbackMessage>
          ) : (
            <span className="ready-summary"><Clock3 size={15} /> {t(document.sourceType === "File upload" && !fileObservationMode(document)
              ? "projectImportPipelineLastConfirmed" : "projectImportPipelineLiveUpdating")}</span>
          )}
          {pipeline.status === "failed" ? (
            <button className="action-button secondary" aria-describedby={retryBlockedReason ? retryDescriptionId : undefined} disabled={reviewLocked || !failedStep || retryLimitReached || Boolean(retryBlockedReason) || pipelineDetailLoading[document.id]} onClick={() => { void retryLivePipelineStep(document as CreatedKnowledgeDocument, failedStep?.name); }} title={reviewLocked ? t("projectImportReviewExtractionLockedHelp") : retryBlockedReason ? t(retryBlockedReason) : undefined} type="button">
              {pipelineDetailLoading[document.id] ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />} {pipelineDetailLoading[document.id] ? t("knowledgeDetailRetryingStep") : retryLimitReached ? t("projectImportRetryLimitReached") : retryBlockedReason ? t("ocrRetryDisabled") : t("pipelineRetryFailedStep")}
            </button>
          ) : null}
          {reviewLocked ? <span className="ready-summary"><ShieldCheck size={15} /> {t("projectImportReviewExtractionLocked")}</span> : null}
          {stageAction ? (
            <Link className="action-button secondary" href={stageAction.href}>
              <ArrowRight size={16} /> {stageAction.label}
            </Link>
          ) : null}
          <div className="document-management-actions">
            <button className="action-button secondary" onClick={() => setVersionDocumentId(document.id)} type="button">
              <ListRestart size={16} /> {t("projectImportVersionManagement")}
            </button>
	                    <DropdownSelect
	                      aria-label={format("projectImportDocumentStatusAria", { title: document.title })}
	                      className="status-select"
	                      disabled={!canEditLifecycle || pendingStatusChange?.documentId === document.id || statusSubmitting}
	                      onChange={(event) => { void requestStatusChange(document, event.target.value, effectiveStatus); }}
	                      title={!canEditLifecycle ? t("projectImportMissingLifecyclePermission") : undefined}
	                      value={effectiveStatus}
	                    >
              {waitingForAction ? (
                <>
                  {effectiveStatus !== "deleted" ? <option value="inactive">{t("projectImportStatusInactive")}</option> : null}
                  <option value="deleted">{t("delete")}</option>
                </>
              ) : document.hasActiveVersion ? (
                <>
                  <option value="active">{t("projectImportStatusActive")}</option>
                  <option value="inactive">{t("projectImportStatusInactive")}</option>
                  <option value="deleted">{t("delete")}</option>
                </>
              ) : (
                <>
                  <option disabled value={document.documentStatus}>{t(extractionLabel(document.extractionOutcome))}</option>
                  <option value="deleted">{t("delete")}</option>
                </>
              )}
            </DropdownSelect>
          </div>
        </div>
        {pipeline.status === "failed" ? <>
          <OCRBudgetStatus step={failedStep?.ocr} />
          <ChunkingIssueSummary issue={failedStep?.ocr?.chunking_issue} />
          {retryBlockedReason ? <p className="document-retry-notice" id={retryDescriptionId} role="status">{t(retryBlockedReason)}</p> : null}
          {retryNotice ? <FeedbackField>{retryNotice}</FeedbackField> : null}
        </> : null}
        {cardSteps?.length ? (
          <details className="pipeline-step-detail">
            <summary>{t("projectImportPipelineStepDetails")}</summary>
            {stepStats ? (
              <div className="pipeline-step-overview" aria-label={format("projectImportPipelineStepOverviewAria", { completed: stepStats.completed, total: stepStats.total, percent: stepStats.percent })}>
                <div>
                  <strong>{format("projectImportPipelineStepProgress", { completed: formatCount(stepStats.completed, locale), total: formatCount(stepStats.total, locale) })}</strong>
                  <small>{format("projectImportPipelineStepOverall", { percent: stepStats.percent })}</small>
                </div>
                <span className="step-overview-pill completed"><CheckCircle2 size={13} /> {format("projectImportPipelineStepCompletedCount", { count: formatCount(stepStats.completed, locale) })}</span>
                <span className="step-overview-pill active"><Clock3 size={13} /> {format("projectImportPipelineStepActiveCount", { count: formatCount(stepStats.active, locale) })}</span>
                <span className={`step-overview-pill ${stepStats.failed ? "failed" : "neutral"}`}><AlertTriangle size={13} /> {format("projectImportPipelineStepFailedCount", { count: formatCount(stepStats.failed, locale) })}</span>
              </div>
            ) : null}
            <table className="feedback-step-table">
              <thead><tr><th>{t("pipelineCurrentStep")}</th><th>{t("systemStatusColumn")}</th><th>{t("knowledgeDetailPipelineProgress")}</th><th>{t("systemDetails")}</th></tr></thead>
              <tbody>{cardSteps.map((step, index) => {
                const statusKind = pipelineStepStatusKind(step.status), progress = pipelineStepProgress(step);
                return <tr key={step.name}>
                  <th scope="row"><span className="feedback-step-number">{index + 1}</span>{pipelineStepLabel(step.name, t)}</th>
                  <td><span className={`feedback-step-status feedback-${statusKind === "failed" ? "error" : statusKind === "completed" ? "success" : "info"}`}>
                    {statusKind === "completed" ? <CheckCircle2 size={14} /> : statusKind === "failed" ? <AlertTriangle size={14} /> : <Clock3 size={14} />}{pipelineStepStatusLabel(step.status, t)}
                  </span></td>
                  <td><div className="pipeline-step-progress" role="progressbar" aria-label={pipelineStepLabel(step.name, t)} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div><small>{progress}% · {format("projectImportRetryCount", { count: formatCount(step.retryCount, locale) })}</small></td>
                  <td>{step.error ? <FeedbackField>{localize(step.error)}</FeedbackField> : null}{step.artifactRef ? <details className="pipeline-step-technical"><summary>{t("pipelineTechnicalDetails")}</summary><code className="pipeline-step-artifact">{step.artifactRef}</code></details> : null}</td>
                </tr>;
              })}</tbody>
            </table>
          </details>
        ) : null}
        </>}
      </div>
    </article>
  );
}
