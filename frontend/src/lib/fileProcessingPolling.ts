import type { PipelineExecution } from "./api";

/** Old null-execution responses keep their existing UI cadence, not a DB fallback. */
export function fileProcessingPollDelay(execution?: PipelineExecution | null, background = false, legacyMs = 2500): number {
  if (!execution) return background ? 15000 : legacyMs;
  const foreground = execution.poll_interval_seconds;
  const interval = background ? execution.background_poll_interval_seconds : foreground;
  // Reject malformed new contracts: do not pretend another policy is effective.
  if (!Number.isInteger(foreground) || foreground < 1 || foreground > 60 ||
      !Number.isInteger(interval) || interval < foreground || interval > (background ? 300 : 60)) {
    throw new Error("file_processing_poll_contract_invalid");
  }
  return interval * 1000;
}

export function isPollingAuthorizationFailure(error: unknown): boolean {
  return typeof error === "object" && error !== null && "status" in error && (error.status === 401 || error.status === 403);
}
