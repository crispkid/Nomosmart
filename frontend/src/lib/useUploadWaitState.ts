"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { uploadWaitNoticeMs } from "./uploadProgress";

type WaitAttempt = {
  id: number;
  waitMs: number;
  returnDeadline: number;
  progressDeadline: number;
  canReturn: boolean;
};
const idle = { canReturn: false, progressStalled: false };

/** UI waiting only. Never owns, cancels or retries the server operation. */
export function useUploadWaitState(waitNoticeMs: number) {
  const current = useRef<WaitAttempt | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const mounted = useRef(false);
  const [state, setState] = useState(idle);

  const clearTimer = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
  }, []);

  const refresh = useCallback(function refreshWait() {
    clearTimer();
    const attempt = current.current;
    if (!mounted.current || !attempt) return;
    const now = performance.now();
    attempt.canReturn ||= now >= attempt.returnDeadline;
    const next = { canReturn: attempt.canReturn, progressStalled: now >= attempt.progressDeadline };
    setState(previous => previous.canReturn === next.canReturn && previous.progressStalled === next.progressStalled ? previous : next);
    // Progress may move its own deadline, never the attempt's return deadline.
    const deadline = Math.min(attempt.canReturn ? Infinity : attempt.returnDeadline, next.progressStalled ? Infinity : attempt.progressDeadline);
    if (Number.isFinite(deadline)) {
      timer.current = window.setTimeout(() => {
        if (current.current === attempt && mounted.current) refreshWait();
      }, Math.max(1, Math.ceil(deadline - now)));
    }
  }, [clearTimer]);

  const begin = useCallback((id: number) => {
    const waitMs = uploadWaitNoticeMs(waitNoticeMs);
    const deadline = performance.now() + waitMs;
    current.current = { id, waitMs, returnDeadline: deadline, progressDeadline: deadline, canReturn: false };
    refresh();
  }, [refresh, waitNoticeMs]);

  const progress = useCallback((id: number) => {
    const attempt = current.current;
    if (!attempt || attempt.id !== id) return;
    attempt.progressDeadline = performance.now() + attempt.waitMs;
    refresh();
  }, [refresh]);

  const finish = useCallback((id?: number) => {
    if (id !== undefined && current.current?.id !== id) return;
    current.current = null;
    clearTimer();
  }, [clearTimer]);

  const reset = useCallback(() => {
    finish();
    setState(idle);
  }, [finish]);

  useEffect(() => {
    mounted.current = true;
    refresh();
    // Background timer throttling must not give the attempt a new deadline.
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("pageshow", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      mounted.current = false;
      clearTimer();
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("pageshow", refresh);
      window.removeEventListener("focus", refresh);
      // Keep the deadline across StrictMode's effect cleanup/setup cycle.
    };
  }, [clearTimer, refresh]);

  return { ...state, begin, progress, finish, reset };
}
