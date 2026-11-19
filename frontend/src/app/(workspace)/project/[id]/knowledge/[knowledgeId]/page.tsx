"use client";

import { resourcePageTitle } from "@/lib/browserTitle";

import { contentUpdateFeedback } from "@/lib/contentUpdateFeedback";
import { FeedbackMessage, FeedbackField } from "@/components/FeedbackMessage";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useParams, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Code2, Edit3, FileText, Loader2, Network, Pencil, Tags, Trash2 } from "lucide-react";
import { DocumentRenameDialog } from "@/components/DocumentRenameDialog";
import { fileExtension } from "@/lib/documentNames";
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
import { fileProcessingPollDelay, isPollingAuthorizationFailure } from "@/lib/fileProcessingPolling";
import { KnowledgeDetailReads, KnowledgeReadinessBudget, acceptsKnowledgeRead, completionGateBlocksKnowledgeDetail, knowledgeReadinessKey, needsKnowledgeReadinessCheck } from "@/lib/knowledgeReadiness";
import { confirmStation, createStationRevision, deleteKnowledgeChunk, getDocumentVersionSubmissionEvidence, getKnowledgeDetail, reopenStation, retryPipelineStep, type KnowledgeDetailResponse } from "@/lib/api";
import { t as translate } from "@/lib/i18n";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { useI18n } from "@/lib/i18nClient";
import { useReadResource } from "@/lib/useReadResource";
import { markdownArtifactReasonKey, sourceSelectionGroupsForChunks, sourceSelectionScrollBehavior } from "@/lib/markdownSourceMapping";
import { retryContent, type ContentUpdateResult } from "@/lib/documentContentApi";

const DocumentContentEditorModal = dynamic(() => import("@/components/DocumentContentEditorModal").then(module => module.DocumentContentEditorModal), { ssr: false });

import { type Translate, type KnowledgeChunk, type DocumentView, visibleTagDetails, liveChunk, isPipelineActive, shouldPollKnowledgeCompletionGate } from "@/components/knowledgeDetail/knowledgeDetailModel";
import { createKnowledgeTagActions, useKnowledgeTagState } from "@/components/knowledgeDetail/useKnowledgeTagSection";
import { useManualChunkSection } from "@/components/knowledgeDetail/useManualChunkSection";
import { ChunkListPager, useChunkPage } from "@/components/knowledgeDetail/ChunkListPager";
import { ChunkDeleteDialog, DocumentGraphDialog } from "@/components/knowledgeDetail/KnowledgeDetailDialogs";
import { ChunkPreview, TagResultStrip, KnowledgeDetailCompletionGate, TagEditor } from "@/components/knowledgeDetail/KnowledgeDetailParts";
import { ChunkReferencePanel, ContentChecklist, OverlapBanner, StationActions, StationReopenDialog, StationRevisionBanner, StationStepper, activeStation, locateText, stationName, usesStations, type StationNumber } from "@/components/knowledgeDetail/ExtractionStations";

export default function KnowledgePage() {
  const params = useParams<{ id: string; knowledgeId: string }>();
  const { apiFetch, currentUser, authReady, applicationAccess } = useAuth();
  const { locale, format } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const [liveDetail, setLiveDetail] = useState<KnowledgeDetailResponse | null>(null);
  const [renameOpen, setRenameOpen] = useState(false);
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
  // CHG-442 four stations: the viewed station follows the active one unless the person picks a reached station.
  const searchParams = useSearchParams();
  const requestedStation = Number(searchParams.get("station"));
  const [pickedStation, setPickedStation] = useState<StationNumber | null>(requestedStation >= 1 && requestedStation <= 4 ? requestedStation as StationNumber : null);
  const [stationBusy, setStationBusy] = useState(false);
  const [stationError, setStationError] = useState<string | null>(null);
  const [reopenTarget, setReopenTarget] = useState<StationNumber | null>(null);
  const [onlyOverlap, setOnlyOverlap] = useState(false);
  const [onlyUnresolved, setOnlyUnresolved] = useState(false);
  const [chunkMenu, setChunkMenu] = useState<{ left: number; top: number } | null>(null);
  const tagState = useKnowledgeTagState();
  const { documentTagDraft, setDocumentTagDraft, chunkTagDrafts, setChunkTagDrafts, tagBusyKey, tagError } = tagState;
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeChunk | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const articleViewerRef = useRef<HTMLDivElement>(null);
  const chunkListRef = useRef<HTMLDivElement>(null);
  const skipNextSourceScrollRef = useRef(false);
  const displayChunks = useMemo(() => liveDetail?.chunks.map((chunk) => liveChunk(chunk, t, format)) ?? [], [format, liveDetail?.chunks, t]);
  const stationMode = usesStations(liveDetail);
  const currentActiveStation = activeStation(liveDetail);
  // CHG-447 FIX447-002: at stations 1-3 the next stage waits for the four confirmations, not for artifacts.
  const stationsPending = stationMode && typeof liveDetail?.current_station === "number" && liveDetail.current_station >= 1 && liveDetail.current_station <= 3;
  const nextStageBlockedKey = stationsPending ? "knowledgeDetailStationsPending" : liveDetail?.next_stage_block_reason === "chunks_required" ? "knowledgeDetailChunksRequired" : "knowledgeDetailArtifactsNotReady";
  const viewStation: StationNumber = !stationMode ? 4 : pickedStation && pickedStation <= (currentActiveStation ?? 4) ? pickedStation : currentActiveStation ?? 4;
  useEffect(() => {
    if (!chunkMenu) return;
    const close = (event: MouseEvent) => { if (!(event.target instanceof Element && event.target.closest(".manual-chunk-menu"))) setChunkMenu(null); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [chunkMenu]);
  const lastActiveStation = useRef(currentActiveStation);
  useEffect(() => {
    if (lastActiveStation.current !== null && lastActiveStation.current !== currentActiveStation) setPickedStation(null);
    lastActiveStation.current = currentActiveStation;
  }, [currentActiveStation]);
  const chunkNumber = useMemo(() => new Map(displayChunks.map(chunk => [chunk.id, chunk.index])), [displayChunks]);
  const overlapLabel = useCallback((chunkId: string) => (liveDetail?.overlapping_chunks?.[chunkId] ?? []).map(id => `#${chunkNumber.get(id) ?? "?"}`).join("、"), [chunkNumber, liveDetail?.overlapping_chunks]);
  const documentTags = visibleTagDetails(liveDetail?.document_tags ?? []);
  const markdownSourceText = liveDetail?.markdown_text ?? null;
  const physicalPagesUnknown = liveDetail?.pipeline?.steps.some(step => step.input_mode === "native_pdf" && step.page_map_status === "unknown") ?? false;
  const selectedChunkIdSet = useMemo(() => new Set(selectedChunkIds), [selectedChunkIds]);
  const selectedChunks = useMemo(() => displayChunks.filter((chunk) => selectedChunkIdSet.has(chunk.id)), [displayChunks, selectedChunkIdSet]);
  const listedChunks = useMemo(() => stationMode && viewStation === 2 && onlyOverlap ? displayChunks.filter(chunk => liveDetail?.overlapping_chunks?.[chunk.id]?.length) : displayChunks, [displayChunks, liveDetail?.overlapping_chunks, onlyOverlap, stationMode, viewStation]);
  const chunkPage = useChunkPage(listedChunks, selectedChunkIds); // D424-16: render 50 chunks per page
  const selectedChunk = selectedChunks[0];
  const selectedSourceGroups = useMemo(() => sourceSelectionGroupsForChunks(displayChunks, selectedChunkIds), [displayChunks, selectedChunkIds]);
  const rememberSourcePosition = useSourceViewPosition(articleViewerRef, documentView, markdownSourceText, selectedChunkIds.length);
  const { manualSelection, setManualSelection, manualChunkBusy, manualChunkError, manualOverlapIds, captureManualSelection, submitManualChunk } = useManualChunkSection({ apiFetch, params, liveDetail, setLiveDetail, articleViewerRef, markdownSourceText, setSelectedChunkIds, setSourceLocationError });
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

  // OPT424-035: the detail is one read resource for the route and user: the first read, then reads
  // scheduled while processing or a readiness check is active. Reads share the single-flight lease with
  // the manual readiness recheck; results feed the page detail that tag, chunk and retry actions update.
  const loadedRouteRef = useRef<string | null>(null);
  const readDetail = useCallback(async (signal: AbortSignal) => {
    const polling = loadedRouteRef.current === routeKey;
    const before = currentReadState.current.detail;
    const key = knowledgeReadinessKey(userId, params.id, params.knowledgeId, before);
    if (polling && key && needsKnowledgeReadinessCheck(before) && !readinessBudget.take(key)) {
      setStoppedReadiness(key);
      throw new DOMException("Readiness budget exhausted", "AbortError");
    }
    const lease = detailReads.begin(routeKey);
    if (!lease) throw new DOMException("Read already in progress", "AbortError");
    signal.addEventListener("abort", lease.cancel, { once: true });
    try {
      const detail = await fetchDetail(lease.signal);
      const latest = currentReadState.current;
      if (!lease.active() || !latest.canObserve || latest.routeKey !== routeKey) throw new DOMException("Read superseded", "AbortError");
      if (!polling) {
        if (detail.document.id !== params.knowledgeId || detail.document.project_id !== params.id) throw new Error("knowledge_read_scope_mismatch");
      } else if (!acceptsKnowledgeRead(userId, params.id, params.knowledgeId, before, latest.detail, detail)) throw new Error("knowledge_read_scope_mismatch");
      return detail;
    } finally { lease.finish(); }
  }, [detailReads, fetchDetail, params.id, params.knowledgeId, readinessBudget, routeKey, userId]);
  const [pollFailures, setPollFailures] = useState(0);
  const detailRead = useReadResource<KnowledgeDetailResponse>(readDetail, routeKey, canObserve && deniedReadRoute !== routeKey, {
    onData: (detail) => {
      loadedRouteRef.current = routeKey;
      setLiveDetail(detail);
      setLoadedRoute(routeKey);
      setSelectedChunkIds((current) => current.length ? current : detail.chunks[0]?.id ? [detail.chunks[0].id] : []);
      setLoadError(false);
    },
    onError: (error) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      handleDetailReadError(error);
      setPollFailures((count) => count + 1);
    },
  });
  const loading = detailRead.status === "loading" && loadedRoute !== routeKey;
  const reloadDetail = detailRead.reload;
  function handleDetailReadError(error: unknown) {
    if (isPollingAuthorizationFailure(error)) setDeniedReadRoute(routeKey);
    if (readinessKey && error instanceof Error && ["knowledge_read_scope_mismatch", "file_processing_poll_contract_invalid"].includes(error.message)) {
      readinessBudget.stop(readinessKey); setStoppedReadiness(readinessKey);
    }
    if (readinessKey && readinessBudget.exhausted(readinessKey)) setStoppedReadiness(readinessKey);
    setLoadError(true);
  }

  useEffect(() => () => { detailReads.cancel(); }, [detailReads, routeKey, canObserve]);

  // Schedules the next detail read while processing or a readiness check is active, re-evaluated when the
  // detail changes (from a read or an action), after a failed read, and when page visibility changes.
  const pollingActive = Boolean(canObserve && deniedReadRoute !== routeKey && loadedRoute === routeKey && (
    shouldPollKnowledgeCompletionGate(liveDetail) || liveDetail?.pipeline?.execution?.phase === "stopping" ||
    (isPipelineActive(liveDetail?.pipeline) && !liveDetail?.document_layout?.pages.length) ||
    liveDetail?.chunk_artifact_status === "queued" || liveDetail?.chunk_artifact_status === "running" ||
    Boolean(readinessKey && needsKnowledgeReadinessCheck(liveDetail) && !readinessBudget.exhausted(readinessKey))));
  const execution = liveDetail?.pipeline?.execution;
  const handleDetailReadErrorRef = useRef(handleDetailReadError);
  useEffect(() => { handleDetailReadErrorRef.current = handleDetailReadError; });
  useEffect(() => {
    if (!pollingActive) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      clearTimeout(timer);
      let delay: number;
      try { delay = fileProcessingPollDelay(execution, document.visibilityState === "hidden"); }
      catch (error) { handleDetailReadErrorRef.current(error); return; }
      timer = setTimeout(() => { void reloadDetail(); }, delay);
    };
    document.addEventListener("visibilitychange", schedule);
    schedule();
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", schedule); };
  }, [pollingActive, execution, liveDetail, pollFailures, reloadDetail]);

  // The readiness window has its own deadline, independent of the read cadence and of renders.
  const readinessActive = Boolean(canObserve && loadedRoute === routeKey && readinessKey && needsKnowledgeReadinessCheck(liveDetail));
  useEffect(() => {
    if (!readinessActive || !readinessKey) return;
    readinessBudget.observe(readinessKey);
    const deadline = setTimeout(() => {
      readinessBudget.stop(readinessKey);
      setStoppedReadiness(readinessKey);
      detailReads.cancel();
    }, readinessBudget.remainingMs(readinessKey));
    return () => clearTimeout(deadline);
  }, [detailReads, readinessActive, readinessBudget, readinessKey]);

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


  // CHUNK442-001: right-click on the highlighted selection (or Shift+F10 / the menu key, or a long press) opens the
  // chunk menu; outside the selection the browser's own menu stays.
  function selectionContains(x: number, y: number) {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return false;
    return Array.from(selection.getRangeAt(0).getClientRects()).some(rect => x >= rect.left - 2 && x <= rect.right + 2 && y >= rect.top - 2 && y <= rect.bottom + 2);
  }
  function openChunkMenu(event: React.MouseEvent<HTMLDivElement>) {
    if (!liveDetail?.manual_edit_enabled || documentView === "tags") return;
    if (!selectionContains(event.clientX, event.clientY)) { setChunkMenu(null); return; }
    captureManualSelection(documentView);
    event.preventDefault();
    setChunkMenu({ left: Math.min(window.innerWidth - 180, event.clientX), top: Math.max(72, event.clientY) });
  }
  function openChunkMenuFromKeyboard(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!(event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) || !liveDetail?.manual_edit_enabled || documentView === "tags") return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return;
    captureManualSelection(documentView);
    event.preventDefault();
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    setChunkMenu({ left: Math.min(window.innerWidth - 180, Math.max(16, rect.left)), top: Math.max(72, rect.bottom + 4) });
  }

  // OPT424-033: the card holds edit, delete and tag controls, so it is a plain container; selection has its own
  // toggle button. Clicking the card body still selects for pointer users. CHG-442: station 2 shows no tags and
  // marks overlaps; station 3 lists chunks for selection only.
  function chunkCard(chunk: KnowledgeChunk, mode: "full" | "chunks" | "select" = "full") {
    return (
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
                    {mode === "select" ? null : <span className="chunk-card-actions">
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
                    </span>}
                  </span>
                </div>
                <div className="chunk-content-shell">
                  <ChunkPreview chunk={chunk} />
                </div>
                {liveDetail?.overlapping_chunks?.[chunk.id]?.length ? <small className="chunk-overlap-label"><AlertTriangle size={13} /> {format("overlapCardLabel", { list: overlapLabel(chunk.id) })}</small> : null}
                {mode === "full" && tagMutationLocked && !mutationLocked ? <small className="field-note">{t("knowledgeDetailPublishedTagsReadonly")}</small> : null}
                {mode === "full" ? <TagEditor
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
                /> : null}
              </article>
    );
  }

  async function runStationAction(action: () => Promise<KnowledgeDetailResponse>) {
    setStationBusy(true);
    setStationError(null);
    try {
      const refreshed = await action();
      setLiveDetail(refreshed);
      setPickedStation(null);
      setSelectedChunkIds(refreshed.chunks[0]?.id ? [refreshed.chunks[0].id] : []);
      return true;
    } catch (error) {
      setStationError(operationalErrorMessage(error, t, format, "stationActionFailed"));
      return false;
    } finally {
      setStationBusy(false);
    }
  }

  function chunkListPanel(mode: "full" | "chunks" | "select", title: string) {
    return (
      <Panel title={title} action={mode === "full" ? (
        <div className="panel-action-group">
          <button className="action-button secondary" onClick={() => setGraphOpen(true)} type="button">
            <Network size={16} /> {t("knowledgeGraphPreview")}
          </button>
        </div>) : undefined}>
        {mode === "chunks" ? <OverlapBanner count={liveDetail?.overlap_group_count ?? 0} format={format} onlyOverlap={onlyOverlap} onToggle={setOnlyOverlap} t={t} /> : null}
        <div className="chunk-list extraction-chunks" ref={chunkListRef}>
          {chunkPage.items.map((chunk) => chunkCard(chunk, mode))}
          <ChunkListPager chunkPage={chunkPage} />
          {!loading && !loadError && displayChunks.length === 0 ? <div className="chunk-empty-state"><AlertTriangle size={20} /><strong>{t("knowledgeDetailNoChunksTitle")}</strong><p>{t("knowledgeDetailNoChunksHelp")}</p></div> : null}
        </div>
      </Panel>
    );
  }

  function rightPanel() {
    if (stationMode && viewStation === 1 && liveDetail) {
      return <Panel title={t("stationChecklistTitle")}><ContentChecklist detail={liveDetail} format={format} onLocate={(excerpt) => { if (!locateText(articleViewerRef.current, excerpt)) setSourceLocationError(true); }} t={t} /></Panel>;
    }
    if (stationMode && viewStation === 2) return chunkListPanel("chunks", t("knowledgeDetailChunkResults"));
    if (stationMode && viewStation === 3 && liveDetail) {
      return (
        <Panel title={t("stationName3")}>
          <div className="station-tag-reference">
            {selectedChunk ? <>
              <small className="field-note">{format("knowledgeDetailSelectChunkAria", { id: selectedChunk.id, number: selectedChunk.index })}</small>
              <TagEditor
                busy={tagBusyKey?.startsWith(`chunk:${selectedChunk.id}:`) ?? false}
                disabled={tagMutationLocked}
                draft={chunkTagDrafts[selectedChunk.id] ?? ""}
                label={t("knowledgeDetailChunkTagResults")}
                onAdd={() => addChunkTagFromDraft(selectedChunk.id)}
                onAuto={() => autoTagOneChunk(selectedChunk.id)}
                onDelete={(tagId) => deleteOneChunkTag(selectedChunk.id, tagId)}
                onDraft={(value) => setChunkTagDrafts((current) => ({ ...current, [selectedChunk.id]: value }))}
                tags={selectedChunk.tagDetails}
                t={t}
              />
            </> : null}
            <ChunkReferencePanel apiFetch={apiFetch} chunkId={selectedChunk?.id ?? null} detail={liveDetail} editable={!tagMutationLocked && Boolean(liveDetail.document.capabilities?.can_edit_chunks)} format={format}
              onOnlyUnresolved={setOnlyUnresolved} onSelectChunk={(chunkId) => { setOnlyUnresolved(false); selectMarkdownChunks([chunkId]); }} onlyUnresolved={onlyUnresolved} projectId={params.id} t={t} />
            <div className="document-tag-strip">
              <div><strong>{t("knowledgeDetailDocumentTags")}</strong><small>{t("knowledgeDetailDocumentTagsHelp")}</small></div>
              <TagEditor busy={tagBusyKey?.startsWith("document:") ?? false} disabled={tagMutationLocked} draft={documentTagDraft} onAdd={addDocumentTagFromDraft}
                onAuto={autoTagWholeDocument} onDelete={deleteWholeDocumentTag} onDraft={setDocumentTagDraft} tags={documentTags} t={t} />
            </div>
            {tagError ? <FeedbackField>{t("knowledgeDetailTagOperationFailed")}</FeedbackField> : null}
          </div>
        </Panel>
      );
    }
    return chunkListPanel("full", t("knowledgeDetailChunkResults"));
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
        {liveDetail ? <span className="document-title-edit"><strong>{liveDetail.document.title}</strong>{liveDetail.document.capabilities?.can_manage_lifecycle && liveDetail.document.source_type !== "project_reference" ? <button aria-label={format("documentRenameButtonLabel", { title: liveDetail.document.title })} className="icon-button" onClick={() => setRenameOpen(true)} title={t("documentRenameTitle")} type="button"><Pencil size={14} /></button> : null}</span> : null}
        <span>{t("knowledgeDetailDocumentVersion")} {liveDetail?.version.version_label ?? "-"}</span>
        <span>{liveDetail?.pipeline?.status ?? t("knowledgeDetailNoPipeline")}</span>
        <StatusBadge status={liveDetail?.version.status ?? "loading"} />
        <div className="project-context-actions">
          {(liveDetail?.chat_access ? liveDetail.chat_access.query_enabled : liveDetail && !knowledgeGateBlocked && liveDetail.next_stage_allowed) ? <Link className="text-link next-stage-link" href={liveDetail?.chat_access?.mode === "published"
            ? `/project/${params.id}/import?chat_version_id=${encodeURIComponent(liveDetail.chat_access.document_version_id)}` : `/project/${params.id}/knowledge/${params.knowledgeId}/chat-test`}>
            {t(liveDetail?.chat_access?.mode === "published" ? "knowledgePublishedChat" : "chatTest")} <ArrowRight size={16} />
          </Link> : liveDetail?.chat_access?.mode === "history_only" ? <Link className="text-link" href={`/project/${params.id}/knowledge/${params.knowledgeId}/chat-test`}>
            {t("knowledgeChatHistoryOnly")}
          </Link> : liveDetail && !knowledgeGateBlocked ? <span className="next-stage-disabled" title={t(nextStageBlockedKey)}><AlertTriangle size={16} /> {t("chatTest")}</span> : null}
        </div>
      </div>

      {liveDetail?.document.superseded_by?.length ? <FeedbackMessage tone="warning">{format("documentSupersededBy", { titles: liveDetail.document.superseded_by.map(item => `〈${item.title}〉`).join("、") })}</FeedbackMessage> : null}
      {stationMode && liveDetail ? <div className="station-header">
        <StationStepper detail={liveDetail} onView={(station) => { setPickedStation(station); setStationError(null); if (station < 3 && documentView === "tags") setDocumentView("original"); }} t={t} viewStation={viewStation} />
        {liveDetail.content_edit_reason === "content_edit_station_revision_required" && liveDetail.document.capabilities?.can_edit_chunks
          ? <StationRevisionBanner busy={stationBusy} error={stationError} onCreate={() => void runStationAction(() => createStationRevision(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, liveDetail.version.lock_version))} t={t} />
          : <StationActions busy={stationBusy} canEdit={Boolean(liveDetail.document.capabilities?.can_edit_chunks)} detail={liveDetail} error={stationError} format={format}
              onConfirm={(station) => void runStationAction(() => confirmStation(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, station, liveDetail.version.lock_version))}
              onReopen={(station) => { setStationError(null); setReopenTarget(station); }} t={t} viewStation={viewStation} />}
      </div> : null}
      {(liveDetail?.chunk_artifact_error_code === "embedding_build_provider_result_unknown" || liveDetail?.chunk_artifact_error_code === "model_usage_persistence_unconfirmed") && contentFeedback?.reasonCode !== liveDetail?.chunk_artifact_error_code ? <FeedbackMessage tone="warning">{t(liveDetail.chunk_artifact_error_code === "model_usage_persistence_unconfirmed" ? "modelUsagePersistenceUnconfirmed" : "embeddingBuildResultUnknown")}</FeedbackMessage> : null}
      {!knowledgeGateBlocked && contentFeedback ? <FeedbackMessage tone={contentFeedback.tone}>{t(contentFeedback.message)}</FeedbackMessage> : null}
      {liveDetail && knowledgeGateBlocked ? (
        <KnowledgeDetailCompletionGate contentFeedback={contentFeedback} detail={liveDetail} format={format} onRetry={handleRetryStep} onEdit={() => setContentEditor({ versionId: liveDetail!.version.id })} projectId={params.id} retryError={retryError} retryingStep={retryingStep} reviewLocked={mutationLocked} t={t} />
      ) : (
        <>
      <div className="content-grid split extraction-workspace">
        {stationMode && viewStation === 3 ? chunkListPanel("select", t("knowledgeDetailChunkResults")) : <Panel
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
              {stationMode && viewStation < 3 ? null : <button
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
              </button>}
            </div>
              </div></div>
              {originalDownloadFailed ? <FeedbackField>{t("knowledgeDetailDownloadFailed")}</FeedbackField> : null}
              {liveDetail?.document.capabilities?.can_edit_chunks && (!liveDetail.content_edit_mode || liveDetail.content_edit_mode === "readonly") ? <small className="content-edit-disabled-reason" id="content-edit-disabled-reason" role="status">{t(liveDetail.content_edit_reason === "project_editor_required" ? "apiForbidden" : liveDetail.content_edit_reason === "content_edit_review_locked" ? "knowledgeDetailReviewLockedReason" : liveDetail.content_edit_reason === "content_edit_station_reopen_required" ? "contentEditStationReopenRequired" : liveDetail.content_edit_reason === "content_edit_station_revision_required" ? "contentEditStationRevisionRequired" : "contentEditUnavailable")}</small> : null}
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
          <div className={`article-viewer article-viewer-${documentView}`} onContextMenu={openChunkMenu} onKeyDown={openChunkMenuFromKeyboard} onKeyUp={() => captureManualSelection(documentView)} onMouseUp={(event) => { if (event.button === 0) { setChunkMenu(null); captureManualSelection(documentView); } }} ref={articleViewerRef}>
            {loading ? <div className="empty-state compact">{t("notificationLoading")}</div> : loadError ? <div className="empty-state compact">{t("notificationError")}</div> : markdownSourceText ? (
              documentView === "original" ? <ContinuousDocumentViewer source={markdownSourceText} selectionGroups={selectedSourceGroups} sourceActionLabel={t("documentReadingSourceAction")} onSelectRange={selectSourceRange} /> :
              <div className="article-markdown"><CanonicalMarkdownSource chunks={displayChunks} onSelectChunkIds={selectMarkdownChunks} selectedChunkIds={selectedChunkIds} source={markdownSourceText} /></div>
            ) : <div className="empty-state compact">{t(markdownArtifactReasonKey(liveDetail?.markdown_artifact_reason_code))}</div>}
          </div>
          <TagResultStrip className="document-tag-result-strip" label={t("knowledgeDetailDocumentTags")} tags={documentTags} t={t} />
          </>
          )}
          {manualSelection && chunkMenu ? (
            <div aria-label={t("manualChunkMenuLabel")} className="manual-chunk-popover manual-chunk-menu" onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); setChunkMenu(null); } }} role="menu" style={{ left: chunkMenu.left, top: chunkMenu.top }}>
              <button
                autoFocus
                disabled={manualChunkBusy}
                onMouseDown={(event) => { event.preventDefault(); event.stopPropagation(); }}
                onClick={(event) => { event.stopPropagation(); setChunkMenu(null); void submitManualChunk(); }}
                role="menuitem"
                type="button"
              >
                {manualChunkBusy ? <Loader2 className="spin" size={15} /> : <Edit3 size={15} />} {t("manualChunkMenuAction")}
              </button>
            </div>
          ) : null}
          {manualChunkError ? <FeedbackField>{t("knowledgeDetailManualChunkFailed")}</FeedbackField> : null}
          {manualOverlapIds.length ? <FeedbackMessage tone="warning">{format("manualChunkOverlapNotice", { list: manualOverlapIds.map(id => `#${chunkNumber.get(id) ?? "?"}`).join("、") })}</FeedbackMessage> : null}
          {liveDetail?.manual_edit_enabled && documentView !== "tags" ? <small className="field-note">{t("manualChunkMenuHint")}</small> : null}
          {sourceLocationError ? <FeedbackMessage tone="error">{t("sourceLocationError")}</FeedbackMessage> : null}
        </Panel>}
        {rightPanel()}
      </div>

      {readinessPending ? <KnowledgeReadinessNotice stopped={readinessStopped || deniedReadRoute === routeKey}
        busy={manualReadBusy} canRetry={canObserve && deniedReadRoute !== routeKey} onRetry={() => void recheckReadinessOnce()} /> :
      <div className={liveDetail?.next_stage_allowed ? "review-banner" : "review-banner warning"}>
        {liveDetail?.next_stage_allowed ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}
        <span>{liveDetail?.chat_access?.mode === "published" ? t("knowledgePublishedChat") : liveDetail?.next_stage_allowed ? t("knowledgeDetailReviewReady") : t(nextStageBlockedKey)}</span>
      </div>}

      {reopenTarget && liveDetail ? <StationReopenDialog busy={stationBusy} chunkCount={liveDetail.active_chunk_count} error={stationError} format={format} onCancel={() => setReopenTarget(null)}
        onConfirm={() => void runStationAction(() => reopenStation(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, reopenTarget, liveDetail.version.lock_version)).then(done => { if (done) setReopenTarget(null); })} station={reopenTarget} t={t} /> : null}
      {deleteTarget ? <ChunkDeleteDialog busy={deleteBusy} chunk={deleteTarget} error={deleteError} onCancel={() => setDeleteTarget(null)} onConfirm={() => void confirmChunkDeletion()} /> : null}
      {renameOpen && liveDetail ? <DocumentRenameDialog apiFetch={apiFetch} documentId={liveDetail.document.id} extension={liveDetail.version.canonical_extension ?? fileExtension(liveDetail.version.original_file_name)} lockVersion={liveDetail.document.lock_version} onClose={() => setRenameOpen(false)} onRenamed={(summary) => {
        setLiveDetail((current) => current ? { ...current, document: { ...current.document, title: summary.title, lock_version: summary.lock_version }, original_file: current.original_file ? { ...current.original_file, download_file_name: `${summary.title}${current.version.canonical_extension ?? fileExtension(current.version.original_file_name)}` } : current.original_file } : current);
        setRenameOpen(false);
      }} projectId={params.id} title={liveDetail.document.title} /> : null}
      {graphOpen ? <DocumentGraphDialog detail={liveDetail ?? null} onClose={() => setGraphOpen(false)} projectId={params.id} /> : null}
        </>
      )}
      {contentEditor && liveDetail ? <DocumentContentEditorModal projectId={params.id} documentId={liveDetail.document.id} versionId={contentEditor.versionId} chunkId={contentEditor.chunkId} onClose={() => setContentEditor(null)} onSaved={handleContentSaved} /> : null}
    </AppShell>
  );
}
