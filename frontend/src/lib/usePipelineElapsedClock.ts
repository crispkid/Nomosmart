"use client";

import { useEffect, useState } from "react";
import { pipelineElapsed, type ElapsedPipeline } from "./pipelineElapsed";

/** One local clock for the list. Scope/visibility changes never reset Backend time. */
export function usePipelineElapsedClock(pipelines: ElapsedPipeline[], enabled: boolean, scope: string): number {
  const [now, setNow] = useState(() => Date.now());
  // Depend on clock-relevant fields, not on card/translation object identities.
  const key = JSON.stringify(pipelines.map(p => ({ id: p.id, status: p.status,
    startedAt: p.startedAt, completedAt: p.completedAt, observationInterrupted: p.observationInterrupted,
    execution: p.execution ? { phase: p.execution.phase } : null })));
  useEffect(() => {
    if (!enabled) return;
    const observed: ElapsedPipeline[] = JSON.parse(key);
    let timer: number | undefined;
    const clear = () => { window.clearTimeout(timer); timer = undefined; };
    const refresh = () => {
      clear();
      if (document.visibilityState === "hidden") return;
      const time = Date.now();
      setNow(time);
      if (observed.some(p => pipelineElapsed(p, time).kind === "running")) {
        timer = window.setTimeout(refresh, 1000);
      }
    };
    refresh();
    if (!observed.some(p => pipelineElapsed(p, Date.now()).kind === "running")) return clear;
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("pageshow", refresh);
    return () => {
      clear();
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("pageshow", refresh);
    };
  }, [key, enabled, scope]);
  return now;
}
