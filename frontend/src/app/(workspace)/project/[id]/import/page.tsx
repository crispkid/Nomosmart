"use client";

import { DropdownSelect } from "@/components/DropdownSelect";
import { resourcePageTitle } from "@/lib/browserTitle";
import { useModalFocus } from "@/components/useModalFocus";
import { UiValidationError } from "@/lib/transportError";
import { useFeedback } from "@/components/FeedbackProvider";
import { ocrFailureKey, ocrRetryBlocked } from "@/lib/ocrPresentation";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, Clock3, FilePlus2, MessageSquareText, Network, ShieldCheck } from "lucide-react";
import { AppShell, PageGrid, Panel, StatCard } from "@/components/AppShell";
import { DataServiceModal, UploadFilesModal, type CreatedKnowledgeDocument, type DataServicePayload } from "@/components/KnowledgeSourceModals";
import { formatCount } from "@/lib/numberFormat";
import { usePipelineElapsedClock } from "@/lib/usePipelineElapsedClock";
import { fileProcessingPollDelay } from "@/lib/fileProcessingPolling";
import { useAuth } from "@/components/AuthProvider";
import { createDataSource, getDataSourceConnectionOptions, getPipelineDetail, getProject, getUploadConfig, listModels, listProjectDocuments, listProjectMembers, retryPipelineStep, startDocumentExtraction, testDataSourceConnection, uploadProjectDocuments, type AIModelResponse, type ApiError, type DocumentSummary, type DocumentUploadResult, type PipelineRunDetail, type ProjectResponse, type ProjectMemberResponse } from "@/lib/api";
import { t as translate } from "@/lib/i18n";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { pipelineStepLabel } from "@/lib/pipelineSteps";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { pipelineIsExecuting } from "@/lib/reviewPresentation";
import { confirmedUploadResults, UploadAttemptGuard, uploadOutcomeUnknown, type UploadBatchResult } from "@/lib/uploadProgress";
import { useReadResource } from "@/lib/useReadResource";
import { useDocumentList } from "@/lib/useDocumentList";
import { useDocumentPipelinePolling } from "@/lib/useDocumentPipelinePolling";
import { useTerminalChunkCounts } from "@/lib/useTerminalChunkCounts";
import { extractionRunKey, FILE_EXTRACTION_OBSERVATION_LIMIT, ManualExtractionStarts, observationDelay, PipelineObservationOwnership } from "@/lib/manualExtraction";
import { applyPipelineDetail, type Translate, isReviewLockedVersionStatus, mapPipelineStatus, pipelineSteps, UPLOAD_EXTRACTION_GATE_INITIAL_DELAY_MS, UPLOAD_EXTRACTION_GATE_POLL_INTERVAL_MS, pipelineReachedExtractionGate, pipelineFailedBeforeExtractionGate, liveDocumentFromSummary, serviceDocumentFromResponse, filterAndSortDocuments, getSourceState } from "@/components/projectImport/importDocumentModel";
import { DocumentPipelineCard } from "@/components/projectImport/DocumentPipelineCard";
import { createDataSourceSyncActions, useDataSourceSyncState } from "@/components/projectImport/useDataSourceSyncSection";
import { createReferenceSourceActions, createReferenceSourceView, useReferenceSourceState } from "@/components/projectImport/useReferenceSourceSection";
import { KnowledgeSourceDropZone } from "@/components/projectImport/KnowledgeSourceDropZone";
import { ProjectFeatureDialog } from "@/components/projectImport/ProjectFeatureDialog";
import { createStatusChangeActions, createStatusChangeView, useStatusChangeState } from "@/components/projectImport/useStatusChangeSection";
import { createProjectVersionActions, createProjectVersionView, useProjectVersionState } from "@/components/projectImport/useProjectVersionSection";
import { createProjectPermissionActions, createProjectPermissionView, useProjectPermissionState } from "@/components/projectImport/useProjectPermissionSection";

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
  const [projectAccessState, setProjectAccess] = useState<"loading" | "granted" | "denied" | "error">("loading");
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
  const referenceSourceState = useReferenceSourceState();
  const setProjectMembersRef = useRef<(members: ProjectMemberResponse[]) => void>(() => undefined);
  // OPT424-035: the project (with its members) and the document list are read resources. Their results
  // feed the page state that permission, upload and pipeline actions also update.
  const readProject = useCallback(async (signal: AbortSignal) => Promise.all([
    getProject(apiFetch, params.id, signal),
    listProjectMembers(apiFetch, params.id, signal).catch(() => [] as ProjectMemberResponse[]),
  ]), [apiFetch, params.id]);
  const projectRead = useReadResource(readProject, `${params.id}:${currentUser?.user_id ?? ""}`, true, {
    onData: ([projectRow, members]) => {
      setProject(projectRow);
      setTitleRead({ fetch: apiFetch, route: params.id });
      setProjectAccess("granted");
      setProjectMembersRef.current(members);
    },
    onError: (error) => {
      setProject(null);
      setProjectAccess((error as ApiError).status === 401 || (error as ApiError).status === 403 ? "denied" : "error");
    },
  });
  const projectAccess = projectRead.status === "loading" ? "loading" : projectAccessState;
  const readDocuments = useCallback(async (signal: AbortSignal) => {
    const [documents, models, uploadConfig] = await Promise.all([
      listProjectDocuments(apiFetch, params.id, signal),
      listModels(apiFetch, "OCR", signal),
      getUploadConfig(apiFetch, signal).catch(() => null)
    ]);
    const hydrated = await Promise.all(documents.map(async (document) => {
      const versionId = document.latest_version?.id;
      const pipelineId = document.latest_pipeline?.id;
      if (!versionId || !pipelineId) return liveDocumentFromSummary(document, t);
      try {
        const detail = await getPipelineDetail(apiFetch, params.id, document.id, versionId, pipelineId, signal);
        return liveDocumentFromSummary(document, t, detail);
      } catch {
        return liveDocumentFromSummary(document, t);
      }
    }));
    return { hydrated, models, uploadConfig };
  }, [apiFetch, params.id, t]);
  const documentsRead = useReadResource(readDocuments, params.id, true, {
    onData: ({ hydrated, models, uploadConfig }) => {
      replaceLiveDocuments(hydrated);
      setOcrModels(models.filter((model) => model.is_active));
      if (uploadConfig?.max_upload_size_mb) setMaxUploadSizeMb(uploadConfig.max_upload_size_mb);
    },
    onError: () => {
      setLiveDocuments([]);
      setOcrModels([]);
    },
  });
  const documentLoadState = documentsRead.status;
  const documentLoadError = documentsRead.status === "error" ? t("projectImportLoadDocumentsFailed") : "";
  const { notify } = useFeedback();
  const statusChangeState = useStatusChangeState();
  const { committedStatuses, pendingStatusChange, statusSubmitting } = statusChangeState;
  const [pipelineDetailLoading, setPipelineDetailLoading] = useState<Record<string, boolean>>({});
  const [pipelineRetryNotices, setPipelineRetryNotices] = useState<Record<string, { pipelineId: string; message: string }>>({});
  const dataSourceSyncState = useDataSourceSyncState();
  const { syncRunsByDataSource, setSyncRunsByDataSource, syncRunLoading, setSyncRunLoading } = dataSourceSyncState;
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
  useLayoutEffect(() => { setProjectMembersRef.current = setProjectMembers; }, [setProjectMembers]);
  const projectPermissionActions = createProjectPermissionActions(projectPermissionState, { apiFetch, canManageProjectPermissions, currentUser, params, project, setProject, setProjectAccess });
  const { openPermissionModal } = projectPermissionActions;

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

  const visibleDocuments = useMemo(() => filterAndSortDocuments(allDocuments, documentQuery, sortBy), [allDocuments, documentQuery, sortBy]);
  const elapsedEnabled = Boolean(currentUser && projectReady && documentLoadState === "ready");
  const elapsedNow = usePipelineElapsedClock(visibleDocuments
    .filter(document => document.sourceState === "pipeline" && document.documentStatus !== "deleted")
    .map(document => document.pipeline), elapsedEnabled, params.id);
  const projectVersionState = useProjectVersionState({ apiFetch, format, params, t, allDocuments, syncRunsByDataSource, setSyncRunsByDataSource, setSyncRunLoading });
  const { setVersionDocumentId } = projectVersionState;

  const dataSourceSyncActions = createDataSourceSyncActions(dataSourceSyncState, { apiFetch, format, locale, params, t, projectReady, setCreatedImports, setLiveDocuments });
  const { refreshDataSourceSyncRuns, syncNow } = dataSourceSyncActions;

  function applyPipelineDetailToDocument(document: CreatedKnowledgeDocument, detail: PipelineRunDetail): CreatedKnowledgeDocument {
    return applyPipelineDetail(document, detail, params.id, t);
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

  const referenceSourceActions = createReferenceSourceActions(referenceSourceState, { apiFetch, format, params, t, projectReady, setCreatedImports });
  const { loadReferenceSources } = referenceSourceActions;

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

  const projectVersionActions = createProjectVersionActions(projectVersionState, { apiFetch, format, params, t, projectReady, canEditLifecycle, replaceLiveDocuments, setCreatedImports, setLiveDocuments });

  const statusChangeActions = createStatusChangeActions(statusChangeState, { apiFetch, format, params, t, canEditLifecycle, notify, setCreatedImports, setLiveDocuments });
  const { requestStatusChange } = statusChangeActions;


  const { renderReferenceModal } = createReferenceSourceView(referenceSourceState, referenceSourceActions);
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
        <StatCard label={t("totalDocuments")} value={documentLoadState === "loading" ? "…" : formatCount(allDocuments.length, locale)} helper={format("projectImportTotalDocumentsHelp", { active: formatCount(allDocuments.filter((item) => item.documentStatus === "active").length, locale), inactive: formatCount(allDocuments.filter((item) => item.documentStatus === "inactive").length, locale) })} />
        <StatCard label={t("projectImportPipelineRunning")} value={documentLoadState === "loading" ? "…" : formatCount(allDocuments.filter((item) => getSourceState(item) === "pipeline" && pipelineIsExecuting(item.pipeline.status)).length, locale)} helper={t("projectImportPipelineRunningHelp")} tone="sage" />
        <StatCard label={t("projectImportFailedItems")} value={documentLoadState === "loading" ? "…" : formatCount(allDocuments.filter((item) => item.pipeline.status === "failed" || getSourceState(item) === "sync_failed").length, locale)} helper={t("projectImportFailedItemsHelp")} tone="gold" />
        <StatCard label={t("projectImportReadyForExtraction")} value={documentLoadState === "loading" ? "…" : formatCount(allDocuments.filter((item) => getSourceState(item) === "ready_for_extraction").length, locale)} helper={t("projectImportReadyForExtractionHelp")} />
      </PageGrid>

      {canUpload ? <div className="content-grid">
        <KnowledgeSourceDropZone
          active={projectDropActive}
          dragDepthRef={projectDragDepth}
          onActiveChange={setProjectDropActive}
          onOpenDataService={() => setDataServiceModalOpen(true)}
          onOpenReference={() => { void loadReferenceSources(); }}
          onOpenUpload={openUploadModal}
          t={t}
        />
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
      {activeModal ? <ProjectFeatureDialog activeModal={activeModal} dialogRef={featureDialogRef} fixedChatVersion={fixedChatVersion} onClose={() => setActiveModal(null)} projectId={params.id} t={t} /> : null}

      {uploadModalOpen ? <UploadFilesModal canSubmit={canUpload} onObservationEnd={releaseModalObservation} initialFiles={initialUploadFiles} maxUploadBytes={maxUploadSizeMb * 1024 * 1024} ocrModels={ocrModels} onClose={closeUploadModal} onCreate={addUploadedDocuments} onRetryPipeline={retryUploadModalPipeline} onUploadFiles={uploadLiveDocuments} /> : null}
      {canUpload && dataServiceModalOpen ? <DataServiceModal key={`${params.id}:${currentUser?.user_id}:${JSON.stringify(currentUser?.permissions ?? [])}`} onLoadConnectionOptions={loadLiveDataSourceOptions} onClose={() => setDataServiceModalOpen(false)} onCreate={addDataServiceDocument} onCreateDataSource={createLiveDataSource} onTestConnection={testLiveDataSource} /> : null}
      {renderReferenceModal()}

      {permissionModalOpen && canManageProjectPermissions ? renderProjectPermissionModal() : null}

      {renderProjectVersionModals()}

      {renderStatusChangeModal()}
    </AppShell>
  );
}
