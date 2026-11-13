"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CursorPage } from "./api";
import { ReadResource } from "./readResource";

type ListState<T> = {
  scope: unknown; load: (cursor?: string | null, signal?: AbortSignal) => Promise<CursorPage<T>>;
  items: T[]; cursor: string | null; hasMore: boolean; ready: boolean;
  loading: boolean; error: unknown;
};

export function useCursorList<T extends { id: string }>(load: ListState<T>["load"], scope: unknown, enabled: boolean) {
  const [state, setState] = useState<ListState<T> | null>(null);
  const requests = useRef({ generation: 0, busy: false });
  // OPT424-035: each page read runs through a ReadResource, so a newer read aborts the older request.
  const resource = useRef(new ReadResource<CursorPage<T>>());
  const read = useCallback(async (previous: ListState<T> | null) => {
    if (!enabled || (previous && requests.current.busy)) return;
    const generation = ++requests.current.generation;
    requests.current.busy = true;
    const base: ListState<T> = previous ?? { scope, load, items: [], cursor: null, hasMore: false, ready: false, loading: false, error: null };
    setState({ ...base, loading: true, error: null });
    try {
      const result = await resource.current.run((signal) => load(base.cursor, signal));
      if (!result.committed || generation !== requests.current.generation) return;
      const page = result.data;
      const rows = new Map(base.items.map((item) => [item.id, item]));
      page.items.forEach((item) => rows.set(item.id, item));
      setState({ ...base, items: [...rows.values()], cursor: page.next_cursor, hasMore: page.has_more, ready: true, loading: false, error: null });
    } catch (error) {
      if (generation === requests.current.generation) {
        const code = error && typeof error === "object" && "code" in error ? error.code : null;
        const restart = code === "cursor_scope_mismatch" || code === "cursor_invalid" || code === "cursor_expired";
        setState({ ...base, ...(restart ? { items: [], cursor: null, hasMore: false, ready: false } : {}), loading: false, error });
      }
    } finally {
      if (generation === requests.current.generation) requests.current.busy = false;
    }
  }, [enabled, load, scope]);
  const reload = useCallback(() => read(null), [read]);
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void reload(); });
    const requestState = requests.current;
    const reads = resource.current;
    return () => { cancelled = true; requestState.generation += 1; requestState.busy = false; reads.invalidate(); };
  }, [reload]);
  const current = enabled && state && state.scope === scope && state.load === load ? state : null;
  return {
    items: current?.items ?? [], ready: current?.ready ?? false, loading: current?.loading ?? true,
    error: current?.error, hasMore: current?.hasMore ?? false, reload,
    loadMore: () => current?.ready && current.hasMore && current.cursor ? read(current) : Promise.resolve()
  };
}
