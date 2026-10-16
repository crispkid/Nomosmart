"use client";

import { useLayoutEffect, useMemo, useState } from "react";
import { useGraphLayoutSession } from "@/components/GraphLayoutSession";
import type { GraphExplorerNode, GraphExplorerEdge } from "@/components/GraphExplorer";
import { countGraphLayout, getGraphLayoutCache, graphCacheBudget, isGraphLayoutSession, putGraphLayoutCache, registerGraphLayoutCancellation } from "./graphLayoutCache";
import { graphLayoutSnapshot, graphSourceDigest, validGraphPositions, type GraphPositions, type LayoutReply } from "./graphLayoutProtocol";
import { runtimeConfig } from "./runtimeConfig";

let requestId = 0;
export function useGraphLayout(nodes: GraphExplorerNode[], edges: GraphExplorerEdge[], scope?: string, binding?: string | null) {
  const owner = useGraphLayoutSession();
  const snapshot = useMemo(() => graphLayoutSnapshot(nodes, edges), [nodes, edges]);
  const geometry = JSON.stringify(snapshot);
  const identity = JSON.stringify([owner, scope, binding, geometry]);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{ identity: string; retry: number; positions: GraphPositions; failed: boolean } | null>(null);
  useLayoutEffect(() => {
    if (!snapshot.nodes.length || (scope && !binding)) return;
    let cancelled = false, settled = false;
    let worker: Worker | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let unregister = () => {};
    const current = () => !cancelled && (!owner || isGraphLayoutSession(owner));
    const dispose = () => { worker?.terminate(); worker = null; if (timer) clearTimeout(timer); timer = null; unregister(); };
    const cancel = () => { if (!settled && worker) countGraphLayout("cancelled"); cancelled = true; dispose(); };
    const fail = () => {
      if (!current()) return;
      settled = true; dispose(); countGraphLayout("failures");
      setResult({ identity, retry, positions: {}, failed: true });
    };
    const budget = graphCacheBudget(runtimeConfig());
    const cacheable = Boolean(owner && scope && binding && binding !== "unavailable");
    graphSourceDigest([scope, binding, snapshot]).then(key => {
      if (!current()) return;
      const cached = cacheable ? getGraphLayoutCache(owner!, key, budget) : null;
      if (cached) { settled = true; setResult({ identity, retry, positions: cached, failed: false }); return; }
      try {
        worker = new Worker(new URL("../workers/graphLayout.worker.ts", import.meta.url), { type: "module" });
        unregister = registerGraphLayoutCancellation(cancel);
        const id = ++requestId;
        worker.onmessage = ({ data }: MessageEvent<LayoutReply>) => {
          if (!current() || data.id !== id) return;
          if (!("positions" in data) || !validGraphPositions(data.positions, snapshot.nodes)) { fail(); return; }
          settled = true; dispose(); countGraphLayout("completed");
          if (cacheable) putGraphLayoutCache(owner!, key, data.positions, budget);
          setResult({ identity, retry, positions: data.positions, failed: false });
        };
        worker.onerror = event => { event.preventDefault(); fail(); };
        worker.onmessageerror = fail;
        timer = setTimeout(fail, 60000);
        worker.postMessage({ id, snapshot }); countGraphLayout("dispatched");
      } catch { fail(); }
    }).catch(fail);
    return cancel;
    // identity includes every ordered input. New object references alone must not restart work.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity, retry]);
  const currentResult = result?.identity === identity && result.retry === retry ? result : null;
  return { positions: currentResult?.positions ?? {}, state: !nodes.length ? "idle" as const : currentResult ? currentResult.failed ? "error" as const : "ready" as const : "pending" as const,
    retry: () => setRetry(value => value + 1), identity };
}
