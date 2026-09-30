import type { CreatedKnowledgeDocument as Document } from "../components/KnowledgeSourceModals";

/** Existing Modal observation bound, also applied to post-extraction cleanup. */
export const FILE_EXTRACTION_OBSERVATION_LIMIT = 120;
const activeExecutionPhases = new Set(["queued", "starting_parser", "parsing", "waiting_worker", "processing", "stopping"]);
const terminalExecutionPhases = new Set(["completed", "failed", "cancelled", "recovery_required"]);

function filePipeline(document: Document): boolean {
  return Boolean(document.isLive && document.sourceType === "File upload"
    && document.documentStatus !== "deleted" && document.sourceState === "pipeline");
}

/** Only extraction terminals, never review/publication, may observe cleanup. */
export function hasExtractionTerminal(document: Document): boolean {
  return filePipeline(document) && ["submission_ready", "failed"].includes(document.versionStatus)
    && document.pipeline.status === document.versionStatus;
}

function validCleanupExecution(document: Document): boolean {
  const execution = document.pipeline.execution;
  return Boolean(execution && activeExecutionPhases.has(execution.phase)
    && Number.isInteger(execution.attempt) && execution.attempt >= 1
    && Number.isInteger(execution.progress_revision) && execution.progress_revision >= 0
    && Number.isInteger(execution.poll_interval_seconds) && execution.poll_interval_seconds >= 1 && execution.poll_interval_seconds <= 60
    && Number.isInteger(execution.background_poll_interval_seconds)
    && execution.background_poll_interval_seconds >= execution.poll_interval_seconds
    && execution.background_poll_interval_seconds <= 300);
}

export function fileObservationMode(document: Document): "extraction" | "cleanup" | null {
  if (observesFileExtraction(document)) return "extraction";
  return hasExtractionTerminal(document) && validCleanupExecution(document)
    && !document.pipeline.cleanupObservationStopped ? "cleanup" : null;
}

export function cleanupIsUnconfirmed(document: Document): boolean {
  const execution = document.pipeline.execution;
  // Old null-execution contracts have no new cleanup claim to make.
  return hasExtractionTerminal(document) && Boolean(execution)
    && !terminalExecutionPhases.has(execution!.phase)
    && Boolean(document.pipeline.observationInterrupted || document.pipeline.cleanupObservationStopped || !validCleanupExecution(document));
}

/** Mount-scoped budget survives renders, visibility changes and Modal pauses. */
export class CleanupObservationBudget {
  private attempts = new Map<string, number>();
  take(key: string): boolean {
    const used = this.attempts.get(key) ?? 0;
    if (used >= FILE_EXTRACTION_OBSERVATION_LIMIT) return false;
    this.attempts.set(key, used + 1);
    return true;
  }
  exhausted(key: string): boolean { return (this.attempts.get(key) ?? 0) >= FILE_EXTRACTION_OBSERVATION_LIMIT; }
  clear(): void { this.attempts.clear(); }
}

/** Scope-keyed leases stop old GETs/timers BEFORE another observer takes over. */
export class PipelineObservationOwnership {
  readonly cleanupBudget = new CleanupObservationBudget();
  private owners = new Map<string, { owner: "modal" | "list"; controller: AbortController }>();
  acquire(key: string, owner: "modal" | "list") {
    this.owners.get(key)?.controller.abort();
    const entry = { owner, controller: new AbortController() };
    this.owners.set(key, entry);
    return {
      signal: entry.controller.signal,
      active: () => this.owners.get(key) === entry && !entry.controller.signal.aborted,
      release: () => {
        entry.controller.abort();
        if (this.owners.get(key) === entry) this.owners.delete(key);
      },
    };
  }
  releaseOwner(owner: "modal" | "list"): void {
    for (const [key, entry] of this.owners) {
      if (entry.owner !== owner) continue;
      entry.controller.abort();
      this.owners.delete(key);
    }
  }
  clear(): void { this.releaseOwner("modal"); this.releaseOwner("list"); this.cleanupBudget.clear(); }
}

/** Resolves on cancellation; caller checks its lease before starting more IO. */
export function observationDelay(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => { clearTimeout(timer); signal.removeEventListener("abort", finish); resolve(); };
    const timer = setTimeout(finish, ms);
    signal.addEventListener("abort", finish, { once: true });
  });
}

export function extractionRunKey(projectId: string, document: Document): string | null {
  return projectId && document.isLive && document.id && document.latestVersionId && document.pipeline.id
    ? JSON.stringify([projectId, document.id, document.latestVersionId, document.pipeline.id]) : null;
}

/** Publication/review and other source types are not file-extraction observers. */
export function observesFileExtraction(document: Document): boolean {
  return Boolean(filePipeline(document)
    && ["draft", "ready_for_extraction", "processing", "queued"].includes(document.versionStatus)
    && ["queued", "running", "processing"].includes(document.pipeline.status)
    && !document.extractionSuccessful && document.extractionOutcome !== "complete"
    && !document.pipeline.steps?.some((step) => step.status === "failed"));
}

/** A synchronous guard also closes the gap before React renders disabled buttons. */
export class ManualExtractionStarts {
  private sequence = 0;
  private pending = new Map<string, { token: number; versionId: string }>();
  private settled = new Set<string>();

  begin(documentId: string, versionId = ""): number | null {
    if (!documentId || this.pending.has(documentId) || this.settled.has(JSON.stringify([documentId, versionId]))) return null;
    const token = ++this.sequence;
    this.pending.set(documentId, { token, versionId });
    return token;
  }
  owns(documentId: string, token: number): boolean { return this.pending.get(documentId)?.token === token; }
  finish(documentId: string, token: number, confirmedOrUnknown = false): void {
    if (!this.owns(documentId, token)) return;
    const request = this.pending.get(documentId)!;
    this.pending.delete(documentId);
    if (confirmedOrUnknown) this.settled.add(JSON.stringify([documentId, request.versionId]));
  }
  invalidate(): void { this.pending.clear(); this.settled.clear(); }
}
