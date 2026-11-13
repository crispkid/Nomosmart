// Project import page document model: pure mapping, labels and status helpers
// (split from the project import page, OPT424-038).
import { ocrFailureKey } from "@/lib/ocrPresentation";
import { type CreatedKnowledgeDocument, type SourceState } from "@/components/KnowledgeSourceModals";
import { pipelineTimeFields } from "@/lib/pipelineElapsed";
import { type ApiError, type DataSourceCreateResponse, type DataSyncRunResponse, type DocumentSummary, type PipelineRunDetail } from "@/lib/api";
import { formatShortDateTime } from "@/lib/dateFormat";
import { type TranslationKey } from "@/lib/i18nClient";
import { pipelineStepLabel } from "@/lib/pipelineSteps";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { extractionOutcome, versionPipelineState, type ExtractionOutcome } from "@/lib/reviewPresentation";

export type Translate = (key: TranslationKey) => string;

export function normalizeVersion(version: string) {
  const match = version.match(/^v?(\d+)(?:\.(\d+))?$/i);
  return match ? `v${Number(match[1])}.${Number(match[2] ?? 0)}` : version;
}

export function isWorkingVersion(status: string) {
  return status === "processing" || status === "submission_ready" || status === "pending_manager_review" || status === "pending_owner_review" || status === "approved";
}

export function isReviewLockedVersionStatus(status: string) {
  return status === "pending_manager_review" || status === "pending_owner_review" || status === "approved";
}

export type DocumentItem = CreatedKnowledgeDocument;
type PipelineStepItem = NonNullable<CreatedKnowledgeDocument["pipeline"]["steps"]>[number];
export const projectMemberRoles = [
  { id: "owner", labelKey: "projectRoleOwner" },
  { id: "editor", labelKey: "projectRoleEditor" },
  { id: "viewer", labelKey: "projectRoleViewer" }
] as const;
export type ProjectMemberRole = (typeof projectMemberRoles)[number]["id"];
export type PendingStatusChange = {
  documentId: string;
  documentTitle: string;
  from: string;
  to: string;
  projects: string[];
  isLive: boolean;
  lockVersion?: number;
  requiresConfirmation: boolean;
};

export type VersionSwitchTarget = {
  document: CreatedKnowledgeDocument;
  version: CreatedKnowledgeDocument["versions"][number];
};

export function mapPipelineStatus(status?: string): CreatedKnowledgeDocument["pipeline"]["status"] {
  if (status === "queued") return "queued";
  if (status === "completed") return "completed";
  if (status === "submission_ready") return "submission_ready";
  if (status === "pending_manager_review") return "pending_manager_review";
  if (status === "pending_owner_review") return "pending_owner_review";
  if (status === "approved") return "approved";
  if (status === "publish_ready" || status === "ready_to_publish") return "publish_ready";
  if (status === "publishing") return "publishing";
  if (status === "production_indexing" || status === "indexing" || status === "published_indexing") return "production_indexing";
  if (status === "graph_syncing" || status === "graph_sync" || status === "graph_synchronizing") return "graph_syncing";
  if (status === "published_active" || status === "published" || status === "active") return "published_active";
  if (status === "failed") return "failed";
  if (status === "waiting_action") return "waiting_action";
  if (status === "skipped") return "skipped";
  return "running";
}

function pipelineStatusFromVersion(status?: string, pipelineStatus?: string): CreatedKnowledgeDocument["pipeline"]["status"] {
  const versionState = versionPipelineState(status);
  if (versionState) return versionState;
  const mappedPipeline = mapPipelineStatus(pipelineStatus);
  if (pipelineStatus && mappedPipeline !== "running") return mappedPipeline;
  if (status === "pending_manager_review") return "pending_manager_review";
  if (status === "pending_owner_review") return "pending_owner_review";
  if (status === "approved") return "publish_ready";
  if (status === "publishing") return "publishing";
  if (status === "production_indexing") return "production_indexing";
  if (status === "graph_syncing") return "graph_syncing";
  if (status === "active") return "published_active";
  return mappedPipeline;
}

export function publishStageCurrentStep(status: CreatedKnowledgeDocument["pipeline"]["status"], t: Translate) {
  const labels: Record<CreatedKnowledgeDocument["pipeline"]["status"], string> = {
    queued: t("projectImportStageQueued"),
    running: t("projectImportStageRunning"),
    submission_ready: t("projectImportStageSubmissionReady"),
    pending_manager_review: t("projectImportStagePendingManager"),
    pending_owner_review: t("projectImportStagePendingOwner"),
    approved: t("projectImportStageApproved"),
    publish_ready: t("projectImportStagePublishReady"),
    publishing: t("projectImportStagePublishing"),
    production_indexing: t("projectImportStageProductionIndexing"),
    graph_syncing: t("projectImportStageGraphSyncing"),
    published_active: t("projectImportStagePublishedActive"),
    waiting_action: t("projectImportStageWaitingAction"),
    completed: t("projectImportStageCompleted"),
    failed: t("projectImportStageFailed"),
    review_rejected: t("projectImportReviewRejectedHelp"),
    skipped: t("projectImportStageSkipped")
  };
  return labels[status];
}

function publishStageWaitingRole(status: CreatedKnowledgeDocument["pipeline"]["status"], t: Translate) {
  if (status === "pending_manager_review") return t("projectImportWaitingManager");
  if (status === "pending_owner_review") return t("projectImportWaitingOwner");
  if (status === "approved" || status === "publish_ready") return t("projectImportWaitingPublisher");
  if (status === "production_indexing") return t("projectImportWaitingProductionIndex");
  if (status === "graph_syncing") return t("projectImportWaitingGraphSync");
  return "";
}

export function pipelineEtaForStatus(status: CreatedKnowledgeDocument["pipeline"]["status"], t: Translate) {
  if (status === "submission_ready") return t("projectImportWaitingSubmission");
  if (status === "pending_manager_review" || status === "pending_owner_review") return t("projectImportWaitingApprovalAction");
  if (status === "approved" || status === "publish_ready") return t("projectImportWaitingPublishAction");
  if (status === "publishing" || status === "production_indexing" || status === "graph_syncing") return t("projectImportPublishingInProgress");
  if (status === "published_active") return t("projectImportPublishedAvailable");
  return t("projectImportBackgroundProcessing");
}

export function publishStageAction(status: CreatedKnowledgeDocument["pipeline"]["status"], projectId: string, documentId: string, t: Translate) {
  if (status === "pending_manager_review" || status === "pending_owner_review" || status === "approved" || status === "publish_ready") {
    return { href: "/approve", label: t("projectImportOpenApprovalWorkspace") };
  }
  if (status === "published_active") {
    return { href: `/project/${projectId}/knowledge/${documentId}/chat-test`, label: t("projectImportOpenChatTest") };
  }
  return null;
}

export function pipelineSteps(detail: PipelineRunDetail | undefined, t: Translate): CreatedKnowledgeDocument["pipeline"]["steps"] {
  return detail?.steps.map((step) => ({
    name: step.step_name,
    status: step.status,
    progress: step.progress_percent,
    retryCount: step.retry_count,
    artifactRef: step.output_artifact_ref,
    errorCode: step.error_code,
    error: (step.error_message || step.error_code) && !(step.ocr_call_state === "in_flight" && step.error_code === "ocr_image_provider_result_unknown") ? t(ocrFailureKey(step)) : null,
    ocr: step.step_name === "ocr_extract" || step.chunking_issue ? step : undefined
  }));
}

export const UPLOAD_EXTRACTION_GATE_INITIAL_DELAY_MS = 1200;
export const UPLOAD_EXTRACTION_GATE_POLL_INTERVAL_MS = 2500;

export function pipelineReachedExtractionGate(detail: PipelineRunDetail | null | undefined) {
  return detail?.status === "submission_ready";
}

export function pipelineFailedBeforeExtractionGate(detail: PipelineRunDetail | null | undefined) {
  return detail?.status === "failed" || Boolean(detail?.steps.some((step) => step.status === "failed"));
}

export function pipelineStepProgress(step: PipelineStepItem) {
  return Math.min(100, Math.max(0, Math.round(step.progress)));
}

export function pipelineStepStatusKind(status: string) {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "running") return "running";
  if (status === "waiting_action" || status === "pending" || status === "queued") return "waiting";
  return "neutral";
}

export function pipelineStepStatusLabel(status: string, t: Translate) {
  const labels: Record<string, TranslationKey> = {
    completed: "projectImportStepStatusCompleted",
    failed: "projectImportStepStatusFailed",
    running: "projectImportStepStatusRunning",
    waiting_action: "projectImportStepStatusWaiting",
    pending: "projectImportStepStatusPending",
    queued: "projectImportStepStatusQueued",
    skipped: "projectImportStepStatusSkipped"
  };
  const key = labels[status];
  return key ? t(key) : status.replaceAll("_", " ");
}

export function pipelineStepStats(steps: PipelineStepItem[]) {
  const completed = steps.filter((step) => pipelineStepStatusKind(step.status) === "completed").length;
  const failed = steps.filter((step) => pipelineStepStatusKind(step.status) === "failed").length;
  const active = steps.filter((step) => pipelineStepStatusKind(step.status) === "running").length;
  const percent = steps.length ? Math.round(steps.reduce((sum, step) => sum + pipelineStepProgress(step), 0) / steps.length) : 0;
  return { completed, failed, active, percent, total: steps.length };
}

export function extractionLabel(outcome: ExtractionOutcome | undefined): TranslationKey {
  return { complete: "projectImportExtractionComplete", failed: "projectImportExtractionNotSuccessful",
    running: "projectImportExtractionRunning", waiting: "projectImportExtractionWaiting",
    unknown: "projectImportExtractionUnknown" }[outcome ?? "unknown"] as TranslationKey;
}

export function liveDocumentFromSummary(document: DocumentSummary, t: Translate, detail?: PipelineRunDetail): CreatedKnowledgeDocument {
  const version = document.latest_version;
  // A late detail response must never supply the extraction state of another version.
  if (detail && (detail.document_version_id !== version?.id || detail.document_id !== document.id
    || detail.id !== document.latest_pipeline?.id)) detail = undefined;
  const versionRows = document.versions?.length ? document.versions : version ? [version] : [];
  const hasActiveVersion = versionRows.some((item) => item.status === "active");
  const pipeline = document.latest_pipeline;
  const extractionStatus = detail?.status ?? pipeline?.status;
  const outcome = extractionOutcome({ versionStatus: version?.status, pipelineStatus: detail?.status ?? pipeline?.status,
    currentStep: detail?.current_step_name ?? pipeline?.current_step_name, steps: pipelineSteps(detail, t) });
  const pipelineStatus = pipelineStatusFromVersion(version?.status, detail?.status ?? pipeline?.status);
  const pipelineId = detail?.id ?? pipeline?.id;
  const pipelineCurrentStep = versionPipelineState(version?.status) ? null : detail?.current_step_name ?? pipeline?.current_step_name;
  const pipelineProgress = detail?.progress_percent ?? pipeline?.progress_percent ?? 0;
  const pipelineError = detail?.error_message || pipeline?.error_message ? t(ocrFailureKey(detail?.steps.find(step => step.status === "failed"), detail?.error_message ?? pipeline?.error_message)) : "";
  const hasFormalPipelineState = Boolean(pipeline || detail) || ["processing", "submission_ready", "pending_manager_review", "pending_owner_review", "approved", "publishing", "production_indexing", "graph_syncing", "active"].includes(version?.status ?? "");
  const serviceSource = document.service_source ? {
    serviceType: document.service_source.service_type.toUpperCase() as NonNullable<CreatedKnowledgeDocument["serviceSource"]>["serviceType"],
    location: document.service_source.location,
    scheduleMode: document.service_source.schedule_mode === "cron" ? "cron" as const : "once" as const,
    cronExpression: document.service_source.cron_expression ?? undefined,
    timezone: document.service_source.timezone ?? "Asia/Taipei"
  } : undefined;
  const referenceSource = document.reference_source ? {
    referenceId: document.reference_source.reference_id,
    sourceProjectId: document.reference_source.source_project_id,
    sourceDocumentId: document.reference_source.source_document_id,
    sourceVersionId: document.reference_source.source_version_id,
    projectName: document.reference_source.project_name,
    documentName: document.reference_source.document_name,
    snapshotVersion: document.reference_source.snapshot_version,
    latestActiveVersion: document.reference_source.latest_active_version ?? document.reference_source.snapshot_version,
    hasAccess: document.reference_source.has_access,
    status: document.reference_source.status,
    detectedAt: document.reference_source.detected_at ? document.reference_source.detected_at.slice(0, 16).replace("T", " ") : "",
    pendingEventCount: document.reference_source.pending_event_count
  } : undefined;
  return {
    id: document.id,
    latestVersionId: version?.id,
    isLive: true,
    lockVersion: document.lock_version,
    title: document.title,
    version: version?.version_label ?? "v1.0",
    owner: document.created_by_name || t("documentMetadataUnknown"),
    documentStatus: document.status,
    versionStatus: versionPipelineState(version?.status) ? version!.status : extractionStatus === "submission_ready" ? "submission_ready" : extractionStatus === "failed" ? "failed" : version?.status ?? "draft",
    extractionSuccessful: outcome === "complete",
    extractionOutcome: outcome,
    hasActiveVersion,
    sourceType: serviceSource ? `${serviceSource.serviceType} service` : referenceSource ? t("projectImportReferenceOtherProject") : document.source_type === "file_upload" ? "File upload" : document.source_type,
    sourceState: serviceSource && !hasFormalPipelineState ? "ready_for_extraction" : hasFormalPipelineState ? "pipeline" : "ready_for_extraction",
    dataSourceId: document.service_source?.data_source_id,
    serviceSource,
    referenceSource,
    chunks: version?.active_chunk_count ?? null,
    chunkCountRunId: version?.status === "submission_ready" && pipeline?.status === "submission_ready"
      && typeof version.active_chunk_count === "number" ? pipeline.id ?? undefined : undefined,
    updatedAt: document.updated_at.slice(0, 16).replace("T", " "),
    impactedProjects: [],
    versions: versionRows.map((item) => ({ id: item.id, label: item.version_label, status: item.status, createdAt: item.created_at.slice(0, 16).replace("T", " "), author: item.created_by_name || t("documentMetadataUnknown"), lockVersion: item.lock_version })),
    pipeline: pipeline || detail
      ? { id: pipelineId, ...pipelineTimeFields(detail ?? pipeline ?? undefined), execution: detail?.execution ?? pipeline?.execution, status: pipelineStatus, progress: pipelineStatus === "published_active" ? 100 : pipelineProgress, currentStep: pipelineCurrentStep ? pipelineStepLabel(pipelineCurrentStep, t) : publishStageCurrentStep(pipelineStatus, t), waitingRole: publishStageWaitingRole(pipelineStatus, t), elapsed: "", eta: pipelineEtaForStatus(pipelineStatus, t), error: pipelineError, steps: pipelineSteps(detail, t) }
      : { status: "running", progress: 0, currentStep: t("projectImportWaitingManualExtraction"), waitingRole: "", elapsed: "", eta: "", error: "" }
  };
}

export function serviceDocumentFromResponse(response: DataSourceCreateResponse, t: Translate): CreatedKnowledgeDocument {
  const document = liveDocumentFromSummary(response.document, t);
  const remoteUri = typeof response.data_source.source_identity.remote_uri === "string" ? response.data_source.source_identity.remote_uri : response.document.title;
  const serviceType = response.data_source.service_type.toUpperCase() as NonNullable<CreatedKnowledgeDocument["serviceSource"]>["serviceType"];
  return {
    ...document,
    dataSourceId: response.data_source.id,
    sourceType: `${serviceType} service`,
    sourceState: response.sync_run.status === "queued" ? "syncing" : response.sync_run.status === "failed" ? "sync_failed" : "ready_for_extraction",
    serviceSource: {
      serviceType,
      location: remoteUri,
      scheduleMode: response.data_source.schedule_mode === "cron" ? "cron" : "once",
      cronExpression: response.data_source.cron_expression ?? undefined,
      timezone: response.data_source.timezone
    },
    pipeline: {
      ...document.pipeline,
      currentStep: response.sync_run.status === "queued" ? t("projectImportWaitingBackgroundSync") : response.sync_run.status === "failed" ? t("projectImportSyncFailed") : t("projectImportReadyExtractionTitle"),
      eta: response.sync_run.status === "queued" ? t("projectImportWaitingWorker") : "",
      error: response.sync_run.error_summary ? t("projectImportSyncFailed") : ""
    }
  };
}

export function getReferenceSource(document: DocumentItem): NonNullable<CreatedKnowledgeDocument["referenceSource"]> | null {
  return document.referenceSource ?? null;
}

export function getSourceState(document: DocumentItem): SourceState {
  return "sourceState" in document ? document.sourceState : "pipeline";
}

export function isServiceDocument(document: DocumentItem) {
  return Boolean(document.dataSourceId || document.serviceSource || document.sourceType.toLowerCase().includes("service"));
}

export function formatSyncDate(value: string | null | undefined, locale: "en" | "zh") {
  return formatShortDateTime(value, locale, "—");
}

export function syncRunLabel(status: string, t: Translate) {
  return { queued: t("projectImportSyncQueued"), running: t("projectImportSyncRunning"), success: t("projectImportSyncSuccess"), unchanged: t("projectImportSyncUnchanged"), failed: t("projectImportSyncFailed") }[status] ?? status;
}

export function syncRunStep(run: DataSyncRunResponse, t: Translate) {
  if (run.status === "success") return run.document_version_id ? t("projectImportSyncSuccessPendingExtraction") : t("projectImportSyncSuccessShort");
  if (run.status === "unchanged") return t("projectImportSyncUnchangedNoVersion");
  if (run.status === "failed") return t("projectImportSyncFailed");
  if (run.status === "running") return t("projectImportSyncWorkerRunning");
  return t("projectImportSyncQueuedStep");
}

export function projectImportErrorMessage(error: ApiError | Error | null, t: Translate, format: (key: TranslationKey, params: Record<string, string | number>) => string) {
  if (!error) return "";
  if ("code" in error && error.code === "last_project_owner") return t("projectImportLastOwnerError");
  if ("code" in error && error.code === "project_owner_self_protected") return t("projectImportSelfOwnerError");
  return operationalErrorMessage(error, t, format, "projectImportPermissionSaveFailed");
}

export function documentStatusLabel(status: string, t: Translate) {
  if (status === "active") return t("projectImportStatusActive");
  if (status === "inactive") return t("projectImportStatusInactive");
  if (status === "deleted") return t("projectImportStatusDeleted");
  return status;
}

/** Project import document list search and sort (OPT424-038). */
export function filterAndSortDocuments(allDocuments: DocumentItem[], documentQuery: string, sortBy: string) {
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
}
