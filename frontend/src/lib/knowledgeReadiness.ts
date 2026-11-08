import type { KnowledgeDetailResponse } from "./api";

export const KNOWLEDGE_READINESS_MAX_ATTEMPTS = 120;
export const KNOWLEDGE_READINESS_WINDOW_MS = 5 * 60 * 1000;
const completedStagingStates = new Set([
  "submission_ready", "pending_manager_review", "pending_owner_review", "approved",
  "publish_ready", "ready_to_publish", "completed", "review_rejected",
]);

const knowledgeDetailReadyStates = new Set([
  "submission_ready", "pending_manager_review", "pending_owner_review", "approved",
  "publish_ready", "ready_to_publish", "publishing", "production_indexing", "graph_syncing",
  "published_active", "published", "active", "completed", "review_rejected",
]);
const automaticExtractionSteps = [
  "upload_received", "parse_document", "ocr_extract", "generate_markdown", "split_paragraphs",
  "chunk_knowledge", "auto_tag", "build_embeddings", "build_staging_index", "build_graph_preview",
  "prepare_submission",
];
const governanceWaitingVersions: Record<string, string> = {
  manager_review: "pending_manager_review", owner_review: "pending_owner_review", publish: "approved",
};

/** Governance waiting follows completed extraction; it never grants editing permission. */
function hasCompletedGovernanceWait(detail: KnowledgeDetailResponse): boolean {
  const pipeline = detail.pipeline;
  if (!pipeline || pipeline.status !== "waiting_action"
    || !pipeline.current_step_name || governanceWaitingVersions[pipeline.current_step_name] !== detail.version.status
    || pipeline.project_id !== detail.document.project_id || pipeline.document_id !== detail.document.id
    || pipeline.document_version_id !== detail.version.id || pipeline.steps.some(step => step.status === "failed")) return false;
  const required = pipeline.run_type === "document_extraction" ? automaticExtractionSteps
    : pipeline.run_type === "document_content_update" ? ["generate_markdown", "parse_structure", "auto_tag", "embedding", "staging_index", "build_graph_preview", "cleanup_superseded"] : null;
  return Boolean(required && required.every(name => {
    const steps = pipeline.steps.filter(step => step.step_name === name);
    return steps.length === 1 && steps[0].status === "completed";
  }));
}

export function completionGateBlocksKnowledgeDetail(detail: KnowledgeDetailResponse | null): boolean {
  return Boolean(detail?.pipeline && !knowledgeDetailReadyStates.has(detail.pipeline.status)
    && !hasCompletedGovernanceWait(detail));
}

/** A read can be repeated without granting access or claiming the cause is transient. */
export function needsKnowledgeReadinessCheck(detail: KnowledgeDetailResponse | null): boolean {
  return Boolean(detail && detail.pipeline && (completedStagingStates.has(detail.pipeline.status) || hasCompletedGovernanceWait(detail))
    && completedStagingStates.has(detail.version.status)
    && !detail.pipeline.steps.some((step) => step.status === "failed")
    // Unpublished documents are "inactive"; this is not an archived project.
    && !["deleted", "archived"].includes(detail.document.status)
    && detail.active_chunk_count > 0 && detail.chunk_artifact_status === "failed"
    && detail.next_stage_allowed === false && detail.next_stage_block_reason === "vector_index_not_ready"
    && detail.chat_access?.mode !== "published");
}

export function knowledgeReadinessKey(userId: string, projectId: string, documentId: string,
  detail: KnowledgeDetailResponse | null): string | null {
  if (!userId || !detail?.version.id || !detail.pipeline?.id || detail.document.project_id !== projectId
    || detail.document.id !== documentId || detail.pipeline.project_id !== projectId
    || detail.pipeline.document_id !== documentId || detail.pipeline.document_version_id !== detail.version.id) return null;
  return JSON.stringify([userId, projectId, documentId, detail.version.id, detail.pipeline.id]);
}

export function readinessBudgetExhausted(attempts: number, elapsedMs: number): boolean {
  return attempts >= KNOWLEDGE_READINESS_MAX_ATTEMPTS || elapsedMs >= KNOWLEDGE_READINESS_WINDOW_MS;
}

export function acceptsKnowledgeRead(userId: string, projectId: string, documentId: string,
  before: KnowledgeDetailResponse | null, current: KnowledgeDetailResponse | null, next: KnowledgeDetailResponse): boolean {
  if (!before || !current || next.document.id !== documentId || next.document.project_id !== projectId
    || current.document.id !== documentId || current.document.project_id !== projectId
    || next.version.id !== before.version.id || next.pipeline?.id !== before.pipeline?.id
    || current.version.id !== before.version.id || current.pipeline?.id !== before.pipeline?.id
    || next.version.lock_version < current.version.lock_version) return false;
  if (!before.pipeline) return true;
  const key = knowledgeReadinessKey(userId, projectId, documentId, before);
  return Boolean(key && knowledgeReadinessKey(userId, projectId, documentId, next) === key
    && knowledgeReadinessKey(userId, projectId, documentId, current) === key);
}

/** Mount-owned state survives effects/renders/visibility changes, not user or route ownership. */
export class KnowledgeReadinessBudget {
  private entries = new Map<string, { attempts: number; started: number; stopped: boolean }>();
  observe(key: string): void {
    if (!this.entries.has(key)) this.entries.set(key, { attempts: 0, started: performance.now(), stopped: false });
  }
  remainingMs(key: string): number {
    const entry = this.entries.get(key);
    return entry ? Math.max(0, KNOWLEDGE_READINESS_WINDOW_MS - (performance.now() - entry.started)) : 0;
  }
  exhausted(key: string): boolean {
    const entry = this.entries.get(key);
    return Boolean(entry && (entry.stopped || readinessBudgetExhausted(entry.attempts, performance.now() - entry.started)));
  }
  take(key: string): boolean {
    this.observe(key);
    if (this.exhausted(key)) return false;
    this.entries.get(key)!.attempts++;
    return true;
  }
  stop(key: string): void { this.observe(key); this.entries.get(key)!.stopped = true; }
}

/** One current read lease, with real cancellation and stale-completion exclusion. */
export class KnowledgeDetailReads {
  private pending: { scope: string; controller: AbortController } | null = null;
  begin(scope: string) {
    if (this.pending) return null;
    const entry = { scope, controller: new AbortController() };
    this.pending = entry;
    return {
      signal: entry.controller.signal,
      active: () => this.pending === entry && !entry.controller.signal.aborted,
      finish: () => { if (this.pending === entry) this.pending = null; },
      cancel: () => { entry.controller.abort(); if (this.pending === entry) this.pending = null; },
    };
  }
  cancel(): void { this.pending?.controller.abort(); this.pending = null; }
}
