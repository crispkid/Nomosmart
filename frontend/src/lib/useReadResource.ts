"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type ReadState<T> = { scope: unknown; load: (signal: AbortSignal) => Promise<T>; data: T | null; status: "loading" | "ready" | "error"; error: unknown };

export type ReadResourceOptions<T> = {
  /** Keep the last committed data (and show it) while a newer read for the same scope runs or fails. */
  keepData?: boolean;
  /** Called once per committed read, after the data is stored; use it to sync dependent state. */
  onData?: (data: T) => void;
  /** Called once per current read that fails (automatic or explicit). */
  onError?: (error: unknown) => void;
  /** Called synchronously when a read starts. */
  onStart?: () => void;
  /**
   * Polling: after each current read finishes (committed or failed), returns the delay in ms until the
   * next read, or null to stop. Re-evaluated when page visibility changes; never overlaps a read.
   */
  poll?: (result: { data: T } | { error: unknown }) => number | null;
};

/**
 * Read-only resources commit only while their identity and request are current. Each request gets
 * an AbortSignal that is aborted when a newer request starts or the component unmounts (OPT424-035).
 * `reload()` resolves to true when its result was committed. `refresh()` resolves to the committed
 * data, rejects with the error of a current failed read, and resolves to null when the read was
 * disabled or superseded.
 */
export function useReadResource<T>(load: (signal: AbortSignal) => Promise<T>, scope: unknown, enabled: boolean, options: ReadResourceOptions<T> = {}) {
  const [state, setState] = useState<ReadState<T> | null>(null);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const keepData = options.keepData ?? false;
  const onData = useRef(options.onData);
  const onError = useRef(options.onError);
  const onStart = useRef(options.onStart);
  const poll = useRef(options.poll);
  useEffect(() => { onData.current = options.onData; onError.current = options.onError; onStart.current = options.onStart; poll.current = options.poll; });
  const polling = useRef<{ timer: ReturnType<typeof setTimeout> | undefined; inFlight: boolean; last: { data: T } | { error: unknown } | null; reload: () => Promise<boolean> }>({ timer: undefined, inFlight: false, last: null, reload: async () => false });
  const schedulePoll = useCallback(() => {
    const state = polling.current;
    clearTimeout(state.timer);
    state.timer = undefined;
    if (!poll.current || !state.last || state.inFlight) return;
    const delay = poll.current(state.last);
    if (delay === null) return;
    state.timer = setTimeout(() => { void state.reload(); }, delay);
  }, []);
  // One read; resolves { committed } and rethrows the error of a current failed read.
  const run = useCallback(async (): Promise<{ committed: false } | { committed: true; data: T }> => {
    if (!enabled) return { committed: false };
    const request = ++generation.current;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    const same = (value: ReadState<T> | null): value is ReadState<T> => Boolean(value && value.scope === scope && value.load === load);
    setState((previous) => ({ scope, load, data: keepData && same(previous) ? previous.data : null, status: "loading", error: null }));
    clearTimeout(polling.current.timer);
    polling.current.inFlight = true;
    onStart.current?.();
    let data: T;
    try {
      data = await load(current.signal);
    } catch (error) {
      if (request !== generation.current) return { committed: false };
      setState((previous) => ({ scope, load, data: keepData && same(previous) ? previous.data : null, status: "error", error }));
      polling.current.inFlight = false;
      polling.current.last = { error };
      onError.current?.(error);
      schedulePoll();
      throw error;
    }
    if (request !== generation.current) return { committed: false };
    setState({ scope, load, data, status: "ready", error: null });
    polling.current.inFlight = false;
    polling.current.last = { data };
    onData.current?.(data);
    schedulePoll();
    return { committed: true, data };
  }, [enabled, load, scope, keepData, schedulePoll]);
  const refresh = useCallback(async (): Promise<T | null> => {
    const result = await run();
    return result.committed ? result.data : null;
  }, [run]);
  const reload = useCallback(async (): Promise<boolean> => {
    try { return (await run()).committed; }
    catch { return false; }
  }, [run]);
  useEffect(() => { polling.current.reload = reload; }, [reload]);
  useEffect(() => {
    let cancelled = false;
    const state = polling.current;
    queueMicrotask(() => { if (!cancelled) void reload(); });
    return () => {
      cancelled = true; generation.current += 1; controller.current?.abort(); controller.current = null;
      clearTimeout(state.timer); state.timer = undefined; state.inFlight = false; state.last = null;
    };
  }, [reload]);
  const polls = Boolean(options.poll);
  useEffect(() => {
    if (!polls) return;
    document.addEventListener("visibilitychange", schedulePoll);
    return () => document.removeEventListener("visibilitychange", schedulePoll);
  }, [polls, schedulePoll]);
  const current = enabled && state && state.scope === scope && state.load === load ? state : null;
  const update = useCallback((change: (data: T) => T) => {
    setState((value) => value && value.scope === scope && value.load === load && value.data !== null && (value.status === "ready" || keepData)
      ? { ...value, data: change(value.data) } : value);
  }, [scope, load, keepData]);
  return { data: current?.data ?? null, status: current?.status ?? "loading", error: current?.error, reload, refresh, update };
}
