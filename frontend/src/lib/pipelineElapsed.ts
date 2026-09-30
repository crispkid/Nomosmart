/** Display only: never writes timestamps, advances progress or polls a service. */
export type PipelineTimes = { startedAt?: string | null; completedAt?: string | null };
export type ElapsedPipeline = PipelineTimes & {
  id?: string | null;
  status: string;
  observationInterrupted?: boolean;
  execution?: { phase: string } | null;
};
export type ElapsedState = { kind: "unknown" } | { kind: "running" | "completed"; seconds: number };

/** Preserve explicit null; undefined means an older response omitted the field. */
export function pipelineTimeFields(source?: { started_at?: string | null; completed_at?: string | null }): PipelineTimes {
  return { startedAt: source?.started_at, completedAt: source?.completed_at };
}

function timestamp(value: string | null | undefined): number | null {
  if (typeof value !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute, second, , offsetHour, offsetMinute] = match;
  const days = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
  if (Number(month) < 1 || Number(month) > 12 || Number(day) < 1 || Number(day) > days
    || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59
    || Number(offsetHour ?? 0) > 23 || Number(offsetMinute ?? 0) > 59) return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
}

export function pipelineElapsed(pipeline: ElapsedPipeline, now: number, enabled = true): ElapsedState {
  if (!enabled || !pipeline.id || !Number.isFinite(now)) return { kind: "unknown" };
  const start = timestamp(pipeline.startedAt);
  if (start === null || start > now) return { kind: "unknown" };
  if (pipeline.completedAt !== null && pipeline.completedAt !== undefined) {
    const end = timestamp(pipeline.completedAt);
    return end === null || end < start || end > now ? { kind: "unknown" }
      : { kind: "completed", seconds: Math.floor((end - start) / 1000) };
  }
  const terminal = ["completed", "failed", "cancelled", "recovery_required", "cleanup_pending"].includes(pipeline.execution?.phase ?? "");
  if (pipeline.observationInterrupted || terminal || !["running", "processing"].includes(pipeline.status)) return { kind: "unknown" };
  return { kind: "running", seconds: Math.floor((now - start) / 1000) };
}

export function elapsedUnits(seconds: number): { minutes: number; seconds: number } {
  return { minutes: Math.floor(seconds / 60), seconds: seconds % 60 };
}
