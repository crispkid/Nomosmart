"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CreatedKnowledgeDocument as Document } from "../components/KnowledgeSourceModals";
import { listProjectDocuments, type ApiFetch, type DocumentSummary } from "./api";
import { extractionRunKey } from "./manualExtraction";
import { needsTerminalChunkCount, terminalCountScopeMatches, TerminalCountAttempts } from "./terminalChunkCount";

type Options = { projectId: string; enabled: boolean; documents: Document[]; apiFetch: ApiFetch;
  receive: (expected: Document, summary: DocumentSummary) => void };
type Read = { controller: AbortController; promise: Promise<DocumentSummary[]>; targets: Map<string, Document> };

export function useTerminalChunkCounts(options: Options) {
  const current = useRef(options);
  const attempts = useRef(new TerminalCountAttempts());
  const mounted = useRef(false);
  const read = useRef<Read | null>(null);
  const [states, setStates] = useState<Record<string, "pending" | "failed">>({});

  useEffect(() => { current.current = options; }, [options]);
  const request = useCallback((expected: Document, manual = false) => {
    const scope = current.current;
    const key = extractionRunKey(scope.projectId, expected);
    if (!scope.enabled || !key || !needsTerminalChunkCount(expected) || !attempts.current.begin(key, manual)) return;
    setStates((state) => ({ ...state, [key]: "pending" }));
    if (!read.current) {
      const controller = new AbortController();
      const promise = listProjectDocuments(scope.apiFetch, scope.projectId, controller.signal);
      read.current = { controller, promise, targets: new Map() };
    }
    const work = read.current;
    work.targets.set(key, expected);
    void work.promise.then((summaries) => {
      if (work.controller.signal.aborted || !work.targets.has(key) || !current.current.enabled
        || current.current.projectId !== scope.projectId
        || !current.current.documents.some((item) => terminalCountScopeMatches(item, expected))) return;
      const summary = summaries.find((item) => item.id === expected.id);
      if (summary) current.current.receive(expected, summary);
    }).catch(() => {
      // Existing terminal/progress remains truthful; only the count is unknown.
    }).finally(() => {
      attempts.current.finish(key);
      if (read.current === work) read.current = null;
      // A successful scoped merge hides this fallback. Missing/mismatched/null
      // summaries show a retry, rather than turning an initial zero into truth.
      if (mounted.current) setStates((state) => ({ ...state, [key]: "failed" }));
    });
  }, []);

  useEffect(() => {
    if (!options.enabled) {
      read.current?.controller.abort(); read.current = null;
      return;
    }
    const work = read.current;
    if (work) {
      for (const [key, expected] of work.targets) {
        if (!options.documents.some((item) => terminalCountScopeMatches(item, expected))) work.targets.delete(key);
      }
      if (!work.targets.size) { work.controller.abort(); read.current = null; }
    }
    for (const document of options.documents) request(document);
  }, [options, request]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; read.current?.controller.abort(); read.current = null; };
  }, []);

  return { retry: (document: Document) => request(document, true), state: (document: Document) => {
    if (!needsTerminalChunkCount(document)) return "known" as const;
    return states[extractionRunKey(options.projectId, document)!] ?? "pending";
  } };
}
