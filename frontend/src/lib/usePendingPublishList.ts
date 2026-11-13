"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ApprovalPendingPublishPage, ApprovalPendingPublishResponse } from "./api";
import { ReadResource } from "./readResource";

type Load = (cursor?: string | null, signal?: AbortSignal) => Promise<ApprovalPendingPublishPage>;
type State = {
  scope: unknown; load: Load; items: ApprovalPendingPublishResponse[];
  total: number | null; cursor: string | null; hasMore: boolean;
  ready: boolean; loading: boolean; stale: boolean; error: unknown;
  failedPage: "first" | "more" | null;
};

/** A read-only, login-scoped list. Publication itself remains with the caller. */
export function usePendingPublishList(load: Load, scope: unknown, enabled: boolean) {
  const [state, setState] = useState<State | null>(null);
  const stored = useRef<State | null>(null);
  const requests = useRef({ generation: 0, busy: false });
  // OPT424-035: each page read runs through a ReadResource, so a newer read aborts the older request.
  const resource = useRef(new ReadResource<ApprovalPendingPublishPage>());
  const identity = useMemo(() => ({ load, scope, enabled }), [load, scope, enabled]);
  const lifecycle = useRef<typeof identity | null>(null);
  useLayoutEffect(() => {
    lifecycle.current = identity;
    const pending = requests.current;
    const reads = resource.current;
    return () => { lifecycle.current = null; pending.generation++; pending.busy = false; reads.invalidate(); };
  }, [identity]);

  const read = useCallback(async (previous: State | null, append: boolean) => {
    if (!enabled || lifecycle.current !== identity || (append && requests.current.busy)) return;
    if (append && (!previous?.hasMore || !previous.cursor)) return;
    const generation = ++requests.current.generation;
    requests.current.busy = true;
    const base: State = previous ?? {
      scope, load, items: [], total: null, cursor: null, hasMore: false,
      ready: false, loading: false, stale: false, error: null, failedPage: null,
    };
    const commit = (next: State) => { stored.current = next; setState(next); };
    commit({ ...base, loading: true, error: null, failedPage: null });
    try {
      const result = await resource.current.run((signal) => load(append ? base.cursor : null, signal));
      if (!result.committed || lifecycle.current !== identity || generation !== requests.current.generation) return;
      const page = result.data;
      const rows = new Map((append ? base.items : []).map(item => [item.document_version_id, item]));
      page.items.forEach(item => rows.set(item.document_version_id, item));
      commit({ ...base, items: [...rows.values()], total: page.total, cursor: page.next_cursor,
        hasMore: page.has_more, ready: true, loading: false, stale: false, error: null, failedPage: null });
    } catch (error) {
      if (lifecycle.current !== identity || generation !== requests.current.generation) return;
      const code = error && typeof error === "object" && "code" in error ? error.code : null;
      const restart = code === "cursor_scope_mismatch" || code === "cursor_invalid" || code === "cursor_expired";
      commit({ ...base, ...(restart ? { items: [], cursor: null, hasMore: false, ready: false } : {}),
        total: null, loading: false, stale: base.ready && !restart, error, failedPage: append && !restart ? "more" : "first" });
    } finally {
      if (lifecycle.current === identity && generation === requests.current.generation) requests.current.busy = false;
    }
  }, [enabled, identity, load, scope]);

  const reload = useCallback(() => {
    const previous = stored.current;
    return read(previous && previous.scope === scope && previous.load === load ? previous : null, false);
  }, [load, read, scope]);
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void reload(); });
    return () => { cancelled = true; };
  }, [reload]);

  const afterPublish = useCallback((versionId: string) => {
    if (lifecycle.current !== identity || !enabled) return Promise.resolve();
    requests.current.generation++;
    requests.current.busy = false;
    const current = stored.current;
    const remaining = current && current.scope === scope && current.load === load ? {
      ...current, items: current.items.filter(item => item.document_version_id !== versionId),
      total: null, stale: true, cursor: null, hasMore: false, error: null,
    } : null;
    return read(remaining, false);
  }, [enabled, identity, load, read, scope]);

  const current = enabled && state && state.scope === scope && state.load === load ? state : null;
  const loadMore = () => current?.ready ? read(current, true) : Promise.resolve();
  return {
    items: current?.items ?? [], total: current?.total ?? null, ready: current?.ready ?? false,
    loading: current?.loading ?? enabled, stale: current?.stale ?? false, error: current?.error,
    hasMore: current?.hasMore ?? false, reload, loadMore, afterPublish,
    retry: () => current?.failedPage === "more" ? loadMore() : reload(),
    isCurrent: () => lifecycle.current === identity && enabled,
  };
}
