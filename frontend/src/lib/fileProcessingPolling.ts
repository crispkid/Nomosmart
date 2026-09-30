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

/** One request at a time; cleanup suppresses results from the previous route/run. */
export function startFileProcessingPolling<T>(options: {
  load: () => Promise<T>;
  value: (value: T) => void;
  error: (error: unknown) => void;
  execution: () => PipelineExecution | null | undefined;
  active: () => boolean;
}): () => void {
  let stopped = false;
  let inFlight = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const schedule = () => {
    if (stopped || inFlight || !options.active()) return;
    clearTimeout(timer);
    try {
      timer = setTimeout(tick, fileProcessingPollDelay(options.execution(), document.visibilityState === "hidden"));
    } catch (error) {
      stopped = true;
      options.error(error);
    }
  };
  const tick = async () => {
    if (stopped || inFlight || !options.active()) return;
    inFlight = true;
    try {
      const next = await options.load();
      if (!stopped) options.value(next);
    } catch (error) {
      if (!stopped) {
        if (isPollingAuthorizationFailure(error)) stopped = true;
        options.error(error);
      }
    } finally {
      inFlight = false;
      schedule();
    }
  };
  document.addEventListener("visibilitychange", schedule);
  schedule();
  return () => {
    stopped = true;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", schedule);
  };
}
