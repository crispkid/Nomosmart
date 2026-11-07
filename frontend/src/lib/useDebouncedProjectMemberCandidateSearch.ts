import { useEffect, useRef, useState } from "react";

import type { ProjectMemberCandidatePage } from "@/lib/api";


type CandidateSearchPhase = "idle" | "waiting" | "loading" | "ready" | "error";

type CandidateSearchState = {
  phase: CandidateSearchPhase;
  result: ProjectMemberCandidatePage | null;
  error: Error | null;
};

type InternalCandidateSearchState = CandidateSearchState & { query: string };

type CandidateSearchOptions = {
  enabled: boolean;
  query: string;
  search: (query: string, signal: AbortSignal) => Promise<ProjectMemberCandidatePage>;
  delayMs?: number;
};

const idleState: CandidateSearchState = { phase: "idle", result: null, error: null };


export function useDebouncedProjectMemberCandidateSearch({
  enabled,
  query,
  search,
  delayMs = 300,
}: CandidateSearchOptions): CandidateSearchState {
  const normalizedQuery = query.trim();
  const [state, setState] = useState<InternalCandidateSearchState>({ ...idleState, query: "" });
  const requestSequence = useRef(0);

  useEffect(() => {
    const sequence = ++requestSequence.current;
    if (!enabled || !normalizedQuery) {
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      if (sequence !== requestSequence.current || controller.signal.aborted) return;
      setState({ query: normalizedQuery, phase: "loading", result: null, error: null });
      void search(normalizedQuery, controller.signal).then((result) => {
        if (sequence !== requestSequence.current || controller.signal.aborted) return;
        setState({ query: normalizedQuery, phase: "ready", result, error: null });
      }).catch((error: unknown) => {
        if (sequence !== requestSequence.current || controller.signal.aborted) return;
        setState({ query: normalizedQuery, phase: "error", result: null, error: error instanceof Error ? error : new Error("Project member candidate search failed") });
      });
    }, delayMs);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [delayMs, enabled, normalizedQuery, search]);

  if (!enabled || !normalizedQuery) return idleState;
  if (state.query !== normalizedQuery) return { phase: "waiting", result: null, error: null };
  return state;
}
