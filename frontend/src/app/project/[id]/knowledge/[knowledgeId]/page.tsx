"use client";

import { type KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Code2, Download, Edit3, FileText, Loader2, Network, Plus, RotateCcw, Tags, Trash2, Wand2, X } from "lucide-react";
import { AppShell, Panel, StatusBadge } from "@/components/AppShell";
import { CanonicalMarkdownSource } from "@/components/CanonicalMarkdownSource";
import { ChunkMarkdownView } from "@/components/ChunkMarkdownView";
import { useAuth } from "@/components/AuthProvider";
import { DocumentLayoutViewer } from "@/components/DocumentLayoutViewer";
import { FileProcessingStatus } from "@/components/FileProcessingStatus";
import { KnowledgeReadinessNotice } from "@/components/KnowledgeReadinessNotice";
import { isPollingAuthorizationFailure, startFileProcessingPolling } from "@/lib/fileProcessingPolling";
import { KnowledgeDetailReads, KnowledgeReadinessBudget, acceptsKnowledgeRead, knowledgeReadinessKey, needsKnowledgeReadinessCheck } from "@/lib/knowledgeReadiness";
import { VersionGraphPreview } from "@/components/VersionGraphPreview";
import { SafeMarkdown } from "@/components/SafeMarkdown";
import { addChunkTag, addDocumentTag, autoTagChunk, autoTagDocument, createManualChunk, deleteChunkTag, deleteDocumentTag, deleteKnowledgeChunk, getKnowledgeArtifactBlob, getKnowledgeDetail, retryPipelineStep, type ApprovalChunkEvidence, type KnowledgeDetailResponse, type KnowledgeTagResponse, type OriginalFileViewerMetadata, type PipelineRunDetail } from "@/lib/api";
import { t as translate } from "@/lib/i18n";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { mappedSelectionRange } from "@/lib/manualSourceSelection";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { chunkIdsForResolvedSourceAnchor, codePointLength, markdownArtifactReasonKey, resolvedSourceMappings, sourceAnchorsForChunks, sourceSelectionGroupsForChunks, sourceSelectionScrollBehavior, type ResolvedSourceMapping } from "@/lib/markdownSourceMapping";

type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;

type KnowledgeChunk = {
  id: string;
  index: number;
  title: string;
  type: "text" | "image" | "table" | "chart";
  sourceAnchor: string;
  sourceMappings: ResolvedSourceMapping[];
  sourceLabel: string;
  content: string;
  displayMarkdown: string | null;
  markdownContent: string | null;
  tokens: number;
  confidence: number;
  tags: string[];
  tagDetails: KnowledgeTagResponse[];
};

type ArticleView = "original" | "markdown";
type DocumentView = ArticleView | "tags";

type ManualTextSelection = {
  content: string;
  viewMode: ArticleView;
  sourceAnchor: string;
  startOffset: number;
  endOffset: number;
  offsetScope: "canonical_markdown" | "source_anchor";
  top: number;
  left: number;
};

function sourceAnchor(chunk: ApprovalChunkEvidence) {
  const resolved = resolvedSourceMappings(chunk.source_mapping)[0];
  if (resolved) return resolved.sourceAnchor;
  const firstMapping = chunk.source_mapping[0] as Record<string, unknown> | undefined;
  const mappedAnchor = firstMapping?.sourceAnchor ?? firstMapping?.source_anchor ?? firstMapping?.anchor;
  return typeof mappedAnchor === "string" && mappedAnchor ? mappedAnchor : `chunk-${chunk.chunk_index}`;
}

function sourceLabel(chunk: ApprovalChunkEvidence, t: Translate, format: Format) {
  const firstMapping = chunk.source_mapping[0] as Record<string, unknown> | undefined;
  const page = firstMapping?.page ?? firstMapping?.page_number;
  if (typeof page === "number" || typeof page === "string") return format("knowledgeDetailOriginalPage", { page });
  return format("knowledgeDetailChunkLabel", { number: chunk.chunk_index });
}

function chunkType(contentType: string): KnowledgeChunk["type"] {
  if (contentType === "image" || contentType === "table" || contentType === "chart") return contentType;
  return "text";
}

function displayChunkTitle(title: string | null | undefined, chunkIndex: number, format: Format) {
  const fallback = format("knowledgeDetailChunkTitle", { number: chunkIndex });
  const candidate = title?.trim() || fallback;
  return candidate.replace(new RegExp(`\\s+#${chunkIndex}\\s*$`), "").trim() || fallback;
}

function visibleTagDetails(tags: KnowledgeTagResponse[]) {
  return tags.filter((tag) => tag.source !== "rule");
}

function liveChunk(chunk: ApprovalChunkEvidence, t: Translate, format: Format): KnowledgeChunk {
  const tagDetails = chunk.tag_details ?? chunk.tags.map((tag, index) => ({ tag_id: `${chunk.id}-${index}`, tag_text: tag, source: "legacy", confidence_score: null, metadata: {}, created_by: null, created_at: "" }));
  return {
    id: chunk.id,
    index: chunk.chunk_index,
    title: displayChunkTitle(chunk.title, chunk.chunk_index, format),
    type: chunkType(chunk.content_type),
    sourceAnchor: sourceAnchor(chunk),
    sourceMappings: resolvedSourceMappings(chunk.source_mapping),
    sourceLabel: sourceLabel(chunk, t, format),
    content: chunk.content,
    displayMarkdown: chunk.display_markdown,
    markdownContent: chunk.markdown_content,
    tokens: chunk.token_count ?? 0,
    confidence: chunk.confidence_score ?? 0,
    tags: visibleTagDetails(tagDetails).map((tag) => tag.tag_text),
    tagDetails: visibleTagDetails(tagDetails)
  };
}

function ChunkPreview({ chunk }: { chunk: KnowledgeChunk }) {
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

function TagResultStrip({ className = "", label, tags, t }: { className?: string; label: string; tags: KnowledgeTagResponse[]; t: Translate }) {
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

function isMarkdownOriginal(metadata: OriginalFileViewerMetadata | null | undefined) {
  return metadata?.viewer_type === "markdown" && metadata.markdown_source_mode === "rendered_original_raw_markdown";
}

function artifactUnavailableLabel(metadata: OriginalFileViewerMetadata | null | undefined, t: Translate) {
  if (!metadata) return t("knowledgeDetailOriginalUnavailable");
  if (metadata.preview_error_code === "original_file_missing") return t("knowledgeDetailOriginalMissing");
  if (metadata.viewer_type === "unsupported") return t("knowledgeDetailPreviewUnsupported");
  return t("knowledgeDetailOriginalUnavailable");
}

function layoutUnavailableLabel(status: string | undefined, t: Translate) {
  if (status === "partial") return t("knowledgeDetailLayoutPartial");
  if (status === "failed") return t("knowledgeDetailLayoutFailed");
  return t("knowledgeDetailLayoutUnavailable");
}

function isPipelineActive(pipeline: PipelineRunDetail | null | undefined) {
  return Boolean(pipeline && ["running", "processing", "waiting_action", "queued"].includes(pipeline.status));
}

function failedPipelineStep(pipeline: PipelineRunDetail | null | undefined) {
  return pipeline?.steps.find((step) => step.status === "failed") ?? null;
}

const KNOWLEDGE_DETAIL_GATE_READY_STATUSES = new Set([
  "submission_ready",
  "pending_manager_review",
  "pending_owner_review",
  "approved",
  "publish_ready",
  "ready_to_publish",
  "publishing",
  "production_indexing",
  "graph_syncing",
  "published_active",
  "published",
  "active",
  "completed",
  "review_rejected"
]);

function completionGateBlocksKnowledgeDetail(detail: KnowledgeDetailResponse | null) {
  const pipeline = detail?.pipeline;
  if (!pipeline) return false;
  if (KNOWLEDGE_DETAIL_GATE_READY_STATUSES.has(pipeline.status)) return false;
  return true;
}

function shouldPollKnowledgeCompletionGate(detail: KnowledgeDetailResponse | null) {
  const pipeline = detail?.pipeline;
  if (!pipeline || !completionGateBlocksKnowledgeDetail(detail)) return false;
  if (pipeline.status === "failed" || failedPipelineStep(pipeline)) return false;
  return isPipelineActive(pipeline);
}

function pipelineStepLabel(stepName: string | null | undefined, t: Translate) {
  if (!stepName) return t("knowledgeDetailPipelineStepUnknown");
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
  const key = labels[stepName];
  return key ? t(key) : stepName.replace(/_/g, " ");
}

function LayoutPipelineFallback({ detail, retryingStep, retryError, reviewLocked, onRetry, t, format }: { detail: KnowledgeDetailResponse | null; retryingStep: string | null; retryError: boolean; reviewLocked: boolean; onRetry: (stepName: string) => void; t: Translate; format: Format }) {
  const pipeline = detail?.pipeline ?? null;
  const failedStep = failedPipelineStep(pipeline);
  const active = isPipelineActive(pipeline);
  const currentStepName = failedStep?.step_name ?? pipeline?.current_step_name ?? null;
  const progress = Math.max(0, Math.min(100, Math.round(pipeline?.progress_percent ?? 0)));
  const retryLimitReached = (failedStep?.retry_count ?? 0) >= 3;
  const canRetry = Boolean(detail && pipeline?.id && detail.version.id && failedStep && !reviewLocked && !retryLimitReached);

  return (
    <div className={`pipeline-layout-fallback ${failedStep ? "failed" : active ? "running" : "idle"}`}>
      <div className="pipeline-layout-icon" aria-hidden="true">
        {active ? <Loader2 className="spin" size={22} /> : failedStep ? <AlertTriangle size={22} /> : <FileText size={22} />}
      </div>
      <div className="pipeline-layout-content">
        <strong>{active ? t("knowledgeDetailPipelineGeneratingLayout") : failedStep ? t("knowledgeDetailPipelineFailedTitle") : t("knowledgeDetailPipelineWaitingTitle")}</strong>
        <p>{active ? t("knowledgeDetailPipelineGeneratingLayoutHelp") : failedStep ? t("knowledgeDetailPipelineFailedHelp") : layoutUnavailableLabel(detail?.document_layout?.status, t)}</p>
        <div className="pipeline-progress-row">
          <span>{pipelineStepLabel(currentStepName, t)}</span>
          <span>{format("knowledgeDetailPipelineProgressPercent", { percent: progress })}</span>
        </div>
        <div className="pipeline-progress-track" aria-label={t("knowledgeDetailPipelineProgress")} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
          <span style={{ width: `${progress}%` }} />
        </div>
        <FileProcessingStatus execution={pipeline?.execution} queued={pipeline?.status === "queued"} />
        {failedStep?.error_message || pipeline?.error_message ? <p className="pipeline-error-message">{t("apiGenericError")}</p> : null}
        {reviewLocked ? <small className="field-note">{t("knowledgeDetailReviewLockedReason")}</small> : null}
        {retryLimitReached ? <small className="field-note">{t("knowledgeDetailRetryLimitReached")}</small> : null}
        {retryError ? <small className="field-error">{t("knowledgeDetailRetryFailed")}</small> : null}
        {canRetry && failedStep ? (
          <button className="action-button secondary" disabled={retryingStep === failedStep.step_name} type="button" onClick={() => onRetry(failedStep.step_name)}>
            {retryingStep === failedStep.step_name ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />} {retryingStep === failedStep.step_name ? t("knowledgeDetailRetryingStep") : t("knowledgeDetailRetryFailedStep")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function KnowledgeDetailCompletionGate({ detail, projectId, retryingStep, retryError, reviewLocked, onRetry, t, format }: { detail: KnowledgeDetailResponse; projectId: string; retryingStep: string | null; retryError: boolean; reviewLocked: boolean; onRetry: (stepName: string) => void; t: Translate; format: Format }) {
  const failedStep = failedPipelineStep(detail.pipeline);
  const progress = Math.max(0, Math.min(100, Math.round(detail.pipeline?.progress_percent ?? 0)));
  return (
    <section className={`knowledge-detail-gate${failedStep ? " failed" : ""}`} aria-live="polite">
      <div className="knowledge-detail-gate-heading">
        <span aria-hidden="true">{failedStep ? <AlertTriangle size={24} /> : <Loader2 className="spin" size={24} />}</span>
        <div>
          <strong>{failedStep ? t("knowledgeDetailPipelineFailedTitle") : t("knowledgeDetailCompletionGateTitle")}</strong>
          <p>{failedStep ? t("knowledgeDetailPipelineFailedHelp") : t("knowledgeDetailCompletionGateHelp")}</p>
        </div>
        <span className="knowledge-detail-gate-percent">{format("knowledgeDetailPipelineProgressPercent", { percent: progress })}</span>
      </div>
      <LayoutPipelineFallback detail={detail} format={format} onRetry={onRetry} retryError={retryError} retryingStep={retryingStep} reviewLocked={reviewLocked} t={t} />
      <div className="knowledge-detail-gate-actions">
        <Link className="action-button secondary" href={`/project/${projectId}/import`}>
          <ArrowLeft size={16} /> {t("knowledgeDetailBackToDocuments")}
        </Link>
      </div>
    </section>
  );
}

function MarkdownRendered({ source }: { source: string }) {
  return <SafeMarkdown className="rendered-markdown-document" source={source} />;
}

function TagEditor({
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

export default function KnowledgePage() {
  const params = useParams<{ id: string; knowledgeId: string }>();
  const { apiFetch, currentUser, authReady, applicationAccess } = useAuth();
  const { locale, format } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const [liveDetail, setLiveDetail] = useState<KnowledgeDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [loadedRoute, setLoadedRoute] = useState<string | null>(null);
  const userId = currentUser?.user_id ?? "";
  const routeKey = JSON.stringify([userId, params.id, params.knowledgeId]);
  const canObserve = Boolean(userId && authReady && applicationAccess === "granted");
  const [readinessBudget] = useState(() => new KnowledgeReadinessBudget());
  const [detailReads] = useState(() => new KnowledgeDetailReads());
  const [stoppedReadiness, setStoppedReadiness] = useState<string | null>(null);
  const [deniedReadRoute, setDeniedReadRoute] = useState<string | null>(null);
  const [manualReadKey, setManualReadKey] = useState<string | null>(null);
  const currentReadState = useRef({ routeKey, detail: liveDetail, canObserve });
  useEffect(() => { currentReadState.current = { routeKey, detail: liveDetail, canObserve }; }, [routeKey, liveDetail, canObserve]);
  const readinessKey = knowledgeReadinessKey(userId, params.id, params.knowledgeId, liveDetail);
  const readinessPending = loadedRoute === routeKey && needsKnowledgeReadinessCheck(liveDetail) && Boolean(readinessKey);
  const readinessStopped = Boolean(readinessKey && (readinessBudget.exhausted(readinessKey) || stoppedReadiness === readinessKey));
  const manualReadBusy = Boolean(readinessKey && manualReadKey === readinessKey);
  const [documentView, setDocumentView] = useState<DocumentView>("original");
  const [graphOpen, setGraphOpen] = useState(false);
  const [selectedChunkIds, setSelectedChunkIds] = useState<string[]>([]);
  const [selectionRequest, setSelectionRequest] = useState(0);
  const [chunkScrollRequest, setChunkScrollRequest] = useState<{ chunkId: string; sequence: number } | null>(null);
  const [sourceLocationError, setSourceLocationError] = useState(false);
  const [downloadError, setDownloadError] = useState(false);
  const [retryingStep, setRetryingStep] = useState<string | null>(null);
  const [retryError, setRetryError] = useState(false);
  const [manualSelection, setManualSelection] = useState<ManualTextSelection | null>(null);
  const [manualChunkBusy, setManualChunkBusy] = useState(false);
  const [manualChunkError, setManualChunkError] = useState(false);
  const [documentTagDraft, setDocumentTagDraft] = useState("");
  const [chunkTagDrafts, setChunkTagDrafts] = useState<Record<string, string>>({});
  const [tagBusyKey, setTagBusyKey] = useState<string | null>(null);
  const [tagError, setTagError] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeChunk | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const articleViewerRef = useRef<HTMLDivElement>(null);
  const chunkListRef = useRef<HTMLDivElement>(null);
  const skipNextSourceScrollRef = useRef(false);
  const displayChunks = useMemo(() => liveDetail?.chunks.map((chunk) => liveChunk(chunk, t, format)) ?? [], [format, liveDetail?.chunks, t]);
  const documentTags = visibleTagDetails(liveDetail?.document_tags ?? []);
  const originalSourceText = liveDetail?.source_text ?? null;
  const markdownSourceText = liveDetail?.markdown_text ?? null;
  const selectedChunks = useMemo(() => displayChunks.filter((chunk) => selectedChunkIds.includes(chunk.id)), [displayChunks, selectedChunkIds]);
  const selectedChunk = selectedChunks[0];
  const selectedSourceAnchors = useMemo(() => sourceAnchorsForChunks(displayChunks, selectedChunkIds), [displayChunks, selectedChunkIds]);
  const selectedSourceGroups = useMemo(() => sourceSelectionGroupsForChunks(displayChunks, selectedChunkIds), [displayChunks, selectedChunkIds]);
  const mutationLocked = liveDetail?.manual_edit_reason === "review_locked";
  const tagMutationLocked = mutationLocked || Boolean(liveDetail?.tag_edit_reason)
    || ["active", "inactive"].includes(liveDetail?.version.status ?? "");
  const knowledgeGateBlocked = liveDetail ? completionGateBlocksKnowledgeDetail(liveDetail) : false;

  const fetchDetail = useCallback((signal?: AbortSignal) => getKnowledgeDetail(apiFetch, params.id, params.knowledgeId, signal), [apiFetch, params.id, params.knowledgeId]);

  useEffect(() => {
    if (!canObserve || deniedReadRoute === routeKey) return;
    const lease = detailReads.begin(routeKey);
    if (!lease) return;
    fetchDetail(lease.signal).then((detail) => {
      if (lease.active()) {
        if (detail.document.id !== params.knowledgeId || detail.document.project_id !== params.id) throw new Error("knowledge_read_scope_mismatch");
        setLiveDetail(detail);
        setLoadedRoute(routeKey);
        setSelectedChunkIds((current) => current.length ? current : detail.chunks[0]?.id ? [detail.chunks[0].id] : []);
        setLoadError(false);
      }
    }).catch((error) => {
      if (lease.active()) {
        if (isPollingAuthorizationFailure(error)) setDeniedReadRoute(routeKey);
        setLoadError(true);
      }
    }).finally(() => {
      if (lease.active()) setLoading(false);
      lease.finish();
    });
    return lease.cancel;
  }, [fetchDetail, routeKey, canObserve, deniedReadRoute, detailReads, params.id, params.knowledgeId]);

  useEffect(() => () => { detailReads.cancel(); }, [detailReads, routeKey, canObserve]);

  useEffect(() => {
    if (!canObserve || deniedReadRoute === routeKey || loadedRoute !== routeKey) return;
    let current = liveDetail;
    let lease: ReturnType<KnowledgeDetailReads["begin"]> = null;
    const active = () => shouldPollKnowledgeCompletionGate(current) ||
      (isPipelineActive(current?.pipeline) && !current?.document_layout?.pages.length) ||
      current?.chunk_artifact_status === "queued" || current?.chunk_artifact_status === "running" ||
      Boolean(readinessKey && needsKnowledgeReadinessCheck(current) && !readinessBudget.exhausted(readinessKey));
    if (readinessKey && needsKnowledgeReadinessCheck(current)) readinessBudget.observe(readinessKey);
    if (!active()) return;
    // Deadline is independent of background cadence and is not reset by renders.
    const deadline = readinessKey && needsKnowledgeReadinessCheck(current) ? setTimeout(() => {
      readinessBudget.stop(readinessKey);
      setStoppedReadiness(readinessKey);
      lease?.cancel();
    }, readinessBudget.remainingMs(readinessKey)) : undefined;
    const stop = startFileProcessingPolling({
      load: async () => {
        if (readinessKey && needsKnowledgeReadinessCheck(current) && !readinessBudget.take(readinessKey)) {
          setStoppedReadiness(readinessKey);
          throw new DOMException("Readiness budget exhausted", "AbortError");
        }
        lease = detailReads.begin(routeKey);
        if (!lease) throw new DOMException("Read already in progress", "AbortError");
        const request = lease;
        const before = current;
        try {
          const detail = await fetchDetail(request.signal);
          const latest = currentReadState.current;
          if (!request.active() || !latest.canObserve || latest.routeKey !== routeKey) throw new DOMException("Read superseded", "AbortError");
          if (!acceptsKnowledgeRead(userId, params.id, params.knowledgeId, before, latest.detail, detail)) throw new Error("knowledge_read_scope_mismatch");
          return detail;
        } finally { request.finish(); }
      },
      execution: () => current?.pipeline?.execution,
      active,
      value: (detail) => {
        current = detail;
        setLiveDetail(detail);
        setSelectedChunkIds((current) => current.length ? current : detail.chunks[0]?.id ? [detail.chunks[0].id] : []);
        setLoadError(false);
      },
      error: (error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (isPollingAuthorizationFailure(error)) setDeniedReadRoute(routeKey);
        if (readinessKey && error instanceof Error && ["knowledge_read_scope_mismatch", "file_processing_poll_contract_invalid"].includes(error.message)) {
          readinessBudget.stop(readinessKey); setStoppedReadiness(readinessKey);
        }
        if (readinessKey && readinessBudget.exhausted(readinessKey)) setStoppedReadiness(readinessKey);
        setLoadError(true);
      }
    });
    return () => { stop(); clearTimeout(deadline); lease?.cancel(); };
  }, [liveDetail, fetchDetail, loadedRoute, routeKey, canObserve, deniedReadRoute, detailReads, readinessBudget, readinessKey, stoppedReadiness, userId, params.id, params.knowledgeId]);

  async function recheckReadinessOnce() {
    if (!canObserve || deniedReadRoute === routeKey || !readinessPending || !readinessStopped || !readinessKey) return;
    const lease = detailReads.begin(routeKey);
    if (!lease) return;
    const before = liveDetail;
    setManualReadKey(readinessKey);
    try {
      const detail = await fetchDetail(lease.signal);
      const latest = currentReadState.current;
      if (!lease.active() || !latest.canObserve || latest.routeKey !== routeKey) return;
      if (!acceptsKnowledgeRead(userId, params.id, params.knowledgeId, before, latest.detail, detail)) throw new Error("knowledge_read_scope_mismatch");
      setLiveDetail(detail); setLoadError(false);
    } catch (error) {
      if (lease.active()) {
        if (isPollingAuthorizationFailure(error)) setDeniedReadRoute(routeKey);
        setLoadError(true);
      }
    } finally {
      setManualReadKey((current) => current === readinessKey ? null : current);
      lease.finish();
    }
  }

  useEffect(() => {
    if (!graphOpen) return;
    const previousBodyOverflow = document.body.style.overflow;
    const previousHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.overflow = previousHtmlOverflow;
    };
  }, [graphOpen]);

  useEffect(() => {
    if (documentView === "tags") {
      return;
    }
    if (!selectedChunk) return;
    if (skipNextSourceScrollRef.current) {
      skipNextSourceScrollRef.current = false;
      return;
    }

    const animationFrame = requestAnimationFrame(() => {
      const viewer = articleViewerRef.current;
      const target = documentView === "markdown"
        ? viewer?.querySelector<HTMLElement>(`[data-chunk-ids~="${CSS.escape(selectedChunk.id)}"]`)
        : viewer?.querySelector<HTMLElement>(`[data-source-anchor="${CSS.escape(selectedChunk.sourceAnchor)}"]`);
      if (!viewer || !target) {
        setSourceLocationError(true);
        return;
      }

      const viewerRect = viewer.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const targetTop = viewer.scrollTop + targetRect.top - viewerRect.top - (viewer.clientHeight - targetRect.height) / 2;
      setSourceLocationError(false);
      viewer.scrollTo({ behavior: sourceSelectionScrollBehavior(), top: Math.max(0, targetTop) });
    });

    return () => cancelAnimationFrame(animationFrame);
  }, [documentView, liveDetail?.original_file, selectedChunk, selectionRequest]);

  useEffect(() => {
    if (!chunkScrollRequest) return;
    const animationFrame = requestAnimationFrame(() => {
      const chunkList = chunkListRef.current;
      const target = chunkList?.querySelector<HTMLElement>(`[data-chunk-id="${chunkScrollRequest.chunkId}"]`);
      if (!chunkList || !target) return;
      const listRect = chunkList.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const targetTop = chunkList.scrollTop + targetRect.top - listRect.top - (chunkList.clientHeight - targetRect.height) / 2;
      chunkList.scrollTo({ behavior: sourceSelectionScrollBehavior(), top: Math.max(0, targetTop) });
    });

    return () => cancelAnimationFrame(animationFrame);
  }, [chunkScrollRequest]);

  function selectChunk(chunkId: string) {
    if (selectedChunkIds.length === 1 && selectedChunkIds[0] === chunkId) {
      setSelectedChunkIds([]);
      setSourceLocationError(false);
      return;
    }
    setSelectedChunkIds([chunkId]);
    setSelectionRequest((request) => request + 1);
  }

  function selectSourceAnchor(sourceAnchor: string) {
    const matchingIds = chunkIdsForResolvedSourceAnchor(displayChunks, sourceAnchor);
    if (!matchingIds.length) {
      setSourceLocationError(true);
      return;
    }
    if (matchingIds.some((chunkId) => !selectedChunkIds.includes(chunkId))) skipNextSourceScrollRef.current = true;
    setSelectedChunkIds(matchingIds);
    setSourceLocationError(false);
    setChunkScrollRequest((request) => ({ chunkId: matchingIds[0], sequence: (request?.sequence ?? 0) + 1 }));
  }

  function selectMarkdownChunks(chunkIds: string[]) {
    if (!chunkIds.length) return;
    skipNextSourceScrollRef.current = true;
    setSelectedChunkIds(chunkIds);
    setSourceLocationError(false);
    setChunkScrollRequest((request) => ({ chunkId: chunkIds[0], sequence: (request?.sequence ?? 0) + 1 }));
  }

  function handleSourceKeyDown(event: KeyboardEvent<HTMLElement>, sourceAnchor: string) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectSourceAnchor(sourceAnchor);
    }
  }

  function captureManualSelection(viewMode: ArticleView) {
    if (!liveDetail?.manual_edit_enabled) return;
    const selection = window.getSelection();
    const viewer = articleViewerRef.current;
    if (!selection || !viewer || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    if (!viewer.contains(range.commonAncestorContainer)) return;
    const rawSelection = selection.toString();
    const content = rawSelection.trim();
    if (!content) {
      setManualSelection(null);
      return;
    }
    if (viewMode === "original") {
      const mapped = mappedSelectionRange(range);
      if (!mapped || !markdownSourceText) {
        setManualSelection(null);
        setSourceLocationError(true);
        return;
      }
      const raw = Array.from(markdownSourceText).slice(mapped.start, mapped.end).join("");
      const canonicalContent = raw.trim();
      if (!canonicalContent) return;
      const startOffset = mapped.start + codePointLength(raw.slice(0, raw.length - raw.trimStart().length));
      const rect = range.getBoundingClientRect();
      setManualSelection({ content: canonicalContent, viewMode, sourceAnchor: "markdown-document",
        startOffset, endOffset: startOffset + codePointLength(canonicalContent), offsetScope: "canonical_markdown",
        top: Math.max(72, rect.top - 48), left: Math.min(window.innerWidth - 180, Math.max(16, rect.left)) });
      setManualChunkError(false);
      setSourceLocationError(false);
      return;
    }
    const node = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE ? range.commonAncestorContainer as Element : range.commonAncestorContainer.parentElement;
    const anchorElement = node?.closest<HTMLElement>("[data-source-anchor]");
    const sourceAnchor = viewMode === "markdown" ? "markdown-document" : anchorElement?.dataset.sourceAnchor || "original-document";
    const canonicalRoot = viewer.querySelector<HTMLElement>("[data-canonical-markdown-source] code");
    const offsetRoot = viewMode === "markdown" ? canonicalRoot : anchorElement ?? viewer;
    if (!offsetRoot) return;
    if (!offsetRoot.contains(range.startContainer) || !offsetRoot.contains(range.endContainer)) return;
    const preRange = document.createRange();
    preRange.selectNodeContents(offsetRoot);
    preRange.setEnd(range.startContainer, range.startOffset);
    const leadingWhitespace = rawSelection.slice(0, rawSelection.length - rawSelection.trimStart().length);
    const startOffset = codePointLength(preRange.toString()) + codePointLength(leadingWhitespace);
    const endOffset = startOffset + codePointLength(content);
    const rect = range.getBoundingClientRect();
    setManualSelection({
      content,
      viewMode,
      sourceAnchor,
      startOffset,
      endOffset,
      offsetScope: viewMode === "markdown" ? "canonical_markdown" : "source_anchor",
      top: Math.max(72, rect.top - 48),
      left: Math.min(window.innerWidth - 180, Math.max(16, rect.left + rect.width / 2 - 70))
    });
    setManualChunkError(false);
  }

  async function submitManualChunk() {
    if (!manualSelection || !liveDetail?.manual_edit_enabled) return;
    setManualChunkBusy(true);
    setManualChunkError(false);
    try {
      const refreshed = await createManualChunk(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, {
        content: manualSelection.content,
        view_mode: manualSelection.viewMode,
        source_anchor: manualSelection.sourceAnchor,
        start_offset: manualSelection.startOffset,
        end_offset: manualSelection.endOffset,
        offset_unit: "unicode_code_point",
        offset_scope: manualSelection.offsetScope,
        lock_version: liveDetail.version.lock_version
      });
      setLiveDetail(refreshed);
      const selectedId = refreshed.chunks.find((chunk) => chunk.content === manualSelection.content)?.id ?? refreshed.chunks[0]?.id;
      setSelectedChunkIds(selectedId ? [selectedId] : []);
      setManualSelection(null);
      window.getSelection()?.removeAllRanges();
    } catch {
      setManualChunkError(true);
    } finally {
      setManualChunkBusy(false);
    }
  }

  async function refreshAfterTag(action: () => Promise<KnowledgeDetailResponse>) {
    setTagError(false);
    try {
      const refreshed = await action();
      setLiveDetail(refreshed);
      setSelectedChunkIds((current) => current.length ? current : refreshed.chunks[0]?.id ? [refreshed.chunks[0].id] : []);
    } catch {
      setTagError(true);
    } finally {
      setTagBusyKey(null);
    }
  }

  function addDocumentTagFromDraft() {
    const tagText = documentTagDraft.trim();
    if (!liveDetail || !tagText) return;
    setTagBusyKey("document:add");
    refreshAfterTag(() => addDocumentTag(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, tagText)).then(() => setDocumentTagDraft(""));
  }

  function addChunkTagFromDraft(chunkId: string) {
    const tagText = (chunkTagDrafts[chunkId] ?? "").trim();
    if (!liveDetail || !tagText) return;
    setTagBusyKey(`chunk:${chunkId}:add`);
    refreshAfterTag(() => addChunkTag(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, chunkId, tagText)).then(() => setChunkTagDrafts((current) => ({ ...current, [chunkId]: "" })));
  }

  function autoTagWholeDocument() {
    if (!liveDetail) return;
    setTagBusyKey("document:auto");
    refreshAfterTag(() => autoTagDocument(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id));
  }

  function deleteWholeDocumentTag(tagId: string) {
    if (!liveDetail) return;
    setTagBusyKey(`document:delete:${tagId}`);
    refreshAfterTag(() => deleteDocumentTag(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, tagId));
  }

  function autoTagOneChunk(chunkId: string) {
    if (!liveDetail) return;
    setTagBusyKey(`chunk:${chunkId}:auto`);
    refreshAfterTag(() => autoTagChunk(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, chunkId));
  }

  function deleteOneChunkTag(chunkId: string, tagId: string) {
    if (!liveDetail) return;
    setTagBusyKey(`chunk:${chunkId}:delete:${tagId}`);
    refreshAfterTag(() => deleteChunkTag(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, chunkId, tagId));
  }

  async function handleRetryStep(stepName: string) {
    if (!liveDetail?.pipeline?.id) return;
    setRetryingStep(stepName);
    setRetryError(false);
    try {
      const updated = await retryPipelineStep(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, liveDetail.pipeline.id, stepName);
      setLiveDetail({ ...liveDetail, pipeline: updated });
      const refreshed = await fetchDetail();
      setLiveDetail(refreshed);
      setSelectedChunkIds((current) => current.length ? current : refreshed.chunks[0]?.id ? [refreshed.chunks[0].id] : []);
    } catch {
      setRetryError(true);
    } finally {
      setRetryingStep(null);
    }
  }

  async function confirmChunkDeletion() {
    if (!deleteTarget || !liveDetail?.manual_edit_enabled) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      const refreshed = await deleteKnowledgeChunk(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, deleteTarget.id, liveDetail.version.lock_version);
      setLiveDetail(refreshed);
      setSelectedChunkIds((current) => current.includes(deleteTarget.id) ? refreshed.chunks[0]?.id ? [refreshed.chunks[0].id] : [] : current);
      setDeleteTarget(null);
    } catch (error) {
      setDeleteError(operationalErrorMessage(error, t, format, "knowledgeDetailDeleteChunkFailed"));
    } finally {
      setDeleteBusy(false);
    }
  }

  if (!canObserve || deniedReadRoute === routeKey || loadedRoute !== routeKey) return <AppShell title={t("knowledgeDetailTitle")}>
    <div className="review-banner" role="status">{loadError ? <AlertTriangle size={20} /> : <Loader2 className="spin" size={20} />}
      <span>{t(loadError ? "apiGenericError" : "loadingData")}</span>
    </div>
  </AppShell>;

  return (
    <AppShell title={t("knowledgeDetailTitle")}>
      <div className="project-context">
        <Link className="text-link" href={`/project/${params.id}/import`}><ArrowLeft size={16} /> {t("knowledgeDetailBackToDocuments")}</Link>
        <span>{t("knowledgeDetailDocumentVersion")} {liveDetail?.version.version_label ?? "-"}</span>
        <span>{liveDetail?.pipeline?.status ?? t("knowledgeDetailNoPipeline")}</span>
        <StatusBadge status={liveDetail?.version.status ?? "loading"} />
        <div className="project-context-actions">
          {liveDetail?.chat_access?.query_enabled || (liveDetail && !knowledgeGateBlocked && liveDetail.next_stage_allowed) ? <Link className="text-link next-stage-link" href={liveDetail?.chat_access?.mode === "published"
            ? `/project/${params.id}/import?chat_version_id=${encodeURIComponent(liveDetail.chat_access.document_version_id)}` : `/project/${params.id}/knowledge/${params.knowledgeId}/chat-test`}>
            {t(liveDetail?.chat_access?.mode === "published" ? "knowledgePublishedChat" : "chatTest")} <ArrowRight size={16} />
          </Link> : liveDetail?.chat_access?.mode === "history_only" ? <Link className="text-link" href={`/project/${params.id}/knowledge/${params.knowledgeId}/chat-test`}>
            {t("knowledgeChatHistoryOnly")}
          </Link> : liveDetail && !knowledgeGateBlocked ? <span className="next-stage-disabled" title={t(liveDetail.next_stage_block_reason === "chunks_required" ? "knowledgeDetailChunksRequired" : "knowledgeDetailArtifactsNotReady")}><AlertTriangle size={16} /> {t("chatTest")}</span> : null}
        </div>
      </div>

      {liveDetail && knowledgeGateBlocked ? (
        <KnowledgeDetailCompletionGate detail={liveDetail} format={format} onRetry={handleRetryStep} projectId={params.id} retryError={retryError} retryingStep={retryingStep} reviewLocked={mutationLocked} t={t} />
      ) : (
        <>
      <div className="content-grid split extraction-workspace">
        <Panel
          title={t("documentArticle")}
          action={
            <div className="document-view-toggle" aria-label={t("approvalEvidenceViewMode")} role="group">
              <button
                aria-pressed={documentView === "original"}
                className={documentView === "original" ? "active" : ""}
                onClick={() => setDocumentView("original")}
                type="button"
              >
                <FileText size={15} /> {t("originalDocument")}
              </button>
              <button
                aria-pressed={documentView === "markdown"}
                className={documentView === "markdown" ? "active" : ""}
                onClick={() => setDocumentView("markdown")}
                type="button"
              >
                <Code2 size={15} /> {t("markdownView")}
              </button>
              <button
                aria-pressed={documentView === "tags"}
                className={documentView === "tags" ? "active" : ""}
                onClick={() => {
                  setDocumentView("tags");
                  setManualSelection(null);
                  setSourceLocationError(false);
                }}
                type="button"
              >
                <Tags size={15} /> {t("knowledgeDetailTagTab")}
              </button>
            </div>
          }
        >
          {documentView === "tags" ? (
            <div className="document-tag-panel">
              <div className="document-tag-strip">
                <div>
                  <strong>{t("knowledgeDetailDocumentTags")}</strong>
                  <small>{t(tagMutationLocked && !mutationLocked ? "knowledgeDetailPublishedTagsReadonly" : "knowledgeDetailDocumentTagsHelp")}</small>
                </div>
                <TagEditor
                  busy={tagBusyKey?.startsWith("document:") ?? false}
                  disabled={!liveDetail || tagMutationLocked}
                  draft={documentTagDraft}
                  onAdd={addDocumentTagFromDraft}
                  onAuto={autoTagWholeDocument}
                  onDelete={deleteWholeDocumentTag}
                  onDraft={setDocumentTagDraft}
                  tags={documentTags}
                  t={t}
                />
              </div>
              {tagError ? <small className="field-error">{t("knowledgeDetailTagOperationFailed")}</small> : null}
            </div>
          ) : (
          <>
          <div className={`article-viewer article-viewer-${documentView}`} onKeyUp={() => captureManualSelection(documentView)} onMouseUp={() => captureManualSelection(documentView)} ref={articleViewerRef}>
            {documentView === "original" ? (
              <article className="document-article">
                {loading ? <section className="document-page"><div className="document-page-content"><p>{t("notificationLoading")}</p></div></section> : null}
                {loadError ? <section className="document-page"><div className="document-page-content"><p>{t("notificationError")}</p></div></section> : null}
                {!loading && !loadError && liveDetail?.original_file && isMarkdownOriginal(liveDetail.original_file) && !liveDetail.document_layout?.pages.length ? (
                  <section className="document-page markdown-original-page">
                    <div className="document-page-content">
                      {originalSourceText ? <MarkdownRendered source={originalSourceText} /> : <div className="empty-state compact">{artifactUnavailableLabel(liveDetail.original_file, t)}</div>}
                    </div>
                    <footer className="document-page-number">MD</footer>
                  </section>
                ) : null}
                {!loading && !loadError && liveDetail?.document_layout?.pages.length ? (
                  <DocumentLayoutViewer canonicalSource={markdownSourceText ?? undefined} formatPageLabel={(page) => format("knowledgeDetailOriginalPage", { page })} onKeyDown={handleSourceKeyDown} onSelect={selectSourceAnchor} pages={liveDetail.document_layout.pages} selectedAnchors={selectedSourceAnchors} selectionGroups={selectedSourceGroups} />
                ) : null}
                {!loading && !loadError && !isMarkdownOriginal(liveDetail?.original_file) && !liveDetail?.document_layout?.pages.length ? (
                  <section className="document-page">
                    <div className="document-page-content">
                      <div className="empty-state compact">
                        <LayoutPipelineFallback detail={liveDetail} format={format} onRetry={handleRetryStep} retryError={retryError} retryingStep={retryingStep} reviewLocked={mutationLocked} t={t} />
                        {downloadError ? <small className="field-error">{t("knowledgeDetailDownloadFailed")}</small> : null}
                        {liveDetail?.original_file?.download_url ? <button className="action-button secondary" type="button" onClick={() => liveDetail.original_file?.download_url && getKnowledgeArtifactBlob(apiFetch, liveDetail.original_file.download_url).then((blob) => { const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = liveDetail.original_file?.original_file_name ?? "document"; anchor.click(); URL.revokeObjectURL(url); setDownloadError(false); }).catch(() => setDownloadError(true))}><Download size={16} /> {t("knowledgeDetailDownloadOriginal")}</button> : null}
                      </div>
                    </div>
                  </section>
                ) : null}
              </article>
            ) : (
              <div className="article-markdown">
                {!loading && !loadError && !markdownSourceText ? <div className="empty-state compact">{t(markdownArtifactReasonKey(liveDetail?.markdown_artifact_reason_code))}</div> : null}
                {markdownSourceText ? <CanonicalMarkdownSource chunks={displayChunks} onSelectChunkIds={selectMarkdownChunks} selectedChunkIds={selectedChunkIds} source={markdownSourceText} /> : null}
              </div>
            )}
          </div>
          <TagResultStrip className="document-tag-result-strip" label={t("knowledgeDetailDocumentTags")} tags={documentTags} t={t} />
          </>
          )}
          {manualSelection ? (
            <div className="manual-chunk-popover" style={{ left: manualSelection.left, top: manualSelection.top }}>
              <button
                disabled={manualChunkBusy}
                onMouseDown={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                }}
                onClick={(event) => {
                  event.stopPropagation();
                  submitManualChunk();
                }}
                type="button"
              >
                {manualChunkBusy ? <Loader2 className="spin" size={15} /> : <Edit3 size={15} />} {t("knowledgeDetailManualChunking")}
              </button>
              {manualChunkError ? <small className="field-error">{t("knowledgeDetailManualChunkFailed")}</small> : null}
            </div>
          ) : null}
          {sourceLocationError ? <div className="source-location-error">{t("sourceLocationError")}</div> : null}
        </Panel>

        <Panel
          title={t("knowledgeDetailChunkResults")}
          action={
            <div className="panel-action-group">
              <button className="action-button secondary" onClick={() => setGraphOpen(true)} type="button">
                <Network size={16} /> {t("knowledgeGraphPreview")}
              </button>
            </div>
          }
        >
          <div className="chunk-list extraction-chunks" ref={chunkListRef}>
            {displayChunks.map((chunk) => (
              <article
                aria-label={format("knowledgeDetailSelectChunkAria", { id: chunk.id, number: chunk.index })}
                aria-pressed={selectedChunkIds.includes(chunk.id)}
                className={selectedChunkIds.includes(chunk.id) ? "chunk-card selected" : "chunk-card"}
                data-chunk-id={chunk.id}
                key={chunk.id}
                onClick={() => selectChunk(chunk.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectChunk(chunk.id);
                  }
                }}
                role="button"
                tabIndex={0}
              >
                <div className="chunk-head">
                  <span className="chunk-title-row">
                    <span className="chunk-title-meta">
                      <span className="chunk-index-badge">#{chunk.index}</span>
                      <small className="chunk-inline-meta">
                        <span>{chunk.sourceLabel}</span>
                        <span>{format("knowledgeDetailTokenCount", { count: chunk.tokens })}</span>
                        <span>{format("knowledgeDetailConfidence", { value: Math.round(chunk.confidence * 100) })}</span>
                      </small>
                    </span>
                    <span className="chunk-card-actions">
                      <small className="chunk-technical-id">{chunk.id}</small>
                      <button
                        aria-label={format("knowledgeDetailDeleteChunkAria", { number: chunk.index })}
                        className="chunk-delete-button"
                        disabled={!liveDetail?.manual_edit_enabled || deleteBusy}
                        onClick={(event) => { event.stopPropagation(); setDeleteError(null); setDeleteTarget(chunk); }}
                        onKeyDown={(event) => event.stopPropagation()}
                        title={t("knowledgeDetailDeleteChunk")}
                        type="button"
                      ><Trash2 size={17} /></button>
                    </span>
                  </span>
                </div>
                <div className="chunk-content-shell">
                  <ChunkPreview chunk={chunk} />
                </div>
                {tagMutationLocked && !mutationLocked ? <small className="field-note">{t("knowledgeDetailPublishedTagsReadonly")}</small> : null}
                <TagEditor
                  busy={tagBusyKey?.startsWith(`chunk:${chunk.id}:`) ?? false}
                  disabled={!liveDetail || tagMutationLocked}
                  draft={chunkTagDrafts[chunk.id] ?? ""}
                  label={t("knowledgeDetailChunkTagResults")}
                  onAdd={() => addChunkTagFromDraft(chunk.id)}
                  onAuto={() => autoTagOneChunk(chunk.id)}
                  onDelete={(tagId) => deleteOneChunkTag(chunk.id, tagId)}
                  onDraft={(value) => setChunkTagDrafts((current) => ({ ...current, [chunk.id]: value }))}
                  tags={chunk.tagDetails}
                  t={t}
                />
              </article>
            ))}
            {!loading && !loadError && displayChunks.length === 0 ? <div className="chunk-empty-state"><AlertTriangle size={20} /><strong>{t("knowledgeDetailNoChunksTitle")}</strong><p>{t("knowledgeDetailNoChunksHelp")}</p></div> : null}
          </div>
        </Panel>
      </div>

      {readinessPending ? <KnowledgeReadinessNotice stopped={readinessStopped || deniedReadRoute === routeKey}
        busy={manualReadBusy} canRetry={canObserve && deniedReadRoute !== routeKey} onRetry={() => void recheckReadinessOnce()} /> :
      <div className={liveDetail?.next_stage_allowed ? "review-banner" : "review-banner warning"}>
        {liveDetail?.next_stage_allowed ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
        <span>{liveDetail?.chat_access?.mode === "published" ? t("knowledgePublishedChat") : liveDetail?.next_stage_allowed ? t("knowledgeDetailReviewReady") : t(liveDetail?.next_stage_block_reason === "chunks_required" ? "knowledgeDetailChunksRequired" : "knowledgeDetailArtifactsNotReady")}</span>
      </div>}

      {deleteTarget ? <div className="system-modal-backdrop" onKeyDown={(event) => { if (event.key === "Escape" && !deleteBusy) setDeleteTarget(null); }} onMouseDown={(event) => { if (event.target === event.currentTarget && !deleteBusy) setDeleteTarget(null); }} role="presentation">
        <section aria-labelledby="delete-chunk-title" aria-modal="true" className="system-reauth-modal chunk-delete-modal" role="alertdialog">
          <header><span className="danger-icon"><Trash2 size={20} /></span><div><small>{format("knowledgeDetailChunkLabel", { number: deleteTarget.index })}</small><h2 id="delete-chunk-title">{t("knowledgeDetailDeleteChunkTitle")}</h2></div><button aria-label={t("close")} className="modal-close-button" disabled={deleteBusy} onClick={() => setDeleteTarget(null)} type="button"><X size={18} /></button></header>
          <p>{t("knowledgeDetailDeleteChunkHelp")}</p>
          <blockquote>{deleteTarget.content.slice(0, 180)}{deleteTarget.content.length > 180 ? "..." : ""}</blockquote>
          {deleteError ? <div className="error-summary" role="alert"><strong>{deleteError}</strong></div> : null}
          <footer><button className="action-button secondary" disabled={deleteBusy} onClick={() => setDeleteTarget(null)} type="button">{t("cancel")}</button><button className="action-button danger" disabled={deleteBusy} onClick={() => void confirmChunkDeletion()} type="button">{deleteBusy ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}{t("knowledgeDetailConfirmDeleteChunk")}</button></footer>
        </section>
      </div> : null}

      {graphOpen ? (
        <div className="modal-backdrop">
          <section aria-labelledby="document-graph-title" aria-modal="true" className="modal-panel document-graph-modal" role="dialog">
            <div className="modal-header">
              <div>
                <p className="eyebrow">{liveDetail ? `${liveDetail.document.title} · ${liveDetail.version.version_label}` : t("knowledgeDetailLiveGraphEyebrow")}</p>
                <h2 id="document-graph-title">{t("knowledgeGraphPreview")}</h2>
              </div>
              <button className="icon-button" onClick={() => setGraphOpen(false)} type="button" aria-label={t("knowledgeDetailCloseGraphPreview")}>
                <X size={18} />
              </button>
            </div>
            {liveDetail ? <VersionGraphPreview projectId={params.id} documentId={liveDetail.document.id}
              versionId={liveDetail.version.id} documentTitle={liveDetail.document.title}
              version={liveDetail.version.version_label} /> : null}
          </section>
        </div>
      ) : null}
        </>
      )}
    </AppShell>
  );
}
