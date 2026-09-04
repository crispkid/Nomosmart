"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Clock3, Database, FilePlus2, FolderSync, Layers3, ListRestart, MessageSquareText, Network, RotateCcw, ShieldCheck, Trash2, UploadCloud, UserPlus, UserRoundCog, X } from "lucide-react";
import { ActionButton, AppShell, PageGrid, Panel, StatCard, StatusBadge } from "@/components/AppShell";
import { DataServiceModal, UploadFilesModal, type CreatedKnowledgeDocument, type DataServicePayload, type SourceState } from "@/components/KnowledgeSourceModals";
import { ProjectReferenceModal } from "@/components/ProjectReferenceModal";
import { ProjectChatTest } from "@/components/ProjectChatTest";
import { ProjectGraphPreview } from "@/components/ProjectGraphPreview";
import { ProjectMemberAutocomplete } from "@/components/ProjectMemberAutocomplete";
import { ProjectMemberRoleSelector } from "@/components/ProjectMemberRoleSelector";
import { useAuth } from "@/components/AuthProvider";
import { createDataSource, getDocumentLifecycleImpact, getPipelineDetail, getProject, getUploadConfig, importProjectDocumentReferences, listDataSourceSyncRuns, listModels, listProjectDocuments, listProjectMembers, listProjectReferenceSources, queueDataSourceSync, removeProjectMember, replaceProjectMember, retryPipelineStep, searchProjectMemberCandidates, startDocumentExtraction, switchActiveDocumentVersion, testDataSourceConnection, updateDocumentLifecycle, updateDocumentReferenceVersion, updateProjectDocumentFile, uploadProjectDocuments, type AIModelResponse, type ApiError, type DataSourceCreateResponse, type DataSyncRunResponse, type DocumentSummary, type DocumentUploadResult, type PipelineRunDetail, type ProjectMemberCandidate, type ProjectMemberResponse, type ProjectResponse, type ReferenceSourceProjectResponse, type ReferenceSourceVersionResponse } from "@/lib/api";
import { t as translate } from "@/lib/i18n";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";
import { formatPersonName } from "@/lib/personName";
import { availableProjectMemberCandidates, projectMemberOwnerProtection } from "@/lib/projectPermissions";
import { useDebouncedProjectMemberCandidateSearch } from "@/lib/useDebouncedProjectMemberCandidateSearch";

type Translate = (key: TranslationKey) => string;

function normalizeVersion(version: string) {
  const match = version.match(/^v?(\d+)(?:\.(\d+))?$/i);
  return match ? `v${Number(match[1])}.${Number(match[2] ?? 0)}` : version;
}

function isWorkingVersion(status: string) {
  return status === "processing" || status === "submission_ready" || status === "pending_manager_review" || status === "pending_owner_review" || status === "approved";
}

function isReviewLockedVersionStatus(status: string) {
  return status === "pending_manager_review" || status === "pending_owner_review" || status === "approved";
}

type DocumentItem = CreatedKnowledgeDocument;
type PipelineStepItem = NonNullable<CreatedKnowledgeDocument["pipeline"]["steps"]>[number];
const projectMemberRoles = [
  { id: "owner", labelKey: "projectRoleOwner" },
  { id: "editor", labelKey: "projectRoleEditor" },
  { id: "viewer", labelKey: "projectRoleViewer" }
] as const;
type ProjectMemberRole = (typeof projectMemberRoles)[number]["id"];
type PendingStatusChange = {
  documentId: string;
  documentTitle: string;
  from: string;
  to: string;
  projects: string[];
  isLive: boolean;
  lockVersion?: number;
  requiresConfirmation: boolean;
};
type LifecycleNotice = {
  title: string;
  message: string;
};
type VersionSwitchTarget = {
  document: CreatedKnowledgeDocument;
  version: CreatedKnowledgeDocument["versions"][number];
};

function mapPipelineStatus(status?: string): CreatedKnowledgeDocument["pipeline"]["status"] {
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
  const mappedPipeline = mapPipelineStatus(pipelineStatus);
  if (pipelineStatus && mappedPipeline !== "running") return mappedPipeline;
  if (status === "pending_manager_review") return "pending_manager_review";
  if (status === "pending_owner_review") return "pending_owner_review";
  if (status === "approved") return "publish_ready";
  if (status === "publishing") return "publishing";
  if (status === "production_indexing") return "production_indexing";
  if (status === "graph_syncing") return "graph_syncing";
  if (status === "active") return "published_active";
  if (status === "review_rejected") return "failed";
  return mappedPipeline;
}

function publishStageCurrentStep(status: CreatedKnowledgeDocument["pipeline"]["status"], t: Translate) {
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
    skipped: t("projectImportStageSkipped")
  };
  return labels[status];
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
  return key ? t(key) : stepName.replaceAll("_", " ");
}

function publishStageWaitingRole(status: CreatedKnowledgeDocument["pipeline"]["status"], t: Translate) {
  if (status === "pending_manager_review") return t("projectImportWaitingManager");
  if (status === "pending_owner_review") return t("projectImportWaitingOwner");
  if (status === "approved" || status === "publish_ready") return t("projectImportWaitingPublisher");
  if (status === "production_indexing") return t("projectImportWaitingProductionIndex");
  if (status === "graph_syncing") return t("projectImportWaitingGraphSync");
  return "";
}

function pipelineEtaForStatus(status: CreatedKnowledgeDocument["pipeline"]["status"], t: Translate) {
  if (status === "submission_ready") return t("projectImportWaitingSubmission");
  if (status === "pending_manager_review" || status === "pending_owner_review") return t("projectImportWaitingApprovalAction");
  if (status === "approved" || status === "publish_ready") return t("projectImportWaitingPublishAction");
  if (status === "publishing" || status === "production_indexing" || status === "graph_syncing") return t("projectImportPublishingInProgress");
  if (status === "published_active") return t("projectImportPublishedAvailable");
  return t("projectImportBackgroundProcessing");
}

function publishStageAction(status: CreatedKnowledgeDocument["pipeline"]["status"], projectId: string, documentId: string, t: Translate) {
  if (status === "pending_manager_review" || status === "pending_owner_review" || status === "approved" || status === "publish_ready") {
    return { href: "/approve", label: t("projectImportOpenApprovalWorkspace") };
  }
  if (status === "published_active") {
    return { href: `/project/${projectId}/knowledge/${documentId}/chat-test`, label: t("projectImportOpenChatTest") };
  }
  return null;
}

function pipelineSteps(detail: PipelineRunDetail | undefined, t: Translate): CreatedKnowledgeDocument["pipeline"]["steps"] {
  return detail?.steps.map((step) => ({
    name: step.step_name,
    status: step.status,
    progress: step.progress_percent,
    retryCount: step.retry_count,
    artifactRef: step.output_artifact_ref,
    error: step.error_message ? t("apiGenericError") : null
  }));
}

const UPLOAD_EXTRACTION_GATE_POLL_LIMIT = 120;
const UPLOAD_EXTRACTION_GATE_INITIAL_DELAY_MS = 1200;
const UPLOAD_EXTRACTION_GATE_POLL_INTERVAL_MS = 2500;

function pipelineReachedExtractionGate(detail: PipelineRunDetail | null | undefined) {
  return detail?.status === "submission_ready";
}

function pipelineFailedBeforeExtractionGate(detail: PipelineRunDetail | null | undefined) {
  return detail?.status === "failed" || Boolean(detail?.steps.some((step) => step.status === "failed"));
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function pipelineStepProgress(step: PipelineStepItem) {
  return Math.min(100, Math.max(0, Math.round(step.progress)));
}

function pipelineStepStatusKind(status: string) {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "running") return "running";
  if (status === "waiting_action" || status === "pending" || status === "queued") return "waiting";
  return "neutral";
}

function pipelineStepStatusLabel(status: string, t: Translate) {
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

function pipelineStepStats(steps: PipelineStepItem[]) {
  const completed = steps.filter((step) => pipelineStepStatusKind(step.status) === "completed").length;
  const failed = steps.filter((step) => pipelineStepStatusKind(step.status) === "failed").length;
  const active = steps.filter((step) => ["running", "waiting"].includes(pipelineStepStatusKind(step.status))).length;
  const percent = steps.length ? Math.round(steps.reduce((sum, step) => sum + pipelineStepProgress(step), 0) / steps.length) : 0;
  return { completed, failed, active, percent, total: steps.length };
}

function liveDocumentFromSummary(document: DocumentSummary, t: Translate, detail?: PipelineRunDetail): CreatedKnowledgeDocument {
  const version = document.latest_version;
  const versionRows = document.versions?.length ? document.versions : version ? [version] : [];
  const hasActiveVersion = versionRows.some((item) => item.status === "active");
  const pipeline = document.latest_pipeline;
  const pipelineStatus = pipelineStatusFromVersion(version?.status, detail?.status ?? pipeline?.status);
  const pipelineId = detail?.id ?? pipeline?.id;
  const pipelineCurrentStep = detail?.current_step_name ?? pipeline?.current_step_name;
  const pipelineProgress = detail?.progress_percent ?? pipeline?.progress_percent ?? 0;
  const pipelineError = detail?.error_message || pipeline?.error_message ? t("apiGenericError") : "";
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
    owner: t("projectImportCurrentUser"),
    documentStatus: document.status,
    versionStatus: detail?.status === "submission_ready" ? "submission_ready" : detail?.status === "failed" ? "failed" : version?.status ?? "draft",
    extractionSuccessful: hasActiveVersion,
    sourceType: serviceSource ? `${serviceSource.serviceType} service` : referenceSource ? t("projectImportReferenceOtherProject") : document.source_type === "file_upload" ? "File upload" : document.source_type,
    sourceState: serviceSource && !hasFormalPipelineState ? "ready_for_extraction" : hasFormalPipelineState ? "pipeline" : "ready_for_extraction",
    dataSourceId: document.service_source?.data_source_id,
    serviceSource,
    referenceSource,
    chunks: detail?.steps.find((step) => step.step_name === "chunk_knowledge")?.output_artifact_ref ? 1 : 0,
    updatedAt: document.updated_at.slice(0, 16).replace("T", " "),
    impactedProjects: [],
    versions: versionRows.map((item) => ({ id: item.id, label: item.version_label, status: item.status, createdAt: item.created_at.slice(0, 16).replace("T", " "), author: t("projectImportCurrentUser"), lockVersion: item.lock_version })),
    pipeline: pipeline || detail
      ? { id: pipelineId, status: pipelineStatus, progress: pipelineStatus === "published_active" ? 100 : pipelineProgress, currentStep: pipelineCurrentStep ? pipelineStepLabel(pipelineCurrentStep, t) : publishStageCurrentStep(pipelineStatus, t), waitingRole: publishStageWaitingRole(pipelineStatus, t), elapsed: "", eta: pipelineEtaForStatus(pipelineStatus, t), error: pipelineError, steps: pipelineSteps(detail, t) }
      : { status: "running", progress: 0, currentStep: t("projectImportWaitingManualExtraction"), waitingRole: "", elapsed: "", eta: "", error: "" }
  };
}

function serviceDocumentFromResponse(response: DataSourceCreateResponse, t: Translate): CreatedKnowledgeDocument {
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

function getReferenceSource(document: DocumentItem): NonNullable<CreatedKnowledgeDocument["referenceSource"]> | null {
  return document.referenceSource ?? null;
}

function getSourceState(document: DocumentItem): SourceState {
  return "sourceState" in document ? document.sourceState : "pipeline";
}

function isServiceDocument(document: DocumentItem) {
  return Boolean(document.dataSourceId || document.serviceSource || document.sourceType.toLowerCase().includes("service"));
}

function formatSyncDate(value: string | null | undefined, locale: "en" | "zh") {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(locale === "en" ? "en-US" : "zh-TW", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function syncRunLabel(status: string, t: Translate) {
  return { queued: t("projectImportSyncQueued"), running: t("projectImportSyncRunning"), success: t("projectImportSyncSuccess"), unchanged: t("projectImportSyncUnchanged"), failed: t("projectImportSyncFailed") }[status] ?? status;
}

function syncRunStep(run: DataSyncRunResponse, t: Translate) {
  if (run.status === "success") return run.document_version_id ? t("projectImportSyncSuccessPendingExtraction") : t("projectImportSyncSuccessShort");
  if (run.status === "unchanged") return t("projectImportSyncUnchangedNoVersion");
  if (run.status === "failed") return t("projectImportSyncFailed");
  if (run.status === "running") return t("projectImportSyncWorkerRunning");
  return t("projectImportSyncQueuedStep");
}

function projectImportErrorMessage(error: ApiError | Error | null, t: Translate, format: (key: TranslationKey, params: Record<string, string | number>) => string) {
  if (!error) return "";
  if ("code" in error && error.code === "last_project_owner") return t("projectImportLastOwnerError");
  if ("code" in error && error.code === "project_owner_self_protected") return t("projectImportSelfOwnerError");
  return operationalErrorMessage(error, t, format, "projectImportPermissionSaveFailed");
}

function documentStatusLabel(status: string, t: Translate) {
  if (status === "active") return t("projectImportStatusActive");
  if (status === "inactive") return t("projectImportStatusInactive");
  if (status === "deleted") return t("projectImportStatusDeleted");
  return status;
}

export default function ImportPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const { apiFetch, currentUser } = useAuth();
  const { locale, format, localize } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [liveDocuments, setLiveDocuments] = useState<CreatedKnowledgeDocument[]>([]);
  const [ocrModels, setOcrModels] = useState<AIModelResponse[]>([]);
  const [documentQuery, setDocumentQuery] = useState("");
  const [sortBy, setSortBy] = useState("updatedAt");
  const [activeModal, setActiveModal] = useState<"graph" | "chat" | null>(null);
  const [permissionModalOpen, setPermissionModalOpen] = useState(false);
  const [projectMembers, setProjectMembers] = useState<ProjectMemberResponse[]>([]);
  const [permissionQuery, setPermissionQuery] = useState("");
  const [pendingPermissionUsers, setPendingPermissionUsers] = useState<ProjectMemberCandidate[]>([]);
  const [activePermissionRole, setActivePermissionRole] = useState<ProjectMemberRole>("owner");
  const [permissionLoading, setPermissionLoading] = useState(false);
  const [permissionError, setPermissionError] = useState<ApiError | Error | null>(null);
  const [permissionSavingUserId, setPermissionSavingUserId] = useState<string | null>(null);
  const [permissionRemovingUserId, setPermissionRemovingUserId] = useState<string | null>(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [initialUploadFiles, setInitialUploadFiles] = useState<File[]>([]);
  const [maxUploadSizeMb, setMaxUploadSizeMb] = useState(100);
  const [projectDropActive, setProjectDropActive] = useState(false);
  const projectDragDepth = useRef(0);
  const [dataServiceModalOpen, setDataServiceModalOpen] = useState(false);
  const [referenceModalOpen, setReferenceModalOpen] = useState(false);
  const [referenceSources, setReferenceSources] = useState<ReferenceSourceProjectResponse[]>([]);
  const [referenceSourcesLoading, setReferenceSourcesLoading] = useState(false);
  const [referenceSourcesError, setReferenceSourcesError] = useState("");
  const [createdImports, setCreatedImports] = useState<CreatedKnowledgeDocument[]>([]);
  const [versionDocumentId, setVersionDocumentId] = useState<string | null>(null);
  const updateFileInputRef = useRef<HTMLInputElement>(null);
  const [versionUpdateBusy, setVersionUpdateBusy] = useState(false);
  const [versionUpdateError, setVersionUpdateError] = useState("");
  const [versionUpdateNotice, setVersionUpdateNotice] = useState("");
  const [versionSwitchTarget, setVersionSwitchTarget] = useState<VersionSwitchTarget | null>(null);
  const [versionSwitchReason, setVersionSwitchReason] = useState("");
  const [versionSwitchBusy, setVersionSwitchBusy] = useState(false);
  const [versionSwitchError, setVersionSwitchError] = useState("");
  const [referenceUpdateVersions, setReferenceUpdateVersions] = useState<ReferenceSourceVersionResponse[]>([]);
  const [referenceUpdateVersionId, setReferenceUpdateVersionId] = useState("");
  const [referenceUpdateOldConfirmed, setReferenceUpdateOldConfirmed] = useState(false);
  const [referenceUpdateLoading, setReferenceUpdateLoading] = useState(false);
  const [documentLoadState, setDocumentLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [documentLoadError, setDocumentLoadError] = useState("");
  const [committedStatuses, setCommittedStatuses] = useState<Record<string, string>>({});
  const [pendingStatusChange, setPendingStatusChange] = useState<PendingStatusChange | null>(null);
  const [statusSubmitting, setStatusSubmitting] = useState(false);
  const [statusError, setStatusError] = useState("");
  const [lifecycleNotice, setLifecycleNotice] = useState<LifecycleNotice | null>(null);
  const [pipelineDetailLoading, setPipelineDetailLoading] = useState<Record<string, boolean>>({});
  const [syncRunsByDataSource, setSyncRunsByDataSource] = useState<Record<string, DataSyncRunResponse[]>>({});
  const [syncRunLoading, setSyncRunLoading] = useState<Record<string, boolean>>({});
  const canEditLifecycle = project?.capabilities.can_manage_lifecycle ?? false;
  const canManageProjectPermissions = project?.is_owner ?? false;
  const permissionRoleLabel = (role: ProjectMemberRole) => t(projectMemberRoles.find((item) => item.id === role)?.labelKey ?? "projectRoleViewer");
  const membersForActiveRole = projectMembers.filter((member) => member.roles.includes(activePermissionRole));
  const searchPermissionCandidates = useCallback(
    (query: string, signal: AbortSignal) => searchProjectMemberCandidates(apiFetch, params.id, query, signal),
    [apiFetch, params.id],
  );
  const permissionCandidateSearch = useDebouncedProjectMemberCandidateSearch({
    enabled: permissionModalOpen && canManageProjectPermissions,
    query: permissionQuery,
    search: searchPermissionCandidates,
  });
  const permissionUsers = permissionCandidateSearch.result?.items ?? [];
  const filteredPermissionUsers = availableProjectMemberCandidates(
    permissionUsers,
    projectMembers,
    new Set(pendingPermissionUsers.map((user) => user.id)),
  );
  const permissionSearchMessage = permissionCandidateSearch.phase === "waiting" || permissionCandidateSearch.phase === "loading"
    ? t("projectImportPermissionSearchLoading")
    : permissionCandidateSearch.phase === "error"
      ? t("projectImportPermissionSearchFailed")
      : permissionCandidateSearch.phase === "ready" && !filteredPermissionUsers.length
        ? permissionUsers.length
          ? t("projectImportPermissionSearchNoAdditionalRole")
          : (permissionCandidateSearch.result?.ineligible_match_count ?? 0) > 0
            ? t("projectImportPermissionSearchMissingAccess")
            : t("projectImportPermissionSearchNoResults")
        : "";

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getProject(apiFetch, params.id),
      listProjectMembers(apiFetch, params.id).catch(() => [])
    ]).then(([projectRow, members]) => {
      if (cancelled) return;
      setProject(projectRow);
      setProjectMembers(members);
    }).catch(() => {
      if (!cancelled) setProject(null);
    });
    return () => { cancelled = true; };
  }, [apiFetch, params.id]);

  async function loadProjectPermissions() {
    setPermissionLoading(true);
    setPermissionError(null);
    try {
      const [members, freshProject] = await Promise.all([listProjectMembers(apiFetch, params.id), getProject(apiFetch, params.id)]);
      setProjectMembers(members);
      setProject(freshProject);
    } catch (error) {
      setPermissionError(error as ApiError | Error);
    } finally {
      setPermissionLoading(false);
    }
  }

  function openPermissionModal() {
    if (!canManageProjectPermissions) return;
    setPermissionModalOpen(true);
    setPermissionQuery("");
    setPendingPermissionUsers([]);
    setActivePermissionRole("owner");
    void loadProjectPermissions();
  }

  async function saveProjectMemberRole(userId: string, role: ProjectMemberRole) {
    if (!project || !canManageProjectPermissions || permissionSavingUserId || permissionRemovingUserId) return;
    const member = projectMembers.find((row) => row.user_id === userId);
    if (member && projectMemberOwnerProtection(member, projectMembers, currentUser?.user_id)) return;
    setPermissionSavingUserId(userId);
    setPermissionError(null);
    try {
      const members = await replaceProjectMember(apiFetch, params.id, userId, { roles: [role], lock_version: project.lock_version });
      const freshProject = await getProject(apiFetch, params.id);
      setProjectMembers(members);
      setProject(freshProject);
    } catch (error) {
      setPermissionError(error as ApiError | Error);
    } finally {
      setPermissionSavingUserId(null);
    }
  }

  function stagePermissionCandidate(user: ProjectMemberCandidate) {
    setPendingPermissionUsers((current) => current.some((item) => item.id === user.id) ? current : [...current, user]);
    setPermissionQuery("");
  }

  async function commitPendingPermissionCandidates() {
    if (!project || !canManageProjectPermissions || permissionSavingUserId || permissionRemovingUserId || !pendingPermissionUsers.length) return;
    setPermissionSavingUserId("pending-members");
    setPermissionError(null);
    try {
      let currentProject = project;
      let currentMembers = projectMembers;
      for (const user of pendingPermissionUsers) {
        if (currentMembers.some((member) => member.user_id === user.id)) continue;
        currentMembers = await replaceProjectMember(apiFetch, params.id, user.id, { roles: [activePermissionRole], lock_version: currentProject.lock_version });
        currentProject = await getProject(apiFetch, params.id);
      }
      setProjectMembers(currentMembers);
      setProject(currentProject);
      setPendingPermissionUsers([]);
      setPermissionQuery("");
    } catch (error) {
      setPermissionError(error as ApiError | Error);
    } finally {
      setPermissionSavingUserId(null);
    }
  }

  async function removeProjectPermissionMember(userId: string) {
    if (!project || !canManageProjectPermissions || permissionSavingUserId || permissionRemovingUserId) return;
    const member = projectMembers.find((row) => row.user_id === userId);
    if (member && projectMemberOwnerProtection(member, projectMembers, currentUser?.user_id)) return;
    setPermissionRemovingUserId(userId);
    setPermissionError(null);
    try {
      const updated = await removeProjectMember(apiFetch, params.id, userId, project.lock_version);
      const members = await listProjectMembers(apiFetch, params.id);
      setProjectMembers(members);
      setProject(updated);
    } catch (error) {
      setPermissionError(error as ApiError | Error);
    } finally {
      setPermissionRemovingUserId(null);
    }
  }

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
      setLiveDocuments(hydrated);
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
  }, [apiFetch, params.id, t]);

  const visibleDocuments = useMemo(() => {
    const query = documentQuery.trim().toLowerCase();
    const filtered = [...createdImports, ...liveDocuments].filter((document) => {
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
  }, [createdImports, liveDocuments, documentQuery, sortBy]);
  const allDocuments = [...createdImports, ...liveDocuments];
  const versionDocument = allDocuments.find((document) => document.id === versionDocumentId);
  const versionReferenceSource = versionDocument ? getReferenceSource(versionDocument) : null;
  const displayedVersions = versionDocument ? versionDocument.versions : [];
  const versionDataSourceId = versionDocument && "dataSourceId" in versionDocument ? versionDocument.dataSourceId : undefined;
  const currentSyncRuns = versionDataSourceId ? syncRunsByDataSource[versionDataSourceId] ?? [] : [];

  useEffect(() => {
    if (!versionDataSourceId) return;
    let cancelled = false;
    setSyncRunLoading((current) => ({ ...current, [versionDataSourceId]: true }));
    listDataSourceSyncRuns(apiFetch, params.id, versionDataSourceId)
      .then((runs) => {
        if (!cancelled) setSyncRunsByDataSource((current) => ({ ...current, [versionDataSourceId]: runs }));
      })
      .catch(() => {
        if (!cancelled) setSyncRunsByDataSource((current) => ({ ...current, [versionDataSourceId]: [] }));
      })
      .finally(() => {
        if (!cancelled) setSyncRunLoading((current) => ({ ...current, [versionDataSourceId]: false }));
      });
    return () => {
      cancelled = true;
    };
  }, [apiFetch, params.id, versionDataSourceId]);

  useEffect(() => {
    const source = versionReferenceSource;
    setVersionUpdateError("");
    setVersionUpdateNotice("");
    setReferenceUpdateVersions([]);
    setReferenceUpdateVersionId("");
    setReferenceUpdateOldConfirmed(false);
    if (!source?.referenceId || !source.sourceDocumentId || !source.hasAccess) return;
    let cancelled = false;
    setReferenceUpdateLoading(true);
    listProjectReferenceSources(apiFetch, params.id)
      .then((projects) => {
        if (cancelled) return;
        const documents = projects.flatMap((project) => project.documents);
        const sourceDocument = documents.find((document) => document.id === source.sourceDocumentId);
        const versions = sourceDocument?.versions ?? [];
        setReferenceUpdateVersions(versions);
        const selected = versions.find((version) => version.id === source.sourceVersionId) ?? versions.find((version) => version.status === "active") ?? versions[0];
        setReferenceUpdateVersionId(selected?.id ?? "");
      })
      .catch((error) => {
        if (!cancelled) setVersionUpdateError(operationalErrorMessage(error, t, format, "referenceLoadSourcesFailed"));
      })
      .finally(() => {
        if (!cancelled) setReferenceUpdateLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [apiFetch, format, params.id, t, versionReferenceSource]);

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

  function mergeUploadedDocuments(current: CreatedKnowledgeDocument[], documents: CreatedKnowledgeDocument[]) {
    const incomingIds = new Set(documents.map((document) => document.id));
    return [...documents, ...current.filter((document) => !incomingIds.has(document.id))];
  }

  function applyPipelineDetailToDocument(document: CreatedKnowledgeDocument, detail: PipelineRunDetail): CreatedKnowledgeDocument {
    const status = mapPipelineStatus(detail.status);
    const versionStatus = detail.status === "submission_ready" ? "submission_ready" : detail.status === "failed" ? "failed" : document.versionStatus;
    return {
      ...document,
      sourceState: "pipeline",
      versionStatus,
      versions: document.versions.map((version) => version.id === document.latestVersionId ? { ...version, status: versionStatus } : version),
      pipeline: {
        ...document.pipeline,
        id: detail.id,
        status,
        progress: detail.progress_percent,
        currentStep: detail.current_step_name ? pipelineStepLabel(detail.current_step_name, t) : publishStageCurrentStep(status, t),
        eta: pipelineEtaForStatus(status, t),
        error: detail.error_message ? t("apiGenericError") : "",
        steps: pipelineSteps(detail, t)
      }
    };
  }

  function updateUploadedDocumentSnapshots(documents: CreatedKnowledgeDocument[]) {
    const incoming = new Map(documents.map((document) => [document.id, document]));
    setCreatedImports((current) => mergeUploadedDocuments(current, documents));
    setLiveDocuments((current) => current.map((document) => incoming.get(document.id) ?? document));
  }

  async function pollPipelineUntilCompletionGate(document: CreatedKnowledgeDocument, onProgressDocuments?: (documents: CreatedKnowledgeDocument[]) => void, initialDetail?: PipelineRunDetail) {
    let latestDetail = initialDetail;
    let latestDocument = latestDetail ? applyPipelineDetailToDocument(document, latestDetail) : document;
    if (latestDetail) {
      onProgressDocuments?.([latestDocument]);
      updateUploadedDocumentSnapshots([latestDocument]);
    }
    for (let attempt = 0; attempt < UPLOAD_EXTRACTION_GATE_POLL_LIMIT; attempt += 1) {
      if (pipelineReachedExtractionGate(latestDetail) || pipelineFailedBeforeExtractionGate(latestDetail)) return latestDocument;
      if (!document.latestVersionId || !document.pipeline.id) return latestDocument;
      await sleep(attempt === 0 && latestDetail ? UPLOAD_EXTRACTION_GATE_INITIAL_DELAY_MS : UPLOAD_EXTRACTION_GATE_POLL_INTERVAL_MS);
      latestDetail = await getPipelineDetail(apiFetch, params.id, document.id, document.latestVersionId, document.pipeline.id);
      latestDocument = applyPipelineDetailToDocument(latestDocument, latestDetail);
      onProgressDocuments?.([latestDocument]);
      updateUploadedDocumentSnapshots([latestDocument]);
    }
    return latestDocument;
  }

  function addUploadedDocuments(documents: CreatedKnowledgeDocument[], autoExtractionId?: string) {
    updateUploadedDocumentSnapshots(documents);
    if (autoExtractionId) router.push(`/project/${params.id}/knowledge/${autoExtractionId}`);
  }

  function openUploadModal(files: File[] = []) {
    setInitialUploadFiles(files);
    setUploadModalOpen(true);
  }

  function closeUploadModal() {
    setUploadModalOpen(false);
    setInitialUploadFiles([]);
    projectDragDepth.current = 0;
    setProjectDropActive(false);
  }

  function addDataServiceDocument(document: CreatedKnowledgeDocument) {
    setCreatedImports((current) => [document, ...current]);
  }

  async function testLiveDataSource(payload: DataServicePayload) {
    await testDataSourceConnection(apiFetch, params.id, payload);
  }

  async function createLiveDataSource(payload: DataServicePayload) {
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
    const liveDocument = [...createdImports, ...liveDocuments].find((item) => item.id === documentId && item.isLive && item.latestVersionId);
    if (liveDocument?.latestVersionId) {
      try {
        const response = await startDocumentExtraction(apiFetch, params.id, liveDocument.id, liveDocument.latestVersionId, {});
        const detail = response.pipeline.id ? await getPipelineDetail(apiFetch, params.id, liveDocument.id, liveDocument.latestVersionId, response.pipeline.id) : undefined;
        const next = liveDocumentFromSummary(response.document, t, detail);
        setLiveDocuments((current) => current.map((item) => item.id === documentId ? next : item));
        setCreatedImports((current) => current.map((item) => item.id === documentId ? next : item));
        return;
      } catch (error) {
        const message = operationalErrorMessage(error, t, format, "projectImportStatusUpdateFailed");
        const markFailed = (item: CreatedKnowledgeDocument): CreatedKnowledgeDocument => item.id === documentId ? {
          ...item,
          sourceState: "pipeline",
          pipeline: { ...item.pipeline, status: "failed", progress: 0, currentStep: t("projectImportStartExtraction"), eta: "", error: message }
        } : item;
        setLiveDocuments((current) => current.map(markFailed));
        setCreatedImports((current) => current.map(markFailed));
        return;
      }
    }
    setCreatedImports((current) => current.map((item) => item.id === documentId ? {
      ...item,
      sourceState: "pipeline",
      versionStatus: "processing",
      versions: item.versions.map((version, index) => index === 0 ? { ...version, status: "processing" } : version),
      pipeline: { status: "running", progress: 5, currentStep: t("projectImportUploadReceived"), waitingRole: "", elapsed: "00m 04s", eta: t("projectImportUploadEta"), error: "" }
    } : item));
  }

  async function uploadLiveDocuments(files: File[], options: { ocrModelId: string | null; forceOcr: boolean; startExtraction: boolean }, onProgressDocuments?: (documents: CreatedKnowledgeDocument[]) => void) {
    const upload = await uploadProjectDocuments(apiFetch, params.id, files, { ocrModelId: options.ocrModelId, forceOcr: options.forceOcr, startExtraction: options.startExtraction });
    const results = upload.results.filter((result): result is DocumentUploadResult & { document: DocumentSummary } => result.status === "success" && result.document !== null);
    if (!results.length && upload.failed_count) {
      const failure = upload.results[0];
      throw Object.assign(new Error("document_upload_failed"), { status: 422, code: failure?.error_code || "document_upload_failed" }) as ApiError;
    }
    const summaries = results.map((result) => liveDocumentFromSummary(result.document, t));
    onProgressDocuments?.(summaries);
    updateUploadedDocumentSnapshots(summaries);
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
        const detail = await getPipelineDetail(apiFetch, params.id, result.document.id, versionId, pipelineId);
        const hydratedDocument = liveDocumentFromSummary(result.document, t, detail);
        hydrated.push(options.startExtraction && results.length === 1 ? await pollPipelineUntilCompletionGate(hydratedDocument, onProgressDocuments, detail) : hydratedDocument);
      } catch {
        hydrated.push(summaries[index]);
      }
      onProgressDocuments?.([...hydrated, ...summaries.slice(index + 1)]);
      updateUploadedDocumentSnapshots(hydrated);
    }
    return hydrated;
  }

  async function retryUploadModalPipeline(document: CreatedKnowledgeDocument, onProgressDocument?: (document: CreatedKnowledgeDocument) => void) {
    const failedStep = document.pipeline.steps?.find((step) => step.status === "failed");
    if (!document.latestVersionId || !document.pipeline.id || !failedStep) throw new Error(t("knowledgeDetailRetryFailed"));
    const detail = await retryPipelineStep(apiFetch, params.id, document.id, document.latestVersionId, document.pipeline.id, failedStep.name);
    const restarted = applyPipelineDetailToDocument(document, detail);
    updateUploadedDocumentSnapshots([restarted]);
    return pollPipelineUntilCompletionGate(restarted, (documents) => onProgressDocument?.(documents[0]), detail);
  }

  async function retryLivePipelineStep(document: CreatedKnowledgeDocument, stepName?: string | null) {
    if (!document.isLive || !document.latestVersionId || !document.pipeline.id || !stepName) return;
    setPipelineDetailLoading((current) => ({ ...current, [document.id]: true }));
    try {
      const detail = await retryPipelineStep(apiFetch, params.id, document.id, document.latestVersionId, document.pipeline.id, stepName);
      const patch = {
        status: mapPipelineStatus(detail.status),
        progress: detail.progress_percent,
        currentStep: detail.current_step_name ? pipelineStepLabel(detail.current_step_name, t) : document.pipeline.currentStep,
        error: detail.error_message ? t("apiGenericError") : "",
        steps: pipelineSteps(detail, t)
      };
      setLiveDocuments((current) => current.map((item) => item.id === document.id ? { ...item, pipeline: { ...item.pipeline, ...patch } } : item));
      setCreatedImports((current) => current.map((item) => item.id === document.id ? { ...item, pipeline: { ...item.pipeline, ...patch } } : item));
    } finally {
      setPipelineDetailLoading((current) => ({ ...current, [document.id]: false }));
    }
  }

  async function syncNow(document: DocumentItem) {
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

  async function hydrateUpdatedDocument(document: DocumentSummary) {
    const versionId = document.latest_version?.id;
    const pipelineId = document.latest_pipeline?.id;
    if (!versionId || !pipelineId) return liveDocumentFromSummary(document, t);
    try {
      const detail = await getPipelineDetail(apiFetch, params.id, document.id, versionId, pipelineId);
      return liveDocumentFromSummary(document, t, detail);
    } catch {
      return liveDocumentFromSummary(document, t);
    }
  }

  async function reloadLiveDocuments() {
    const documents = await listProjectDocuments(apiFetch, params.id);
    const hydrated = await Promise.all(documents.map((document) => hydrateUpdatedDocument(document)));
    setLiveDocuments(hydrated);
    return hydrated;
  }

  async function applyUpdatedDocument(document: DocumentSummary) {
    const next = await hydrateUpdatedDocument(document);
    setLiveDocuments((current) => current.map((item) => item.id === next.id ? next : item));
    setCreatedImports((current) => current.map((item) => item.id === next.id ? next : item));
    return next;
  }

  async function updateCurrentFileVersion(file: File | null | undefined) {
    if (!file || !versionDocument?.isLive || versionUpdateBusy) return;
    setVersionUpdateBusy(true);
    setVersionUpdateError("");
    setVersionUpdateNotice("");
    try {
      const response = await updateProjectDocumentFile(apiFetch, params.id, versionDocument.id, file);
      if (response.no_change) {
        setVersionUpdateNotice(t("projectImportUpdateNoChange"));
        return;
      }
      const next = await applyUpdatedDocument(response.document);
      setVersionDocumentId(next.id);
      setVersionUpdateNotice(t("projectImportUpdateStarted"));
    } catch (error) {
      setVersionUpdateError(operationalErrorMessage(error, t, format, "projectImportUpdateFailed"));
    } finally {
      setVersionUpdateBusy(false);
      if (updateFileInputRef.current) updateFileInputRef.current.value = "";
    }
  }

  async function updateCurrentReferenceVersion() {
    const source = versionReferenceSource;
    if (!source?.referenceId || !referenceUpdateVersionId || versionUpdateBusy) return;
    const selected = referenceUpdateVersions.find((version) => version.id === referenceUpdateVersionId);
    if (selected && selected.status !== "active" && !referenceUpdateOldConfirmed) {
      setVersionUpdateError(t("projectImportReferenceOldVersionConfirmRequired"));
      return;
    }
    setVersionUpdateBusy(true);
    setVersionUpdateError("");
    setVersionUpdateNotice("");
    try {
      const response = await updateDocumentReferenceVersion(apiFetch, source.referenceId, { source_version_id: referenceUpdateVersionId, old_version_confirmed: referenceUpdateOldConfirmed });
      const next = await applyUpdatedDocument(response.document);
      setVersionDocumentId(next.id);
      setVersionUpdateNotice(response.no_change ? t("projectImportReferenceNoChange") : t("projectImportReferenceUpdateStarted"));
      setReferenceUpdateOldConfirmed(false);
    } catch (error) {
      setVersionUpdateError(operationalErrorMessage(error, t, format, "projectImportUpdateFailed"));
    } finally {
      setVersionUpdateBusy(false);
    }
  }

  function requestVersionSwitch(version: CreatedKnowledgeDocument["versions"][number]) {
    if (!versionDocument || version.status !== "inactive" || !canEditLifecycle) return;
    setVersionSwitchTarget({ document: versionDocument, version });
    setVersionSwitchReason(format("projectImportSwitchActiveDefaultReason", { version: version.label }));
    setVersionSwitchError("");
  }

  async function confirmVersionSwitch() {
    if (!versionSwitchTarget || versionSwitchBusy) return;
    const target = versionSwitchTarget;
    const reason = versionSwitchReason.trim();
    if (!reason) {
      setVersionSwitchError(t("projectImportSwitchActiveReasonRequired"));
      return;
    }
    if (!target.version.lockVersion) {
      setVersionSwitchError(t("projectImportMissingLockVersion"));
      return;
    }
    setVersionSwitchBusy(true);
    setVersionSwitchError("");
    setVersionUpdateError("");
    setVersionUpdateNotice("");
    try {
      await switchActiveDocumentVersion(apiFetch, target.version.id, {
        lock_version: target.version.lockVersion,
        impact_confirmed: true,
        audit_reason: reason
      });
      const refreshed = await reloadLiveDocuments();
      setCreatedImports((current) => current.filter((item) => !refreshed.some((document) => document.id === item.id)));
      setVersionDocumentId(target.document.id);
      setVersionSwitchTarget(null);
      setVersionSwitchReason("");
      setVersionUpdateNotice(format("projectImportVersionSwitchSuccess", { version: target.version.label }));
    } catch (error) {
      setVersionSwitchError(operationalErrorMessage(error, t, format, "projectImportVersionSwitchFailed"));
    } finally {
      setVersionSwitchBusy(false);
    }
  }

  useEffect(() => {
    if (!pendingStatusChange) return;
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !statusSubmitting) setPendingStatusChange(null);
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [pendingStatusChange, statusSubmitting]);

  useEffect(() => {
    if (!lifecycleNotice) return;
    const timeoutId = window.setTimeout(() => setLifecycleNotice(null), 4500);
    return () => window.clearTimeout(timeoutId);
  }, [lifecycleNotice]);

  function impactSummaryProjects(referenceCount: number, activeVersionCount: number) {
    const summary = [];
    if (referenceCount > 0) summary.push(format("projectImportImpactReferences", { count: referenceCount }));
    if (activeVersionCount > 0) summary.push(format("projectImportImpactActiveVersions", { count: activeVersionCount }));
    return summary;
  }

  async function requestStatusChange(document: DocumentItem, requestedStatus: string, currentStatus: string) {
    if (requestedStatus === currentStatus) return;
    setStatusError("");
    setLifecycleNotice(null);
    if (requestedStatus === "inactive" || requestedStatus === "deleted") {
      const baseChange: PendingStatusChange = { documentId: document.id, documentTitle: document.title, from: currentStatus, to: requestedStatus, projects: document.impactedProjects, isLive: Boolean("isLive" in document && document.isLive), lockVersion: "lockVersion" in document ? document.lockVersion : undefined, requiresConfirmation: true };
      setPendingStatusChange(baseChange);
      if ("isLive" in document && document.isLive) {
        try {
          const impact = await getDocumentLifecycleImpact(apiFetch, params.id, document.id, requestedStatus);
          setPendingStatusChange((current) => current?.documentId === document.id && current.to === requestedStatus ? { ...current, projects: impactSummaryProjects(impact.impacted_reference_count, impact.impacted_active_version_count), requiresConfirmation: impact.requires_confirmation } : current);
        } catch (error) {
          setStatusError(operationalErrorMessage(error, t, format, "projectImportImpactLoadFailed"));
        }
      }
      return;
    }
    if ("isLive" in document && document.isLive) {
      if (!canEditLifecycle) {
        setStatusError(t("projectImportMissingLifecyclePermission"));
        return;
      }
      if (!("lockVersion" in document) || document.lockVersion === undefined) {
        setStatusError(t("projectImportMissingLockVersion"));
        return;
      }
      setStatusSubmitting(true);
      try {
        const updated = await updateDocumentLifecycle(apiFetch, params.id, document.id, { lock_version: document.lockVersion, status: requestedStatus, impact_confirmed: false, reason: "lifecycle update from project document list" });
        setLiveDocuments((current) => current.map((item) => item.id === document.id ? liveDocumentFromSummary(updated, t) : item));
        setCreatedImports((current) => current.map((item) => item.id === document.id ? liveDocumentFromSummary(updated, t) : item));
        setCommittedStatuses((current) => {
          const next = { ...current };
          delete next[document.id];
          return next;
        });
        if (currentStatus === "inactive" && requestedStatus === "active") {
          setLifecycleNotice({
            title: t("projectImportReactivatedTitle"),
            message: t("projectImportReactivatedMessage")
          });
        }
      } catch (error) {
        setStatusError(operationalErrorMessage(error, t, format, "projectImportStatusUpdateFailed"));
      } finally {
        setStatusSubmitting(false);
      }
      return;
    }
    setCommittedStatuses((current) => ({ ...current, [document.id]: requestedStatus }));
  }

  async function confirmStatusChange() {
    if (!pendingStatusChange || statusSubmitting) return;
    const change = pendingStatusChange;
    setStatusSubmitting(true);
    setStatusError("");
    if (change.isLive) {
      try {
        if (change.lockVersion === undefined) throw new Error(t("projectImportMissingLockVersion"));
        const updated = await updateDocumentLifecycle(apiFetch, params.id, change.documentId, { lock_version: change.lockVersion, status: change.to, impact_confirmed: change.requiresConfirmation, reason: change.to === "deleted" ? "soft delete from project document list" : "lifecycle update from project document list" });
        if (change.to === "deleted" || updated.status === "deleted") {
          setLiveDocuments((current) => current.filter((item) => item.id !== change.documentId));
          setCreatedImports((current) => current.filter((item) => item.id !== change.documentId));
        } else {
          setLiveDocuments((current) => current.map((item) => item.id === change.documentId ? liveDocumentFromSummary(updated, t) : item));
          setCreatedImports((current) => current.map((item) => item.id === change.documentId ? liveDocumentFromSummary(updated, t) : item));
        }
        setCommittedStatuses((current) => {
          const next = { ...current };
          delete next[change.documentId];
          return next;
        });
        setPendingStatusChange(null);
      } catch (error) {
        setStatusError(error instanceof Error && !(`status` in error) ? t("projectImportMissingLockVersion") : operationalErrorMessage(error, t, format, "projectImportStatusUpdateFailed"));
      } finally {
        setStatusSubmitting(false);
      }
      return;
    }
    window.setTimeout(() => {
      if (change.to === "deleted") {
        setCreatedImports((current) => current.filter((item) => item.id !== change.documentId));
      } else {
        setCommittedStatuses((current) => ({ ...current, [change.documentId]: change.to }));
      }
      setStatusSubmitting(false);
      setPendingStatusChange(null);
    }, 300);
  }

  return (
    <AppShell title={project?.name ?? t("projectImportFallbackProjectTitle")}>
      {lifecycleNotice ? (
        <div className="lifecycle-notice-popup" role="status" aria-live="polite">
          <CheckCircle2 size={18} />
          <div>
            <strong>{localize(lifecycleNotice.title)}</strong>
            <span>{localize(lifecycleNotice.message)}</span>
          </div>
          <button aria-label={t("projectImportDismissLifecycleNotice")} onClick={() => setLifecycleNotice(null)} type="button">
            <X size={15} />
          </button>
        </div>
      ) : null}

      <div className="project-context">
        <Link className="text-link" href="/projects"><ArrowLeft size={16} /> {t("projectImportBackToProjects")}</Link>
        <div className="project-context-actions">
          <button className="action-button secondary" onClick={() => setActiveModal("graph")} type="button"><Network size={16} /> {t("knowledgeGraph")}</button>
          <button className="action-button secondary" onClick={() => setActiveModal("chat")} type="button"><MessageSquareText size={16} /> {t("chatTest")}</button>
          {canManageProjectPermissions ? <button className="action-button secondary" onClick={openPermissionModal} type="button"><ShieldCheck size={16} /> {t("projectImportPermissionManagement")}</button> : null}
        </div>
      </div>

      <PageGrid>
        <StatCard label={t("totalDocuments")} value={documentLoadState === "loading" ? "…" : String(allDocuments.length)} helper={`active ${allDocuments.filter((item) => item.documentStatus === "active").length} / inactive ${allDocuments.filter((item) => item.documentStatus === "inactive").length}`} />
        <StatCard label={t("projectImportPipelineRunning")} value={documentLoadState === "loading" ? "…" : String(allDocuments.filter((item) => ["queued", "running", "submission_ready", "pending_manager_review", "pending_owner_review", "approved", "publish_ready", "publishing", "production_indexing", "graph_syncing", "waiting_action"].includes(item.pipeline.status)).length)} helper={t("projectImportPipelineRunningHelp")} tone="sage" />
        <StatCard label={t("projectImportFailedItems")} value={documentLoadState === "loading" ? "…" : String(allDocuments.filter((item) => item.pipeline.status === "failed" || getSourceState(item) === "sync_failed").length)} helper={t("projectImportFailedItemsHelp")} tone="gold" />
        <StatCard label={t("projectImportReadyForExtraction")} value={documentLoadState === "loading" ? "…" : String(allDocuments.filter((item) => getSourceState(item) === "ready_for_extraction").length)} helper={t("projectImportReadyForExtractionHelp")} />
      </PageGrid>

      <div className="content-grid">
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
      </div>

      <Panel
        title={t("projectImportDocumentList")}
        action={
          <div className="document-toolbar">
            <label className="document-search">
              <span>{t("search")}</span>
              <input
                onChange={(event) => setDocumentQuery(event.target.value)}
                placeholder={t("projectImportSearchPlaceholder")}
                value={documentQuery}
              />
            </label>
            <label className="document-sort">
              <span>{t("sort")}</span>
              <select onChange={(event) => setSortBy(event.target.value)} value={sortBy}>
                <option value="updatedAt">{t("projectImportSortUpdatedAt")}</option>
                <option value="status">{t("status")}</option>
                <option value="progress">{t("projectImportSortProgress")}</option>
                <option value="name">{t("projectImportSortName")}</option>
              </select>
            </label>
          </div>
        }
      >
        {documentLoadState === "loading" ? <div className="empty-state compact" role="status"><Clock3 size={24} /><p>{t("projectImportLoadingDocuments")}</p></div> : null}
        {documentLoadState === "error" ? <div className="empty-state compact" role="alert"><AlertTriangle size={24} /><p>{localize(documentLoadError)}</p></div> : null}
        {documentLoadState === "ready" && visibleDocuments.length === 0 ? <div className="empty-state compact"><FilePlus2 size={24} /><p>{t("projectImportNoFormalDocuments")}</p></div> : null}
        <div className="document-pipeline-list">
          {visibleDocuments.map((document) => {
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
            const committedStatus = committedStatuses[document.id] ?? document.documentStatus;
            const effectiveStatus = committedStatus === "deleted" ? "deleted" : waitingForAction ? "inactive" : committedStatus;
            const activeVersion = document.versions.find((version) => version.status === "active")?.label;
            const workingVersion = document.versions.find((version) => isWorkingVersion(version.status))?.label;
            const referenceSource = getReferenceSource(document);
            const stageAction = publishStageAction(pipeline.status, params.id, document.id, t);
            return (
            <article className="document-pipeline-card" key={document.id}>
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
                    <button className="text-link" onClick={() => startManualExtraction(document.id)} type="button">
                      {t("knowledgeExtraction")} <ArrowRight size={16} />
                    </button>
                  ) : (
                    <Link className="text-link" href={`/project/${params.id}/knowledge/${document.id}`}>
                      {t("knowledgeExtraction")} <ArrowRight size={16} />
                    </Link>
                  )}
                </div>
              </div>

              <div className="document-pipeline-body">
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
	                      {sourceState === "ready_for_extraction" ? <button className="action-button" disabled={reviewLocked} onClick={() => startManualExtraction(document.id)} title={reviewLocked ? t("projectImportReviewExtractionLockedHelp") : undefined} type="button"><ArrowRight size={16} /> {t("projectImportStartExtraction")}</button> : null}
	                      <button className="action-button danger" disabled={!canEditLifecycle || pendingStatusChange?.documentId === document.id || statusSubmitting} onClick={() => { void requestStatusChange(document, "deleted", committedStatuses[document.id] ?? document.documentStatus); }} title={!canEditLifecycle ? t("projectImportMissingLifecyclePermission") : undefined} type="button"><AlertTriangle size={16} /> {t("delete")}</button>
	                    </div>
                  </div>
                ) : <>
                <div className="pipeline-summary">
                  <span>{format("projectImportChunkCount", { count: document.chunks })}</span>
                  <span>{t("pipelineCurrentStep")}：{localize(pipeline.currentStep)}</span>
                  <span>{t("pipelineElapsed")}：{pipeline.elapsed}</span>
                  <span>{t("pipelineEta")}：{localize(pipeline.eta)}</span>
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
                  {pipeline.error ? (
                    <span className="error-summary"><AlertTriangle size={15} /> {localize(pipeline.error)}</span>
                  ) : (
                    <span className="ready-summary"><Clock3 size={15} /> {t("projectImportPipelineLiveUpdating")}</span>
                  )}
                  {pipeline.status === "failed" ? (
                    <button className="action-button secondary" disabled={reviewLocked || !failedStep || retryLimitReached || pipelineDetailLoading[document.id]} onClick={() => retryLivePipelineStep(document as CreatedKnowledgeDocument, failedStep?.name)} title={reviewLocked ? t("projectImportReviewExtractionLockedHelp") : undefined} type="button"><RotateCcw size={16} /> {retryLimitReached ? t("projectImportRetryLimitReached") : t("pipelineRetryFailedStep")}</button>
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
	                    <select
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
                      ) : document.extractionSuccessful ? (
                        <>
                          <option value="active">{t("projectImportStatusActive")}</option>
                          <option value="inactive">{t("projectImportStatusInactive")}</option>
                          <option value="deleted">{t("delete")}</option>
                        </>
                      ) : (
                        <>
                          <option disabled value={document.documentStatus}>{t("projectImportExtractionNotSuccessful")}</option>
                          <option value="deleted">{t("delete")}</option>
                        </>
                      )}
                    </select>
                  </div>
                </div>
                {cardSteps?.length ? (
                  <details className="pipeline-step-detail">
                    <summary>{t("projectImportPipelineStepDetails")}</summary>
                    {stepStats ? (
                      <div className="pipeline-step-overview" aria-label={format("projectImportPipelineStepOverviewAria", { completed: stepStats.completed, total: stepStats.total, percent: stepStats.percent })}>
                        <div>
                          <strong>{format("projectImportPipelineStepProgress", { completed: stepStats.completed, total: stepStats.total })}</strong>
                          <small>{format("projectImportPipelineStepOverall", { percent: stepStats.percent })}</small>
                        </div>
                        <span className="step-overview-pill completed"><CheckCircle2 size={13} /> {format("projectImportPipelineStepCompletedCount", { count: stepStats.completed })}</span>
                        <span className="step-overview-pill active"><Clock3 size={13} /> {format("projectImportPipelineStepActiveCount", { count: stepStats.active })}</span>
                        <span className={`step-overview-pill ${stepStats.failed ? "failed" : "neutral"}`}><AlertTriangle size={13} /> {format("projectImportPipelineStepFailedCount", { count: stepStats.failed })}</span>
                      </div>
                    ) : null}
                    <ol className="pipeline-step-card-grid">
                      {cardSteps.map((step, index) => {
                        const statusKind = pipelineStepStatusKind(step.status);
                        const progress = pipelineStepProgress(step);
                        return (
                          <li className="pipeline-step-card-item" key={step.name}>
                            <article className={`pipeline-step-card step-${statusKind}`}>
                              <header>
                                <span className="pipeline-step-number">{index + 1}</span>
                                <strong>{pipelineStepLabel(step.name, t)}</strong>
                                <span className={`pipeline-step-status step-${statusKind}`}>
                                  {statusKind === "completed" ? <CheckCircle2 size={13} /> : statusKind === "failed" ? <AlertTriangle size={13} /> : <Clock3 size={13} />}
                                  {pipelineStepStatusLabel(step.status, t)}
                                </span>
                              </header>
                              <div className="pipeline-step-progress" aria-label={format("projectImportPipelineStepPercentAria", { step: pipelineStepLabel(step.name, t), percent: progress })}>
                                <span style={{ width: `${progress}%` }} />
                              </div>
                              <div className="pipeline-step-meta">
                                <span>{format("projectImportRetryCount", { count: step.retryCount })}</span>
                                {step.artifactRef ? <span className="pipeline-step-artifact">{step.artifactRef}</span> : null}
                              </div>
                              {step.error ? <p className="pipeline-step-error"><AlertTriangle size={14} /> {localize(step.error)}</p> : null}
                            </article>
                            {index < cardSteps.length - 1 ? <span className="pipeline-step-arrow" aria-hidden="true"><ArrowRight size={16} /></span> : null}
                          </li>
                        );
                      })}
                    </ol>
                  </details>
                ) : null}
                </>}
              </div>
            </article>
            );
          })}
        </div>
        {visibleDocuments.length === 0 ? (
          <div className="empty-state">{t("projectImportNoMatchingDocuments")}</div>
        ) : null}
      </Panel>

      {activeModal ? (
        <div className="modal-backdrop" role="presentation">
          <section aria-modal="true" className={`modal-panel project-feature-modal ${activeModal === "chat" ? "project-chat-modal" : "project-graph-modal"}`} role="dialog">
            <div className="modal-header">
              <div>
                <p className="eyebrow">{t("projectImportFeatureEyebrow")}</p>
                <h2>{activeModal === "graph" ? t("knowledgeGraph") : t("chatTest")}</h2>
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
              <ProjectChatTest />
            )}
          </section>
        </div>
      ) : null}

      {uploadModalOpen ? <UploadFilesModal initialFiles={initialUploadFiles} maxUploadBytes={maxUploadSizeMb * 1024 * 1024} ocrModels={ocrModels} onClose={closeUploadModal} onCreate={addUploadedDocuments} onRetryPipeline={retryUploadModalPipeline} onUploadFiles={uploadLiveDocuments} /> : null}
      {dataServiceModalOpen ? <DataServiceModal onClose={() => setDataServiceModalOpen(false)} onCreate={addDataServiceDocument} onCreateDataSource={createLiveDataSource} onTestConnection={testLiveDataSource} /> : null}
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

      {permissionModalOpen && canManageProjectPermissions ? (
        <div className="modal-backdrop" role="presentation">
          <section aria-labelledby="project-permissions-title" aria-modal="true" className="modal-panel project-permission-modal" role="dialog">
            <div className="modal-header">
              <div className="modal-title-row">
                <span className="modal-title-icon"><UserRoundCog size={20} /></span>
                <div>
                  <p className="eyebrow">{project?.name ?? t("projectImportFallbackProjectTitle")}</p>
                  <h2 id="project-permissions-title">{t("projectImportPermissionManagement")}</h2>
                </div>
              </div>
              <button className="icon-button" onClick={() => setPermissionModalOpen(false)} type="button" aria-label={t("projectImportClosePermissionModal")}>
                <X size={18} />
              </button>
            </div>
            {permissionError ? <div className="error-summary" role="alert"><strong>{projectImportErrorMessage(permissionError, t, format)}</strong><button className="text-link" onClick={loadProjectPermissions} type="button">{t("retry")}</button></div> : null}
            {permissionLoading ? <div className="empty-state compact" role="status"><Clock3 size={24} /><p>{t("loadingData")}</p></div> : (
              <div className="project-permission-body">
                <section className="create-section project-permission-section">
                  <div className="create-section-title"><UserRoundCog size={18} /><h3>{t("projectsOwnersAndMembers")}</h3></div>
                  {!canManageProjectPermissions ? <div className="permission-note locked"><AlertTriangle size={16} /> {t("projectImportPermissionOwnerOnly")}</div> : null}
                  <div className="member-search">
                    <ProjectMemberAutocomplete
                      candidates={filteredPermissionUsers}
                      disabled={!canManageProjectPermissions || Boolean(permissionSavingUserId || permissionRemovingUserId)}
                      id="project-permission-user-search"
                      label={t("projectsSearchUsers")}
                      locale={locale}
                      onQueryChange={setPermissionQuery}
                      onSelect={stagePermissionCandidate}
                      placeholder={t("projectsSearchUsersPlaceholder")}
                      statusMessage={permissionSearchMessage}
                      value={permissionQuery}
                    />
                    <button className="action-button secondary" disabled={!canManageProjectPermissions || !pendingPermissionUsers.length || Boolean(permissionSavingUserId || permissionRemovingUserId)} onClick={() => { void commitPendingPermissionCandidates(); }} type="button"><UserPlus size={16} /> {t("projectsAddMember")}</button>
                    {pendingPermissionUsers.length ? (
                      <div className="project-permission-selected-users">
                        {pendingPermissionUsers.map((user) => (
                          <span className="project-permission-selected-user" key={user.id}>
                            {formatPersonName(user, locale)}
                            <button aria-label={t("projectImportRemovePendingMember")} onClick={() => setPendingPermissionUsers((current) => current.filter((item) => item.id !== user.id))} type="button">
                              <X size={13} />
                            </button>
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                  <div aria-label={t("projectsMemberRolesAria")} className="role-tabs" role="tablist">{projectMemberRoles.map((role) => <button aria-selected={activePermissionRole === role.id} className={activePermissionRole === role.id ? "role-tab active" : "role-tab"} key={role.id} onClick={() => { setPendingPermissionUsers([]); setActivePermissionRole(role.id); }} role="tab" type="button">{permissionRoleLabel(role.id)}<span>{projectMembers.filter((member) => member.roles.includes(role.id)).length}</span></button>)}</div>
                  <div className="project-permission-member-list">
                    {membersForActiveRole.map((member) => {
                      const currentRole = member.roles.find((role): role is ProjectMemberRole => projectMemberRoles.some((item) => item.id === role));
                      if (!currentRole) return null;
                      const busy = permissionSavingUserId === member.user_id || permissionRemovingUserId === member.user_id;
                      const protection = projectMemberOwnerProtection(member, projectMembers, currentUser?.user_id);
                      const protectionId = protection ? `project-member-protection-${member.user_id}` : undefined;
                      return (
                        <article className={protection ? "project-permission-member protected" : "project-permission-member"} key={member.user_id}>
                          <div>
                            <strong>{formatPersonName(member, locale)}</strong>
                            <small>{member.email ?? member.user_id}</small>
                            {protection ? <span className="project-permission-protection-reason" id={protectionId}><ShieldCheck size={13} />{t(protection === "last_owner" ? "projectImportLastOwnerProtected" : "projectImportSelfOwnerProtected")}</span> : null}
                          </div>
                          <ProjectMemberRoleSelector
                            describedBy={protectionId}
                            disabled={!canManageProjectPermissions || busy || Boolean(protection)}
                            label={t("projectsMemberRolesAria")}
                            memberId={member.user_id}
                            onChange={(role) => { void saveProjectMemberRole(member.user_id, role); }}
                            options={projectMemberRoles.map((role) => ({ id: role.id, label: permissionRoleLabel(role.id) }))}
                            role={currentRole}
                          />
                          {protection ? null : <button className="icon-button danger" disabled={!canManageProjectPermissions || busy} onClick={() => { void removeProjectPermissionMember(member.user_id); }} title={t("projectImportRemoveMember")} type="button" aria-label={t("projectImportRemoveMember")}><Trash2 size={17} /></button>}
                        </article>
                      );
                    })}
                    {!membersForActiveRole.length ? <div className="empty-state compact">{t("projectImportNoMembersInRole")}</div> : null}
                  </div>
                  <p className="field-note">{t("projectImportPermissionHelp")}</p>
                </section>
              </div>
            )}
            <div className="modal-actions"><button className="action-button secondary" onClick={() => setPermissionModalOpen(false)} type="button">{t("close")}</button></div>
          </section>
        </div>
      ) : null}

      {versionDocument ? (
        <div className="modal-backdrop" role="presentation">
          <section aria-modal="true" className="modal-panel version-modal" role="dialog">
            <div className="modal-header">
              <div>
                <p className="eyebrow">{versionDocument.title}</p>
                <h2>{t("projectImportVersionManagement")}</h2>
              </div>
              <button className="icon-button" onClick={() => setVersionDocumentId(null)} type="button" aria-label={t("projectImportCloseVersionModal")}>
                <X size={18} />
              </button>
            </div>
            <div className="current-version-card">
              <div className="current-version-primary">
                <span>{t("projectImportCurrentVersion")}</span>
                <strong>{normalizeVersion(versionDocument.version)}</strong>
                <StatusBadge status={versionDocument.versionStatus} />
              </div>
              <div className="current-version-roles">
                {versionDocument.versions.find((version) => version.status === "active") ? <span className="version-role-active"><CheckCircle2 size={14} /> {t("statusActive")}：{versionDocument.versions.find((version) => version.status === "active")?.label}</span> : null}
                {versionDocument.versions.find((version) => isWorkingVersion(version.status)) ? <span className="version-role-working"><Clock3 size={14} /> {t("projectImportWorkingVersion")}：{versionDocument.versions.find((version) => isWorkingVersion(version.status))?.label}</span> : null}
              </div>
            </div>
            {versionUpdateNotice ? <div className="reference-result compact"><CheckCircle2 size={18} /><span><strong>{localize(versionUpdateNotice)}</strong></span></div> : null}
            {versionUpdateError ? <div className="error-summary" role="alert"><strong>{localize(versionUpdateError)}</strong></div> : null}
            {versionDocument.sourceType === "File upload" ? (
              <div className="version-update-action">
                <div><strong>{t("projectImportUpdateDocument")}</strong><small>{t("projectImportUpdateDocumentHelp")}</small></div>
                <input
                  ref={updateFileInputRef}
                  className="sr-only"
                  onChange={(event) => { void updateCurrentFileVersion(event.target.files?.[0]); }}
                  type="file"
                />
                <button className="action-button secondary" disabled={versionUpdateBusy} onClick={() => updateFileInputRef.current?.click()} type="button">
                  <UploadCloud size={16} /> {versionUpdateBusy ? t("projectImportSubmitting") : t("projectImportChooseUpdateFile")}
                </button>
              </div>
            ) : null}
            {isServiceDocument(versionDocument) ? <div className="version-sync-action"><div><FolderSync size={18} /><span><strong>{t("projectImportDataServiceSync")}</strong><small>{t("projectImportDataServiceSyncHelp")}</small></span></div><button className="action-button secondary" disabled={getSourceState(versionDocument) === "syncing"} onClick={() => syncNow(versionDocument)} type="button"><FolderSync size={16} /> {getSourceState(versionDocument) === "syncing" ? t("projectImportSyncingEllipsis") : t("syncNow")}</button></div> : null}
            {"serviceSource" in versionDocument && versionDocument.serviceSource ? <div className="service-refresh-detail"><span>{t("projectImportServiceSource")}：{versionDocument.serviceSource.serviceType}</span><span>{t("projectImportServiceLocation")}：{versionDocument.serviceSource.location}</span><span>{t("projectImportServiceSchedule")}：{versionDocument.serviceSource.scheduleMode === "cron" ? `${versionDocument.serviceSource.cronExpression} · ${versionDocument.serviceSource.timezone}` : t("projectImportOneTime")}</span></div> : null}
            {versionDataSourceId ? (
              <>
                <div className="version-list-heading">
                  <strong>{t("projectImportSyncHistory")}</strong>
                  <button className="text-link" disabled={syncRunLoading[versionDataSourceId]} onClick={() => { void refreshDataSourceSyncRuns(versionDataSourceId); }} type="button">
                    <RotateCcw size={15} /> {syncRunLoading[versionDataSourceId] ? t("projectImportRefreshing") : t("projectImportRefresh")}
                  </button>
                </div>
                <div className="version-list">
                  {currentSyncRuns.length > 0 ? currentSyncRuns.slice(0, 5).map((run) => (
                    <article className="version-row" key={run.id}>
                      <div>
                        <strong>{syncRunLabel(run.status, t)} · {run.trigger_type === "scheduled" ? t("projectImportScheduled") : t("projectImportManual")}</strong>
                        <small>{syncRunStep(run, t)} · {formatSyncDate(run.completed_at ?? run.started_at ?? run.created_at, locale)}</small>
                      </div>
                      <StatusBadge status={run.status === "success" || run.status === "unchanged" ? "completed" : run.status === "failed" ? "failed" : "running"} />
                    </article>
                  )) : (
                    <div className="empty-state">{syncRunLoading[versionDataSourceId] ? t("projectImportLoadingSyncRuns") : t("projectImportNoSyncRuns")}</div>
                  )}
                </div>
              </>
            ) : null}
            {versionReferenceSource ? (
              <div className="reference-source-detail">
                <div className="reference-source-heading"><Layers3 size={17} /><span><strong>{t("projectImportReferenceSource")}</strong><small>{versionReferenceSource.hasAccess ? t("projectImportReferenceSourceAccessible") : t("projectImportReferenceSourceSnapshot")}</small></span></div>
                <dl><div><dt>{t("projectImportReferenceProject")}</dt><dd>{versionReferenceSource.projectName}</dd></div><div><dt>{t("projectImportReferenceDocument")}</dt><dd>{versionReferenceSource.documentName}</dd></div><div><dt>{t("projectImportCurrentReferenceVersion")}</dt><dd>{versionReferenceSource.snapshotVersion}</dd></div><div><dt>{t("projectImportLatestActive")}</dt><dd>{versionReferenceSource.latestActiveVersion}</dd></div><div><dt>{t("projectImportReferenceEvents")}</dt><dd>{versionReferenceSource.pendingEventCount ?? 0}</dd></div></dl>
              </div>
            ) : null}
            {versionReferenceSource?.referenceId ? (
              <div className="version-sync-action">
                <div><Layers3 size={18} /><span><strong>{t("projectImportReferenceUpdateVersion")}</strong><small>{t("projectImportReferenceUpdateVersionHelp")}</small></span></div>
                <div className="version-reference-update-controls">
                  <select
                    disabled={!versionReferenceSource.hasAccess || referenceUpdateLoading || versionUpdateBusy}
                    onChange={(event) => {
                      setReferenceUpdateVersionId(event.target.value);
                      setReferenceUpdateOldConfirmed(false);
                    }}
                    value={referenceUpdateVersionId}
                  >
                    <option value="">{referenceUpdateLoading ? t("loadingData") : t("projectImportSelectReferenceVersion")}</option>
                    {referenceUpdateVersions.map((version) => <option key={version.id} value={version.id}>{version.version_label} · {version.status}</option>)}
                  </select>
                  {referenceUpdateVersions.find((version) => version.id === referenceUpdateVersionId)?.status !== "active" && referenceUpdateVersionId ? (
                    <label className="field-note reference-old-confirm">
                      <input checked={referenceUpdateOldConfirmed} onChange={(event) => setReferenceUpdateOldConfirmed(event.target.checked)} type="checkbox" />
                      {t("projectImportReferenceOldVersionConfirm")}
                    </label>
                  ) : null}
                  <button className="action-button secondary" disabled={!versionReferenceSource.hasAccess || !referenceUpdateVersionId || versionUpdateBusy} onClick={() => { void updateCurrentReferenceVersion(); }} type="button"><RotateCcw size={16} /> {versionUpdateBusy ? t("projectImportSubmitting") : t("projectImportUpdateReference")}</button>
                </div>
              </div>
            ) : null}
            {versionReferenceSource?.pendingEventCount ? <div className="reference-version-alert"><AlertTriangle size={17} /><span><strong>{format("projectImportReferencePendingEvents", { count: versionReferenceSource.pendingEventCount })}</strong><small>{t("projectImportReferencePendingEventsHelp")}</small></span></div> : null}
            {versionReferenceSource && !versionReferenceSource.pendingEventCount && versionReferenceSource.latestActiveVersion !== versionReferenceSource.snapshotVersion ? <div className="reference-version-alert"><AlertTriangle size={17} /><span><strong>{t("projectImportReferenceNewVersionTitle")}</strong><small>{format("projectImportReferenceNewVersionHelp", { snapshot: versionReferenceSource.snapshotVersion, latest: versionReferenceSource.latestActiveVersion })}</small></span></div> : null}
            <div className="version-list-heading"><strong>{t("projectImportVersionHistory")}</strong><small>{t("projectImportVersionHistoryHelp")}</small></div>
            <div className="version-list">
              {displayedVersions.map((version) => {
                const activeVersion = version.status === "active";
                const switchableVersion = version.status === "inactive";
                const canSwitchVersion = canEditLifecycle && switchableVersion;
                return (
                  <article className="version-row" key={version.id}>
                    <div>
                      <strong>{version.label}</strong>
                      <small>{version.createdAt} · {version.author}</small>
                    </div>
                    <StatusBadge status={version.status} />
                    <button
                      className="action-button secondary"
                      disabled={!canSwitchVersion || versionSwitchBusy}
                      onClick={() => requestVersionSwitch(version)}
                      title={!canEditLifecycle ? t("projectImportMissingLifecyclePermission") : !switchableVersion && !activeVersion ? t("projectImportVersionSwitchBlocked") : undefined}
                      type="button"
                    >
                      {activeVersion ? t("projectImportCurrentVersionBadge") : canSwitchVersion ? t("projectImportSwitchActiveVersion") : t("projectImportVersionSwitchBlocked")}
                    </button>
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      ) : null}

      {versionSwitchTarget ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !versionSwitchBusy) setVersionSwitchTarget(null);
          }}
          role="presentation"
        >
          <section aria-labelledby="version-switch-title" aria-modal="true" className="modal-panel warning-modal" role="alertdialog">
            <div className="modal-header">
              <div><p className="eyebrow">{versionSwitchTarget.document.title}</p><h2 id="version-switch-title">{t("projectImportSwitchActiveTitle")}</h2></div>
              <button aria-label={t("projectImportCloseVersionSwitchWarning")} className="icon-button" disabled={versionSwitchBusy} onClick={() => setVersionSwitchTarget(null)} type="button"><X size={18} /></button>
            </div>
            <div className="warning-body"><ListRestart size={24} /><div><strong>{versionSwitchTarget.version.label}</strong><small>{t("projectImportSwitchActiveHelp")}</small></div></div>
            {versionSwitchError ? <div className="error-summary" role="alert"><AlertTriangle size={15} /> {localize(versionSwitchError)}</div> : null}
            <label className="field-stack">
              <span>{t("projectImportSwitchActiveReason")}</span>
              <textarea disabled={versionSwitchBusy} onChange={(event) => setVersionSwitchReason(event.target.value)} value={versionSwitchReason} />
            </label>
            <div className="modal-actions">
              <button className="action-button secondary" disabled={versionSwitchBusy} onClick={() => setVersionSwitchTarget(null)} type="button">{t("cancel")}</button>
              <button className="action-button" disabled={versionSwitchBusy || !versionSwitchReason.trim()} onClick={() => { void confirmVersionSwitch(); }} type="button">{versionSwitchBusy ? t("projectImportSubmitting") : t("projectImportConfirmSwitchActive")}</button>
            </div>
          </section>
        </div>
      ) : null}

      {pendingStatusChange ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !statusSubmitting) setPendingStatusChange(null);
          }}
          role="presentation"
        >
          <section aria-labelledby="status-change-title" aria-modal="true" className="modal-panel warning-modal" role="alertdialog">
            <div className="modal-header">
              <div><p className="eyebrow">{t("projectImportImpactWarning")}</p><h2 id="status-change-title">{pendingStatusChange.to === "inactive" ? t("projectImportDisableDocument") : t("projectImportDeleteDocument")}</h2></div>
              <button aria-label={t("projectImportCloseLifecycleWarning")} className="icon-button" disabled={statusSubmitting} onClick={() => setPendingStatusChange(null)} type="button"><X size={18} /></button>
            </div>
	            <div className="warning-body"><AlertTriangle size={24} /><div><strong>{pendingStatusChange.documentTitle}</strong><small>{t("projectImportLifecycleWarningHelp")}</small></div></div>
	            {statusError ? <div className="error-summary" role="alert"><AlertTriangle size={15} /> {localize(statusError)}</div> : null}
	            <div className="status-change-preview">
              <span><small>{t("projectImportCurrentStatus")}</small><strong>{documentStatusLabel(pendingStatusChange.from, t)}</strong></span>
              <ArrowRight size={18} />
              <span><small>{t("projectImportPendingStatus")}</small><strong>{documentStatusLabel(pendingStatusChange.to, t)}</strong></span>
            </div>
            <div className="impacted-projects">
              {pendingStatusChange.projects.length ? pendingStatusChange.projects.map((project) => <span key={project}>{project}</span>) : <span>{t("projectImportNoReferenceProjects")}</span>}
            </div>
            <div className="modal-actions"><button className="action-button secondary" disabled={statusSubmitting} onClick={() => setPendingStatusChange(null)} type="button">{t("cancel")}</button><button className="action-button danger" disabled={statusSubmitting} onClick={confirmStatusChange} type="button">{statusSubmitting ? t("projectImportSubmitting") : t("projectImportConfirmContinue")}</button></div>
          </section>
        </div>
      ) : null}
    </AppShell>
  );
}
