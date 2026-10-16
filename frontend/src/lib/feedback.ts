import type { TranslationKey } from "./i18n";

export type FeedbackTone = "success" | "info" | "warning" | "error";
export type FeedbackMessage = {
  id: string;
  scope: string;
  tone: FeedbackTone;
  title: TranslationKey;
  reason?: TranslationKey;
  params?: Record<string, string | number>;
  critical?: boolean;
};
export type FeedbackRecord = FeedbackMessage & { createdAt: number };

let failureSink: ((message: FeedbackMessage) => void) | undefined;
export function registerFeedbackFailures(sink: (message: FeedbackMessage) => void) {
  failureSink = sink;
  return () => { if (failureSink === sink) failureSink = undefined; };
}
/** Capture the initiating session; an old request cannot publish into a new login. */
export function feedbackFailureReporter() {
  const sink = typeof window === "undefined" ? undefined : failureSink;
  return (unknown: boolean) => sink?.({ id: crypto.randomUUID(), scope: "operation", tone: unknown ? "warning" : "error",
    title: unknown ? "feedbackWarningTitle" : "feedbackErrorTitle", reason: unknown ? "feedbackResultUnknown" : "feedbackCheckContext" });
}

/** Values used by public UI messages, never arbitrary server/exception payloads. */
export function safeFeedback(message: FeedbackMessage): FeedbackMessage {
  const params: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(message.params ?? {})) {
    if (/^(count|completed|total|limit|seconds|version|requestId)$/.test(key) &&
        ((typeof value === "number" && Number.isFinite(value)) ||
         (typeof value === "string" && /^[A-Za-z0-9_.:/ -]{1,80}$/.test(value)))) params[key] = value;
  }
  return { id: message.id, scope: message.scope, tone: message.tone, title: message.title,
    reason: message.reason, critical: message.critical, params };
}

export function recordFeedback(records: FeedbackRecord[], message: FeedbackMessage, limit: number, now: number): FeedbackRecord[] {
  const safe = safeFeedback(message);
  const previous = records.find(item => item.id === safe.id && item.scope === safe.scope);
  return [{ ...safe, createdAt: previous?.createdAt ?? now },
    ...records.filter(item => item.id !== safe.id || item.scope !== safe.scope)].slice(0, limit);
}

export type FeedbackSettings = { toastDurationMs: number; toastVisibleLimit: number; recentLimit: number };
export function feedbackInteger(value: string | number | undefined, fallback: number, min: number, max: number): number {
  if (value === undefined) return fallback;
  if ((typeof value === "string" && !/^\d+$/.test(value)) || !Number.isInteger(Number(value)) || Number(value) < min || Number(value) > max)
    throw new Error("feedback_configuration_invalid");
  return Number(value);
}

export function feedbackSettings(config: { feedbackToastDurationMs?: number; feedbackToastVisibleLimit?: number; feedbackRecentLimit?: number }): FeedbackSettings {
  return { toastDurationMs: feedbackInteger(config.feedbackToastDurationMs, 5000, 3000, 20000),
    toastVisibleLimit: feedbackInteger(config.feedbackToastVisibleLimit, 2, 1, 3),
    recentLimit: feedbackInteger(config.feedbackRecentLimit, 20, 1, 100) };
}

export function createFeedbackStore(settings: FeedbackSettings, enabled: boolean) {
  let active = enabled;
  let snapshot: { recent: FeedbackRecord[]; queue: FeedbackMessage[] } = { recent: [], queue: [] };
  const listeners = new Set<() => void>();
  const seen = new Set<string>();
  const capacity = settings.recentLimit * 50;
  const publish = () => listeners.forEach(listener => listener());
  return {
    activate() { active = enabled; },
    dispose() { active = false; snapshot = { recent: [], queue: [] }; seen.clear(); },
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    snapshot() { return snapshot; },
    notify(message: FeedbackMessage, toast = true) {
      if (!active) return;
      const safe = safeFeedback(message), identity = JSON.stringify([safe.scope, safe.id]);
      const alreadySeen = seen.has(identity);
      seen.add(identity);
      if (seen.size > capacity) seen.delete(seen.values().next().value!);
      const overflow: FeedbackMessage = { id: "feedback-queue-capacity", scope: "session", tone: "info", title: "feedbackQueueFull" };
      const queue = alreadySeen ? snapshot.queue.map(item => item.id === safe.id && item.scope === safe.scope ? safe : item) : !toast ? snapshot.queue :
        snapshot.queue.length < capacity ? [...snapshot.queue, safe] : snapshot.queue.some(item => item.id === overflow.id) ? snapshot.queue : [...snapshot.queue.slice(0, capacity - 1), overflow];
      snapshot = { recent: recordFeedback(snapshot.recent, safe, settings.recentLimit, Date.now()),
        queue };
      publish();
    },
    dismiss(id: string, scope: string) {
      snapshot = { ...snapshot, queue: snapshot.queue.filter(item => item.id !== id || item.scope !== scope) }; publish();
    },
  };
}
