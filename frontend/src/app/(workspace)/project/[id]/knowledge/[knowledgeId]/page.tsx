"use client";

import { resourcePageTitle } from "@/lib/browserTitle";

import { contentUpdateFeedback } from "@/lib/contentUpdateFeedback";
import { FeedbackMessage, FeedbackField } from "@/components/FeedbackMessage";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Code2, Edit3, FileText, Loader2, Network, Tags, Trash2, X } from "lucide-react";
import { AppShell, Panel, StatusBadge } from "@/components/AppShell";
import { CanonicalMarkdownSource } from "@/components/CanonicalMarkdownSource";
import { useAuth } from "@/components/AuthProvider";
import { ContinuousDocumentViewer } from "@/components/ContinuousDocumentViewer";
import { OriginalFileDownload } from "@/components/OriginalFileDownload";
import { IconActionButton } from "@/components/IconActionButton";
import { useSourceViewPosition } from "@/lib/sourceViewPosition";
import { formatCount } from "@/lib/numberFormat";
import { sourceTargetForMappings } from "@/lib/sourceRangeGeometry";
import { KnowledgeReadinessNotice } from "@/components/KnowledgeReadinessNotice";
import { isPollingAuthorizationFailure, startFileProcessingPolling } from "@/lib/fileProcessingPolling";
import { KnowledgeDetailReads, KnowledgeReadinessBudget, acceptsKnowledgeRead, completionGateBlocksKnowledgeDetail, knowledgeReadinessKey, needsKnowledgeReadinessCheck } from "@/lib/knowledgeReadiness";
import { deleteKnowledgeChunk, getDocumentVersionSubmissionEvidence, getKnowledgeDetail, retryPipelineStep, type KnowledgeDetailResponse } from "@/lib/api";
import { t as translate } from "@/lib/i18n";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { VersionGraphPreview } from "@/components/VersionGraphPreview";
import { useI18n } from "@/lib/i18nClient";
import { markdownArtifactReasonKey, sourceSelectionGroupsForChunks, sourceSelectionScrollBehavior } from "@/lib/markdownSourceMapping";
import { retryContent, type ContentUpdateResult } from "@/lib/documentContentApi";

const DocumentContentEditorModal = dynamic(() => import("@/components/DocumentContentEditorModal").then(module => module.DocumentContentEditorModal), { ssr: false });

import { type Translate, type KnowledgeChunk, type DocumentView, visibleTagDetails, liveChunk, isPipelineActive, shouldPollKnowledgeCompletionGate } from "@/components/knowledgeDetail/knowledgeDetailModel";
import { createKnowledgeTagActions, useKnowledgeTagState } from "@/components/knowledgeDetail/useKnowledgeTagSection";
import { useManualChunkSection } from "@/components/knowledgeDetail/useManualChunkSection";
import { ChunkPreview, TagResultStrip, KnowledgeDetailCompletionGate, TagEditor } from "@/components/knowledgeDetail/KnowledgeDetailParts";

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
  const [contentEditor, setContentEditor] = useState<{ chunkId?: string; versionId: string } | null>(null);
  const [originalDownloadFailed, setOriginalDownloadFailed] = useState(false);
  const [contentNotice, setContentNotice] = useState<"submitted" | "recovery_cancelled" | null>(null);
  const [selectedChunkIds, setSelectedChunkIds] = useState<string[]>([]);
  const [selectionRequest, setSelectionRequest] = useState(0);
  const [chunkScrollRequest, setChunkScrollRequest] = useState<{ chunkId: string; sequence: number } | null>(null);
  const [sourceLocationError, setSourceLocationError] = useState(false);
  const [retryingStep, setRetryingStep] = useState<string | null>(null);
  const [retryError, setRetryError] = useState(false);
  const tagState = useKnowledgeTagState();
  const { documentTagDraft, setDocumentTagDraft, chunkTagDrafts, setChunkTagDrafts, tagBusyKey, tagError } = tagState;
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeChunk | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const articleViewerRef = useRef<HTMLDivElement>(null);
  const chunkListRef = useRef<HTMLDivElement>(null);
  const skipNextSourceScrollRef = useRef(false);
  const displayChunks = useMemo(() => liveDetail?.chunks.map((chunk) => liveChunk(chunk, t, format)) ?? [], [format, liveDetail?.chunks, t]);
  const documentTags = visibleTagDetails(liveDetail?.document_tags ?? []);
  const markdownSourceText = liveDetail?.markdown_text ?? null;
  const physicalPagesUnknown = liveDetail?.pipeline?.steps.some(step => step.input_mode === "native_pdf" && step.page_map_status === "unknown") ?? false;
  const selectedChunkIdSet = useMemo(() => new Set(selectedChunkIds), [selectedChunkIds]);
  const selectedChunks = useMemo(() => displayChunks.filter((chunk) => selectedChunkIdSet.has(chunk.id)), [displayChunks, selectedChunkIdSet]);
  const selectedChunk = selectedChunks[0];
  const selectedSourceGroups = useMemo(() => sourceSelectionGroupsForChunks(displayChunks, selectedChunkIds), [displayChunks, selectedChunkIds]);
  const rememberSourcePosition = useSourceViewPosition(articleViewerRef, documentView, markdownSourceText, selectedChunkIds.length);
  const { manualSelection, setManualSelection, manualChunkBusy, manualChunkError, captureManualSelection, submitManualChunk } = useManualChunkSection({ apiFetch, params, liveDetail, setLiveDetail, articleViewerRef, markdownSourceText, setSelectedChunkIds, setSourceLocationError });
  function changeDocumentView(view: DocumentView) {
    if (view === documentView) return;
    if (view !== "tags" && documentView !== "tags") rememberSourcePosition();
    setManualSelection(null);
    setDocumentView(view);
  }
  const mutationLocked = liveDetail?.manual_edit_reason === "review_locked";
  const tagMutationLocked = mutationLocked || Boolean(liveDetail?.tag_edit_reason)
    || ["active", "inactive"].includes(liveDetail?.version.status ?? "");
  const knowledgeGateBlocked = liveDetail ? completionGateBlocksKnowledgeDetail(liveDetail) : false;
  const contentFeedback = contentUpdateFeedback(liveDetail?.content_update, contentNotice);

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
      current?.pipeline?.execution?.phase === "stopping" ||
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
        : sourceTargetForMappings(viewer, selectedChunk.sourceMappings);
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

  function selectSourceRange(range: { start: number; end: number }) {
    const matching = displayChunks.filter(chunk => chunk.sourceMappings.some(mapping => mapping.markdownStart < range.end && mapping.markdownEnd > range.start)).map(chunk => chunk.id);
    if (!matching.length) { setSourceLocationError(true); return; }
    skipNextSourceScrollRef.current = true;
    setSelectedChunkIds(matching);
    setSourceLocationError(false);
    setChunkScrollRequest(request => ({ chunkId: matching[0], sequence: (request?.sequence ?? 0) + 1 }));
  }

  function selectMarkdownChunks(chunkIds: string[]) {
    if (!chunkIds.length) return;
    skipNextSourceScrollRef.current = true;
    setSelectedChunkIds(chunkIds);
    setSourceLocationError(false);
    setChunkScrollRequest((request) => ({ chunkId: chunkIds[0], sequence: (request?.sequence ?? 0) + 1 }));
  }

  const tagActions = createKnowledgeTagActions(tagState, { apiFetch, params, liveDetail, setLiveDetail, setSelectedChunkIds });
  const { addDocumentTagFromDraft, addChunkTagFromDraft, autoTagWholeDocument, deleteWholeDocumentTag, autoTagOneChunk, deleteOneChunkTag } = tagActions;

  async function handleRetryStep(stepName: string) {
    if (!liveDetail?.pipeline?.id) return;
    setRetryingStep(stepName);
    setRetryError(false);
    try {
      if (liveDetail.content_update) {
        await retryContent(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, liveDetail.content_update.update_id, liveDetail.version.lock_version);
        const refreshed = await fetchDetail(); setLiveDetail(refreshed); return;
      }
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

  async function handleContentSaved(result: ContentUpdateResult) {
    if (result.changed || result.status === "recovery_cancelled") {
      const refreshed = (await getDocumentVersionSubmissionEvidence(apiFetch, params.id, liveDetail!.document.id, result.document_version_id)).detail;
      if (refreshed.version.id !== result.document_version_id) throw new Error("content_update_scope_changed");
      setLiveDetail(refreshed); setSelectedChunkIds([]); setGraphOpen(false);
    }
    // The editor emits the no-change toast; do not add a second acknowledgement.
    setContentNotice(result.status === "recovery_cancelled" ? "recovery_cancelled" : result.changed ? "submitted" : null);
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
    <AppShell title={t("knowledgeDetailTitle")} browserTitle={resourcePageTitle(t("knowledgeDetailTitle"), !loadError && !loading ? liveDetail?.document.title : null, !loadError && !loading ? liveDetail?.version.version_label : null)}>
      <div className="project-context">
        <Link className="text-link" href={`/project/${params.id}/import`}><ArrowLeft size={16} /> {t("knowledgeDetailBackToDocuments")}</Link>
        <span>{t("knowledgeDetailDocumentVersion")} {liveDetail?.version.version_label ?? "-"}</span>
        <span>{liveDetail?.pipeline?.status ?? t("knowledgeDetailNoPipeline")}</span>
        <StatusBadge status={liveDetail?.version.status ?? "loading"} />
        <div className="project-context-actions">
          {(liveDetail?.chat_access ? liveDetail.chat_access.query_enabled : liveDetail && !knowledgeGateBlocked && liveDetail.next_stage_allowed) ? <Link className="text-link next-stage-link" href={liveDetail?.chat_access?.mode === "published"
            ? `/project/${params.id}/import?chat_version_id=${encodeURIComponent(liveDetail.chat_access.document_version_id)}` : `/project/${params.id}/knowledge/${params.knowledgeId}/chat-test`}>
            {t(liveDetail?.chat_access?.mode === "published" ? "knowledgePublishedChat" : "chatTest")} <ArrowRight size={16} />
          </Link> : liveDetail?.chat_access?.mode === "history_only" ? <Link className="text-link" href={`/project/${params.id}/knowledge/${params.knowledgeId}/chat-test`}>
            {t("knowledgeChatHistoryOnly")}
          </Link> : liveDetail && !knowledgeGateBlocked ? <span className="next-stage-disabled" title={t(liveDetail.next_stage_block_reason === "chunks_required" ? "knowledgeDetailChunksRequired" : "knowledgeDetailArtifactsNotReady")}><AlertTriangle size={16} /> {t("chatTest")}</span> : null}
        </div>
      </div>

      {(liveDetail?.chunk_artifact_error_code === "embedding_build_provider_result_unknown" || liveDetail?.chunk_artifact_error_code === "model_usage_persistence_unconfirmed") && contentFeedback?.reasonCode !== liveDetail?.chunk_artifact_error_code ? <FeedbackMessage tone="warning">{t(liveDetail.chunk_artifact_error_code === "model_usage_persistence_unconfirmed" ? "modelUsagePersistenceUnconfirmed" : "embeddingBuildResultUnknown")}</FeedbackMessage> : null}
      {!knowledgeGateBlocked && contentFeedback ? <FeedbackMessage tone={contentFeedback.tone}>{t(contentFeedback.message)}</FeedbackMessage> : null}
      {liveDetail && knowledgeGateBlocked ? (
        <KnowledgeDetailCompletionGate contentFeedback={contentFeedback} detail={liveDetail} format={format} onRetry={handleRetryStep} onEdit={() => setContentEditor({ versionId: liveDetail!.version.id })} projectId={params.id} retryError={retryError} retryingStep={retryingStep} reviewLocked={mutationLocked} t={t} />
      ) : (
        <>
      <div className="content-grid split extraction-workspace">
        <Panel
          title={t("contentEditDocumentPanelTitle")}
          action={
            <div className="content-edit-panel-actions">
              <div className="content-edit-button-scroll"><div className="content-edit-button-row">
              <OriginalFileDownload metadata={liveDetail?.original_file} compact onFailureChange={setOriginalDownloadFailed} />
              {liveDetail?.document.capabilities?.can_edit_chunks ? <IconActionButton className="action-button content-edit-open" label={t("contentEditAction")} disabled={!liveDetail.content_edit_mode || liveDetail.content_edit_mode === "readonly"} aria-describedby={!liveDetail.content_edit_mode || liveDetail.content_edit_mode === "readonly" ? "content-edit-disabled-reason" : undefined} onClick={() => setContentEditor({ versionId: liveDetail!.version.id })}><Edit3 size={18} aria-hidden="true" /></IconActionButton> : null}
            <div className="document-view-toggle" aria-label={t("approvalEvidenceViewMode")} role="group">
              <button
                aria-pressed={documentView === "original"}
                className={documentView === "original" ? "active" : ""}
                onClick={() => changeDocumentView("original")}
                type="button"
              >
                <FileText size={15} /> {t("documentReadingView")}
              </button>
              <button
                aria-pressed={documentView === "markdown"}
                className={documentView === "markdown" ? "active" : ""}
                onClick={() => changeDocumentView("markdown")}
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
              </div></div>
              {originalDownloadFailed ? <FeedbackField>{t("knowledgeDetailDownloadFailed")}</FeedbackField> : null}
              {liveDetail?.document.capabilities?.can_edit_chunks && (!liveDetail.content_edit_mode || liveDetail.content_edit_mode === "readonly") ? <small className="content-edit-disabled-reason" id="content-edit-disabled-reason" role="status">{t(liveDetail.content_edit_reason === "project_editor_required" ? "apiForbidden" : liveDetail.content_edit_reason === "content_edit_review_locked" ? "knowledgeDetailReviewLockedReason" : "contentEditUnavailable")}</small> : null}
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
              {tagError ? <FeedbackField>{t("knowledgeDetailTagOperationFailed")}</FeedbackField> : null}
            </div>
          ) : (
          <>
          {!loading && !loadError && markdownSourceText && physicalPagesUnknown ? <small className="field-note" role="status">{t("ocrNativeDocumentPrecision")}</small> : null}
          <div className={`article-viewer article-viewer-${documentView}`} onKeyUp={() => captureManualSelection(documentView)} onMouseUp={() => captureManualSelection(documentView)} ref={articleViewerRef}>
            {loading ? <div className="empty-state compact">{t("notificationLoading")}</div> : loadError ? <div className="empty-state compact">{t("notificationError")}</div> : markdownSourceText ? (
              documentView === "original" ? <ContinuousDocumentViewer source={markdownSourceText} selectionGroups={selectedSourceGroups} sourceActionLabel={t("documentReadingSourceAction")} onSelectRange={selectSourceRange} /> :
              <div className="article-markdown"><CanonicalMarkdownSource chunks={displayChunks} onSelectChunkIds={selectMarkdownChunks} selectedChunkIds={selectedChunkIds} source={markdownSourceText} /></div>
            ) : <div className="empty-state compact">{t(markdownArtifactReasonKey(liveDetail?.markdown_artifact_reason_code))}</div>}
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
              {manualChunkError ? <FeedbackField>{t("knowledgeDetailManualChunkFailed")}</FeedbackField> : null}
            </div>
          ) : null}
          {sourceLocationError ? <FeedbackMessage tone="error">{t("sourceLocationError")}</FeedbackMessage> : null}
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
              // OPT424-033: the card holds edit, delete and tag controls, so it is a
              // plain container; selection has its own toggle button. Clicking the
              // card body still selects for pointer users.
              <article
                className={selectedChunkIdSet.has(chunk.id) ? "chunk-card selected" : "chunk-card"}
                data-chunk-id={chunk.id}
                key={chunk.id}
                onClick={() => selectChunk(chunk.id)}
              >
                <div className="chunk-head">
                  <span className="chunk-title-row">
                    <span className="chunk-title-meta">
                      <button
                        aria-label={format("knowledgeDetailSelectChunkAria", { id: chunk.id, number: chunk.index })}
                        aria-pressed={selectedChunkIdSet.has(chunk.id)}
                        className="chunk-index-badge chunk-select-toggle"
                        onClick={(event) => { event.stopPropagation(); selectChunk(chunk.id); }}
                        type="button"
                      >#{chunk.index}</button>
                      <small className="chunk-inline-meta">
                        <span>{chunk.sourceLabel}</span>
                        <span>{format("knowledgeDetailTokenCount", { count: formatCount(chunk.tokens, locale) })}</span>
                        <span>{format("knowledgeDetailConfidence", { value: Math.round(chunk.confidence * 100) })}</span>
                      </small>
                    </span>
                    <span className="chunk-card-actions">
                      <small className="chunk-technical-id">{chunk.id}</small>
                      {liveDetail?.document.capabilities?.can_edit_chunks ? <button type="button" className="chunk-delete-button" aria-label={t("contentEditChunkAction")} disabled={!liveDetail.content_edit_mode || liveDetail.content_edit_mode === "readonly"} onClick={event => { event.stopPropagation(); setContentEditor({ chunkId: chunk.id, versionId: liveDetail!.version.id }); }} onKeyDown={event => event.stopPropagation()}><Edit3 size={17} /></button> : null}
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
          {deleteError ? <FeedbackMessage tone="error"><strong>{deleteError}</strong></FeedbackMessage> : null}
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
      {contentEditor && liveDetail ? <DocumentContentEditorModal projectId={params.id} documentId={liveDetail.document.id} versionId={contentEditor.versionId} chunkId={contentEditor.chunkId} onClose={() => setContentEditor(null)} onSaved={handleContentSaved} /> : null}
    </AppShell>
  );
}
