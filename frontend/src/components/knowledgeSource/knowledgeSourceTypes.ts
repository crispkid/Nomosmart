// Knowledge source document and service types shared by the import page and source modals (OPT424-038).
import { type OcrProgress } from "@/lib/ocrPresentation";

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
  | "review_rejected"
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
  extractionOutcome?: import("@/lib/reviewPresentation").ExtractionOutcome;
  hasActiveVersion?: boolean;
  sourceType: string;
  sourceState: SourceState;
  serviceSource?: ServiceSource;
  referenceSource?: ReferenceSource;
  chunks: number | null;
  /** Run whose terminal count was confirmed by the document summary. */
  chunkCountRunId?: string;
  updatedAt: string;
  impactedProjects: string[];
  versions: Array<{ id: string; label: string; status: string; createdAt: string; author: string; lockVersion?: number }>;
  pipeline: {
    id?: string | null;
    execution?: import("@/lib/api").PipelineExecution | null;
    status: PipelineStatus;
    progress: number;
    currentStep: string;
    waitingRole: string;
    elapsed: string;
    startedAt?: string | null;
    completedAt?: string | null;
    eta: string;
    error: string;
    steps?: Array<{ name: string; status: string; progress: number; retryCount: number; artifactRef?: string | null; error?: string | null; errorCode?: string | null; ocr?: OcrProgress }>;
    observationInterrupted?: boolean;
    cleanupObservationStopped?: boolean;
  };
};
