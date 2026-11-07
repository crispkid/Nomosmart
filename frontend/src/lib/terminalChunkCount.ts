import type { CreatedKnowledgeDocument as Document } from "../components/KnowledgeSourceModals";
import type { DocumentSummary } from "./api";

export function needsTerminalChunkCount(document: Document): boolean {
  return Boolean(document.isLive && document.documentStatus !== "deleted" && document.latestVersionId
    && document.pipeline.id && document.versionStatus === "submission_ready"
    && document.pipeline.status === "submission_ready" && document.chunkCountRunId !== document.pipeline.id);
}

/** Count only; never replace progress, permission, governance or the whole list. */
export function terminalCountScopeMatches(current: Document, expected: Document): boolean {
  return needsTerminalChunkCount(current) && current.id === expected.id
    && current.latestVersionId === expected.latestVersionId && current.pipeline.id === expected.pipeline.id
    && current.documentStatus === expected.documentStatus && current.lockVersion === expected.lockVersion;
}

export function mergeTerminalChunkCount(current: Document, expected: Document, summary: DocumentSummary): Document {
  if (!terminalCountScopeMatches(current, expected) || summary.id !== current.id || summary.status !== current.documentStatus
    || summary.latest_version?.id !== current.latestVersionId || summary.latest_pipeline?.id !== current.pipeline.id
    || summary.latest_version?.status !== "submission_ready" || summary.latest_pipeline?.status !== "submission_ready") return current;
  const count = summary.latest_version.active_chunk_count;
  if (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0) return current;
  return { ...current, chunks: count, chunkCountRunId: current.pipeline.id! };
}

/** One automatic attempt per mount/run, with bounded explicit manual retries. */
export class TerminalCountAttempts {
  private attempted = new Set<string>();
  private pending = new Set<string>();
  begin(key: string, manual = false): boolean {
    if (this.pending.has(key) || (!manual && this.attempted.has(key))) return false;
    this.attempted.add(key); this.pending.add(key); return true;
  }
  finish(key: string): void { this.pending.delete(key); }
}
