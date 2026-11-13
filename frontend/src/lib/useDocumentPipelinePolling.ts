"use client";

import { useEffect, useRef } from "react";
import type { CreatedKnowledgeDocument as Document } from "../components/KnowledgeSourceModals";
import { getPipelineDetail, type ApiFetch, type PipelineRunDetail } from "./api";
import { fileProcessingPollDelay, isPollingAuthorizationFailure } from "./fileProcessingPolling";
import { ReadResource } from "./readResource";
import { extractionRunKey, fileObservationMode, type PipelineObservationOwnership } from "./manualExtraction";
import { receiveUploadDocuments } from "./documentList";

type Options = {
  projectId: string;
  enabled: boolean;
  documents: Document[];
  apiFetch: ApiFetch;
  applyDetail: (document: Document, detail: PipelineRunDetail) => Document;
  receive: (documents: Document[]) => void;
  ownership: PipelineObservationOwnership;
};
type Observer = { document: Document; stop: () => void; active: () => boolean };

/** List-owned, GET-only observation. The upload modal owns observation while open. */
export function useDocumentPipelinePolling(options: Options) {
  const current = useRef(options);
  const observers = useRef(new Map<string, Observer>());
  const denied = useRef(new Set<string>());

  useEffect(() => {
    current.current = options;
    const active = new Map(options.enabled ? options.documents.flatMap((document) => {
      const key = extractionRunKey(options.projectId, document);
      return key && fileObservationMode(document) ? [[key, document] as const] : [];
    }) : []);
    for (const [key, observer] of observers.current) {
      const next = active.get(key);
      if (!next || !observer.active()) { observer.stop(); observers.current.delete(key); }
      else observer.document = next;
    }
    for (const [key, document] of active) {
      if (observers.current.has(key) || denied.current.has(key)) continue;
      const lease = options.ownership.acquire(key, "list");
      const cleanupBudget = options.ownership.cleanupBudget;
      const observer: Observer = { document, stop: lease.release, active: lease.active };
      const valid = () => lease.active() && current.current.enabled
        && !denied.current.has(key) && Boolean(fileObservationMode(observer.document))
        && current.current.documents.some((item) => extractionRunKey(current.current.projectId, item) === key
          && Boolean(fileObservationMode(item)));
      const publish = (next: Document) => {
        observer.document = next;
        current.current.receive([next]);
      };
      const stopCleanup = (next: Document) => {
        publish({ ...next, pipeline: { ...next.pipeline, observationInterrupted: true, cleanupObservationStopped: true } });
      };
      if (fileObservationMode(document) === "cleanup" && cleanupBudget.exhausted(key)) {
        stopCleanup(document);
        lease.release();
        continue;
      }
      // OPT424-035: each observer is a ReadResource: GET-only, one read at a time, aborted with the
      // ownership lease, first read after one polling interval, polling while the observation is valid.
      const handleError = (error: unknown) => {
        if (!valid()) return;
        const cleanup = fileObservationMode(observer.document) === "cleanup";
        const invalidContract = error instanceof Error && error.message === "file_processing_poll_contract_invalid";
        const next = { ...observer.document, pipeline: { ...observer.document.pipeline, observationInterrupted: true,
          cleanupObservationStopped: cleanup && (cleanupBudget.exhausted(key) || invalidContract || isPollingAuthorizationFailure(error)),
        } };
        if (isPollingAuthorizationFailure(error)) denied.current.add(key);
        publish(next);
      };
      const delay = () => fileProcessingPollDelay(observer.document.pipeline.execution, globalThis.document.visibilityState === "hidden");
      const load = (signal: AbortSignal) => {
        if (!valid()) return Promise.reject(new DOMException("Observation inactive", "AbortError"));
        if (fileObservationMode(observer.document) === "cleanup" && !cleanupBudget.take(key)) {
          return Promise.reject(new Error("pipeline_cleanup_observation_exhausted"));
        }
        return getPipelineDetail(current.current.apiFetch, options.projectId,
          document.id, document.latestVersionId!, document.pipeline.id!, AbortSignal.any([lease.signal, signal]));
      };
      let begun = false;
      const resource = new ReadResource<PipelineRunDetail>({
        onStart: () => { begun = true; },
        onData: (detail) => {
          if (!valid()) return;
          if (detail.project_id !== options.projectId || detail.document_id !== document.id
            || detail.id !== document.pipeline.id || detail.document_version_id !== document.latestVersionId) {
            handleError(new Error("pipeline_observation_scope_mismatch"));
            return;
          }
          const candidate = current.current.applyDetail(observer.document, detail);
          // An older terminal response must not stop an observer of newer work.
          const next = receiveUploadDocuments({ live: [observer.document], created: [] }, [candidate]).live[0];
          if (fileObservationMode(next) === "cleanup" && cleanupBudget.exhausted(key)) stopCleanup(next);
          else publish(next);
        },
        onError: (error) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          handleError(error);
        },
        poll: (outcome) => {
          if ("error" in outcome && isPollingAuthorizationFailure(outcome.error)) return null;
          if (!valid()) return null;
          try { return delay(); } catch (error) { handleError(error); return null; }
        },
      });
      const begin = () => {
        if (!valid()) return;
        try { resource.start(load, delay()); } catch (error) { handleError(error); }
      };
      const visibility = () => { if (begun) resource.schedule(); else begin(); };
      globalThis.document.addEventListener("visibilitychange", visibility);
      begin();
      const stop = () => { resource.dispose(); globalThis.document.removeEventListener("visibilitychange", visibility); };
      lease.signal.addEventListener("abort", stop, { once: true });
      observer.stop = () => { stop(); lease.release(); };
      observers.current.set(key, observer);
    }
  }, [options]);

  useEffect(() => {
    const entries = observers.current;
    const blocked = denied.current;
    return () => {
      for (const observer of entries.values()) observer.stop();
      entries.clear();
      blocked.clear();
    };
  }, []);
}
