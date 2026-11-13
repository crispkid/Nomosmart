"use client";

import { DropdownSelect } from "@/components/DropdownSelect";

import { resourcePageTitle } from "@/lib/browserTitle";


import { useModalFocus } from "@/components/useModalFocus";

import { UiValidationError } from "@/lib/transportError";
import { useFeedback } from "@/components/FeedbackProvider";
import { ocrFailureKey, ocrRetryBlocked } from "@/lib/ocrPresentation";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, Clock3, Database, FilePlus2, Layers3, MessageSquareText, Network, ShieldCheck, UploadCloud, X } from "lucide-react";
import { AppShell, PageGrid, Panel, StatCard } from "@/components/AppShell";
import { DataServiceModal, UploadFilesModal, type CreatedKnowledgeDocument, type DataServicePayload, type SourceState } from "@/components/KnowledgeSourceModals";
import { ProjectReferenceModal } from "@/components/ProjectReferenceModal";
import { ProjectChatTest } from "@/components/ProjectChatTest";
import { formatCount } from "@/lib/numberFormat";
import { pipelineTimeFields } from "@/lib/pipelineElapsed";
import { usePipelineElapsedClock } from "@/lib/usePipelineElapsedClock";
import { fileProcessingPollDelay } from "@/lib/fileProcessingPolling";
import { useAuth } from "@/components/AuthProvider";
import { createDataSource, getDataSourceConnectionOptions, getPipelineDetail, getProject, getUploadConfig, importProjectDocumentReferences, listDataSourceSyncRuns, listModels, listProjectDocuments, listProjectMembers, listProjectReferenceSources, queueDataSourceSync, retryPipelineStep, startDocumentExtraction, testDataSourceConnection, uploadProjectDocuments, type AIModelResponse, type ApiError, type DataSyncRunResponse, type DocumentSummary, type DocumentUploadResult, type PipelineRunDetail, type ProjectResponse, type ReferenceSourceProjectResponse } from "@/lib/api";
import { t as translate } from "@/lib/i18n";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { pipelineStepLabel } from "@/lib/pipelineSteps";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";
import { extractionOutcome, pipelineIsExecuting } from "@/lib/reviewPresentation";
import { confirmedUploadResults, UploadAttemptGuard, uploadOutcomeUnknown, type UploadBatchResult } from "@/lib/uploadProgress";
import { useDocumentList } from "@/lib/useDocumentList";
import { useDocumentPipelinePolling } from "@/lib/useDocumentPipelinePolling";
import { useTerminalChunkCounts } from "@/lib/useTerminalChunkCounts";
import { extractionRunKey, FILE_EXTRACTION_OBSERVATION_LIMIT, ManualExtractionStarts, observationDelay, PipelineObservationOwnership } from "@/lib/manualExtraction";

import { type Translate, isReviewLockedVersionStatus, type DocumentItem, mapPipelineStatus, publishStageCurrentStep, pipelineEtaForStatus, pipelineSteps, UPLOAD_EXTRACTION_GATE_INITIAL_DELAY_MS, UPLOAD_EXTRACTION_GATE_POLL_INTERVAL_MS, pipelineReachedExtractionGate, pipelineFailedBeforeExtractionGate, liveDocumentFromSummary, serviceDocumentFromResponse, getSourceState, formatSyncDate, syncRunStep } from "@/components/projectImport/importDocumentModel";
import { DocumentPipelineCard } from "@/components/projectImport/DocumentPipelineCard";
import { createStatusChangeActions, createStatusChangeView, useStatusChangeState } from "@/components/projectImport/useStatusChangeSection";
import { createProjectVersionActions, createProjectVersionView, useProjectVersionState } from "@/components/projectImport/useProjectVersionSection";
import { createProjectPermissionActions, createProjectPermissionView, useProjectPermissionState } from "@/components/projectImport/useProjectPermissionSection";

// OPT424-036: the graph engine loads only when a graph dialog opens.
const ProjectGraphPreview = dynamic(() => import("@/components/ProjectGraphPreview").then(module => module.ProjectGraphPreview), { ssr: false });

export default function ImportPage() {
  const params = useParams<{ id: string }>();
  const { currentUser } = useAuth();
  // A new project owns a new list and attempt lifecycle. Old callbacks cannot
  // update the next project's state, including a navigate-away-and-back cycle.
  return <ProjectImportPage key={`${params.id}:${currentUser?.user_id ?? "anonymous"}`} />;
}

function ProjectImportPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const processingPollScope = useRef(0);
  const uploadAttempts = useRef(new UploadAttemptGuard());
  const manualStarts = useRef(new ManualExtractionStarts());
  const [observationOwnership] = useState(() => new PipelineObservationOwnership());
  const releaseModalObservation = useCallback(() => {
    uploadAttempts.current.leave();
    observationOwnership.releaseOwner("modal");
  }, [observationOwnership]);
  useEffect(() => {
    processingPollScope.current += 1;
    const guard = uploadAttempts.current;
    const starts = manualStarts.current;
    return () => { processingPollScope.current += 1; guard.invalidate(); starts.invalidate(); observationOwnership.clear(); };
  }, [observationOwnership, params.id]);
  const searchParams = useSearchParams();
  const requestedChatVersions = searchParams.getAll("chat_version_id");
  const requestedChatVersion = requestedChatVersions.length === 0 ? undefined : requestedChatVersions.length === 1 ? requestedChatVersions[0] : "";
  const { apiFetch, currentUser } = useAuth();
  const { locale, format, localize } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [titleRead, setTitleRead] = useState<{ fetch: typeof apiFetch; route: string } | null>(null);
  const [projectAccess, setProjectAccess] = useState<"loading" | "granted" | "denied" | "error">("loading");
  const { allDocuments, setLiveDocuments, setCreatedImports,
    replaceLiveDocuments, updateUploadedDocumentSnapshots, acceptExtractionReceipt, updatePipelineSnapshots, updateTerminalChunkCount } = useDocumentList();
  const [manualStartPending, setManualStartPending] = useState<Record<string, boolean>>({});
  const [manualStartNotices, setManualStartNotices] = useState<Record<string, { versionId?: string; unknown: boolean; message: string }>>({});
  const [ocrModels, setOcrModels] = useState<AIModelResponse[]>([]);
  const [documentQuery, setDocumentQuery] = useState("");
  const [sortBy, setSortBy] = useState("updatedAt");
  const [activeModal, setActiveModal] = useState<"graph" | "chat" | null>(null);
  const featureDialogRef = useModalFocus(Boolean(activeModal), () => setActiveModal(null));
  const [fixedChatVersion, setFixedChatVersion] = useState<string | undefined>(requestedChatVersion);
  useEffect(() => {
    setFixedChatVersion(requestedChatVersion);
    if (requestedChatVersion !== undefined) setActiveModal("chat");
  }, [requestedChatVersion, params.id]);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [uploadNotice, setUploadNotice] = useState<TranslationKey | null>(null);
  const [initialUploadFiles, setInitialUploadFiles] = useState<File[]>([]);
  const [maxUploadSizeMb, setMaxUploadSizeMb] = useState(100);
  const [projectDropActive, setProjectDropActive] = useState(false);
  const projectDragDepth = useRef(0);
  const [dataServiceModalOpen, setDataServiceModalOpen] = useState(false);
  const [referenceModalOpen, setReferenceModalOpen] = useState(false);
  const [referenceSources, setReferenceSources] = useState<ReferenceSourceProjectResponse[]>([]);
  const [referenceSourcesLoading, setReferenceSourcesLoading] = useState(false);
  const [referenceSourcesError, setReferenceSourcesError] = useState("");
  const [documentLoadState, setDocumentLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [documentLoadError, setDocumentLoadError] = useState("");
  const { notify } = useFeedback();
  const statusChangeState = useStatusChangeState();
  const { committedStatuses, pendingStatusChange, statusSubmitting } = statusChangeState;
  const [pipelineDetailLoading, setPipelineDetailLoading] = useState<Record<string, boolean>>({});
  const [pipelineRetryNotices, setPipelineRetryNotices] = useState<Record<string, { pipelineId: string; message: string }>>({});
  const [syncRunsByDataSource, setSyncRunsByDataSource] = useState<Record<string, DataSyncRunResponse[]>>({});
  const [syncRunLoading, setSyncRunLoading] = useState<Record<string, boolean>>({});
  const projectReady = projectAccess === "granted" && project?.id === params.id;
  const canEditLifecycle = projectReady && (project?.capabilities.can_manage_lifecycle ?? false);
  const canUpload = projectAccess === "granted" && project?.id === params.id && documentLoadState === "ready" && project?.capabilities?.can_upload === true;
  const canStartExtraction = projectAccess === "granted" && project?.id === params.id && documentLoadState === "ready" && project?.capabilities?.can_start_extraction === true;
  const terminalCounts = useTerminalChunkCounts({ projectId: params.id, documents: allDocuments, apiFetch,
    enabled: Boolean(currentUser && projectAccess === "granted" && project?.id === params.id && documentLoadState === "ready"),
    receive: updateTerminalChunkCount });
  useDocumentPipelinePolling({
    projectId: params.id,
    documents: allDocuments,
    enabled: Boolean(currentUser && projectAccess === "granted" && project?.id === params.id && documentLoadState === "ready" && !uploadModalOpen),
    apiFetch,
    applyDetail: applyPipelineDetailToDocument,
    receive: updatePipelineSnapshots,
    ownership: observationOwnership,
  });
  const canManageProjectPermissions = projectReady && (project?.is_owner ?? false);
  const projectPermissionState = useProjectPermissionState({ apiFetch, canManageProjectPermissions, params, t });
  const { permissionModalOpen, setProjectMembers } = projectPermissionState;
  const projectPermissionActions = createProjectPermissionActions(projectPermissionState, { apiFetch, canManageProjectPermissions, currentUser, params, project, setProject, setProjectAccess });
  const { openPermissionModal } = projectPermissionActions;

  useEffect(() => {
    let cancelled = false;
    setProjectAccess("loading");
    Promise.all([
      getProject(apiFetch, params.id),
      listProjectMembers(apiFetch, params.id).catch(() => [])
    ]).then(([projectRow, members]) => {
      if (cancelled) return;
      setProject(projectRow);
      setTitleRead({ fetch: apiFetch, route: params.id });
      setProjectAccess("granted");
      setProjectMembers(members);
    }).catch((error: ApiError) => {
      if (!cancelled) {
        setProject(null);
        setProjectAccess(error.status === 401 || error.status === 403 ? "denied" : "error");
      }
    });
    return () => { cancelled = true; };
  }, [apiFetch, params.id, currentUser?.user_id, setProjectMembers]);

  useEffect(() => {
    if (projectAccess === "loading" || (projectAccess === "granted" && project?.capabilities.can_upload)) return;
    releaseModalObservation();
    processingPollScope.current += 1;
    uploadAttempts.current.invalidate();
    manualStarts.current.invalidate();
    setUploadModalOpen(false);
    setInitialUploadFiles([]);
    setDataServiceModalOpen(false);
    setProjectDropActive(false);
    projectDragDepth.current = 0;
  }, [projectAccess, project?.capabilities.can_upload, releaseModalObservation]);

  useEffect(() => {
    let cancelled = false;
    setDocumentLoadState("loading");
    setDocumentLoadError("");
    Promise.all([
      listProjectDocuments(apiFetch, params.id),
      listModels(apiFetch, "OCR"),
      getUploadConfig(apiFetch).catch(() => null)
    ]).then(async ([documents, models, uploadConfig]) => {
      if (cancelled) return;
      const hydrated = await Promise.all(documents.map(async (document) => {
        const versionId = document.latest_version?.id;
        const pipelineId = document.latest_pipeline?.id;
        if (!versionId || !pipelineId) return liveDocumentFromSummary(document, t);
        try {
          const detail = await getPipelineDetail(apiFetch, params.id, document.id, versionId, pipelineId);
          return liveDocumentFromSummary(document, t, detail);
        } catch {
          return liveDocumentFromSummary(document, t);
        }
      }));
      if (cancelled) return;
      replaceLiveDocuments(hydrated);
      setOcrModels(models.filter((model) => model.is_active));
      if (uploadConfig?.max_upload_size_mb) setMaxUploadSizeMb(uploadConfig.max_upload_size_mb);
      setDocumentLoadState("ready");
    }).catch(() => {
      if (!cancelled) {
        setLiveDocuments([]);
        setOcrModels([]);
        setDocumentLoadState("error");
        setDocumentLoadError(t("projectImportLoadDocumentsFailed"));
      }
    });
    return () => { cancelled = true; };
  }, [apiFetch, params.id, t, replaceLiveDocuments, setLiveDocuments]);

  const visibleDocuments = useMemo(() => {
    const query = documentQuery.trim().toLowerCase();
    const filtered = allDocuments.filter((document) => {
      const haystack = [
        document.title,
        document.sourceType,
        document.owner,
        document.documentStatus,
        document.versionStatus,
        document.pipeline.status,
        document.pipeline.currentStep
      ].join(" ").toLowerCase();
      return !query || haystack.includes(query);
    });

    return [...filtered].sort((a, b) => {
      if (sortBy === "name") return a.title.localeCompare(b.title, "zh-Hant");
      if (sortBy === "status") return a.documentStatus.localeCompare(b.documentStatus, "zh-Hant");
      if (sortBy === "progress") return b.pipeline.progress - a.pipeline.progress;
      return b.updatedAt.localeCompare(a.updatedAt);
    });
  }, [allDocuments, documentQuery, sortBy]);
  const elapsedEnabled = Boolean(currentUser && projectReady && documentLoadState === "ready");
  const elapsedNow = usePipelineElapsedClock(visibleDocuments
    .filter(document => document.sourceState === "pipeline" && document.documentStatus !== "deleted")
    .map(document => document.pipeline), elapsedEnabled, params.id);
  const projectVersionState = useProjectVersionState({ apiFetch, format, params, t, allDocuments, syncRunsByDataSource, setSyncRunsByDataSource, setSyncRunLoading });
  const { setVersionDocumentId } = projectVersionState;

  async function refreshDataSourceSyncRuns(dataSourceId: string) {
    setSyncRunLoading((current) => ({ ...current, [dataSourceId]: true }));
    try {
      const runs = await listDataSourceSyncRuns(apiFetch, params.id, dataSourceId);
      setSyncRunsByDataSource((current) => ({ ...current, [dataSourceId]: runs }));
      return runs;
    } finally {
      setSyncRunLoading((current) => ({ ...current, [dataSourceId]: false }));
    }
  }

  function applySyncRunState(documentId: string, run: DataSyncRunResponse) {
    const sourceState: SourceState = run.status === "failed" ? "sync_failed" : run.status === "success" || run.status === "unchanged" ? "ready_for_extraction" : "syncing";
    const syncedAt = formatSyncDate(run.completed_at ?? run.started_at ?? run.created_at, locale);
    const patch = {
      sourceState,
      updatedAt: syncedAt,
      pipeline: {
        currentStep: syncRunStep(run, t),
        elapsed: "",
        eta: run.status === "queued" ? t("projectImportWaitingWorker") : run.status === "running" ? t("projectImportSyncRunning") : "",
        error: run.error_summary ? operationalCodeMessage(run.error_code, t, format, "projectImportSyncFailed") : ""
      }
    };
    const applyPatch = (item: CreatedKnowledgeDocument): CreatedKnowledgeDocument => {
      if (item.id !== documentId) return item;
      const nextVersions = run.document_version_id && !item.versions.some((version) => version.id === run.document_version_id)
        ? [{ id: run.document_version_id, label: t("projectImportLatestSyncVersion"), status: "draft", createdAt: syncedAt, author: t("projectImportSystemSync") }, ...item.versions]
        : item.versions;
      return {
        ...item,
        ...patch,
        latestVersionId: run.document_version_id ?? item.latestVersionId,
        versionStatus: run.document_version_id ? "draft" : item.versionStatus,
        versions: nextVersions,
        pipeline: { ...item.pipeline, ...patch.pipeline }
      };
    };
    setCreatedImports((current) => current.map(applyPatch));
    setLiveDocuments((current) => current.map(applyPatch));
  }

  async function pollDataSourceSyncRun(documentId: string, dataSourceId: string, runId: string) {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, attempt === 0 ? 500 : 2000));
      const runs = await refreshDataSourceSyncRuns(dataSourceId);
      const latestRun = runs.find((run) => run.id === runId) ?? runs[0];
      if (!latestRun) continue;
      applySyncRunState(documentId, latestRun);
      if (["success", "unchanged", "failed"].includes(latestRun.status)) return;
    }
  }

  function applyPipelineDetailToDocument(document: CreatedKnowledgeDocument, detail: PipelineRunDetail): CreatedKnowledgeDocument {
    if (detail.project_id !== params.id || detail.document_id !== document.id
      || detail.document_version_id !== document.latestVersionId || detail.id !== document.pipeline.id) return document;
    const status = mapPipelineStatus(detail.status);
    const versionStatus = detail.status === "submission_ready" ? "submission_ready" : detail.status === "failed" ? "failed" : document.versionStatus;
    const outcome = extractionOutcome({ versionStatus, pipelineStatus: detail.status,
      currentStep: detail.current_step_name, steps: pipelineSteps(detail, t) });
    return {
      ...document,
      sourceState: "pipeline",
      versionStatus,
      chunks: versionStatus === "submission_ready" && document.versionStatus !== "submission_ready" ? null : document.chunks,
      extractionSuccessful: outcome === "complete",
      extractionOutcome: outcome,
      versions: document.versions.map((version) => version.id === document.latestVersionId ? { ...version, status: versionStatus } : version),
      pipeline: {
        ...document.pipeline,
        id: detail.id,
        ...pipelineTimeFields(detail),
        execution: detail.execution,
        status,
        progress: detail.progress_percent,
        currentStep: detail.current_step_name ? pipelineStepLabel(detail.current_step_name, t) : publishStageCurrentStep(status, t),
        eta: pipelineEtaForStatus(status, t),
        error: detail.error_message ? t(ocrFailureKey(detail.steps.find(step => step.status === "failed"), detail.error_message)) : "",
        observationInterrupted: false,
        cleanupObservationStopped: false,
        steps: pipelineSteps(detail, t)
      }
    };
  }

  async function pollPipelineUntilCompletionGate(document: CreatedKnowledgeDocument, onProgressDocuments?: (documents: CreatedKnowledgeDocument[]) => void, initialDetail?: PipelineRunDetail, canObserve: () => boolean = () => true) {
    const scope = processingPollScope.current;
    const key = extractionRunKey(params.id, document);
    if (!key || !canObserve()) return document;
    const lease = observationOwnership.acquire(key, "modal");
    const observing = () => lease.active() && scope === processingPollScope.current && canObserve();
    let latestDetail = initialDetail;
    let latestDocument = latestDetail ? applyPipelineDetailToDocument(document, latestDetail) : document;
    try {
    if (latestDetail) {
      onProgressDocuments?.([latestDocument]);
      updateUploadedDocumentSnapshots([latestDocument]);
    }
    for (let attempt = 0; attempt < FILE_EXTRACTION_OBSERVATION_LIMIT; attempt += 1) {
      if (pipelineReachedExtractionGate(latestDetail) || pipelineFailedBeforeExtractionGate(latestDetail)) return latestDocument;
      if (!document.latestVersionId || !document.pipeline.id) return latestDocument;
      if (!observing()) return latestDocument;
      await observationDelay(fileProcessingPollDelay(latestDetail?.execution, globalThis.document.visibilityState === "hidden",
        attempt === 0 && latestDetail ? UPLOAD_EXTRACTION_GATE_INITIAL_DELAY_MS : UPLOAD_EXTRACTION_GATE_POLL_INTERVAL_MS), lease.signal);
      if (!observing()) return latestDocument;
      try {
        latestDetail = await getPipelineDetail(apiFetch, params.id, document.id, document.latestVersionId, document.pipeline.id, lease.signal);
      } catch {
        if (!observing()) return latestDocument;
        latestDocument = { ...latestDocument, pipeline: { ...latestDocument.pipeline, observationInterrupted: true } };
        onProgressDocuments?.([latestDocument]);
        updateUploadedDocumentSnapshots([latestDocument]);
        return latestDocument;
      }
      if (!observing()) return latestDocument;
      latestDocument = applyPipelineDetailToDocument(latestDocument, latestDetail);
      onProgressDocuments?.([latestDocument]);
      updateUploadedDocumentSnapshots([latestDocument]);
    }
    return latestDocument;
    } finally { lease.release(); }
  }

  function addUploadedDocuments(documents: CreatedKnowledgeDocument[], autoExtractionId?: string) {
    updateUploadedDocumentSnapshots(documents);
    if (autoExtractionId) router.push(`/project/${params.id}/knowledge/${autoExtractionId}`);
  }

  function openUploadModal(files: File[] = []) {
    if (!canUpload) return;
    if (uploadAttempts.current.isPending()) { setUploadNotice("uploadExistingPending"); return; }
    observationOwnership.releaseOwner("list");
    setInitialUploadFiles(files);
    setUploadModalOpen(true);
  }

  function closeUploadModal() {
    releaseModalObservation();
    setUploadModalOpen(false);
    setInitialUploadFiles([]);
    projectDragDepth.current = 0;
    setProjectDropActive(false);
    const scope = processingPollScope.current;
    const attempt = uploadAttempts.current.current();
    const current = () => scope === processingPollScope.current && uploadAttempts.current.accepts(attempt);
    void listProjectDocuments(apiFetch, params.id).then((documents) => {
      if (current()) replaceLiveDocuments(documents.map((document) => liveDocumentFromSummary(document, t)));
    }).catch(() => {
      if (current()) setUploadNotice("uploadListRefreshFailed");
    });
  }

  function addDataServiceDocument(document: CreatedKnowledgeDocument) {
    setCreatedImports((current) => [document, ...current]);
  }

  const loadLiveDataSourceOptions = useCallback(async () => {
    if (!projectReady) throw new UiValidationError("projectImportUploadNotAllowed");
    return getDataSourceConnectionOptions(apiFetch, params.id);
  }, [apiFetch, params.id, projectReady]);

  async function testLiveDataSource(payload: DataServicePayload) {
    if (!projectReady) throw new UiValidationError("projectImportUploadNotAllowed");
    await testDataSourceConnection(apiFetch, params.id, payload);
  }

  async function createLiveDataSource(payload: DataServicePayload) {
    if (!projectReady) throw new UiValidationError("projectImportUploadNotAllowed");
    const response = await createDataSource(apiFetch, params.id, payload);
    return serviceDocumentFromResponse(response, t);
  }

  async function loadReferenceSources() {
    setReferenceModalOpen(true);
    setReferenceSourcesLoading(true);
    setReferenceSourcesError("");
    try {
      const sources = await listProjectReferenceSources(apiFetch, params.id);
      setReferenceSources(sources);
    } catch (error) {
      setReferenceSourcesError(operationalErrorMessage(error, t, format, "referenceLoadSourcesFailed"));
    } finally {
      setReferenceSourcesLoading(false);
    }
  }

  async function createLiveReferences(mode: "reference" | "copy", items: Array<{ source_document_id: string; source_version_id: string; old_version_confirmed?: boolean }>) {
    if (!projectReady) throw new UiValidationError("projectImportUploadNotAllowed");
    const response = await importProjectDocumentReferences(apiFetch, params.id, { mode, items });
    const created = await Promise.all(response.results.filter((result) => result.status === "created" && result.document).map(async (result) => {
      const document = result.document!;
      const versionId = document.latest_version?.id;
      const pipelineId = document.latest_pipeline?.id;
      if (!versionId || !pipelineId) return liveDocumentFromSummary(document, t);
      try {
        const detail = await getPipelineDetail(apiFetch, params.id, document.id, versionId, pipelineId);
        return liveDocumentFromSummary(document, t, detail);
      } catch {
        return liveDocumentFromSummary(document, t);
      }
    }));
    if (created.length) setCreatedImports((current) => [...created, ...current]);
    return {
      createdCount: created.length,
      errors: response.results.filter((result) => result.status === "failed").map((result) => operationalCodeMessage(result.error_code, t, format, "referenceCreateFailed"))
    };
  }

  async function startManualExtraction(documentId: string) {
    const liveDocument = allDocuments.find((item) => item.id === documentId && item.isLive && item.latestVersionId);
    if (!canStartExtraction || !liveDocument?.latestVersionId || liveDocument.sourceState !== "ready_for_extraction" || liveDocument.documentStatus === "deleted"
      || isReviewLockedVersionStatus(liveDocument.versionStatus)) return;
    const token = manualStarts.current.begin(documentId, liveDocument.latestVersionId);
    if (token === null) return;
    const scope = processingPollScope.current;
    const active = () => scope === processingPollScope.current && manualStarts.current.owns(documentId, token);
    setManualStartPending((current) => ({ ...current, [documentId]: true }));
    setManualStartNotices((current) => {
      const next = { ...current }; delete next[documentId]; return next;
    });
    let unknown = false;
    let confirmed = false;
    try {
      const response = await startDocumentExtraction(apiFetch, params.id, liveDocument.id, liveDocument.latestVersionId, {});
      if (!active()) return;
      if (response.document.id !== documentId || response.document.latest_version?.id !== liveDocument.latestVersionId
        || !response.pipeline.id) throw new Error("extraction_receipt_unconfirmed");
      // Commit the confirmed receipt before any GET. A read failure cannot undo it.
      const next = liveDocumentFromSummary({ ...response.document, latest_pipeline: response.pipeline }, t);
      acceptExtractionReceipt(liveDocument, next);
      confirmed = true;
      // Non-file sources retain their existing one-shot detail hydration.
      // Only the file list gains continuous observation in this repair.
      if (next.sourceType !== "File upload") await hydrateStartedSource(next, active);
    } catch (error) {
      if (!active()) return;
      unknown = uploadOutcomeUnknown(error);
      setManualStartNotices((current) => ({ ...current, [documentId]: {
        versionId: liveDocument.latestVersionId,
        unknown,
        message: unknown ? t("projectImportExtractionOutcomeUnknown")
          : operationalErrorMessage(error, t, format, "projectImportStatusUpdateFailed"),
      } }));
    } finally {
      if (active()) {
        setManualStartPending((current) => ({ ...current, [documentId]: false }));
        // Hold confirmed starts too: React may not yet have rendered the receipt.
        manualStarts.current.finish(documentId, token, unknown || confirmed);
      }
    }
  }

  async function hydrateStartedSource(document: CreatedKnowledgeDocument, active: () => boolean) {
    try {
      const detail = await getPipelineDetail(apiFetch, params.id, document.id, document.latestVersionId!, document.pipeline.id!);
      if (active()) updatePipelineSnapshots([applyPipelineDetailToDocument(document, detail)]);
    } catch {
      if (active()) updatePipelineSnapshots([{ ...document, pipeline: { ...document.pipeline, observationInterrupted: true } }]);
    }
  }

  async function uploadLiveDocuments(files: File[], options: { ocrModelId: string | null; startExtraction: boolean }, onProgressDocuments?: (documents: CreatedKnowledgeDocument[]) => void): Promise<UploadBatchResult<CreatedKnowledgeDocument>> {
    if (!canUpload) throw new UiValidationError("projectImportUploadNotAllowed");
    const attempt = uploadAttempts.current.begin();
    const scope = processingPollScope.current;
    const active = () => scope === processingPollScope.current && uploadAttempts.current.accepts(attempt);
    const observing = () => active() && uploadAttempts.current.canPresent(attempt);
    setUploadNotice(null);
    try {
    const upload = await uploadProjectDocuments(apiFetch, params.id, files, { ocrModelId: options.ocrModelId, startExtraction: options.startExtraction });
    if (!active()) return { documents: [], receipts: [] };
    const receipts = upload.results.map((result) => ({ index: result.index, status: result.status, documentId: result.document?.id, versionId: result.document?.latest_version?.id, errorCode: result.error_code }));
    confirmedUploadResults(files.map((file) => ({ name: file.name, ok: true, reason: "" })), receipts);
    const results = upload.results.filter((result): result is DocumentUploadResult & { document: DocumentSummary } => result.status === "success" && result.document !== null);
    const summaries = results.map((result) => liveDocumentFromSummary(result.document, t));
    if (observing()) onProgressDocuments?.(summaries);
    updateUploadedDocumentSnapshots(summaries);
    if (!observing()) return { documents: summaries, receipts };
    const hydrated: CreatedKnowledgeDocument[] = [];
    for (const [index, result] of results.entries()) {
      const versionId = result.document.latest_version?.id;
      const pipelineId = result.document.latest_pipeline?.id;
      if (!versionId || !pipelineId) {
        hydrated.push(summaries[index]);
        onProgressDocuments?.([...hydrated, ...summaries.slice(index + 1)]);
        updateUploadedDocumentSnapshots(hydrated);
        continue;
      }
      try {
        if (!observing()) return { documents: summaries, receipts };
        const lease = observationOwnership.acquire(extractionRunKey(params.id, summaries[index])!, "modal");
        let detail: PipelineRunDetail;
        try {
          detail = await getPipelineDetail(apiFetch, params.id, result.document.id, versionId, pipelineId, lease.signal);
        } finally { lease.release(); }
        if (!observing()) return { documents: summaries, receipts };
        const hydratedDocument = liveDocumentFromSummary(result.document, t, detail);
        hydrated.push(options.startExtraction && results.length === 1 ? await pollPipelineUntilCompletionGate(hydratedDocument, onProgressDocuments, detail, observing) : hydratedDocument);
      } catch {
        hydrated.push({ ...summaries[index], pipeline: { ...summaries[index].pipeline, observationInterrupted: true } });
      }
      if (!observing()) return { documents: hydrated, receipts };
      onProgressDocuments?.([...hydrated, ...summaries.slice(index + 1)]);
      updateUploadedDocumentSnapshots(hydrated);
    }
    return { documents: hydrated, receipts };
    } catch (error) {
      if (active()) setUploadNotice(uploadOutcomeUnknown(error) ? "uploadOutcomeUnknown" : "uploadRejected");
      throw error;
    } finally {
      uploadAttempts.current.finish(attempt);
    }
  }

  async function retryUploadModalPipeline(document: CreatedKnowledgeDocument, onProgressDocument?: (document: CreatedKnowledgeDocument) => void) {
    if (!canStartExtraction) throw new UiValidationError("projectImportUploadNotAllowed");
    const failedStep = document.pipeline.steps?.find((step) => step.status === "failed");
    if (!document.latestVersionId || !document.pipeline.id || !failedStep) throw new UiValidationError("knowledgeDetailRetryFailed");
    const scope = processingPollScope.current;
    const attempt = uploadAttempts.current.begin();
    const observing = () => scope === processingPollScope.current && uploadAttempts.current.canPresent(attempt);
    try {
      const detail = await retryPipelineStep(apiFetch, params.id, document.id, document.latestVersionId, document.pipeline.id, failedStep.name);
      if (!observing()) return document;
      const restarted = applyPipelineDetailToDocument(document, detail);
      updateUploadedDocumentSnapshots([restarted]);
      return await pollPipelineUntilCompletionGate(restarted, (documents) => onProgressDocument?.(documents[0]), detail, observing);
    } finally {
      uploadAttempts.current.finish(attempt);
    }
  }

  async function retryLivePipelineStep(document: CreatedKnowledgeDocument, stepName?: string | null) {
    if (!projectReady) return;
    if (!document.isLive || !document.latestVersionId || !document.pipeline.id || !stepName) return;
    const failedStep = document.pipeline.steps?.find((step) => step.name === stepName && step.status === "failed");
    if (!failedStep || ocrRetryBlocked(failedStep.ocr) || pipelineDetailLoading[document.id]) return;
    const pipelineId = document.pipeline.id;
    setPipelineRetryNotices((current) => ({ ...current, [document.id]: { pipelineId, message: "" } }));
    setPipelineDetailLoading((current) => ({ ...current, [document.id]: true }));
    try {
      const detail = await retryPipelineStep(apiFetch, params.id, document.id, document.latestVersionId, document.pipeline.id, stepName);
      const patch = {
        status: mapPipelineStatus(detail.status),
        progress: detail.progress_percent,
        currentStep: detail.current_step_name ? pipelineStepLabel(detail.current_step_name, t) : document.pipeline.currentStep,
        error: detail.error_message ? t(ocrFailureKey(detail.steps.find(step => step.status === "failed"), detail.error_message)) : "",
        steps: pipelineSteps(detail, t)
      };
      setLiveDocuments((current) => current.map((item) => item.id === document.id ? { ...item, pipeline: { ...item.pipeline, ...patch } } : item));
      setCreatedImports((current) => current.map((item) => item.id === document.id ? { ...item, pipeline: { ...item.pipeline, ...patch } } : item));
    } catch (error) {
      setPipelineRetryNotices((current) => ({ ...current, [document.id]: {
        pipelineId, message: operationalErrorMessage(error, t, format, "knowledgeDetailRetryFailed")
      } }));
    } finally {
      setPipelineDetailLoading((current) => ({ ...current, [document.id]: false }));
    }
  }

  async function syncNow(document: DocumentItem) {
    if (!projectReady) return;
    if ("dataSourceId" in document && document.dataSourceId) {
      setCreatedImports((current) => current.map((item) => item.id === document.id ? {
        ...item,
        sourceState: "syncing",
        pipeline: { ...item.pipeline, currentStep: t("projectImportManualSyncSource"), elapsed: "00m 01s", eta: t("projectImportWaitingWorker"), error: "" }
      } : item));
      try {
        const run = await queueDataSourceSync(apiFetch, params.id, document.dataSourceId);
        setSyncRunsByDataSource((current) => ({ ...current, [document.dataSourceId!]: [run, ...(current[document.dataSourceId!] ?? []).filter((item) => item.id !== run.id)] }));
        applySyncRunState(document.id, run);
        void pollDataSourceSyncRun(document.id, document.dataSourceId, run.id);
      } catch (error) {
        setCreatedImports((current) => current.map((item) => item.id === document.id ? {
          ...item,
          sourceState: "sync_failed",
          pipeline: { ...item.pipeline, currentStep: t("projectImportSyncScheduleFailed"), elapsed: "", eta: "", error: operationalErrorMessage(error, t, format, "projectImportSyncScheduleFailed") }
        } : item));
      }
      return;
    }
    setCreatedImports((current) => current.map((item) => item.id === document.id ? {
      ...item,
      sourceState: "syncing",
      pipeline: { ...item.pipeline, currentStep: t("projectImportManualSyncSource"), elapsed: "00m 01s", eta: t("projectImportWaitingRemoteService") }
    } : item));
  }

  const projectVersionActions = createProjectVersionActions(projectVersionState, { apiFetch, format, params, t, projectReady, canEditLifecycle, replaceLiveDocuments, setCreatedImports, setLiveDocuments });

  const statusChangeActions = createStatusChangeActions(statusChangeState, { apiFetch, format, params, t, canEditLifecycle, notify, setCreatedImports, setLiveDocuments });
  const { requestStatusChange } = statusChangeActions;


  const { renderStatusChangeModal } = createStatusChangeView(statusChangeState, statusChangeActions, { localize, t });
  const { renderProjectVersionModals } = createProjectVersionView(projectVersionState, projectVersionActions, { canEditLifecycle, format, locale, localize, syncRunLoading, refreshDataSourceSyncRuns, syncNow, t });
  const { renderProjectPermissionModal } = createProjectPermissionView(projectPermissionState, projectPermissionActions, { canManageProjectPermissions, currentUser, format, locale, project, t });
  return (
    <AppShell title={project?.name ?? t("projectImportFallbackProjectTitle")} browserTitle={resourcePageTitle(t("workspaceImportTitle"), projectReady && titleRead?.fetch === apiFetch && titleRead.route === params.id ? project?.name : null)}>
      <div className="project-import-page">
      <div className="project-context">
        <Link className="text-link" href="/projects"><ArrowLeft size={16} /> {t("projectImportBackToProjects")}</Link>
        <div className="project-context-actions">
          <button className="action-button secondary" onClick={() => setActiveModal("graph")} type="button"><Network size={16} /> {t("knowledgeGraph")}</button>
          <button className="action-button secondary" onClick={() => { setFixedChatVersion(undefined); setActiveModal("chat"); }} type="button"><MessageSquareText size={16} /> {t("chatTest")}</button>
          {canManageProjectPermissions ? <button className="action-button secondary" onClick={openPermissionModal} type="button"><ShieldCheck size={16} /> {t("projectImportPermissionManagement")}</button> : null}
        </div>
      </div>

      {uploadNotice ? <p className="field-note" role="status">{t(uploadNotice)}</p> : null}

      <PageGrid>
        <StatCard label={t("totalDocuments")} value={documentLoadState === "loading" ? "…" : formatCount(allDocuments.length, locale)} helper={`active ${formatCount(allDocuments.filter((item) => item.documentStatus === "active").length, locale)} / inactive ${formatCount(allDocuments.filter((item) => item.documentStatus === "inactive").length, locale)}`} />
        <StatCard label={t("projectImportPipelineRunning")} value={documentLoadState === "loading" ? "…" : formatCount(allDocuments.filter((item) => getSourceState(item) === "pipeline" && pipelineIsExecuting(item.pipeline.status)).length, locale)} helper={t("projectImportPipelineRunningHelp")} tone="sage" />
        <StatCard label={t("projectImportFailedItems")} value={documentLoadState === "loading" ? "…" : formatCount(allDocuments.filter((item) => item.pipeline.status === "failed" || getSourceState(item) === "sync_failed").length, locale)} helper={t("projectImportFailedItemsHelp")} tone="gold" />
        <StatCard label={t("projectImportReadyForExtraction")} value={documentLoadState === "loading" ? "…" : formatCount(allDocuments.filter((item) => getSourceState(item) === "ready_for_extraction").length, locale)} helper={t("projectImportReadyForExtractionHelp")} />
      </PageGrid>

      {canUpload ? <div className="content-grid">
        <Panel title={t("projectImportAddKnowledgeSource")}>
          <div
            aria-label={t("projectImportDropAria")}
            className={`drop-zone project-source-drop-zone ${projectDropActive ? "drag-active" : ""}`}
            onClick={() => openUploadModal()}
            onDragEnter={(event) => {
              event.preventDefault();
              projectDragDepth.current += 1;
              setProjectDropActive(true);
            }}
            onDragLeave={(event) => {
              event.preventDefault();
              projectDragDepth.current = Math.max(0, projectDragDepth.current - 1);
              if (projectDragDepth.current === 0) setProjectDropActive(false);
            }}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
            }}
            onDrop={(event) => {
              event.preventDefault();
              projectDragDepth.current = 0;
              setProjectDropActive(false);
              const files = Array.from(event.dataTransfer.files);
              if (files.length) openUploadModal(files);
            }}
            onKeyDown={(event) => {
              if (event.target !== event.currentTarget) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openUploadModal();
              }
            }}
            role="button"
            tabIndex={0}
          >
            <UploadCloud size={36} />
            <strong>{t("projectImportDropTitle")}</strong>
            <small>{t("projectImportDropHelp")}</small>
            <div className="drop-actions">
              <button className="action-button" onClick={(event) => { event.stopPropagation(); openUploadModal(); }} type="button"><FilePlus2 size={17} /> {t("projectImportChooseFiles")}</button>
              <button className="action-button secondary" onClick={(event) => { event.stopPropagation(); setDataServiceModalOpen(true); }} type="button"><Database size={17} /> {t("projectImportDataService")}</button>
              <button className="action-button secondary" title={t("projectImportReferenceOtherProject")} onClick={(event) => { event.stopPropagation(); void loadReferenceSources(); }} type="button"><Layers3 size={17} /> {t("projectImportReferenceOtherProject")}</button>
            </div>
          </div>
        </Panel>
      </div> : null}

      <Panel
        title={t("projectImportDocumentList")}
        action={
          <div className="document-toolbar">
            <label className="document-search">
              <span>{t("projectImportSearchLabel")}</span>
              <input
                onChange={(event) => setDocumentQuery(event.target.value)}
                placeholder={t("projectImportSearchPlaceholder")}
                value={documentQuery}
              />
            </label>
            <label className="document-sort">
              <span>{t("sort")}</span>
              <DropdownSelect onChange={(event) => setSortBy(event.target.value)} value={sortBy}>
                <option value="updatedAt">{t("projectImportSortUpdatedAt")}</option>
                <option value="status">{t("status")}</option>
                <option value="progress">{t("projectImportSortProgress")}</option>
                <option value="name">{t("projectImportSortName")}</option>
              </DropdownSelect>
            </label>
          </div>
        }
      >
        {documentLoadState === "loading" ? <div className="empty-state compact" role="status"><Clock3 size={24} /><p>{t("projectImportLoadingDocuments")}</p></div> : null}
        {documentLoadState === "error" ? <div className="empty-state compact" role="alert"><AlertTriangle size={24} /><p>{localize(documentLoadError)}</p></div> : null}
        {documentLoadState === "ready" && visibleDocuments.length === 0 ? <div className="empty-state compact"><FilePlus2 size={24} /><p>{t("projectImportNoFormalDocuments")}</p></div> : null}
        <div className="document-pipeline-list">
          {visibleDocuments.map((document) => (
            <DocumentPipelineCard
              key={document.id}
              document={document}
              t={t}
              format={format}
              locale={locale}
              localize={localize}
              projectId={params.id}
              projectAccess={projectAccess}
              canStartExtraction={canStartExtraction}
              canEditLifecycle={canEditLifecycle}
              terminalCounts={terminalCounts}
              elapsedNow={elapsedNow}
              elapsedEnabled={elapsedEnabled}
              committedStatuses={committedStatuses}
              pendingStatusChange={pendingStatusChange}
              statusSubmitting={statusSubmitting}
              manualStartPending={manualStartPending}
              manualStartNotices={manualStartNotices}
              pipelineDetailLoading={pipelineDetailLoading}
              pipelineRetryNotices={pipelineRetryNotices}
              startManualExtraction={startManualExtraction}
              retryLivePipelineStep={retryLivePipelineStep}
              requestStatusChange={requestStatusChange}
              setVersionDocumentId={setVersionDocumentId}
            />
          ))}
        </div>
        {visibleDocuments.length === 0 ? (
          <div className="empty-state">{t("projectImportNoMatchingDocuments")}</div>
        ) : null}
      </Panel>

      </div>
      {activeModal ? (
        <div className="modal-backdrop" role="presentation">
          <section ref={featureDialogRef} tabIndex={-1} aria-labelledby="project-feature-title" aria-modal="true" className={`modal-panel project-feature-modal ${activeModal === "chat" ? "project-chat-modal" : "project-graph-modal"}`} role="dialog">
            <div className="modal-header">
              <div>
                <p className="eyebrow">{t("projectImportFeatureEyebrow")}</p>
                <h2 id="project-feature-title">{activeModal === "graph" ? t("knowledgeGraph") : t("chatTest")}</h2>
              </div>
              <button className="icon-button" onClick={() => setActiveModal(null)} type="button" aria-label={t("projectImportCloseFeatureModal")}>
                <X size={18} />
              </button>
            </div>

            {activeModal === "graph" ? (
              <div className="feature-summary">
                <div className="feature-copy">
                  <strong>{t("projectImportGraphHelpTitle")}</strong>
                  <small>{t("projectImportGraphHelpDescription")}</small>
                </div>
                <ProjectGraphPreview />
              </div>
            ) : (
              <ProjectChatTest fixedVersionId={fixedChatVersion} key={`${params.id}:${fixedChatVersion ?? "all"}`} />
            )}
          </section>
        </div>
      ) : null}

      {uploadModalOpen ? <UploadFilesModal canSubmit={canUpload} onObservationEnd={releaseModalObservation} initialFiles={initialUploadFiles} maxUploadBytes={maxUploadSizeMb * 1024 * 1024} ocrModels={ocrModels} onClose={closeUploadModal} onCreate={addUploadedDocuments} onRetryPipeline={retryUploadModalPipeline} onUploadFiles={uploadLiveDocuments} /> : null}
      {canUpload && dataServiceModalOpen ? <DataServiceModal key={`${params.id}:${currentUser?.user_id}:${JSON.stringify(currentUser?.permissions ?? [])}`} onLoadConnectionOptions={loadLiveDataSourceOptions} onClose={() => setDataServiceModalOpen(false)} onCreate={addDataServiceDocument} onCreateDataSource={createLiveDataSource} onTestConnection={testLiveDataSource} /> : null}
      {referenceModalOpen ? (
        <ProjectReferenceModal
          error={referenceSourcesError}
          loading={referenceSourcesLoading}
          onClose={() => setReferenceModalOpen(false)}
          onCreate={createLiveReferences}
          onRefresh={() => { void loadReferenceSources(); }}
          sources={referenceSources}
        />
      ) : null}

      {permissionModalOpen && canManageProjectPermissions ? renderProjectPermissionModal() : null}

      {renderProjectVersionModals()}

      {renderStatusChangeModal()}
    </AppShell>
  );
}
