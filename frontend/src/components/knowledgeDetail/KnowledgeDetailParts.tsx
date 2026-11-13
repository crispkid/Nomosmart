"use client";

import { type ContentUpdateFeedback } from "@/lib/contentUpdateFeedback";
import { FeedbackField, feedbackIcons } from "@/components/FeedbackMessage";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, Edit3, FileText, Loader2, Plus, RotateCcw, Trash2, Wand2 } from "lucide-react";
import { ChunkMarkdownView } from "@/components/ChunkMarkdownView";
import { FileProcessingStatus } from "@/components/FileProcessingStatus";
import { OCRBudgetStatus } from "@/components/OCRBudgetStatus";
import { ChunkingIssueSummary } from "@/components/ChunkingIssueSummary";
import { ocrRetryBlockReasonKey } from "@/lib/ocrPresentation";
import { type KnowledgeDetailResponse, type KnowledgeTagResponse } from "@/lib/api";
import { pipelineStepLabel } from "@/lib/pipelineSteps";
import { type Translate, type Format, type KnowledgeChunk, layoutUnavailableLabel, isPipelineActive, failedPipelineStep, pipelineFailureKey, imageOcrRetryBlocked } from "./knowledgeDetailModel";

/* Knowledge detail page presentational parts (split from the page, OPT424-038). */

export function ChunkPreview({ chunk }: { chunk: KnowledgeChunk }) {
  return (
    <ChunkMarkdownView
      chunk={{
        content: chunk.content,
        display_markdown: chunk.displayMarkdown,
        markdown_content: chunk.markdownContent,
      }}
      className="chunk-safe-markdown"
    />
  );
}

export function TagResultStrip({ className = "", label, tags, t }: { className?: string; label: string; tags: KnowledgeTagResponse[]; t: Translate }) {
  return (
    <div aria-label={label} className={`tag-result-strip ${className}`}>
      <span className="tag-result-strip-label">{label}</span>
      <div className="tag-result-strip-list">
        {tags.length ? tags.map((tag) => (
          <span className={`knowledge-tag-chip tag-source-${tag.source}`} key={tag.tag_id}>
            <em>{tag.tag_text}</em>
            <small>{tag.source}</small>
          </span>
        )) : <small>{t("knowledgeDetailNoTags")}</small>}
      </div>
    </div>
  );
}

export function LayoutPipelineFallback({ detail, retryingStep, retryError, reviewLocked, onRetry, t, format, embedded = false }: { detail: KnowledgeDetailResponse | null; retryingStep: string | null; retryError: boolean; reviewLocked: boolean; onRetry: (stepName: string) => void; t: Translate; format: Format; embedded?: boolean }) {
  const pipeline = detail?.pipeline ?? null;
  const failedStep = failedPipelineStep(pipeline);
  const active = isPipelineActive(pipeline);
  const currentStepName = failedStep?.step_name ?? pipeline?.current_step_name ?? null;
  const imageOcrStep = pipeline?.steps.find(step => step.step_name === "ocr_extract" && (step.input_mode === "page_images" || step.input_mode === "native_pdf"));
  const nativePending = imageOcrStep?.input_mode === "native_pdf" && imageOcrStep.status !== "completed";
  const progress = Math.max(0, Math.min(100, Math.round(pipeline?.progress_percent ?? 0)));
  const retryLimitReached = (failedStep?.retry_count ?? 0) >= 3;
  const canRetry = Boolean(detail && pipeline?.id && detail.version.id && failedStep && !reviewLocked && !retryLimitReached && !imageOcrRetryBlocked(failedStep) && detail.content_update?.status !== "blocked");

  return (
    <div className={embedded ? "knowledge-detail-gate-body" : `pipeline-layout-fallback ${failedStep ? "failed" : active ? "running" : "idle"}`}>
      {!embedded ? <div className="pipeline-layout-icon" aria-hidden="true">
        {active ? <Loader2 className="spin" size={22} /> : failedStep ? <AlertTriangle size={22} /> : <FileText size={22} />}
      </div> : null}
      <div className="pipeline-layout-content">
        {!embedded ? <><strong>{active ? t("knowledgeDetailPipelineGeneratingLayout") : failedStep ? t("knowledgeDetailPipelineFailedTitle") : t("knowledgeDetailPipelineWaitingTitle")}</strong>
        <p>{active ? t("knowledgeDetailPipelineGeneratingLayoutHelp") : failedStep ? t("knowledgeDetailPipelineFailedHelp") : layoutUnavailableLabel(detail?.document_layout?.status, t)}</p></> : null}
        <div className="pipeline-progress-row">
          <span>{pipelineStepLabel(currentStepName, t)}</span>
          {!nativePending ? <span>{format("knowledgeDetailPipelineProgressPercent", { percent: progress })}</span> : null}
        </div>
        {!nativePending ? <div className="pipeline-progress-track" aria-label={t("knowledgeDetailPipelineProgress")} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
          <span style={{ width: `${progress}%` }} />
        </div> : null}
        <FileProcessingStatus execution={pipeline?.execution} queued={pipeline?.status === "queued"} />
        <OCRBudgetStatus step={imageOcrStep} />
        <ChunkingIssueSummary issue={failedStep?.chunking_issue} />
        {!failedStep?.chunking_issue && (failedStep?.error_message || pipeline?.error_message) ? <FeedbackField>{t(pipelineFailureKey(failedStep, failedStep?.error_message ?? pipeline?.error_message))}</FeedbackField> : null}
        {imageOcrRetryBlocked(failedStep) ? <small className="field-note">{t(ocrRetryBlockReasonKey(failedStep) ?? "ocrImagePartialReview")}</small> : null}
        {reviewLocked ? <small className="field-note">{t("knowledgeDetailReviewLockedReason")}</small> : null}
        {retryLimitReached ? <small className="field-note">{t("knowledgeDetailRetryLimitReached")}</small> : null}
        {retryError ? <FeedbackField>{t("knowledgeDetailRetryFailed")}</FeedbackField> : null}
        {!embedded && canRetry && failedStep ? (
          <button className="action-button secondary" disabled={retryingStep === failedStep.step_name} type="button" onClick={() => onRetry(failedStep.step_name)}>
            {retryingStep === failedStep.step_name ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />} {retryingStep === failedStep.step_name ? t("knowledgeDetailRetryingStep") : t("knowledgeDetailRetryFailedStep")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function KnowledgeDetailCompletionGate({ detail, projectId, retryingStep, retryError, reviewLocked, onRetry, onEdit, t, format, contentFeedback }: { detail: KnowledgeDetailResponse; projectId: string; retryingStep: string | null; retryError: boolean; reviewLocked: boolean; onRetry: (stepName: string) => void; onEdit: () => void; t: Translate; format: Format; contentFeedback: ContentUpdateFeedback | null }) {
  const failedStep = failedPipelineStep(detail.pipeline);
  const retryLimitReached = (failedStep?.retry_count ?? 0) >= 3;
  const activelyProcessing = isPipelineActive(detail.pipeline) && detail.pipeline?.execution?.phase !== "recovery_required";
  const canRetry = Boolean(detail.pipeline?.id && failedStep && !reviewLocked && !retryLimitReached && !imageOcrRetryBlocked(failedStep) && detail.content_update?.status !== "blocked");
  const tone = contentFeedback?.tone ?? (failedStep ? "error" : activelyProcessing ? "info" : "warning");
  const Icon = feedbackIcons[tone];
  return (
    <section className={`knowledge-detail-gate feedback-workflow feedback-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <div className="knowledge-detail-gate-heading">
        <span aria-hidden="true">{contentFeedback ? <Icon size={24} /> : activelyProcessing ? <Loader2 className="spin" size={24} /> : <AlertTriangle size={24} />}</span>
        <div>
          <strong>{failedStep ? t("knowledgeDetailPipelineFailedTitle") : t("knowledgeDetailCompletionGateTitle")}</strong>
          <p>{contentFeedback ? t(contentFeedback.message) : failedStep ? t("knowledgeDetailPipelineFailedHelp") : t("knowledgeDetailCompletionGateHelp")}</p>
        </div>
      </div>
      <LayoutPipelineFallback embedded detail={detail} format={format} onRetry={onRetry} retryError={retryError} retryingStep={retryingStep} reviewLocked={reviewLocked} t={t} />
      <div className="knowledge-detail-gate-actions">
        {detail.content_edit_mode === "overwrite_candidate" && detail.document.capabilities?.can_edit_chunks ? <button className="action-button" type="button" onClick={onEdit}><Edit3 size={16} />{t("contentEditAction")}</button> : null}
        {canRetry && failedStep ? <button className="action-button secondary" disabled={retryingStep === failedStep.step_name} type="button" onClick={() => onRetry(failedStep.step_name)}>
          {retryingStep === failedStep.step_name ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />} {retryingStep === failedStep.step_name ? t("knowledgeDetailRetryingStep") : t("knowledgeDetailRetryFailedStep")}
        </button> : null}
        <Link className="action-button secondary" href={`/project/${projectId}/import`}>
          <ArrowLeft size={16} /> {t("knowledgeDetailBackToDocuments")}
        </Link>
      </div>
    </section>
  );
}

export function TagEditor({
  tags,
  label,
  draft,
  disabled,
  busy,
  onDraft,
  onAdd,
  onAuto,
  onDelete,
  t
}: {
  tags: KnowledgeTagResponse[];
  label?: string;
  draft: string;
  disabled: boolean;
  busy: boolean;
  onDraft: (value: string) => void;
  onAdd: () => void;
  onAuto: () => void;
  onDelete: (tagId: string) => void;
  t: Translate;
}) {
  const [adding, setAdding] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (adding) inputRef.current?.focus();
  }, [adding]);

  function submitInlineTag() {
    if (!draft.trim() || disabled || busy) return;
    onAdd();
    setAdding(false);
  }

  return (
    <div className="knowledge-tag-editor" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
      {label ? <span className="knowledge-tag-editor-label">{label}</span> : null}
      <div className="knowledge-tag-list">
        {tags.length ? tags.map((tag) => (
          <span className={`knowledge-tag-chip tag-source-${tag.source}`} key={tag.tag_id}>
            <em>{tag.tag_text}</em>
            <small>{tag.source}</small>
            <button aria-label={`${t("knowledgeDetailDeleteTag")} ${tag.tag_text}`} disabled={disabled || busy} onClick={() => onDelete(tag.tag_id)} type="button"><Trash2 size={12} /></button>
          </span>
        )) : <small>{t("knowledgeDetailNoTags")}</small>}
        {adding ? (
          <input
            aria-label={t("knowledgeDetailTagInputPlaceholder")}
            className="knowledge-tag-inline-input"
            disabled={disabled || busy}
            maxLength={80}
            onBlur={() => {
              if (!draft.trim()) setAdding(false);
            }}
            onChange={(event) => onDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submitInlineTag();
              }
              if (event.key === "Escape") {
                event.preventDefault();
                onDraft("");
                setAdding(false);
              }
            }}
            placeholder={t("knowledgeDetailTagInputPlaceholder")}
            ref={inputRef}
            value={draft}
          />
        ) : (
          <button className="knowledge-tag-add-button" disabled={disabled || busy} onClick={() => setAdding(true)} title={t("knowledgeDetailAddTag")} type="button"><Plus size={15} /></button>
        )}
        <button className="knowledge-tag-auto-button" disabled={disabled || busy} onClick={onAuto} title={t("knowledgeDetailAutoTag")} type="button">{busy ? <Loader2 className="spin" size={15} /> : <Wand2 size={15} />}</button>
      </div>
    </div>
  );
}
