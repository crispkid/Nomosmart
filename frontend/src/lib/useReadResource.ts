"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type ReadState<T> = { scope: unknown; load: (signal: AbortSignal) => Promise<T>; data: T | null; status: "loading" | "ready" | "error"; error: unknown };

/**
 * Read-only resources commit only while their identity and request are current. Each request gets
 * an AbortSignal that is aborted when a newer request starts or the component unmounts (OPT424-035).
 */
export function useReadResource<T>(load: (signal: AbortSignal) => Promise<T>, scope: unknown, enabled: boolean) {
  const [state, setState] = useState<ReadState<T> | null>(null);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const reload = useCallback(async () => {
    if (!enabled) return;
    const request = ++generation.current;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setState({ scope, load, data: null, status: "loading", error: null });
    try {
      const data = await load(current.signal);
      if (request === generation.current) setState({ scope, load, data, status: "ready", error: null });
    } catch (error) {
      if (request === generation.current) setState({ scope, load, data: null, status: "error", error });
    }
  }, [enabled, load, scope]);
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void reload(); });
    return () => { cancelled = true; generation.current += 1; controller.current?.abort(); controller.current = null; };
  }, [reload]);
  const current = enabled && state && state.scope === scope && state.load === load ? state : null;
  const update = useCallback((change: (data: T) => T) => {
    setState((value) => value && value.scope === scope && value.load === load && value.status === "ready" && value.data !== null
      ? { ...value, data: change(value.data) } : value);
  }, [scope, load]);
  return { data: current?.data ?? null, status: current?.status ?? "loading", error: current?.error, reload, update };
}
